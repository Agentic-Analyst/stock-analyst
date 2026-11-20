"""The EBITDA margin shown is the one the projections make (Hansen, 18 Nov 2026).

Projected EBITDA is operating income plus D&A at the Projections tab's own
rate. The model-inputs row was a separate number the projections never read:
Hansen's showed 14.9% (D&A from a trailing statement at 1.8% of revenue)
beside a projected 27.8% (D&A at 14.7% of revenue, as reported), and the
report printed the 14.9%. Built offline from Hansen's real statements.
"""
import pathlib

import pytest

_FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def _build(name, ticker):
    from src.agents.fm.financial_model_builder import FinancialModelBuilder
    from src.agents.fm.formula_evaluator import formula_integrity, model_integrity

    class Quiet:
        def __getattr__(self, _name):
            return lambda *args, **kwargs: None

    builder = FinancialModelBuilder(ticker, Quiet())
    builder.load_json_file(_FIXTURES / name)
    builder.build_model()
    results = builder.formula_evaluator.evaluate_all_tabs()
    return results, formula_integrity(results), model_integrity(results)


@pytest.mark.parametrize("name, ticker", [
    ("hsn_ax_2026_11_18.json", "HSN.AX"),
    ("bkng_no_cost_of_revenue.json", "BKNG"),
    ("mu_memory_boom_2026_10_09.json", "MU"),
])
def test_the_margin_shown_is_the_margin_projected(name, ticker):
    results, formulas, model = _build(name, ticker)
    assert formulas["status"] == "ready" and model["status"] == "ready"
    inputs, assumptions = results["Model_Inputs"]["cells"], results["Assumptions"]["cells"]
    projections = results["Projections"]["cells"]
    for year in range(5):
        projected = projections[f"(22, {2 + year})"]
        assert inputs[f"(6, {2 + year})"] == pytest.approx(projected, abs=1e-9)
        assert assumptions[f"(10, {3 + year})"] == pytest.approx(projected, abs=1e-9)


def test_hansen_shows_its_projected_margin_and_the_report_prints_it():
    from src.report_agent import extract_model_assumptions
    results, _, _ = _build("hsn_ax_2026_11_18.json", "HSN.AX")
    margins = extract_model_assumptions(results)["ebitda_margins"]
    assert margins[0] == pytest.approx(0.2778, abs=5e-4)       # was 0.1491
    assert all(m == pytest.approx(margins[0], abs=1e-9) for m in margins)
