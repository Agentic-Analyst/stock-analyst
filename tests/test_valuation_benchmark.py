from datetime import datetime, timezone

import pytest

from src.valuation_benchmark import (
    benchmark,
    formula_signature,
    latest_by_ticker,
    methodology_values,
)


def thesis(ticker="AAPL", *, recorded=100.0, perpetual=80.0, exit_multiple=100.0,
           comps=140.0, price=100.0, completed="2026-01-01T00:00:00Z",
           version=1, model_version="model-v2", rating="HOLD", capm=True):
    return {
        "ticker": ticker,
        "version": version,
        "model_version": model_version,
        "completed_at": completed,
        "capm_derived": capm,
        "valuation": {
            "fair_value": recorded,
            "perpetual": perpetual,
            "exit_multiple": exit_multiple,
            "comps": comps,
            "current_price": price,
        },
        "verdict": {"rating": rating},
    }


def market(ticker="AAPL", *, quote_type="EQUITY", price=100.0,
           analyst_target=120.0, analyst_count=20, sector="Technology"):
    return {
        "symbol": ticker,
        "quote_type": quote_type,
        "price_at_refresh": price,
        "analyst_target_mean": analyst_target,
        "analyst_count": analyst_count,
        "sector": sector,
    }


def test_method_equal_replay_gives_each_method_one_vote():
    values = methodology_values(thesis())
    assert values["dcf_view"] == 90.0
    assert values["flat_three_leg"] == pytest.approx(106.666667)
    assert values["method_equal"] == 115.0


def test_failed_legs_are_excluded_without_halving_a_survivor():
    assert methodology_values(thesis(perpetual=-5, exit_multiple=100, comps=0))["method_equal"] == 100
    assert methodology_values(thesis(perpetual=0, exit_multiple=0, comps=140))["method_equal"] == 140


def test_formula_signature_distinguishes_old_and_current_blends():
    assert formula_signature(thesis(recorded=115.0)) == "method_equal"
    assert formula_signature(thesis(recorded=106.666667)) == "flat_three_leg"
    assert formula_signature(thesis(recorded=77.0)) == "other"
    assert formula_signature(thesis(recorded=None)) == "unavailable"


def test_latest_cohort_is_selected_within_a_model_version():
    docs = [
        thesis(completed="2026-01-01T00:00:00Z", version=1),
        thesis(completed="2026-02-01T00:00:00Z", version=2),
        thesis(ticker="MSFT", model_version="old"),
    ]
    assert [doc["version"] for doc in latest_by_ticker(docs, model_version="model-v2")] == [2]


def test_benchmark_reports_bias_and_analyst_disagreement_without_blending_consensus():
    result = benchmark(
        [thesis(recorded=80, perpetual=70, exit_multiple=90, comps=120, rating="SELL")],
        [market(analyst_target=125)],
        now=datetime(2026, 9, 10, tzinfo=timezone.utc),
    )
    assert result["recorded_at_run"]["fair_value_gap"]["median"] == -0.2
    assert result["method_equal_replay_at_run"]["fair_value_gap"]["median"] == 0.0
    cross = result["current_analyst_cross_check"]
    assert cross["model_gap"]["median"] == 0.0
    assert cross["analyst_gap"]["median"] == 0.25
    assert cross["model_minus_analyst_gap"]["median"] == -0.25
    assert result["recorded_at_run"]["ratings"] == {"SELL": 1}


def test_non_equities_and_unclassified_rows_do_not_enter_current_cross_check():
    docs = [thesis("VOO"), thesis("UNKNOWN")]
    result = benchmark(docs, [market("VOO", quote_type="ETF")])
    assert result["data_quality"]["domains"] == {"non_equity": 1, "unclassified": 1}
    assert result["current_analyst_cross_check"]["model_gap"]["n"] == 0
    assert result["recorded_at_run"]["fair_value_gap"]["n"] == 0


def test_readiness_requires_a_fresh_versioned_and_well_covered_cohort():
    docs = [thesis(f"T{i}") for i in range(20)]
    sector_names = ["Technology", "Financials", "Healthcare", "Industrials", "Energy"]
    markets = [market(f"T{i}", sector=sector_names[i % len(sector_names)])
               for i in range(20)]
    ready = benchmark(docs, markets)
    assert ready["readiness"]["cross_sectional_calibration_ready"] is True
    assert ready["readiness"]["forecast_backtest_ready"] is False

    docs[0]["model_version"] = None
    docs[1]["capm_derived"] = False
    docs[2]["valuation"]["comps"] = None
    unready = benchmark(docs, markets)
    blockers = unready["readiness"]["cross_sectional_blockers"]
    assert "cohort_contains_unversioned_runs" in blockers

    docs[0]["model_version"] = "model-v1"
    mixed = benchmark(docs, markets)
    assert "cohort_mixes_model_versions" in mixed["readiness"]["cross_sectional_blockers"]


def test_twelve_month_readiness_is_about_observation_age_not_model_optimism():
    docs = [thesis(f"T{i}", completed="2024-01-01T00:00:00Z") for i in range(20)]
    result = benchmark(
        docs, [market(f"T{i}") for i in range(20)],
        now=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )
    assert result["data_quality"]["age_eligible_for_12m_backtest"] == 20
    assert result["readiness"]["forecast_backtest_ready"] is True


def test_cross_sectional_readiness_rejects_a_sector_concentrated_sample():
    docs = [thesis(f"T{i}") for i in range(20)]
    result = benchmark(docs, [market(f"T{i}", sector="Technology") for i in range(20)])
    blockers = result["readiness"]["cross_sectional_blockers"]
    assert "fewer_than_5_equity_sectors" in blockers
    assert "single_sector_exceeds_40_percent" in blockers
