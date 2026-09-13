from datetime import datetime, timezone

import pytest

from src.financial_period_bridge import build_ttm_bridge


NOW = datetime(2026, 9, 12, tzinfo=timezone.utc)
PERIODS = ("2026-06-30", "2026-03-31", "2025-12-31", "2025-09-30")


def _statements(periods=PERIODS):
    return {
        "income_statement": {
            period: {
                "Total Revenue": 100.0,
                "Operating Income": 20.0,
                "Diluted Average Shares": 10.0 + index,
                "Tax Rate For Calcs": 0.20,
                "Tax Provision": 5.0,
                "Pretax Income": 20.0,
            }
            for index, period in enumerate(periods)
        },
        "cash_flow": {
            period: {
                "Operating Cash Flow": 30.0,
                "Capital Expenditure": -10.0,
                "Depreciation And Amortization": 8.0,
            }
            for period in periods
        },
        "balance_sheet": {
            period: {
                "Cash And Cash Equivalents": 50.0 + index,
                "Cash Cash Equivalents And Short Term Investments": 80.0 + index,
                "Total Debt": 25.0 + index,
            }
            for index, period in enumerate(periods)
        },
    }


def test_four_aligned_quarters_build_a_current_ttm_bridge(monkeypatch):
    monkeypatch.setenv("QUARTERLY_STATEMENT_MAX_AGE_DAYS", "150")
    result = build_ttm_bridge(_statements(), as_of=NOW)

    assert result["status"] == "current"
    assert result["basis"] == "ttm"
    assert result["latest_period"] == "2026-06-30"
    assert result["income_statement"]["Total Revenue"] == 400.0
    assert result["income_statement"]["Diluted Average Shares"] == pytest.approx(11.5)
    assert result["income_statement"]["Tax Rate For Calcs"] == pytest.approx(0.20)
    assert result["cash_flow"]["Capital Expenditure"] == -40.0
    assert result["normalized"]["capex_to_revenue"] == pytest.approx(-0.10)
    assert result["normalized"]["da_to_revenue"] == pytest.approx(0.08)
    assert result["normalized"]["short_term_investments"] == pytest.approx(30.0)
    assert result["normalized"]["non_operating_investments"] == pytest.approx(30.0)
    assert result["normalized"]["effective_tax_rate"] == pytest.approx(0.25)


def test_ttm_requires_four_common_consecutive_periods():
    statements = _statements(PERIODS[:3])
    result = build_ttm_bridge(statements, as_of=NOW)
    assert result["status"] == "unavailable"
    assert "four are required" in result["reason"]


def test_misaligned_or_stale_quarters_cannot_become_model_inputs(monkeypatch):
    statements = _statements()
    statements["balance_sheet"].pop("2026-06-30")
    assert build_ttm_bridge(statements, as_of=NOW)["status"] == "unavailable"

    monkeypatch.setenv("QUARTERLY_STATEMENT_MAX_AGE_DAYS", "90")
    stale = build_ttm_bridge(
        _statements(), as_of=datetime(2026, 10, 15, tzinfo=timezone.utc)
    )
    assert stale["status"] == "stale"
    assert stale["basis"] == "annual"


def test_environment_cannot_accept_a_quarter_older_than_six_months(monkeypatch):
    monkeypatch.setenv("QUARTERLY_STATEMENT_MAX_AGE_DAYS", "9999")
    result = build_ttm_bridge(
        _statements(), as_of=datetime(2027, 1, 15, tzinfo=timezone.utc)
    )

    assert result["max_age_days"] == 180
    assert result["status"] == "stale"


def test_future_quarters_are_not_accepted():
    periods = ("2027-06-30", "2027-03-31", "2026-12-31", "2026-09-30")
    result = build_ttm_bridge(_statements(periods), as_of=NOW)
    assert result["status"] == "unavailable"


def test_partial_quarter_flow_does_not_masquerade_as_a_ttm_value():
    statements = _statements()
    for index, period in enumerate(PERIODS):
        if index:
            statements["cash_flow"][period].pop("Depreciation And Amortization")

    result = build_ttm_bridge(statements, as_of=NOW)

    assert "Depreciation And Amortization" not in result["cash_flow"]
    assert result["normalized"]["depreciation_and_amortization"] is None
    assert result["normalized"]["da_to_revenue"] is None


def test_zero_placeholder_quarters_do_not_create_partial_ttm_depreciation():
    statements = _statements()
    for period in PERIODS[1:]:
        statements["cash_flow"][period]["Depreciation And Amortization"] = 0.0

    result = build_ttm_bridge(statements, as_of=NOW)

    assert result["normalized"]["depreciation_and_amortization"] is None
    assert result["normalized"]["da_to_revenue"] is None


def test_income_statement_depreciation_does_not_replace_cash_flow_da():
    statements = _statements()
    for period in PERIODS:
        statements["cash_flow"][period].pop("Depreciation And Amortization")
        statements["income_statement"][period]["Reconciled Depreciation"] = 1.0

    result = build_ttm_bridge(statements, as_of=NOW)

    assert result["normalized"]["depreciation_and_amortization"] is None
    assert result["normalized"]["da_to_revenue"] is None


def test_complete_fcf_and_ocf_derive_missing_capex_exactly():
    statements = _statements()
    for period in PERIODS:
        statements["cash_flow"][period].pop("Capital Expenditure")
        statements["cash_flow"][period]["Free Cash Flow"] = 20.0

    result = build_ttm_bridge(statements, as_of=NOW)

    assert result["normalized"]["capital_expenditure"] == -40.0
    assert result["normalized"]["capital_expenditure_source"] == (
        "derived_from_complete_fcf_minus_ocf"
    )
    assert result["normalized"]["capex_to_revenue"] == pytest.approx(-0.10)


def test_total_investment_line_can_capture_noncurrent_marketable_securities():
    statements = _statements()
    for period in PERIODS:
        statements["balance_sheet"][period].update({
            "Other Short Term Investments": 23.0,
            "Investments And Advances": 84.0,
        })

    result = build_ttm_bridge(statements, as_of=NOW)

    assert result["normalized"]["short_term_investments"] == 23.0
    assert result["normalized"]["non_operating_investments"] == 107.0
    assert result["normalized"]["non_operating_investments_source"] == (
        "short_term_investments_plus_investments_and_advances"
    )
