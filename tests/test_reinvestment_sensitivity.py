import math

import pytest

from src.reinvestment_sensitivity import build_reinvestment_sensitivity
from src.summary_evidence import (
    external_benchmark,
    render_external_benchmark,
    render_external_benchmark_compact,
)


def _computed(*, workbook_value=None):
    wacc, growth, mid_year = 0.09, 0.025, 0.5
    fcf = [100.0] * 10
    present = sum(
        value / (1 + wacc) ** (year - mid_year)
        for year, value in enumerate(fcf, 1)
    )
    terminal = (
        fcf[-1] * (1 + growth) / (wacc - growth)
        / (1 + wacc) ** (10 - mid_year)
    )
    base = (present + terminal) / 10.0
    if workbook_value is not None:
        base = workbook_value
    return {
        "Projections": {"cells": {
            **{f"(3, {column})": 1000.0 for column in range(2, 7)},
        }},
        "Valuation (DCF)": {"cells": {
            **{f"(16, {column})": 100.0 for column in range(2, 12)},
            "(12, 2)": wacc,
            "(23, 2)": growth,
            "(30, 2)": 0.0,
            "(31, 2)": 0.0,
            "(32, 2)": 0.0,
            "(36, 2)": 10.0,
            "(37, 2)": base,
        }},
        "Sensitivity": {"cells": {"(4, 2)": mid_year}},
    }


def _financial(periods=3):
    income, cash = {}, {}
    for index in range(periods):
        period = f"{2025 - index}-12-31"
        income[period] = {"Total Revenue": 1000.0}
        cash[period] = {"Capital Expenditure": -100.0}
    return {"financial_statements": {
        "income_statement": income,
        "cash_flow": cash,
    }}


def test_material_capex_cycle_is_an_explicit_non_voting_sensitivity():
    result = build_reinvestment_sensitivity(
        _computed(), _financial(),
        modeling_basis={"capex_to_revenue": -0.30, "da_to_revenue": 0.05},
    )

    assert result["status"] == "material"
    assert result["cycle"] == "reported_capex_above_history"
    assert result["reported_capex_to_revenue"] == -0.30
    assert result["historical_normalized_capex_to_revenue"] == -0.10
    assert result["historical_normalized_perpetual_dcf"] > result[
        "reported_run_rate_perpetual_dcf"
    ]
    assert result["normalized_value_change"] > 0
    assert result["included_in_intrinsic_value"] is False


def test_reinvestment_case_requires_three_complete_annual_observations():
    result = build_reinvestment_sensitivity(
        _computed(), _financial(periods=2),
        modeling_basis={"capex_to_revenue": -0.30, "da_to_revenue": 0.05},
    )

    assert result["status"] == "unavailable"
    assert len(result["annual_observations"]) == 2


def test_reinvestment_case_fails_closed_when_independent_replay_does_not_match():
    result = build_reinvestment_sensitivity(
        _computed(workbook_value=9999.0), _financial(),
        modeling_basis={"capex_to_revenue": -0.30, "da_to_revenue": 0.05},
    )

    assert result["status"] == "unavailable"
    assert "did not reconcile" in result["reason"]


def test_reinvestment_sensitivity_is_visible_but_never_an_intrinsic_vote():
    sensitivity = build_reinvestment_sensitivity(
        _computed(), _financial(),
        modeling_basis={"capex_to_revenue": -0.30, "da_to_revenue": 0.05},
    )
    evidence = external_benchmark(
        {"external_expectations": {"currency": "USD"}},
        valuation_metrics={"reinvestment_sensitivity": sensitivity},
    )

    assert evidence["reinvestment_sensitivity"]["included_in_intrinsic_value"] is False
    full = render_external_benchmark(evidence)
    compact = render_external_benchmark_compact(evidence)
    assert "reinvestment-cycle sensitivity" in full
    assert "not forward guidance or an independent valuation vote" in full
    assert "Reinvestment sensitivity" in compact
    assert "receives no valuation vote" in compact
