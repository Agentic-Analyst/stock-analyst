import pytest

from src.external_expectations import build_external_expectations
from src.report_agent import (
    _withheld_valuation_commentary,
    build_analyst_consensus_table,
    build_street_reconciliation_table,
)


def expectations():
    financials = {
        "company_data": {
            "basic_info": {"currency": "USD"},
            "market_data": {"current_price": 332.27, "shares_outstanding_basic": 14.9e9},
            "analyst_consensus": {
                "captured_at": "2026-09-12T05:37:00Z",
                "price_target": {"mean": 324.4, "analyst_count": 39,
                                 "currency": "USD", "source": "yahoo_finance"},
                "recommendation": {"label": "strong_buy", "source": "finnhub"},
                "source_snapshots": {
                    "finnhub": {"captured_at": "2026-09-12T05:37:00Z",
                                "recommendation": {"label": "strong_buy", "total": 53,
                                                   "period": "2026-09-01"}},
                    "yahoo_finance": {"captured_at": "2026-09-12T05:36:59Z",
                                      "price_target": {"mean": 324.4,
                                                       "analyst_count": 39,
                                                       "currency": "USD",
                                                       "as_of": None},
                                      "recommendation": {"label": "buy"}},
                },
            },
        },
        "analyst_data": {
            "revenue_estimates": {
                "0y": {"avg": 500e9, "growth": .148, "numberOfAnalysts": 40},
                "+1y": {"avg": 551e9, "growth": .102, "numberOfAnalysts": 39},
            },
            "earnings_estimates": {
                "0y": {"avg": 8.82, "numberOfAnalysts": 40},
                "+1y": {"avg": 9.57, "numberOfAnalysts": 39},
            },
        },
    }
    return build_external_expectations(financials), financials


def test_reconciliation_distinguishes_dcf_comps_street_and_market():
    street, _ = expectations()
    valuation = {
        "dcf_perpetual": {
            "intrinsic_value_per_share": 153.91,
            "pv_fcfs": 1_000e9,
            "terminal_value": 2_000e9,
            "enterprise_value": 3_000e9,
        },
        "dcf_exit": {"intrinsic_value_per_share": 183.79},
        "summary": {"comps_intrinsic": 245.11},
        "reverse_dcf": {
            "model_terminal_fcf": 200e9,
            "market_enterprise_value": 4_900e9,
        },
    }
    text = build_street_reconciliation_table(
        street, {"revenue": [500e9, 551e9]}, valuation,
        {"confidence": "low", "role": "broad_sector_cross_check",
         "included_in_blended_value": False},
    )
    assert "Internal DCF midpoint | $168.85 | -49.2%" in text
    assert "Peer-multiple cross-check | $245.11 | -26.2%" in text
    assert "low confidence; excluded from blend" in text
    assert "Street mean target | $324.40 | -2.4%" in text
    assert "Finnhub" not in text  # normalized source ids are intentionally exact/lowercase
    assert "finnhub: Strong Buy (53 rating observations; current)" in text
    assert "Street-Implied Net Margin" in text
    assert "not averaged into intrinsic value" in text
    assert "Economics implied by the external target" in text
    assert "33.9x forward P/E" in text
    assert "8.8x EV/+1y Street revenue" in text
    assert "Analyst-target reverse DCF" in text
    assert "embedded cash-flow expectation" in text
    assert "Whole-path reverse DCF" in text
    assert "explicit and terminal free cash flow proportionally" in text
    assert "not blended into intrinsic value" in text
    assert "Model vs Street" in text
    assert "largest gap 0.0%" in text
    assert "not a near-term top-line disagreement" in text
    assert "independent directional earnings cross-check" in text
    assert "Model NOPAT Margin" in text


def test_reconciliation_solves_market_and_analyst_assumption_benchmarks():
    street, _ = expectations()
    path = [100e9, 110e9, 120e9, 130e9, 140e9]
    valuation = {
        "dcf_perpetual": {
            "intrinsic_value_per_share": 150.0,
            "enterprise_value": 2_000e9,
        },
        "dcf_exit": {"intrinsic_value_per_share": 180.0},
        "dcf_inputs": {"fcf": path},
        "reverse_dcf": {"market_enterprise_value": 4_900e9},
        "summary": {},
    }

    text = build_street_reconciliation_table(
        street, {"revenue": [500e9, 551e9]}, valuation, {}, {},
        {"wacc": 0.09, "terminal_growth": 0.025},
    )

    assert "One-assumption reverse DCF" in text
    assert "current market WACC" in text
    assert "external mean target WACC" in text
    assert "model WACC 9.00%" in text
    assert "model terminal growth 2.50%" in text
    assert "diagnostic only" in text


def test_material_profitability_disagreement_is_prominent():
    street, _ = expectations()
    text = build_street_reconciliation_table(
        street,
        {"revenue": [500e9, 551e9], "nopat": [230e9, 250e9]},
        {
            "dcf_perpetual": {"intrinsic_value_per_share": 250.0},
            "dcf_exit": {"intrinsic_value_per_share": 260.0},
            "summary": {},
        },
        {},
    )

    assert "Profitability reconciliation warning" in text
    assert "blocks a point valuation" in text


def test_isolated_profitability_anomaly_is_not_mislabeled_as_persistent():
    street, _ = expectations()
    text = build_street_reconciliation_table(
        street,
        {"revenue": [500e9, 551e9], "nopat": [230e9, 145e9]},
        {
            "dcf_perpetual": {"intrinsic_value_per_share": 250.0},
            "dcf_exit": {"intrinsic_value_per_share": 260.0},
            "summary": {},
        },
        {},
    )

    assert "Profitability reconciliation anomaly" in text
    assert "does not independently block publication" in text
    assert "Profitability reconciliation warning" not in text


def test_material_forecast_disagreement_is_not_buried_in_a_side_by_side_table():
    street, _ = expectations()
    text = build_street_reconciliation_table(
        street,
        {"revenue": [400e9, 430e9]},
        {
            "dcf_perpetual": {"intrinsic_value_per_share": 250.0},
            "dcf_exit": {"intrinsic_value_per_share": 260.0},
            "summary": {},
        },
        {},
    )

    assert "Forecast reconciliation warning" in text
    assert "20.0%" in text
    assert "requires explicit justification before publication" in text


def test_reconciliation_does_not_call_a_street_anchored_forecast_independent():
    street, _ = expectations()
    text = build_street_reconciliation_table(
        street,
        {"revenue": [500e9, 551e9]},
        {
            "dcf_perpetual": {"intrinsic_value_per_share": 153.91},
            "dcf_exit": {"intrinsic_value_per_share": 183.79},
            "summary": {},
        },
        {},
        {"near_term_revenue_is_consensus_anchored": True},
    )

    assert "Forecast input provenance" in text
    assert "deliberately anchored" in text
    assert "not independent validation" in text


def test_provider_capture_time_is_not_mislabeled_as_provider_as_of():
    _, financials = expectations()
    table = build_analyst_consensus_table(
        financials["company_data"]["analyst_consensus"])
    yahoo = next(line for line in table.splitlines() if line.startswith("| Yahoo Finance"))
    assert "| N/A | 2026-09-12T05:36:59Z |" in yahoo
    assert "Provider As Of" in table and "Captured" in table
    assert "Target Coverage" in table and "Rating Coverage" in table
    assert "| 39 target observations | Buy | N/A | N/A |" in yahoo


def test_consensus_table_never_uses_rating_population_as_target_coverage():
    consensus = {
        "source_snapshots": {
            "finnhub": {
                "price_target": {"mean": 250.0, "currency": "USD"},
                "recommendation": {
                    "label": "buy", "total": 48, "period": "2026-09-01",
                },
            },
        },
    }

    row = next(line for line in build_analyst_consensus_table(consensus).splitlines()
               if line.startswith("| Finnhub"))

    assert "| $250.00 USD | N/A | N/A | Buy | 48 rating observations |" in row


def test_withheld_commentary_mentions_available_forward_expectations():
    street, _ = expectations()
    text = _withheld_valuation_commentary(
        {
            "reliability": {"withheld_reason": "evidence conflicts"},
            "summary": {},
            "reverse_dcf": {},
        },
        {"analyst_consensus": {}},
        {"external_expectations": street},
    )

    assert "model-versus-Street table documents near-term revenue and EPS" in text
    assert "used as a model anchor" in text


def test_undated_target_can_challenge_but_not_corroborate_exceptional_claim():
    street, _ = expectations()
    yahoo = street["price_target"]["source_evidence"]["yahoo_finance"]

    assert yahoo["temporal_quality"]["status"] == "unknown"
    assert yahoo["qualified_for_contradiction"] is True
    assert yahoo["qualified_for_corroboration"] is False
    assert street["price_target"]["qualified_for_corroboration"] is False
    assert any("No provider-dated current price target" in warning
               for warning in street["warnings"])
