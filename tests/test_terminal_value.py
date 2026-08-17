"""
Tests for the implied exit multiple and the withholding of contradictory
fair values.

TWO THINGS ARE PINNED HERE.

1. THE IMPLIED EXIT MULTIPLE MUST BE DERIVED, NOT READ OFF A ROW.
   A first attempt at this diagnostic used the workbook's "EV/EBITDA —
   Perpetual" row as the multiple the perpetuity implies. It is not: that row
   divides TODAY's enterprise value by TERMINAL EBITDA, which is a forward
   multiple on present value. For the audited META run it reads 5.14x while the
   perpetuity actually implies 6.68x, so the diagnostic would have reported a
   2.2x assumption gap where the real gap is 1.7x — a confidently wrong number
   inside a warning about confidently wrong numbers.

       TV      = FCF_terminal * (1 + g) / (WACC - g)
       implied = TV / EBITDA_terminal

2. A CONTRADICTORY FAIR VALUE MUST NOT BE HANDED OVER AT ALL.
   Telling a model not to quote a number while still giving it that number is a
   weak control: it is the most quotable thing in the payload, and one
   summarisation step later the caveat is gone and "$109.81" is on screen. Past
   the unreliable threshold the point estimate is replaced by the range.

Run:  python -m pytest tests/test_terminal_value.py -q
"""

import os

import pytest


def implied_exit_multiple(fcf_terminal, ebitda_terminal, wacc, g):
    """Mirrors the derivation in model_generation_agent."""
    if not (fcf_terminal and ebitda_terminal) or wacc is None or g is None:
        return None
    if wacc <= g or ebitda_terminal <= 0:
        return None
    tv = fcf_terminal * (1 + g) / (wacc - g)
    implied = tv / ebitda_terminal
    return implied if implied > 0 else None


# The audited META run, 2026-08-15.
META = dict(
    fcf_terminal=102_316_598_342.327,
    ebitda_terminal=183_929_647_181.20248,
    wacc=0.11035433947772656,
    g=0.025,
)
META_ASSUMED_MULTIPLE = 11.2192
META_EV_TODAY = 946_209_984_094.4014


class TestImpliedExitMultiple:
    def test_matches_first_principles_on_the_real_meta_run(self):
        assert implied_exit_multiple(**META) == pytest.approx(6.68, abs=0.01)

    def test_is_not_the_workbook_forward_multiple(self):
        # The bug that was caught: these are different quantities, and using
        # the wrong one misstates the assumption gap.
        forward = META_EV_TODAY / META["ebitda_terminal"]
        assert forward == pytest.approx(5.14, abs=0.01)
        assert implied_exit_multiple(**META) != pytest.approx(forward, abs=0.5)

    def test_meta_assumption_gap_is_material_and_fires(self):
        implied = implied_exit_multiple(**META)
        gap = max(implied, META_ASSUMED_MULTIPLE) / min(implied, META_ASSUMED_MULTIPLE)
        assert gap == pytest.approx(1.68, abs=0.01)
        assert gap >= 1.4, "the diagnostic threshold must catch this"

    def test_lower_wacc_implies_a_higher_multiple(self):
        # Directional sanity: a cheaper cost of capital is worth a richer exit.
        low = implied_exit_multiple(**{**META, "wacc": 0.09})
        assert low > implied_exit_multiple(**META)

    def test_higher_growth_implies_a_higher_multiple(self):
        hi = implied_exit_multiple(**{**META, "g": 0.035})
        assert hi > implied_exit_multiple(**META)

    @pytest.mark.parametrize("bad", [
        dict(wacc=0.02, g=0.025),      # WACC below g -> negative denominator
        dict(wacc=0.025, g=0.025),     # equal -> divide by zero
        dict(ebitda_terminal=0),       # zero terminal EBITDA
        dict(ebitda_terminal=-1e9),    # negative terminal EBITDA
        dict(fcf_terminal=0),          # no terminal cash flow
        dict(fcf_terminal=None),
    ])
    def test_degenerate_inputs_return_none_rather_than_nonsense(self, bad):
        assert implied_exit_multiple(**{**META, **bad}) is None

    def test_negative_terminal_fcf_cannot_produce_a_positive_multiple(self):
        # A cash-burning company must not silently yield a plausible multiple.
        assert implied_exit_multiple(**{**META, "fcf_terminal": -5e9}) is None


def decide(band, legs):
    """Mirrors the withholding branch in BuildModelTool.execute."""
    positive = [v for v in legs.values() if isinstance(v, (int, float)) and v > 0]
    if band == "unreliable" and len(positive) >= 2:
        return dict(fair_value=None, withheld=True,
                    low=min(positive), high=max(positive))
    return dict(fair_value="kept", withheld=False, low=None, high=None)


class TestWithholding:
    def test_eog_point_estimate_is_withheld(self):
        # $3.97 vs $215.64 -> the blend $109.81 must not be quotable.
        out = decide("unreliable", {"perpetual_dcf": 3.97, "exit_multiple_dcf": 215.64})
        assert out["withheld"] and out["fair_value"] is None
        assert (out["low"], out["high"]) == (3.97, 215.64)

    def test_converged_model_keeps_its_fair_value(self):
        out = decide("moderate", {"perpetual_dcf": 380.64, "exit_multiple_dcf": 549.16})
        assert not out["withheld"] and out["fair_value"] == "kept"

    def test_wide_but_not_unreliable_still_reports_a_number(self):
        # "wide" gets a range note; withholding is reserved for contradiction,
        # otherwise the product stops answering the question it exists to answer.
        out = decide("wide", {"perpetual_dcf": 203.80, "exit_multiple_dcf": 411.81})
        assert not out["withheld"]

    def test_single_surviving_leg_is_not_withheld_as_a_range(self):
        # One positive leg cannot express a range; the single-method rail
        # already explains that case.
        out = decide("unreliable", {"perpetual_dcf": -7.23, "exit_multiple_dcf": 83.33})
        assert not out["withheld"]

    def test_range_excludes_broken_legs(self):
        out = decide("unreliable", {"a": -0.73, "b": 6.21, "c": 213.30})
        assert (out["low"], out["high"]) == (6.21, 213.30)
