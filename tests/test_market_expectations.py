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


def test_plain_rating_notes_cover_each_withholding_reason():
    cases = {
        "The DCF-only estimate is -94% from the market for a mega-cap, but ... does not corroborate both the direction": "model and the Street's price targets point to different conclusions.",
        "The valuation methods span more than 1.8x.": "valuation methods disagree too widely",
        "Latest annual financial period is 270 days old, beyond the 200-day annual-only limit": "financial statements are too old",
        "At least one valuation method failed with a non-positive value (perpetual_dcf).": "produced no positive value",
        "something new": "No rating is published for this run.",
    }
    for reason, expected in cases.items():
        assert expected in plain_rating_note(reason)
    assert "lending arm" in plain_rating_note("x", "a disclosed captive-finance segment is consolidated")
    assert "price cycle" in plain_rating_note("x", "memory-chip margins follow DRAM and NAND contract prices")
    for reason in cases:
        note = plain_rating_note(reason)
        assert "corroborate" not in note and "mega-cap" not in note and "DCF" not in note


def test_withheld_payload_carries_the_plain_rating_note():
    out = build_market_expectations(
        _computed(), _financials(),
        {"point_estimate_withheld": True, "range_low": 60.0, "range_high": 70.0,
         "withheld_reason": "The valuation methods span more than 1.8x."},
    )
    assert out["rating_note"].startswith("No rating is published because the valuation methods")
    published = build_market_expectations(_computed(), _financials(), {"point_estimate_withheld": False})
    assert published["rating_note"] is None



def test_two_conditions_are_both_named_disagreement_first():
    amazon = ("The DCF-only estimate is -41% from the market for a mega-cap, but the "
              "analyst-target evidence does not corroborate both the direction and "
              "material magnitude of that gap. Latest annual financial period is 270 "
              "days old, beyond the 200-day annual-only limit.")
    assert plain_rating_note(amazon) == (
        "No rating is published because the model and the Street's price targets "
        "point to different conclusions and the latest annual financial statements "
        "are too old for a current valuation."
    )


from src.agents.tools.analysis_tools import valuation_publication_boundary  # noqa: E402


def _boundary_reason(*, legs, price, target, rating="buy"):
    """A withheld reason exactly as the engine writes it."""
    withheld, reason = valuation_publication_boundary(
        band="moderate", legs=legs, fair_value=sum(legs.values()) / len(legs),
        current_price=price, is_mega_cap=True, analyst_target=target,
        analyst_count=40, analyst_rating=rating, analyst_rating_count=40,
    )
    assert withheld
    return reason


def test_a_street_target_in_the_same_direction_backs_only_part_of_the_move():
    # Meta, 2026-09-27: the model says +26%, the Street +5%. Both call it
    # undervalued, so "different conclusions" misread the disagreement.
    reason = _boundary_reason(
        legs={"perpetual_dcf": 852.06, "exit_multiple_dcf": 1040.74},
        price=751.66, target=790.27,
    )
    assert plain_rating_note(reason) == (
        "No rating is published because the Street's price targets (+5%) back "
        "only part of the model's upside."
    )


def test_a_street_target_pointing_the_other_way_is_named():
    # Tesla: the model is far below the price, the Street above it.
    reason = _boundary_reason(
        legs={"perpetual_dcf": 24.34, "exit_multiple_dcf": 30.0},
        price=372.11, target=396.62, rating="hold",
    )
    assert plain_rating_note(reason) == (
        "No rating is published because the Street's price targets point the "
        "other way (+7%), against the model's downside."
    )


def test_ratings_are_named_when_every_target_backs_the_move():
    reason = _boundary_reason(
        legs={"perpetual_dcf": 125.0, "exit_multiple_dcf": 135.0},
        price=100.0, target=140.0, rating="hold",
    )
    assert plain_rating_note(reason) == (
        "No rating is published because the Street's analyst ratings do not "
        "point the same way as the model."
    )
