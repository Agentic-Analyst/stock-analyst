"""
Beta must be measured against the listing's own market.

THE BUG. Yahoo's `beta` is computed against the S&P 500 for every listing. For
a US stock that is right, and our regression reproduces it (Apple 1.09 vs
1.085, NVIDIA 2.19 vs 2.217). For anything else it measures co-movement with an
American index and reads as low risk: Reliance 0.15 (0.98 vs the Nifty),
Infosys 0.11 (0.70), PC Jeweller 0.33 (3.28), Shell -0.22 (0.72 vs the FTSE).
Every NSE listing hit the CAPM's floor, and PC Jeweller — a small-cap jeweller
that swings 50% — was discounted at 7.9% and rated BUY at +48.6%.

Offline: the regression is exercised on synthetic series through a fake
yfinance, so the arithmetic is pinned without the network.

Run:  python -m pytest tests/test_market_beta.py -q
"""

import os
import sys
import types

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "src"))

from src.agents.fm.market_beta import (
    compute_beta,
    country_risk_premium,
    home_index,
    _WEAK_FIT_R2,
)


class TestHomeIndex:
    @pytest.mark.parametrize("symbol,index", [
        ("PCJEWELLER.NS", "^NSEI"), ("RELIANCE.BO", "^BSESN"), ("MC.PA", "^FCHI"),
        ("SAP.DE", "^GDAXI"), ("SHEL.L", "^FTSE"), ("7203.T", "^N225"),
        ("005930.KS", "^KS11"), ("0700.HK", "^HSI"), ("NESN.SW", "^SSMI"),
        ("ASML.AS", "^AEX"), ("RY.TO", "^GSPTSE"), ("BHP.AX", "^AXJO"),
        ("AAPL", "^GSPC"), ("NVDA", "^GSPC"),
    ])
    def test_suffix_maps_to_the_home_market(self, symbol, index):
        assert home_index(symbol) == index

    def test_unknown_suffix_falls_back_to_the_sp500(self):
        assert home_index("XYZ.ZZ") == "^GSPC"

    def test_missing_symbol_is_us(self):
        assert home_index(None) == "^GSPC"


class TestCountryRiskPremium:
    def test_developed_markets_carry_none(self):
        for c in ("United States", "France", "Japan", "Switzerland", "Netherlands"):
            value, label = country_risk_premium(c)
            assert value == 0.0
            assert "no country premium" in label

    def test_india_carries_a_premium_and_says_it_is_approximate(self):
        value, label = country_risk_premium("India")
        assert 0.02 <= value <= 0.04
        assert "approx" in label and "as of" in label

    def test_unknown_country_is_not_guessed(self):
        value, label = country_risk_premium("Atlantis")
        assert value == 0.0
        assert "no country premium on record" in label

    def test_missing_country_is_not_guessed(self):
        value, label = country_risk_premium(None)
        assert value == 0.0

    def test_operator_override(self, monkeypatch):
        monkeypatch.setenv("CRP_INDIA", "0.035")
        value, label = country_risk_premium("India")
        assert value == pytest.approx(0.035)
        assert "override" in label

    def test_override_with_spaces_in_the_name(self, monkeypatch):
        monkeypatch.setenv("CRP_SOUTH_AFRICA", "0.05")
        value, _ = country_risk_premium("South Africa")
        assert value == pytest.approx(0.05)

    def test_nonsense_override_is_ignored(self, monkeypatch):
        monkeypatch.setenv("CRP_INDIA", "banana")
        value, _ = country_risk_premium("India")
        assert 0.02 <= value <= 0.04


def _fake_yfinance(series_by_symbol):
    """yfinance stand-in whose history() returns fixed monthly closes."""
    import pandas as pd
    module = types.ModuleType("yfinance")

    class _Ticker:
        def __init__(self, symbol):
            self._s = symbol

        def history(self, period="5y", interval="1mo", auto_adjust=True):
            closes = series_by_symbol.get(self._s)
            if closes is None:
                return pd.DataFrame()
            idx = pd.date_range("2021-01-31", periods=len(closes), freq="ME")
            return pd.DataFrame({"Close": closes}, index=idx)

    module.Ticker = _Ticker
    return module


def _closes_from_returns(returns, start=100.0):
    out, level = [start], start
    for r in returns:
        level *= (1 + r); out.append(level)
    return out


class TestComputeBeta:
    def _install(self, monkeypatch, stock_returns, index_returns, stock="X.NS", index="^NSEI"):
        monkeypatch.setitem(sys.modules, "yfinance", _fake_yfinance({
            stock: _closes_from_returns(stock_returns),
            index: _closes_from_returns(index_returns),
        }))

    def test_recovers_a_known_slope(self, monkeypatch):
        """Stock moves exactly 1.5x the index every month: beta is 1.5, R² is 1."""
        import numpy as np
        rng = np.random.default_rng(7)
        idx = list(rng.normal(0.01, 0.04, 60))
        stk = [1.5 * r for r in idx]
        self._install(monkeypatch, stk, idx)
        fit = compute_beta("X.NS")
        assert fit["raw"] == pytest.approx(1.5, abs=1e-6)
        assert fit["r_squared"] == pytest.approx(1.0, abs=1e-6)
        assert fit["index"] == "^NSEI"
        assert fit["observations"] == 60
        assert fit["weak_fit"] is False

    def test_blume_adjustment(self, monkeypatch):
        import numpy as np
        rng = np.random.default_rng(3)
        idx = list(rng.normal(0.01, 0.04, 60)); stk = [2.0 * r for r in idx]
        self._install(monkeypatch, stk, idx)
        fit = compute_beta("X.NS")
        assert fit["blume"] == pytest.approx(0.67 * 2.0 + 0.33, abs=1e-6)

    def test_weak_fit_is_flagged_not_hidden(self, monkeypatch):
        """Uncorrelated series: the slope is noise, and the result says so."""
        import numpy as np
        rng = np.random.default_rng(11)
        idx = rng.normal(0.01, 0.04, 60)
        noise = rng.normal(0.01, 0.10, 60)
        # Make the stock EXACTLY orthogonal to the index (Gram-Schmidt), so the
        # fit is zero by construction rather than small by luck — two random
        # series over 60 months can share R² ~0.1 by chance.
        ic = idx - idx.mean()
        stk = noise - ic * (np.dot(noise - noise.mean(), ic) / np.dot(ic, ic))
        self._install(monkeypatch, list(stk), list(idx))
        fit = compute_beta("X.NS")
        assert fit["r_squared"] < _WEAK_FIT_R2
        assert fit["weak_fit"] is True

    def test_insufficient_history_returns_none(self, monkeypatch):
        idx = [0.01] * 10; stk = [0.02] * 10
        self._install(monkeypatch, stk, idx)
        assert compute_beta("X.NS") is None

    def test_missing_index_returns_none(self, monkeypatch):
        import numpy as np
        rng = np.random.default_rng(1)
        monkeypatch.setitem(sys.modules, "yfinance", _fake_yfinance({
            "X.NS": _closes_from_returns(list(rng.normal(0.01, 0.04, 60)))}))
        assert compute_beta("X.NS") is None

    def test_never_raises(self, monkeypatch):
        module = types.ModuleType("yfinance")

        class _Boom:
            def __init__(self, *a, **k): raise RuntimeError("down")

        module.Ticker = _Boom
        monkeypatch.setitem(sys.modules, "yfinance", module)
        assert compute_beta("X.NS") is None

    def test_no_symbol_returns_none(self):
        assert compute_beta(None) is None


class TestCapmIntegration:
    """The CAPM uses the home-index beta and adds the country premium."""

    def _pcj(self):
        return {
            "basic_info": {"symbol": "PCJEWELLER.NS", "currency": "INR", "country": "India"},
            "capital_structure": {"beta": 0.326, "total_debt": 11_665_600_512},
            "market_data": {"market_cap": 116_928_094_208},
            "growth_profitability": {},
        }

    def test_uses_the_regression_not_yahoo(self, monkeypatch):
        from src.agents.fm import assumption_grounding as ag
        monkeypatch.setattr(ag, "compute_beta", None, raising=False)
        import src.agents.fm.market_beta as mb
        monkeypatch.setattr(mb, "compute_beta", lambda s: {
            "raw": 3.28, "blume": 0.67 * 3.28 + 0.33, "r_squared": 0.23,
            "observations": 59, "index": "^NSEI", "window": "5y monthly", "weak_fit": False})
        c = ag.capm_components(self._pcj())
        assert c["beta"] == pytest.approx(2.0)          # clamped at the new ceiling
        assert "vs ^NSEI" in c["beta_source"]
        assert "clamped to 2.00" in c["beta_source"]
        assert c["beta_index"] == "^NSEI"

    def test_country_premium_is_added_to_the_erp(self, monkeypatch):
        from src.agents.fm import assumption_grounding as ag
        import src.agents.fm.market_beta as mb
        monkeypatch.setattr(mb, "compute_beta", lambda s: None)
        c = ag.capm_components(self._pcj())
        assert c["country_risk_premium"] == pytest.approx(0.029)
        assert c["equity_risk_premium_total"] == pytest.approx(0.055 + 0.029)
        assert c["cost_of_equity"] == pytest.approx(
            c["risk_free_rate"] + c["beta"] * c["equity_risk_premium_total"])
        assert "India" in c["crp_source"]

    def test_falls_back_to_yahoo_and_says_so(self, monkeypatch):
        from src.agents.fm import assumption_grounding as ag
        import src.agents.fm.market_beta as mb
        monkeypatch.setattr(mb, "compute_beta", lambda s: None)
        c = ag.capm_components(self._pcj())
        assert "S&P 500" in c["beta_source"]
        assert "price history was unavailable" in c["beta_source"]

    def test_pc_jeweller_is_no_longer_discounted_like_a_utility(self, monkeypatch):
        """
        With its own beta and India's premium the cost of equity is where a desk
        would put it, not 8%.
        """
        from src.agents.fm import assumption_grounding as ag
        import src.agents.fm.market_beta as mb
        monkeypatch.setattr(mb, "compute_beta", lambda s: {
            "raw": 3.28, "blume": 0.67 * 3.28 + 0.33, "r_squared": 0.23,
            "observations": 59, "index": "^NSEI", "window": "5y monthly", "weak_fit": False})
        c = ag.capm_components(self._pcj())
        assert c["cost_of_equity"] > 0.15

    def test_developed_market_is_unchanged_by_the_premium(self, monkeypatch):
        from src.agents.fm import assumption_grounding as ag
        import src.agents.fm.market_beta as mb
        monkeypatch.setattr(mb, "compute_beta", lambda s: None)
        c = ag.capm_components({"basic_info": {"symbol": "AAPL", "currency": "USD", "country": "United States"},
                                "capital_structure": {"beta": 1.085, "total_debt": 1e9},
                                "market_data": {"market_cap": 4e12}, "growth_profitability": {}})
        assert c["country_risk_premium"] == 0.0
        assert c["equity_risk_premium_total"] == pytest.approx(0.055)
