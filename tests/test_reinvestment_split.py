"""Projected capex glides toward replacing worn equipment, not acquired-intangible amortisation.

Hansen (19 Nov 2026): D&A is 14.7% of revenue, of which depreciation is 5.0%;
capex has been 3.9-6.0% and capitalised software 3.5-4.7%. Gliding capex to
1.1x all of D&A took it to 16.2% of revenue by year five and halved projected
free cash flow. The split rule is off until the owner decides
(VYNN_REINVESTMENT_SPLIT=1).
"""
import json
import pathlib

import pytest

from src.agents.fm.assumption_grounding import reinvestment_split

_FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def test_hansen_s_split_is_read_from_its_statements():
    split = reinvestment_split(json.loads((_FIXTURES / "hsn_ax_2026_11_18.json").read_text()))
    assert split["fiscal_year"] == "2026-06-30"
    assert split["depreciation_share_of_da"] == pytest.approx(19_322_000 / 56_791_000)
    assert split["intangibles_purchase_to_revenue"] == pytest.approx(
        (15_461_000 / 353_106_000 + 18_278_000 / 392_486_000 + 13_452_000 / 386_494_000) / 3)


def test_no_split_in_the_statements_means_no_change():
    data = {"financial_statements": {"income_statement": {"2025-12-31": {"Total Revenue": 100.0}},
                                     "cash_flow": {"2025-12-31": {"Depreciation And Amortization": 5.0}}}}
    assert reinvestment_split(data) is None


def _hansen_capex_share(monkeypatch, on):
    if on:
        monkeypatch.setenv("VYNN_REINVESTMENT_SPLIT", "1")
    else:
        monkeypatch.delenv("VYNN_REINVESTMENT_SPLIT", raising=False)
    from src.agents.fm.financial_model_builder import FinancialModelBuilder

    class Quiet:
        def __getattr__(self, _name):
            return lambda *args, **kwargs: None
    builder = FinancialModelBuilder("HSN.AX", Quiet())
    builder.load_json_file(_FIXTURES / "hsn_ax_2026_11_18.json")
    builder.build_model()
    cells = builder.formula_evaluator.evaluate_all_tabs()["Projections"]["cells"]
    return [abs(cells[f"(13, {c})"]) / cells[f"(3, {c})"] for c in (2, 6)]


def test_off_by_default_the_glide_is_unchanged(monkeypatch):
    first, last = _hansen_capex_share(monkeypatch, on=False)
    assert last == pytest.approx(1.1 * 0.147, abs=0.003)


def test_on_capex_counts_software_and_glides_to_equipment_plus_software(monkeypatch):
    first, last = _hansen_capex_share(monkeypatch, on=True)
    assert first == pytest.approx(0.039 + 0.042, abs=0.003)          # capex + capitalised software
    assert last == pytest.approx(1.1 * (0.050 + 0.042), abs=0.004)   # was 16.2%
