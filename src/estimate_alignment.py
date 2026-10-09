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
# A consistent table chains: "+1y" grows from "0y" (its year-ago revenue is
# "0y"'s average). Every consistent table checked (MU, COST, AZO, the banks)
# matches exactly.
_CHAIN_TOLERANCE = 0.005
# A fiscal year is 52 or 53 weeks; its end moves a few days year to year.
_ONE_YEAR_DAYS = (300, 430)
# The reported year less its quarters already in the statements leaves the
# quarters Yahoo has and the statements do not; each must look like a quarter
# of that company (Micron's implied FY2026 Q4: 1.3x its May quarter). Toyota's
# and Sony's year-ago figures are on another basis (0.36x and 0.06x their
# statements) and leave a negative quarter.
_IMPLIED_QUARTER_BOUNDS = (0.5, 2.5)
# One year's revenue against the next, wherever the table is realigned.
_YEAR_ON_YEAR_BOUNDS = (0.5, 5.0)


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


def _chains(current_year: Dict[str, Any], next_year: Any) -> bool:
    """Whether Yahoo's "+1y" grows from its "0y" (True when it cannot say)."""
    base = _positive((next_year or {}).get("yearAgoRevenue")) if isinstance(next_year, dict) else None
    average = _positive(current_year.get("avg"))
    return base is None or average is None or abs(base / average - 1.0) <= _CHAIN_TOLERANCE


def _torn(current_year: Dict[str, Any], next_year: Any) -> Optional[Dict[str, Any]]:
    """
    A half-rolled table: "0y" is the year after the statements but "+1y" grows
    from a different base, the year after it. Jabil, Accenture and FactSet on
    9 October 2026: "0y" FY2026 (year-ago = the FY2025 statement), "+1y"
    FY2028, FY2027 only as "+1y"'s year-ago revenue ($44.78B against "0y"'s
    $35.06B for Jabil). Read as the year after "0y", "+1y" put FY2028 in FY2.
    """
    if _chains(current_year, next_year):
        return None
    base = _positive(next_year.get("yearAgoRevenue"))
    average = _positive(current_year.get("avg"))
    plausible = (_YEAR_ON_YEAR_BOUNDS[0] <= base / average <= _YEAR_ON_YEAR_BOUNDS[1]
                 if base and average else False)
    return {"status": "torn", "next_year_base_revenue": base, "next_year_base_plausible": plausible}


def _implied_quarters_plausible(data: Dict[str, Any], reported: float, latest_end: date,
                                latest_revenue: float, provider_year_end: date) -> bool:
    quarters = ((data.get("quarterly_financial_statements") or {}).get("income_statement") or {})
    inside = []
    for period, row in quarters.items() if isinstance(quarters, dict) else []:
        when, revenue = _date(period), _revenue(row)
        if when is not None and revenue is not None and latest_end < when <= provider_year_end:
            inside.append((when, revenue))
    missing = 4 - len(inside)
    if missing >= 4:
        return _YEAR_ON_YEAR_BOUNDS[0] <= reported / latest_revenue <= _YEAR_ON_YEAR_BOUNDS[1]
    implied = reported - sum(revenue for _, revenue in inside)
    if missing <= 0:
        return abs(implied) <= _SAME_YEAR_REVENUE_TOLERANCE * reported
    # Against the latest quarter (a grower: Micron's implied Q4 is 1.3x its
    # May quarter) or the same quarters a year earlier (a seasonal business:
    # Vail's July quarter is a quarter of its April one, and equal to last
    # July's). A different basis leaves a negative remainder and fails both.
    in_bounds = lambda ratio: _IMPLIED_QUARTER_BOUNDS[0] <= ratio <= _IMPLIED_QUARTER_BOUNDS[1]
    latest_quarter = max(inside)[1]
    if in_bounds(implied / missing / latest_quarter):
        return True
    year_earlier = sorted(
        (when, revenue) for period, row in quarters.items()
        for when, revenue in [(_date(period), _revenue(row))]
        if when is not None and revenue is not None and when <= latest_end
    )[-missing:]
    if len(year_earlier) != missing:
        return False
    return in_bounds(implied / sum(revenue for _, revenue in year_earlier))


def estimate_alignment(modeling_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Whether Yahoo's "0y" is the year after the latest annual statement.

    "rolled" needs every sign that Yahoo has seen one more fiscal year reported
    than the statements carry: its last fiscal year end is a year after the
    latest annual statement's; its current quarter's year-ago revenue is a
    statement quarter from inside that newer year; its table chains ("+1y"
    grows from "0y"); and the reported year it implies leaves plausible
    quarters once the statements' quarters of that year are taken out. A
    year-ago figure equal to the latest statement is never a roll, even in a
    flat year: it cannot be told from a table that has not rolled, and a flat
    year moves the model little either way. A provider whose revenue
    definition differs from the statements' (Ford, Deere, the oil majors) on
    the same fiscal year is aligned.
    """
    data = modeling_data if isinstance(modeling_data, dict) else {}
    analyst = data.get("analyst_data") if isinstance(data.get("analyst_data"), dict) else {}
    revenue_rows = analyst.get("revenue_estimates") or {}
    current_year = revenue_rows.get("0y") if isinstance(revenue_rows, dict) else None
    next_year = revenue_rows.get("+1y") if isinstance(revenue_rows, dict) else None
    statements = (data.get("financial_statements") or {}).get("income_statement")
    latest = _latest(statements)
    if not isinstance(current_year, dict) or latest is None:
        return {"status": "unknown"}
    latest_end, latest_revenue = latest
    result: Dict[str, Any] = {"latest_annual_statement_end": latest_end.isoformat()}
    year_ago = _positive(current_year.get("yearAgoRevenue"))
    basic = ((data.get("company_data") or {}).get("basic_info") or {})
    provider_year_end = _date(basic.get("last_fiscal_year_end"))
    if provider_year_end is not None:
        result["provider_last_fiscal_year_end"] = provider_year_end.isoformat()
    lag = (provider_year_end - latest_end).days if provider_year_end is not None else None

    # Yahoo's clock has moved a year past the statements: its last fiscal year
    # end is a year later, and its current quarter grows from a statement
    # quarter inside that newer year.
    matched = None
    if lag is not None and _ONE_YEAR_DAYS[0] <= lag <= _ONE_YEAR_DAYS[1]:
        current_quarter = revenue_rows.get("0q") if isinstance(revenue_rows, dict) else None
        quarter_year_ago = _positive((current_quarter or {}).get("yearAgoRevenue"))
        quarters = ((data.get("quarterly_financial_statements") or {}).get("income_statement")
                    or {})
        if quarter_year_ago is not None and isinstance(quarters, dict):
            for period, row in quarters.items():
                when, revenue = _date(period), _revenue(row)
                if (when is not None and revenue is not None
                        and latest_end < when <= provider_year_end
                        and abs(revenue / quarter_year_ago - 1.0)
                        <= _SAME_QUARTER_REVENUE_TOLERANCE):
                    matched = when

    same_year = (year_ago is not None
                 and abs(year_ago / latest_revenue - 1.0) <= _SAME_YEAR_REVENUE_TOLERANCE)
    if same_year or (lag is not None and lag < _ONE_YEAR_DAYS[0] and year_ago is not None):
        # A broken chain on a clock that has not moved is a provider basis
        # (HDB's "+1y" year-ago is its own "0y" low; MUFG's is 0.51x), not a
        # roll: torn only once the clock has moved.
        torn = _torn(current_year, next_year) if same_year and matched is not None else None
        if torn:
            return {**result, **torn,
                    "current_quarter_year_ago_period": matched.isoformat()}
        aligned = {**result, "status": "aligned"}
        if not same_year:
            # Same fiscal year on both clocks; the provider defines revenue
            # differently from the statements.
            aligned["year_ago_revenue_ratio"] = year_ago / latest_revenue
        return aligned
    if lag is None or year_ago is None or lag > _ONE_YEAR_DAYS[1]:
        return {**result, "status": "unverified"}

    if (matched is None or not _chains(current_year, next_year)
            or not _implied_quarters_plausible(data, year_ago, latest_end, latest_revenue,
                                               provider_year_end)):
        return {**result, "status": "unverified"}
    return {
        **result,
        "status": "rolled",
        "years_shifted": 1,
        "reported_year_revenue": year_ago,
        "current_quarter_year_ago_period": matched.isoformat(),
    }


def _realign_torn(analyst: Dict[str, Any], alignment: Dict[str, Any]) -> None:
    """
    "+1y" becomes the year "0y" grows into, from Yahoo's own base for its
    "+1y"; Yahoo's "+1y" is kept as "+2y". Its EPS has no such base (Jabil's
    "+1y" year-ago EPS is half its "0y", on three analysts), so FY2 EPS is
    dropped rather than taken from the wrong year.
    """
    revenue = analyst.get("revenue_estimates") or {}
    eps = analyst.get("earnings_estimates") or {}
    analyst["provider_estimates"] = {
        "revenue_estimates": copy.deepcopy(revenue),
        "earnings_estimates": copy.deepcopy(eps),
    }
    next_year = revenue.get("+1y") or {}
    aligned = {key: value for key, value in revenue.items() if key != "+1y"}
    if alignment.get("next_year_base_plausible"):
        base = alignment["next_year_base_revenue"]
        current = _positive((revenue.get("0y") or {}).get("avg"))
        aligned["+1y"] = {
            "avg": base,
            "numberOfAnalysts": next_year.get("numberOfAnalysts"),
            "growth": base / current - 1.0 if current else None,
            "currency": next_year.get("currency"),
            "implied_from_next_year": True,
        }
        aligned["+2y"] = dict(next_year)
    analyst["revenue_estimates"] = aligned
    analyst["earnings_estimates"] = _rolled_eps(eps)
    alignment["note"] = (
        "Yahoo's +1y revenue had rolled a year past its 0y; "
        + ("+1y is the year 0y grows into, from Yahoo's own base, and Yahoo's +1y is +2y; "
           if alignment.get("next_year_base_plausible") else "+1y revenue is not used; ")
        + "its EPS had rolled in full: the reported year's EPS is 0y and Yahoo's 0y is +1y."
    )


def _rolled_eps(eps: Dict[str, Any]) -> Dict[str, Any]:
    """
    EPS rows when Yahoo's EPS table has rolled a year past the statements: the
    reported year's EPS (Yahoo's 0y year-ago) is 0y, Yahoo's 0y is +1y, and
    Yahoo's +1y is +2y only when it grows from Yahoo's 0y. In a torn table the
    EPS table has rolled in full while revenue has not: Jabil's 0y year-ago
    EPS, 13.09, is its four FY2026 quarters (2.85 + 2.69 + 3.16 + 4.40), and
    its 0y, 17.69, is FY2027.
    """
    current, following = eps.get("0y") or {}, eps.get("+1y")
    aligned: Dict[str, Any] = {key: eps[key] for key in ("0q", "+1q") if key in eps}
    reported = current.get("yearAgoEps")
    if isinstance(reported, (int, float)) and not isinstance(reported, bool) \
            and math.isfinite(float(reported)):
        aligned["0y"] = {
            "avg": float(reported),
            "numberOfAnalysts": current.get("numberOfAnalysts"),
            "currency": current.get("currency"),
            "reported": True,
        }
    if current:
        aligned["+1y"] = dict(current)
    base = following.get("yearAgoEps") if isinstance(following, dict) else None
    average = current.get("avg")
    if (isinstance(base, (int, float)) and isinstance(average, (int, float))
            and not isinstance(base, bool) and average
            and abs(float(base) / float(average) - 1.0) <= _CHAIN_TOLERANCE):
        aligned["+2y"] = dict(following)
    return aligned


def align_street_estimates(modeling_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Realign the annual estimate rows in place when Yahoo's clock has rolled
    past the statements; record the alignment either way. Idempotent.
    """
    data = modeling_data if isinstance(modeling_data, dict) else {}
    analyst = data.get("analyst_data")
    # An empty table (the estimate scrape failed) stays empty: a recorded
    # alignment would make it look like analyst data.
    if not isinstance(analyst, dict) or not analyst:
        return {"status": "unknown"}
    if isinstance(analyst.get("estimate_alignment"), dict):
        return analyst["estimate_alignment"]
    alignment = estimate_alignment(data)
    if alignment.get("status") == "torn":
        _realign_torn(analyst, alignment)
        analyst["estimate_alignment"] = alignment
        return alignment
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

    aligned_eps = _rolled_eps(eps)
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
