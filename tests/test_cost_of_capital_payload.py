"""A model's result carries its discount-rate build-up (Vanke, 19 Nov 2026).

Asked "what discount rate does it use, and why?", the answer had to back 14.5%
out of the reverse DCF and could not say why the rate was so high: the tool
returned no rate at all, though the model kept its whole CAPM record.
"""
from types import SimpleNamespace

from src.agents.tools.analysis_tools import _cost_of_capital

VANKE_CAPM = {
    "wacc": 0.1452, "risk_free_rate": 0.0182, "risk_free_source": "China 10y government bond",
    "beta": 1.137, "beta_source": "regression vs CSI 300", "equity_risk_premium": 0.0433,
    "country_risk_premium": 0.0098, "cost_of_equity": 0.0784, "pre_tax_cost_of_debt": 0.2082,
    "issuer_credit_spread": 0.19, "issuer_synthetic_rating": "D",
    "issuer_interest_coverage": -0.1312,
    "issuer_credit_spread_source": "synthetic D rating: operating profit does not cover interest (distressed)",
    "after_tax_cost_of_debt": 0.1562, "equity_weight": 0.21, "debt_weight": 0.79, "wacc_clamped": False,
}


def _state(assumptions):
    return SimpleNamespace(financial_model=SimpleNamespace(assumptions=assumptions))


def test_the_build_up_is_returned_with_its_reason():
    out = _cost_of_capital(_state({"capm": VANKE_CAPM, "terminal_growth_rate": 0.01}))
    assert out["wacc"] == 0.1452 and out["issuer_synthetic_rating"] == "D"
    assert out["beta"] == 1.14 and out["issuer_interest_coverage"] == -0.13
    assert "distressed" in out["credit_spread_basis"]
    assert out["terminal_growth"] == 0.01 and "wacc_outside_usual_band" not in out
    assert "0.145 = 14.5%" in out["how_to_read"]


def test_no_record_no_block():
    assert _cost_of_capital(_state({})) is None
    assert _cost_of_capital(SimpleNamespace(financial_model=None)) is None


def test_a_rate_outside_the_usual_band_is_flagged_and_bad_numbers_left_out():
    out = _cost_of_capital(_state({"capm": {**VANKE_CAPM, "wacc_clamped": True, "beta": float("nan")}}))
    assert out["wacc_outside_usual_band"] is True and "beta" not in out


def test_the_chat_s_model_state_keeps_the_build_up(tmp_path, monkeypatch):
    # The chat's copy of the assumptions kept only a few fields, so the block
    # above would have stayed empty on every real run.
    import asyncio
    import importlib
    import importlib.util
    import json
    import pathlib
    from src.agents.supervisor.state import FinancialData, FinancialState
    import src.financial_freshness as freshness
    spec = importlib.util.spec_from_file_location(
        "mid_cycle_harness", pathlib.Path(__file__).parent / "test_mid_cycle_follow_through.py")
    harness = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(harness)
    agent = importlib.import_module("src.agents.supervisor.task_agents.model_generation_agent")
    financials = harness._memory_financials()
    (tmp_path / "financials").mkdir()
    (tmp_path / "financials" / "financials_annual_modeling_latest.json").write_text(json.dumps(financials))

    def build(ticker, json_path, output_path, logger=None):
        (tmp_path / "models" / f"{ticker}_financial_model_computed_values.json").write_text(
            json.dumps(harness._workbook({}, published=False)))
        return SimpleNamespace(llm_assumptions={"capm": VANKE_CAPM})
    monkeypatch.setattr(agent, "create_financial_model", build)
    monkeypatch.setattr(freshness, "financial_statement_freshness", lambda raw: {"status": "current"})
    state = FinancialState(user_query="value it", ticker="SNDK", company_name="Sandisk",
                           email="t@example.com", timestamp="t", analysis_path=str(tmp_path))
    state.financial_data = FinancialData(
        ticker="SNDK", company_name="Sandisk",
        key_metrics={"basic_info": financials["company_data"]["basic_info"],
                     "market_data": {"current_price": harness.PRICE}},
        raw_data=financials)
    out = asyncio.run(agent.model_generation_agent(state))
    assert out.financial_model.assumptions["capm"]["wacc"] == 0.1452
    block = _cost_of_capital(out)
    assert block["issuer_synthetic_rating"] == "D" and "distressed" in block["credit_spread_basis"]
