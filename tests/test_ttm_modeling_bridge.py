"""TTM data must update the model without corrupting fiscal-year history."""

import logging

import openpyxl
import pytest

from src.agents.fm.assumption_grounding import ground_assumptions
from src.agents.fm.formula_evaluator import FormulaEvaluator
from src.agents.fm.tabs.tab_historical import HistoricalTabBuilder
from src.agents.fm.tabs.tab_projections import ProjectionsTabBuilder
from src.agents.fm.tabs.tab_raw import RawTabBuilder
from src.agents.fm.tabs.tab_valuation_perpetual_growth_dcf import (
    ValuationPerpetualGrowthDCFBuilder,
)


def _current_bridge():
    return {
        "status": "current",
        "latest_period": "2026-06-30",
        "quarter_periods": ["2026-06-30", "2026-03-31", "2025-12-31", "2025-09-30"],
        "income_statement": {
            "Total Revenue": 400.0,
            "Gross Profit": 180.0,
            "Operating Income": 100.0,
        },
        "cash_flow": {"Depreciation And Amortization": 20.0},
        "normalized": {
            "capex_to_revenue": -0.08,
            "da_to_revenue": 0.05,
            "cash": 61.0,
            "short_term_investments": 29.0,
            "total_debt": 25.0,
        },
    }


def _grounding_data():
    return {
        "company_data": {
            "basic_info": {"currency": "USD", "country": "United States"},
            "market_data": {"market_cap": 1_000.0, "shares_outstanding": 10.0},
            "capital_structure": {"beta": 1.0, "total_debt": 25.0},
            "growth_profitability": {
                "operating_margins": 0.10,
                "ebitda_margins": 0.15,
                "gross_margins": 0.30,
            },
            "valuation_metrics": {},
        },
        "financial_statements": {
            "income_statement": {
                "2025-09-30": {
                    "Total Revenue": 360.0,
                    "Gross Profit": 144.0,
                    "Operating Income": 72.0,
                    "EBITDA": 90.0,
                },
                "2024-09-30": {
                    "Total Revenue": 340.0,
                    "Gross Profit": 136.0,
                    "Operating Income": 68.0,
                    "EBITDA": 85.0,
                },
            },
            "balance_sheet": {},
            "cash_flow": {},
        },
        "ttm_bridge": _current_bridge(),
    }


def test_grounding_prefers_ttm_margins_and_exposes_current_modeling_basis():
    grounded, notes = ground_assumptions(
        {
            "wacc": 0.09,
            "terminal_growth_rate": 0.025,
            "operating_margins": [0.10] * 5,
            "ebitda_margins": [0.15] * 5,
            "gross_margins": [0.30] * 5,
        },
        _grounding_data(),
    )

    assert grounded["operating_margins"][0] == pytest.approx(0.25)
    assert grounded["ebitda_margins"][0] == pytest.approx(0.30)
    assert grounded["gross_margins"][0] == pytest.approx(0.45)
    assert grounded["modeling_basis"]["period_end"] == "2026-06-30"
    assert grounded["modeling_basis"]["capex_to_revenue"] == pytest.approx(-0.08)
    assert grounded["modeling_basis"]["short_term_investments"] == pytest.approx(29.0)
    assert any("TTM/current balance-sheet bridge" in note for note in notes)


def test_projection_and_equity_bridge_use_current_ttm_inputs():
    basis = {**_current_bridge()["normalized"], "period_end": "2026-06-30"}
    workbook = openpyxl.Workbook()
    projections = ProjectionsTabBuilder(modeling_basis=basis).create_tab(workbook)
    valuation = ValuationPerpetualGrowthDCFBuilder(modeling_basis=basis).create_tab(workbook)

    assert "*0.050000000000" in projections["B12"].value
    assert "(-0.080000000000*1.00" in projections["B13"].value
    assert valuation["B30"].value == 61.0
    assert valuation["B31"].value == 25.0
    assert valuation["B32"].value == 29.0
    assert "2026-06-30" in valuation["G30"].value


def test_combined_cash_and_investments_field_does_not_double_count_cash():
    period = "2025-09-30"
    statements = {
        "income_statement": {period: {
            "Total Revenue": 100.0,
            "Cost Of Revenue": 40.0,
            "Operating Income": 30.0,
            "Net Income": 25.0,
        }},
        "cash_flow": {period: {
            "Operating Cash Flow": 35.0,
            "Capital Expenditure": -10.0,
        }},
        "balance_sheet": {period: {
            "Cash And Cash Equivalents": 50.0,
            "Cash Cash Equivalents And Short Term Investments": 80.0,
            "Total Debt": 20.0,
        }},
    }
    workbook = openpyxl.Workbook()
    raw = RawTabBuilder()
    raw.add_data_from_json({"financial_statements": statements})
    raw.create_tab(workbook)
    HistoricalTabBuilder().create_tab(workbook)
    evaluator = FormulaEvaluator(workbook)
    evaluator.set_logger(logging.getLogger("test_ttm_modeling_bridge"))
    cells = evaluator.evaluate_all_tabs()["Historical"]["cells"]

    assert cells["(30, 6)"] == 50.0
    assert cells["(31, 6)"] == 30.0
    assert cells["(37, 6)"] == -60.0
