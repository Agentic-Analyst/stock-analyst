import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from analyst_consensus import FinnhubConsensusClient, collect_consensus, yahoo_snapshot


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
