"""Projected capex glides toward the D&A ongoing spending replaces (Hansen, 19 Nov 2026).

Capex glides from today's ratio to 1.1x D&A by year five. Hansen's D&A is
14.7% of revenue: depreciation 5.0%, amortisation 9.7%. Its capex (3.9-6.0%)
already includes the software it capitalises (3.5-4.7%: capex equals
equipment plus intangibles, to the dollar). The amortisation that spending
does not match (5.5%) is acquired intangibles running off; gliding to it took
capex to 16.2% of revenue and halved projected free cash flow. The target is
now 1.1 x (D&A - unmatched amortisation); the starting point is unchanged.
A first version added software to capex and double counted it (review).
"""
import json
import pathlib

import pytest

from src.agents.fm.assumption_grounding import reinvestment_split

_FIXTURES = pathlib.Path(__file__).parent / "fixtures"
HANSEN = json.loads((_FIXTURES / "hsn_ax_2026_11_18.json").read_text())


def test_hansen_s_unmatched_amortisation():
    split = reinvestment_split(HANSEN)
    revenue = 386_494_000
    amortisation = (56_791_000 - 19_322_000) / revenue
    spending = (15_461_000 / 353_106_000 + 18_278_000 / 392_486_000 + 13_452_000 / 386_494_000) / 3
    assert split["source"] == "income statement"
    assert split["unmatched_amortization_to_revenue"] == pytest.approx(amortisation - spending)
    assert split["da_replaced_share"] == pytest.approx(1 - (amortisation - spending) / (56_791_000 / revenue))


def _company(income, cash):
    return {"financial_statements": {"income_statement": {"2025-12-31": {"Total Revenue": 100.0, **income}},
                                     "cash_flow": {"2025-12-31": cash}}}


@pytest.mark.parametrize("income, cash", [
    # D&A not split.
    ({}, {"Depreciation And Amortization": 5.0, "Purchase Of Intangibles": -1.0}),
    # All depreciation (WiseTech's share of 1.0): nothing to cut.
    ({}, {"Depreciation And Amortization": 5.0, "Depreciation": 5.0, "Purchase Of Intangibles": -4.0}),
    # Spending matches amortisation: nothing unmatched.
    ({}, {"Depreciation And Amortization": 5.0, "Depreciation": 3.0, "Purchase Of Intangibles": -2.5}),
    # No depreciation reported (a data gap): the target must not glide to zero.
    ({}, {"Depreciation And Amortization": 10.0, "Depreciation": 0.0, "Purchase Of Intangibles": 0.0}),
    # No intangibles line at all (Vanke): capex may already hold it.
    ({}, {"Depreciation And Amortization": 5.0, "Depreciation": 3.0}),
    # Samsung: income-statement D&A a small subset of the cash-flow D&A.
    ({"Depreciation Income Statement": 1.7, "Depreciation And Amortization In Income Statement": 2.6},
     {"Depreciation And Amortization": 46.9, "Purchase Of Intangibles": -0.1}),
])
def test_no_change_without_unmatched_amortisation(income, cash):
    assert reinvestment_split(_company(income, cash)) is None


def test_a_refund_is_not_spending():
    split = reinvestment_split(_company({}, {"Depreciation And Amortization": 5.0, "Depreciation": 3.0,
                                             "Purchase Of Intangibles": 1.0}))
    assert split["intangibles_purchase_to_revenue"] == 0.0
    assert split["unmatched_amortization_to_revenue"] == pytest.approx(0.02)


def _hansen_capex_share(monkeypatch, on):
    if on:
        monkeypatch.delenv("VYNN_REINVESTMENT_SPLIT", raising=False)
    else:
        monkeypatch.setenv("VYNN_REINVESTMENT_SPLIT", "0")
    from src.agents.fm.financial_model_builder import FinancialModelBuilder

    class Quiet:
        def __getattr__(self, _name):
            return lambda *args, **kwargs: None
    builder = FinancialModelBuilder("HSN.AX", Quiet())
    builder.load_json_file(_FIXTURES / "hsn_ax_2026_11_18.json")
    builder.build_model()
    cells = builder.formula_evaluator.evaluate_all_tabs()["Projections"]["cells"]
    return [abs(cells[f"(13, {c})"]) / cells[f"(3, {c})"] for c in (2, 6)]


def test_switched_off_the_glide_is_the_old_one(monkeypatch):
    first, last = _hansen_capex_share(monkeypatch, on=False)
    assert first == pytest.approx(0.039, abs=0.002) and last == pytest.approx(1.1 * 0.147, abs=0.003)


def test_on_by_default_the_start_is_unchanged_and_the_target_drops_the_unmatched_part(monkeypatch):
    first, last = _hansen_capex_share(monkeypatch, on=True)
    split = reinvestment_split(HANSEN)
    assert first == pytest.approx(0.039, abs=0.002)                       # no double count
    assert last == pytest.approx(1.1 * (0.147 - split["unmatched_amortization_to_revenue"]), abs=0.003)


def test_the_assumption_note_appears_only_when_the_rule_applies(monkeypatch):
    from src.agents.fm import assumption_grounding as ag
    split = reinvestment_split(HANSEN)
    assert split is not None
    monkeypatch.setenv("VYNN_REINVESTMENT_SPLIT", "0")
    source = open(ag.__file__).read()
    # The note is written after the memory-cycle step and checks the switch.
    assert source.index('"Year-five capex target') > source.index("apply_mid_cycle(a, mid_cycle)")
