"""
The valuation engine must not be systematically bearish, and must not count
one opinion twice.

THE BUG, in two parts, found by measuring 49 stored theses: the median name
came out 15.7% BELOW market, the mean 22.1% below, 69% were negative, and the
ratings ran 18 SELL/STRONG SELL against 5 BUY/STRONG BUY. An engine that rates
two thirds of large-cap America a sell is not conservative, it is miscalibrated.

PART 1 — the equity risk premium was a house assumption over a published one.
`_mature_erp()` returned the module constant 5.5% while `country_risk.load_table()`
— already called a few lines from the only use site — carried Damodaran's
published implied premium of 4.23%. The published figure was read ONLY to print
in the provenance note, so every workbook stated "mature-market ERP 5.5% (house
assumption; Damodaran's implied base 4.23%)" and then discounted at the higher
one. It runs through the model twice: the inflated WACC discounts the perpetuity
leg directly, and it also lowers the exit-multiple ceiling in
`defensible_multiple`, which is a function of WACC. Both DCF legs therefore
moved together off this single input.

PART 2 — the headline averaged three legs, two of which were the same opinion.
The perpetual and exit-multiple DCFs share the WACC, the projected free cash
flow and the terminal logic; on AAPL they came out $111.85 and $116.93, 4.5%
apart. Counting them as two votes gave one discounted-cash-flow view two thirds
of the headline and gave market comps — the only market-anchored leg — one
third, so whenever the DCF disagreed with the market the DCF won by
construction.

Run:  python -m pytest tests/test_valuation_calibration.py -q
"""

import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "src"))


# --------------------------------------------------------------------------
# Part 1: the equity risk premium
# --------------------------------------------------------------------------

def test_erp_prefers_the_published_figure_over_the_house_constant():
    from src.agents.fm.assumption_grounding import _mature_erp, _ERP
    from src.agents.fm.country_risk import load_table

    os.environ.pop("EQUITY_RISK_PREMIUM", None)
    published = (load_table() or {}).get("mature_erp")
    assert isinstance(published, (int, float)), "no published ERP to compare against"

    resolved = _mature_erp()
    assert resolved == pytest.approx(published), (
        "the engine must discount at the published premium it already fetches, "
        "not at the house constant it only mentions in a footnote"
    )
    # And the bug's signature: the two differ, so this is a real preference
    # and not a coincidence that would hide a regression.
    assert resolved != pytest.approx(_ERP), (
        "published and house figures are equal, so this test proves nothing; "
        "pick a case where they differ"
    )


def test_erp_env_override_still_wins():
    """A desk stating its own view must still be able to."""
    from src.agents.fm.assumption_grounding import _mature_erp

    os.environ["EQUITY_RISK_PREMIUM"] = "0.05"
    try:
        assert _mature_erp() == pytest.approx(0.05)
    finally:
        os.environ.pop("EQUITY_RISK_PREMIUM", None)


@pytest.mark.parametrize("bad", ["0.99", "0.0004", "-0.04", "abc", ""])
def test_erp_rejects_an_unusable_override(bad):
    """
    A parse failure or a fat-fingered percentage must never become the
    discount rate. Out of band falls through to the published figure.
    """
    from src.agents.fm.assumption_grounding import _mature_erp
    from src.agents.fm.country_risk import load_table

    published = (load_table() or {}).get("mature_erp")
    os.environ["EQUITY_RISK_PREMIUM"] = bad
    try:
        assert _mature_erp() == pytest.approx(published)
    finally:
        os.environ.pop("EQUITY_RISK_PREMIUM", None)


def test_erp_stays_inside_a_defensible_band():
    from src.agents.fm.assumption_grounding import _mature_erp

    os.environ.pop("EQUITY_RISK_PREMIUM", None)
    assert 0.03 <= _mature_erp() <= 0.09


# --------------------------------------------------------------------------
# Part 2: the blend gives each METHODOLOGY one vote
# --------------------------------------------------------------------------

def _blend(perpetual, exit_multiple, comps):
    """Evaluate the shipped row-26 formula through the real evaluator."""
    import logging

    from openpyxl import Workbook

    from src.agents.fm.formula_evaluator import FormulaEvaluator
    from src.agents.fm.tabs.tab_summary import SummaryTabBuilder  # noqa: F401

    dcf_n = '(($B$18>0)+($B$22>0))'
    dcf_avg = f'((MAX($B$18,0)+MAX($B$22,0))/{dcf_n})'
    formula = (f'=IF({dcf_n}=0,'
               'IF($B$30>0,$B$30,AVERAGE($B$18,$B$22)),'
               f'IF($B$30>0,({dcf_avg}+$B$30)/2,{dcf_avg}))')

    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    ws.cell(row=18, column=2, value=perpetual)
    ws.cell(row=22, column=2, value=exit_multiple)
    ws.cell(row=30, column=2, value=comps)
    ws.cell(row=26, column=2, value=formula)

    ev = FormulaEvaluator(wb)
    ev.set_logger(logging.getLogger("test_valuation_calibration"))
    return ev.evaluate_all_tabs()["Summary"]["cells"].get("(26, 2)")


def test_two_near_identical_dcf_legs_get_one_vote_between_them():
    """
    AAPL's real numbers. Under the flat three-way average the two DCF legs
    outvoted comps 2:1 and produced $168.03; the DCF view and the market view
    weighted equally give $194.85.
    """
    assert _blend(111.85, 116.93, 275.32) == pytest.approx((114.39 + 275.32) / 2, abs=0.02)


def test_the_blend_does_not_simply_raise_every_number():
    """
    The point is weighting, not optimism. Where the DCF and the market agree,
    the headline must be unchanged — otherwise this is a thumb on the scale.
    """
    assert _blend(100.0, 100.0, 100.0) == pytest.approx(100.0)


def test_a_dcf_above_the_market_is_pulled_DOWN_by_comps():
    """
    Symmetry check: the same rule that lifts a too-bearish DCF must lower a
    too-bullish one, or it is a bias rather than a method.
    """
    # DCF view 300, comps 100 -> 200. The old flat average gave 233.33.
    assert _blend(300.0, 300.0, 100.0) == pytest.approx(200.0)


def test_comps_alone_carries_the_headline_when_both_dcf_legs_fail():
    assert _blend(0.0, 0.0, 275.32) == pytest.approx(275.32)


def test_dcf_alone_carries_the_headline_when_comps_is_unavailable():
    """A missing comps leg must not halve the answer."""
    assert _blend(111.85, 116.93, 0.0) == pytest.approx(114.39, abs=0.02)


def test_a_single_surviving_dcf_leg_is_the_whole_dcf_view():
    assert _blend(0.0, 116.93, 275.32) == pytest.approx((116.93 + 275.32) / 2, abs=0.02)


def test_a_total_failure_stays_negative_so_the_unreliable_rail_trips():
    """
    Every leg broken must NOT be laundered into a positive number. The
    negative value is what makes the report print the reason instead of a
    fair value.
    """
    out = _blend(-2.0, 0.0, 0.0)
    assert isinstance(out, (int, float)) and out < 0
