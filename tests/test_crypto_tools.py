import asyncio
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

pd = pytest.importorskip("pandas")

from agents.tools.crypto_tools import (
    GetCryptoTool, _market_structure, _performance, _rolling_24h,
)


def history(days=400):
    start = datetime(2025, 1, 1)
    index = [start + timedelta(days=i) for i in range(days)]
    closes = [40_000 + i * 25 + (i % 7) * 10 for i in range(days)]
    return pd.DataFrame({"Close": closes}, index=index)


def test_get_crypto_returns_supply_liquidity_and_calendar_day_risk(monkeypatch):
    import yfinance as yf
    from agents.tools import yf_resilience

    class Ticker:
        info = {
            "currency": "USD", "marketCap": 1.2e12, "volume24Hr": 4.8e10,
            "circulatingSupply": 19.9e6, "totalSupply": 19.9e6,
            "maxSupply": 21e6,
        }

    monkeypatch.setattr(yf, "Ticker", lambda _symbol: Ticker())
    monkeypatch.setattr(yf_resilience, "fetch_history", lambda *args, **kwargs: history())
    result = json.loads(asyncio.run(GetCryptoTool().execute("bitcoin")))
    assert result["status"] == "ok" and result["symbol"] == "BTC-USD"
    assert result["market_structure"]["volume_to_market_cap"] == 0.04
    assert result["market_structure"]["circulating_to_max_supply"] == pytest.approx(19.9 / 21)
    assert result["performance"]["returns"]["one_year"] is not None
    assert result["performance"]["annualized_volatility_one_year"] is not None
    assert result["methodology"]["annualized_volatility"] == "daily_returns_sqrt_365"
    assert result["methodology"]["intrinsic_value"] is None
    assert result["methodology"]["on_chain_data"] is False
    assert result["price_usd"] == result["price"]


def test_non_usd_pair_is_not_mislabeled_as_a_usd_price(monkeypatch):
    import yfinance as yf
    from agents.tools import yf_resilience

    class Ticker:
        info = {"currency": "EUR"}

    monkeypatch.setattr(yf, "Ticker", lambda _symbol: Ticker())
    monkeypatch.setattr(yf_resilience, "fetch_history", lambda *args, **kwargs: history())
    result = json.loads(asyncio.run(GetCryptoTool().execute("BTC-EUR")))
    assert result["currency"] == "EUR" and "price_usd" not in result
    assert "market_cap_usd" not in result and "volume_24h_usd" not in result


def test_crypto_risk_and_long_returns_require_the_period_they_claim():
    result = _performance(history(20))
    assert result["returns"]["one_year"] is None
    assert result["annualized_volatility_one_year"] is None
    assert result["max_drawdown_one_year"] is None

    sparse = pd.DataFrame({"Close": [90, 100, 110]}, index=[
        datetime(2024, 1, 1), datetime(2025, 8, 1), datetime(2026, 1, 1),
    ])
    assert _performance(sparse)["returns"]["one_year"] is None

    thin = pd.DataFrame({"Close": [90, 70, 110]}, index=[
        datetime(2025, 1, 1), datetime(2025, 7, 1), datetime(2026, 1, 1),
    ])
    result = _performance(thin)
    assert result["returns"]["one_year"] is not None
    assert result["max_drawdown_one_year"] is None
    assert result["high_one_year"] is None


def test_impossible_supply_relationships_are_not_claimed_as_facts():
    market = _market_structure({
        "circulatingSupply": 20, "totalSupply": 10, "maxSupply": 15,
    })
    assert market["circulating_supply"] == 20
    assert market["total_supply"] is None
    assert market["max_supply"] is None
    assert market["circulating_to_max_supply"] is None


def test_24h_change_uses_intraday_rolling_window_not_daily_close_label():
    index = [datetime(2026, 9, 10) + timedelta(hours=i) for i in range(30)]
    frame = pd.DataFrame({"Close": [100.0] * 6 + [120.0] * 24}, index=index)

    result = _rolling_24h(frame)

    assert result["basis"] == "rolling_24h_intraday_close"
    assert result["return"] == pytest.approx(0.2)
    assert result["price"] == 120.0


def test_unknown_crypto_is_rejected_before_a_market_snapshot(monkeypatch):
    from agents.tools import crypto_utils

    monkeypatch.setattr(crypto_utils, "search_crypto_symbol", lambda _asset: None)
    result = json.loads(asyncio.run(GetCryptoTool().execute("not-a-real-coin")))
    assert result["status"] == "error"
