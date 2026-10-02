"""The dashboard payload: benchmark only, silent when the method is ruled out."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from src.market_expectations import build_market_expectations  # noqa: E402
from test_valuation_runway_and_corroboration import _minimal_workbook  # noqa: E402


def _financials(summary=""):
    return {
        "company_data": {"basic_info": {
            "quote_type": "EQUITY", "industry": "Software - Application", "currency": "USD",
            "listing_currency": "USD", "business_summary": summary,
        }},
        "external_expectations": {"price_target": {"mean": 120.0, "analyst_count": 30}},
    }


def _computed(price=100.0):
    workbook = _minimal_workbook("Revenue (NTM10)")
    workbook["Summary"]["cells"]["(9, 2)"] = price
    return workbook


def test_withheld_run_carries_the_sentence_and_the_model_view_headline():
    out = build_market_expectations(
        _computed(), _financials(),
        {"point_estimate_withheld": True, "range_low": 60.0, "range_high": 70.0},
    )
    assert out["status"] == "ready"
    assert out["sentence"].startswith("At this price, revenue would have to grow about")
    assert out["model_view_headline"].startswith(
        "the modeled cash flows support a value below the market")
    assert out["required_growth"]["model_equivalent_growth"] is not None


def test_published_run_carries_the_sentence_without_a_withheld_headline():
    out = build_market_expectations(_computed(), _financials(), {"point_estimate_withheld": False})
    assert out["sentence"] and out["model_view_headline"] is None


def test_ruled_out_method_states_neither_direction_nor_growth():
    out = build_market_expectations(
        _computed(),
        {"company_data": {"basic_info": {
            "quote_type": "EQUITY", "industry": "Semiconductors",
            "business_summary": "Makes DRAM and NAND memory.",
        }}},
        {"point_estimate_withheld": True, "range_low": 60.0, "range_high": 70.0},
    )
    assert out["sentence"] is None and out["required_growth"] is None
    assert "states no direction" in out["model_view_headline"]
    assert out["method_note"].startswith("memory-chip margins")


def test_a_broken_input_yields_an_error_status_not_an_exception():
    out = build_market_expectations(None, None, None)
    assert out["status"] in {"ready", "error"}


from src.summary_evidence import plain_rating_note  # noqa: E402


RANGE = "VYNN's answer here is a range, not a single fair value"


def test_plain_rating_notes_cover_each_model_reason():
    cases = {
        "The valuation methods span more than 1.8x.": "the valuation methods disagree too widely to settle on one",
        "The valuation methods disagree by more than 2.5x, so no defensible point estimate exists.":
            "the valuation methods disagree too widely to settle on one",
        "Latest annual financial period is 270 days old, beyond the 200-day annual-only limit":
            "the latest annual financial statements are too old for a current valuation",
        "At least one valuation method failed with a non-positive value (perpetual_dcf).":
            "one valuation method produced no positive value",
        "The bank valuation is an audit scenario, not a publishable point estimate, because "
        "the CAPM cost of equity hit its model boundary.":
            "a core input of the bank model hit its safety limit",
    }
    for reason, cause in cases.items():
        assert plain_rating_note(reason) == f"{RANGE}, because {cause}."
    # An unrecognised reason still says what the answer is.
    assert plain_rating_note("something new") == f"{RANGE}."
    assert "lending arm" in plain_rating_note("x", "a disclosed captive-finance segment is consolidated")
    assert "price cycle" in plain_rating_note("x", "memory-chip margins follow DRAM and NAND contract prices")
    for reason in list(cases) + ["something new"]:
        note = plain_rating_note(reason)
        # A retail sentence: no auditor's terms, and nothing that reads as a
        # missing rating.
        assert "corroborate" not in note and "mega-cap" not in note and "DCF" not in note
        assert "No rating" not in note and "rated" not in note.lower()
        assert "withh" not in note.lower() and "published" not in note.lower()


def test_what_the_street_thinks_is_never_the_reason_for_a_range():
    # A sound model the Street does not back is published with a confidence
    # alert. When the model is blocked as well, the Street's position follows
    # the reason as context, and the plain sentence names only the model.
    street_only = (
        "The DCF-only estimate is -94% from the market for a mega-cap, but the "
        "available well-covered analyst-target evidence does not corroborate "
        "both the direction and material magnitude of that gap."
    )
    assert plain_rating_note(street_only) == f"{RANGE}."
    both = "The valuation methods span more than 1.8x. " + street_only
    assert plain_rating_note(both) == (
        f"{RANGE}, because the valuation methods disagree too widely to settle on one."
    )


def test_the_note_never_calls_one_estimate_or_nothing_a_range():
    nothing = plain_rating_note(
        "No finite positive intrinsic-value output was produced, so no point "
        "estimate, directional rating, or price target can be published.",
        shape="unavailable",
    )
    assert nothing == (
        "VYNN has no fair value to state here, because the model produced no "
        "positive value."
    )
    one = plain_rating_note(
        "At least one valuation method failed with a non-positive value (exit_multiple_dcf).",
        shape="single_estimate",
    )
    assert one == (
        "VYNN's answer here is a scenario estimate, not a fair value, because "
        "one valuation method produced no positive value."
    )
    for note in (nothing, one):
        assert "a range" not in note
    # A shape this function does not know is read as the weakest claim.
    assert plain_rating_note("x", shape="mystery") == "VYNN has no fair value to state here."


def test_a_ruled_out_method_is_called_a_scenario_whatever_its_shape():
    for shape in ("range", "single_estimate", "unavailable"):
        note = plain_rating_note(
            "x", "a disclosed captive-finance segment is consolidated", shape=shape)
        assert note.startswith("VYNN's answer here is a scenario, not a fair value, because ")
        assert "lending arm" in note and "a range" not in note


def test_range_only_payload_carries_the_plain_note():
    out = build_market_expectations(
        _computed(), _financials(),
        {"point_estimate_withheld": True, "range_low": 60.0, "range_high": 70.0,
         "withheld_reason": "The valuation methods span more than 1.8x."},
    )
    assert out["rating_note"] == (
        f"{RANGE}, because the valuation methods disagree too widely to settle on one."
    )
    no_range = build_market_expectations(
        _computed(), _financials(),
        {"point_estimate_withheld": True,
         "withheld_reason": "At least one valuation method failed with a non-positive value (perpetual_dcf)."},
    )
    assert no_range["rating_note"].startswith("VYNN has no fair value to state here, because")
    published = build_market_expectations(_computed(), _financials(), {"point_estimate_withheld": False})
    assert published["rating_note"] is None


def test_two_model_conditions_are_both_named_model_before_freshness():
    amazon = ("The valuation methods span more than 1.8x. That range is useful "
              "scenario evidence. Latest annual financial period is 270 days old, "
              "beyond the 200-day annual-only limit.")
    assert plain_rating_note(amazon) == (
        f"{RANGE}, because the valuation methods disagree too widely to settle "
        "on one and the latest annual financial statements are too old for a "
        "current valuation."
    )


from src.agents.tools.analysis_tools import valuation_publication_decision  # noqa: E402
from src.confidence_alert import alert_facts, alert_sentence  # noqa: E402


def _boundary_alert(*, legs, price, target, rating="buy"):
    """The alert exactly as the engine builds it for a sound model the Street
    does not back. Before, these cases were withheld and read "NOT RATED"."""
    decision = valuation_publication_decision(
        band="moderate", legs=legs, fair_value=sum(legs.values()) / len(legs),
        current_price=price, is_mega_cap=True, analyst_target=target,
        analyst_count=40, analyst_rating=rating, analyst_rating_count=40,
    )
    assert decision["withheld"] is False and decision["alert"]
    return decision["alert"]


def test_a_street_target_in_the_same_direction_backs_only_part_of_the_move():
    # Meta, 2026-09-27: the model says +26%, the Street +5%. Both call it
    # undervalued, so "different conclusions" would misread the disagreement.
    alert = _boundary_alert(
        legs={"perpetual_dcf": 852.06, "exit_multiple_dcf": 1040.74},
        price=751.66, target=790.27,
    )
    assert alert["relation"] == "smaller"
    assert alert_facts(alert) == (
        "VYNN's fair value is 26% above the market price, while the mean target "
        "of 40 analysts is 5% above it, which backs less than half of that move."
    )


def test_a_street_target_pointing_the_other_way_is_named():
    # Tesla: the model is far below the price, the Street above it.
    alert = _boundary_alert(
        legs={"perpetual_dcf": 24.34, "exit_multiple_dcf": 30.0},
        price=372.11, target=396.62, rating="hold",
    )
    assert alert["relation"] == "opposite"
    assert alert_sentence(alert) == (
        "Low confidence: VYNN's fair value is 93% below the market price, while "
        "the mean target of 40 analysts is 7% above it. That is a large gap "
        "between VYNN and the Street, so treat this as VYNN's own view and weigh both."
    )


def test_ratings_are_named_when_every_target_backs_the_move():
    alert = _boundary_alert(
        legs={"perpetual_dcf": 125.0, "exit_multiple_dcf": 135.0},
        price=100.0, target=140.0, rating="hold",
    )
    assert alert["relation"] == "rating"
    assert alert_facts(alert) == (
        "VYNN's fair value is 30% above the market price, while analysts rate "
        "it HOLD (40 ratings), which does not point the same way."
    )


def _evidence_alert(*, legs, target_rows=None, ratings=None, price=100.0):
    """An alert from the provider-evidence path production uses."""
    comps = "market_comps" in legs
    fair = (
        ((legs["perpetual_dcf"] + legs["exit_multiple_dcf"]) / 2 + legs["market_comps"]) / 2
        if comps else sum(legs.values()) / len(legs)
    )
    decision = valuation_publication_decision(
        band="moderate", legs=legs, fair_value=fair, current_price=price,
        analyst_target_evidence=target_rows or {},
        analyst_rating_evidence=ratings or {},
    )
    assert decision["withheld"] is False and decision["alert"]
    return decision["alert"]


def _target(gap, *, current=True, count=30, price=100.0):
    return {
        "mean": price * (1 + gap), "analyst_count": count,
        "qualified_for_contradiction": True,
        "qualified_for_corroboration": current,
        "temporal_quality": {"status": "current" if current else "unknown"},
    }


_COMPS_UP = {"perpetual_dcf": 125.0, "exit_multiple_dcf": 135.0, "market_comps": 130.0}
_DCF_UP = {"perpetual_dcf": 125.0, "exit_multiple_dcf": 135.0}


def test_the_comps_branch_names_the_binding_target_not_the_first():
    # Yahoo backs half the move; Finnhub's +3% is the one that does not.
    alert = _evidence_alert(legs=_COMPS_UP, target_rows={
        "yahoo_finance": _target(0.152), "finnhub": _target(0.03),
    })
    assert "The model is +30% from the market" in alert["detail"]
    assert alert_facts(alert) == (
        "VYNN's fair value is 30% above the market price, while the mean target "
        "of 30 analysts is 3% above it, which backs less than half of that move."
    )


def test_a_target_at_the_price_is_named():
    alert = _evidence_alert(legs=_DCF_UP, target_rows={"yahoo_finance": _target(0.0)})
    assert alert["relation"] == "at_market"
    assert alert_facts(alert) == (
        "VYNN's fair value is 30% above the market price, while the mean target "
        "of 30 analysts sits at the market price."
    )


def test_a_rating_is_named_when_it_is_the_only_disagreement():
    # A target just above half the move backs the model; the HOLD does not.
    alert = _evidence_alert(
        legs=_COMPS_UP, target_rows={"benzinga": _target(0.152)},
        ratings={"finnhub": {"label": "hold", "analyst_count": 20}},
    )
    assert alert["relation"] == "rating"
    assert alert_facts(alert) == (
        "VYNN's fair value is 30% above the market price, while analysts rate "
        "it HOLD (20 ratings), which does not point the same way."
    )
    # With no target at all, a SELL is still named, never "price targets".
    alert = _evidence_alert(
        legs=_COMPS_UP, ratings={"finnhub": {"label": "sell", "analyst_count": 20}},
    )
    assert "analysts rate it SELL (20 ratings)" in alert_facts(alert)


def test_a_target_that_is_not_current_is_not_called_a_disagreement():
    alert = _evidence_alert(
        legs=_DCF_UP, target_rows={"yahoo_finance": _target(0.40, current=False)},
    )
    assert alert["relation"] == "unconfirmed"
    assert alert_sentence(alert) == (
        "Low confidence: VYNN's fair value is 30% above the market price, and "
        "no current analyst target was available to check it against. Nothing "
        "outside the model confirms a gap this large, so treat it as VYNN's own view."
    )


def test_bank_alerts_use_the_bank_boundary_s_own_threshold():
    # Banks need a target that backs at least 8% or half of the move.
    from src.agents.fm.bank_valuation import assess_bank_publication
    out = assess_bank_publication(
        fair_value=140, intrinsic_fair_value=140, peer_fair_value=None, current_price=100,
        analyst_target_evidence={"yahoo_finance": {
            "mean": 115.0, "analyst_count": 25,
            "qualified_for_corroboration": True, "qualified_for_contradiction": True,
        }},
    )
    assert out["point_estimate_withheld"] is False
    assert alert_facts(out["confidence_alert"]) == (
        "VYNN's fair value is 40% above the market price, while the mean target "
        "of 25 analysts is 15% above it, which backs less than half of that move."
    )


def test_a_published_alert_is_never_called_a_missing_rating():
    # The alert qualifies an answer; it must not read as "no rating".
    alert = _evidence_alert(legs=_DCF_UP, target_rows={"yahoo_finance": _target(0.0)})
    for text in (alert_facts(alert), alert_sentence(alert)):
        lowered = text.lower()
        assert "not rated" not in lowered and "withh" not in lowered
        assert "no rating" not in lowered


def _engine_reasons():
    """Reasons exactly as the engine writes them, one per model blocker."""
    from src.agents.fm.bank_valuation import assess_bank_publication
    from src.valuation_methodology import assess_valuation_methodology

    def boundary(**kwargs):
        decision = valuation_publication_decision(**{
            "band": "moderate", "current_price": 150.0, **kwargs,
        })
        assert decision["withheld"] is True and decision["alert"] is None
        return decision["reason"]

    def bank(**kwargs):
        out = assess_bank_publication(**{
            "fair_value": 100.0, "intrinsic_fair_value": 100.0,
            "peer_fair_value": None, "current_price": 100.0, **kwargs,
        })
        assert out["point_estimate_withheld"] is True
        return out["publication_withheld_reason"]

    unsuitable = assess_valuation_methodology({"company_data": {"basic_info": {
        "quote_type": "EQUITY", "industry": "Software - Application",
        "currency": "USD", "listing_currency": "USD",
    }}})
    assert unsuitable["publication_allowed"] is False
    return {
        "wide": boundary(
            band="wide", legs={"perpetual_dcf": 100.0, "exit_multiple_dcf": 190.0},
            fair_value=145.0),
        "unreliable": boundary(
            band="unreliable", legs={"perpetual_dcf": 100.0, "exit_multiple_dcf": 300.0},
            fair_value=200.0),
        "failed leg": boundary(
            band="single-method", legs={"perpetual_dcf": 100.0, "exit_multiple_dcf": -5.0},
            fair_value=100.0),
        "no value": boundary(band="single-method", legs={}, fair_value=None),
        "bank boundary": bank(bank_inputs={
            "input_boundary_triggered": True, "cost_of_equity_clamped": True}),
        "bank spread": bank(fair_value=200.0, intrinsic_fair_value=100.0, peer_fair_value=300.0),
        "bank unavailable": bank(fair_value=None, intrinsic_fair_value=None),
        "no cash flow": unsuitable["reason"],
        "revenue forecast": (
            "The near-term operating case is not reconciled: FY1 model revenue is "
            "-22% versus the 12-analyst Street estimate. A point valuation cannot "
            "be published until this material forecast disagreement is explained "
            "or corrected."
        ),
        "margin forecast": (
            "The near-term profitability case is not reconciled: FY1 model NOPAT "
            "margin is 35.0% versus 10.0% Street-implied net margin (12 EPS analysts)."
        ),
        "stale": "Latest annual financial period is 270 days old, beyond the 200-day annual-only limit",
        "safety check": (
            "The valuation publication safety check could not be completed; the "
            "model is available only as an audit scenario."
        ),
        "missing manifest": (
            "The model's machine-readable publication decision is missing or "
            "incomplete; the workbook remains available only as an audit scenario."
        ),
    }


def test_every_reason_the_engine_writes_gets_a_plain_cause():
    # A reason with no plain cause would leave the user the bare sentence.
    for name, reason in _engine_reasons().items():
        note = plain_rating_note(reason)
        assert note.startswith(f"{RANGE}, because "), (name, reason, note)
        assert note.count(" and ") <= 3, note
        for jargon in ("DCF", "NOPAT", "CAPM", "mega-cap", "corroborate", "P/B"):
            assert jargon not in note, (name, note)


def test_the_forecast_conflict_reasons_in_this_file_are_the_engine_s_own_words():
    # The two forecast sentences above are quoted, not built; keep them tied
    # to the source that writes them.
    import inspect
    from src import report_agent
    source = inspect.getsource(report_agent.enforce_valuation_publication_boundary)
    assert '"The near-term operating case is not reconciled: "' in source
    assert '"The near-term profitability case is not reconciled: " + details' in source
