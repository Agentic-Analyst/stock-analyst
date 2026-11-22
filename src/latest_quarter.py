"""Keep a company's twelve-month sales current after it reports results (22 Nov 2026).

VYNN's model starts from the last four reported quarters (financial_period_bridge.build_ttm_bridge), read from
Yahoo's quarter-by-quarter tables. Those tables lag a company's results by days to weeks. NVIDIA reported its October
quarter on 17 Nov 2026 (sales $115.8B); on 21-22 Nov Yahoo's table still ended in July (the newest column existed but
its sales were blank), so the model started from $303B instead of $362B, set analysts' fresh forecasts against stale
sales (next-year growth +89% instead of about +58%) and placed NVIDIA half-way through its fiscal year instead of
three-quarters. The bridge still counted as current: 114 days old, under the 150-day limit.

This module looks at two fresher sources and returns a ``fresh_revenue`` record when either has a newer complete
quarter than the bridge:

1. The SEC's structured figures (XBRL company facts), once the quarterly or annual report is filed. US filers only.
2. Yahoo's summary (``mostRecentQuarter``, ``totalRevenue``), which carried NVIDIA's new quarter within about four days.

When neither has the new quarter yet but the company has filed a results release (an 8-K with item 2.02) for a later
quarter, it returns ``results_pending`` so the model and every surface can say its figures predate those results.

Only the twelve-month revenue and the date it runs to are refreshed, in a separate record. Margins, reinvestment, the
balance sheet and every period label keep the bridge's own four quarters, so no ratio mixes quarters. Never raises: on
any failure the caller keeps the bridge as it was.
"""
from __future__ import annotations

import json
import math
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
_CONCEPT_URL = "https://data.sec.gov/api/xbrl/companyconcept/CIK{cik:010d}/us-gaap/{tag}.json"
# Revenue tags US filers use; companies move between them over the years, so all are read and merged.
_REVENUE_TAGS = (
    "Revenues",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
    "SalesRevenueNet",
)
_CACHE_SECONDS = 6 * 3600
# A results release more than this many days after the bridge's quarter end is about a later quarter. A company's
# release for a quarter comes within about 90 days of its end (NVIDIA: 22 to 31 days; slower annual reports up to ~90),
# while the next quarter's release cannot come before about 91 + 15 days.
_LATER_RELEASE_DAYS = 95
# A source's quarter counts as newer only when it ends at least this long after the bridge's (one quarter is ~91 days;
# Yahoo dates NVIDIA's quarters to the month end, the SEC to the fiscal week end, a few days apart).
_NEWER_QUARTER_DAYS = 45
# Twelve-month revenue rarely moves outside this ratio in one quarter; outside it, a unit or source error is likelier.
_PLAUSIBLE_RATIO = (0.5, 2.5)


def enabled() -> bool:
    return os.getenv("VYNN_FRESH_RESULTS", "1").strip().lower() not in ("0", "false", "no", "off")


def _date(value: Any) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc).date()
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str) and len(value) >= 10:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


# ---------------------------------------------------------------- SEC structured figures

def quarters_from_facts(facts: Iterable[Dict[str, Any]]) -> Dict[date, Tuple[float, str, str]]:
    """{quarter end: (three-month revenue, form, filed)} from XBRL revenue facts.

    10-Q filings report each quarter's own three months; the fourth quarter appears only inside the 10-K's full
    year, so it is the year less the three quarters that fall inside it. Where several filings report the same span,
    the latest-filed value wins (later reports restate).
    """
    spans: Dict[Tuple[date, date], Tuple[float, str, str]] = {}
    for fact in facts or []:
        start, end, value = _date(fact.get("start")), _date(fact.get("end")), _number(fact.get("val"))
        if start is None or end is None or value is None or end <= start:
            continue
        filed = str(fact.get("filed") or "")
        key = (start, end)
        if key not in spans or filed >= spans[key][2]:
            spans[key] = (value, str(fact.get("form") or ""), filed)
    quarters: Dict[date, Tuple[float, str, str]] = {}
    for (start, end), row in spans.items():
        if 80 <= (end - start).days <= 100:
            quarters[end] = row
    for (start, end), (value, form, filed) in spans.items():
        if not 350 <= (end - start).days <= 380 or end in quarters:
            continue
        inside = [q for q in quarters if start < q < end and (q - start).days >= 80]
        if len(inside) == 3:
            quarters[end] = (value - sum(quarters[q][0] for q in inside), form, filed)
    return quarters


def twelve_months(quarters: Dict[date, Tuple[float, str, str]]) -> Optional[Dict[str, Any]]:
    """Twelve-month revenue from the latest four consecutive quarters, or None."""
    ends = sorted(quarters, reverse=True)[:4]
    if len(ends) < 4:
        return None
    gaps = [(a - b).days for a, b in zip(ends, ends[1:])]
    if any(not 80 <= gap <= 100 for gap in gaps):
        return None
    values = [quarters[end][0] for end in ends]
    if any(v <= 0 for v in values):
        return None
    latest = quarters[ends[0]]
    return {"revenue": sum(values), "period_end": ends[0].isoformat(),
            "quarter_ends": [e.isoformat() for e in ends], "form": latest[1], "filed": latest[2]}


def _sec_json(url: str, cache_name: str) -> Optional[Dict[str, Any]]:
    from src.agents.fm import netcache
    cached = netcache.cache_get(cache_name, _CACHE_SECONDS)
    if isinstance(cached, dict) and cached:
        return cached
    try:
        data = json.loads(netcache.http_get(url, timeout=10.0))
    except Exception as exc:  # a missing tag is a 404; anything else is a failed source
        if "404" in str(exc):
            netcache.cache_put(cache_name, {"missing": True})
        return None
    if isinstance(data, dict):
        netcache.cache_put(cache_name, data)
        return data
    return None


def _cik(ticker: str) -> Optional[int]:
    from src.sec_filer import _ciks
    try:
        return _ciks().get((ticker or "").strip().upper())
    except Exception:
        return None


def sec_twelve_month_revenue(ticker: str) -> Optional[Dict[str, Any]]:
    """The SEC's latest twelve-month revenue for a US filer, or None."""
    cik = _cik(ticker)
    if not cik:
        return None
    merged: Dict[date, Tuple[float, str, str]] = {}
    for tag in _REVENUE_TAGS:
        data = _sec_json(_CONCEPT_URL.format(cik=cik, tag=tag), f"sec_concept_{cik}_{tag}")
        facts = ((data or {}).get("units") or {}).get("USD") or []
        for end, row in quarters_from_facts(facts).items():
            if end not in merged or row[2] > merged[end][2]:
                merged[end] = row
    result = twelve_months(merged)
    if result:
        result["source"] = "sec_xbrl"
    return result


def sec_results_after(ticker: str, period_end: date) -> Optional[Dict[str, Any]]:
    """A results release (8-K item 2.02) filed for a quarter after ``period_end``, or None."""
    cik = _cik(ticker)
    if not cik:
        return None
    data = _sec_json(_SUBMISSIONS_URL.format(cik=cik), f"sec_submissions_recent_{cik}")
    recent = (((data or {}).get("filings") or {}).get("recent") or {})
    rows = zip(recent.get("form") or [], recent.get("filingDate") or [], recent.get("items") or [],
               recent.get("accessionNumber") or [])
    for form, filed, items, accession in rows:
        filed_on = _date(filed)
        if (str(form).startswith("8-K") and "2.02" in str(items or "")
                and filed_on and (filed_on - period_end).days > _LATER_RELEASE_DAYS):
            return {"filed": filed_on.isoformat(), "accession": accession, "form": form}
    return None


# ---------------------------------------------------------------- Yahoo's summary

def yahoo_twelve_month_revenue(info: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Yahoo summary's twelve-month revenue and the quarter it runs to, or None. Yahoo reports it in the
    statements' currency, the same unit as the bridge."""
    info = info or {}
    revenue, period = _number(info.get("totalRevenue")), _date(info.get("mostRecentQuarter"))
    if revenue is None or revenue <= 0 or period is None:
        return None
    return {"revenue": revenue, "period_end": period.isoformat(), "source": "yahoo_summary"}


# ---------------------------------------------------------------- the decision

def fresh_revenue(bridge: Dict[str, Any], ticker: str, info: Optional[Dict[str, Any]] = None, *,
                  use_sec: bool = True) -> Dict[str, Any]:
    """What a current bridge should know about results reported after its quarters.

    Returns {} (nothing newer), {"fresh_revenue": {...}} (a newer complete quarter), or {"results_pending": {...}}
    (results released for a later quarter, figures not yet in any structured source).
    """
    try:
        if not enabled() or not isinstance(bridge, dict) or bridge.get("status") != "current":
            return {}
        period = _date(bridge.get("latest_period"))
        base = _number((bridge.get("normalized") or {}).get("revenue"))
        if period is None or base is None or base <= 0:
            return {}
        candidates: List[Dict[str, Any]] = []
        sec = sec_twelve_month_revenue(ticker) if use_sec else None
        if sec:
            candidates.append(sec)
        yahoo = yahoo_twelve_month_revenue(info)
        if yahoo:
            candidates.append(yahoo)
        newer = [c for c in candidates if (_date(c["period_end"]) - period).days >= _NEWER_QUARTER_DAYS
                 and _PLAUSIBLE_RATIO[0] <= c["revenue"] / base <= _PLAUSIBLE_RATIO[1]]
        if newer:
            latest_end = max(_date(c["period_end"]) for c in newer)
            same = [c for c in newer if abs((_date(c["period_end"]) - latest_end).days) <= 10]
            chosen = next((c for c in same if c["source"] == "sec_xbrl"), same[0])
            record = {**chosen, "previous_revenue": base, "previous_period_end": period.isoformat()}
            others = [c for c in same if c is not chosen]
            if others:
                record["cross_check"] = {"source": others[0]["source"], "revenue": others[0]["revenue"],
                                         "difference": others[0]["revenue"] / chosen["revenue"] - 1}
            return {"fresh_revenue": record}
        pending = sec_results_after(ticker, period) if use_sec else None
        if pending:
            return {"results_pending": {**pending, "figures_through": period.isoformat()}}
        return {}
    except Exception:
        return {}
