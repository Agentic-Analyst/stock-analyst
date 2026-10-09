"""
explain_price_move — the evidence for "why did X crash / jump / move".

One call returns what an analyst would pull before answering: the live quote,
the recent move the question is about (peak to trough, with the S&P 500 over
the same dates), the sessions that made it and their volume, the dated news
that could have moved each of those sessions (src/company_news.py) and the
SEC filings over the same days (src/sec_activity.py). The answer then names
the move and ties each driver to the day it hit the price, instead of
guessing from today's quote and a handful of headlines.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from .base import Tool, tool_error, tool_ok
from .crypto_utils import is_crypto_symbol, normalize_crypto_symbol

_HISTORY = "2y"
_HISTORY_DAYS = 730
_NEWS_LEAD_DAYS = 3


def _live_price(ticker: str) -> Optional[float]:
    from .yf_resilience import live_price
    return live_price(ticker)


# The fund a reader would compare the stock with: a sector-wide day reads
# differently from a company-specific one (SNDK and MU fell 4.9% and 4.8% on
# October 8 with the memory trade, after Samsung's results).
_INDUSTRY_FUNDS = {
    "Semiconductors": ("SMH", "semiconductor ETF"),
    "Semiconductor Equipment & Materials": ("SMH", "semiconductor ETF"),
    "Software - Infrastructure": ("IGV", "software ETF"),
    "Software - Application": ("IGV", "software ETF"),
    "Biotechnology": ("XBI", "biotech ETF"),
    "Banks - Regional": ("KRE", "regional bank ETF"),
    "Oil & Gas E&P": ("XOP", "oil & gas producers ETF"),
    "Gold": ("GDX", "gold miners ETF"),
}
_SECTOR_FUNDS = {
    "Technology": ("XLK", "technology sector ETF"),
    "Healthcare": ("XLV", "health care sector ETF"),
    "Financial Services": ("XLF", "financials sector ETF"),
    "Consumer Cyclical": ("XLY", "consumer discretionary sector ETF"),
    "Communication Services": ("XLC", "communication services sector ETF"),
    "Industrials": ("XLI", "industrials sector ETF"),
    "Consumer Defensive": ("XLP", "consumer staples sector ETF"),
    "Energy": ("XLE", "energy sector ETF"),
    "Utilities": ("XLU", "utilities sector ETF"),
    "Real Estate": ("XLRE", "real estate sector ETF"),
    "Basic Materials": ("XLB", "materials sector ETF"),
}


# The market a listing is measured against: Paris against the CAC 40, not the
# S&P 500 (LVMH's -9.3% slide read as stock-specific beside the S&P's +1.4%).
_HOME_INDEX = {
    ".PA": ("^FCHI", "CAC 40"), ".L": ("^FTSE", "FTSE 100"), ".DE": ("^GDAXI", "DAX"),
    ".AS": ("^AEX", "AEX"), ".SW": ("^SSMI", "SMI"), ".MI": ("FTSEMIB.MI", "FTSE MIB"),
    ".MC": ("^IBEX", "IBEX 35"), ".T": ("^N225", "Nikkei 225"), ".HK": ("^HSI", "Hang Seng"),
    ".SS": ("000001.SS", "Shanghai Composite"), ".SZ": ("399001.SZ", "Shenzhen Component"),
    ".NS": ("^NSEI", "Nifty 50"), ".BO": ("^BSESN", "Sensex"), ".KS": ("^KS11", "KOSPI"),
    ".TW": ("^TWII", "Taiwan Weighted"), ".TO": ("^GSPTSE", "S&P/TSX Composite"),
    ".AX": ("^AXJO", "S&P/ASX 200"),
}
_UNNAMED_QUOTE_TYPES = {"ETF", "MUTUALFUND", "CRYPTOCURRENCY", "INDEX", "CURRENCY", "FUTURE"}


def market_index(ticker: str) -> tuple:
    """(symbol, name) of the benchmark a move is compared with."""
    if ticker.endswith("-USD"):
        return ("BTC-USD", "Bitcoin") if ticker != "BTC-USD" else ("^GSPC", "S&P 500")
    for suffix, index in _HOME_INDEX.items():
        if ticker.endswith(suffix):
            return index
    return ("^GSPC", "S&P 500")


def _identity(ticker: str) -> Dict[str, Any]:
    """Name, currency, sector, industry, exchange time zone and quote type, from one lookup."""
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info or {}
    except Exception:
        info = {}
    return {"name": info.get("longName") or info.get("shortName") or None,
            "currency": info.get("currency") or None, "sector": info.get("sector") or None,
            "industry": info.get("industry") or None,
            "exchange_tz": info.get("exchangeTimezoneName") or None,
            "quote_type": (info.get("quoteType") or "").upper() or None}


def session_open(last_session: str, exchange_tz: Optional[str], now=None) -> bool:
    """Whether the listing's last bar is today's session and it is still trading."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from src.company_news import _CLOSES
    close = _CLOSES.get(exchange_tz or "")
    if not close:
        return False      # a 24/7 market or an unknown exchange: no partial flag
    try:
        local = (now or datetime.now(tz=ZoneInfo("UTC"))).astimezone(ZoneInfo(exchange_tz))
    except Exception:
        return False
    return local.date().isoformat() == last_session and (local.hour, local.minute) < close


def sector_fund(sector: Optional[str], industry: Optional[str], currency: Optional[str]) -> Optional[tuple]:
    """US sector funds compare a US listing; a home-market line gets none."""
    if currency not in (None, "USD"):
        return None
    return _INDUSTRY_FUNDS.get(industry or "") or _SECTOR_FUNDS.get(sector or "")


def _live_frame(symbol: str):
    """Daily bars with today's live price in place of a missing evening close."""
    from src.price_moves import with_live_close
    from .yf_resilience import fetch_history
    frame = fetch_history(symbol, _HISTORY)
    if frame is None:
        return None
    return with_live_close(frame, _live_price(symbol))


def _iso(day: str) -> date:
    return date.fromisoformat(day[:10])


def news_window(move: Dict[str, Any]) -> tuple:
    """From a few days before the move began (or its first big day) to today."""
    starts = [d["date"] for d in move.get("biggest_days") or []]
    episode = move.get("episode") or {}
    if episode.get("start_date"):
        starts.append(episode["start_date"])
    end = _iso(move.get("as_of_session") or date.today().isoformat())
    start = min((_iso(d) for d in starts), default=end) - timedelta(days=_NEWS_LEAD_DAYS)
    return start, max(end, date.today())


class ExplainPriceMoveTool(Tool):
    name = "explain_price_move"
    description = (
        "The evidence for WHY a stock moved: 'why did X crash / drop / fall / tank', "
        "'why is X up / surging', 'what happened to X', 'why did X move today'. One "
        "call returns the live quote and today's change, the recent move (peak to "
        "trough or trough to peak in the window, with the S&P 500 over the same "
        "dates), the biggest sessions with their volume versus normal, performance "
        "over 5d/1mo/3mo/ytd/1y, the 52-week high and drawdown (and the first close "
        "for a recent IPO), the dated news for the sessions that moved, each article "
        "with its source and summary, and insider/company SEC filings over the same "
        "days (Form 144 sale notices, Form 4 trades, 8-Ks, offerings). Prefer it to "
        "get_prices + get_global_news for any why-did-it-move question."
    )
    parameters = {
        "type": "object",
        "properties": {
            "ticker": {"type": "string", "description": "Ticker symbol (resolve non-US names first)."},
            "window": {"type": "string",
                       "description": "How far back to look for the move: 5d, 1mo (default), 3mo, 6mo, 1y. "
                                      "Use a longer window when the user asks about a slide over months.",
                       "default": "1mo"},
            "direction": {"type": "string",
                          "description": "down for crash/drop/fall/plunge, up for surge/jump/rally, auto otherwise.",
                          "default": "auto"},
        },
        "required": ["ticker"],
    }

    async def execute(self, ticker: str, window: str = "1mo", direction: str = "auto") -> str:
        import asyncio
        from .data_tools import listing_identity
        from .yf_resilience import fetch_history

        ticker = (ticker or "").strip().upper()
        ticker = normalize_crypto_symbol(ticker) or ticker
        window = (window or "1mo").strip().lower()
        direction = (direction or "auto").strip().lower()
        if direction not in ("up", "down", "auto"):
            direction = "auto"

        index_symbol, index_name = market_index(ticker)
        daily, live, market, identity = await asyncio.gather(
            asyncio.to_thread(fetch_history, ticker, _HISTORY),
            asyncio.to_thread(_live_price, ticker),
            asyncio.to_thread(_live_frame, index_symbol),
            asyncio.to_thread(_identity, ticker),
        )
        name, currency = identity.get("name"), identity.get("currency")
        crypto = is_crypto_symbol(ticker) or identity.get("quote_type") == "CRYPTOCURRENCY"
        exchange_tz = "UTC" if crypto else (identity.get("exchange_tz") or "America/New_York")
        last_session = str(daily.index[-1].date()) if daily is not None and len(daily) else ""

        from src.price_moves import day_change, describe_move, index_change
        move = describe_move(daily, live, window=window, direction=direction,
                             history_days_requested=_HISTORY_DAYS,
                             index_closes=None if market is None else market["Close"],
                             index_name=index_name,
                             session_open=session_open(last_session, exchange_tz))
        if not move:
            return tool_error(f"No price history for {ticker} right now.", ticker=ticker)

        start, end = news_window(move)
        sessions = [str(stamp.date()) for stamp in daily.index] if daily is not None else []
        focus = [d["date"] for d in move.get("biggest_days") or []]
        recent = sessions[-2:]

        from src.company_news import news_for_move
        from src.sec_activity import filing_activity
        fund = None if crypto else sector_fund(identity.get("sector"), identity.get("industry"), currency)
        require_name = identity.get("quote_type") not in _UNNAMED_QUOTE_TYPES and not crypto
        news, filings, fund_frame = await asyncio.gather(
            asyncio.to_thread(news_for_move, ticker, name, start, end, sessions, focus, recent,
                              exchange_tz, require_name),
            asyncio.to_thread(lambda: None if not require_name else filing_activity(ticker, start, end)),
            asyncio.to_thread(lambda: _live_frame(fund[0]) if fund else None),
        )
        payload: Dict[str, Any] = {"ticker": ticker, **move}
        if name:
            payload["company"] = name
        if currency:
            payload["currency"] = currency
        market_today = {"index": index_name, "index_today_pct": day_change(market)}
        if fund and fund_frame is not None:
            market_today[f"{fund[0]}_today_pct"] = day_change(fund_frame)
            payload["sector_fund"] = {"symbol": fund[0], "name": fund[1],
                                      "sector": identity.get("sector"), "industry": identity.get("industry")}
            episode = payload.get("episode")
            if episode:
                episode[f"{fund[0]}_same_dates_pct"] = index_change(
                    fund_frame["Close"], episode["start_date"], episode["end_date"])
        payload["market_today"] = market_today
        payload["news"] = news
        if filings:
            payload["sec_filings"] = filings
        payload["how_to_read"] = (
            "episode = the largest move in the window; biggest_days = the sessions that made it "
            "(volume_vs_average 2+ means heavy trading); news.by_session lists articles under the "
            "first session they could have moved (after-close news moves the next session unless it "
            "looks back at the day); news.coverage is the span of days the news feed reaches; "
            "market_same_dates_pct and the sector fund's same-dates/today moves separate a "
            "stock-specific move from the market's or the sector's; from_window_high is the fall "
            "from the window's high to now; a session_in_progress has only part of its volume. "
            "A Form 144 is a notice of intent to sell, not a completed sale."
        )
        return tool_ok(**payload)


def build_move_tools() -> List[Tool]:
    return [ExplainPriceMoveTool()]
