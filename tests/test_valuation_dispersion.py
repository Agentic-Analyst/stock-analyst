"""
Tests for the valuation dispersion rail.

WHY THIS EXISTS. Every prior sanity rail inspected only the FINAL blended fair
value, so a number averaged from methods that wildly contradict each other
passed cleanly as long as the average landed somewhere plausible. Replaying 39
real production models showed how bad that was:

    EOG    perpetual $3.97   vs exit $215.64   -> blend $109.81  "-18.5%"
    META   perpetual $27.50  vs exit $906.98   -> blend $467.24  "-22.8%"
    BTSG   perpetual $30.93  vs exit $93.67    -> blend $62.30   "+4.3%"
    HOOD   perpetual -$7.23  (failed)          -> blend $38.05   "-59.9%"

None tripped a rail: the blend was positive, the company was not a mega-cap,
and the implied upside was mild. The median spread across all 39 models was
1.85x and 31 exceeded 1.5x. The rail added here flags 29 of the 39.

The cases below are taken from that real data, so a regression is measured
against what the pipeline actually produced, not invented inputs.

Run:  python -m pytest tests/test_valuation_dispersion.py -q
"""

import os
import re
import sys
import math

import pytest

# Import the rail without pulling in the agent's heavy dependency graph.
_SRC = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "src", "agents", "tools", "analysis_tools.py",
)
_text = open(_SRC).read()
_start = _text.index("def valuation_dispersion(")
_end = _text.index("\nclass ", _start)
_ns: dict = {"math": math}
exec(compile(_text[_start:_end], _SRC, "exec"), _ns)
valuation_dispersion = _ns["valuation_dispersion"]
valuation_publication_boundary = _ns["valuation_publication_boundary"]


def band(**legs):
    return valuation_dispersion(legs)[1]


def note(**legs):
    return valuation_dispersion(legs)[2]


class TestRealProductionCases:
    """Every case is a model this pipeline actually shipped to a user."""

    def test_eog_54x_spread_is_unreliable(self):
        # The worst observed: two methods 54x apart averaged into a confident
        # "$109.81, -18.5% downside".
        assert band(perpetual=3.97, exit_multiple=215.64) == "unreliable"

    def test_meta_33x_spread_is_unreliable(self):
        assert band(perpetual=27.50, exit_multiple=906.98) == "unreliable"

    def test_btsg_3x_spread_is_unreliable(self):
        # Looked entirely benign: +4.3% upside. Built from a 3x contradiction.
        assert band(perpetual=30.93, exit_multiple=93.67) == "unreliable"

    def test_nvda_2x_spread_is_wide(self):
        assert band(perpetual=203.80, exit_multiple=411.81) == "wide"

    def test_meta_converged_run_is_moderate(self):
        # The one META run where all three methods roughly agreed.
        assert band(perpetual=380.64, exit_multiple=549.16, comps=656.57) == "moderate"

    def test_hood_failed_leg_is_single_method(self):
        # A negative share price is a FAILED method, not a low estimate. The
        # blend silently dropped it and shipped a one-method number as consensus.
        assert band(perpetual=-7.23, exit_multiple=83.33) == "single-method"


class TestBandBoundaries:
    def test_tight_agreement_passes_silently(self):
        r, b, n = valuation_dispersion({"a": 100.0, "b": 115.0})
        assert b == "tight" and n is None, "a converged model must not be warned about"

    @pytest.mark.parametrize(
        "hi,expected",
        [(129.0, "tight"), (131.0, "moderate"), (179.0, "moderate"),
         (181.0, "wide"), (249.0, "wide"), (251.0, "unreliable")],
    )
    def test_thresholds(self, hi, expected):
        assert band(a=100.0, b=hi) == expected

    def test_ratio_is_max_over_min(self):
        r, _, _ = valuation_dispersion({"a": 50.0, "b": 200.0})
        assert r == pytest.approx(4.0)

    def test_tight_dcf_pair_without_comps_is_one_method_not_triangulation(self):
        ratio, result, warning = valuation_dispersion({
            "perpetual DCF": 151.66,
            "exit multiple DCF": 183.68,
            "market comps": 0.0,
        })
        assert ratio == pytest.approx(183.68 / 151.66)
        assert result == "single-method"
        assert "no independent market-comps" in warning.lower()


class TestGuardsAgainstFalseAlarms:
    def test_single_leg_is_not_a_spread(self):
        assert valuation_dispersion({"only": 100.0}) == (None, None, None)

    def test_empty_and_none_inputs(self):
        assert valuation_dispersion({}) == (None, None, None)
        assert valuation_dispersion(None) == (None, None, None)
        assert valuation_dispersion({"a": None, "b": None}) == (None, None, None)

    def test_non_numeric_legs_are_ignored(self):
        assert valuation_dispersion({"a": "n/a", "b": 100.0}) == (None, None, None)

    def test_nan_is_ignored(self):
        assert valuation_dispersion({"a": float("nan"), "b": 100.0}) == (None, None, None)

    def test_all_legs_broken_defers_to_the_existing_rail(self):
        # Both non-positive: the pre-existing non-positive rail owns this case,
        # and firing twice would bury the clearer message.
        assert valuation_dispersion({"a": -5.0, "b": -10.0}) == (None, None, None)

    def test_zero_is_treated_as_broken_not_as_a_low_value(self):
        # A $0 leg would otherwise make every ratio infinite.
        assert band(a=0.0, b=100.0) == "single-method"


class TestFailedMethodPublicationBoundary:
    def test_surviving_leg_is_audit_only_even_when_close_to_market(self):
        withheld, reason = valuation_publication_boundary(
            band="single-method",
            legs={"perpetual_dcf": -7.23, "exit_multiple_dcf": 83.33},
            fair_value=83.33,
            current_price=80.0,
        )
        assert withheld is True
        assert "non-positive value" in reason

    def test_failed_leg_does_not_hide_market_street_or_reverse_dcf_evidence(self):
        withheld, reason = valuation_publication_boundary(
            band="single-method",
            legs={"perpetual_dcf": 14.64, "exit_multiple_dcf": 0.0},
            fair_value=14.64,
            current_price=365.44,
            is_mega_cap=True,
            analyst_target=391.0,
            analyst_count=39,
            analyst_rating="buy",
            analyst_rating_count=45,
            reverse_dcf_gap=66.76,
        )

        assert withheld is True
        assert "exit_multiple_dcf" in reason
        assert "-96% from the market" in reason
        assert "39-analyst target benchmark is +7%" in reason
        assert "terminal free cash flow +6676% versus the model" in reason

    @pytest.mark.parametrize("value", [None, 0.0, -10.0, float("nan")])
    def test_invalid_intrinsic_output_fails_closed(self, value):
        withheld, reason = valuation_publication_boundary(
            band=None, legs={}, fair_value=value, current_price=100.0,
        )
        assert withheld is True
        assert "No finite positive" in reason

    def test_no_positive_leg_still_reports_independent_evidence(self):
        withheld, reason = valuation_publication_boundary(
            band=None,
            legs={"perpetual_dcf": -50.0, "exit_multiple_dcf": 0.0},
            fair_value=-25.0,
            current_price=60.0,
            analyst_target=80.0,
            analyst_count=12,
            analyst_rating="buy",
            analyst_rating_count=18,
            reverse_dcf_gap=55.0,
        )

        assert withheld is True
        assert "No finite positive" in reason
        assert "12-analyst target benchmark is +33%" in reason
        assert "BUY (18 ratings)" in reason
        assert "terminal free cash flow +5500% versus the model" in reason


class TestNoteContent:
    def test_unreliable_note_forbids_quoting_a_number(self):
        n = note(perpetual=3.97, exit_multiple=215.64)
        assert "do not quote a fair value" in n.lower()
        assert "54.3x" in n or "54.2x" in n, n

    def test_wide_note_asks_for_a_range(self):
        n = note(a=100.0, b=200.0)
        assert "range" in n.lower()

    def test_notes_name_the_actual_legs_and_values(self):
        # The agent must be able to show the football field, which means the
        # note has to carry the numbers, not just a verdict.
        n = note(perpetual=100.0, exit_multiple=250.0)
        assert "100.00" in n and "250.00" in n

    def test_single_method_note_explains_the_failure(self):
        n = note(perpetual=-7.23, exit_multiple=83.33)
        assert "not a low estimate" in n.lower()
        assert "perpetual" in n.lower()


class TestPublicationBoundary:
    AAPL_LEGS = {
        "perpetual_dcf": 151.66,
        "exit_multiple_dcf": 183.68,
        "market_comps": 0.0,
    }

    def test_dcf_only_megacap_gap_cannot_become_a_precise_sell(self):
        withheld, reason = valuation_publication_boundary(
            band="single-method",
            legs=self.AAPL_LEGS,
            fair_value=167.67,
            current_price=332.27,
            is_mega_cap=True,
            analyst_target=324.40,
            analyst_count=39,
        )
        assert withheld is True
        assert "no independent market-comps" in reason.lower()

    def test_large_non_megacap_dcf_gap_still_needs_numeric_corroboration(self):
        withheld, reason = valuation_publication_boundary(
            band="single-method",
            legs=self.AAPL_LEGS,
            fair_value=167.67,
            current_price=332.27,
            is_mega_cap=False,
        )
        assert withheld is True
        assert "analyst-target evidence does not corroborate both" in reason

    def test_independent_comps_do_not_override_conflicting_broad_consensus(self):
        withheld, reason = valuation_publication_boundary(
            band="moderate",
            legs={**self.AAPL_LEGS, "market_comps": 234.93},
            fair_value=201.10,
            current_price=332.27,
            is_mega_cap=True,
            analyst_target=324.40,
            analyst_count=39,
        )
        assert withheld is True
        assert "39-analyst target benchmark" in reason

    def test_wide_methods_publish_a_range_not_a_point_call(self):
        withheld, reason = valuation_publication_boundary(
            band="wide",
            legs={"perpetual_dcf": 145.0, "exit_multiple_dcf": 177.0,
                  "market_comps": 329.0},
            fair_value=245.0,
            current_price=266.0,
            is_mega_cap=True,
            analyst_target=278.0,
            analyst_count=22,
        )
        assert withheld is True
        assert "more than 1.8x" in reason

    def test_supportive_consensus_allows_an_exceptional_model_call(self):
        assert valuation_publication_boundary(
            band="moderate",
            legs={**self.AAPL_LEGS, "market_comps": 234.93},
            fair_value=201.10,
            current_price=332.27,
            is_mega_cap=True,
            analyst_target=220.0,
            analyst_count=20,
        ) == (False, None)

    def test_well_covered_rating_is_material_when_target_is_unavailable(self):
        withheld, reason = valuation_publication_boundary(
            band="single-method",
            legs={"perpetual_dcf": 50.0, "exit_multiple_dcf": 60.0},
            fair_value=55.0,
            current_price=100.0,
            is_mega_cap=False,
            analyst_rating="strong_buy",
            analyst_rating_count=24,
        )
        assert withheld is True
        assert "STRONG BUY" in reason
        assert "24 ratings" in reason

    def test_supportive_rating_alone_cannot_validate_a_precise_large_target(self):
        withheld, reason = valuation_publication_boundary(
            band="single-method",
            legs={"perpetual_dcf": 50.0, "exit_multiple_dcf": 60.0},
            fair_value=55.0,
            current_price=100.0,
            is_mega_cap=False,
            analyst_rating="sell",
            analyst_rating_count=24,
        )
        assert withheld is True
        assert "analyst-target evidence does not corroborate both" in reason

    def test_same_direction_but_trivial_target_gap_does_not_corroborate_model(self):
        withheld, reason = valuation_publication_boundary(
            band="single-method",
            legs={"perpetual_dcf": 72.58, "exit_multiple_dcf": 87.71},
            fair_value=80.15,
            current_price=53.72,
            is_mega_cap=False,
            analyst_target=57.07,
            analyst_count=32,
            analyst_rating="buy",
            analyst_rating_count=52,
        )
        assert withheld is True
        assert "+49%" in reason
        assert "32-analyst target benchmark is +6%" in reason

    def test_aligned_target_direction_and_magnitude_can_corroborate_large_dcf(self):
        assert valuation_publication_boundary(
            band="single-method",
            legs={"perpetual_dcf": 72.0, "exit_multiple_dcf": 88.0},
            fair_value=80.0,
            current_price=53.0,
            is_mega_cap=False,
            analyst_target=76.0,
            analyst_count=18,
            analyst_rating="buy",
            analyst_rating_count=20,
        ) == (False, None)

    def test_non_megacap_comps_conflict_is_not_mislabeled_megacap(self):
        withheld, reason = valuation_publication_boundary(
            band="moderate",
            legs={"perpetual_dcf": 45.0, "exit_multiple_dcf": 55.0,
                  "market_comps": 60.0},
            fair_value=55.0,
            current_price=100.0,
            is_mega_cap=False,
            analyst_rating_evidence={
                "finnhub": {"label": "buy", "analyst_count": 20},
            },
        )
        assert withheld is True
        assert "for the company" in reason
        assert "mega-cap" not in reason
