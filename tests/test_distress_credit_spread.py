"""A company that cannot cover its interest borrows at a distressed rate, in any currency.

China Vanke (18 Nov 2026) loses money from operations, yet was lent to at
the 1.5% house spread (3.1% all in) and discounted at 2.5%: the synthetic
rating table is calibrated on large US firms, so it was skipped for a yuan
reporter. Distress (EBIT below 1.25x interest) now applies it anywhere; a
healthy issuer outside the table's scope keeps the house fallback.
"""
import pytest

from src.agents.fm.assumption_grounding import _DEBT_SPREAD, _issuer_credit_spread


def _company(currency, market_cap, rows):
    company = {"basic_info": {"currency": currency}, "market_data": {"market_cap": market_cap}}
    statements = {f"{2022 + i}-12-31": {"Operating Income": ebit, "Interest Expense": interest}
                  for i, (ebit, interest) in enumerate(rows)}
    return company, {"financial_statements": {"income_statement": statements}}


def test_a_yuan_reporter_losing_money_gets_the_distress_spread():
    company, data = _company("CNY", 30e9, [(-5.0e9, 4.0e9), (-2.3e9, 3.8e9), (1.0e9, 3.5e9)])
    spread = _issuer_credit_spread(company, data)
    assert spread["synthetic"] and spread["rating"] == "D2/D" and spread["spread"] == pytest.approx(0.19)
    assert "outside its USD scope" in spread["source"]


def test_a_healthy_yuan_reporter_keeps_the_house_fallback():
    company, data = _company("CNY", 30e9, [(9.0e9, 1.0e9), (8.0e9, 1.0e9)])
    spread = _issuer_credit_spread(company, data)
    assert not spread["synthetic"] and spread["spread"] == pytest.approx(_DEBT_SPREAD)


def test_a_small_us_company_in_distress_gets_its_spread_too():
    company, data = _company("USD", 2e9, [(0.5e9, 1.0e9), (0.6e9, 1.0e9)])
    spread = _issuer_credit_spread(company, data)
    assert spread["rating"] == "C2/C" and "below its >$5B scope" in spread["source"]


def test_a_small_healthy_us_company_keeps_the_house_fallback():
    company, data = _company("USD", 2e9, [(3.0e9, 1.0e9), (3.2e9, 1.0e9)])
    assert _issuer_credit_spread(company, data)["spread"] == pytest.approx(_DEBT_SPREAD)


def test_one_bad_year_is_not_distress():
    # The median of the observations decides, not the single worst year.
    company, data = _company("EUR", 10e9, [(-1.0e9, 1.0e9), (4.0e9, 1.0e9), (4.5e9, 1.0e9)])
    assert not _issuer_credit_spread(company, data)["synthetic"]


def test_equity_never_costs_less_than_the_company_s_debt(monkeypatch):
    # Vanke on 19 Nov 2026: CAPM gave its equity 4.1% beside 20.6% on its debt.
    from src.agents.fm import assumption_grounding as ag
    import src.agents.fm.market_beta as mb
    monkeypatch.setattr(mb, "compute_beta", lambda s: None)
    company, data = _company("CNY", 35e9, [(-5.0e9, 4.0e9), (-2.3e9, 3.8e9), (1.0e9, 3.5e9)])
    company["market_data"].update({"beta": 0.6, "market_cap_financial": 35e9})
    company["capital_structure"] = {"total_debt": 365e9}
    capm = ag.capm_components(company, data)
    assert capm["cost_of_equity_capm"] < capm["pre_tax_cost_of_debt"]
    assert capm["cost_of_equity"] == pytest.approx(capm["pre_tax_cost_of_debt"])
    assert capm["cost_of_equity_floored_at_debt"] is True
    wacc, note = ag.compute_capm_wacc(company, components=capm)
    assert "equity ranks below debt" in note and wacc == capm["wacc"]


def test_a_healthy_company_s_cost_of_equity_is_plain_capm(monkeypatch):
    from src.agents.fm import assumption_grounding as ag
    import src.agents.fm.market_beta as mb
    monkeypatch.setattr(mb, "compute_beta", lambda s: None)
    company, data = _company("USD", 50e9, [(9.0e9, 1.0e9), (8.0e9, 1.0e9)])
    company["market_data"].update({"beta": 1.1, "market_cap_financial": 50e9})
    company["capital_structure"] = {"total_debt": 10e9}
    capm = ag.capm_components(company, data)
    assert capm["cost_of_equity"] == pytest.approx(capm["cost_of_equity_capm"])
    assert capm["cost_of_equity_floored_at_debt"] is False


def test_a_loss_maker_with_almost_no_debt_keeps_its_capm_cost_of_equity(monkeypatch):
    # The review's case: $40B of equity, $1B of debt, operating losses against
    # $20M of interest. The D spread on that sliver of debt (23.8% all in) must
    # not become the equity's required return (WACC ~24% instead of ~8%).
    from src.agents.fm import assumption_grounding as ag
    import src.agents.fm.market_beta as mb
    monkeypatch.setattr(mb, "compute_beta", lambda s: None)
    company, data = _company("USD", 40e9, [(-1.2e9, 0.02e9), (-0.9e9, 0.02e9), (-0.5e9, 0.02e9)])
    company["market_data"].update({"beta": 1.1, "market_cap_financial": 40e9})
    company["capital_structure"] = {"total_debt": 1e9}
    capm = ag.capm_components(company, data)
    assert capm["issuer_synthetic_rating"] == "D2/D"
    assert capm["cost_of_equity"] == pytest.approx(capm["cost_of_equity_capm"])
    assert capm["cost_of_equity_floored_at_debt"] is False and capm["wacc"] < 0.12


def test_the_workbook_formula_uses_the_same_debt_weight_rule():
    import openpyxl
    from src.agents.fm import assumption_grounding as ag
    from src.agents.fm.tabs import tab_valuation_perpetual_growth_dcf as tab
    source = open(tab.__file__).read()
    assert "IF(B11>={_KE_FLOOR_DEBT_WEIGHT},MAX(B3+B5*B4,B7),B3+B5*B4)" in source
    assert ag._KE_FLOOR_DEBT_WEIGHT == 0.30


@pytest.mark.parametrize("debt_weight, expected_ke", [(0.91, 0.2062), (0.05, 0.0414)])
def test_the_workbook_formula_evaluates_to_the_same_rule(debt_weight, expected_ke):
    import openpyxl
    from src.agents.fm.assumption_grounding import _KE_FLOOR_DEBT_WEIGHT
    from src.agents.fm.formula_evaluator import FormulaEvaluator
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Valuation (DCF)"
    # Rf, ERP, beta, Kd, E/V and D/V as the DCF tab lays them out.
    ws["B3"], ws["B4"], ws["B5"], ws["B7"] = 0.0102, 0.0415, 0.75, 0.2062
    ws["B10"] = 1 - debt_weight
    ws["B11"] = "=1-B10"
    ws["B6"] = f"=IF(B11>={_KE_FLOOR_DEBT_WEIGHT},MAX(B3+B5*B4,B7),B3+B5*B4)"
    ke = FormulaEvaluator(wb).evaluate_all_tabs()["Valuation (DCF)"]["cells"]["(6, 2)"]
    assert ke == pytest.approx(expected_ke, abs=1e-4)
