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


# Yahoo's news endpoint is the only source the chat's quick news tool had. On
# 17 Nov 2026 it answered "YAHOO! FINANCE IS CURRENTLY DOWN" and 9 of 10
# replayed overview answers said "I couldn't retrieve fresh headlines". Google
# News' public search feed (no key) fills in when Yahoo returns nothing.
GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"


def parse_google_news(xml_bytes: bytes, count: int = 10) -> List[dict]:
    """Items from a Google News RSS document, newest first, in Yahoo's item shape."""
    import xml.etree.ElementTree as ET
    from email.utils import parsedate_to_datetime
    items = []
    for it in ET.fromstring(xml_bytes).findall("./channel/item"):
        title = (it.findtext("title") or "").strip()
        publisher = (it.findtext("source") or "").strip() or None
        if publisher and title.endswith(" - " + publisher):
            title = title[: -len(" - " + publisher)]
        try:
            when = parsedate_to_datetime(it.findtext("pubDate") or "").astimezone(timezone.utc)
        except Exception:
            when = None
        if title:
            items.append({"title": title, "publisher": publisher, "link": it.findtext("link"),
                          "published": when.isoformat() if when else None, "_when": when})
    items.sort(key=lambda i: i["_when"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    for i in items:
        i.pop("_when", None)
    return items[:count]


def fetch_google_news(query: str, count: int = 10, days: int = 30, timeout: int = 10) -> List[dict]:
    """Headlines from Google News search for the last ``days`` days; empty on any failure."""
    import urllib.parse
    import urllib.request
    url = GOOGLE_NEWS_RSS + "?" + urllib.parse.urlencode(
        {"q": f"{query} when:{days}d", "hl": "en-US", "gl": "US", "ceid": "US:en"})
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; VYNN research)"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return parse_google_news(r.read(), count)
    except Exception:
        return []


def _company_name(ticker: str) -> Optional[str]:
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info or {}
        return info.get("shortName") or info.get("longName")
    except Exception:
        return None


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
    if not items:
        name = _company_name(ticker)
        items = fetch_google_news(f'"{name}"' if name else f"{ticker} stock", count)
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
    if not items:
        items = fetch_google_news(topic, count)
    return items[:count]
