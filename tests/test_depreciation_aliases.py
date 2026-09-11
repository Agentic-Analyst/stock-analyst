"""D&A aliases must not silently remove cash flow or double count it."""

import logging

import openpyxl

from src.agents.fm.financial_metrics import (
    depreciation_and_amortization,
    depreciation_excel_formula,
)
from src.agents.fm.formula_evaluator import FormulaEvaluator
from src.agents.fm.tabs.tab_historical import HistoricalTabBuilder
from src.agents.fm.tabs.tab_raw import RawTabBuilder


PERIOD = "2025-12-31"


def _google_shaped_statements():
    return {
        "income_statement": {PERIOD: {
            "Total Revenue": 100.0,
            "Cost Of Revenue": 40.0,
            "Operating Income": 30.0,
            "Net Income": 25.0,
            "Reconciled Depreciation": 21.0,
        }},
        "cash_flow": {PERIOD: {
            "Operating Cash Flow": 35.0,
            "Capital Expenditure": -10.0,
            "Free Cash Flow": 25.0,
            "Depreciation And Amortization": None,
            "Depreciation Amortization Depletion": 21.0,
            "Depreciation": 21.0,
        }},
        "balance_sheet": {PERIOD: {
            "Cash And Cash Equivalents": 10.0,
        }},
    }


def test_depreciation_alias_uses_one_economic_value_not_the_sum():
    assert depreciation_and_amortization(_google_shaped_statements(), PERIOD) == 21.0


def test_excel_formula_scopes_aliases_to_their_statements():
    formula = depreciation_excel_formula("F$1")
    assert 'Raw!$A:$A,"Cash Flow Statement"' in formula
    assert 'Raw!$A:$A,"Income Statement"' in formula
    assert "Depreciation Amortization Depletion" in formula


def test_historical_tab_recovers_depreciation_when_canonical_row_is_null():
    workbook = openpyxl.Workbook()
    raw = RawTabBuilder()
    raw.add_data_from_json({"financial_statements": _google_shaped_statements()})
    raw.create_tab(workbook)
    HistoricalTabBuilder().create_tab(workbook)

    evaluator = FormulaEvaluator(workbook)
    evaluator.set_logger(logging.getLogger("test_depreciation_aliases"))
    cells = evaluator.evaluate_all_tabs()["Historical"]["cells"]

    assert cells["(18, 6)"] == 21.0
    assert cells["(19, 6)"] == 51.0
