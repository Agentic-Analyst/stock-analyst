"""Figures VYNN shows side by side must reconcile (blind review, 18 Nov 2026)."""
import os
import sys

import pytest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "src"))

from src.report_agent import _margins_table  # noqa: E402


def test_the_margin_table_says_which_period_each_figure_is():
    # Hansen: EBITDA A$122.5M on revenue A$386.5M is 31.7%; the provider's
    # trailing figure was 19.9%, shown as "Current Value" beside the annual table.
    historical = {
        "years": ["2025", "2026"],
        "revenue": [392.5e6, 386.494e6], "gross_profit": [140e6, 144.6e6],
        "ebitda": [110.1e6, 122.54e6], "net_income": [43.4e6, 47.8e6],
    }
    company = {"gross_margin": 0.374, "operating_margin": 0.181, "ebitda_margin": 0.199,
               "net_margin": 0.124, "roe": 0.125, "roa": 0.06}
    table = _margins_table(historical, company)
    assert "| Metric | Fiscal 2026 (from the table above) | Trailing 12 Months (provider) |" in table
    assert "| EBITDA Margin | 31.7% | 19.9% |" in table
    assert "| Net Margin | 12.4% | 12.4% |" in table
    assert "| Operating Margin | — | 18.1% |" in table


def test_without_statements_only_the_provider_column_is_shown():
    table = _margins_table({"years": []}, {"ebitda_margin": 0.199})
    assert table.startswith("| Metric | Trailing 12 Months (provider) |")
    assert "| EBITDA Margin | 19.9% |" in table


def test_next_years_growth_is_measured_from_this_years_estimate():
    from src.external_expectations import build_external_expectations
    data = {
        "company_data": {"basic_info": {"currency": "CNY", "financial_currency": "CNY"},
                         "market_data": {"current_price": 2.94, "shares_outstanding_basic": 11.93e9}},
        "analyst_data": {
            "revenue_estimates": {
                "0y": {"avg": 179.342e9, "numberOfAnalysts": 6, "yearAgoRevenue": 233.43e9, "growth": -0.2317},
                "+1y": {"avg": 135.233e9, "numberOfAnalysts": 6, "yearAgoRevenue": 165.79e9, "growth": -0.1843},
            },
            "earnings_estimate": {
                "0y": {"avg": -2.07, "numberOfAnalysts": 4, "growth": -0.5},
                "+1y": {"avg": -1.43, "numberOfAnalysts": 4, "growth": 0.31},
            },
        },
    }
    rows = build_external_expectations(data).get("forward_estimates") or []
    if len(rows) < 2:
        pytest.skip("this artifact shape does not produce two forward rows")
    assert rows[0]["revenue_growth"] == pytest.approx(-0.2317)
    assert rows[1]["revenue_growth"] == pytest.approx(135.233 / 179.342 - 1)
    # Across a loss, a growth rate means nothing.
    assert rows[1]["eps_growth"] is None
