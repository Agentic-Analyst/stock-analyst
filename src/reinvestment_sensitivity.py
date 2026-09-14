"""Auditable reinvestment-cycle sensitivity for operating-company DCFs.

Current capex is observable, but it is not automatically a forecast.  During a
large build-out, carrying the trailing capex/revenue ratio into FY1 can depress
cash flow sharply; replacing it with a historical average can be equally wrong
if the investment cycle persists.  This module computes both cases without
silently choosing whichever answer is closer to the market.

The shipped workbook remains the reported-run-rate case.  The alternate case
changes only FY1-FY4 capex intensity, fading from the three-year median to the
same FY5 steady-state capex/D&A ratio as the workbook.  Revenue, margins, WACC,
terminal growth, working capital, and the FY5/FY10 terminal economics are held
fixed.  The result is a sensitivity diagnostic, never an additional valuation
vote and never a replacement for actual forward capex guidance.
"""
from __future__ import annotations

import math
import statistics
from typing import Any, Dict, Iterable, Optional


SCHEMA_VERSION = 1


def _number(value: Any, *, positive: bool = False) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or (positive and number <= 0):
        return None
    return number


def _metric(row: Dict[str, Any], names: Iterable[str]) -> Optional[float]:
    for name in names:
        value = _number((row or {}).get(name))
        if value is not None:
            return value
    return None


def _annual_capex_ratios(financial_data: Dict[str, Any]) -> list[Dict[str, Any]]:
    statements = (financial_data or {}).get("financial_statements") or {}
    income = statements.get("income_statement") or {}
    cash_flow = statements.get("cash_flow") or {}
    if not isinstance(income, dict) or not isinstance(cash_flow, dict):
        return []
    rows = []
    for period in sorted(set(income).intersection(cash_flow), key=str, reverse=True):
        revenue = _metric(
            income.get(period) or {}, ("Total Revenue", "Operating Revenue", "Revenue")
        )
        capex = _metric(
            cash_flow.get(period) or {},
            ("Capital Expenditure", "Capital Expenditures"),
        )
        if revenue is None or revenue <= 0 or capex is None or capex > 0:
            continue
        ratio = capex / revenue
        if -1.0 <= ratio <= 0.0:
            rows.append({"period": str(period), "capex_to_revenue": ratio})
        if len(rows) >= 3:
            break
    return rows


def _cell(computed: Dict[str, Any], tab: str, row: int, column: int) -> Any:
    return (((computed or {}).get(tab) or {}).get("cells") or {}).get(
        f"({row}, {column})"
    )


def build_reinvestment_sensitivity(
    computed_values: Dict[str, Any],
    financial_data: Dict[str, Any],
    *,
    modeling_basis: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Compare reported-run-rate and historical-normalized capex cases.

    Returns a safe, serializable diagnostic. ``status=unavailable`` is an
    ordinary data state; callers must not infer a normalized forecast from
    fewer than three complete annual observations.
    """
    basis = modeling_basis if isinstance(modeling_basis, dict) else {}
    reported_ratio = _number(basis.get("capex_to_revenue"))
    da_ratio = _number(basis.get("da_to_revenue"))
    history = _annual_capex_ratios(financial_data or {})
    if (
        reported_ratio is None or not -1.0 <= reported_ratio <= 0.0
        or da_ratio is None or not 0.0 <= da_ratio <= 0.5
        or len(history) < 3
    ):
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "unavailable",
            "included_in_intrinsic_value": False,
            "reason": (
                "A current capex/D&A bridge and three complete annual capex-to-"
                "revenue observations are required for reinvestment sensitivity."
            ),
            "annual_observations": history,
        }

    revenues = [
        _number(_cell(computed_values, "Projections", 3, column), positive=True)
        for column in range(2, 7)
    ]
    explicit_fcf = [
        _number(_cell(computed_values, "Valuation (DCF)", 16, column))
        for column in range(2, 12)
    ]
    wacc = _number(_cell(computed_values, "Valuation (DCF)", 12, 2), positive=True)
    growth = _number(_cell(computed_values, "Valuation (DCF)", 23, 2))
    cash = _number(_cell(computed_values, "Valuation (DCF)", 30, 2))
    debt = _number(_cell(computed_values, "Valuation (DCF)", 31, 2))
    investments = _number(_cell(computed_values, "Valuation (DCF)", 32, 2))
    shares = _number(_cell(computed_values, "Valuation (DCF)", 36, 2), positive=True)
    base_per_share = _number(
        _cell(computed_values, "Valuation (DCF)", 37, 2), positive=True
    )
    mid_year = _number(_cell(computed_values, "Sensitivity", 4, 2))
    if mid_year is None:
        mid_year = 0.0
    required = [*revenues, *explicit_fcf, wacc, growth, cash, debt, investments,
                shares, base_per_share]
    if any(value is None for value in required) or not 0 <= mid_year <= 1:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "unavailable",
            "included_in_intrinsic_value": False,
            "reason": "The evaluated workbook lacks the complete DCF cells required for the sensitivity.",
            "annual_observations": history,
        }
    # The completeness gate above guarantees these values. Keep the runtime
    # check explicit because ``python -O`` removes assertions and this module
    # is used inside the production worker image.
    if wacc is None or growth is None or shares is None:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "unavailable",
            "included_in_intrinsic_value": False,
            "reason": "The evaluated workbook lacks complete discount-rate inputs.",
            "annual_observations": history,
        }
    if wacc <= growth:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "unavailable",
            "included_in_intrinsic_value": False,
            "reason": "The model WACC must exceed terminal growth.",
            "annual_observations": history,
        }

    normalized_ratio = statistics.median(
        row["capex_to_revenue"] for row in history
    )
    adjusted_fcf = list(explicit_fcf)
    for index in range(5):
        # Both paths converge to the same 1.1x-D&A steady state in FY5. The
        # target term therefore cancels; only the starting-intensity gap
        # remains, scaled down linearly over FY1-FY4.
        remaining = 1.0 - index / 4.0
        adjusted_fcf[index] = (
            explicit_fcf[index]
            + revenues[index] * (normalized_ratio - reported_ratio) * remaining
        )

    def dcf_per_share(fcf_path: list[float]) -> float:
        present_value = sum(
            value / (1.0 + wacc) ** (year - mid_year)
            for year, value in enumerate(fcf_path, 1)
        )
        terminal_value = (
            fcf_path[-1] * (1.0 + growth) / (wacc - growth)
            / (1.0 + wacc) ** (10.0 - mid_year)
        )
        return (
            present_value + terminal_value + cash - debt + investments
        ) / shares

    replayed_base = dcf_per_share(explicit_fcf)
    tolerance = max(0.05, base_per_share * 0.005)
    if abs(replayed_base - base_per_share) > tolerance:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "unavailable",
            "included_in_intrinsic_value": False,
            "reason": (
                "The independent DCF replay did not reconcile to the workbook; "
                "the alternate capex case was withheld."
            ),
            "annual_observations": history,
            "workbook_value": base_per_share,
            "replayed_value": replayed_base,
        }

    normalized_value = dcf_per_share(adjusted_fcf)
    value_change = normalized_value / base_per_share - 1.0
    intensity_change = normalized_ratio - reported_ratio
    if intensity_change < -0.02:
        cycle = "reported_capex_below_history"
    elif intensity_change > 0.02:
        cycle = "reported_capex_above_history"
    else:
        cycle = "reported_capex_near_history"
    material = bool(abs(value_change) >= 0.05 or abs(intensity_change) >= 0.02)
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "material" if material else "not_material",
        "included_in_intrinsic_value": False,
        "role": "capex_cycle_sensitivity_only",
        "cycle": cycle,
        "reported_capex_to_revenue": reported_ratio,
        "historical_normalized_capex_to_revenue": normalized_ratio,
        "depreciation_and_amortization_to_revenue": da_ratio,
        "annual_observations": history,
        "reported_run_rate_perpetual_dcf": base_per_share,
        "historical_normalized_perpetual_dcf": normalized_value,
        "normalized_value_change": value_change,
        "sensitivity_range_low": min(base_per_share, normalized_value),
        "sensitivity_range_high": max(base_per_share, normalized_value),
        "reason": (
            "The alternate case changes only the starting capex intensity and "
            "fades it to the workbook's same FY5 steady state. It is not forward "
            "guidance, is excluded from intrinsic-value blending, and does not "
            "alter revenue, margins, WACC, terminal growth, or terminal economics."
        ),
    }
