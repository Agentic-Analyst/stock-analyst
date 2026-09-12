"""Freshness checks for the financial statements underlying a valuation."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional


def _timestamp(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        try:
            parsed = datetime.strptime(raw[:10], "%Y-%m-%d")
        except ValueError:
            return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def financial_statement_freshness(
    data: Dict[str, Any], *, as_of: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Assess the newest annual period; scrape time cannot make statements new."""
    now = as_of or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    try:
        max_age = max(365, int(os.getenv("FINANCIAL_STATEMENT_MAX_AGE_DAYS", "550") or 550))
    except ValueError:
        max_age = 550
    statements = (data or {}).get("financial_statements") or {}
    required = ("income_statement", "balance_sheet", "cash_flow")
    periods_by_statement = {}
    missing = []
    for name in required:
        rows = statements.get(name) or {}
        parsed = {}
        if isinstance(rows, dict):
            for period in rows:
                stamp = _timestamp(period)
                # These are historical actual statements. A future column is
                # an estimate or bad provider timestamp and cannot prove that
                # the valuation inputs are current.
                if stamp is not None and stamp <= now + timedelta(days=1):
                    parsed[stamp.date()] = str(period)
        if not parsed:
            missing.append(name)
        periods_by_statement[name] = parsed
    if missing:
        return {
            "status": "unavailable",
            "as_of": now.isoformat(),
            "latest_period": None,
            "age_days": None,
            "max_age_days": max_age,
            "reason": (
                "No parseable actual period was available for: "
                + ", ".join(missing) + "."
            ),
        }
    common = set.intersection(*(
        set(periods_by_statement[name]) for name in required
    ))
    if not common:
        return {
            "status": "unavailable",
            "as_of": now.isoformat(),
            "latest_period": None,
            "age_days": None,
            "max_age_days": max_age,
            "reason": (
                "No common actual period was present across the income statement, "
                "balance sheet, and cash-flow statement."
            ),
        }
    latest_date = max(common)
    latest = datetime.combine(latest_date, datetime.min.time(), tzinfo=timezone.utc)
    label = periods_by_statement[required[0]][latest_date]
    age = max(0, (now - latest).days)
    stale = age > max_age
    return {
        "status": "stale" if stale else "current",
        "as_of": now.isoformat(),
        "latest_period": label,
        "age_days": age,
        "max_age_days": max_age,
        "reason": (
            f"Latest annual financial period is {age} days old, beyond the {max_age}-day limit."
            if stale else None
        ),
    }
