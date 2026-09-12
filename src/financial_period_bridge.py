"""Build a validated trailing-twelve-month bridge from quarterly statements.

Annual statements remain the fiscal-year history and revenue-forecast base.
The TTM bridge is deliberately separate: it refreshes margins, reinvestment,
working capital, tax, and the balance-sheet equity bridge without mixing four
overlapping quarters into the annual time series.
"""
from __future__ import annotations

import math
import os
from datetime import date, datetime, timezone
from typing import Any, Dict, Iterable, Optional


_FLOW_STATEMENTS = ("income_statement", "cash_flow")
_REQUIRED_STATEMENTS = (*_FLOW_STATEMENTS, "balance_sheet")
_AVERAGE_FIELDS = (
    "average shares", "average diluted shares", "average basic shares",
)
_RATE_FIELDS = ("tax rate", "rate for calcs")


def _utc_date(value: Any) -> Optional[date]:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).date() if value.tzinfo else value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return datetime.strptime(value.strip()[:10], "%Y-%m-%d").date()
        except ValueError:
            return None


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _metric(row: Dict[str, Any], names: Iterable[str]) -> Optional[float]:
    for name in names:
        value = _number((row or {}).get(name))
        if value is not None:
            return value
    return None


def _aggregate_flow(rows: Iterable[Dict[str, Any]]) -> Dict[str, float]:
    values: Dict[str, list[float]] = {}
    for row in rows:
        for field, raw in (row or {}).items():
            value = _number(raw)
            if value is not None:
                values.setdefault(str(field), []).append(value)
    out = {}
    for field, observations in values.items():
        lowered = field.lower()
        if any(token in lowered for token in _AVERAGE_FIELDS + _RATE_FIELDS):
            out[field] = sum(observations) / len(observations)
        else:
            out[field] = sum(observations)
    return out


def _unavailable(now: datetime, reason: str, **extra: Any) -> Dict[str, Any]:
    return {
        "status": "unavailable",
        "basis": "annual",
        "as_of": now.isoformat(),
        "latest_period": None,
        "age_days": None,
        "reason": reason,
        **extra,
    }


def build_ttm_bridge(
    quarterly_statements: Dict[str, Any], *, as_of: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Return a TTM bridge only when four aligned, recent quarters exist."""
    now = as_of or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    try:
        max_age = max(90, int(os.getenv("QUARTERLY_STATEMENT_MAX_AGE_DAYS", "150") or 150))
    except ValueError:
        max_age = 150

    normalized: Dict[str, Dict[date, Dict[str, Any]]] = {}
    missing = []
    for statement in _REQUIRED_STATEMENTS:
        rows = (quarterly_statements or {}).get(statement) or {}
        parsed = {}
        if isinstance(rows, dict):
            for period, row in rows.items():
                stamp = _utc_date(period)
                if stamp is not None and stamp <= now.date() and isinstance(row, dict):
                    parsed[stamp] = row
        if not parsed:
            missing.append(statement)
        normalized[statement] = parsed
    if missing:
        return _unavailable(
            now, "Quarterly statements unavailable for: " + ", ".join(missing) + ".",
            max_age_days=max_age,
        )

    common = set.intersection(*(set(normalized[name]) for name in _REQUIRED_STATEMENTS))
    periods = sorted(common, reverse=True)[:4]
    if len(periods) < 4:
        return _unavailable(
            now,
            f"Only {len(periods)} aligned quarterly periods were available; four are required.",
            max_age_days=max_age,
            quarter_periods=[period.isoformat() for period in periods],
        )

    chronological = sorted(periods)
    gaps = [(right - left).days for left, right in zip(chronological, chronological[1:])]
    span = (chronological[-1] - chronological[0]).days
    if span < 240 or span > 400 or any(gap < 55 or gap > 135 for gap in gaps):
        return _unavailable(
            now,
            "Quarterly periods are not a plausible consecutive four-quarter series.",
            max_age_days=max_age,
            quarter_periods=[period.isoformat() for period in periods],
            period_gaps_days=gaps,
        )

    income = _aggregate_flow(normalized["income_statement"][period] for period in periods)
    cash_flow = _aggregate_flow(normalized["cash_flow"][period] for period in periods)
    balance = dict(normalized["balance_sheet"][periods[0]])
    revenue = _metric(income, ("Total Revenue", "Operating Revenue", "Revenue"))
    operating_cf = _metric(cash_flow, ("Operating Cash Flow", "Total Cash From Operating Activities"))
    if revenue is None or revenue <= 0 or operating_cf is None:
        return _unavailable(
            now,
            "The aligned quarters lack positive revenue or operating cash flow required for a DCF bridge.",
            max_age_days=max_age,
            quarter_periods=[period.isoformat() for period in periods],
        )

    latest = periods[0]
    age = (now.date() - latest).days
    status = "current" if age <= max_age else "stale"
    cash = _metric(balance, ("Cash And Cash Equivalents", "Cash", "Cash Financial"))
    combined = _metric(balance, ("Cash Cash Equivalents And Short Term Investments",))
    investments = _metric(balance, ("Other Short Term Investments", "Short Term Investments"))
    if investments is None and combined is not None:
        investments = max(0.0, combined - (cash or 0.0))
    debt = _metric(balance, ("Total Debt", "TotalDebt"))
    capex = _metric(cash_flow, ("Capital Expenditure", "Capital Expenditures"))
    da = _metric(cash_flow, (
        "Depreciation And Amortization", "Depreciation Amortization Depletion",
        "Depreciation",
    )) or _metric(income, ("Reconciled Depreciation", "Depreciation And Amortization"))
    tax_provision = _metric(income, ("Tax Provision",))
    pretax_income = _metric(income, ("Pretax Income", "Income Before Tax"))

    return {
        "status": status,
        "basis": "ttm" if status == "current" else "annual",
        "as_of": now.isoformat(),
        "latest_period": latest.isoformat(),
        "age_days": age,
        "max_age_days": max_age,
        "quarter_periods": [period.isoformat() for period in periods],
        "period_gaps_days": gaps,
        "income_statement": income,
        "cash_flow": cash_flow,
        "balance_sheet": balance,
        "normalized": {
            "revenue": revenue,
            "operating_cash_flow": operating_cf,
            "capital_expenditure": capex,
            "depreciation_and_amortization": da,
            "capex_to_revenue": capex / revenue if capex is not None else None,
            "da_to_revenue": da / revenue if da is not None else None,
            "cash": cash,
            "short_term_investments": investments,
            "total_debt": debt,
            "effective_tax_rate": (
                tax_provision / pretax_income
                if tax_provision is not None and pretax_income is not None
                and pretax_income > 0 and 0 < tax_provision / pretax_income <= 0.5
                else None
            ),
        },
        "reason": (
            None if status == "current" else
            f"Latest quarterly period is {age} days old, beyond the {max_age}-day limit."
        ),
    }
