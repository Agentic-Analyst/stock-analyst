import pytest

from src.summary_evidence import (
    compact_publication_reason,
    external_benchmark,
    render_external_benchmark,
    render_external_benchmark_compact,
    supported_valuation_span,
    supported_valuation_values,
)


def test_compact_publication_reason_keeps_decision_and_drops_evidence_appendix():
    reason = (
        "The DCF gap is not independently corroborated. External benchmarks: "
        "provider details. Terminal-only reverse DCF cross-check: diagnostics."
    )

    assert compact_publication_reason(reason) == (
        "The DCF gap is not independently corroborated."
    )


def test_supported_range_excludes_context_only_comps():
    metrics = {
        "perpetual_price": 153.91,
        "exit_multiple_price": 183.79,
        "comps_price": 245.11,
        "comps_included_in_blended_value": False,
    }
    assert supported_valuation_values(metrics) == [153.91, 183.79]


def test_equal_displayed_method_outputs_are_one_estimate_not_a_range():
    assert supported_valuation_span([13245.004, 13245.003]) == {
        "low": 13245.003, "high": 13245.004, "shape": "single_estimate",
    }
    assert supported_valuation_span([153.91, 183.79])["shape"] == "range"


def test_bank_range_uses_bank_methods_not_discarded_dcf():
    metrics = {
        "valuation_method": "justified_pb_roe",
        "perpetual_price": 12,
        "exit_multiple_price": 20,
        "bank_intrinsic_fair_value": 281.23,
        "bank_peer_fair_value": 296.63,
    }
    assert supported_valuation_values(metrics) == [281.23, 296.63]


def test_bank_range_falls_back_past_a_nonfinite_preferred_alias():
    metrics = {
        "valuation_method": "justified_pb_roe",
        "bank_intrinsic_fair_value": float("nan"),
        "intrinsic_fair_value": 281.23,
    }
    assert supported_valuation_values(metrics) == [281.23]


def test_external_benchmark_carries_target_rating_and_model_reconciliation():
    data = {
        "external_expectations": {
            "currency": "USD",
            "coverage": "high",
            "price_target": {
                "mean": 324.4, "return_vs_market": -0.0237,
                "analyst_count": 39, "source": "yahoo_finance",
                "provider_as_of": None,
                "qualified_for_contradiction": True,
                "qualified_for_corroboration": False,
                "temporal_quality": {"status": "unknown"},
            },
            "valuation_cross_check": {
                "forward_pe_at_mean_target": 33.9,
                "target_implied_ev_to_forward_revenue": 8.8,
            },
            "recommendations": {
                "active_label": "strong_buy", "active_source": "finnhub",
                    "source_evidence": {
                        "finnhub": {
                            "analyst_count": 53,
                            "period": "2026-09-11",
                            "qualified": True,
                            "temporal_quality": {"status": "current"},
                        },
                },
            },
            "analyst_observations": {
                "source": "benzinga", "observation_count": 2,
                "as_of": "2026-09-11",
                "oldest_observation_as_of": "2026-09-10",
                "observations": [
                    {
                        "date": "2026-09-11", "firm": "Firm One",
                        "action": "Maintains", "rating": "buy",
                        "price_target": 350.0,
                        "source": "benzinga",
                        "content_role": "structured_external_analyst_observation",
                        "temporal_quality": {"status": "current"},
                    },
                    {
                        "date": "2026-09-10", "firm": "Firm Two",
                        "action": "Raises", "rating": "strong_buy",
                        "price_target": 375.0,
                        "source": "benzinga",
                        "content_role": "structured_external_analyst_observation",
                        "temporal_quality": {"status": "current"},
                    },
                ],
            },
            "forward_estimates": [{
                "revenue": 500e9, "eps": 8.82,
                "revenue_analyst_count": 40, "eps_analyst_count": 40,
            }],
        },
    }

    evidence = external_benchmark(data, [510e9])

    assert evidence["target_mean"] == 324.4
    assert evidence["rating_analyst_count"] == 53
    assert evidence["analyst_observation_count"] == 2
    assert evidence["analyst_observation_firms"] == ["Firm One", "Firm Two"]
    assert evidence["analyst_observation_metadata"][0]["action"] == "Maintains"
    assert "insight" not in evidence["analyst_observation_metadata"][0]
    assert evidence["forward"][0]["model_vs_street"] == pytest.approx(0.02)
    rendered = render_external_benchmark(evidence)
    assert "39 target observations" in rendered
    assert "53 rating observations" in rendered
    compact = render_external_benchmark_compact(evidence)
    assert "External analyst view: STRONG BUY from finnhub" in compact
    assert "not Vynn's rating" in compact
    assert "2 current structured observation(s)" in rendered
    assert "Firm One / 2026-09-11 / action Maintains" in rendered
    assert "Licensed rationale prose was not read or collected" in rendered
    assert "Services growth offsets hardware pressure" not in rendered
    assert "model +2.0% vs Street" in rendered
    assert "provider date unavailable; caution-only" in rendered
    assert "33.9x forward P/E" in rendered
    assert "8.8x EV/forward Street revenue" in rendered
    assert "None is intrinsic value" in rendered


def test_external_benchmark_rejects_unmarked_or_wrong_source_observations():
    data = {"external_expectations": {
        "analyst_observations": {
            "source": "benzinga",
            "observation_count": 3,
            "observations": [
                {
                    "firm": "Missing Role", "rating": "buy", "source": "benzinga",
                },
                {
                    "firm": "Wrong Source", "rating": "buy",
                    "source": "unlicensed_web",
                    "content_role": "structured_external_analyst_observation",
                },
                {
                    "firm": "Empty", "source": "benzinga",
                    "content_role": "structured_external_analyst_observation",
                },
            ],
        },
    }}

    evidence = external_benchmark(data)

    assert evidence["analyst_observation_count"] == 0
    assert evidence["analyst_observation_metadata"] == []


def test_external_benchmark_does_not_underreport_valid_observations_below_prompt_cap():
    observations = [{
        "date": f"2026-09-{day:02d}",
        "firm": f"Firm {day}",
        "rating": "buy",
        "price_target": 300.0 + day,
        "source": "benzinga",
        "content_role": "structured_external_analyst_observation",
        "temporal_quality": {"status": "current"},
    } for day in range(1, 8)]
    data = {"external_expectations": {"analyst_observations": {
        "source": "benzinga",
        "observation_count": len(observations),
        "observations": observations,
    }}}

    evidence = external_benchmark(data)

    assert evidence["analyst_observation_count"] == 7
    assert len(evidence["analyst_observation_metadata"]) == 7


def test_external_benchmark_discloses_when_street_revenue_is_a_model_input():
    data = {
        "external_expectations": {
            "currency": "USD",
            "forward_estimates": [{
                "revenue": 500e9,
                "revenue_analyst_count": 40,
            }],
        },
    }

    evidence = external_benchmark(
        data,
        [500.02e9],
        revenue_growth_source="yahoo_analyst_consensus_with_deterministic_fade",
    )
    rendered = render_external_benchmark(evidence)

    assert evidence["forward"][0]["model_uses_street_anchor"] is True
    assert "used as a model revenue anchor" in rendered
    assert "model input" in rendered
    assert "independent validation" not in rendered


def test_external_benchmark_explains_reverse_dcf_delta_as_a_percentage_not_ratio():
    evidence = external_benchmark(
        {"external_expectations": {"currency": "USD"}},
        valuation_metrics={
            "market_implied_terminal_fcf": 123.4e9,
            "market_implied_fcf_vs_model": 0.573,
        },
    )

    rendered = render_external_benchmark(evidence)

    assert evidence["market_implied_fcf_delta"] == pytest.approx(0.573)
    assert "requires terminal FCF 57.3% above the model" in rendered
    assert "USD 123.4B" in rendered
    assert "0.6x" not in rendered
    assert "diagnostic only; not a valuation vote" in rendered


def test_external_benchmark_makes_the_analyst_target_an_economic_dcf_cross_check():
    evidence = external_benchmark(
        {"external_expectations": {
            "currency": "USD",
            "price_target": {
                "mean": 335.72, "analyst_count": 26, "source": "benzinga",
                "provider_as_of": "2026-09-12",
                "qualified_for_corroboration": True,
            },
        }},
        valuation_metrics={
            "analyst_target_implied_terminal_fcf": 625e9,
            "analyst_target_implied_fcf_vs_model": 2.12,
        },
    )

    rendered = render_external_benchmark(evidence)

    assert "analyst-target reverse DCF" in rendered
    assert "212.0% above the model" in rendered
    assert "USD 625.0B" in rendered
    assert "excluded from intrinsic value" in rendered


def test_external_benchmark_calls_out_material_conflict_and_distribution():
    evidence = external_benchmark(
        {"external_expectations": {
            "currency": "USD",
            "price_target": {
                "mean": 335.72, "median": 350.0, "low": 245.0, "high": 400.0,
                "return_vs_market": 0.01,
                "analyst_count": 26, "source": "benzinga",
                "provider_as_of": "2026-09-10",
                "qualified_for_contradiction": True,
                "qualified_for_corroboration": True,
                "source_evidence": {
                    "benzinga": {
                        "mean": 335.72, "analyst_count": 26,
                        "provider_as_of": "2026-09-10",
                        "currency_comparable": True,
                        "temporal_quality": {"status": "current"},
                    },
                    "yahoo_finance": {
                        "mean": 324.40, "analyst_count": 39,
                        "provider_as_of": None,
                        "currency_comparable": True,
                        "temporal_quality": {"status": "unknown"},
                    },
                },
            },
            "forward_estimates": [{
                "revenue": 477.8e9, "revenue_analyst_count": 39,
            }],
        }},
        [477.8e9],
        revenue_growth_source="yahoo_analyst_consensus_with_deterministic_fade",
        valuation_metrics={
            "fair_value": 170.0,
            "current_price": 332.27,
            "upside_vs_market": -0.488,
            "perpetual_price": 157.8,
            "exit_multiple_price": 182.4,
            "market_implied_fcf_path_vs_model": 1.1245,
            "analyst_target_implied_fcf_path_vs_model": 1.1737,
            "wacc": 0.0938,
            "terminal_growth": 0.025,
            "market_implied_wacc": 0.0577,
            "analyst_target_implied_wacc": 0.0569,
            "market_implied_terminal_growth": 0.0707,
            "analyst_target_implied_terminal_growth": 0.0714,
        },
    )

    assert evidence["benchmark_relationship"] == "material_conflict"
    assert evidence["target_range_relationship"] == (
        "analyst_range_entirely_above_model_range"
    )
    rendered = render_external_benchmark(evidence)
    assert "low USD 245.00, median USD 350.00, high USD 400.00" in rendered
    assert "unresolved calibration conflict, not a minor caveat" in rendered
    assert "even the analyst low is above" in rendered
    assert "provider cross-checks kept separate" in rendered
    assert "near-term revenue is already anchored" in rendered
    assert "whole-path reverse DCF" in rendered
    assert "market-implied WACC 5.77%" in rendered
    assert "model WACC 9.38%" in rendered


def test_extreme_reverse_dcf_gap_is_labeled_as_model_scope_not_company_value():
    evidence = {
        "currency": "USD",
        "market_implied_fcf_path_delta": 42.07,
    }

    full = render_external_benchmark(evidence)
    compact = render_external_benchmark_compact(evidence)

    for rendered in (full, compact):
        assert "43.07" in rendered
        assert "modeled operating cash-flow path" in rendered
        assert "not a comprehensive company value" in rendered
        assert "does not validate the market price" in rendered
