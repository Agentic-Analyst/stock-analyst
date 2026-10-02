import json

import openpyxl

from src.valuation_artifact_audit import (
    _confidence_alert_checks,
    _publication_input_from_artifact,
    _replay_formula_integrity,
    audit_run,
    _withheld_headline_is_explicit,
    _workbook_headline_label,
    _workbook_status_label,
)


def test_publication_recheck_preserves_saved_rolling_forecast_clock():
    forecast_basis = {
        "basis": "rolling_twelve_months",
        "as_of": "2026-07-31",
        "fiscal_year_progress": 0.496,
    }
    computed = {
        "_vynn": {"model_inputs": {"forecast_basis": forecast_basis}},
    }

    data = _publication_input_from_artifact({}, computed)

    assert data["model_inputs"]["forecast_basis"] == forecast_basis


def test_intentional_specialized_refusal_without_workbook_passes_audit(tmp_path):
    financials = tmp_path / "financials"
    financials.mkdir()
    payload = {
        "ticker": "PLD",
        "company_data": {
            "basic_info": {
                "symbol": "PLD", "quote_type": "EQUITY",
                "currency": "USD", "listing_currency": "USD",
            },
            "market_data": {
                "current_price": 118.0, "current_price_listing": 118.0,
            },
        },
        "valuation_methodology": {
            "primary_method": "reit_affo_nav",
            "specialized_service": "reit",
            "publication_allowed": False,
            "reason": "A corporate DCF is not sufficient for a REIT.",
        },
        "financial_freshness": {"status": "current"},
    }
    (financials / "financials_annual_modeling_latest.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )

    result = audit_run(tmp_path)

    assert result["status"] == "passed"
    assert result["artifact_kind"] == "specialized_refusal_without_corporate_model"
    assert result["specialized_service"] == "reit"
    assert result["financial_currency"] == "USD"
    assert result["listing_currency"] == "USD"
    assert result["current_price_listing"] == 118.0
    assert result["current_policy_publishable_value"] is None
    assert result["point_estimate_withheld"] is True
    assert result["checks"] == [
        "PASS specialized methodology refused an inapplicable corporate model"
    ]


def test_specialized_refusal_with_partial_model_artifact_still_fails_closed(tmp_path):
    financials = tmp_path / "financials"
    financials.mkdir()
    (financials / "financials_annual_modeling_latest.json").write_text(
        json.dumps({
            "valuation_methodology": {
                "specialized_service": "commodity_cycle",
                "publication_allowed": False,
            }
        }),
        encoding="utf-8",
    )
    models = tmp_path / "models"
    models.mkdir()
    (models / "partial.json").write_text("{}", encoding="utf-8")

    import pytest
    with pytest.raises(ValueError):
        audit_run(tmp_path)


def test_legacy_artifact_integrity_is_replayed_from_downloadable_workbook(tmp_path):
    models = tmp_path / "models"
    models.mkdir()
    workbook = openpyxl.Workbook()
    workbook.active.title = "Summary"
    workbook["Summary"]["A1"] = "=1/0"
    workbook.save(models / "TEST_financial_model.xlsx")

    result = _replay_formula_integrity(tmp_path)

    assert result["status"] == "error"
    assert result["issue_count"] == 1
    assert result["issues"][0]["tab"] == "Summary"
    assert result["issues"][0]["cell"] == "(1, 1)"


def test_cli_returns_nonzero_when_any_artifact_fails(monkeypatch, tmp_path):
    from src import valuation_artifact_audit as module

    results = iter([
        {"status": "passed", "checks": ["PASS ok"]},
        {"status": "passed_with_warnings", "checks": ["WARN regenerate"]},
        {"status": "failed", "checks": ["FAIL unsafe"]},
    ])
    monkeypatch.setattr(module, "audit_run", lambda _root: next(results))

    assert module.main([str(tmp_path / "one")]) == 0
    assert module.main([str(tmp_path / "two")]) == 0
    assert module.main([str(tmp_path / "three")]) == 1


def test_audit_reads_headline_from_downloadable_workbook_not_stale_sidecar(tmp_path):
    models = tmp_path / "models"
    models.mkdir()
    workbook = openpyxl.Workbook()
    workbook.active.title = "Summary"
    workbook["Summary"]["A26"] = "DCF scenario midpoint (not published)"
    workbook.save(models / "AAPL_financial_model.xlsx")

    assert _workbook_headline_label(tmp_path) == (
        "DCF scenario midpoint (not published)"
    )


def test_withheld_headline_requires_an_explicit_non_publication_warning():
    assert _withheld_headline_is_explicit(
        "DCF scenario midpoint (not published)"
    )
    assert _withheld_headline_is_explicit(
        "Point estimate withheld — scenarios only"
    )

    # These were real legacy labels.  They avoid the words "fair value" but
    # still put a prominent per-share answer in front of the user.
    assert not _withheld_headline_is_explicit("Average of Methods (Per-Share)")
    assert not _withheld_headline_is_explicit("Bank Valuation Audit Midpoint")
    assert not _withheld_headline_is_explicit("DCF scenario midpoint")
    assert not _withheld_headline_is_explicit(None)


# --------------------------------------------------------------------------
# A confidence alert qualifies a published value, and every copy states it
# --------------------------------------------------------------------------

_ALERT = {"kind": "street_divergence", "relation": "opposite", "model_gap": -0.49,
          "benchmark_gap": 0.15, "analyst_count": 35}
_FLAGGED_LABEL = "PUBLISHABLE (low confidence: far from analyst consensus)"


def _alert_checks(**overrides):
    return _confidence_alert_checks(**{
        "withheld": False, "current_alert": _ALERT,
        "stored_publication": {"publication_allowed": True, "confidence_alert": _ALERT},
        "workbook_status_label": _FLAGGED_LABEL, **overrides,
    })


def test_a_flagged_artifact_whose_copies_agree_passes():
    assert _alert_checks() == []
    assert _alert_checks(current_alert=None,
                         stored_publication={"publication_allowed": True}) == []


def test_an_alert_on_a_range_only_result_fails():
    assert _alert_checks(withheld=True) == [
        "FAIL range-only output carries a confidence alert"
    ]
    assert _alert_checks(withheld=True, current_alert=None) == []


def test_a_saved_artifact_that_dropped_the_alert_fails():
    assert _alert_checks(
        stored_publication={"publication_allowed": True, "confidence_alert": None},
    ) == ["FAIL saved artifact publishes without the confidence alert current policy requires"]


def test_an_artifact_written_before_alerts_existed_only_warns():
    assert _alert_checks(stored_publication={"publication_allowed": True}) == [
        "WARN saved artifact predates confidence alerts; regenerate before use"
    ]


def test_a_stricter_saved_artifact_is_not_this_check_s_business():
    # Saved as range-only where current policy would publish with an alert: the
    # saved copy claims less, so nothing is said that a reader could act on.
    assert _alert_checks(stored_publication={"publication_allowed": False}) == []


def test_the_workbook_must_say_low_confidence_beside_a_flagged_value():
    for label in ("PUBLISHABLE", None, "SCENARIO RANGE ONLY"):
        assert _alert_checks(workbook_status_label=label) == [
            "FAIL downloadable workbook does not state the confidence alert "
            "on the value it publishes"
        ]


def test_the_status_cell_is_read_from_the_downloadable_workbook(tmp_path):
    models = tmp_path / "models"
    models.mkdir()
    workbook = openpyxl.Workbook()
    workbook.active.title = "Summary"
    workbook["Summary"]["B24"] = _FLAGGED_LABEL
    workbook.save(models / "META_financial_model.xlsx")
    assert _workbook_status_label(tmp_path) == _FLAGGED_LABEL

    # A bank workbook states it on the bank tab; Summary only points there.
    workbook.create_sheet("Bank Valuation")["B22"] = "SCENARIO RANGE ONLY"
    workbook["Summary"]["B24"] = "='Bank Valuation'!B22"
    workbook.save(models / "META_financial_model.xlsx")
    assert _workbook_status_label(tmp_path) == "SCENARIO RANGE ONLY"
