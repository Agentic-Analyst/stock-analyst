"""
A scenario-only run's figures are an audit scenario, never VYNN's range.

Sandisk, re-run on the memory-maker engine, is scenario only: the cash-flow
model is ruled out for a memory maker, and the thesis card states no value.
The chat answer still said "The supported valuation-method range is
$3,447.51-$3,786.88 USD", the report closed "VYNN shows the range above
instead of a single fair value... because the valuation evidence does not
support one defensible number", and the guard allowed the range's endpoints
in the model's own prose: the peak-cycle DCF, presented as VYNN's range.

The report's parsed status lines (Investment View, Single Fair Value,
Supported Valuation Range) are unchanged: api-runner reads them.

Run:  python -m pytest tests/test_scenario_is_not_a_range.py -q
"""

import os
import sys
from types import SimpleNamespace

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "src"))
sys.path.insert(0, os.path.join(_ROOT, "tests"))

from src.agents.supervisor import supervisor_agent  # noqa: E402

MEMORY_CYCLE = {
    "publication_allowed": False,
    "primary_method": "scenario_only_pending_cycle_normalization",
    "reason": (
        "The DCF may be shown as an auditable scenario, but no point estimate or "
        "directional rating should be published because memory-chip margins follow "
        "DRAM and NAND contract prices, so the covered years sit at one point of that "
        "cycle; a point call requires a mid-cycle margin rather than the forecast "
        "years' margin."
    ),
}


def _metrics(scenario: bool):
    metrics = {
        "fair_value": 3617.20, "perpetual_price": 3447.51, "exit_multiple_price": 3786.88,
        "current_price": 1692.42, "upside_vs_market": 1.137,
        "point_estimate_withheld": True,
        "publication_withheld_reason": MEMORY_CYCLE["reason"] if scenario
        else "independent evidence conflicts",
    }
    if scenario:
        metrics["method_suitability"] = dict(MEMORY_CYCLE)
    return metrics


def _runner(scenario: bool):
    runner = supervisor_agent.SupervisorWorkflowRunner.__new__(
        supervisor_agent.SupervisorWorkflowRunner)
    runner.ticker = "SNDK"
    runner.state = SimpleNamespace(
        financial_data=SimpleNamespace(key_metrics={"basic_info": {"currency": "USD"}},
                                       raw_data={}),
        news_analysis=None,
        financial_model=SimpleNamespace(assumptions={}, valuation_metrics=_metrics(scenario)),
    )
    return runner


def test_the_scenario_answer_states_no_range():
    answer = _runner(scenario=True)._safe_withheld_valuation_answer()
    assert "valuation-method range" not in answer
    assert "3,447.51" not in answer and "3,786.88" not in answer
    assert "audit scenario, not stated as a valuation" in answer
    assert "VYNN's answer here is a scenario, not a fair value" in answer


def test_a_range_answer_still_states_its_range():
    answer = _runner(scenario=False)._safe_withheld_valuation_answer()
    assert "The supported valuation-method range is $3,447.51–$3,786.88 USD." in answer


def test_the_guard_keeps_scenario_figures_out_of_the_models_prose():
    prose = ("VYNN's answer on SNDK is a range, not a single fair value: "
             "$3,447.51–$3,786.88. The Street's mean target is $2,136.54.")
    # A range answer may state its endpoints...
    assert _runner(scenario=False)._guard_user_answer(prose) == prose
    # ...a scenario has none to state: the fixed statement replaces the prose.
    replaced = _runner(scenario=True)._guard_user_answer(prose)
    assert replaced != prose
    assert "3,447.51" not in replaced and "3,786.88" not in replaced


def test_the_report_names_the_scenario_and_keeps_the_parsed_lines():
    from src.report_agent import valuation_publication_status
    reliability = {
        "point_estimate_withheld": True, "band": "single-method",
        "range_low": 3447.51, "range_high": 3786.88,
        "withheld_reason": MEMORY_CYCLE["reason"], "method_suitability": dict(MEMORY_CYCLE),
    }
    text = valuation_publication_status({"valuation": {"reliability": reliability}})
    assert "the cash-flow model run as an audit scenario, not a valuation" in text
    assert "does not support one defensible number" not in text
    # What api-runner parses is untouched.
    assert "**Supported Valuation Range**:" in text
    assert "**Single Fair Value**: Range only" in text

    reliability.pop("method_suitability")
    text = valuation_publication_status({"valuation": {"reliability": reliability}})
    assert "because the valuation evidence does not support one defensible number" in text


def test_the_per_us_share_lead_states_no_scenario_range():
    from test_home_listing_valuation import AZN_VIEW, _london_withheld_state
    for scenario, expected in ((False, True), (True, False)):
        runner = supervisor_agent.SupervisorWorkflowRunner.__new__(
            supervisor_agent.SupervisorWorkflowRunner)
        state = _london_withheld_state()
        state.listing_view = AZN_VIEW
        if scenario:
            state.financial_model.valuation_metrics["method_suitability"] = dict(MEMORY_CYCLE)
        runner.state, runner.ticker = state, "AZN.L"
        lead = runner._listing_lead("withheld", state.financial_model.valuation_metrics)
        assert ("valuation-method range" in lead or "scenario estimate is" in lead) is expected, lead
