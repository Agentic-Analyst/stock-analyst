"""
Crypto market-data tool for the generalist agent.

Crypto has no fundamentals, no earnings, no DCF — so it gets its own price-first
snapshot tool instead of being forced through the equity pipeline. Data comes
from yfinance's `XXX-USD` pairs (already a dependency; no new vendor).

`get_crypto` answers the questions people actually ask about a coin: its latest
daily close, performance, risk, liquidity, supply, and one-year range. Pair it
with get_technicals for RSI/moving-average levels and get_prediction_markets
for event odds.
"""

from __future__ import annotations

import math
import statistics
from datetime import date, timedelta
from typing import Any, Dict, Optional, Tuple

from .base import Tool, tool_ok, tool_error
from .crypto_utils import normalize_crypto_symbol


def _number(value: Any) -> Optional[float]:
    try:
        if value is None or value != value or isinstance(value, bool):
            return None
        out = float(value)
        return out if math.isfinite(out) else None
    except (TypeError, ValueError):
        return None


def _performance(frame: Any) -> Dict[str, Any]:
    """Calendar-day crypto return/risk metrics; missing history stays missing."""
    keys = ("one_day", "seven_days", "thirty_days", "ninety_days", "ytd",
            "one_year", "three_year", "five_year")
    empty = {
        "as_of": None, "observations": 0,
        "returns": {key: None for key in keys},
        "annualized_volatility_thirty_days": None,
        "annualized_volatility_one_year": None,
        "max_drawdown_one_year": None,
        "high_one_year": None, "low_one_year": None,
        "pct_from_high_one_year": None,
        "basis": "daily_close",
    }
    if frame is None or getattr(frame, "empty", True) or "Close" not in frame:
        return empty

    points = []
    for index, raw in frame["Close"].items():
        value = _number(raw)
        try:
            when = index.date() if hasattr(index, "date") else date.fromisoformat(str(index)[:10])
        except ValueError:
            continue
        if value is not None and value > 0:
            points.append((when, value))
    points = sorted(dict(points).items())
    empty["observations"] = len(points)
    if len(points) < 2:
        return empty

    end = points[-1][0]

    def since(start: date) -> Optional[float]:
        if points[0][0] > start + timedelta(days=3):
            return None
        first = next(((when, value) for when, value in points if when >= start), None)
        if first is None or first[0] > start + timedelta(days=3) or first[0] >= end:
            return None
        return points[-1][1] / first[1] - 1.0

    starts = {
        "one_day": end - timedelta(days=1),
        "seven_days": end - timedelta(days=7),
        "thirty_days": end - timedelta(days=30),
        "ninety_days": end - timedelta(days=90),
        "ytd": date(end.year, 1, 1),
        "one_year": end - timedelta(days=365),
        "three_year": end - timedelta(days=365 * 3),
        "five_year": end - timedelta(days=365 * 5),
    }

    def risk_window(days: int, minimum_returns: int) -> Tuple[Optional[float], list]:
        start = end - timedelta(days=days)
        window = [(when, value) for when, value in points if when >= start]
        full = bool(window) and window[0][0] <= start + timedelta(days=3)
        daily = ([current / previous - 1.0
                  for (_, previous), (_, current) in zip(window, window[1:])]
                 if full else [])
        volatility = (statistics.stdev(daily) * math.sqrt(365)
                      if len(daily) >= minimum_returns else None)
        return volatility, window if full and len(daily) >= minimum_returns else []

    volatility_30d, _ = risk_window(30, 20)
    volatility_1y, one_year = risk_window(365, 300)
    high = low = drawdown = distance = None
    if one_year:
        values = [value for _, value in one_year]
        high, low = max(values), min(values)
        distance = points[-1][1] / high - 1.0 if high > 0 else None
        peak, drawdown = 0.0, 0.0
        for value in values:
            peak = max(peak, value)
            if peak > 0:
                drawdown = min(drawdown, value / peak - 1.0)

    return {
        "as_of": end.isoformat(), "observations": len(points),
        "returns": {key: since(start) for key, start in starts.items()},
        "annualized_volatility_thirty_days": volatility_30d,
        "annualized_volatility_one_year": volatility_1y,
        "max_drawdown_one_year": drawdown,
        "high_one_year": high, "low_one_year": low,
        "pct_from_high_one_year": distance,
        "basis": "daily_close",
    }


def _market_structure(info: Any) -> Dict[str, Optional[float]]:
    source = info if isinstance(info, dict) else {}

    def nonnegative(*keys: str) -> Optional[float]:
        for key in keys:
            value = _number(source.get(key))
            if value is not None and value >= 0:
                return value
        return None

    def positive(*keys: str) -> Optional[float]:
        value = nonnegative(*keys)
        return value if value is not None and value > 0 else None

    cap = positive("marketCap")
    volume = nonnegative("volume24Hr", "volume")
    circulating = positive("circulatingSupply")
    total = positive("totalSupply")
    maximum = positive("maxSupply")
    if circulating is not None and total is not None and total < circulating:
        total = None
    if maximum is not None and any(
            value is not None and value > maximum for value in (circulating, total)):
        maximum = None
    return {
        "market_cap": cap,
        "volume_24h": volume,
        "volume_to_market_cap": volume / cap if volume is not None and cap else None,
        "circulating_supply": circulating,
        "total_supply": total,
        "max_supply": maximum,
        "circulating_to_max_supply": (
            circulating / maximum if circulating is not None and maximum else None
        ),
    }


class GetCryptoTool(Tool):
    name = "get_crypto"
    description = (
        "Get a market snapshot for a cryptocurrency: latest daily close, 1d / 7d / "
        "30d / YTD / multi-year performance, calendar-day volatility and drawdown, "
        "market cap, volume, and supply. Use this for ANY crypto question (Bitcoin, Ethereum, Solana, "
        "and other major coins) — 'what's the outlook for BTC', 'how has ETH done', "
        "'is Solana up'. Accepts a coin name ('Bitcoin', 'ethereum') or symbol "
        "('BTC', 'SOL', 'BTC-USD'). IMPORTANT: crypto has no fundamentals, earnings, "
        "or DCF — never call get_financials/build_model/write_report for a coin. "
        "For chart levels (RSI, 200-day) use get_technicals with the coin's -USD "
        "symbol; for event odds ('will BTC hit $X') use get_prediction_markets."
    )
    parameters = {
        "type": "object",
        "properties": {
            "asset": {
                "type": "string",
                "description": "Coin name or symbol, e.g. 'Bitcoin', 'ETH', 'SOL-USD'.",
            }
        },
        "required": ["asset"],
    }

    async def execute(self, asset: str) -> str:
        import asyncio

        symbol = normalize_crypto_symbol(asset)
        if not symbol:
            # Long-tail coin outside the curated map (e.g. a new alt) — try a
            # live Yahoo symbol search before giving up. Bittensor/TAO went
            # unanswered in prod for exactly this gap.
            from .crypto_utils import search_crypto_symbol
            symbol = await asyncio.to_thread(search_crypto_symbol, asset)
        if not symbol:
            return tool_error(
                f"'{asset}' isn't a recognized cryptocurrency (a live Yahoo "
                "symbol search found no matching -USD pair with price data). "
                "Pass a coin name (Bitcoin, Ethereum, Solana) or its symbol "
                "(BTC, ETH). For a stock, use get_prices/get_financials instead.",
                asset=asset,
            )

        def _snapshot():
            import yfinance as yf
            from .yf_resilience import fetch_history

            t = yf.Ticker(symbol)
            df = fetch_history(symbol, "5y", attempts=2,
                               auto_adjust=False, actions=False)
            if df is None or df.empty:
                return None
            performance = _performance(df)
            close = df["Close"].dropna()
            if close.empty:
                return None
            last = _number(close.iloc[-1])
            if last is None or last <= 0:
                return None

            info = {}
            try:
                info = t.info or {}
            except Exception:
                pass
            currency = str(info.get("currency") or symbol.rsplit("-", 1)[-1]).upper()
            market = _market_structure(info)
            returns = performance["returns"]

            def percentage(key: str) -> Optional[float]:
                value = returns.get(key)
                return round(value * 100, 2) if isinstance(value, (int, float)) else None

            price_digits = 8 if last < 0.01 else 6 if last < 1 else 2
            payload = {
                "symbol": symbol,
                "currency": currency,
                "price": round(last, price_digits),
                # Backward-compatible headline fields used by findings and old prompts.
                "change_24h_pct": percentage("one_day"),
                "change_7d_pct": percentage("seven_days"),
                "change_30d_pct": percentage("thirty_days"),
                "change_ytd_pct": percentage("ytd"),
                "high_52w": performance.get("high_one_year"),
                "low_52w": performance.get("low_one_year"),
                "pct_from_52w_high": (
                    round(performance["pct_from_high_one_year"] * 100, 2)
                    if isinstance(performance.get("pct_from_high_one_year"), (int, float))
                    else None
                ),
                "market_structure": market,
                "performance": performance,
                "as_of": performance.get("as_of"),
            }
            if currency == "USD":
                payload.update({
                    "price_usd": payload["price"],
                    "market_cap_usd": market.get("market_cap"),
                    "volume_24h_usd": market.get("volume_24h"),
                })
            return payload

        data = await asyncio.to_thread(_snapshot)
        if not data:
            return tool_error(f"No market data for {symbol}.", asset=asset, symbol=symbol)
        return tool_ok(
            asset_class="crypto",
            methodology={
                "returns": "cumulative_fractions_from_daily_close",
                "annualized_volatility": "daily_returns_sqrt_365",
                "intrinsic_value": None,
                "on_chain_data": False,
            },
            note=("Crypto price, liquidity, supply, and risk snapshot. No issuer "
                  "fundamentals or DCF apply. This does not claim on-chain activity "
                  "or protocol revenue; use get_prediction_markets for event odds."),
            **data,
        )


def build_crypto_tools():
    return [GetCryptoTool()]
