"""
Put Yahoo's annual Street estimates on the statements' fiscal years.

Yahoo labels its estimates by its own fiscal clock: "0y" is the first fiscal
year it has not seen reported. Every consumer here (the revenue anchor, the
EPS margin bridge, the publication boundary's Street comparison) reads "0y" as
the year after the latest annual statement. For a few weeks after a fiscal
year closes the two clocks disagree: the company reports the year, Yahoo rolls
"0y" to the following one, and its statements still end a year earlier.

Micron, 9 October 2026: FY2026 (ended 3 September) was reported in late
September and "0y" was already FY2027 ($275B), while the annual statements
ended at FY2025 ($37.4B) and the quarterly ones at May 2026. The model's first
forecast year took the Street's FY2027 and its second FY2028, a year early on a
company whose revenue was doubling. Costco and AutoZone (August year ends)
were in the same window.

When the estimates have rolled, the reported year comes back as "0y" from
Yahoo's own year-ago figures (the revenue and EPS it grows "0y" from), "0y"
becomes "+1y", and "+1y" is kept as "+2y". The provider's table is preserved
under ``provider_estimates``.
"""

from __future__ import annotations

import copy
import math
from datetime import date, datetime
from typing import Any, Dict, Optional

# The provider's year-ago revenue equals the latest annual statement's when
# both describe the same fiscal year (the EPS bridge uses the same tolerance).
_SAME_YEAR_REVENUE_TOLERANCE = 0.02
# A quarter's revenue identifies the quarter: the provider's year-ago figure
# for its current quarter matches one statement quarter to the dollar, give or
# take restatement rounding.
_SAME_QUARTER_REVENUE_TOLERANCE = 0.005
# A fiscal year is 52 or 53 weeks; its end moves a few days year to year.
_ONE_YEAR_DAYS = (300, 430)


def _date(value: Any) -> Optional[date]:
    try:
        return datetime.strptime(str(value or "")[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _positive(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) and value > 0 else None


def _revenue(row: Any) -> Optional[float]:
    if not isinstance(row, dict):
        return None
    for key in ("Total Revenue", "Operating Revenue"):
        value = _positive(row.get(key))
        if value is not None:
            return value
    return None


def _latest(rows: Any) -> Optional[tuple]:
    """(period end, revenue) of the latest dated statement row with revenue."""
    dated = []
    for period, row in (rows or {}).items() if isinstance(rows, dict) else []:
        when, revenue = _date(period), _revenue(row)
        if when is not None and revenue is not None:
            dated.append((when, revenue))
    return max(dated) if dated else None


def estimate_alignment(modeling_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Whether Yahoo's "0y" is the year after the latest annual statement.

    "rolled" needs two independent signs that Yahoo has seen one more fiscal
    year reported than the statements carry: its last fiscal year end is a
    year after the latest annual statement's, and its current quarter's
    year-ago revenue is a statement quarter from inside that newer year. A
    provider whose revenue definition differs from the statements' (Ford,
    Deere, the oil majors) fails the year-ago match in every period, so the
    year-ago figure alone never decides it.
    """
    data = modeling_data if isinstance(modeling_data, dict) else {}
    analyst = data.get("analyst_data") if isinstance(data.get("analyst_data"), dict) else {}
    revenue_rows = analyst.get("revenue_estimates") or {}
    current_year = revenue_rows.get("0y") if isinstance(revenue_rows, dict) else None
    statements = (data.get("financial_statements") or {}).get("income_statement")
    latest = _latest(statements)
    if not isinstance(current_year, dict) or latest is None:
        return {"status": "unknown"}
    latest_end, latest_revenue = latest
    result: Dict[str, Any] = {"latest_annual_statement_end": latest_end.isoformat()}
    year_ago = _positive(current_year.get("yearAgoRevenue"))
    if year_ago is not None and abs(year_ago / latest_revenue - 1.0) <= _SAME_YEAR_REVENUE_TOLERANCE:
        return {**result, "status": "aligned"}

    basic = ((data.get("company_data") or {}).get("basic_info") or {})
    provider_year_end = _date(basic.get("last_fiscal_year_end"))
    if provider_year_end is None or year_ago is None:
        return {**result, "status": "unverified"}
    result["provider_last_fiscal_year_end"] = provider_year_end.isoformat()
    lag = (provider_year_end - latest_end).days
    if lag < _ONE_YEAR_DAYS[0]:
        # Same fiscal year on both clocks; the provider defines revenue
        # differently from the statements.
        return {**result, "status": "aligned", "year_ago_revenue_ratio": year_ago / latest_revenue}
    if lag > _ONE_YEAR_DAYS[1]:
        return {**result, "status": "unverified"}

    current_quarter = revenue_rows.get("0q") if isinstance(revenue_rows, dict) else None
    quarter_year_ago = _positive((current_quarter or {}).get("yearAgoRevenue"))
    quarters = ((data.get("quarterly_financial_statements") or {}).get("income_statement") or {})
    matched = None
    if quarter_year_ago is not None and isinstance(quarters, dict):
        for period, row in quarters.items():
            when, revenue = _date(period), _revenue(row)
            if (when is not None and revenue is not None
                    and latest_end < when <= provider_year_end
                    and abs(revenue / quarter_year_ago - 1.0) <= _SAME_QUARTER_REVENUE_TOLERANCE):
                matched = when
    if matched is None:
        return {**result, "status": "unverified"}
    return {
        **result,
        "status": "rolled",
        "years_shifted": 1,
        "reported_year_revenue": year_ago,
        "current_quarter_year_ago_period": matched.isoformat(),
    }


def align_street_estimates(modeling_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Realign the annual estimate rows in place when Yahoo's clock has rolled
    past the statements; record the alignment either way. Idempotent.
    """
    data = modeling_data if isinstance(modeling_data, dict) else {}
    analyst = data.get("analyst_data")
    if not isinstance(analyst, dict):
        return {"status": "unknown"}
    if isinstance(analyst.get("estimate_alignment"), dict):
        return analyst["estimate_alignment"]
    alignment = estimate_alignment(data)
    if alignment.get("status") != "rolled":
        analyst["estimate_alignment"] = alignment
        return alignment

    revenue = analyst.get("revenue_estimates") or {}
    eps = analyst.get("earnings_estimates") or {}
    analyst["provider_estimates"] = {
        "revenue_estimates": copy.deepcopy(revenue),
        "earnings_estimates": copy.deepcopy(eps),
    }
    latest_revenue = _latest((data.get("financial_statements") or {}).get("income_statement"))[1]
    reported_revenue = alignment["reported_year_revenue"]
    current_revenue, next_revenue = revenue.get("0y") or {}, revenue.get("+1y")
    current_eps, next_eps = eps.get("0y") or {}, eps.get("+1y")

    # The reported year: Yahoo's own year-ago figures, the base it grows "0y"
    # from. A reported number has no estimate spread; its coverage is the
    # table's.
    aligned_revenue = {
        "0y": {
            "avg": reported_revenue,
            "numberOfAnalysts": current_revenue.get("numberOfAnalysts"),
            "growth": reported_revenue / latest_revenue - 1.0,
            "currency": current_revenue.get("currency"),
            "reported": True,
        },
        "+1y": {**current_revenue, "yearAgoRevenue": reported_revenue},
    }
    if isinstance(next_revenue, dict):
        aligned_revenue["+2y"] = dict(next_revenue)
    for key in ("0q", "+1q"):
        if key in revenue:
            aligned_revenue[key] = revenue[key]

    aligned_eps: Dict[str, Any] = {}
    reported_eps = current_eps.get("yearAgoEps")
    if isinstance(reported_eps, (int, float)) and not isinstance(reported_eps, bool) \
            and math.isfinite(float(reported_eps)):
        aligned_eps["0y"] = {
            "avg": float(reported_eps),
            "numberOfAnalysts": current_eps.get("numberOfAnalysts"),
            "currency": current_eps.get("currency"),
            "reported": True,
        }
    if current_eps:
        aligned_eps["+1y"] = dict(current_eps)
    if isinstance(next_eps, dict):
        aligned_eps["+2y"] = dict(next_eps)
    for key in ("0q", "+1q"):
        if key in eps:
            aligned_eps[key] = eps[key]

    analyst["revenue_estimates"] = aligned_revenue
    analyst["earnings_estimates"] = aligned_eps
    alignment["note"] = (
        f"Yahoo's estimates had rolled to the fiscal year after "
        f"{alignment['provider_last_fiscal_year_end']} while the annual statements end "
        f"{alignment['latest_annual_statement_end']}; the reported year "
        f"({reported_revenue:,.0f} revenue) is 0y, Yahoo's 0y is +1y and its +1y is +2y."
    )
    analyst["estimate_alignment"] = alignment
    return alignment
