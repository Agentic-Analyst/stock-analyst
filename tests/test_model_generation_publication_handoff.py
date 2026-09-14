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
    assert "Point estimate=WITHHELD" in line
    assert "Fair Value" not in line
    assert "-48.2%" not in line


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
