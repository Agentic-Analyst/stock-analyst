"""The confidence alert: what it states, and the words every surface shares.

A sound model the Street does not back used to be withheld and read "NOT
RATED". It is now published with an alert that gives both positions. These
tests pin the alert's arithmetic and its sentences, because the chat answer,
the report, the workbook and the dashboard all print them from this module.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.confidence_alert import (  # noqa: E402
    AT_MARKET, KIND_STREET, NOT_RATED, OPPOSITE, RANGE, RATING, SCENARIO_STEM,
    SINGLE_ESTIMATE, SMALLER, UNAVAILABLE, UNCONFIRMED,
    alert_body, alert_facts, alert_label, alert_sentence, alert_sentence_zh,
    build_street_alert, no_single_value_statement, no_single_value_stem,
    normalize_alert, rating_in_report, reason_with_street_context,
    report_rating_heading, single_fair_value_line, support_shape, view_name,
    workbook_status,
)


def _target(gap, count=30, source="yahoo_finance"):
    return {"gap": gap, "count": count, "source": source}


# --------------------------------------------------------------------------
# Which Street evidence the alert names
# --------------------------------------------------------------------------

def test_a_target_on_the_other_side_is_named_first():
    alert = build_street_alert(-0.49, targets=[_target(-0.10, 12), _target(0.15, 35)])
    assert alert["kind"] == KIND_STREET
    assert alert["relation"] == OPPOSITE
    assert alert["benchmark_gap"] == 0.15 and alert["analyst_count"] == 35


def test_the_furthest_opposing_target_is_the_one_named():
    alert = build_street_alert(0.40, targets=[_target(-0.05, 10), _target(-0.22, 18)])
    assert alert["relation"] == OPPOSITE and alert["benchmark_gap"] == -0.22


def test_a_target_at_the_price_is_named_before_a_small_one():
    alert = build_street_alert(0.30, targets=[_target(0.03, 9), _target(0.001, 40)])
    assert alert["relation"] == AT_MARKET and alert["analyst_count"] == 40


def test_a_target_backing_less_than_half_the_move_is_named():
    alert = build_street_alert(0.30, targets=[_target(0.14, 20), _target(0.03, 30)])
    assert alert["relation"] == SMALLER
    # The one backing the least of the move is what a reader needs.
    assert alert["benchmark_gap"] == 0.03


def test_a_target_backing_half_the_move_is_not_a_disagreement():
    # Half of +30% is +15%. With no rating against the model either, nothing
    # is named and the alert reports that no current target was a mismatch.
    alert = build_street_alert(0.30, targets=[_target(0.152, 20)])
    assert alert["relation"] == UNCONFIRMED and alert["benchmark_gap"] is None


def test_the_half_move_floor_is_five_percent_and_eight_for_banks():
    assert build_street_alert(0.08, targets=[_target(0.045)])["relation"] == SMALLER
    assert build_street_alert(0.08, targets=[_target(0.055)])["relation"] == UNCONFIRMED
    assert build_street_alert(
        0.08, targets=[_target(0.055)], half_move_floor=0.08)["relation"] == SMALLER


def test_a_rating_is_named_only_when_no_target_argues_against_the_model():
    hold = [{"label": "hold", "count": 20}]
    assert build_street_alert(0.30, targets=[_target(0.20)], ratings=hold)["relation"] == RATING
    both = build_street_alert(0.30, targets=[_target(-0.10)], ratings=hold)
    assert both["relation"] == OPPOSITE
    # The rating still travels with the alert for surfaces that show both.
    assert both["analyst_rating"] == "HOLD" and both["analyst_rating_count"] == 20


def test_a_rating_that_agrees_with_the_model_is_not_a_disagreement():
    alert = build_street_alert(-0.30, ratings=[{"label": "strong_sell", "count": 12}])
    assert alert["relation"] == UNCONFIRMED and alert["analyst_rating"] is None


@pytest.mark.parametrize("gap", [None, 0, 0.0, float("nan"), float("inf"), "0.3", True])
def test_no_alert_without_a_model_gap(gap):
    assert build_street_alert(gap, targets=[_target(0.2)]) is None


def test_bad_rows_are_ignored_not_fatal():
    alert = build_street_alert(
        0.30,
        targets=[None, {}, {"gap": "x"}, {"gap": float("nan")}, _target(-0.2, "many")],
        ratings=[None, {"label": None}, {"label": "mystery", "count": 9}],
    )
    assert alert["relation"] == OPPOSITE and alert["analyst_count"] is None


# --------------------------------------------------------------------------
# What crosses a file or service boundary
# --------------------------------------------------------------------------

def test_normalize_keeps_a_real_alert_and_drops_display_fields():
    alert = build_street_alert(-0.49, targets=[_target(0.15, 35)], detail="  audit   text ")
    stored = {**alert, "text": "Low confidence: ...", "label": "x", "extra": object()}
    assert normalize_alert(stored) == alert
    assert alert["detail"] == "audit text"


@pytest.mark.parametrize("junk", [
    None, "alert", 3, [], {}, {"kind": "other", "model_gap": -0.4},
    {"kind": KIND_STREET}, {"kind": KIND_STREET, "model_gap": 0},
    {"kind": KIND_STREET, "model_gap": "big"},
])
def test_normalize_rejects_what_is_not_an_alert(junk):
    assert normalize_alert(junk) is None
    assert alert_sentence(junk) == "" and alert_label(junk) == "" and alert_body(junk) == ""


def test_normalize_bounds_untrusted_fields():
    alert = normalize_alert({
        "kind": KIND_STREET, "model_gap": 0.4, "relation": "invented",
        "benchmark_gap": "x", "analyst_count": -5, "analyst_rating": "x" * 500,
        "analyst_rating_count": 10**9, "detail": "d" * 5000,
    })
    assert alert["relation"] == UNCONFIRMED and alert["benchmark_gap"] is None
    assert alert["analyst_count"] is None
    assert len(alert["analyst_rating"]) == 40 and alert["analyst_rating_count"] == 100_000
    assert len(alert["detail"]) == 2000


def test_a_blocked_run_keeps_the_street_as_context_after_its_reason():
    alert = build_street_alert(-0.49, targets=[_target(0.15, 35)], detail="The Street stands apart.")
    assert reason_with_street_context("Statements are 270 days old.", alert) == (
        "Statements are 270 days old. The Street stands apart."
    )
    # Never twice, and never from something that is not an alert.
    once = reason_with_street_context("Statements are 270 days old.", alert)
    assert reason_with_street_context(once, alert) == once
    for junk in (None, {}, "alert", {"kind": "other", "detail": "x"},
                 build_street_alert(-0.49, targets=[_target(0.15, 35)])):
        assert reason_with_street_context("  Statements  are old. ", junk) == "Statements are old."
    assert reason_with_street_context(None, alert) == "The Street stands apart."


# --------------------------------------------------------------------------
# The sentences
# --------------------------------------------------------------------------

def test_the_opposite_alert_states_both_positions():
    alert = build_street_alert(-0.49, targets=[_target(0.15, 35)])
    assert alert_facts(alert) == (
        "VYNN's fair value is 49% below the market price, while the mean target "
        "of 35 analysts is 15% above it."
    )
    assert alert_sentence(alert) == (
        "Low confidence: VYNN's fair value is 49% below the market price, while "
        "the mean target of 35 analysts is 15% above it. That is a large gap "
        "between VYNN and the Street, so treat this as VYNN's own view and weigh both."
    )
    assert alert_sentence(alert) == "Low confidence: " + alert_body(alert)
    assert alert_label(alert) == "low confidence: far from analyst consensus"


def test_the_unconfirmed_alert_does_not_claim_a_disagreement():
    alert = build_street_alert(0.62)
    assert alert_sentence(alert) == (
        "Low confidence: VYNN's fair value is 62% above the market price, and "
        "no current analyst target was available to check it against. Nothing "
        "outside the model confirms a gap this large, so treat it as VYNN's own view."
    )
    assert alert_label(alert) == "low confidence: not yet confirmed by analysts"


def test_an_unknown_analyst_count_reads_naturally():
    alert = build_street_alert(-0.30, targets=[_target(0.10, 0)])
    assert "while the analysts' mean target is 10% above it" in alert_facts(alert)


@pytest.mark.parametrize("alert", [
    build_street_alert(-0.49, targets=[_target(0.15, 35)]),
    build_street_alert(0.30, targets=[_target(0.0, 30)]),
    build_street_alert(0.26, targets=[_target(0.05, 40)]),
    build_street_alert(0.30, ratings=[{"label": "hold", "count": 20}]),
    build_street_alert(0.62),
])
def test_no_sentence_reads_as_a_missing_rating(alert):
    for text in (alert_facts(alert), alert_body(alert), alert_sentence(alert), alert_label(alert)):
        lowered = text.lower()
        assert "not rated" not in lowered and "withh" not in lowered
        assert "no rating" not in lowered and "unrated" not in lowered
    # No em dash in anything a user reads.
    assert chr(0x2014) not in alert_sentence(alert) + alert_label(alert)


def test_the_chinese_sentence_states_the_same_two_positions():
    alert = build_street_alert(-0.49, targets=[_target(0.15, 35)])
    assert alert_sentence_zh(alert) == (
        "置信度低：VYNN 的公允价值低于市场价 49%，而 35 位分析师的平均目标价高于市场价 15%。"
        "两者差距较大，请将此视为 VYNN 自身的观点，并综合两方判断。"
    )
    assert alert_sentence_zh(None) == ""
    for relation_alert in (
        build_street_alert(0.30, targets=[_target(0.0, 30)]),
        build_street_alert(0.26, targets=[_target(0.05, 40)]),
        build_street_alert(0.30, ratings=[{"label": "hold", "count": 20}]),
        build_street_alert(0.62),
    ):
        text = alert_sentence_zh(relation_alert)
        assert text.startswith("置信度低：VYNN 的公允价值高于市场价") and "未评级" not in text
    # With no analyst figure to set beside VYNN's there are not two positions
    # to weigh, in Chinese as in English.
    assert alert_sentence_zh(build_street_alert(0.62)) == (
        "置信度低：VYNN 的公允价值高于市场价 62%，且没有可供核对的最新分析师目标价。"
        "模型之外尚无证据印证如此大的差距，请将此视为 VYNN 自身的观点。"
    )


@pytest.mark.parametrize("stored", [
    # Relations that name a figure the stored alert no longer carries.
    {"kind": KIND_STREET, "model_gap": 0.4, "relation": OPPOSITE, "benchmark_gap": None},
    {"kind": KIND_STREET, "model_gap": 0.4, "relation": SMALLER, "benchmark_gap": "x"},
    {"kind": KIND_STREET, "model_gap": 0.4, "relation": RATING, "analyst_rating": ""},
    {"kind": KIND_STREET, "model_gap": 0.4, "relation": "invented"},
])
def test_an_alert_with_no_analyst_figure_never_says_weigh_both(stored):
    english, chinese = alert_sentence(stored), alert_sentence_zh(stored)
    assert normalize_alert(stored)["relation"] == UNCONFIRMED
    assert alert_label(stored) == "low confidence: not yet confirmed by analysts"
    assert "no current analyst target was available" in english
    assert english.endswith("so treat it as VYNN's own view.")
    assert "weigh both" not in english and "large gap between VYNN and the Street" not in english
    assert chinese.endswith("请将此视为 VYNN 自身的观点。") and "综合两方判断" not in chinese


# --------------------------------------------------------------------------
# Words for a result with no single value
# --------------------------------------------------------------------------

def test_a_rating_keeps_the_heading_the_services_read():
    assert report_rating_heading("BUY") == "### Investment Rating: BUY"
    assert report_rating_heading("STRONG SELL", priced=False) == "### Investment Rating: STRONG SELL"


@pytest.mark.parametrize("rating", [NOT_RATED, "not rated", "", None, "  "])
def test_no_rating_is_shown_as_what_the_report_gives_instead(rating):
    assert report_rating_heading(rating) == "### Investment View: Range Only"
    assert report_rating_heading(rating, priced=False) == "### Investment View: No Market Price"


@pytest.mark.parametrize("low,high,shape", [
    (150.0, 290.0, RANGE), (290.0, 150.0, RANGE), (20.74, 20.75, RANGE),
    # Surfaces print cents: two methods equal at the cent are one estimate.
    (20.74, 20.7401, SINGLE_ESTIMATE), (264.73, 264.73, SINGLE_ESTIMATE),
    (None, None, UNAVAILABLE), (None, 12.0, UNAVAILABLE), (12.0, None, UNAVAILABLE),
    (0, 12.0, UNAVAILABLE), (-3.0, 12.0, UNAVAILABLE), (12.0, -3.0, UNAVAILABLE),
    (float("nan"), 12.0, UNAVAILABLE), (12.0, float("inf"), UNAVAILABLE),
    ("12", 14.0, UNAVAILABLE), (True, 14.0, UNAVAILABLE),
])
def test_what_the_methods_support(low, high, shape):
    assert support_shape(low, high) == shape


def test_each_shape_has_its_own_words_and_only_a_range_is_called_one():
    assert [view_name(shape) for shape in (RANGE, SINGLE_ESTIMATE, UNAVAILABLE)] == [
        "Range Only", "Scenario Estimate Only", "No Fair Value",
    ]
    assert single_fair_value_line(RANGE) == "**Single Fair Value**: Range only"
    assert single_fair_value_line(SINGLE_ESTIMATE) == "**Single Fair Value**: Scenario estimate only"
    assert single_fair_value_line(UNAVAILABLE) == "**Single Fair Value**: None"
    assert no_single_value_stem(RANGE) == "VYNN's answer here is a range, not a single fair value"
    assert no_single_value_stem(SINGLE_ESTIMATE) == (
        "VYNN's answer here is a scenario estimate, not a fair value")
    assert no_single_value_stem(UNAVAILABLE) == "VYNN has no fair value to state here"
    assert SCENARIO_STEM == "VYNN's answer here is a scenario, not a fair value"
    for shape in (SINGLE_ESTIMATE, UNAVAILABLE):
        for text in (view_name(shape), single_fair_value_line(shape),
                     no_single_value_statement(shape), no_single_value_stem(shape)):
            assert "range" not in text.lower()
    for shape in (RANGE, SINGLE_ESTIMATE, UNAVAILABLE, "mystery", None):
        for text in (view_name(shape), single_fair_value_line(shape),
                     no_single_value_statement(shape), no_single_value_stem(shape)):
            lowered = text.lower()
            assert "not rated" not in lowered and "withh" not in lowered
            assert "one method" not in lowered and chr(0x2014) not in text
    # A shape this module does not know is read as the weakest claim.
    assert view_name("mystery") == "No Fair Value"


def test_the_heading_names_what_the_report_shows_instead_of_a_rating():
    assert report_rating_heading(NOT_RATED, shape=RANGE) == "### Investment View: Range Only"
    assert report_rating_heading(NOT_RATED, shape=SINGLE_ESTIMATE) == (
        "### Investment View: Scenario Estimate Only")
    assert report_rating_heading(None, shape=UNAVAILABLE) == "### Investment View: No Fair Value"
    # No market price says nothing about the valuation, whatever its shape.
    for shape in (RANGE, SINGLE_ESTIMATE, UNAVAILABLE):
        assert report_rating_heading(NOT_RATED, priced=False, shape=shape) == (
            "### Investment View: No Market Price")
        assert report_rating_heading("HOLD", shape=shape) == "### Investment Rating: HOLD"


def test_the_machine_rating_is_read_back_from_either_wording():
    assert rating_in_report("## Recommendation\n### Investment Rating: HOLD\n") == "HOLD"
    assert rating_in_report("## Investment Rating: STRONG BUY") == "STRONG BUY"
    assert rating_in_report("### Investment View: Range Only\n") == NOT_RATED
    assert rating_in_report("### Investment View: Scenario Estimate Only\n") == NOT_RATED
    assert rating_in_report("### Investment View: No Fair Value\n") == NOT_RATED
    assert rating_in_report("### Investment View: No Market Price\n") == NOT_RATED
    # A report written before the rewording.
    assert rating_in_report("### Investment Rating: NOT RATED\n") == NOT_RATED
    assert rating_in_report("no heading at all") == NOT_RATED
    assert rating_in_report(None) == NOT_RATED


def test_the_workbook_status_cell():
    alert = build_street_alert(-0.49, targets=[_target(0.15, 35)])
    assert workbook_status(False) == "PUBLISHABLE"
    assert workbook_status(False, alert) == (
        "PUBLISHABLE (low confidence: far from analyst consensus)"
    )
    assert workbook_status(True) == "SCENARIO RANGE ONLY"
    assert workbook_status(True, one_estimate=True) == "SCENARIO ESTIMATE ONLY"
    # An alert qualifies a published answer only.
    assert workbook_status(True, alert) == "SCENARIO RANGE ONLY"
