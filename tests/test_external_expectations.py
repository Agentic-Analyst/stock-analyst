import pytest

from src.external_expectations import (
    align_forward_estimates_to_forecast_basis,
    build_external_expectations,
    implied_discount_rate_for_enterprise_value,
    implied_fcf_path_scale_for_enterprise_value,
    implied_terminal_growth_for_enterprise_value,
    implied_terminal_fcf_for_enterprise_value,
    reconcile_model_profitability,
)


def test_fiscal_street_estimates_are_aligned_to_rolling_model_clock():
    expectations = {"forward_estimates": [
        {
            "period": "0y", "revenue": 100.0, "eps": 2.0,
            "implied_net_income": 20.0,
            "revenue_analyst_count": 10, "eps_analyst_count": 9,
        },
        {
            "period": "+1y", "revenue": 140.0, "eps": 3.0,
            "implied_net_income": 35.0,
            "revenue_analyst_count": 8, "eps_analyst_count": 7,
        },
    ]}
    basis = {
        "basis": "rolling_twelve_months",
        "period_end": "2026-06-30",
        "fiscal_year_progress": 0.25,
        "base_revenue": 90.0,
    }

    aligned = align_forward_estimates_to_forecast_basis(expectations, basis)

    assert len(aligned) == 1
    assert aligned[0]["horizon"] == "NTM1"
    assert aligned[0]["period"] == "NTM ending 2027-06-30"
    assert aligned[0]["revenue"] == pytest.approx(110.0)
    assert aligned[0]["eps"] == pytest.approx(2.25)
    assert aligned[0]["implied_net_income"] == pytest.approx(23.75)
    assert aligned[0]["implied_net_margin"] == pytest.approx(23.75 / 110.0)
    assert aligned[0]["revenue_analyst_count"] == 8
    assert aligned[0]["eps_analyst_count"] == 7
    assert aligned[0]["revenue_growth"] == pytest.approx(110.0 / 90.0 - 1.0)

    profitability = reconcile_model_profitability(
        expectations, {"revenue": [110.0], "nopat": [24.0]}, basis
    )
    assert [row["horizon"] for row in profitability["rows"]] == ["NTM1"]
    # A second hard-conflict vote is unavailable without Street +2y data.
    assert profitability["conflicts"] == []


def test_invalid_or_absent_rolling_basis_preserves_fiscal_estimates():
    expectations = {"forward_estimates": [
        {"period": "0y", "revenue": 100.0},
        {"period": "+1y", "revenue": 120.0},
    ]}

    assert align_forward_estimates_to_forecast_basis(
        expectations, {"basis": "annual_fiscal_year"}
    ) == expectations["forward_estimates"]
    assert align_forward_estimates_to_forecast_basis(
        expectations, {
            "basis": "rolling_twelve_months", "fiscal_year_progress": 2.0,
        }
    ) == expectations["forward_estimates"]


def _dcf_value(path, wacc, growth, mid_year_adjustment=0.0):
    return (
        sum(value / (1 + wacc) ** (year - mid_year_adjustment)
            for year, value in enumerate(path, start=1))
        + path[-1] * (1 + growth) / (wacc - growth)
        / (1 + wacc) ** (len(path) - mid_year_adjustment)
    )


def test_reverse_dcf_solves_implied_wacc_without_tuning_the_model():
    path = [100.0, 110.0, 120.0, 130.0, 140.0]
    target = _dcf_value(path, 0.075, 0.025)

    result = implied_discount_rate_for_enterprise_value(
        target, explicit_fcf=path, terminal_growth=0.025, model_wacc=0.09,
    )

    assert result["available"] is True
    assert result["implied_wacc"] == pytest.approx(0.075, abs=1e-10)
    assert result["implied_wacc_vs_model"] == pytest.approx(-0.015)
    assert "benchmark_only" in result["role"]


def test_reverse_dcf_solves_implied_terminal_growth_at_fixed_wacc():
    path = [100.0, 110.0, 120.0, 130.0, 140.0]
    target = _dcf_value(path, 0.09, 0.045)

    result = implied_terminal_growth_for_enterprise_value(
        target, explicit_fcf=path, wacc=0.09, model_terminal_growth=0.025,
    )

    assert result["available"] is True
    assert result["implied_terminal_growth"] == pytest.approx(0.045, abs=1e-10)
    assert result["implied_terminal_growth_vs_model"] == pytest.approx(0.02)


def test_reverse_dcf_assumption_solvers_match_mid_year_workbook_timing():
    path = [100.0, 110.0, 120.0, 130.0, 140.0]
    target = _dcf_value(path, 0.075, 0.035, mid_year_adjustment=0.5)

    rate = implied_discount_rate_for_enterprise_value(
        target,
        explicit_fcf=path,
        terminal_growth=0.035,
        model_wacc=0.09,
        mid_year_adjustment=0.5,
    )
    growth = implied_terminal_growth_for_enterprise_value(
        target,
        explicit_fcf=path,
        wacc=0.075,
        model_terminal_growth=0.025,
        mid_year_adjustment=0.5,
    )

    assert rate["implied_wacc"] == pytest.approx(0.075, abs=1e-10)
    assert growth["implied_terminal_growth"] == pytest.approx(0.035, abs=1e-10)


@pytest.mark.parametrize("timing", [-0.1, 1.1, None, float("nan")])
def test_reverse_dcf_rejects_invalid_discount_timing(timing):
    assert not implied_discount_rate_for_enterprise_value(
        1000.0,
        explicit_fcf=[100.0, 110.0],
        terminal_growth=0.025,
        mid_year_adjustment=timing,
    )["available"]


@pytest.mark.parametrize("function,kwargs", [
    (implied_discount_rate_for_enterprise_value,
     {"explicit_fcf": [], "terminal_growth": 0.025}),
    (implied_terminal_growth_for_enterprise_value,
     {"explicit_fcf": [100.0], "wacc": None}),
])
def test_reverse_dcf_assumption_solvers_fail_closed(function, kwargs):
    assert function(1000.0, **kwargs)["available"] is False


def test_whole_path_reverse_dcf_is_a_linear_ev_benchmark():
    result = implied_fcf_path_scale_for_enterprise_value(
        4_800.0, model_enterprise_value=2_000.0
    )

    assert result["available"] is True
    assert result["scale"] == pytest.approx(2.4)
    assert result["implied_fcf_path_vs_model"] == pytest.approx(1.4)
    assert "benchmark_only" in result["role"]


def test_whole_path_reverse_dcf_rejects_nonpositive_or_missing_ev():
    assert not implied_fcf_path_scale_for_enterprise_value(
        None, model_enterprise_value=2_000.0
    )["available"]
    assert not implied_fcf_path_scale_for_enterprise_value(
        1_000.0, model_enterprise_value=0
    )["available"]


def data():
    return {
        "company_data": {
            "basic_info": {"currency": "USD"},
            "market_data": {
                "current_price": 332.27,
                "shares_outstanding_basic": 14_900_000_000,
            },
            "analyst_consensus": {
                "captured_at": "2026-09-12T05:37:00Z",
                "price_target": {
                    "mean": 324.4, "median": 335, "low": 215, "high": 400,
                    "analyst_count": 39, "currency": "USD",
                    "source": "yahoo_finance", "as_of": None,
                },
                "recommendation": {"label": "strong_buy", "source": "finnhub"},
                "analyst_observations": {
                    "source": "benzinga",
                    "observation_count": 2,
                    "as_of": "2026-09-11",
                    "observations": [
                        {
                            "date": "2026-09-11", "firm": "Firm One",
                            "action": "Maintains", "rating": "buy",
                            "price_target": 350.0,
                            "source": "benzinga",
                        },
                        {
                            "date": "2026-09-10", "firm": "Firm Two",
                            "action": "Raises", "rating": "strong_buy",
                            "price_target": 375.0,
                            "source": "benzinga",
                        },
                    ],
                },
                "source_snapshots": {
                    "benzinga": {"price_target": {
                        "mean": 334.94, "analyst_count": 24,
                        "currency": "USD", "as_of": "2026-09-12T05:00:00Z",
                    }},
                    "yahoo_finance": {"price_target": {
                        "mean": 324.4, "analyst_count": 39,
                        "currency": "USD", "as_of": None,
                    }, "recommendation": {
                        "label": "buy", "analyst_count": 0,
                    }},
                    "finnhub": {"recommendation": {
                        "label": "strong_buy", "total": 53, "period": "2026-09-01",
                    }},
                },
            },
        },
        "analyst_data": {
            "captured_at": "2026-09-12T05:36:58Z",
            "revenue_estimates": {
                "0y": {"avg": 500e9, "growth": .148, "numberOfAnalysts": 40},
                "+1y": {"avg": 551e9, "growth": .102, "numberOfAnalysts": 39},
            },
            "earnings_estimates": {
                "0y": {"avg": 8.82, "growth": .10, "numberOfAnalysts": 40},
                "+1y": {"avg": 9.57, "growth": .085, "numberOfAnalysts": 39},
            },
        },
    }


def test_builds_a_separate_street_case_without_manufacturing_intrinsic_value():
    result = build_external_expectations(data())
    assert result["price_target"]["return_vs_market"] == pytest.approx(324.4 / 332.27 - 1)
    assert result["recommendations"]["direction"] == "bullish"
    # Yahoo exposes an aggregate recommendation label but not the population
    # behind it; only Finnhub is count-qualified, so cross-source agreement is
    # unknown rather than manufactured.
    assert result["recommendations"]["directional_agreement"] is None
    assert result["recommendations"]["source_evidence"]["yahoo_finance"]["qualified"] is False
    assert result["forward_estimates"][1]["revenue"] == 551e9
    assert result["forward_estimates"][1]["implied_net_margin"] == pytest.approx(
        9.57 * 14.9e9 / 551e9)
    assert result["valuation_cross_check"]["forward_pe_at_market"] == pytest.approx(
        332.27 / 9.57)
    assert result["valuation_cross_check"]["forward_pe_at_mean_target"] == pytest.approx(
        324.4 / 9.57)
    assert result["valuation_cross_check"]["target_implied_market_cap"] == pytest.approx(
        324.4 * 14.9e9)
    assert result["valuation_cross_check"][
        "target_implied_ev_to_forward_revenue"
    ] == pytest.approx(324.4 * 14.9e9 / 551e9)
    assert result["coverage"] == "high"
    assert result["role"] == "external_benchmark_only"
    assert result["included_in_intrinsic_value"] is False
    observations = result["analyst_observations"]
    assert observations["observation_count"] == 2
    assert observations["source"] == "benzinga"
    assert observations["observations"][0]["firm"] == "Firm One"
    assert observations["included_in_intrinsic_value"] is False
    assert observations["content_policy"] == "structured_metadata_only_no_licensed_prose"
    targets = result["price_target"]["source_evidence"]
    assert targets["benzinga"]["qualified"] is True
    assert targets["yahoo_finance"]["qualified"] is True
    assert targets["benzinga"]["return_vs_market"] == pytest.approx(
        334.94 / 332.27 - 1
    )
    assert any("source date unavailable" in warning for warning in result["warnings"])


def test_stale_or_wrong_source_analyst_observations_are_excluded():
    payload = data()
    payload["company_data"]["analyst_consensus"]["analyst_observations"] = {
        "source": "benzinga",
        "observations": [
            {
                "date": "2025-01-01", "firm": "Old Firm",
                "rating": "buy", "source": "benzinga",
            },
            {
                "date": "2026-09-11", "firm": "Unknown Source",
                "rating": "buy", "source": "unlicensed_web",
            },
        ],
    }

    result = build_external_expectations(payload)

    assert result["analyst_observations"]["observation_count"] == 0
    assert result["analyst_observations"]["excluded_observation_count"] == 2
    assert any("Structured analyst observations" in warning for warning in result["warnings"])


def test_sparse_inputs_remain_explicitly_limited_and_never_default_to_neutral():
    result = build_external_expectations({})
    assert result["coverage"] == "limited"
    assert result["price_target"]["mean"] is None
    assert result["recommendations"]["direction"] is None
    assert len(result["warnings"]) == 2


def test_one_analyst_rating_is_visible_but_not_treated_as_consensus():
    payload = data()
    payload["company_data"]["analyst_consensus"]["source_snapshots"] = {
        "benzinga": {"recommendation": {
            "label": "sell", "unique_analyst_count": 1,
        }}
    }

    result = build_external_expectations(payload)

    evidence = result["recommendations"]["source_evidence"]["benzinga"]
    assert evidence["qualified"] is False
    assert result["recommendations"]["directional_agreement"] is None
    assert "Recommendation coverage is below five analysts." in result["warnings"]


def test_legacy_yahoo_target_count_cannot_be_reused_as_rating_coverage():
    payload = data()
    payload["company_data"]["analyst_consensus"]["source_snapshots"] = {
        "yahoo_finance": {
            "price_target": {
                "mean": 324.4, "analyst_count": 39, "currency": "USD",
            },
            "recommendation": {"label": "buy", "total": 39},
        },
    }

    result = build_external_expectations(payload)

    yahoo = result["recommendations"]["source_evidence"]["yahoo_finance"]
    assert yahoo["analyst_count"] == 0
    assert yahoo["qualified"] is False


def test_legacy_yahoo_without_source_snapshots_cannot_invent_rating_coverage():
    payload = data()
    consensus = payload["company_data"]["analyst_consensus"]
    consensus.pop("source_snapshots")
    consensus["recommendation"] = {
        "label": "buy",
        "source": "yahoo_finance",
        # This is the historical malformed shape found in saved production
        # artifacts. It came from target coverage, not a rating distribution.
        "analyst_count": 39,
    }

    result = build_external_expectations(payload)

    yahoo = result["recommendations"]["source_evidence"]["yahoo_finance"]
    assert yahoo["analyst_count"] == 0
    assert yahoo["qualified"] is False
    assert result["recommendations"]["active_qualified"] is False
    assert "Recommendation coverage is below five analysts." in result["warnings"]


def test_negative_street_eps_is_preserved_without_publishing_a_meaningless_pe():
    payload = data()
    payload["company_data"]["market_data"].update({
        "shares_outstanding_diluted": float("nan"),
        "shares_outstanding_basic": 2_000_000_000,
    })
    payload["analyst_data"]["earnings_estimates"]["+1y"].update({
        "avg": -0.75, "low": -1.1, "high": -0.3,
    })

    result = build_external_expectations(payload)

    forward = result["forward_estimates"][1]
    assert forward["eps"] == -0.75
    assert forward["implied_net_income"] == -1_500_000_000
    assert forward["implied_net_margin"] == pytest.approx(-1.5e9 / 551e9)
    assert result["valuation_cross_check"]["forward_pe_at_market"] is None
    assert result["valuation_cross_check"]["forward_pe_at_mean_target"] is None


def test_street_eps_bridge_uses_the_all_class_implied_share_count():
    payload = data()
    payload["company_data"]["market_data"].update({
        "shares_outstanding_implied": 12_200_000_000,
        "shares_outstanding_diluted": None,
        "shares_outstanding_basic": 5_900_000_000,
    })

    result = build_external_expectations(payload)

    assert result["forward_estimates"][1]["implied_net_income"] == pytest.approx(
        9.57 * 12_200_000_000
    )


def test_cross_currency_adr_eps_is_converted_before_profitability_bridge():
    payload = data()
    payload["company_data"]["basic_info"] = {
        "currency": "TWD",
        "listing_currency": "USD",
    }
    payload["company_data"]["market_data"] = {
        "current_price": 13_702.0,
        "current_price_listing": 433.24,
        "fx_listing_to_financial": 31.627,
        "shares_outstanding_implied": 5_186_000_000,
    }
    payload["company_data"]["valuation_metrics"] = {
        "pe_ratio_forward": 19.76,
    }
    payload["company_data"]["analyst_consensus"] = {}
    payload["analyst_data"]["revenue_estimates"] = {
        "0y": {"avg": 5_434e12, "numberOfAnalysts": 30},
        "+1y": {"avg": 7_296e12, "numberOfAnalysts": 29},
    }
    payload["analyst_data"]["earnings_estimates"] = {
        "0y": {"avg": 16.933, "low": 15.0, "high": 18.0,
               "numberOfAnalysts": 30},
        "+1y": {"avg": 21.925, "low": 18.0, "high": 24.0,
                "numberOfAnalysts": 29},
    }

    result = build_external_expectations(payload)
    forward = result["forward_estimates"][1]

    assert forward["eps_source_value"] == pytest.approx(21.925)
    assert forward["eps_source_currency"] == "USD"
    assert forward["eps"] == pytest.approx(21.925 * 31.627)
    assert forward["eps_currency"] == "TWD"
    assert forward["eps_currency_conversion_rate"] == pytest.approx(31.627)
    assert forward["eps_unit_basis"] == "provider_forward_pe_dimensional_match"
    assert forward["eps_unit_confidence"] == "high"
    assert forward["implied_net_margin"] == pytest.approx(
        21.925 * 31.627 * 5_186_000_000 / 7_296e12
    )
    assert result["valuation_cross_check"]["forward_pe_at_market"] == pytest.approx(
        13_702.0 / (21.925 * 31.627)
    )


def test_cross_currency_eps_fails_closed_without_a_valid_fx_rate():
    payload = data()
    payload["company_data"]["basic_info"] = {
        "currency": "TWD",
        "listing_currency": "USD",
    }
    payload["company_data"]["market_data"].update({
        "current_price": 13_702.0,
        "fx_listing_to_financial": None,
    })

    result = build_external_expectations(payload)

    assert all(row["eps"] is None for row in result["forward_estimates"])
    assert all(row["implied_net_margin"] is None
               for row in result["forward_estimates"])
    assert result["valuation_cross_check"]["forward_pe_at_market"] is None
    assert any("currency/unit could not be resolved" in warning
               for warning in result["warnings"])


def test_cross_currency_adr_eps_can_already_be_in_reporting_currency():
    payload = data()
    payload["company_data"]["basic_info"] = {
        "currency": "CNY",
        "listing_currency": "USD",
    }
    payload["company_data"]["market_data"] = {
        "current_price": 732.03,
        "current_price_listing": 109.30,
        "fx_listing_to_financial": 6.6974,
        "shares_outstanding_implied": 2_485_623_615,
    }
    payload["company_data"]["valuation_metrics"] = {
        "pe_ratio_forward": 11.7633,
    }
    payload["company_data"]["analyst_consensus"] = {}
    payload["analyst_data"]["revenue_estimates"] = {
        "0y": {"avg": 1.12149e12, "numberOfAnalysts": 43},
        "+1y": {"avg": 1.26369e12, "numberOfAnalysts": 43},
    }
    payload["analyst_data"]["earnings_estimates"] = {
        "0y": {"avg": 44.36884, "numberOfAnalysts": 30},
        "+1y": {"avg": 62.31802, "numberOfAnalysts": 30},
    }

    result = build_external_expectations(payload)
    forward = result["forward_estimates"][1]

    assert forward["eps_source_currency"] == "CNY"
    assert forward["eps"] == pytest.approx(62.31802)
    assert forward["eps_currency_conversion_rate"] == pytest.approx(1.0)
    assert forward["implied_net_margin"] == pytest.approx(
        62.31802 * 2_485_623_615 / 1.26369e12
    )
    assert result["valuation_cross_check"]["forward_pe_at_market"] == pytest.approx(
        732.03 / 62.31802
    )


def test_ambiguous_cross_currency_eps_unit_is_excluded_instead_of_guessed():
    payload = data()
    payload["company_data"]["basic_info"] = {
        "currency": "CAD",
        "listing_currency": "USD",
    }
    payload["company_data"]["market_data"] = {
        "current_price": 108.0,
        "current_price_listing": 100.0,
        "fx_listing_to_financial": 1.08,
        "shares_outstanding_implied": 1_000_000,
    }
    payload["company_data"]["valuation_metrics"] = {
        "pe_ratio_forward": 10.4,
    }
    payload["company_data"]["analyst_consensus"] = {}
    payload["analyst_data"]["earnings_estimates"]["+1y"]["avg"] = 10.0

    result = build_external_expectations(payload)

    assert result["forward_estimates"][1]["eps"] is None
    assert result["forward_estimates"][1]["eps_unit_basis"] == (
        "ambiguous_forward_pe_unit_evidence"
    )
    assert any("currency/unit could not be resolved" in warning
               for warning in result["warnings"])


def test_model_profitability_is_benchmarked_against_well_covered_street_case():
    expectations = build_external_expectations(data())
    result = reconcile_model_profitability(
        expectations,
        {
            "revenue": [500e9, 551e9],
            "nopat": [140e9, 145e9],
        },
    )

    assert result["rows"][0]["model_after_tax_operating_margin"] == pytest.approx(.28)
    assert result["rows"][0]["street_implied_net_margin"] == pytest.approx(
        8.82 * 14.9e9 / 500e9
    )
    assert result["rows"][0]["qualified"] is True
    assert result["conflicts"] == []


def test_large_earnings_disagreement_is_a_material_reconciliation_conflict():
    expectations = build_external_expectations(data())
    result = reconcile_model_profitability(
        expectations,
        {
            "revenue": [500e9, 551e9],
            "nopat": [220e9, 240e9],
        },
    )

    assert [row["horizon"] for row in result["conflicts"]] == ["FY1", "FY2"]
    assert "not an accounting equivalence" in result["comparison_basis"]


def test_isolated_eps_margin_anomaly_is_visible_but_not_a_hard_conflict():
    expectations = build_external_expectations(data())
    # FY1 is far above the EPS-implied margin, while FY2 reconciles. A single
    # horizon can reflect one-time GAAP/adjusted EPS and is not evidence of a
    # persistent operating-model disagreement by itself.
    result = reconcile_model_profitability(
        expectations,
        {
            "revenue": [500e9, 551e9],
            "nopat": [220e9, 145e9],
        },
    )

    assert result["conflicts"] == []
    assert [row["horizon"] for row in result["diagnostic_conflicts"]] == ["FY1"]
    assert [row["horizon"] for row in result["isolated_horizon_anomalies"]] == ["FY1"]
    assert result["rows"][0]["diagnostic_conflict"] is True
    assert result["rows"][0]["material_conflict"] is False


def test_stale_provider_target_is_excluded_from_both_benchmark_roles():
    payload = data()
    payload["company_data"]["analyst_consensus"]["source_snapshots"] = {
        "finnhub": {
            "captured_at": "2026-09-12T05:37:00Z",
            "price_target": {
                "mean": 400.0,
                "analyst_count": 25,
                "currency": "USD",
                "as_of": "2025-01-01",
            },
        },
    }

    result = build_external_expectations(payload)
    evidence = result["price_target"]["source_evidence"]["finnhub"]

    assert evidence["temporal_quality"]["status"] == "stale"
    assert evidence["qualified_for_contradiction"] is False
    assert evidence["qualified_for_corroboration"] is False
    assert any("excluded: finnhub" in warning for warning in result["warnings"])


def test_aggregate_calculation_time_does_not_become_target_freshness():
    payload = data()
    consensus = payload["company_data"]["analyst_consensus"]
    consensus["price_target"].update({
        "source": "benzinga", "mean": 350.0, "analyst_count": 25,
        "as_of": None, "aggregate_calculated_at": "2026-09-12T05:36:59Z",
    })
    consensus["source_snapshots"] = {
        "benzinga": {
            "captured_at": "2026-09-12T05:37:00Z",
            "price_target": {
                "mean": 350.0,
                "analyst_count": 25,
                "currency": "USD",
                "as_of": None,
                "aggregate_calculated_at": "2026-09-12T05:36:59Z",
            },
        },
    }

    result = build_external_expectations(payload)
    evidence = result["price_target"]["source_evidence"]["benzinga"]

    assert evidence["temporal_quality"]["status"] == "unknown"
    assert evidence["qualified_for_contradiction"] is True
    assert evidence["qualified_for_corroboration"] is False


def test_listing_currency_prevents_provider_currency_from_self_validating():
    payload = data()
    consensus = payload["company_data"]["analyst_consensus"]
    consensus["price_target"].update({"currency": "EUR", "source": "benzinga"})
    consensus["source_snapshots"] = {
        "benzinga": {"price_target": {
            "mean": 334.94,
            "analyst_count": 24,
            "currency": "EUR",
            "as_of": "2026-09-12T05:00:00Z",
        }},
    }

    result = build_external_expectations(payload)
    evidence = result["price_target"]["source_evidence"]["benzinga"]

    assert result["currency"] == "USD"
    assert evidence["currency_comparable"] is False
    assert evidence["qualified_for_contradiction"] is False
    assert evidence["qualified_for_corroboration"] is False


def test_stale_rating_population_does_not_inflate_coverage():
    payload = data()
    payload["company_data"]["analyst_consensus"]["source_snapshots"] = {
        "finnhub": {"recommendation": {
            "label": "strong_buy",
            "total": 53,
            "period": "2025-01-01",
        }},
    }

    result = build_external_expectations(payload)

    assert result["recommendations"]["active_qualified"] is False
    assert result["coverage"] == "moderate"
    assert any("recommendation evidence excluded: finnhub" in warning
               for warning in result["warnings"])
    assert "No current recommendation evidence with adequate coverage is available." \
        in result["warnings"]


def test_external_target_is_translated_into_a_reverse_dcf_expectation():
    result = implied_terminal_fcf_for_enterprise_value(
        5_000.0,
        pv_explicit_fcf=1_000.0,
        pv_terminal_value=2_000.0,
        model_terminal_fcf=500.0,
    )

    assert result["available"] is True
    assert result["implied_terminal_fcf"] == pytest.approx(1_000.0)
    assert result["implied_fcf_vs_model"] == pytest.approx(1.0)
    assert result["role"] == "external_target_reverse_dcf_benchmark_only"


@pytest.mark.parametrize("terminal_pv,terminal_fcf", [(0, 500), (2000, 0), (None, 500)])
def test_external_target_reverse_dcf_fails_closed_without_valid_terminal_mapping(
    terminal_pv, terminal_fcf,
):
    result = implied_terminal_fcf_for_enterprise_value(
        5_000.0,
        pv_explicit_fcf=1_000.0,
        pv_terminal_value=terminal_pv,
        model_terminal_fcf=terminal_fcf,
    )

    assert result["available"] is False
    assert result["implied_terminal_fcf"] is None
