"""Canonical financial-model metrics across provider label variants."""
from __future__ import annotations

import math
from typing import Any, Dict, Optional


# Yahoo occasionally leaves its usual D&A row null while publishing the same
# value under one of these adjacent labels. Keep the statement with the label:
# Raw contains fields from every statement, so matching only the field could
# double count the same economic value.
DEPRECIATION_SOURCES = (
    ("cash_flow", "Cash Flow Statement", "Depreciation And Amortization"),
    ("cash_flow", "Cash Flow Statement", "Depreciation Amortization Depletion"),
    ("income_statement", "Income Statement", "Reconciled Depreciation"),
    ("cash_flow", "Cash Flow Statement", "Depreciation"),
    ("income_statement", "Income Statement", "Depreciation And Amortization"),
)


def depreciation_and_amortization(
    financial_statements: Dict[str, Any], period: str
) -> Optional[float]:
    """Return the most comprehensive non-negative D&A value for ``period``."""
    values = []
    for statement_key, _, field in DEPRECIATION_SOURCES:
        rows = (financial_statements.get(statement_key) or {}).get(period) or {}
        value = rows.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        number = float(value)
        if math.isfinite(number) and number >= 0:
            values.append(number)
    return max(values) if values else None


def depreciation_excel_formula(period_reference: str) -> str:
    """Excel expression matching :func:`depreciation_and_amortization`."""
    lookups = []
    for _, statement_name, field in DEPRECIATION_SOURCES:
        lookups.append(
            'SUMIFS(Raw!$D:$D,'
            f'Raw!$A:$A,"{statement_name}",'
            f'Raw!$B:$B,"{field}",'
            f'Raw!$C:$C,{period_reference}&"*")'
        )
    return f"MAX({','.join(lookups)})"


# Denominators for inventory and payable days.
WORKING_CAPITAL_COST_BASE_COGS = "cost_of_revenue"
WORKING_CAPITAL_COST_BASE_REVENUE = "revenue"
_COST_OF_REVENUE_FIELDS = ("Cost Of Revenue", "Reconciled Cost Of Revenue")


def _positive_number(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    number = float(value)
    return math.isfinite(number) and number > 0


def working_capital_cost_base(financial_statements: Dict[str, Any]) -> str:
    """Return the base that inventory and payable days are measured against.

    Inventory and payables turn with cost of revenue, so that is the base
    whenever the issuer reports it in any annual period. Some issuers present
    expenses by function and never report a cost-of-revenue line. Booking
    Holdings is the production case: $5.1B of payables (19% of revenue) and no
    cost of revenue in any year. Measuring its payable days against the absent
    line left them blank, the forecast carried zero payables, and the first
    projected year absorbed a $4.35B working-capital outflow that never
    happens. For such an issuer revenue is the only consistent base: it
    reproduces the reported balance-to-revenue ratios and moves with the
    business. The base is chosen once per issuer and never per year, so a
    days history never mixes two denominators.
    """
    income = (financial_statements or {}).get("income_statement") or {}
    has_revenue = False
    for row in income.values():
        if not isinstance(row, dict):
            continue
        if any(_positive_number(row.get(field)) for field in _COST_OF_REVENUE_FIELDS):
            return WORKING_CAPITAL_COST_BASE_COGS
        revenue = next(
            (float(row[field]) for field in ("Total Revenue", "Operating Revenue")
             if _positive_number(row.get(field))),
            None,
        )
        if revenue is None:
            continue
        has_revenue = True
        # A gross profit below revenue implies a cost of revenue even when
        # the line itself is missing, so that issuer keeps the cost base.
        gross = row.get("Gross Profit")
        if (
            isinstance(gross, (int, float)) and not isinstance(gross, bool)
            and math.isfinite(float(gross)) and float(gross) < revenue
        ):
            return WORKING_CAPITAL_COST_BASE_COGS
    # With no revenue either, nothing can be measured; keep the default so an
    # empty payload never changes the workbook's formulas.
    return (
        WORKING_CAPITAL_COST_BASE_REVENUE if has_revenue
        else WORKING_CAPITAL_COST_BASE_COGS
    )
