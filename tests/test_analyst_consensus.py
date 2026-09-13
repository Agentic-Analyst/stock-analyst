import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import analyst_consensus
from analyst_consensus import (
    BenzingaConsensusClient,
    FinnhubConsensusClient,
    TipRanksConsensusClient,
    collect_consensus,
    yahoo_snapshot,
)
from report_agent import extract_company_overview


class Response:
    def __init__(self, payload, *, error=False):
        self.payload, self.error = payload, error

    def raise_for_status(self):
        if self.error:
            raise RuntimeError("denied")

    def json(self):
        return self.payload


class Session:
    def __init__(self, responses):
        self.responses, self.calls = responses, []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses[url.rsplit("/", 1)[-1]]


class StaticClient:
    def __init__(self, payload):
        self.payload, self.calls = payload, []

    def fetch(self, ticker, *, currency=None):
        self.calls.append((ticker, currency))
        return self.payload


class McpResponse:
    def __init__(self, payload=None, *, text=None, headers=None, error=False):
        self.text = text if text is not None else json.dumps(payload or {})
        self.headers = headers or {"content-type": "application/json"}
        self.error = error

    def raise_for_status(self):
        if self.error:
            raise RuntimeError("denied")


class McpSession:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


YAHOO = {
    "target_mean_price": 210.0,
    "target_median_price": 205.0,
    "target_high_price": 260.0,
    "target_low_price": 150.0,
    "recommendation_key": "buy",
    "recommendation_mean": 1.8,
    "number_of_analyst_opinions": 42,
}


def test_report_publication_uses_normalized_primary_not_stale_legacy_mirror():
    data = {
        "ticker": "AAPL",
        "company_data": {
            "basic_info": {}, "market_data": {}, "valuation_metrics": {},
            "capital_structure": {}, "growth_profitability": {},
            "forward_guidance": {
                "target_mean_price": 100.0,
                "number_of_analyst_opinions": 2,
                "recommendation_key": "sell",
            },
            "analyst_consensus": {
                "price_target": {"mean": 210.0, "high": 240.0, "low": 180.0,
                                 "analyst_count": 20, "source": "benzinga"},
                "recommendation": {"label": "buy", "source": "benzinga"},
            },
        },
        "market_data": {},
    }
    company = extract_company_overview(data)
    assert company["target_mean_price"] == 210.0
    assert company["target_high_price"] == 240.0
    assert company["target_low_price"] == 180.0
    assert company["num_analysts"] == 20
    assert company["recommendation"] == "buy"


def test_yahoo_fields_are_normalized_with_provenance():
    out = yahoo_snapshot(YAHOO, currency="USD")
    assert out["price_target"]["mean"] == 210.0
    assert out["price_target"]["analyst_count"] == 42
    assert out["price_target"]["source"] == "yahoo_finance"
    assert out["captured_at"]
    assert out["recommendation"]["analyst_count"] == 0
    assert out["recommendation"]["coverage_count_available"] is False


def test_finnhub_uses_header_auth_and_normalizes_counts():
    session = Session({
        "price-target": Response({"targetMean": 220, "targetMedian": 215,
                                  "targetHigh": 280, "targetLow": 160,
                                  "numberAnalysts": 35, "lastUpdated": "2026-09-09"}),
        "recommendation": Response([
            {"period": "2026-08-01", "strongBuy": 1, "buy": 2, "hold": 3,
             "sell": 4, "strongSell": 5},
            {"period": "2026-09-01", "strongBuy": 10, "buy": 20, "hold": 5,
             "sell": 1, "strongSell": 0},
        ]),
    })
    out = FinnhubConsensusClient("secret", session=session).fetch("aapl", currency="USD")
    assert out["price_target"]["mean"] == 220.0
    assert out["recommendation"]["period"] == "2026-09-01"
    assert out["recommendation"]["label"] == "strong_buy"
    assert out["recommendation"]["total"] == 36
    assert all(call[1]["headers"] == {"X-Finnhub-Token": "secret"} for call in session.calls)
    assert all("secret" not in call[0] for call in session.calls)


def test_benzinga_consensus_is_normalized_with_unique_analyst_count():
    session = Session({
        # Some plans expose only the aggregate endpoint. It remains a usable
        # caution benchmark, but cannot inherit freshness from updated_at.
        "insights": Response({}, error=True),
        "ratings": Response({}, error=True),
        "consensus-ratings": Response({
            "aggregate_ratings": {
                "strong_buy": 7, "buy": 12, "hold": 5, "sell": 2,
            },
            "consensus_price_target": 293.69,
            "consensus_rating": "BUY",
            "consensus_rating_val": 3.92,
            "high_price_target": 350,
            "low_price_target": 200,
            "total_analyst_count": 50,
            "unique_analyst_count": 26,
            "updated_at": "2026-09-10T20:00:00Z",
        }),
    })

    out = BenzingaConsensusClient(
        "secret", session=session,
        clock=lambda: analyst_consensus.datetime(
            2026, 9, 11, tzinfo=analyst_consensus.timezone.utc),
    ).fetch(
        "aapl", currency="USD")

    assert out["price_target"] == {
        "mean": 293.69,
        "median": None,
        "high": 350.0,
        "low": 200.0,
        "analyst_count": 26,
        "coverage_unit": "provider_unique_analysts",
        "currency": "USD",
        "as_of": None,
        "aggregate_calculated_at": "2026-09-10T20:00:00Z",
        "source": "benzinga",
    }
    assert out["recommendation"]["label"] == "buy"
    assert out["recommendation"]["unique_analyst_count"] == 26
    assert out["recommendation"]["total_rating_count"] == 50
    assert out["recommendation"]["aggregate_calculated_at"] == "2026-09-10T20:00:00Z"
    assert out["partial_errors"] == [
        "analyst_insights:RuntimeError", "dated_ratings:RuntimeError",
    ]
    params = session.calls[2][1]["params"]
    assert params["token"] == "secret"
    assert params["parameters[tickers]"] == "AAPL"
    assert params["parameters[date_from]"] == "2025-09-11"
    assert params["parameters[date_to]"] == "2026-09-11"
    # Benzinga applies pagesize before aggregating. ``pagesize=1`` therefore
    # produced a convincing-looking "consensus" from one analyst instead of
    # the full rating population (verified live on AAPL: 1 versus 24 unique
    # analysts). The one-ticker filter already guarantees one response object.
    assert "pagesize" not in params
    assert "secret" not in session.calls[0][0]

    from report_agent import build_analyst_consensus_table
    table = build_analyst_consensus_table({
        "source_snapshots": {"benzinga": {
            "captured_at": out["captured_at"],
            "price_target": out["price_target"],
            "recommendation": out["recommendation"],
        }},
    })
    assert "Provider As Of" in table
    assert "| N/A |" in table
    assert "not the provider as-of date" in table


def test_benzinga_dated_records_are_deduplicated_before_consensus():
    session = Session({
        "insights": Response({"analyst-insights": [
            {
                "id": "old-insight", "date": "2026-08-01",
                "analyst_id": "a1", "firm": "Firm One", "firm_id": "f1",
                "action": "Maintains", "rating": "Buy", "pt": "200",
                "analyst_insights": "Earlier rationale.",
                "security": {"symbol": "AAPL"}, "updated": 1,
            },
            {
                "id": "new-insight", "date": "2026-09-10",
                "analyst_id": "a1", "firm": "Firm One", "firm_id": "f1",
                "action": "Raises", "rating": "Strong Buy", "pt": "220",
                "analyst_insights": "Demand and margins support the revised view.",
                "security": {"symbol": "AAPL"}, "updated": 2,
            },
            # Wrong-symbol evidence must never enter AAPL's prompt/artifact.
            {
                "id": "wrong", "date": "2026-09-10",
                "analyst_id": "a9", "firm": "Other", "rating": "Sell",
                "analyst_insights": "Unrelated.",
                "security": {"symbol": "MSFT"},
            },
        ]}),
        "ratings": Response({"ratings": [
            {"id": "old-a1", "ticker": "AAPL", "date": "2026-08-01",
             "time": "10:00:00", "analyst_id": "a1", "firm_id": "f1",
             "currency": "USD", "pt_current": "200", "rating_current": "Buy"},
            {"id": "new-a1", "ticker": "AAPL", "date": "2026-09-10",
             "time": "10:00:00", "analyst_id": "a1", "firm_id": "f1",
             "currency": "USD", "pt_current": "220", "rating_current": "Strong Buy"},
            {"id": "a2", "ticker": "AAPL", "date": "2026-09-09",
             "time": "10:00:00", "analyst_id": "a2", "firm_id": "f2",
             "currency": "USD", "pt_current": "180", "rating_current": "Hold"},
            # The rating is still usable, but the foreign-currency target is not.
            {"id": "a3", "ticker": "AAPL", "date": "2026-09-08",
             "time": "10:00:00", "analyst_id": "a3", "firm_id": "f3",
             "currency": "EUR", "pt_current": "300", "rating_current": "Sell"},
        ]}),
    })
    out = BenzingaConsensusClient(
        "secret", session=session,
        clock=lambda: analyst_consensus.datetime(
            2026, 9, 11, tzinfo=analyst_consensus.timezone.utc),
    ).fetch("aapl", currency="USD")

    assert len(session.calls) == 2
    assert session.calls[0][0].endswith("/analyst/insights")
    assert session.calls[1][0].endswith("/calendar/ratings")
    assert out["window"]["records_received"] == 4
    assert out["window"]["unique_analyst_firm_records"] == 3
    assert out["price_target"] == {
        "mean": 200.0,
        "median": 200.0,
        "high": 220.0,
        "low": 180.0,
        "analyst_count": 2,
        "coverage_unit": "latest_analyst_firm_target_observations",
        "currency": "USD",
        "as_of": "2026-09-10",
        "oldest_observation_as_of": "2026-09-09",
        "source": "benzinga",
        "source_endpoint": "dated_ratings",
    }
    assert out["recommendation"]["total"] == 3
    assert out["recommendation"]["label"] == "buy"
    assert out["recommendation"]["period"] == "2026-09-10"
    observations = out["analyst_observations"]
    assert observations["observation_count"] == 1
    assert observations["as_of"] == "2026-09-10"
    assert observations["observations"][0]["firm"] == "Firm One"
    assert observations["observations"][0]["rating"] == "strong_buy"
    assert observations["observations"][0]["price_target"] == 220.0
    assert "insight" not in observations["observations"][0]
    assert observations["included_in_intrinsic_value"] is False
    serialized = json.dumps(out)
    assert "Demand and margins support the revised view" not in serialized
    assert "Earlier rationale" not in serialized
    assert "Unrelated" not in serialized


def test_benzinga_observations_survive_when_yahoo_wins_numerical_consensus(monkeypatch):
    benzinga = StaticClient({
        "captured_at": "2026-09-11T23:00:00Z",
        "providers": ["benzinga"],
        "price_target": {"mean": 400.0, "analyst_count": 1,
                         "currency": "USD", "source": "benzinga"},
        "analyst_observations": {
            "source": "benzinga", "observation_count": 1,
            "as_of": "2026-09-10", "observations": [{
                "date": "2026-09-10", "firm": "Firm One",
                "rating": "buy", "source": "benzinga",
            }],
        },
    })
    monkeypatch.setenv("ANALYST_CONSENSUS_PROVIDER", "auto")
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)

    out = collect_consensus(
        "AAPL", YAHOO, currency="USD", benzinga_client=benzinga)

    assert out["price_target"]["source"] == "yahoo_finance"
    assert out["analyst_observations"]["source"] == "benzinga"
    assert out["analyst_observations"]["observation_count"] == 1
    assert out["source_snapshots"]["benzinga"]["analyst_observations"]


def test_dated_insight_observation_sample_beats_undated_benzinga_aggregate():
    insight_rows = []
    for index, (target, rating) in enumerate((
        (300, "Buy"), (320, "Buy"), (340, "Strong Buy"),
        (280, "Hold"), (360, "Buy"), (310, "Buy"),
    ), start=1):
        insight_rows.append({
            "id": f"i{index}", "date": f"2026-09-{index:02d}",
            "analyst_id": f"a{index}", "firm": f"Firm {index}",
            "firm_id": f"f{index}", "action": "Maintains",
            "rating": rating, "pt": str(target),
            "analyst_insights": f"Rationale {index}.",
            "security": {"symbol": "AAPL"}, "updated": index,
        })
    session = Session({
        "insights": Response({"analyst-insights": insight_rows}),
        "ratings": Response({}, error=True),
        "consensus-ratings": Response({
            "consensus_price_target": 250,
            "high_price_target": 400,
            "low_price_target": 150,
            "unique_analyst_count": 26,
            "total_analyst_count": 50,
            "consensus_rating": "Hold",
            "updated_at": "2026-09-11T20:00:00Z",
        }),
    })

    out = BenzingaConsensusClient(
        "secret", session=session,
        clock=lambda: analyst_consensus.datetime(
            2026, 9, 12, tzinfo=analyst_consensus.timezone.utc),
    ).fetch("AAPL", currency="USD")

    assert out["price_target"]["mean"] == 318.3333333333333
    assert out["price_target"]["analyst_count"] == 6
    assert out["price_target"]["as_of"] == "2026-09-06"
    assert out["price_target"]["oldest_observation_as_of"] == "2026-09-01"
    assert out["price_target"]["coverage_unit"] == (
        "latest_analyst_insight_target_observations"
    )
    assert out["recommendation"]["total"] == 6
    assert out["recommendation"]["period"] == "2026-09-06"
    assert out["analyst_observations"]["unique_analyst_records"] == 6
    assert out["analyst_observations"]["undated_aggregate_price_target"]["mean"] == 250
    assert out["analyst_observations"]["undated_aggregate_recommendation"]["label"] == "hold"


def test_auto_prefers_benzinga_without_spending_fallback_calls(monkeypatch):
    benzinga = StaticClient({
        "captured_at": "2026-09-10T20:00:00Z",
        "providers": ["benzinga"],
        "price_target": {"mean": 225.0, "analyst_count": 20,
                         "currency": "USD", "source": "benzinga"},
        "recommendation": {"label": "buy", "unique_analyst_count": 20,
                           "source": "benzinga"},
    })
    finnhub = StaticClient({"providers": ["finnhub"]})
    tipranks = StaticClient({"providers": ["tipranks"]})
    monkeypatch.setenv("ANALYST_CONSENSUS_PROVIDER", "auto")
    monkeypatch.delenv("ANALYST_CONSENSUS_SECONDARY", raising=False)

    out = collect_consensus(
        "AAPL", YAHOO, currency="USD", client=finnhub,
        benzinga_client=benzinga, tipranks_client=tipranks)

    assert out["price_target"]["source"] == "benzinga"
    assert out["providers"] == ["benzinga", "yahoo_finance"]
    assert len(benzinga.calls) == 1
    assert finnhub.calls == []
    assert tipranks.calls == []
    assert out["provider_status"]["benzinga"]["meets_minimum_coverage"] is True
    assert out["provider_status"]["benzinga"]["price_target_eligible"] is True
    assert out["provider_status"]["benzinga"]["recommendation_eligible"] is True
    assert out["provider_status"]["finnhub"]["attempted"] is False
    assert out["provider_status"]["finnhub"]["configured"] is True


def test_undercovered_benzinga_snapshot_cannot_replace_broad_yahoo_consensus(monkeypatch):
    benzinga = StaticClient({
        "captured_at": "2026-09-11T23:00:00Z",
        "providers": ["benzinga"],
        "price_target": {"mean": 400.0, "analyst_count": 1,
                         "currency": "USD", "source": "benzinga"},
        "recommendation": {"label": "buy", "unique_analyst_count": 1,
                           "source": "benzinga"},
    })
    monkeypatch.setenv("ANALYST_CONSENSUS_PROVIDER", "auto")
    monkeypatch.setenv("ANALYST_CONSENSUS_MIN_ANALYSTS", "3")
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)

    out = collect_consensus(
        "AAPL", YAHOO, currency="USD", benzinga_client=benzinga)

    assert out["price_target"]["mean"] == 210.0
    assert out["price_target"]["source"] == "yahoo_finance"
    assert out["providers"] == ["yahoo_finance", "benzinga"]
    assert out["source_snapshots"]["benzinga"]["price_target"]["mean"] == 400.0
    assert out["provider_status"]["benzinga"]["usable"] is True
    assert out["provider_status"]["benzinga"]["meets_minimum_coverage"] is False


def test_section_coverage_cannot_borrow_from_well_covered_other_section(monkeypatch):
    benzinga = StaticClient({
        "captured_at": "2026-09-11T23:00:00Z",
        "providers": ["benzinga"],
        "price_target": {"mean": 400.0, "analyst_count": 1,
                         "currency": "USD", "source": "benzinga"},
        "recommendation": {"label": "buy", "unique_analyst_count": 24,
                           "total_rating_count": 50, "source": "benzinga"},
    })
    finnhub = StaticClient({
        "captured_at": "2026-09-11T23:00:00Z",
        "providers": ["finnhub"],
        "recommendation": {"label": "strong_buy", "total": 53,
                           "source": "finnhub"},
    })
    monkeypatch.setenv("ANALYST_CONSENSUS_PROVIDER", "auto")
    monkeypatch.setenv("ANALYST_CONSENSUS_MIN_ANALYSTS", "3")

    out = collect_consensus(
        "AAPL", YAHOO, currency="USD", client=finnhub,
        benzinga_client=benzinga)

    # The 24-person recommendation population does not make Benzinga's
    # one-person target primary. Yahoo's 42-person target wins that section,
    # while Benzinga remains the preferred qualified recommendation source.
    assert out["price_target"]["source"] == "yahoo_finance"
    assert out["price_target"]["mean"] == 210.0
    assert out["recommendation"]["source"] == "benzinga"
    assert out["provider_status"]["benzinga"]["price_target_eligible"] is False
    assert out["provider_status"]["benzinga"]["recommendation_eligible"] is True
    assert len(finnhub.calls) == 1
    assert out["source_snapshots"]["benzinga"]["price_target"]["mean"] == 400.0


def test_tipranks_mcp_is_normalized_and_one_call_per_worker_is_enforced(monkeypatch):
    monkeypatch.setenv("TIPRANKS_MAX_CALLS_PER_WORKER", "1")
    monkeypatch.setattr(analyst_consensus, "_tipranks_calls", 0)
    assets = {"assetsData": [{
        "ticker": "AAPL",
        "analystConsensus": "Moderate Buy",
        "priceTarget": 335.87,
        "url": "https://www.tipranks.com/stocks/aapl",
    }]}
    session = McpSession([
        McpResponse({"jsonrpc": "2.0", "id": 1, "result": {"serverInfo": {}}}),
        McpResponse(text="", headers={}),
        McpResponse({
            "jsonrpc": "2.0", "id": 2,
            "result": {"content": [{"type": "text", "text": json.dumps(assets)}],
                       "isError": False},
        }),
    ])
    client = TipRanksConsensusClient("secret", session=session)

    out = client.fetch("aapl", currency="USD")

    assert out["price_target"]["mean"] == 335.87
    assert out["price_target"]["analyst_count"] == 0
    assert out["recommendation"]["label"] == "buy"
    assert out["price_target"]["source_url"].endswith("/aapl")
    assert client.fetch("MSFT", currency="USD") == {}
    assert len(session.calls) == 3
    assert all(call[1]["params"] == {"apikey": "secret"} for call in session.calls)


def test_explicit_tipranks_secondary_is_evidence_not_the_primary_target(monkeypatch):
    benzinga = StaticClient({
        "captured_at": "2026-09-10T20:00:00Z",
        "providers": ["benzinga"],
        "price_target": {"mean": 225.0, "analyst_count": 20,
                         "currency": "USD", "source": "benzinga"},
        "recommendation": {"label": "buy", "source": "benzinga"},
    })
    tipranks = StaticClient({
        "captured_at": "2026-09-10T20:00:00Z",
        "providers": ["tipranks"],
        "price_target": {"mean": 235.0, "analyst_count": 0,
                         "currency": "USD", "source": "tipranks"},
        "recommendation": {"label": "hold", "source": "tipranks"},
    })
    monkeypatch.setenv("ANALYST_CONSENSUS_PROVIDER", "auto")
    monkeypatch.setenv("ANALYST_CONSENSUS_SECONDARY", "tipranks")
    monkeypatch.setenv("TIPRANKS_DURABLE_OUTPUTS_LICENSED", "true")

    out = collect_consensus(
        "AAPL", YAHOO, currency="USD",
        benzinga_client=benzinga, tipranks_client=tipranks)

    assert out["price_target"]["mean"] == 225.0
    assert out["providers"] == ["benzinga", "yahoo_finance", "tipranks"]
    assert out["source_snapshots"]["tipranks"]["price_target"]["mean"] == 235.0
    assert out["source_comparison"]["recommendation"]["directional_agreement"] is False


def test_tipranks_is_not_fetched_for_durable_outputs_without_contract_flag(monkeypatch):
    tipranks = StaticClient({"providers": ["tipranks"]})
    monkeypatch.setenv("ANALYST_CONSENSUS_PROVIDER", "tipranks")
    monkeypatch.delenv("TIPRANKS_DURABLE_OUTPUTS_LICENSED", raising=False)
    monkeypatch.delenv("BENZINGA_API_KEY", raising=False)
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)

    out = collect_consensus("AAPL", YAHOO, currency="USD", tipranks_client=tipranks)

    assert tipranks.calls == []
    assert out["providers"] == ["yahoo_finance"]


def test_denied_price_target_keeps_recommendations_and_yahoo_target(monkeypatch):
    session = Session({
        "price-target": Response({}, error=True),
        "recommendation": Response([
            {"period": "2026-09-01", "strongBuy": 0, "buy": 1, "hold": 8,
             "sell": 1, "strongSell": 0},
        ]),
    })
    monkeypatch.setenv("ANALYST_CONSENSUS_PROVIDER", "finnhub")
    out = collect_consensus(
        "AAPL", YAHOO, currency="USD",
        client=FinnhubConsensusClient("secret", session=session))
    assert out["price_target"]["source"] == "yahoo_finance"
    assert out["recommendation"]["source"] == "finnhub"
    assert out["providers"] == ["finnhub", "yahoo_finance"]


def test_two_provider_snapshots_stay_separate_and_report_disagreement(monkeypatch):
    session = Session({
        "price-target": Response({"targetMean": 220, "targetMedian": 215,
                                  "targetHigh": 280, "targetLow": 160,
                                  "numberAnalysts": 35, "lastUpdated": "2026-09-09"}),
        "recommendation": Response([
            {"period": "2026-09-01", "strongBuy": 10, "buy": 20, "hold": 5,
             "sell": 1, "strongSell": 0},
        ]),
    })
    monkeypatch.setenv("ANALYST_CONSENSUS_PROVIDER", "finnhub")
    out = collect_consensus(
        "AAPL", YAHOO, currency="USD", quote_currency="USD",
        client=FinnhubConsensusClient("secret", session=session))

    assert out["price_target"]["mean"] == 220.0  # explicit primary; never averaged
    assert out["source_snapshots"]["finnhub"]["price_target"]["mean"] == 220.0
    assert out["source_snapshots"]["yahoo_finance"]["price_target"]["mean"] == 210.0
    price = out["source_comparison"]["price_target"]
    assert price["source_count"] == 2
    assert price["mean_target_spread_pct"] == 4.65
    recommendation = out["source_comparison"]["recommendation"]
    assert recommendation["exact_agreement"] is False
    assert recommendation["directional_agreement"] is True


def test_no_provider_network_is_required_without_a_key(monkeypatch):
    monkeypatch.setenv("ANALYST_CONSENSUS_PROVIDER", "auto")
    monkeypatch.delenv("BENZINGA_API_KEY", raising=False)
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    assert collect_consensus("AAPL", YAHOO)["providers"] == ["yahoo_finance"]


def test_provider_can_be_disabled(monkeypatch):
    monkeypatch.setenv("ANALYST_CONSENSUS_PROVIDER", "none")
    assert collect_consensus("AAPL", YAHOO) == {}


def test_yahoo_quote_targets_are_converted_to_the_model_currency(monkeypatch):
    import src.financial_scraper as scraper

    monkeypatch.setattr(
        scraper, "_fx_rate",
        lambda source, target: 1.35 if (source, target) == ("GBP", "USD") else None)
    info = {"currency": "GBp", "financialCurrency": "USD"}
    assert scraper._analyst_target_in_financial_currency(4000.0, info) == 54.0


def test_each_provider_snapshot_is_currency_normalized_before_comparison(monkeypatch):
    import src.financial_scraper as scraper

    session = Session({
        "price-target": Response({"targetMean": 220, "targetHigh": 260,
                                  "targetLow": 180, "numberAnalysts": 20}),
        "recommendation": Response([]),
    })
    monkeypatch.setenv("ANALYST_CONSENSUS_PROVIDER", "finnhub")
    out = collect_consensus(
        "SHEL.L", YAHOO, currency="USD", quote_currency="GBP",
        client=FinnhubConsensusClient("secret", session=session))
    company = {
        "basic_info": {"listing_currency": "GBP", "currency": "USD"},
        "market_data": {"fx_listing_to_financial": 1.35},
    }

    normalized = scraper._convert_consensus_prices(out, company)
    assert normalized["price_target"]["mean"] == 297.0
    assert normalized["source_snapshots"]["finnhub"]["price_target"]["mean"] == 297.0
    assert normalized["source_snapshots"]["yahoo_finance"]["price_target"]["mean"] == 210.0
    assert set(normalized["source_comparison"]["price_target"]["currency_by_source"].values()) == {"USD"}


def test_missing_fx_never_relabels_an_unconverted_target():
    import src.financial_scraper as scraper

    consensus = {
        "price_target": {
            "mean": 220.0, "currency": "GBP", "source": "finnhub",
        },
        "source_snapshots": {"finnhub": {"price_target": {
            "mean": 220.0, "currency": "GBP", "source": "finnhub",
        }}},
    }
    company = {
        "basic_info": {"listing_currency": "GBP", "currency": "USD"},
        "market_data": {"fx_listing_to_financial": None},
    }

    normalized = scraper._convert_consensus_prices(consensus, company)

    assert normalized["price_target"]["mean"] == 220.0
    assert normalized["price_target"]["currency"] == "GBP"
    assert normalized["source_snapshots"]["finnhub"]["price_target"][
        "currency"
    ] == "GBP"


def test_unexpected_provider_currency_is_preserved_for_policy_rejection():
    import src.financial_scraper as scraper

    consensus = {"price_target": {
        "mean": 220.0, "currency": "EUR", "source": "finnhub",
    }}
    company = {
        "basic_info": {"listing_currency": "USD", "currency": "USD"},
        "market_data": {},
    }

    normalized = scraper._convert_consensus_prices(consensus, company)

    assert normalized["price_target"]["currency"] == "EUR"


def test_report_renders_provider_targets_without_blending_them(monkeypatch):
    from src.report_agent import build_analyst_consensus_table

    session = Session({
        "price-target": Response({"targetMean": 220, "targetMedian": 215,
                                  "targetHigh": 280, "targetLow": 160,
                                  "numberAnalysts": 35, "lastUpdated": "2026-09-09"}),
        "recommendation": Response([
            {"period": "2026-09-01", "strongBuy": 10, "buy": 20, "hold": 5,
             "sell": 1, "strongSell": 0},
        ]),
    })
    monkeypatch.setenv("ANALYST_CONSENSUS_PROVIDER", "finnhub")
    consensus = collect_consensus(
        "AAPL", YAHOO, currency="USD", quote_currency="USD",
        client=FinnhubConsensusClient("secret", session=session))
    table = build_analyst_consensus_table(consensus)

    assert "| Finnhub | $220.00 USD |" in table
    assert "| Yahoo Finance | $210.00 USD |" in table
    assert "provider mean-target spread is 4.7%" in table
    assert "kept separate and excluded from intrinsic value" in table


def test_report_attributes_tipranks_secondary(monkeypatch):
    from src.report_agent import build_analyst_consensus_table

    benzinga = StaticClient({
        "captured_at": "2026-09-10T20:00:00Z",
        "providers": ["benzinga"],
        "price_target": {"mean": 225.0, "analyst_count": 20,
                         "currency": "USD", "source": "benzinga"},
        "recommendation": {"label": "buy", "source": "benzinga"},
    })
    tipranks = StaticClient({
        "captured_at": "2026-09-10T20:00:00Z",
        "providers": ["tipranks"],
        "price_target": {"mean": 235.0, "analyst_count": 0,
                         "currency": "USD", "source": "tipranks"},
        "recommendation": {"label": "hold", "source": "tipranks"},
    })
    monkeypatch.setenv("ANALYST_CONSENSUS_PROVIDER", "auto")
    monkeypatch.setenv("ANALYST_CONSENSUS_SECONDARY", "tipranks")
    monkeypatch.setenv("TIPRANKS_DURABLE_OUTPUTS_LICENSED", "true")
    consensus = collect_consensus(
        "AAPL", YAHOO, currency="USD",
        benzinga_client=benzinga, tipranks_client=tipranks)

    table = build_analyst_consensus_table(consensus)

    assert "| TipRanks | $235.00 USD |" in table
    assert "Data by TipRanks" in table


def test_default_primary_coverage_floor_matches_publication_floor(monkeypatch):
    monkeypatch.delenv("ANALYST_CONSENSUS_MIN_ANALYSTS", raising=False)
    assert analyst_consensus._minimum_analysts() == 5


def test_primary_coverage_floor_cannot_be_configured_below_publication_floor(monkeypatch):
    monkeypatch.setenv("ANALYST_CONSENSUS_MIN_ANALYSTS", "1")
    assert analyst_consensus._minimum_analysts() == 5
