"""
Dated company news for explaining a price move.

The chat's quick news lookup (yf_news.fetch_ticker_news) returns Yahoo's latest
six to ten headlines, titles only. Asked on October 8 why Cerebras crashed,
it had two listicles and a week-old piece: the September 30 stories that moved
the stock ("Cerebras Stock Falls as 19.4 Million-Share Unlock Hits", "Cerebras
stock slides as Nvidia reportedly powers OpenAI's 'Ultrafast' tier") had
already scrolled out of the feed. Finnhub's company-news endpoint takes a date
range and returns each article's summary, so the stories can be read for the
sessions that moved.

Articles are ranked by whether they are about the company (its name or ticker
in the headline), duplicates of one story are folded into one item with the
number of outlets that carried it, and each item is assigned to the trading
session it could have moved: news after the 4pm close moves the next session.
Never raises; None means the provider could not be asked.
"""

from __future__ import annotations

import html
import json
import os
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence

FINNHUB_NEWS_URL = "https://finnhub.io/api/v1/company-news"
_SUMMARY_CHARS = 320
_MAX_ITEMS = 24
_PER_SESSION = 5

# Name endings that headlines drop ("Cerebras", not "Cerebras Systems Inc.").
_SUFFIXES = re.compile(
    r"[,.]?\s+(?:inc|incorporated|corp|corporation|co|company|ltd|limited|plc|"
    r"holdings?|group|systems?|technologies|technology|n\.?v|s\.?a|ag|se)\.?$",
    re.I,
)
# A first word too common to identify a company on its own.
_GENERIC_FIRST = {
    "american", "advanced", "general", "united", "first", "international", "global",
    "national", "the", "new", "applied", "digital", "data", "energy", "royal",
}
# Roundups and comparisons mention many tickers and explain none of them.
_ROUNDUP = re.compile(
    r"\bstocks?\s+(?:that|to\s+(?:buy|watch)|moving)\b|\bwhich\b.*\bbetter\s+buy\b|"
    r"\bvs\.?\s|\bversus\b|\bwinners\s+and\s+losers\b|\bcompany\s+news\s+for\b|"
    r"\btop\s+(?:\d+|wall\s+street)\b|\b\d+\s+(?:top\s+|best\s+|undervalued\s+)?\w*\s*stocks\b|"
    r"\bundercovered\b|\bbet\s+on\s+the\s+same\b",
    re.I,
)

try:  # Eastern time decides which session an article belongs to.
    from zoneinfo import ZoneInfo
    _EASTERN = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover - tzdata missing
    _EASTERN = timezone(timedelta(hours=-4))


def company_names(name: Optional[str], ticker: str) -> List[str]:
    """Strings that identify the company in a headline."""
    names = []
    base = (ticker or "").split(".")[0].split("-")[0].upper()
    if len(base) >= 2:
        names.append(base)
    clean = (name or "").strip()
    while clean and _SUFFIXES.search(clean):
        clean = _SUFFIXES.sub("", clean).strip()
    if clean:
        names.append(clean)
        first = clean.split()[0].strip(",.")
        if len(first) >= 4 and first.lower() not in _GENERIC_FIRST and first != clean:
            names.append(first)
    return names


def _mentions(text: str, names: Sequence[str]) -> bool:
    for n in names:
        if n.isupper() and len(n) <= 5:
            # Tickers match as whole words only: "MU" is not in "MUST".
            if re.search(rf"(?<![A-Za-z]){re.escape(n)}(?![A-Za-z])", text):
                return True
        elif re.search(rf"\b{re.escape(n)}\b", text, re.I):
            return True
    return False


def _tokens(title: str) -> set:
    return {w for w in re.findall(r"[a-z0-9']+", title.lower()) if len(w) > 2}


def _similar(a: set, b: set) -> bool:
    return bool(a and b) and len(a & b) / len(a | b) >= 0.5


def session_for(published: datetime, sessions: Sequence[str]) -> Optional[str]:
    """The first trading session an article could move.

    Before the 4pm close it is that day's session (pre-market news moves the
    open); after the close it is the next session. ``sessions`` are the
    trading dates from the price history, oldest first, as YYYY-MM-DD.
    """
    local = published.astimezone(_EASTERN)
    day = local.date().isoformat()
    after_close = local.hour >= 16
    for s in sessions:
        if s > day or (s == day and not after_close):
            return s
    return None   # after the latest session: it moves the next one


def normalize_finnhub(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        title = html.unescape(str(row.get("headline") or "")).strip()
        stamp = row.get("datetime")
        if not title or not isinstance(stamp, (int, float)) or stamp <= 0:
            continue
        summary = html.unescape(str(row.get("summary") or "")).strip()
        if summary.startswith("http"):
            summary = ""   # some providers put the link where the summary goes
        out.append({
            "published": datetime.fromtimestamp(stamp, tz=timezone.utc),
            "title": title,
            "source": row.get("source") or None,
            "summary": summary[:_SUMMARY_CHARS] + ("…" if len(summary) > _SUMMARY_CHARS else ""),
            "url": row.get("url") or None,
        })
    return out


def rank_and_align(items: List[Dict[str, Any]], names: Sequence[str],
                   sessions: Sequence[str], focus_sessions: Sequence[str] = (),
                   max_items: int = _MAX_ITEMS) -> Dict[str, Any]:
    """Relevant, de-duplicated articles grouped by the session they could move.

    ``focus_sessions`` are the big-move days: their articles are kept first so
    a busy news week cannot crowd out the day the stock actually fell.
    """
    scored = []
    for item in items:
        title, summary = item["title"], item.get("summary") or ""
        score = 0
        if _mentions(title, names):
            score += 3
        elif _mentions(summary, names):
            score += 1
        if _ROUNDUP.search(title):
            score -= 2
        if score <= 0:
            continue
        scored.append((score, item))

    # One story, many outlets: keep the earliest report, count the others.
    stories: List[Dict[str, Any]] = []
    for score, item in sorted(scored, key=lambda pair: pair[1]["published"]):
        tokens = _tokens(item["title"])
        match = next((s for s in stories if _similar(s["_tokens"], tokens)), None)
        if match:
            match["outlets"] += 1
            match["_score"] = max(match["_score"], score) + 0.5
            if not match.get("summary") and item.get("summary"):
                match["summary"] = item["summary"]
            continue
        stories.append({**item, "_tokens": tokens, "_score": float(score), "outlets": 1})

    focus = set(focus_sessions)
    for story in stories:
        story["session"] = session_for(story["published"], sessions) or "after latest session"
    by_session: Dict[str, List[Dict[str, Any]]] = {}
    for story in sorted(stories, key=lambda s: (-(s["session"] in focus), -s["_score"], s["published"])):
        bucket = by_session.setdefault(story["session"], [])
        if len(bucket) < _PER_SESSION and sum(map(len, by_session.values())) < max_items:
            bucket.append(story)

    def public(story: Dict[str, Any]) -> Dict[str, Any]:
        local = story["published"].astimezone(_EASTERN)
        row = {"published_et": local.strftime("%Y-%m-%d %H:%M ET"), "title": story["title"],
               "source": story["source"], "summary": story.get("summary") or None,
               "url": story["url"]}
        if story["outlets"] > 1:
            row["outlets"] = story["outlets"]
        return row

    ordered = sorted(by_session.items(), key=lambda kv: kv[0])
    return {
        "articles_considered": len(items),
        "articles_about_company": len(scored),
        "by_session": [{"session": s, "big_move_day": s in focus,
                        "articles": [public(x) for x in rows]} for s, rows in ordered],
    }


def fetch_finnhub_news(ticker: str, start: date, end: date, timeout: float = 12.0) -> Optional[List[Dict[str, Any]]]:
    """Finnhub company news between two dates; None without a key or on error."""
    key = (os.getenv("FINNHUB_API_KEY") or "").strip()
    if not key or not ticker or "-" in ticker or "." in ticker:
        # Finnhub's company news covers US listings; a coin or a home-market
        # line falls back to Yahoo.
        return None
    try:
        import requests
        response = requests.get(
            FINNHUB_NEWS_URL,
            params={"symbol": ticker.upper(), "from": start.isoformat(), "to": end.isoformat(), "token": key},
            timeout=timeout,
            headers={"User-Agent": "VYNN/1.0 (+https://vynnai.com)"},
        )
        if response.status_code != 200:
            return None
        rows = response.json()
        return rows if isinstance(rows, list) else None
    except Exception:
        return None


def yahoo_items(ticker: str, count: int = 10) -> List[Dict[str, Any]]:
    """Yahoo's latest headlines in the same shape (no summaries)."""
    from src.yf_news import fetch_ticker_news
    out = []
    for item in fetch_ticker_news(ticker, count=count) or []:
        try:
            published = datetime.fromisoformat(str(item.get("published")).replace("Z", "+00:00"))
        except ValueError:
            continue
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        out.append({"published": published, "title": item.get("title") or "",
                    "source": item.get("publisher"), "summary": "", "url": item.get("link")})
    return [i for i in out if i["title"]]


def news_for_move(ticker: str, name: Optional[str], start: date, end: date,
                  sessions: Sequence[str], focus_sessions: Sequence[str] = ()) -> Dict[str, Any]:
    """Ranked, session-aligned articles for a ticker over a date range."""
    names = company_names(name, ticker)
    rows = fetch_finnhub_news(ticker, start, end)
    if rows:
        items, source = normalize_finnhub(rows), "Finnhub company news (headline + summary)"
    else:
        items, source = yahoo_items(ticker), "Yahoo Finance latest headlines (titles only)"
    result = rank_and_align(items, names, sessions, focus_sessions)
    result["source"] = source
    result["matched_names"] = names
    return result
