"""Company announcements from the Australian exchange (ASX), for "why did it move" on .AX listings.

US listings get their filings from SEC EDGAR (src/sec_activity.py). An ASX company
discloses through the exchange's announcements platform instead, and the news feed
often has nothing for a mid-cap: on 17 Nov 2026 VYNN could not say why Hansen
Technologies (HSN.AX) fell 21.2% on 19 Aug 2026, while the exchange shows its FY26
results and a "Leadership Changes" notice released at 8:32 am that morning.

The exchange publishes each company's announcements for a calendar year on a public
page. This module reads that page, keeps the announcements inside the move's
window, and files each one under the first trading session it could have moved:
released before the 4 pm Sydney close, the same day's session; after it, the next.
"""
from __future__ import annotations

import html
import re
import urllib.request
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Sequence

_PAGE = ("https://www.asx.com.au/asx/v2/statistics/announcements.do"
         "?by=asxCode&asxCode={code}&timeframe=Y&year={year}")
_PDF = "https://www.asx.com.au/asx/v2/statistics/displayAnnouncement.do?display=pdf&idsId={ids}"
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; VYNN research)"}
_ROW = re.compile(r"<tr>(.*?)</tr>", re.S)
_CELL = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
_CLOSE_MINUTES = 16 * 60          # the ASX's main session closes at 4:00 pm Sydney time
MAX_ITEMS = 40


def asx_code(ticker: str) -> Optional[str]:
    """'HSN.AX' -> 'HSN'; None for any other listing."""
    t = (ticker or "").strip().upper()
    if t.endswith(".AX") and 1 <= len(t) - 3 <= 6:
        return t[:-3]
    return None


def _text(fragment: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def parse_page(page: str) -> List[Dict[str, Any]]:
    """Every announcement row on one year's page: date, time, headline, price-sensitive, link."""
    out = []
    for row in _ROW.findall(page or ""):
        cells = _CELL.findall(row)
        if len(cells) < 3:
            continue
        stamp = _text(cells[0])
        m = re.match(r"(\d{2})/(\d{2})/(\d{4})\s+(\d{1,2}):(\d{2})\s*([ap]m)", stamp, re.I)
        if not m:
            continue
        day, month, year, hour, minute, ampm = m.groups()
        hour = int(hour) % 12 + (12 if ampm.lower() == "pm" else 0)
        headline_cell = cells[2]
        headline = _text(re.split(r"<br\s*/?>", headline_cell, maxsplit=1)[0])
        ids = re.search(r"idsId=(\d+)", headline_cell)
        out.append({
            "date": f"{year}-{month}-{day}",
            "time_sydney": f"{hour:02d}:{minute}",
            "headline": headline,
            "price_sensitive": 'title="price sensitive"' in cells[1],
            "url": _PDF.format(ids=ids.group(1)) if ids else None,
        })
    return out


def _session_for(item: Dict[str, Any], sessions: Sequence[str]) -> Optional[str]:
    """The first trading session the announcement could have moved."""
    hh, mm = (int(x) for x in item["time_sydney"].split(":"))
    after_close = hh * 60 + mm >= _CLOSE_MINUTES
    for s in sessions:
        if s > item["date"] or (s == item["date"] and not after_close):
            return s
    return None


# Off unless switched on. The ASX makes company announcements freely available
# for private and personal use; commercial use, including aggregating and
# redistributing them, needs the ASX's express written authority. VYNN is a
# commercial service: set VYNN_ASX_ANNOUNCEMENTS=1 only once that is held (or
# replace the source with a licensed feed).
_ENABLE = "VYNN_ASX_ANNOUNCEMENTS"


def enabled() -> bool:
    import os
    return os.getenv(_ENABLE, "").strip().lower() in ("1", "true", "yes", "on")


def announcements_for_move(ticker: str, start: date, end: date, sessions: Sequence[str],
                           fetch=None) -> Optional[Dict[str, Any]]:
    """Announcements between ``start`` and ``end`` for an ASX listing, filed by session.

    Returns None for a non-ASX ticker, when the lookup is not switched on, or
    when the exchange cannot be reached, so the caller simply omits the field.
    ``fetch(url) -> str`` is injectable for tests.
    """
    code = asx_code(ticker)
    if not code or not enabled():
        return None
    fetch = fetch or _get
    items: List[Dict[str, Any]] = []
    try:
        for year in range(start.year, end.year + 1):
            items += parse_page(fetch(_PAGE.format(code=code, year=year)))
    except Exception:
        return None
    lo, hi = start.isoformat(), end.isoformat()
    items = sorted((i for i in items if lo <= i["date"] <= hi),
                   key=lambda i: (i["date"], i["time_sydney"]))
    by_session: Dict[str, List[Dict[str, Any]]] = {}
    for item in items:
        session = _session_for(item, sessions)
        item["session"] = session
        if session and item["price_sensitive"]:
            by_session.setdefault(session, []).append(
                {k: item[k] for k in ("time_sydney", "headline", "url")})
    return {
        "source": "ASX company announcements",
        "price_sensitive_by_session": by_session,
        "all": [{k: i[k] for k in ("date", "time_sydney", "headline", "price_sensitive", "session")}
                for i in items][-MAX_ITEMS:],
        "note": "Times are Sydney time. An announcement released before the 4 pm close can move "
                "that day's session; after it, the next session. Price-sensitive is the exchange's "
                "own flag.",
    }


def _get(url: str, timeout: int = 15) -> str:
    with urllib.request.urlopen(urllib.request.Request(url, headers=_HEADERS), timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore")
