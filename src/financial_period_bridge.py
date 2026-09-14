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
    rows = list(rows)
    values: Dict[str, list[float]] = {}
    for row in rows:
        for field, raw in (row or {}).items():
            value = _number(raw)
            if value is not None:
                values.setdefault(str(field), []).append(value)
    out = {}
    for field, observations in values.items():
        # A TTM flow must cover all four quarters. Summing a field that Yahoo
        # exposed in only one quarter silently annualized one quarter as a
        # full year (BABA D&A became CNY 4.9B versus CNY 47.1B reported for the
        # fiscal year). Optional partial fields are omitted and downstream
        # logic falls back to complete annual evidence.
        if len(observations) != len(rows):
            continue
        lowered = field.lower()
        if any(token in lowered for token in _AVERAGE_FIELDS + _RATE_FIELDS):
            out[field] = sum(observations) / len(observations)
        else:
            out[field] = sum(observations)
    return out


def _complete_metric_sum(
    rows: Iterable[Dict[str, Any]], names: Iterable[str], *, require_positive: bool = False,
) -> Optional[float]:
    """Sum an alias-aware flow only when every quarter has a real value."""
    values = []
    for row in rows:
        value = _metric(row, names)
        if value is None or (require_positive and value <= 0):
            return None
        values.append(value)
    return sum(values) if values else None


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
        max_age = min(
            180,
            max(90, int(os.getenv("QUARTERLY_STATEMENT_MAX_AGE_DAYS", "150") or 150)),
        )
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

    income_rows = [normalized["income_statement"][period] for period in periods]
    cash_flow_rows = [normalized["cash_flow"][period] for period in periods]
    income = _aggregate_flow(income_rows)
    cash_flow = _aggregate_flow(cash_flow_rows)
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
    broad_investments = _metric(balance, (
        "Investments And Advances", "Investmentin Financial Assets",
    ))
    # Yahoo's balance-sheet schema places ``Other Short Term Investments`` in
    # current assets and ``Investments And Advances`` / ``Investmentin
    # Financial Assets`` in non-current assets.  They are distinct buckets.
    # Taking max(short, non-current) omitted one of them for cash-rich issuers:
    # AAPL lost $22.9B from its equity bridge.  Alias rows within the broad
    # bucket are alternatives (chosen by _metric), but the current and
    # non-current buckets must be added.
    valid_short = (
        float(investments) if investments is not None and investments >= 0 else None
    )
    valid_broad = (
        float(broad_investments)
        if broad_investments is not None and broad_investments >= 0 else None
    )
    if valid_short is not None and valid_broad is not None:
        non_operating_investments = valid_short + valid_broad
        non_operating_investments_source = (
            "short_term_investments_plus_investments_and_advances"
        )
    elif valid_broad is not None:
        non_operating_investments = valid_broad
        non_operating_investments_source = "investments_and_advances"
    elif valid_short is not None:
        non_operating_investments = valid_short
        non_operating_investments_source = "short_term_investments"
    else:
        non_operating_investments = None
        non_operating_investments_source = None
    debt = _metric(balance, ("Total Debt", "TotalDebt"))
    capex = _metric(cash_flow, ("Capital Expenditure", "Capital Expenditures"))
    capex_source = "reported_four_quarter_sum" if capex is not None else None
    if capex is None:
        # Some Yahoo quarterly payloads publish OCF and FCF for every quarter
        # but omit the capex row. By definition FCF = OCF + capex when capex is
        # carried as a negative cash outflow, so this is an exact bridge—not an
        # estimated reinvestment assumption.
        free_cash_flow = _metric(cash_flow, ("Free Cash Flow",))
        if free_cash_flow is not None and operating_cf is not None:
            derived = free_cash_flow - operating_cf
            if derived <= 0:
                capex = derived
                capex_source = "derived_from_complete_fcf_minus_ocf"
    da = _complete_metric_sum(cash_flow_rows, (
        "Depreciation And Amortization", "Depreciation Amortization Depletion",
        "Depreciation",
    ), require_positive=True)
    # Do not substitute income-statement ``Reconciled Depreciation`` here. It
    # can exclude amortization and other non-cash add-backs required by UFCF;
    # Alibaba's four-quarter income sum was CNY 4.9B while the complete annual
    # cash-flow statement reported CNY 47.1B D&A. Missing quarterly cash-flow
    # D&A therefore falls back to complete annual history downstream.
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
            "capital_expenditure_source": capex_source,
            "depreciation_and_amortization": da,
            "capex_to_revenue": capex / revenue if capex is not None else None,
            "da_to_revenue": da / revenue if da is not None else None,
            "cash": cash,
            "short_term_investments": investments,
            "non_operating_investments": non_operating_investments,
            "non_operating_investments_source": non_operating_investments_source,
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
