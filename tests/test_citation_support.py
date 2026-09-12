"""A valid evidence ID must actually support the sentence citing it."""

import json

from src.recommendation_validator import RecommendationValidator


def _response(thesis):
    target = {"price": 100.0, "range_low": 90.0, "range_high": 110.0, "driver": ""}
    return {
        "rating": "HOLD",
        "thesis": thesis,
        "valuation_perspective": "",
        "price_targets": {key: dict(target) for key in ("m3", "m6", "m12")},
        "catalysts": [],
        "risks": [],
        "scenarios": {},
        "action": {},
        "monitoring_plan": [],
    }


FIXED = {
    "rating": "HOLD",
    "targets": {
        key: {"price": 100.0, "range_low": 90.0, "range_high": 110.0}
        for key in ("m3", "m6", "m12")
    },
}


def _pack(snippet):
    return {"evidence": [{
        "id": "E1",
        "title": "Apple iPhone demand update",
        "source": "Reuters",
        "snippet": snippet,
        "reasoning": "",
        "type": "catalyst_demand",
        "date": "2026-09-01",
    }]}


def test_topically_supported_citation_passes_semantic_check():
    _, report = RecommendationValidator().validate_and_correct(
        json.dumps(_response("iPhone demand stabilized in China [E1].")),
        FIXED,
        _pack("Apple's iPhone demand stabilized in China during the quarter."),
    )
    assert "citation_support_issues" not in report


def test_unrelated_real_citation_is_rejected_not_laundered():
    _, report = RecommendationValidator().validate_and_correct(
        json.dumps(_response("Apple faces a Department of Justice antitrust trial [E1].")),
        FIXED,
        _pack("Apple's iPhone demand stabilized in China during the quarter."),
    )
    assert report["valid"] is False
    assert report["citation_support_issues"][0]["citations"] == ["E1"]


def test_claim_number_must_appear_in_the_cited_evidence():
    _, report = RecommendationValidator().validate_and_correct(
        json.dumps(_response("iPhone demand increased 25% in China [E1].")),
        FIXED,
        _pack("Apple said iPhone demand increased 12% in China."),
    )
    assert report["valid"] is False
    assert report["citation_support_issues"]


def test_degraded_delivery_removes_unsupported_but_keeps_supported_citation():
    validator = RecommendationValidator()
    data = _response(
        "iPhone demand stabilized in China [E1]. Apple faces an antitrust trial [E1]."
    )
    cleaned, removed = validator.strip_unsupported_citations(
        data, _pack("Apple's iPhone demand stabilized in China during the quarter.")
    )
    assert removed == 1
    assert "China [E1]" in cleaned["thesis"]
    assert "trial [E1]" not in cleaned["thesis"]
