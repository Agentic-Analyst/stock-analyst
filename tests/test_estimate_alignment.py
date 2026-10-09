"""Yahoo's estimate clock must match the statements' fiscal years."""

import copy

import pytest

from src.agents.fm.assumption_grounding import _rolling_consensus_revenue_path
from src.estimate_alignment import align_street_estimates, estimate_alignment
from src.external_expectations import (
    align_forward_estimates_to_forecast_basis,
    build_external_expectations,
)
from src.financial_scraper import _epoch_date


def _micron():
    """Micron on 9 October 2026: FY2026 (ended 3 Sep) reported, Yahoo rolled,
    statements still at FY2025 annual and May 2026 quarterly."""
    return {
        "company_data": {
            "basic_info": {
                "currency": "USD",
                "last_fiscal_year_end": "2026-09-03",
                "most_recent_quarter": "2026-09-03",
            },
            "market_data": {"shares_outstanding_basic": 1.12e9},
        },
        "financial_statements": {
            "income_statement": {
                "2025-08-31": {"Total Revenue": 37.378e9},
                "2024-08-31": {"Total Revenue": 25.111e9},
            },
        },
        "quarterly_financial_statements": {
            "income_statement": {
                "2026-05-31": {"Total Revenue": 41.456e9},
                "2026-02-28": {"Total Revenue": 23.860e9},
                "2025-11-30": {"Total Revenue": 13.643e9},
                "2025-08-31": {"Total Revenue": 11.315e9},
            },
        },
        "ttm_bridge": {
            "status": "current",
            "latest_period": "2026-05-31",
            "normalized": {"revenue": 90.274e9},
        },
        "analyst_data": {
            "revenue_estimates": {
                "0q": {"avg": 61.67e9, "numberOfAnalysts": 33, "yearAgoRevenue": 13.643e9},
                "+1q": {"avg": 66.97e9, "numberOfAnalysts": 31, "yearAgoRevenue": 23.860e9},
                "0y": {"avg": 275.0e9, "numberOfAnalysts": 39,
                       "yearAgoRevenue": 133.188e9, "growth": 1.0648, "currency": "USD"},
                "+1y": {"avg": 319.1e9, "numberOfAnalysts": 42,
                        "yearAgoRevenue": 275.0e9, "growth": 0.1603, "currency": "USD"},
            },
            "earnings_estimates": {
                "0y": {"avg": 176.15, "numberOfAnalysts": 36, "yearAgoEps": 73.88,
                       "growth": 1.3842, "currency": "USD"},
                "+1y": {"avg": 206.33, "numberOfAnalysts": 36, "yearAgoEps": 176.15,
                        "growth": 0.1713, "currency": "USD"},
            },
        },
    }


def test_rolled_estimates_put_the_reported_year_back_in_front():
    data = _micron()
    provider = copy.deepcopy(data["analyst_data"])
    alignment = align_street_estimates(data)

    assert alignment["status"] == "rolled"
    assert alignment["current_quarter_year_ago_period"] == "2025-11-30"
    revenue = data["analyst_data"]["revenue_estimates"]
    eps = data["analyst_data"]["earnings_estimates"]
    # 0y is FY2026, the year after the FY2025 statement: reported, not estimated.
    assert revenue["0y"]["avg"] == pytest.approx(133.188e9)
    assert revenue["0y"]["reported"] is True
    assert revenue["0y"]["growth"] == pytest.approx(133.188 / 37.378 - 1)
    assert eps["0y"]["avg"] == pytest.approx(73.88)
    # Yahoo's FY2027 and FY2028 follow it.
    assert revenue["+1y"]["avg"] == pytest.approx(275.0e9)
    assert revenue["+2y"]["avg"] == pytest.approx(319.1e9)
    assert eps["+1y"]["avg"] == pytest.approx(176.15)
    assert eps["+2y"]["avg"] == pytest.approx(206.33)
    # The provider's own table stays auditable.
    assert data["analyst_data"]["provider_estimates"]["revenue_estimates"] == \
        provider["revenue_estimates"]
    assert "2026-09-03" in alignment["note"] and "2025-08-31" in alignment["note"]


def test_alignment_is_idempotent():
    data = _micron()
    align_street_estimates(data)
    once = copy.deepcopy(data["analyst_data"])
    align_street_estimates(data)
    assert data["analyst_data"] == once


def test_same_year_estimates_are_left_alone():
    data = _micron()
    data["analyst_data"]["revenue_estimates"]["0y"]["yearAgoRevenue"] = 37.5e9
    before = copy.deepcopy(data["analyst_data"]["revenue_estimates"])
    assert align_street_estimates(data)["status"] == "aligned"
    assert data["analyst_data"]["revenue_estimates"] == before
    assert "provider_estimates" not in data["analyst_data"]


def test_a_different_revenue_definition_is_not_a_rolled_year():
    """Ford, Deere, GE: Yahoo's revenue excludes a finance arm or an item the
    statements include, so the year-ago figure never matches, on the same
    fiscal year."""
    data = _micron()
    data["company_data"]["basic_info"]["last_fiscal_year_end"] = "2025-08-31"
    data["analyst_data"]["revenue_estimates"]["0y"]["yearAgoRevenue"] = 34.7e9
    before = copy.deepcopy(data["analyst_data"]["revenue_estimates"])
    alignment = align_street_estimates(data)
    assert alignment["status"] == "aligned"
    assert alignment["year_ago_revenue_ratio"] == pytest.approx(34.7 / 37.378)
    assert data["analyst_data"]["revenue_estimates"] == before


@pytest.mark.parametrize("change", ["no_clock", "quarter_before_statement", "no_quarter_match",
                                    "two_years"])
def test_an_unconfirmed_roll_changes_nothing(change):
    data = _micron()
    basic = data["company_data"]["basic_info"]
    quarter = data["analyst_data"]["revenue_estimates"]["0q"]
    if change == "no_clock":
        basic.pop("last_fiscal_year_end")
    elif change == "quarter_before_statement":
        # Its current quarter is a year after a quarter the annual statement
        # already contains: Yahoo has not moved past the statements.
        data["quarterly_financial_statements"]["income_statement"]["2025-05-31"] = {
            "Total Revenue": 9.301e9}
        quarter["yearAgoRevenue"] = 9.301e9
    elif change == "no_quarter_match":
        quarter["yearAgoRevenue"] = 14.9e9
    else:
        basic["last_fiscal_year_end"] = "2027-09-02"
    before = copy.deepcopy(data["analyst_data"]["revenue_estimates"])
    assert align_street_estimates(data)["status"] == "unverified"
    assert data["analyst_data"]["revenue_estimates"] == before


def test_missing_inputs_are_unknown_not_an_error():
    assert estimate_alignment({})["status"] == "unknown"
    data = _micron()
    data["financial_statements"]["income_statement"] = {}
    assert align_street_estimates(data)["status"] == "unknown"


def test_rolling_path_uses_the_third_street_year_instead_of_a_fade():
    data = _micron()
    align_street_estimates(data)
    qualified = {
        period: (row["avg"], row["numberOfAnalysts"])
        for period, row in data["analyst_data"]["revenue_estimates"].items()
        if period in ("0y", "+1y", "+2y")
    }
    path = _rolling_consensus_revenue_path(data, qualified, terminal_growth=0.03)
    progress = path["fiscal_year_progress"]
    assert progress == pytest.approx(273 / 365)
    # NTM1 (June 2026 - May 2027): the last quarter of reported FY2026 and
    # three of FY2027. NTM2: FY2027 into FY2028, both the Street's.
    assert path["forecast_revenue"][0] == pytest.approx(
        133.188e9 * (1 - progress) + 275.0e9 * progress)
    assert path["forecast_revenue"][1] == pytest.approx(
        275.0e9 * (1 - progress) + 319.1e9 * progress)
    assert path["covered_growth"] == pytest.approx(319.1 / 275.0 - 1)
    assert path["analyst_counts"] == {"0y": 39, "+1y": 39, "+2y": 42}


def test_the_publication_check_sees_the_same_first_year_as_the_model():
    """The boundary compares the model's NTM1 with the Street's on the same
    clock; realigning only the model would make every rolled name disagree."""
    data = _micron()
    align_street_estimates(data)
    qualified = {
        period: (row["avg"], row["numberOfAnalysts"])
        for period, row in data["analyst_data"]["revenue_estimates"].items()
        if period in ("0y", "+1y", "+2y")
    }
    path = _rolling_consensus_revenue_path(data, qualified, terminal_growth=0.03)
    expectations = build_external_expectations(data)
    street = align_forward_estimates_to_forecast_basis(expectations, path)
    assert street[0]["revenue"] == pytest.approx(path["forecast_revenue"][0])


def test_epoch_date():
    assert _epoch_date(1788393600) == "2026-09-03"
    for value in (None, True, 0, -5, float("nan"), "1788393600"):
        assert _epoch_date(value) is None


def _annual_data(revenue_estimates):
    return {
        "company_data": {
            "basic_info": {"currency": "USD", "country": "United States"},
            "capital_structure": {"beta": 1.0, "total_debt": 0},
            "market_data": {"market_cap": 1e9},
            "growth_profitability": {},
            "valuation_metrics": {},
        },
        "financial_statements": {
            "income_statement": {
                "2025-12-31": {"Total Revenue": 100.0},
                "2024-12-31": {"Total Revenue": 90.0},
            },
        },
        "analyst_data": {"revenue_estimates": revenue_estimates},
    }


def test_annual_path_takes_the_third_street_year_then_fades_from_it(monkeypatch):
    from src.agents.fm.assumption_grounding import ground_assumptions

    monkeypatch.setenv("RISK_FREE_USD", "0.04")
    grounded, notes = ground_assumptions({
        "wacc": 0.09,
        "terminal_growth_rate": 0.025,
        "revenue_growth_rates": [0.04] * 5,
    }, _annual_data({
        "0y": {"avg": 150.0, "numberOfAnalysts": 17, "reported": True},
        "+1y": {"avg": 180.0, "numberOfAnalysts": 17},
        "+2y": {"avg": 198.0, "numberOfAnalysts": 16},
    }))

    growth = grounded["revenue_growth_rates"]
    assert growth[:3] == pytest.approx([0.50, 0.20, 0.10])
    # FY4-FY5 fade from FY3's 10% toward 2.5% in eight steps.
    assert growth[3:] == pytest.approx([0.10 - 0.075 / 8, 0.10 - 2 * 0.075 / 8])
    assert grounded["revenue_growth_source"] == (
        "yahoo_analyst_consensus_absolute_revenue_with_deterministic_fade")
    assert any("FY3 10.0% (16 analysts; absolute revenue 198)" in note for note in notes)


def test_a_third_year_never_stands_in_for_a_missing_second(monkeypatch):
    from src.agents.fm.assumption_grounding import ground_assumptions

    monkeypatch.setenv("RISK_FREE_USD", "0.04")
    grounded, _ = ground_assumptions({
        "wacc": 0.09,
        "terminal_growth_rate": 0.025,
        "revenue_growth_rates": [0.04] * 5,
    }, _annual_data({
        "0y": {"avg": 150.0, "numberOfAnalysts": 17},
        "+1y": {"avg": 180.0, "numberOfAnalysts": 2},
        "+2y": {"avg": 198.0, "numberOfAnalysts": 16},
    }))
    assert grounded["revenue_growth_rates"][0] == pytest.approx(0.50)
    assert grounded["revenue_growth_rates"][2] != pytest.approx(0.10)
