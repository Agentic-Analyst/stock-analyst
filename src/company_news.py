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
        # A search result dated by its day alone sits at local noon: say the day.
        stamp = local.strftime("%Y-%m-%d") if story.get("time_unknown") else local.strftime("%Y-%m-%d %H:%M %Z")
        if story.get("date_approximate"):
            stamp = f"around {stamp}"
        row = {"published": stamp, "title": story["title"],
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


# ---- a dated search for a move older than the feed reaches ------------------
#
# Hansen Technologies fell 21.2% on 19 Aug 2026 on its FY26 results and a
# leadership change. Asked in November, VYNN could not say why: the company
# news feed covers mainly US listings, and the fallback (Yahoo's latest
# headlines) reaches back a few days. One Google News search for the company's
# name around the session that moved most finds the coverage of the day.
_DATED_NEWS_MAX = 8
_DATED_TIMESTAMP = re.compile(
    r"(\d{1,2})/(\d{1,2})/(\d{4}),\s*(\d{1,2}):(\d{2})\s*([AP]M)(?:,\s*([+-])(\d{2})(\d{2}))?", re.I)
_DATED_DAY = re.compile(
    r"\b\d{1,2}/\d{1,2}/\d{4}\b|\b\d{4}-\d{2}-\d{2}\b|"
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}\b|"
    r"\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+\d{4}\b",
    re.I,
)
_LEGAL_ENDING = re.compile(
    r",?\s+(?:Inc|Incorporated|Corp|Corporation|Co|Company|Ltd|Limited|plc|PLC|AG|SA|S\.A|NV|N\.V|SE|"
    r"Holdings?|Group|Pty|LLC|L\.P|LP)\.?$", re.I)
# A quote-system name ("HANSEN TEC FPO") finds nothing, but is billed.
_CODE_NAME = re.compile(r"\b(?:FPO|ORD|CDI|NPV|UNITS?|STAPLED|DEF|REG)\b")


def search_name(name: Optional[str]) -> Optional[str]:
    """The company's name as the press writes it, or None when there is none to search."""
    clean = (name or "").strip()
    if clean.lower().startswith("the "):
        clean = clean[4:].strip()
    # Legal endings only: "Hansen Technologies Limited" is "Hansen
    # Technologies" in the press, and "Hansen" alone would find anything.
    while clean and _LEGAL_ENDING.search(clean):
        clean = _LEGAL_ENDING.sub("", clean).strip(" ,.")
    characters = re.sub(r"[^A-Za-z0-9]", "", clean)
    if len(characters) < 2 or _CODE_NAME.search(clean) or (clean.isupper() and len(clean.split()) > 1):
        return None
    return clean


def _visible(text: str) -> str:
    """The text without invisible format marks: Google put right-to-left marks inside "19/08/2026"."""
    import unicodedata
    return "".join(ch for ch in text if unicodedata.category(ch) != "Cf")


def _numeric_days(first: int, second: int, year: int) -> List[date]:
    """Both readings of "a/b/yyyy": Google writes the day first or the month first by locale."""
    out = []
    for month, day_ in ((first, second), (second, first)):
        try:
            candidate = date(year, month, day_)
        except ValueError:
            continue
        if candidate not in out:
            out.append(candidate)
    return out


_RELATIVE_AGE = re.compile(r"\b(\d+|an?|one)\s+(minute|hour|day|week|month)s?\s+ago\b", re.I)


def _relative_days(text: str, fetched_at: datetime, zone) -> Optional[tuple]:
    """The exchange-local days a relative age ("2 weeks ago", "yesterday") allows.

    Counted from the moment of the search, not its date: "1 week ago" read at
    10 pm in New York (the next day in UTC) moved a 5 Nov article to 6 Nov.
    "n units ago" means more than n and at most n+1 units before the search.
    """
    if re.search(r"\byesterday\b", text, re.I):
        oldest, newest = fetched_at - timedelta(days=2), fetched_at
    else:
        match = _RELATIVE_AGE.search(text)
        if not match:
            return None
        count = 1 if match.group(1).lower() in ("a", "an", "one") else int(match.group(1))
        unit = match.group(2).lower()
        if unit == "month":
            oldest = fetched_at - timedelta(days=31 * (count + 1))
            newest = fetched_at - timedelta(days=28 * count)
        else:
            step = {"minute": timedelta(minutes=1), "hour": timedelta(hours=1),
                    "day": timedelta(days=1), "week": timedelta(days=7)}[unit]
            oldest, newest = fetched_at - step * (count + 1), fetched_at - step * count
    return oldest.astimezone(zone).date(), newest.astimezone(zone).date()


def _search_result_time(row: Dict[str, Any], lo: date, hi: date, zone,
                        fetched_at: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """A result's time, or its day at local noon when only the day is given; None outside the days.

    The search covers three days, so of the two readings of "08/09/2026" at
    most one lies inside them: that one is the date, whatever the locale. An
    exact date outside the days rules the result out. A relative age ("2 weeks
    ago") is used only when no exact date is given and the search's time is
    known; the article is then placed on the session if the age allows it,
    marked approximate.
    """
    from dateutil import parser

    def inside(d: date) -> bool:
        return lo <= d <= hi

    exact_outside = False
    for raw in (row.get("iso_date"), row.get("date")):
        if not raw:
            continue
        text = _visible(str(raw))
        full = _DATED_TIMESTAMP.search(text)
        if full:
            first, second, year, hour, minute, ampm, sign, oh, om = full.groups()
            hour = int(hour) % 12 + (12 if ampm.upper() == "PM" else 0)
            offset = timedelta(hours=int(oh or 0), minutes=int(om or 0)) * (-1 if sign == "-" else 1)
            for d in _numeric_days(int(first), int(second), int(year)):
                stamp = datetime(d.year, d.month, d.day, hour, int(minute), tzinfo=timezone(offset))
                if inside(stamp.astimezone(zone).date()):
                    return {"published": stamp.astimezone(timezone.utc), "time_unknown": False}
            exact_outside = True
            continue
        try:
            iso = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if iso.tzinfo is not None and ("T" in text or ":" in text):
                if inside(iso.astimezone(zone).date()):
                    return {"published": iso.astimezone(timezone.utc), "time_unknown": False}
                exact_outside = True
                continue
        except ValueError:
            pass
        match = _DATED_DAY.search(text)
        if not match:
            continue
        numeric = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", match.group(0))
        if numeric:
            days = _numeric_days(int(numeric.group(1)), int(numeric.group(2)), int(numeric.group(3)))
        else:
            try:
                days = [parser.parse(match.group(0)).date()]
            except (ValueError, OverflowError):
                continue
        day_only = next((d for d in days if inside(d)), None)
        if day_only is not None:
            noon = datetime(day_only.year, day_only.month, day_only.day, 12, tzinfo=zone)
            return {"published": noon.astimezone(timezone.utc), "time_unknown": True}
        exact_outside = True
    # Only a relative age ("2 weeks ago": Robinhood's ten results for 5 Nov
    # 2026, all dropped). The search is limited to the three days, so a result
    # whose age allows them is placed on the session searched, marked approximate.
    if exact_outside or fetched_at is None:
        return None
    for raw in (row.get("date"),):
        if not raw:
            continue
        span = _relative_days(_visible(str(raw)), fetched_at, zone)
        if span is None:
            continue
        first, last = max(span[0], lo), min(span[1], hi)
        if first > last:
            return None
        session = lo + timedelta(days=1)
        chosen = session if first <= session <= last else (first if session < first else last)
        noon = datetime(chosen.year, chosen.month, chosen.day, 12, tzinfo=zone)
        return {"published": noon.astimezone(timezone.utc), "time_unknown": True, "date_approximate": True}
    return None


def _dated_cache_name(name: str, day: date) -> str:
    import hashlib
    return "dated_news_" + hashlib.sha1(f"{name}|{day.isoformat()}".encode()).hexdigest()[:20]


def dated_news(name: Optional[str], day: date, api_key: Optional[str] = None, search=None,
               exchange_tz: Optional[str] = "America/New_York") -> Optional[List[Dict[str, Any]]]:
    """Google News articles naming the company from the day before a session to the day after.

    One SerpAPI search, cached (a past day's results do not change). None when
    no search was made (no key, no searchable name, a failure); [] when it
    found nothing. ``search(params) -> dict`` is injectable for tests.
    """
    query = search_name(name)
    key = api_key or os.getenv("SERPAPI_API_KEY")
    if not query or not key:
        return None
    zone = _zone(exchange_tz)
    lo, hi = day - timedelta(days=1), day + timedelta(days=1)
    from src.agents.fm import netcache
    cache_name = _dated_cache_name(query, day)
    recent = (datetime.now(timezone.utc).date() - day).days <= 7
    # The search's own rows are cached, not their times: a day-only date is
    # placed at noon on the exchange's clock, which differs between listings.
    cached = netcache.cache_get(cache_name, 6 * 3600 if recent else 30 * 86400)
    rows, fetched_at = None, None
    if isinstance(cached, dict) and isinstance(cached.get("rows"), list):
        rows = cached["rows"]
        try:
            stamp = datetime.fromisoformat(str(cached.get("fetched_at")))
            fetched_at = stamp if stamp.tzinfo else None
        except ValueError:
            fetched_at = None      # relative ages are then not used
    elif isinstance(cached, list):
        rows = cached              # an old entry: when it was searched is unknown
    if rows is None:
        fetched_at = datetime.now(timezone.utc)
        params = {"q": f'"{query}"', "tbm": "nws", "num": _DATED_NEWS_MAX,
                  "tbs": f"cdr:1,cd_min:{lo:%m/%d/%Y},cd_max:{hi:%m/%d/%Y}", "api_key": key}
        import logging
        logging.getLogger(__name__).info(
            "serpapi dated news search: %s, %s to %s", query, lo.isoformat(), hi.isoformat())
        try:
            if search is None:
                from serpapi import GoogleSearch
                client = GoogleSearch(params)
                client.timeout = 8
                result = client.get_dict()
            else:
                result = search(params)
        except Exception:
            return None
        if not isinstance(result, dict) or (
                "error" in result and "hasn't returned any results" not in str(result["error"])):
            return None
        rows = [{k: row.get(k) for k in ("title", "link", "source", "date", "iso_date", "snippet")}
                for row in result.get("news_results") or [] if isinstance(row, dict)]
        netcache.cache_put(cache_name, {"fetched_at": fetched_at.isoformat(), "rows": rows})
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = html.unescape(str(row.get("title") or "")).strip()
        when = _search_result_time(row, lo, hi, zone, fetched_at=fetched_at)
        if not title or when is None:
            continue
        source = row.get("source")
        summary = html.unescape(str(row.get("snippet") or "")).strip()
        out.append({
            **when,
            "title": title,
            "source": (source.get("name") if isinstance(source, dict) else source) or None,
            "summary": summary[:_SUMMARY_CHARS] + ("…" if len(summary) > _SUMMARY_CHARS else ""),
            "url": row.get("link") or None,
        })
    return out[:_DATED_NEWS_MAX]


def _reaches(items: List[Dict[str, Any]], day: date) -> bool:
    """Whether the feed has anything from the day before the session to the day after."""
    return any(day - timedelta(days=1) <= i["published"].date() <= day + timedelta(days=1) for i in items)


def _coverage(items: List[Dict[str, Any]], exchange_tz: Optional[str]) -> Optional[Dict[str, str]]:
    zone = _zone(exchange_tz)
    stamps = [i["published"] for i in items]
    if not stamps:
        return None
    return {"earliest": min(stamps).astimezone(zone).date().isoformat(),
            "latest": max(stamps).astimezone(zone).date().isoformat()}


def news_for_move(ticker: str, name: Optional[str], start: date, end: date,
                  sessions: Sequence[str], focus_sessions: Sequence[str] = (),
                  recent_sessions: Sequence[str] = (), exchange_tz: Optional[str] = "America/New_York",
                  require_name: bool = True,
                  session_moves: Optional[Dict[str, float]] = None,
                  dated_search=None) -> Dict[str, Any]:
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
    # The session that moved most, when the feed has nothing near it: one dated
    # search. Companies only (not a fund, an index, a currency or a coin), and
    # never for the last sessions, which the feed covers.
    feed = items
    dated = None
    moves = session_moves or {}
    if focus_sessions and require_name and not ticker.upper().endswith("-USD"):
        biggest = max(focus_sessions, key=lambda s: abs(moves.get(s) or 0.0))
        try:
            top = date.fromisoformat(str(biggest))
        except ValueError:
            top = None
        if top and str(top) not in set(recent_sessions) and not _reaches(items, top):
            found = dated_news(name, top, search=dated_search, exchange_tz=exchange_tz)
            if found is not None:
                dated = {"session": str(top), "query": search_name(name), "articles": len(found),
                         "days": f"{top - timedelta(days=1)} to {top + timedelta(days=1)}"}
                items = items + [i for i in found if i["published"] >= lo]
    result = rank_and_align(items, names, sessions, focus_sessions, recent_sessions=recent_sessions,
                            exchange_tz=exchange_tz, require_name=require_name,
                            session_moves=session_moves)
    if dated:
        source += (f"; plus a Google News search for {dated['days']} "
                   f"({dated['articles']} article{'s' if dated['articles'] != 1 else ''} found)")
        result["dated_search"] = dated
        # The days the feed reaches, not the search: an August search does not
        # mean the feed covers August to November.
        result["coverage"] = _coverage(feed, exchange_tz)
    result["source"] = source
    result["matched_names"] = names
    return result
