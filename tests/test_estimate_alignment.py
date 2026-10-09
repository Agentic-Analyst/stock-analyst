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
    # Past the Street, the fade starts from FY2028's growth and reaches
    # terminal growth at NTM10 (seven steps after the third covered year).
    step = (319.1 / 275.0 - 1 - 0.03) / 7
    fy29 = 319.1e9 * (1 + 319.1 / 275.0 - 1 - step)
    assert path["forecast_revenue"][2] == pytest.approx(319.1e9 * (1 - progress) + fy29 * progress)


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
    # FY4-FY5 fade from FY3's 10% toward 2.5% in seven steps, so terminal
    # growth still arrives at FY10 where the perpetuity tab's stage 2 puts it.
    assert growth[3:] == pytest.approx([0.10 - 0.075 / 7, 0.10 - 2 * 0.075 / 7])
    assert grounded["revenue_growth_source"] == (
        "yahoo_analyst_consensus_absolute_revenue_with_deterministic_fade")
    assert any("FY3 10.0% (16 analysts; absolute revenue 198)" in note for note in notes)
    # The reported year is not called an estimate.
    assert any("FY1 50.0% (reported; absolute revenue 150)" in note for note in notes)


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



# ── from the review: tables that must not be realigned, and torn tables ─────

def test_a_year_ago_on_another_basis_is_not_a_reported_year():
    """Toyota and Sony: Yahoo's 0y year-ago revenue is on another basis
    (0.36x and 0.06x the statements) while the quarters match. Taking it as
    the reported year would leave a negative unreported quarter."""
    data = _micron()
    data["analyst_data"]["revenue_estimates"]["0y"]["yearAgoRevenue"] = 0.36 * 37.378e9
    data["analyst_data"]["revenue_estimates"]["+1y"]["yearAgoRevenue"] = 275.0e9
    before = copy.deepcopy(data["analyst_data"]["revenue_estimates"])
    assert align_street_estimates(data)["status"] == "unverified"
    assert data["analyst_data"]["revenue_estimates"] == before


def test_an_unchained_table_in_the_roll_window_is_not_realigned():
    data = _micron()
    data["analyst_data"]["revenue_estimates"]["+1y"]["yearAgoRevenue"] = 290.0e9
    before = copy.deepcopy(data["analyst_data"]["revenue_estimates"])
    assert align_street_estimates(data)["status"] == "unverified"
    assert data["analyst_data"]["revenue_estimates"] == before


def test_a_flat_reported_year_is_never_taken_for_a_roll():
    """A year-ago equal to the latest statement cannot be told from a table
    that has not rolled, so it is aligned; a flat year moves the model little."""
    data = _micron()
    data["analyst_data"]["revenue_estimates"]["0y"]["yearAgoRevenue"] = 37.6e9
    assert align_street_estimates(data)["status"] == "aligned"


def _jabil():
    """Jabil on 9 October 2026: 0y is FY2026 (year-ago = the FY2025 statement)
    but +1y grows from $44.78B, FY2027, so +1y is FY2028."""
    return {
        "company_data": {"basic_info": {"currency": "USD", "last_fiscal_year_end": "2026-08-30"}},
        "financial_statements": {"income_statement": {
            "2025-08-31": {"Total Revenue": 29.802e9}, "2024-08-31": {"Total Revenue": 28.883e9}}},
        "quarterly_financial_statements": {"income_statement": {
            "2026-05-31": {"Total Revenue": 8.751e9}, "2026-02-28": {"Total Revenue": 8.282e9},
            "2025-11-30": {"Total Revenue": 8.305e9}}},
        "analyst_data": {
            "revenue_estimates": {
                "0q": {"avg": 11.014e9, "numberOfAnalysts": 7, "yearAgoRevenue": 8.305e9},
                "0y": {"avg": 35.057e9, "numberOfAnalysts": 8, "yearAgoRevenue": 29.802e9},
                "+1y": {"avg": 52.073e9, "numberOfAnalysts": 7, "yearAgoRevenue": 44.784e9,
                        "growth": 0.1628},
            },
            "earnings_estimates": {
                "0y": {"avg": 17.69, "numberOfAnalysts": 10, "yearAgoEps": 13.09},
                "+1y": {"avg": 19.81, "numberOfAnalysts": 3, "yearAgoEps": 9.75},
            },
        },
    }


def test_a_torn_table_puts_the_year_0y_grows_into_in_fy2():
    data = _jabil()
    alignment = align_street_estimates(data)
    assert alignment["status"] == "torn"
    revenue = data["analyst_data"]["revenue_estimates"]
    assert revenue["0y"]["avg"] == pytest.approx(35.057e9)          # untouched
    assert revenue["+1y"]["avg"] == pytest.approx(44.784e9)         # FY2027, Yahoo's own base
    assert revenue["+1y"]["growth"] == pytest.approx(44.784 / 35.057 - 1)
    assert revenue["+2y"]["avg"] == pytest.approx(52.073e9)         # FY2028
    # Its EPS has no such base: FY2 EPS is dropped, not taken from FY2028.
    assert "+1y" not in data["analyst_data"]["earnings_estimates"]
    assert data["analyst_data"]["earnings_estimates"]["0y"]["avg"] == pytest.approx(17.69)
    assert data["analyst_data"]["provider_estimates"]["revenue_estimates"]["+1y"]["avg"] == \
        pytest.approx(52.073e9)


def test_a_torn_table_with_an_implausible_base_drops_fy2():
    data = _jabil()
    data["analyst_data"]["revenue_estimates"]["+1y"]["yearAgoRevenue"] = 300e9
    assert align_street_estimates(data)["status"] == "torn"
    assert "+1y" not in data["analyst_data"]["revenue_estimates"]
    assert "+2y" not in data["analyst_data"]["revenue_estimates"]


def test_an_empty_estimate_table_stays_empty():
    data = _micron()
    data["analyst_data"] = {}
    align_street_estimates(data)
    assert data["analyst_data"] == {}


def test_the_eps_unit_is_read_on_yahoos_own_forward_year(monkeypatch):
    """Yahoo's forward P/E is struck on its own +1y; after a realignment
    that is the provider table's row, not ours."""
    import src.external_expectations as ee
    seen = {}

    def spy(**kwargs):
        seen["forward_eps"] = kwargs.get("forward_eps")
        return {"currency": "USD", "basis": "spy", "confidence": "high"}

    monkeypatch.setattr(ee, "_infer_eps_source_currency", spy)
    data = _micron()
    align_street_estimates(data)
    build_external_expectations(data)
    assert seen["forward_eps"] == pytest.approx(206.33)


def test_the_reported_year_is_labelled_reported_downstream():
    from src.report_agent import _street_revenue_source
    data = _micron()
    align_street_estimates(data)
    years = build_external_expectations(data)["forward_estimates"]
    assert years[0]["reported"] is True and years[1]["reported"] is False
    assert _street_revenue_source(years[0], 39) == "the reported revenue"
    assert _street_revenue_source({"reported_share": 0.25}, 39, indefinite=True) == \
        "a blend of the reported year and the 39-analyst Street estimate"
    assert _street_revenue_source(years[1], 39, indefinite=True) == "a 39-analyst Street estimate"


def test_bank_forward_roe_never_counts_a_reported_year():
    """A reported year's EPS over today's book value is trailing ROE, not one
    of the two forward horizons the bank leg needs."""
    from datetime import datetime, timezone
    from src.agents.fm.bank_valuation import _forward_consensus_common_roe

    now = datetime(2026, 10, 9, tzinfo=timezone.utc)
    rows = [
        {"period": "0y", "eps": 20.0, "eps_analyst_count": 20, "reported": True},
        {"period": "+1y", "eps": 22.0, "eps_analyst_count": 20, "reported": False},
    ]
    expectations = {"captured_at": now.isoformat(), "forward_estimates": rows}
    result = _forward_consensus_common_roe(expectations, book_value_per_share=150.0, now=now)
    assert result["status"] != "ready"
    assert [row["period"] for row in result["observations"]] == ["+1y"]
    rows[0]["reported"] = False
    assert _forward_consensus_common_roe(expectations, book_value_per_share=150.0, now=now)["status"] == "ready"
