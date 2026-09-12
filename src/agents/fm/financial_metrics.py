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
