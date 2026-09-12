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


def test_yahoo_fields_are_normalized_with_provenance():
    out = yahoo_snapshot(YAHOO, currency="USD")
    assert out["price_target"]["mean"] == 210.0
    assert out["price_target"]["analyst_count"] == 42
    assert out["price_target"]["source"] == "yahoo_finance"
    assert out["captured_at"]


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
        "currency": "USD",
        "as_of": "2026-09-10T20:00:00Z",
        "source": "benzinga",
    }
    assert out["recommendation"]["label"] == "buy"
    assert out["recommendation"]["unique_analyst_count"] == 26
    assert out["recommendation"]["total_rating_count"] == 50
    params = session.calls[0][1]["params"]
    assert params["token"] == "secret"
    assert params["parameters[tickers]"] == "AAPL"
    assert params["parameters[date_from]"] == "2025-09-11"
    assert params["parameters[date_to]"] == "2026-09-11"
    assert "secret" not in session.calls[0][0]


def test_auto_prefers_benzinga_without_spending_fallback_calls(monkeypatch):
    benzinga = StaticClient({
        "captured_at": "2026-09-10T20:00:00Z",
        "providers": ["benzinga"],
        "price_target": {"mean": 225.0, "analyst_count": 20,
                         "currency": "USD", "source": "benzinga"},
        "recommendation": {"label": "buy", "source": "benzinga"},
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
