"""
Tests for terminal-value reconciliation.

WHAT THIS MODULE IS FOR. The valuation produced two answers that disagreed by a
median 1.85x across 39 production runs, and they were averaged. They are not two
methods — they are one DCF with terminal value assumed twice, once by the
perpetuity formula and once as an exit multiple. Those assumptions imply each
other, so a disagreement means the model contradicts itself.

Inverting the exit multiple recovers the perpetual growth it assumes:

    M = r(1+g)/(WACC-g)   ->   g = (M*WACC - r)/(M + r)

and perpetual growth is checkable against the economy: nothing compounds faster
than nominal GDP forever. That converts "these numbers differ" into "this
assumption is impossible", which identifies WHICH leg is wrong.

Run:  python -m pytest tests/test_terminal_value_reconcile.py -q
"""

import importlib.util
import os

import pytest

_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "src", "agents", "fm", "terminal_value.py",
)
_spec = importlib.util.spec_from_file_location("terminal_value", _PATH)
tv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tv)


# The audited META run, 2026-08-15.
META = dict(
    fcf_terminal=102_316_598_342.327,
    ebitda_terminal=183_929_647_181.20248,
    wacc=0.11035433947772656,
    terminal_growth=0.025,
    exit_multiple=11.2192,
)


class TestTheAlgebra:
    def test_inversion_round_trips(self):
        # The two helpers are inverses; if they drift apart every verdict is junk.
        r, w, g = 0.55, 0.11, 0.025
        m = tv.defensible_multiple(r, w, g)
        assert tv.implied_growth_from_multiple(m, r, w) == pytest.approx(g, abs=1e-9)

    def test_meta_implied_growth(self):
        r = META["fcf_terminal"] / META["ebitda_terminal"]
        g = tv.implied_growth_from_multiple(META["exit_multiple"], r, META["wacc"])
        assert g == pytest.approx(0.0579, abs=0.0002)

    def test_richer_multiple_implies_faster_growth(self):
        r, w = 0.55, 0.11
        assert (tv.implied_growth_from_multiple(15, r, w)
                > tv.implied_growth_from_multiple(8, r, w))

    def test_growth_can_never_reach_wacc(self):
        # The perpetuity diverges at g = WACC, so no finite multiple may imply it.
        r, w = 0.55, 0.11
        for m in (50, 500, 5000):
            g = tv.implied_growth_from_multiple(m, r, w)
            assert g is None or g < w

    def test_multiple_explodes_as_growth_approaches_wacc(self):
        r, w = 0.55, 0.11
        assert tv.defensible_multiple(r, w, 0.109) > tv.defensible_multiple(r, w, 0.04) * 5

    def test_growth_at_or_above_wacc_has_no_multiple(self):
        assert tv.defensible_multiple(0.55, 0.10, 0.10) is None
        assert tv.defensible_multiple(0.55, 0.10, 0.12) is None


class TestVerdicts:
    def test_meta_exit_multiple_is_not_a_terminal_multiple(self):
        out = tv.reconcile(**META)
        assert out["ok"]
        assert out["verdict"] == "growth_not_sustainable"
        assert out["implied_growth"] > tv.MAX_SUSTAINABLE_GROWTH
        assert out["ceiling"] == pytest.approx(8.22, abs=0.02)

    def test_note_names_the_cause_not_just_the_symptom(self):
        note = tv.reconcile(**META)["note"]
        assert "perpetuity" in note.lower()
        assert "5.8%" in note                      # the impossible growth rate
        assert "8.2x" in note                      # the defensible ceiling
        assert "compression" in note.lower()       # the unstated assumption

    def test_consistent_assumptions_produce_no_note(self):
        # An exit multiple set to exactly what the perpetuity implies.
        r = META["fcf_terminal"] / META["ebitda_terminal"]
        m = tv.defensible_multiple(r, META["wacc"], META["terminal_growth"])
        out = tv.reconcile(**{**META, "exit_multiple": m})
        assert out["verdict"] == "consistent"
        assert out["note"] is None

    def test_small_divergence_is_tolerated(self):
        # Within tolerance the difference is noise, not a contradiction; warning
        # on it would train the reader to ignore the warning.
        r = META["fcf_terminal"] / META["ebitda_terminal"]
        m = tv.defensible_multiple(r, META["wacc"], META["terminal_growth"])
        out = tv.reconcile(**{**META, "exit_multiple": m * 1.15})
        assert out["verdict"] == "consistent"

    def test_too_rich_but_still_sustainable(self):
        # This verdict only has room when the assumed growth sits well below the
        # 4% ceiling. At META's own 2.5% the ceiling (8.22x) falls BELOW the
        # tolerance threshold (8.35x), so anything rich enough to flag is
        # already unsustainable and the stronger verdict fires instead — which
        # is the correct precedence, not a gap. Use 1.5% so the window exists.
        case = {**META, "terminal_growth": 0.015}
        r = case["fcf_terminal"] / case["ebitda_terminal"]
        m = tv.defensible_multiple(r, case["wacc"], case["terminal_growth"])
        out = tv.reconcile(**{**case, "exit_multiple": m * 1.3})
        assert out["verdict"] == "exit_multiple_too_rich"
        assert out["implied_growth"] <= tv.MAX_SUSTAINABLE_GROWTH

    def test_unsustainable_growth_outranks_merely_rich(self):
        # Precedence matters: a multiple that cannot be justified at ANY
        # sustainable growth rate is wrong on its own terms, whatever the
        # perpetuity happens to assume.
        r = META["fcf_terminal"] / META["ebitda_terminal"]
        m = tv.defensible_multiple(r, META["wacc"], META["terminal_growth"])
        out = tv.reconcile(**{**META, "exit_multiple": m * 1.4})
        assert out["verdict"] == "growth_not_sustainable"

    def test_too_cheap_is_detected_too(self):
        # A conservative exit multiple is also an inconsistency, not a second
        # opinion — the model should not be quietly under-valuing either.
        r = META["fcf_terminal"] / META["ebitda_terminal"]
        m = tv.defensible_multiple(r, META["wacc"], META["terminal_growth"])
        out = tv.reconcile(**{**META, "exit_multiple": m / 2})
        assert out["verdict"] == "exit_multiple_too_cheap"
        assert "cheaper" in out["note"].lower()


class TestSteadyStateCheck:
    """
    Terminal cash conversion is the deepest diagnostic in the audit. Every
    absurd valuation across the 39 production models had FCF/EBITDA far below
    a mature business, and every sane one sat at 55-82%:

        EOG    3.8%   -> perpetuity $3.97   vs $134.74 market
        META   1.3%   -> perpetuity $27.50  vs $604.96 market
        HOOD   9.6%   -> perpetuity -$7.23
        NVDA  72-79%  -> perpetuity $118-204 vs ~$207   (sane)

    A terminal year still carrying growth-phase capex while growing at 2.5%
    forever is internally contradictory, and it drives the perpetuity value
    structurally far too low.
    """

    def _case(self, fcf_over_ebitda):
        ebitda = 100e9
        return dict(fcf_terminal=ebitda * fcf_over_ebitda, ebitda_terminal=ebitda,
                    wacc=0.11, terminal_growth=0.025, exit_multiple=12.0)

    @pytest.mark.parametrize("conv,ticker", [(0.038, "EOG"), (0.013, "META"), (0.096, "HOOD")])
    def test_real_broken_projections_are_caught(self, conv, ticker):
        out = tv.reconcile(**self._case(conv))
        assert out["verdict"] == "terminal_year_not_steady_state", ticker

    @pytest.mark.parametrize("conv", [0.556, 0.72, 0.82])
    def test_healthy_conversion_is_not_flagged_as_broken(self, conv):
        out = tv.reconcile(**self._case(conv))
        assert out["verdict"] != "terminal_year_not_steady_state"

    def test_steady_state_failure_outranks_the_multiple_verdicts(self):
        # Everything else is derived from terminal cash flow, so if that is
        # broken the multiple comparison is arithmetic on garbage.
        out = tv.reconcile(**{**self._case(0.03), "exit_multiple": 40.0})
        assert out["verdict"] == "terminal_year_not_steady_state"

    def test_ceiling_advice_is_withdrawn_when_the_base_is_broken(self):
        # A ceiling derived from broken terminal cash flow would clamp the exit
        # leg to something equally absurd — EOG's computes to 0.56x — and the
        # legs would then agree on nonsense. Convergence is not correctness.
        out = tv.reconcile(**self._case(0.038))
        assert out["ceiling"] is None
        assert out["implied_multiple"] is None

    def test_note_names_capex_normalisation_as_the_cause(self):
        note = tv.reconcile(**self._case(0.038))["note"]
        assert "steady state" in note.lower()
        assert "capex" in note.lower()
        assert "do not present" in note.lower()

    def test_boundary_is_not_off_by_one(self):
        assert tv.reconcile(**self._case(tv.MIN_TERMINAL_CONVERSION - 0.001))["verdict"] \
            == "terminal_year_not_steady_state"
        assert tv.reconcile(**self._case(tv.MIN_TERMINAL_CONVERSION + 0.001))["verdict"] \
            != "terminal_year_not_steady_state"


class TestRefusesToGuess:
    @pytest.mark.parametrize("bad", [
        dict(fcf_terminal=-5e9),          # cash-burning terminal year
        dict(fcf_terminal=0),
        dict(ebitda_terminal=0),
        dict(ebitda_terminal=-1e9),
        dict(wacc=0.02),                  # WACC below terminal growth
        dict(wacc=0.025),                 # WACC equal to terminal growth
        dict(exit_multiple=0),
        dict(exit_multiple=-5),
        dict(fcf_terminal=None),
        dict(wacc=None),
        dict(exit_multiple="n/a"),
    ])
    def test_degenerate_inputs_return_not_ok_with_no_note(self, bad):
        out = tv.reconcile(**{**META, **bad})
        assert out["ok"] is False
        assert out["note"] is None, "a broken model must not produce advice"

    def test_result_is_always_readable(self):
        # Callers read .get('note') unconditionally; a missing key would crash
        # the tool on exactly the runs that are already going badly.
        out = tv.reconcile(fcf_terminal=None, ebitda_terminal=None, wacc=None,
                           terminal_growth=None, exit_multiple=None)
        assert set(("ok", "verdict", "note")).issubset(out.keys())


class TestCapMakesModelsConsistent:
    """
    The cap in assumption_grounding and the verdict here must agree.

    Grounding now clamps the exit multiple to
    defensible_multiple(r, wacc, MAX_SUSTAINABLE_GROWTH). A model capped that
    way lands exactly on the boundary, so the verdict must call it consistent —
    a strict `>` condemned the very models the cap had just fixed, which is how
    replaying 36 production models produced 24 false "growth_not_sustainable"
    verdicts after capping.
    """

    def test_a_capped_multiple_is_consistent(self):
        from src.agents.fm.terminal_value import (
            defensible_multiple, reconcile, MAX_SUSTAINABLE_GROWTH,
        )
        for r in (0.30, 0.45, 0.60, 0.75, 0.82):
            for wacc in (0.08, 0.095, 0.11, 0.13):
                ceiling = defensible_multiple(r, wacc, MAX_SUSTAINABLE_GROWTH)
                assert ceiling and ceiling > 0
                res = reconcile(
                    fcf_terminal=r * 100, ebitda_terminal=100,
                    wacc=wacc, terminal_growth=0.03, exit_multiple=ceiling,
                )
                assert res["ok"], (r, wacc)
                assert res["verdict"] != "growth_not_sustainable", (
                    f"capping at the ceiling must not be judged unsustainable "
                    f"(r={r}, wacc={wacc}, ceiling={ceiling}, "
                    f"implied_growth={res.get('implied_growth')})"
                )

    def test_just_above_the_ceiling_is_still_caught(self):
        # The tolerance must not become a loophole.
        from src.agents.fm.terminal_value import defensible_multiple, reconcile, MAX_SUSTAINABLE_GROWTH
        r, wacc = 0.60, 0.10
        ceiling = defensible_multiple(r, wacc, MAX_SUSTAINABLE_GROWTH)
        res = reconcile(
            fcf_terminal=r * 100, ebitda_terminal=100,
            wacc=wacc, terminal_growth=0.03, exit_multiple=ceiling * 1.25,
        )
        assert res["verdict"] == "growth_not_sustainable"

    def test_cash_conversion_extraction_rejects_nonsense(self):
        from src.agents.fm.assumption_grounding import _terminal_cash_conversion
        mk = lambda fcf, ebitda: {"financial_statements": {
            "cash_flow": {"2025-12-31": {"Free Cash Flow": fcf}},
            "income_statement": {"2025-12-31": {"EBITDA": ebitda}}}}
        assert _terminal_cash_conversion(mk(60, 100)) == 0.6
        assert _terminal_cash_conversion(mk(-10, 100)) is None   # negative FCF
        assert _terminal_cash_conversion(mk(60, -100)) is None   # negative EBITDA
        assert _terminal_cash_conversion(mk(300, 100)) is None   # r=3.0, mislabelled
        assert _terminal_cash_conversion(mk(1, 100)) is None     # r=0.01, mislabelled
        assert _terminal_cash_conversion({}) is None
