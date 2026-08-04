"""
Crypto market-data tool for the generalist agent.

Crypto has no fundamentals, no earnings, no DCF — so it gets its own price-first
snapshot tool instead of being forced through the equity pipeline. Data comes
from yfinance's `XXX-USD` pairs (already a dependency; no new vendor).

`get_crypto` answers the questions people actually ask about a coin: where is it
now, how has it moved (24h / 7d / 30d / YTD), how big is it (market cap, volume),
and where does it sit versus its 52-week range. Pair it with get_technicals for
RSI/moving-average levels and get_prediction_markets for event odds.
"""

from __future__ import annotations

from .base import Tool, tool_ok, tool_error
from .crypto_utils import normalize_crypto_symbol


class GetCryptoTool(Tool):
    name = "get_crypto"
    description = (
        "Get a live market snapshot for a cryptocurrency: spot price (USD), 24h / "
        "7d / 30d / YTD change, market cap, 24h volume, and position within the "
        "52-week range. Use this for ANY crypto question (Bitcoin, Ethereum, Solana, "
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
            return tool_error(
                f"'{asset}' isn't a recognized cryptocurrency. Pass a coin name "
                "(Bitcoin, Ethereum, Solana) or its symbol (BTC, ETH). For a stock, "
                "use get_prices/get_financials instead.",
                asset=asset,
            )

        def _snapshot():
            import yfinance as yf
            from .yf_resilience import fetch_history

            t = yf.Ticker(symbol)
            df = fetch_history(symbol, "1y")
            if df is None or df.empty:
                return None
            close = df["Close"]
            last = float(close.iloc[-1])

            def _pct_over(days: int):
                if len(close) <= days:
                    return None
                past = float(close.iloc[-(days + 1)])
                return round((last - past) / past * 100, 2) if past else None

            # YTD: first close of the current calendar year in the series.
            ytd = None
            try:
                year = df.index[-1].year
                ytd_df = close[close.index.year == year]
                if len(ytd_df) > 1:
                    first_ytd = float(ytd_df.iloc[0])
                    ytd = round((last - first_ytd) / first_ytd * 100, 2) if first_ytd else None
            except Exception:
                ytd = None

            high_52w = float(close.max())
            low_52w = float(close.min())
            from_high = round((last - high_52w) / high_52w * 100, 2) if high_52w else None

            # Market cap / volume from .info when available (best-effort).
            market_cap = volume_24h = None
            try:
                info = t.info or {}
                market_cap = info.get("marketCap")
                volume_24h = info.get("volume24Hr") or info.get("volume")
            except Exception:
                pass

            return {
                "symbol": symbol,
                "price_usd": round(last, 4 if last < 1 else 2),
                "change_24h_pct": _pct_over(1),
                "change_7d_pct": _pct_over(7),
                "change_30d_pct": _pct_over(30),
                "change_ytd_pct": ytd,
                "high_52w": round(high_52w, 4 if high_52w < 1 else 2),
                "low_52w": round(low_52w, 4 if low_52w < 1 else 2),
                "pct_from_52w_high": from_high,
                "market_cap_usd": market_cap,
                "volume_24h_usd": volume_24h,
                "as_of": str(df.index[-1].date()),
            }

        data = await asyncio.to_thread(_snapshot)
        if not data:
            return tool_error(f"No market data for {symbol}.", asset=asset, symbol=symbol)
        return tool_ok(
            asset_class="crypto",
            note=("Crypto snapshot from market data. No fundamentals/DCF apply. "
                  "Use get_technicals for RSI/MA levels and get_prediction_markets "
                  "for event odds."),
            **data,
        )


def build_crypto_tools():
    return [GetCryptoTool()]
