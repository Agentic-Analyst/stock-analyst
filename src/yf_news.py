#!/usr/bin/env python3
"""
yf_news.py — Yahoo Finance news fetcher, shared by the chat tool
(GetGlobalNewsTool) and the report pipeline's SerpAPI fallback.

Kept as a flat src-root module so both import styles used in this repo
(`from yf_news import ...` inside src/, `from src.yf_news import ...`
from the repo root) can reach it.
"""

import time
from datetime import datetime, timezone
from typing import List, Optional


def _fmt_ts(ts) -> Optional[str]:
    """Unix seconds -> ISO 8601 UTC, or None."""
    try:
        if ts:
            return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()
    except Exception:
        pass
    return None


def extract_news_item(n: dict) -> Optional[dict]:
    """
    Normalize one yfinance news item. Items come in two shapes: flat (older)
    and nested under "content" (newer). Handle both.
    """
    c = n.get("content") if isinstance(n.get("content"), dict) else n
    title = c.get("title")
    if not title:
        return None
    provider = c.get("provider") if isinstance(c.get("provider"), dict) else {}
    link = (
        c.get("canonicalUrl", {}).get("url")
        if isinstance(c.get("canonicalUrl"), dict)
        else c.get("link")
    )
    return {
        "title": title,
        "publisher": c.get("publisher") or provider.get("displayName"),
        "link": link,
        "published": c.get("pubDate") or _fmt_ts(c.get("providerPublishTime")),
    }


def fetch_ticker_news(ticker: str, count: int = 10) -> List[dict]:
    """
    Fetch recent headlines for a ticker via yfinance, with one short retry.
    Returns [{title, publisher, link, published}] — possibly empty, never None.
    """
    import yfinance as yf

    items: List[dict] = []
    for attempt in range(2):
        try:
            raw = yf.Ticker(ticker).news or []
            if not raw:
                raw = yf.Search(ticker, news_count=count).news or []
            for n in raw:
                item = extract_news_item(n)
                if item:
                    items.append(item)
            break
        except Exception:
            if attempt == 0:
                time.sleep(1.2)
            continue
    return items[:count]


def fetch_topic_news(topic: str, count: int = 10) -> List[dict]:
    """Fetch recent market/topic headlines via yfinance Search."""
    import yfinance as yf

    items: List[dict] = []
    try:
        raw = yf.Search(topic, news_count=count).news or []
        for n in raw:
            item = extract_news_item(n)
            if item:
                items.append(item)
    except Exception:
        pass
    return items[:count]
