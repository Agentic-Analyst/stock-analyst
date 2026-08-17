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

import pytest

# Import the rail without pulling in the agent's heavy dependency graph.
_SRC = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "src", "agents", "tools", "analysis_tools.py",
)
_text = open(_SRC).read()
_start = _text.index("def valuation_dispersion(")
_end = _text.index("\nclass ", _start)
_ns: dict = {}
exec(compile(_text[_start:_end], _SRC, "exec"), _ns)
valuation_dispersion = _ns["valuation_dispersion"]


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
