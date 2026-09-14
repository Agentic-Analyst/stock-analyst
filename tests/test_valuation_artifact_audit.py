import json

import openpyxl

from src.valuation_artifact_audit import (
    _publication_input_from_artifact,
    _replay_formula_integrity,
    audit_run,
    _withheld_headline_is_explicit,
    _workbook_headline_label,
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
