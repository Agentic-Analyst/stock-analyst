"""A model's result carries its projected margins beside the reported ones (Hansen, 19 Nov 2026).

Asked "what margins does it assume, and how do they compare with what Hansen
earned?", the answer said it could not tell: the tool returned only headline
results. The projections are the real model's (19 Nov run); the statements
are Hansen's (18 Nov fixture).
"""
import json
import pathlib
from types import SimpleNamespace

from src.agents.tools.analysis_tools import _margin_assumptions

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def _state(projections=FIXTURES / "hsn_ax_projections_2026_11_19.json", raw=None):
    if raw is None:
        raw = json.loads((FIXTURES / "hsn_ax_2026_11_18.json").read_text())
    return SimpleNamespace(financial_model=SimpleNamespace(json_computed_values_path=str(projections)),
                           financial_data=SimpleNamespace(raw_data=raw))


def test_hansen_s_projected_and_reported_margins():
    out = _margin_assumptions(_state())
    first, last = out["projected"][0], out["projected"][-1]
    assert first["period"] == "FY2027" and first["operating_margin"] == 0.1308
    assert first["ebitda_margin"] == 0.2778
    # The model's own growth, not projected revenue over the last annual one.
    assert first["revenue_growth"] == 0.0023 and out["projected"][1]["revenue_growth"] == 0.0412
    # The reinvestment ramp is visible: 3.9% of revenue rising to 16.2%.
    assert first["capex_share_of_revenue"] == 0.0391 and last["capex_share_of_revenue"] == 0.1616
    reported = out["reported"]
    assert len(reported) == 3 and reported[-1]["operating_margin"] > first["operating_margin"]
    assert reported[-1]["gross_margin"] == "not reported (no cost of revenue)"
    assert "no cost of revenue" in out["gross_margin_note"] and "period_note" not in out


def test_a_line_the_company_did_not_report_is_missing_not_zero():
    # The review's case: Booking has no EBITDA line for 2025.
    raw = json.loads((FIXTURES / "bkng_no_cost_of_revenue.json").read_text())
    reported = _margin_assumptions(_state(raw=raw))["reported"]
    income = raw["financial_statements"]["income_statement"]
    for row in reported:
        if "EBITDA" not in income[row["fiscal_year"]]:
            assert "ebitda_margin" not in row
    assert any("ebitda_margin" not in row for row in reported)


def test_a_twelve_month_model_labels_its_periods_and_uses_its_own_growth(tmp_path):
    # The review's case: December year end, model on the twelve months to Sep 2026.
    computed = json.loads((FIXTURES / "hsn_ax_projections_2026_11_19.json").read_text())
    computed["Assumptions"]["cells"]["(7, 3)"] = 0.10
    path = tmp_path / "model.json"
    path.write_text(json.dumps(computed))
    state = _state(projections=path)
    state.financial_model.assumptions = {"forecast_basis": {"basis": "rolling_twelve_months",
                                                             "period_end": "2026-09-30"}}
    out = _margin_assumptions(state)
    assert out["projected"][0]["period"] == "12 months to 2027-09-30"
    assert out["projected"][0]["revenue_growth"] == 0.10
    assert "twelve-month periods from 2026-09-30" in out["period_note"]


def test_no_model_file_no_block(tmp_path):
    assert _margin_assumptions(_state(projections=tmp_path / "missing.json")) is None
    assert _margin_assumptions(SimpleNamespace(financial_model=None)) is None


def test_projections_without_statements_still_show(tmp_path):
    out = _margin_assumptions(_state(raw={}))
    assert out["reported"] == [] and len(out["projected"]) == 5
