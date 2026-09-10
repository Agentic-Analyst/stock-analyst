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
