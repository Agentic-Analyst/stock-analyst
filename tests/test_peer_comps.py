import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from peer_comps import collect_peer_comps


class Client:
    def peers(self, ticker):
        return [ticker, "MSFT", "GOOG", "DELL", "HPQ", "MSFT"]

    def metrics(self, ticker):
        return {
            # Current Finnhub /stock/metric field spelling.
            "MSFT": {"evEbitdaTTM": 24.0, "priceToSalesTTM": 9.0},
            "GOOG": {"currentEv/ebitdaTTM": 18.0, "psTTM": 7.0},
            "DELL": {"enterpriseValueOverEBITDATTM": 12.0, "price/salesTTM": 1.0},
            "HPQ": {"evToEbitdaTTM": -1.0, "priceToSalesTTM": 0.6},
        }[ticker]


def test_real_peer_medians_exclude_the_subject_and_deduplicate():
    out = collect_peer_comps("AAPL", client=Client(), max_peers=10)
    assert out["requested_peers"] == ["MSFT", "GOOG", "DELL", "HPQ"]
    assert out["median_ev_ebitda"] == 18.0
    assert out["median_price_sales"] == 4.0
    assert out["ev_ebitda_peer_count"] == 3
    assert out["source"] == "finnhub"


def test_too_few_observations_do_not_create_a_fake_comps_view():
    class Sparse(Client):
        def peers(self, ticker):
            return ["A", "B"]

        def metrics(self, ticker):
            return {"evToEbitdaTTM": 10.0}

    assert collect_peer_comps("X", client=Sparse()) == {}


def test_feature_is_off_by_default_without_an_injected_client(monkeypatch):
    monkeypatch.delenv("PEER_COMPS_ENABLED", raising=False)
    assert collect_peer_comps("AAPL") == {}


def test_grounding_prefers_real_peer_median_over_self_multiple(monkeypatch):
    from src.agents.fm.assumption_grounding import ground_assumptions

    monkeypatch.setenv("RISK_FREE_USD", "0.04")
    data = {
        "company_data": {
            "basic_info": {"currency": "USD", "country": "United States"},
            "capital_structure": {"beta": 1.0, "total_debt": 0},
            "market_data": {"market_cap": 1e9},
            "valuation_metrics": {
                "enterprise_to_ebitda": 30.0,
                "price_to_sales": 10.0,
            },
        },
        "industry_data": {"peer_comps": {
            "source": "finnhub",
            "median_ev_ebitda": 14.0,
            "median_price_sales": 4.0,
            "ev_ebitda_peer_count": 5,
            "price_sales_peer_count": 4,
        }},
    }
    grounded, notes = ground_assumptions(
        {"wacc": 0.09, "terminal_growth_rate": 0.025}, data)
    assert grounded["comps_ev_ebitda"] == 14.0
    assert grounded["comps_ps"] == 4.0
    assert grounded["comps_source"] == "finnhub_peer_median"
    assert grounded["comps_peer_count"] == 5
    assert any("up to 5 peers" in note for note in notes)
