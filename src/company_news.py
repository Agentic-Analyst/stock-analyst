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
_MAX_ITEMS = 28
_PER_SESSION = 5
_PER_QUIET_SESSION = 3
_GUARANTEED = 2
_SAME_STORY = timedelta(hours=36)

# Name endings that headlines drop ("Cerebras", not "Cerebras Systems Inc.").
_SUFFIXES = re.compile(
    r"(?:[,.]?\s+(?:inc|incorporated|corp|corporation|co|company|ltd|limited|plc|"
    r"holdings?|group|systems?|technologies|technology|n\.?v|s\.?a|ag|se|trust|etf)\.?"
    r"|\s+(?:and|&)|\.com)$",
    re.I,
)
# A first word too common to identify a company on its own.
_GENERIC_FIRST = {
    "american", "advanced", "general", "united", "first", "international", "global",
    "national", "the", "new", "applied", "digital", "data", "energy", "royal",
    "state", "spdr", "invesco", "ishares", "vanguard", "vaneck", "grayscale", "proshares",
}
# What headlines call a company that its listing name does not say.
_ALIASES = {
    "GOOGL": ["Google"], "GOOG": ["Google"], "META": ["Facebook"], "BRK-B": ["Berkshire"],
    "BRK-A": ["Berkshire"], "IBM": ["IBM"], "XOM": ["Exxon"], "TSM": ["TSMC"],
    "LLY": ["Lilly"], "JNJ": ["J&J"], "PG": ["P&G"],
}
# Roundups and comparisons mention many tickers and explain none of them.
_ROUNDUP = re.compile(
    r"\bstocks?\s+(?:that|to\s+(?:buy|watch)|moving)\b|\bwhich\b.*\bbetter\s+buy\b|"
    r"\bvs\.?\s|\bversus\b|\bwinners\s+and\s+losers\b|\bcompany\s+news\s+for\b|"
    r"\btop\s+(?:\d+|wall\s+street)\b|\b\d+\s+(?:top\s+|best\s+|undervalued\s+)?\w*\s*stocks\b|"
    r"\bundercovered\b|\bbet\s+on\s+the\s+same\b",
    re.I,
)

from zoneinfo import ZoneInfo

_EASTERN = ZoneInfo("America/New_York")


def company_names(name: Optional[str], ticker: str) -> List[str]:
    """Strings that identify the company in a headline.

    "The Boeing Company" is "Boeing" in a headline, "Eli Lilly and Company"
    is "Eli Lilly", "Amazon.com, Inc." is "Amazon" and Alphabet is "Google":
    matching the listing name as written threw away every Goldman Sachs and
    Boeing story.
    """
    names = []
    symbol = (ticker or "").upper()
    base = symbol.split(".")[0].split("-")[0]
    if len(base) >= 2:
        names.append(base)
    clean = (name or "").strip()
    if clean.lower().startswith("the "):
        clean = clean[4:].strip()
    while clean and _SUFFIXES.search(clean):
        clean = _SUFFIXES.sub("", clean).strip(" ,.")
    if clean:
        names.append(clean)
        first = clean.split()[0].strip(",.")
        if len(first) >= 4 and first.lower() not in _GENERIC_FIRST and first != clean:
            names.append(first)
    for alias in _ALIASES.get(symbol, []):
        if alias not in names:
            names.append(alias)
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
    """Content words, without quotes, possessives or a plural s."""
    words = re.findall(r"[a-z0-9]+", title.lower().replace("'s ", " "))
    return {w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w
            for w in words if len(w) > 2}


_UP = {"soars", "soared", "jumps", "jumped", "surges", "surged", "rises", "rose", "rallies",
       "rallied", "gains", "gained", "climbs", "climbed", "up", "higher", "upgrade", "upgrades", "raises",
       "rebounds", "rebounded", "pops", "popped", "spikes", "spiked", "boost", "boosts", "lifts"}
_DOWN = {"plunges", "plunged", "falls", "fell", "drops", "dropped", "slides", "slid", "sinks",
         "sank", "tumbles", "tumbled", "slumps", "slumped", "down", "lower", "downgrade",
         "downgrades", "cuts", "crash", "crashes", "crashed", "slips", "slipped", "tanks", "tanked",
         "plummets", "plummeted", "sheds", "loses", "declines", "declined", "selloff", "retreats", "sink"}


def describes_move(title: str, change_pct: Optional[float]) -> bool:
    """Whether a headline reports the session's move ("Cerebras Stock Falls
    as 19.4 Million-Share Unlock Hits" on a -8.9% day), not an opinion piece
    or a product story that happened to run that day."""
    if not change_pct:
        return False
    words = set(re.findall(r"[a-z]+", (title or "").lower()))
    return bool(words & (_DOWN if change_pct < 0 else _UP))


def _figures(title: str) -> set:
    return set(re.findall(r"\d[\d,.]*", title))


def _similar(a: str, b: str) -> bool:
    """Two headlines for one story: mostly the same words, the same figures
    and the same direction. Citi's $45 target is not Mizuho's $43, and a
    $42.6 million insider sale is not a $1.1 million one."""
    ta, tb = _tokens(a), _tokens(b)
    if not (ta and tb) or len(ta & tb) / len(ta | tb) < 0.6:
        return False
    if _figures(a) != _figures(b):
        return False
    wa, wb = set(re.findall(r"[a-z]+", a.lower())), set(re.findall(r"[a-z]+", b.lower()))
    return not ((wa & _UP and wb & _DOWN) or (wa & _DOWN and wb & _UP))


# Local close (hour, minute) by exchange time zone; a 24-hour market has none.
_CLOSES = {
    "America/New_York": (16, 0), "America/Toronto": (16, 0), "Europe/London": (16, 30),
    "Europe/Paris": (17, 30), "Europe/Berlin": (17, 30), "Europe/Amsterdam": (17, 30),
    "Europe/Zurich": (17, 30), "Europe/Madrid": (17, 30), "Europe/Milan": (17, 30),
    "Asia/Tokyo": (15, 30), "Asia/Hong_Kong": (16, 0), "Asia/Shanghai": (15, 0),
    "Asia/Kolkata": (15, 30), "Asia/Seoul": (15, 30), "Asia/Taipei": (13, 30),
    "Australia/Sydney": (16, 0),
}
# Written after the close ABOUT the close: "Why Sandisk Stock Dropped on
# Thursday", "Stocks That Explain Today's Market". They explain that day.
_RETROSPECTIVE = re.compile(
    r"\bwhy\b.*\b(?:today|on\s+(?:monday|tuesday|wednesday|thursday|friday))\b|"
    r"\bexplain\s+today'?s\s+market\b|\b(?:today|this\s+session)'?s?\s+(?:biggest\s+)?movers\b|"
    r"\b(?:soared|jumped|surged|rose|rallied|plunged|fell|dropped|slid|sank|tumbled|slumped)\s+"
    r"(?:\S+\s+)?(?:today|on\s+(?:monday|tuesday|wednesday|thursday|friday))\b",
    re.I,
)


def _zone(name: Optional[str]):
    try:
        return ZoneInfo(name) if name else _EASTERN
    except Exception:
        return _EASTERN


def session_for(published: datetime, sessions: Sequence[str], title: str = "",
                exchange_tz: Optional[str] = "America/New_York") -> Optional[str]:
    """The trading session an article belongs to.

    Before the listing's close it is that day's session (pre-market news moves
    the open); after the close it moves the next session, unless the headline
    looks back at the day that just closed. Times are the exchange's own: a
    Paris listing closes at 17:30 Paris time. A market without a close (crypto,
    exchange_tz "UTC") keeps each article on its UTC date. ``sessions`` are the
    trading dates from the price history, oldest first, as YYYY-MM-DD.
    """
    zone = _zone(exchange_tz)
    local = published.astimezone(zone)
    day = local.date().isoformat()
    close = _CLOSES.get(exchange_tz or "")
    after_close = bool(close) and (local.hour, local.minute) >= close
    if after_close and title and _RETROSPECTIVE.search(title):
        earlier = [s for s in sessions if s <= day]
        if earlier:
            return earlier[-1]
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
                   max_items: int = _MAX_ITEMS, recent_sessions: Sequence[str] = (),
                   exchange_tz: Optional[str] = "America/New_York",
                   require_name: bool = True,
                   session_moves: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """Relevant, de-duplicated articles grouped by the session they could move.

    ``focus_sessions`` are the big-move days and ``recent_sessions`` the last
    few: both are covered before quieter days, so a busy news week cannot
    crowd out the day the stock actually fell or today. A fund or a coin has
    no company name to look for (``require_name`` False): its feed is about
    the market it tracks, so every article counts.
    """
    scored = []
    for item in items:
        title, summary = item["title"], item.get("summary") or ""
        score = 0 if require_name else 1
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
    # Only within a day and a half: "Cerebras stock falls" on September 30
    # and again on October 1 are two days' news, not one story.
    stories: List[Dict[str, Any]] = []
    for score, item in sorted(scored, key=lambda pair: pair[1]["published"]):
        match = next((s for s in stories
                      if item["published"] - s["published"] <= _SAME_STORY
                      and _similar(s["title"], item["title"])), None)
        if match:
            match["outlets"] += 1
            match["_score"] = max(match["_score"], score) + 0.5
            if not match.get("summary") and item.get("summary"):
                match["summary"] = item["summary"]
            continue
        stories.append({**item, "_score": float(score), "outlets": 1})

    focus = set(focus_sessions)
    recent = set(recent_sessions)
    moves = session_moves or {}
    for story in stories:
        story["session"] = (session_for(story["published"], sessions, story["title"], exchange_tz)
                            or "after latest session")
        # The story that reports the day's move leads that day, ahead of an
        # earlier opinion piece ("Cerebras: Forgotten AI Chip Stock").
        story["_matches_move"] = describes_move(story["title"], moves.get(story["session"]))
        if story["_matches_move"]:
            story["_score"] += 2

    def tier(story):
        if story["session"] in focus or story["session"] in recent or story["session"] == "after latest session":
            return 0
        return 1

    ranked = sorted(stories, key=lambda s: (tier(s), -s["_score"], s["published"]))
    by_session: Dict[str, List[Dict[str, Any]]] = {}
    chosen = set()
    # First every big-move session and the latest sessions get their top two
    # stories, so a week of heavy coverage on one day cannot crowd out the day
    # the stock fell (SNDK: five rally days took all 24 slots and the October 7
    # "Toshiba storage fears" story behind the selloff never reached the
    # model). Then the rest fill by rank.
    for limit in (_GUARANTEED, None):
        for story in ranked:
            if id(story) in chosen or len(chosen) >= max_items:
                continue
            bucket = by_session.get(story["session"], [])
            cap = _GUARANTEED if limit else (_PER_SESSION if tier(story) == 0 else _PER_QUIET_SESSION)
            if limit and tier(story) != 0:
                continue
            if len(bucket) >= cap:
                continue
            by_session.setdefault(story["session"], []).append(story)
            chosen.add(id(story))
    for bucket in by_session.values():
        bucket.sort(key=lambda s: (-s["_score"], s["published"]))

    zone = _zone(exchange_tz)

    def public(story: Dict[str, Any]) -> Dict[str, Any]:
        local = story["published"].astimezone(zone)
        row = {"published": local.strftime("%Y-%m-%d %H:%M %Z"), "title": story["title"],
               "source": story["source"], "summary": story.get("summary") or None,
               "url": story["url"]}
        if story["outlets"] > 1:
            row["outlets"] = story["outlets"]
        if _ROUNDUP.search(story["title"]):
            # Kept for context, never a day's headline.
            row["roundup"] = True
        if story["_matches_move"]:
            row["reports_the_move"] = True
        return row

    ordered = sorted(by_session.items(), key=lambda kv: kv[0])
    stamps = [i["published"] for i in items]
    return {
        "articles_considered": len(items),
        "articles_about_company": len(scored),
        # The days the feed reaches: a session before `earliest` has no news
        # because the feed does not go back that far, not because nothing
        # happened.
        "coverage": ({"earliest": min(stamps).astimezone(zone).date().isoformat(),
                      "latest": max(stamps).astimezone(zone).date().isoformat()} if stamps else None),
        "by_session": [{"session": s, "big_move_day": s in focus,
                        "articles": [public(x) for x in rows]} for s, rows in ordered],
    }


def finnhub_symbol(ticker: str) -> Optional[str]:
    """Finnhub's spelling of a US listing (BRK-B is BRK.B); None for others."""
    symbol = (ticker or "").strip().upper()
    if not symbol or "." in symbol or symbol.endswith("-USD") or "=" in symbol or symbol.startswith("^"):
        # A home-market line (MC.PA), a coin, a currency or an index.
        return None
    return symbol.replace("-", ".")


FINNHUB_MARKET_NEWS_URL = "https://finnhub.io/api/v1/news"
_CHUNK_DAYS = 7
_MAX_CHUNKS = 8


def _finnhub_get(url: str, params: Dict[str, Any], key: str, timeout: float) -> Optional[list]:
    try:
        import requests
        response = requests.get(
            url, params=params, timeout=timeout,
            # In a header, as peer_comps and analyst_consensus send it: a URL
            # with the key in it ends up in exception messages and logs.
            headers={"User-Agent": "VYNN/1.0 (+https://vynnai.com)", "X-Finnhub-Token": key},
        )
        if response.status_code != 200:
            return None
        rows = response.json()
        return rows if isinstance(rows, list) else None
    except Exception:
        return None


def fetch_finnhub_news(ticker: str, start: date, end: date, timeout: float = 12.0) -> Optional[List[Dict[str, Any]]]:
    """Finnhub company news between two dates; None without a key or on error.

    Asked a week at a time, newest first: one call stops at about 230
    articles, so for a heavily covered name (Goldman Sachs: 419 in a month)
    a single month-long call reached back only to September 23 and missed
    the sessions that moved the stock.
    """
    key = (os.getenv("FINNHUB_API_KEY") or "").strip()
    symbol = finnhub_symbol(ticker)
    if not key or not symbol:
        return None
    rows: Dict[Any, Dict[str, Any]] = {}
    answered = False
    hi = end
    for _ in range(_MAX_CHUNKS):
        if hi < start:
            break
        lo = max(start, hi - timedelta(days=_CHUNK_DAYS - 1))
        chunk = _finnhub_get(FINNHUB_NEWS_URL, {"symbol": symbol, "from": lo.isoformat(),
                                                "to": hi.isoformat()}, key, timeout)
        if chunk is None:
            break
        answered = True
        for row in chunk:
            if isinstance(row, dict):
                rows[row.get("id") or (row.get("headline"), row.get("datetime"))] = row
        hi = lo - timedelta(days=1)
    return list(rows.values()) if answered else None


def fetch_finnhub_crypto_news(timeout: float = 12.0) -> Optional[List[Dict[str, Any]]]:
    """Finnhub's crypto market news (the latest ~100, with summaries)."""
    key = (os.getenv("FINNHUB_API_KEY") or "").strip()
    if not key:
        return None
    return _finnhub_get(FINNHUB_MARKET_NEWS_URL, {"category": "crypto"}, key, timeout)


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
                  sessions: Sequence[str], focus_sessions: Sequence[str] = (),
                  recent_sessions: Sequence[str] = (), exchange_tz: Optional[str] = "America/New_York",
                  require_name: bool = True,
                  session_moves: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """Ranked, session-aligned articles for a ticker over a date range."""
    names = company_names(name, ticker)
    if ticker.upper().endswith("-USD"):
        # A coin has no company news: Finnhub's crypto market feed (the last
        # day or two, with summaries) and Yahoo's headlines for the pair.
        coin = re.sub(r"\s+USD$", "", name or "", flags=re.I).strip()
        names = [n for n in [ticker.upper().split("-")[0], coin] if n]
        items = normalize_finnhub(fetch_finnhub_crypto_news() or []) + yahoo_items(ticker)
        source = "Finnhub crypto market news (headline + summary) and Yahoo Finance headlines"
        rows = None
    else:
        rows = fetch_finnhub_news(ticker, start, end)
    if rows:
        items, source = normalize_finnhub(rows), "Finnhub company news (headline + summary)"
    elif not ticker.upper().endswith("-USD"):
        items, source = yahoo_items(ticker), "Yahoo Finance latest headlines (titles only, recent days only)"
    lo = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
    items = [i for i in items if i["published"] >= lo]
    result = rank_and_align(items, names, sessions, focus_sessions, recent_sessions=recent_sessions,
                            exchange_tz=exchange_tz, require_name=require_name,
                            session_moves=session_moves)
    result["source"] = source
    result["matched_names"] = names
    return result
