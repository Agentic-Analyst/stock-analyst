"""
Keyless market-data tools for the generalizable agent.

All of these use yfinance (already a dependency) or the free FRED API — no paid
keys. They give the agent the reach it needs to answer questions that aren't
"analyze one ticker": resolving a company in any language, pulling prices and
technicals, market-wide news, and macro series.

Design notes:
* Every tool returns a JSON string (tool_ok / tool_error) so the ReAct loop reads
  results uniformly and never sees a raw exception.
* resolve_symbol pairs the model's world knowledge with yfinance search. yfinance
  handles romanized names well (Noposion, Kweichow Moutai, Tencent) but not raw
  CJK — so the tool's description instructs the model to pass a romanized/English
  form (which it knows), and also returns the model's own candidate if given.
* FRED macro is gated by check_available() on FRED_API_KEY, so the tool simply
  isn't offered when the (free) key isn't configured — the agent then answers
  macro questions from its own knowledge instead of bouncing.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any, List, Optional

from .base import Tool, tool_ok, tool_error
from .crypto_utils import detect_crypto_in_query, normalize_crypto_symbol


# ---------------------------------------------------------------------------
# resolve_symbol — any-language / descriptive company → ticker
# ---------------------------------------------------------------------------
class ResolveSymbolTool(Tool):
    name = "resolve_symbol"
    description = (
        "Resolve a company name, description, or ambiguous ticker to a concrete "
        "stock ticker symbol and exchange. Use this FIRST whenever the user names a "
        "company you're not 100% sure of the ticker for — especially non-English "
        "names, foreign listings, or descriptions. IMPORTANT: pass an English or "
        "romanized form of the name (e.g. for '诺普信' pass 'Noposion', for '贵州茅台' "
        "pass 'Kweichow Moutai', for 'the maker of the iPhone' pass 'Apple') — the "
        "search works best in Latin script. Returns candidate tickers with company "
        "names and exchanges; pick the best match."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Company name in English/romanized form, a ticker, or a short description.",
            }
        },
        "required": ["query"],
    }
    repeatable = True

    async def execute(self, query: str) -> str:
        import asyncio
        query = (query or "").strip()
        if not query:
            return tool_error("Empty query.")

        # Crypto short-circuit: if the query names a coin, hand back its Yahoo
        # -USD symbol directly and steer routing to the crypto path (no equity
        # fundamentals/DCF exist for a coin).
        crypto_symbol = normalize_crypto_symbol(query) or detect_crypto_in_query(query)
        if crypto_symbol:
            return tool_ok(
                query=query,
                asset_class="crypto",
                candidates=[{"ticker": crypto_symbol, "name": query, "exchange": "Crypto", "type": "CRYPTOCURRENCY"}],
                best_guess=crypto_symbol,
                note=("This is a cryptocurrency. Use get_crypto for a market snapshot "
                      "and get_technicals for chart levels. Do NOT call get_financials/"
                      "build_model/write_report — coins have no fundamentals or DCF."),
            )

        def _search():
            import yfinance as yf
            out: List[dict] = []
            try:
                res = yf.Search(query, max_results=8)
                for q in (res.quotes or []):
                    sym = q.get("symbol")
                    if not sym:
                        continue
                    out.append({
                        "ticker": sym,
                        "name": q.get("shortname") or q.get("longname") or "",
                        "exchange": q.get("exchDisp") or q.get("exchange") or "",
                        "type": q.get("quoteType") or q.get("typeDisp") or "",
                    })
            except Exception:
                pass
            return out

        candidates = await asyncio.to_thread(_search)
        # Prefer equities, then keep order.
        equities = [c for c in candidates if str(c.get("type", "")).upper() in ("EQUITY", "EQUITIES", "S")]
        ranked = equities + [c for c in candidates if c not in equities]

        if not ranked:
            return tool_ok(
                query=query, candidates=[],
                note=("No ticker found via search. If you know the ticker from your own "
                      "knowledge, use it directly; otherwise ask the user to clarify."),
            )
        return tool_ok(
            query=query,
            candidates=ranked[:6],
            best_guess=ranked[0]["ticker"],
            note="Pick the candidate that best matches the user's intent, then proceed.",
        )


# ---------------------------------------------------------------------------
# get_prices — OHLCV history / recent performance
# ---------------------------------------------------------------------------
class GetPricesTool(Tool):
    name = "get_prices"
    description = (
        "Get recent price history and performance for a ticker: latest price, and "
        "percentage change over a period. Use for 'how did X do this year', 'how much "
        "did X move in 3 months', 'is X up or down'. period is one of: 1mo, 3mo, 6mo, "
        "1y, ytd, 5y. Returns latest close, period start/end, % change, and high/low."
    )
    parameters = {
        "type": "object",
        "properties": {
            "ticker": {"type": "string", "description": "Ticker symbol (resolve non-US names first)."},
            "period": {"type": "string", "description": "1mo|3mo|6mo|1y|ytd|5y", "default": "1y"},
        },
        "required": ["ticker"],
    }

    async def execute(self, ticker: str, period: str = "1y") -> str:
        import asyncio
        ticker = (ticker or "").strip().upper()
        # Accept bare crypto symbols/names (BTC, Bitcoin) → Yahoo BTC-USD pair.
        ticker = normalize_crypto_symbol(ticker) or ticker
        period = (period or "1y").strip().lower()
        if period not in ("1mo", "3mo", "6mo", "1y", "ytd", "5y", "2y", "max"):
            period = "1y"

        def _hist():
            import yfinance as yf
            t = yf.Ticker(ticker)
            df = t.history(period=period)
            if df is None or df.empty:
                return None
            first = float(df["Close"].iloc[0])
            last = float(df["Close"].iloc[-1])
            return {
                "latest_close": round(last, 2),
                "period_start_close": round(first, 2),
                "pct_change": round((last - first) / first * 100, 2) if first else None,
                "period_high": round(float(df["High"].max()), 2),
                "period_low": round(float(df["Low"].min()), 2),
                "start_date": str(df.index[0].date()),
                "end_date": str(df.index[-1].date()),
            }

        data = await asyncio.to_thread(_hist)
        if not data:
            return tool_error(f"No price data for {ticker} over {period}.", ticker=ticker)
        return tool_ok(ticker=ticker, period=period, **data)


# ---------------------------------------------------------------------------
# get_technicals — RSI/MACD/SMA/Bollinger (computed locally from yfinance)
# ---------------------------------------------------------------------------
class GetTechnicalsTool(Tool):
    name = "get_technicals"
    description = (
        "Compute technical indicators for a ticker from recent daily prices: RSI(14), "
        "50-day and 200-day simple moving averages (and whether price is above/below "
        "them — the '200-day' that traders watch for breakdowns), MACD, and 20-day "
        "Bollinger Bands. Use for chart/technical/breakdown/momentum questions. "
        "Returns the indicator values plus latest price context."
    )
    parameters = {
        "type": "object",
        "properties": {"ticker": {"type": "string", "description": "Ticker symbol."}},
        "required": ["ticker"],
    }

    async def execute(self, ticker: str) -> str:
        import asyncio
        ticker = (ticker or "").strip().upper()
        # Accept bare crypto symbols/names (BTC, Bitcoin) → Yahoo BTC-USD pair.
        ticker = normalize_crypto_symbol(ticker) or ticker

        def _calc():
            import yfinance as yf
            df = yf.Ticker(ticker).history(period="1y")
            if df is None or df.empty or len(df) < 30:
                return None
            close = df["Close"]
            last = float(close.iloc[-1])

            # RSI(14)
            delta = close.diff()
            gain = delta.clip(lower=0).rolling(14).mean()
            loss = (-delta.clip(upper=0)).rolling(14).mean()
            rs = gain / loss
            rsi = float((100 - 100 / (1 + rs)).iloc[-1]) if loss.iloc[-1] != 0 else 100.0

            sma50 = float(close.rolling(50).mean().iloc[-1]) if len(close) >= 50 else None
            sma200 = float(close.rolling(200).mean().iloc[-1]) if len(close) >= 200 else None

            ema12 = close.ewm(span=12, adjust=False).mean()
            ema26 = close.ewm(span=26, adjust=False).mean()
            macd = ema12 - ema26
            signal = macd.ewm(span=9, adjust=False).mean()

            mid = close.rolling(20).mean()
            std = close.rolling(20).std()
            bb_upper = float((mid + 2 * std).iloc[-1])
            bb_lower = float((mid - 2 * std).iloc[-1])

            return {
                "latest_close": round(last, 2),
                "rsi_14": round(rsi, 1),
                "sma_50": round(sma50, 2) if sma50 else None,
                "sma_200": round(sma200, 2) if sma200 else None,
                "above_sma_50": (last > sma50) if sma50 else None,
                "above_sma_200": (last > sma200) if sma200 else None,
                "macd": round(float(macd.iloc[-1]), 3),
                "macd_signal": round(float(signal.iloc[-1]), 3),
                "macd_bullish": bool(macd.iloc[-1] > signal.iloc[-1]),
                "bollinger_upper": round(bb_upper, 2),
                "bollinger_lower": round(bb_lower, 2),
            }

        data = await asyncio.to_thread(_calc)
        if not data:
            return tool_error(f"Not enough price data to compute technicals for {ticker}.", ticker=ticker)
        return tool_ok(ticker=ticker, **data)


# ---------------------------------------------------------------------------
# get_global_news — market-wide headlines ("what happened today")
# ---------------------------------------------------------------------------
class GetGlobalNewsTool(Tool):
    name = "get_global_news"
    description = (
        "Get recent broad market / world financial news headlines (not specific to "
        "one company). Use for 'what happened in the markets today', 'what's moving "
        "markets', general market context. Returns a list of recent headlines with "
        "sources and links."
    )
    parameters = {
        "type": "object",
        "properties": {
            "topic": {"type": "string",
                      "description": "Optional focus, e.g. 'stock market', 'Federal Reserve', 'oil'. Default broad market.",
                      "default": "stock market today"}
        },
    }

    async def execute(self, topic: str = "stock market today") -> str:
        import asyncio
        topic = (topic or "stock market today").strip()

        def _news():
            import yfinance as yf
            items = []
            try:
                res = yf.Search(topic, news_count=10)
                for n in (res.news or []):
                    items.append({
                        "title": n.get("title"),
                        "publisher": n.get("publisher"),
                        "link": n.get("link"),
                        "published": _fmt_ts(n.get("providerPublishTime")),
                    })
            except Exception:
                pass
            return items

        news = await asyncio.to_thread(_news)
        if not news:
            return tool_ok(topic=topic, headlines=[],
                           note="No fresh headlines retrieved; answer from your general knowledge and say it's not live.")
        return tool_ok(topic=topic, headlines=news[:8])


# ---------------------------------------------------------------------------
# get_macro — FRED series (rates, CPI, unemployment, yield curve). Free key.
# ---------------------------------------------------------------------------
_FRED_ALIASES = {
    "fed_funds_rate": "FEDFUNDS", "fed_funds": "FEDFUNDS", "interest_rate": "FEDFUNDS",
    "10y_treasury": "DGS10", "10y": "DGS10", "10_year": "DGS10", "treasury_10y": "DGS10",
    "2y_treasury": "DGS2", "2y": "DGS2",
    "yield_curve": "T10Y2Y", "10y2y": "T10Y2Y",
    "cpi": "CPIAUCSL", "inflation": "CPIAUCSL",
    "core_cpi": "CPILFESL",
    "unemployment": "UNRATE", "unemployment_rate": "UNRATE",
    "gdp": "GDP", "real_gdp": "GDPC1",
    "vix": "VIXCLS",
    "m2": "M2SL", "money_supply": "M2SL",
    "mortgage_30y": "MORTGAGE30US",
}


class GetMacroTool(Tool):
    name = "get_macro"
    description = (
        "Get a macroeconomic time series from the Federal Reserve (FRED): the latest "
        "value and recent trend. Use for questions about interest rates, inflation, "
        "unemployment, the yield curve, GDP, VIX, etc. — e.g. 'how would falling rates "
        "affect banks'. Pass a friendly name: fed_funds_rate, 10y_treasury, "
        "yield_curve, cpi, inflation, unemployment, gdp, vix, m2, mortgage_30y — or a "
        "raw FRED series id. Returns the latest value, date, and recent readings."
    )
    parameters = {
        "type": "object",
        "properties": {
            "indicator": {"type": "string",
                          "description": "Friendly name (fed_funds_rate, 10y_treasury, yield_curve, cpi, unemployment, vix…) or FRED series id."}
        },
        "required": ["indicator"],
    }

    @classmethod
    def check_available(cls) -> bool:
        # Only offered when the (free) FRED key is present; otherwise the agent
        # answers macro questions from its own knowledge.
        return bool(os.getenv("FRED_API_KEY"))

    async def execute(self, indicator: str) -> str:
        import asyncio
        key = (indicator or "").strip().lower().replace(" ", "_")
        series_id = _FRED_ALIASES.get(key, indicator.strip().upper())

        def _fetch():
            import requests
            api_key = os.getenv("FRED_API_KEY")
            end = datetime.utcnow().date()
            start = end - timedelta(days=400)
            url = "https://api.stlouisfed.org/fred/series/observations"
            params = {
                "series_id": series_id, "api_key": api_key, "file_type": "json",
                "observation_start": start.isoformat(), "observation_end": end.isoformat(),
                "sort_order": "desc", "limit": 12,
            }
            r = requests.get(url, params=params, timeout=20)
            r.raise_for_status()
            obs = [o for o in r.json().get("observations", []) if o.get("value") not in (".", None, "")]
            return obs

        try:
            obs = await asyncio.to_thread(_fetch)
        except Exception as exc:
            return tool_error(f"Could not fetch FRED series '{series_id}': {exc}", indicator=indicator)
        if not obs:
            return tool_error(f"No data for FRED series '{series_id}'.", indicator=indicator)
        latest = obs[0]
        recent = [{"date": o["date"], "value": o["value"]} for o in obs[:6]]
        return tool_ok(
            indicator=indicator, series_id=series_id,
            latest_value=latest["value"], latest_date=latest["date"],
            recent=recent,
        )


def _fmt_ts(ts: Optional[int]) -> Optional[str]:
    if not ts:
        return None
    try:
        return datetime.utcfromtimestamp(int(ts)).strftime("%Y-%m-%d")
    except Exception:
        return None


def build_data_tools():
    """Instantiate the keyless data tools (FRED self-excludes without its free key)."""
    return [
        ResolveSymbolTool(),
        GetPricesTool(),
        GetTechnicalsTool(),
        GetGlobalNewsTool(),
        GetMacroTool(),
    ]
