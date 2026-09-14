"""Reverse DCF must explain the market/model gap without changing fair value."""

import logging

import openpyxl
import pytest

from src.agents.fm.formula_evaluator import FormulaEvaluator
from src.agents.fm.tabs.tab_summary import SummaryTabBuilder


def _valuation_data():
    five = [0.03, 0.028, 0.026, 0.024, 0.022]
    return {
        "company_overview": {"company_name": "Example Corp", "current_price": 54.93},
        "assumptions": {
            "wacc": 0.0995,
            "terminal_growth": 0.025,
            "revenue_growth_rates": five,
            "ebitda_margins": five,
        },
        "cost_of_capital": {"wacc": 0.0995},
        "projections": {
            "revenue": [35e9] * 5,
            "ebitda": [8e9] * 5,
            "fcf": [8.31e9, 5.99e9, 6.32e9, 6.62e9, 6.88e9],
        },
        "valuation": {
            "dcf_perpetual": {
                "pv_fcfs": 40e9,
                "terminal_value": 60e9,
                "enterprise_value": 100e9,
                "equity_value": 95e9,
                "intrinsic_value_per_share": 98.34,
            },
            "dcf_exit": {
                "terminal_ev": 80e9,
                "enterprise_value": 92e9,
                "equity_value": 87e9,
                "intrinsic_value_per_share": 89.59,
                "exit_multiple": 11.0,
            },
            "summary": {
                "dcf_intrinsic": 98.34,
                "exit_intrinsic": 89.59,
                "comps_intrinsic": None,
                "average_intrinsic": 93.97,
                "upside": 0.71,
            },
            "dcf_inputs": {
                "fcf": [8.31e9, 5.99e9, 6.32e9, 6.62e9, 6.88e9,
                        7.0e9, 7.1e9, 7.2e9, 7.3e9, 7.4e9],
                "cash": 10e9,
                "debt": 12e9,
                "investments": 0.0,
                "shares": 855e6,
            },
        },
    }


def _evaluate_reverse_dcf(*, terminal_fcf=80.0):
    workbook = openpyxl.Workbook()
    dcf = workbook.active
    dcf.title = "Valuation (DCF)"
    dcf["B19"] = 100.0   # PV of explicit FY1-FY10 FCF
    dcf["B24"] = terminal_fcf    # model FY11 FCF
    # PV of the model terminal value: 80 / (10%-2%) * 0.3855.
    # The reverse DCF references this actual PV rather than assuming a horizon.
    dcf["B26"] = 385.5

    summary = workbook.create_sheet("Summary")
    summary["B4"] = 0.10
    summary["B5"] = 0.02
    summary["B29"] = 500.0
    SummaryTabBuilder()._setup_market_implied_expectations(summary)

    evaluator = FormulaEvaluator(workbook)
    evaluator.set_logger(logging.getLogger("test_reverse_dcf"))
    return summary, evaluator.evaluate_all_tabs()["Summary"]["cells"]


def test_reverse_dcf_solves_for_the_market_implied_terminal_fcf():
    _, cells = _evaluate_reverse_dcf()

    expected = (500.0 - 100.0) * (0.10 - 0.02) / 0.3855
    assert cells["(53, 2)"] == pytest.approx(expected)
    assert cells["(55, 2)"] == pytest.approx(expected / 80.0 - 1.0)


def test_reverse_dcf_is_outside_the_fair_value_rows():
    summary, _ = _evaluate_reverse_dcf()

    assert summary["B26"].value is None
    assert "excluded from fair value" in summary["A56"].value


def test_reverse_dcf_uses_the_model_terminal_pv_not_a_fixed_horizon():
    summary, _ = _evaluate_reverse_dcf()

    formula = summary["B53"].value
    assert "'Valuation (DCF)'!$B$26" in formula
    assert "$K$17" not in formula


def test_reverse_dcf_percentage_is_unavailable_for_nonpositive_model_fcf():
    _, cells = _evaluate_reverse_dcf(terminal_fcf=-80.0)

    assert isinstance(cells["(53, 2)"], (int, float))
    assert cells["(54, 2)"] == -80.0
    assert cells["(55, 2)"] == ""


def test_report_extracts_and_prints_the_diagnostic():
    from src.report_agent import extract_valuation, generate_section_valuation

    computed = {"Summary": {"cells": {
        "(51, 2)": 500.0,
        "(52, 2)": 100.0,
        "(53, 2)": 83.009,
        "(54, 2)": 80.0,
        "(55, 2)": 0.03761,
    }}}
    reverse = extract_valuation(computed)["reverse_dcf"]
    data = _valuation_data()
    data["valuation"]["reverse_dcf"] = reverse

    text, _ = generate_section_valuation(
        data, lambda messages, temperature=0.5: ("commentary", 0.0)
    )

    assert "### Market-Implied Expectations (Reverse DCF)" in text
    assert "| Market-Implied Terminal FCF (Post-Horizon) | $83.01 |" in text
    assert "| Market-Implied FCF vs Model | 3.8% |" in text
    assert "excluded from fair value" in text


def test_bank_report_omits_inapplicable_reverse_dcf_section():
    from src.report_agent import generate_section_valuation

    data = _valuation_data()
    data["valuation"]["bank"] = {
        "fair_value": 159.34,
        "method": "Justified P/B x ROE",
        "inputs": {},
    }
    text, _ = generate_section_valuation(
        data, lambda messages, temperature=0.5: ("commentary", 0.0)
    )

    assert "### Market-Implied Expectations (Reverse DCF)" not in text
    assert "### Bank Valuation Inputs" in text
