from src.agents.supervisor.task_agents.model_generation_agent import (
    _merge_machine_publication_boundary,
    _publication_audit_value,
    _valuation_log_summary,
)


def test_withheld_publication_handoff_uses_machine_audit_value_not_display_label():
    computed = {"_vynn": {"valuation_publication": {
        "publication_allowed": False,
        "canonical_fair_value": None,
        "model_value_for_audit": 165.89,
        "withheld_reason": "Independent evidence conflicts.",
    }}}

    assert _publication_audit_value(computed) == 165.89


def test_publication_handoff_rejects_nonpositive_and_nonfinite_values():
    assert _publication_audit_value({"_vynn": {"valuation_publication": {
        "model_value_for_audit": float("nan"),
        "canonical_fair_value": -1,
    }}}, fallback=120.0) == 120.0
    assert _publication_audit_value({}, fallback=0) is None


def test_withheld_midpoint_is_never_logged_as_fair_value():
    line = _valuation_log_summary({
        "fair_value": 171.85,
        "current_price": 332.27,
        "upside_vs_market": -0.482,
        "point_estimate_withheld": True,
    })

    assert "Audit midpoint=171.85" in line
    # Nothing here says "range": one surviving estimate is logged the same way.
    assert "Single fair value=NONE" in line and "Upside=NONE" in line
    assert "RANGE" not in line
    assert "Fair Value" not in line and "WITHHELD" not in line
    assert "-48.2%" not in line


def test_a_flagged_valuation_is_logged_with_its_confidence():
    line = _valuation_log_summary({
        "fair_value": 380.0,
        "current_price": 751.66,
        "upside_vs_market": -0.494,
        "confidence_alert": {"kind": "street_divergence", "model_gap": -0.494},
    })

    assert "Fair Value=380.00" in line and "Upside=-49.4%" in line
    assert "Confidence=LOW (far from the Street)" in line


def test_machine_publication_denial_cannot_be_loosened_by_model_only_chat():
    merged = _merge_machine_publication_boundary(
        {"fair_value": 302.08, "upside_vs_market": -0.165},
        {"_vynn": {"valuation_publication": {
            "status": "ready",
            "publication_allowed": False,
            "point_estimate_withheld": True,
            "withheld_reason": "The near-term profitability case is not reconciled.",
            "valuation_confidence": "single-method",
            "valuation_method": "dcf_only",
            "valuation_conclusion": "inconclusive",
            "range_low": 154.0,
            "range_high": 181.0,
            "model_scope": "modeled_operating_cash_flow_path_only",
            "model_scope_warning": "Not a comprehensive company value.",
        }}},
    )

    assert merged["point_estimate_withheld"] is True
    assert "profitability case" in merged["publication_withheld_reason"]
    assert merged["stored_publication_status"] == "ready"
    assert merged["valuation_method"] == "dcf_only"
    assert merged["valuation_conclusion"] == "inconclusive"
    assert merged["publication_range_low"] == 154.0
    assert merged["publication_range_high"] == 181.0
    assert merged["model_scope"] == "modeled_operating_cash_flow_path_only"


def test_machine_permission_never_clears_a_stricter_runtime_denial():
    merged = _merge_machine_publication_boundary(
        {
            "point_estimate_withheld": True,
            "publication_withheld_reason": "Runtime evidence conflicts.",
        },
        {"_vynn": {"valuation_publication": {
            "status": "ready",
            "publication_allowed": True,
            "point_estimate_withheld": False,
        }}},
    )

    assert merged["point_estimate_withheld"] is True
    assert merged["publication_withheld_reason"] == "Runtime evidence conflicts."


def test_published_machine_upside_replaces_missing_or_stale_display_value():
    merged = _merge_machine_publication_boundary(
        {"fair_value": 277.31, "current_price": 218.29, "upside_vs_market": -0.99},
        {"_vynn": {"valuation_publication": {
            "status": "ready",
            "publication_allowed": True,
            "point_estimate_withheld": False,
            "canonical_fair_value": 277.31,
            "canonical_upside_vs_market": 0.2704,
        }}},
    )

    assert merged["upside_vs_market"] == 0.2704
    assert "Upside=27.0%" in _valuation_log_summary(merged)


def test_missing_machine_publication_manifest_fails_closed():
    merged = _merge_machine_publication_boundary({"fair_value": 100.0}, {})

    assert merged["point_estimate_withheld"] is True
    assert merged["stored_publication_status"] == "missing"


# --------------------------------------------------------------------------
# The confidence alert follows the same handoff: it qualifies a published
# answer, so a denial clears it and the workbook's own alert is authoritative.
# --------------------------------------------------------------------------

_ALERT = {
    "kind": "street_divergence", "relation": "opposite", "model_gap": -0.49,
    "benchmark_gap": 0.15, "analyst_count": 35, "analyst_rating": None,
    "analyst_rating_count": None, "detail": "The DCF-only estimate is -49% from the market.",
}


def _published(**extra):
    return {"_vynn": {"valuation_publication": {
        "status": "ready", "publication_allowed": True,
        "point_estimate_withheld": False, "canonical_fair_value": 380.0,
        "canonical_upside_vs_market": -0.49, **extra,
    }}}


def test_the_workbook_s_alert_reaches_model_only_chat():
    merged = _merge_machine_publication_boundary(
        {"fair_value": 380.0, "current_price": 751.66},
        _published(confidence_alert={**_ALERT, "text": "Low confidence: ...", "label": "x"}),
    )

    assert not merged.get("point_estimate_withheld")
    # Stored display fields are dropped; the alert itself is what is carried.
    assert merged["confidence_alert"] == _ALERT


def test_an_alert_found_only_at_runtime_is_kept_when_the_workbook_has_none():
    merged = _merge_machine_publication_boundary(
        {"fair_value": 380.0, "confidence_alert": _ALERT}, _published(),
    )

    assert merged["confidence_alert"] == _ALERT


def test_a_machine_denial_clears_the_alert():
    merged = _merge_machine_publication_boundary(
        {"fair_value": 380.0, "confidence_alert": _ALERT},
        {"_vynn": {"valuation_publication": {
            "status": "ready", "publication_allowed": False,
            "point_estimate_withheld": True,
            "withheld_reason": "The valuation methods span more than 1.8x.",
        }}},
    )

    assert merged["point_estimate_withheld"] is True
    assert "confidence_alert" not in merged


def test_a_runtime_denial_never_carries_the_workbook_s_alert():
    merged = _merge_machine_publication_boundary(
        {"point_estimate_withheld": True,
         "publication_withheld_reason": "Latest annual financial period is 270 days old."},
        _published(confidence_alert=_ALERT),
    )

    assert merged["point_estimate_withheld"] is True
    assert "confidence_alert" not in merged


def test_a_missing_manifest_clears_the_alert_too():
    merged = _merge_machine_publication_boundary(
        {"fair_value": 380.0, "confidence_alert": _ALERT}, {},
    )

    assert merged["point_estimate_withheld"] is True
    assert "confidence_alert" not in merged
