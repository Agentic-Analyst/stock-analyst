"""Publication-date parsing and strict freshness filtering for research news.

Ingestion time is deliberately *not* treated as publication time.  A stale
article can be discovered or re-ingested today; using ``createdAt`` as its date
would make it look current forever.  Relative source dates (``"5 days ago"``)
are anchored to the scrape/ingestion timestamp, because interpreting them
relative to every future analysis run has the same failure mode.
"""
from __future__ import annotations

import math
import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple


_ABSOLUTE_FORMATS = (
    "%b %d, %Y",
    "%B %d, %Y",
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%m/%d/%Y",
    "%d %b %Y",
    "%d %B %Y",
)
_RELATIVE_RE = re.compile(
    r"^\s*(?:about\s+|approximately\s+)?(\d+)\s+"
    r"(minute|hour|day|week|month|year)s?\s+ago\s*$",
    re.IGNORECASE,
)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def parse_datetime(value: Any) -> Optional[datetime]:
    """Parse an absolute date/time without inventing one on failure."""
    if isinstance(value, datetime):
        return _utc(value)
    if isinstance(value, date):
        return datetime.combine(value, time.min, tzinfo=timezone.utc)
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        if not math.isfinite(number):
            return None
        # Accept real Unix timestamps, not arbitrary counters.
        if number > 10_000_000_000:
            number /= 1000.0
        if 0 < number < 10_000_000_000:
            try:
                return datetime.fromtimestamp(number, tz=timezone.utc)
            except (OverflowError, OSError, ValueError):
                return None
        return None
    raw = str(value).strip()
    if not raw:
        return None
    iso = raw.replace("Z", "+00:00")
    try:
        return _utc(datetime.fromisoformat(iso))
    except ValueError:
        pass
    # Some feeds include a clock/time-zone suffix after a conventional date.
    candidates = (raw, raw.split(" at ", 1)[0].strip())
    for candidate in candidates:
        for fmt in _ABSOLUTE_FORMATS:
            try:
                return datetime.strptime(candidate, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    return None


def _relative_datetime(raw: str, anchor: Optional[datetime]) -> Optional[datetime]:
    if anchor is None:
        return None
    text = raw.strip().lower()
    if text in ("today", "just now"):
        return anchor
    if text == "yesterday":
        return anchor - timedelta(days=1)
    match = _RELATIVE_RE.match(text)
    if not match:
        return None
    amount = int(match.group(1))
    unit = match.group(2).lower()
    if unit == "minute":
        delta = timedelta(minutes=amount)
    elif unit == "hour":
        delta = timedelta(hours=amount)
    elif unit == "day":
        delta = timedelta(days=amount)
    elif unit == "week":
        delta = timedelta(weeks=amount)
    elif unit == "month":
        delta = timedelta(days=30 * amount)
    else:
        delta = timedelta(days=365 * amount)
    return anchor - delta


def article_publication_datetime(article: Dict[str, Any]) -> Optional[datetime]:
    """Return the source publication time, or ``None`` when it is unknown."""
    for field in ("publish_date", "published_at", "publication_date", "date"):
        raw = article.get(field)
        parsed = parse_datetime(raw)
        if parsed is not None:
            return parsed
        if isinstance(raw, str) and raw.strip():
            anchor = None
            for anchor_field in ("scraped_at", "createdAt", "created_at"):
                anchor = parse_datetime(article.get(anchor_field))
                if anchor is not None:
                    break
            parsed = _relative_datetime(raw, anchor)
            if parsed is not None:
                return parsed
    return None


def filter_fresh_articles(
    articles: Iterable[Dict[str, Any]],
    *,
    max_age_days: int,
    minimum_articles: int,
    limit: Optional[int] = None,
    as_of: Optional[datetime] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Filter and newest-first sort articles using source publication dates."""
    now = _utc(as_of or datetime.now(timezone.utc))
    days = max(1, int(max_age_days))
    cutoff = now - timedelta(days=days)
    fresh: List[Tuple[datetime, Dict[str, Any]]] = []
    stale = unknown = future = 0
    scanned = 0
    # A small clock/feed-date allowance prevents tomorrow-dated evening pieces
    # from being rejected, while still surfacing truly future-dated data.
    future_limit = now + timedelta(days=1)
    for article in articles or []:
        scanned += 1
        published = article_publication_datetime(article)
        if published is None:
            unknown += 1
        elif published > future_limit:
            future += 1
        elif published < cutoff:
            stale += 1
        else:
            copy = dict(article)
            copy["_publication_datetime"] = published.isoformat()
            fresh.append((published, copy))
    fresh.sort(key=lambda pair: pair[0], reverse=True)
    selected = [article for _, article in fresh]
    if limit is not None:
        selected = selected[:max(0, int(limit))]
    dates = [published for published, _ in fresh]
    count = len(selected)
    status = "fresh" if count >= max(1, minimum_articles) else "limited" if count else "unavailable"
    metadata = {
        "status": status,
        "as_of": now.isoformat(),
        "cutoff": cutoff.isoformat(),
        "max_age_days": days,
        "minimum_articles": max(1, int(minimum_articles)),
        "candidates_scanned": scanned,
        "fresh_articles": count,
        "fresh_articles_before_limit": len(fresh),
        "stale_articles_excluded": stale,
        "unknown_date_articles_excluded": unknown,
        "future_date_articles_excluded": future,
        "newest_published_at": max(dates).isoformat() if dates else None,
        "oldest_published_at": min(dates).isoformat() if dates else None,
        "date_policy": "source publication date; ingestion time is not publication time",
    }
    return selected, metadata
