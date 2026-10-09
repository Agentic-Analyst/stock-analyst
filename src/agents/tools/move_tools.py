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
    try:
        import yfinance as yf
        price = getattr(yf.Ticker(ticker).fast_info, "last_price", None)
        return float(price) if price else None
    except Exception:
        return None


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

        daily, live, market, identity = await asyncio.gather(
            asyncio.to_thread(fetch_history, ticker, _HISTORY),
            asyncio.to_thread(_live_price, ticker),
            asyncio.to_thread(fetch_history, "^GSPC", _HISTORY),
            asyncio.to_thread(listing_identity, ticker),
        )
        name, currency = identity

        from src.price_moves import describe_move
        move = describe_move(daily, live, window=window, direction=direction,
                             history_days_requested=_HISTORY_DAYS,
                             index_closes=None if market is None else market["Close"])
        if not move:
            return tool_error(f"No price history for {ticker} right now.", ticker=ticker)

        start, end = news_window(move)
        sessions = [str(stamp.date()) for stamp in daily.index] if daily is not None else []
        focus = [d["date"] for d in move.get("biggest_days") or []]

        from src.company_news import news_for_move
        from src.sec_activity import filing_activity
        crypto = is_crypto_symbol(ticker)
        news, filings = await asyncio.gather(
            asyncio.to_thread(news_for_move, ticker, name, start, end, sessions, focus),
            asyncio.to_thread(lambda: None if crypto else filing_activity(ticker, start, end)),
        )
        payload: Dict[str, Any] = {"ticker": ticker, **move}
        if name:
            payload["company"] = name
        if currency:
            payload["currency"] = currency
        payload["news"] = news
        if filings:
            payload["sec_filings"] = filings
        payload["how_to_read"] = (
            "episode = the largest move in the window; biggest_days = the sessions that made it "
            "(volume_vs_average 2+ means heavy trading); news.by_session lists articles under the "
            "first session they could have moved (after-close news moves the next session); "
            "sp500_same_dates_pct separates a stock-specific move from the market's. A Form 144 is "
            "a notice of intent to sell, not a completed sale."
        )
        return tool_ok(**payload)


def build_move_tools() -> List[Tool]:
    return [ExplainPriceMoveTool()]
