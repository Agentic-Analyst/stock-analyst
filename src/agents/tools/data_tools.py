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

        from src.listing_resolver import (
            _enrichment_order, _search_queries, is_depositary, is_home_listing,
            is_otc, names_might_match, rank_key, venue_suffix,
        )

        def _search(q: str) -> List[dict]:
            import yfinance as yf
            out: List[dict] = []
            try:
                res = yf.Search(q, max_results=8)
                for quote in (res.quotes or []):
                    sym = quote.get("symbol")
                    if not sym:
                        continue
                    out.append({
                        "ticker": sym,
                        "name": quote.get("shortname") or quote.get("longname") or "",
                        "exchange": quote.get("exchDisp") or quote.get("exchange") or "",
                        "type": quote.get("quoteType") or quote.get("typeDisp") or "",
                    })
            except Exception:
                pass
            return out

        def _info(sym: str) -> dict:
            import yfinance as yf
            try:
                return yf.Ticker(sym).info or {}
            except Exception:
                return {}

        async def _enrich(cands: List[dict]) -> List[dict]:
            """
            Attach real listing data to each candidate.

            Search results alone cannot tell a home listing from a regional line:
            the exchange field is not even stable across calls (the same symbol
            came back as TKS and JPX, NYQ and NYS). Concurrency matters — six
            sequential .info calls measured 2.3-3.0s cold against 0.55-0.64s
            through a thread pool. Each call is bounded so one slow foreign
            listing cannot stall the tool; an unenriched candidate is still
            returned, just unranked.
            """
            async def one(c):
                try:
                    return await asyncio.wait_for(asyncio.to_thread(_info, c["ticker"]), timeout=4.0)
                except Exception:
                    return {}

            infos = await asyncio.gather(*[one(c) for c in cands])
            for cand, info in zip(cands, infos):
                cand["_info"] = info
            return cands

        def _annotate(cand: dict) -> dict:
            """Publish the venue facts the model needs to choose for itself."""
            info, sym = cand.pop("_info", {}) or {}, cand["ticker"]
            if not info:
                return cand
            if info.get("longName"):
                cand["name"] = info["longName"]
            cand["currency"] = info.get("currency")
            cand["country"] = info.get("country")
            if info.get("marketCap"):
                cand["market_cap"] = info["marketCap"]
            if info.get("averageVolume"):
                cand["avg_volume"] = info["averageVolume"]
            # One plain-language reason, so the model does not have to infer the
            # venue's status from an exchange code it may not recognise.
            if is_otc(info):
                cand["venue"] = "OTC / unsponsored ADR — not the company's home listing"
            elif is_depositary(info, sym):
                cand["venue"] = "depositary receipt venue — no market cap or share count"
            elif is_home_listing(info, sym):
                cand["venue"] = "primary listing in the company's home market"
            else:
                cand["venue"] = "cross-listing outside the company's home market"
            return cand

        # The model's own query first: it is usually already the brand name, and
        # that path stays a single search.
        seen, candidates = set(), []
        for c in await asyncio.to_thread(_search, query):
            if c["ticker"] not in seen:
                seen.add(c["ticker"])
                candidates.append(c)

        # Keep only equities. The responses also carry ETFs, indices, mutual
        # funds and tokenised-stock crypto lines for these same queries.
        def _is_equity(c):
            return str(c.get("type", "")).upper() in ("EQUITY", "EQUITIES", "S")

        equities = [c for c in candidates if _is_equity(c)]
        others = [c for c in candidates if not _is_equity(c)]

        # An EXACT symbol match always wins. Yahoo answers a short query with
        # fuzzy matches — "MC" returns Freeport-McMoRan and McDonald's alongside
        # Moelis, and both outweigh it on volume — so ranking on venue quality
        # alone hands back a company the user did not ask for.
        wanted = query.upper()

        def _sort_key(c):
            return (c["ticker"].upper() == wanted,) + rank_key(c.get("_info") or {}, c["ticker"])

        # Spend the enrichment budget on the most promising symbols rather than
        # on Yahoo's first six, which for a legal-name query are all regional
        # floors. Only the symbol is known at this point, so this is a cheap
        # pre-sort; the real ranking runs on the fetched data.
        by_symbol = {c["ticker"]: c for c in equities}
        preferred = [by_symbol[t] for t in _enrichment_order(by_symbol)]
        enriched = await _enrich(preferred[:6])
        ranked = sorted(enriched, key=_sort_key, reverse=True)

        # Retry unless we already have the company's HOME listing. Merely finding
        # something tradeable is not enough: the de-accented "Nestle S.A." returns
        # a Milan cross-listing and never NESN.SW, and stopping there would ship
        # the wrong venue without ever trying the brand token.
        def _good(c):
            info = c.get("_info") or {}
            if not info:
                return False
            if c["ticker"].upper() == wanted:
                return True          # the user named this symbol outright
            return is_home_listing(info, c["ticker"]) and not is_otc(info)

        if not any(_good(c) for c in ranked):
            for alt in _search_queries(query)[1:]:
                extra = [c for c in await asyncio.to_thread(_search, alt)
                         if c["ticker"] not in seen and _is_equity(c)
                         and names_might_match(query, c["name"])]
                if not extra:
                    continue
                for c in extra:
                    seen.add(c["ticker"])
                # Only the new arrivals need a lookup; `ranked` already carries
                # its own.
                ranked = sorted(ranked + await _enrich(extra[:6]),
                                key=_sort_key, reverse=True)
                if any(_good(c) for c in ranked):
                    break

        ranked = [_annotate(c) for c in ranked] + others

        if not ranked:
            return tool_ok(
                query=query, candidates=[],
                note=("No ticker found via search. If you know the ticker from your own "
                      "knowledge, use it directly — but include the exchange suffix for "
                      "any non-US listing; otherwise ask the user to clarify."),
            )

        return tool_ok(
            query=query,
            candidates=ranked[:6],
            best_guess=ranked[0]["ticker"],
            note=("Candidates are ordered by venue quality: a company's home listing "
                  "first, then cross-listings, then depositary receipts and OTC lines. "
                  "best_guess is the top of that order. Read the `venue` field before "
                  "overriding it, and prefer a listing with a market_cap — one without "
                  "cannot be valued. Always pass the FULL symbol including its exchange "
                  "suffix (MC.PA, not MC): a bare ticker resolves to whichever company "
                  "owns it in the US."),
        )


# ---------------------------------------------------------------------------
# get_prices — OHLCV history / recent performance
# ---------------------------------------------------------------------------
def company_label(ticker: str) -> Optional[str]:
    """
    The company a ticker actually belongs to.

    Price payloads used to carry the symbol alone. When an agent guessed "MC"
    for LVMH it got back $68.90 with nothing to contradict it — that is Moelis &
    Company on the NYSE — and the figure flowed into a luxury-sector report as
    though it were LVMH's. Naming the issuer lets the model catch its own bad
    guess instead of quoting another company's price at the user.

    Best-effort and never raises; an unnamed quote is still a usable quote.
    """
    return listing_identity(ticker)[0]


def listing_identity(ticker: str) -> tuple:
    """
    ``(company_name, currency)`` for a ticker, in one lookup.

    The currency matters as much as the name: a EUR listing whose findings are
    published with a "$" is telling the user something false about the number,
    and both facts come from the same call.
    """
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info or {}
        name = info.get("longName") or info.get("shortName") or None
        return name, info.get("currency") or None
    except Exception:
        return None, None


class GetPricesTool(Tool):
    name = "get_prices"
    description = (
        "Get live price and performance for a ticker. ALWAYS returns the current "
        "quote (latest price, previous close, TODAY's $ and % change, day range) "
        "plus stats over the requested period. Use period='1d' for 'how is X "
        "doing TODAY / why did X move today' (adds the intraday session: open, "
        "high, low, latest). Longer periods for 'how did X do this year': 1d, "
        "5d, 1mo, 3mo, 6mo, 1y, ytd, 5y. Works for stocks and crypto (-USD)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "ticker": {"type": "string", "description": "Ticker symbol (resolve non-US names first)."},
            "period": {"type": "string", "description": "1d|5d|1mo|3mo|6mo|1y|ytd|5y — use 1d for today's move", "default": "1y"},
        },
        "required": ["ticker"],
    }

    async def execute(self, ticker: str, period: str = "1y") -> str:
        import asyncio
        ticker = (ticker or "").strip().upper()
        # Accept bare crypto symbols/names (BTC, Bitcoin) → Yahoo BTC-USD pair.
        ticker = normalize_crypto_symbol(ticker) or ticker
        period = (period or "1y").strip().lower()
        if period not in ("1d", "5d", "1mo", "3mo", "6mo", "1y", "ytd", "5y", "2y", "max"):
            period = "1y"

        def _quote():
            """Today's quote: latest vs previous close. Daily bars are the most
            reliable path; fast_info fills gaps when history is throttled."""
            from .yf_resilience import fetch_history, fetch_spot
            import yfinance as yf
            latest = prev_close = None
            df = fetch_history(ticker, "5d")
            if df is not None and len(df) >= 1:
                closes = df["Close"].dropna()
                if len(closes) >= 1:
                    latest = float(closes.iloc[-1])
                if len(closes) >= 2:
                    prev_close = float(closes.iloc[-2])
            if latest is None:
                latest = fetch_spot(ticker)
            if prev_close is None:
                try:
                    pc = yf.Ticker(ticker).fast_info.previous_close
                    prev_close = float(pc) if pc else None
                except Exception:
                    pass
            q = {"latest_price": round(latest, 2) if latest is not None else None,
                 "previous_close": round(prev_close, 2) if prev_close is not None else None}
            if latest is not None and prev_close:
                q["day_change"] = round(latest - prev_close, 2)
                q["day_change_pct"] = round((latest - prev_close) / prev_close * 100, 2)
            return q

        def _period_stats():
            from .yf_resilience import fetch_history
            if period in ("1d", "5d"):
                # Intraday bars for the session view.
                df = fetch_history(ticker, period, interval="5m" if period == "1d" else "30m")
            else:
                df = fetch_history(ticker, period)
            if df is None or df.empty:
                return None
            closes = df["Close"].dropna()
            if closes.empty:
                return None
            first, last = float(closes.iloc[0]), float(closes.iloc[-1])
            return {
                "period_open": round(first, 2),
                "period_latest": round(last, 2),
                "period_pct_change": round((last - first) / first * 100, 2) if first else None,
                "period_high": round(float(df["High"].max()), 2),
                "period_low": round(float(df["Low"].min()), 2),
                "start": str(df.index[0]),
                "end": str(df.index[-1]),
            }

        # The name resolves concurrently with the price lookups, so identifying
        # the issuer costs no wall-clock time.
        quote, stats, identity = await asyncio.gather(
            asyncio.to_thread(_quote),
            asyncio.to_thread(_period_stats),
            asyncio.to_thread(listing_identity, ticker),
        )
        name, currency = identity
        if quote.get("latest_price") is None and not stats:
            return tool_error(f"No price data for {ticker} right now.", ticker=ticker)
        payload = {"ticker": ticker, "period": period, **quote}
        if name:
            # Named explicitly so a wrong-ticker guess is visible in the result.
            payload["company"] = name
        if currency:
            # Read by findings.py so the chat chip is denominated correctly.
            payload["currency"] = currency
        if stats:
            payload["period_stats"] = stats
        else:
            payload["note"] = "Period history temporarily unavailable; quote fields are live."
        return tool_ok(**payload)


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
        raw = (ticker or "").strip().upper()
        # Accept bare crypto symbols/names (BTC, Bitcoin) → Yahoo BTC-USD pair.
        normalized = normalize_crypto_symbol(raw)
        if normalized:
            ticker = normalized
        elif raw.endswith("-USD"):
            # A -USD pair our map doesn't know: the base may need Yahoo's
            # numeric suffix (TAO-USD is a dead asset; Bittensor is
            # TAO22974-USD). Resolve live before computing on wrong data.
            from .crypto_utils import search_crypto_symbol
            resolved = await asyncio.to_thread(
                search_crypto_symbol, raw.rsplit("-", 1)[0]
            )
            ticker = resolved or raw
        else:
            ticker = raw

        def _calc():
            from .yf_resilience import fetch_history
            df = fetch_history(ticker, "1y")
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
        "Get recent financial news headlines — market-wide OR for one company. "
        "Pass `ticker` for COMPANY-SPECIFIC headlines: the fast way to answer "
        "'why did AAPL drop today', 'any news on NVDA' (much faster than the "
        "full analyze_news pipeline). Omit ticker for broad market context: "
        "'what happened in the markets today', 'what's moving markets'. "
        "Returns recent headlines with sources, timestamps, and links."
    )
    parameters = {
        "type": "object",
        "properties": {
            "topic": {"type": "string",
                      "description": "Optional focus for market-wide news, e.g. 'Federal Reserve', 'oil'. Default broad market.",
                      "default": "stock market today"},
            "ticker": {"type": "string",
                       "description": "Optional ticker for company-specific headlines, e.g. 'AAPL'."},
        },
    }
    repeatable = True  # ticker news + market news in one turn is legitimate

    async def execute(self, topic: str = "stock market today", ticker: str = "") -> str:
        import asyncio

        # Shared with the report pipeline's SerpAPI fallback (src/yf_news.py).
        from yf_news import fetch_ticker_news, fetch_topic_news

        topic = (topic or "stock market today").strip()
        ticker = (ticker or "").strip().upper()
        if ticker:
            ticker = normalize_crypto_symbol(ticker) or ticker

        def _news():
            if ticker:
                return fetch_ticker_news(ticker, count=10)
            return fetch_topic_news(topic, count=10)

        news = await asyncio.to_thread(_news)
        subject = ticker or topic
        if not news:
            return tool_ok(subject=subject, headlines=[],
                           note="No fresh headlines retrieved; answer from your general knowledge and say it's not live.")
        return tool_ok(subject=subject, headlines=news[:8])


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
