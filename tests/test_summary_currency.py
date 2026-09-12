"""
THE BUG: financial_summary_agent.format_number hardcoded "$", so every figure
in a euro, yen or rupee summary was labelled as dollars.

This is the SAME defect report_agent.format_number was fixed for — its
docstring records LVMH projections reading "$83.23B" and PC Jeweller's
"$44.26B" — on a file the fix was never applied to. It matters because the
summary is downloadable as a PDF (api-runner main.py:2290), so those figures
reach a user directly rather than only feeding a prompt.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import financial_summary_agent as fsa


def setup_function():
    fsa.set_summary_currency(None)


def teardown_function():
    fsa.set_summary_currency(None)


def overview(currency):
    return fsa.extract_company_overview({
        "ticker": "X",
        "company_data": {
            "basic_info": {"long_name": "X", "currency": currency},
            "market_data": {"current_price": 1.0, "market_cap": 3.5e11},
            "valuation_metrics": {}, "capital_structure": {},
            "growth_profitability": {}, "forward_guidance": {},
        },
    })


def test_a_euro_company_is_not_priced_in_dollars():
    overview("EUR")
    assert fsa.format_number(3.5e11) == "€350.00B"


def test_every_magnitude_branch_uses_the_currency():
    overview("JPY")
    assert fsa.format_number(1.5e9).startswith("¥")
    assert fsa.format_number(1.5e6).startswith("¥")
    assert fsa.format_number(1.5e3).startswith("¥")
    assert fsa.format_number(15.0).startswith("¥")


def test_a_rupee_company_reads_in_rupees():
    overview("INR")
    assert fsa.format_number(4.426e10) == "₹44.26B"


def test_a_dollar_company_still_reads_in_dollars():
    overview("USD")
    assert fsa.format_number(3.5e11) == "$350.00B"


def test_an_unknown_currency_falls_back_rather_than_raising():
    overview("ZZZ")
    assert fsa.format_number(1000.0).endswith("1.00K")


def test_a_company_with_no_currency_defaults_to_a_dollar():
    overview(None)
    assert fsa.format_number(1.5e9) == "$1.50B"


def test_the_currency_is_pinned_where_the_data_is_read():
    """So a new entry point cannot forget to pin it and silently print dollars."""
    assert overview("GBP")["currency"] == "GBP"
    assert fsa.format_number(1.0) == "£1.00"


def test_a_later_run_is_not_contaminated_by_an_earlier_one():
    overview("EUR")
    assert fsa.format_number(1.0) == "€1.00"
    overview("USD")
    assert fsa.format_number(1.0) == "$1.00"


def test_none_is_still_not_a_number():
    overview("EUR")
    assert fsa.format_number(None) == "N/A"
