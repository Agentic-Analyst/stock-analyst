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


def test_future_quarters_are_not_accepted():
    periods = ("2027-06-30", "2027-03-31", "2026-12-31", "2026-09-30")
    result = build_ttm_bridge(_statements(periods), as_of=NOW)
    assert result["status"] == "unavailable"
