"""
Every surface reads a memory maker's method the way the report boundary does.

The boundary (#42) left peers out of a mid-cycle value and treated a workbook
built without the rewrite as a scenario, but four other readers kept their own
rule. With a qualifying peer set (5x EV/EBITDA on FY2 peak EBITDA, $3,256 for
Sandisk against a $569 mid-cycle value) the chat agent counted the peer leg,
found the methods 5.8x apart and withheld, while the report published $569
and its tables called the peers "included from blend". A report follow-up
(read_report) had no method at all, so the scenario-only Sandisk report's
fallback said "The supported valuation-method range is $3,656.10-$4,014.84"
(+122%), the audit scenario #41 keeps out of answers. And a mid-cycle answer
still carried the generic "Model-scope warning: ... not a comprehensive company
value", although its gap is the peak lasting longer, which it states.

Run:  python -m pytest tests/test_mid_cycle_follow_through.py -q
"""

import asyncio
import copy
import json
import os
import sys
from types import SimpleNamespace

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "src"))
sys.path.insert(0, os.path.join(_ROOT, "tests"))

from test_memory_mid_cycle import _memory_financials  # noqa: E402

# A peer set that passes the production policy on its own (no monkeypatch).
QUALIFYING_PEERS = {
    "status": "ready", "included_in_blended_value": True, "confidence": "moderate",
    "role": "comparable_company_valuation", "selected_method": "ev_ebitda",
    "size_screen_applied": True, "fundamental_screen_applied": True,
    "selected_peer_count": 5, "median_ev_ebitda": 14.0,
}
MID_CYCLE = {"kind": "nand", "operating_margin": 0.18, "revenue_trend_growth": 0.09}
PERPETUAL, EXIT, COMPS, MIDPOINT, PRICE = 562.23, 575.77, 3256.62, 569.0, 1692.42


def _with_peers(data):
    data = copy.deepcopy(data)
    data.setdefault("industry_data", {})["peer_comps"] = dict(QUALIFYING_PEERS)
    return data


def _short_history(data):
    """Two reported years: no revenue trend, so a memory maker stays a scenario."""
    data = copy.deepcopy(data)
    for statement in data["financial_statements"].values():
        statement.pop(min(statement))
    return data


# ── A, C: the chat model agent ──────────────────────────────────────────────

def _workbook(model_inputs, *, published):
    labels = (
        ("Current Market Price", PRICE),
        ("Value per Share (Perpetual DCF)", PERPETUAL),
        ("Value per Share (Exit Multiple DCF)", EXIT),
        ("Value per Share (Market Comps)", COMPS),
        ("DCF Fair Value (Per-Share)", MIDPOINT),
    )
    cells = {}
    for row, (label, value) in enumerate(labels, start=3):
        cells[f"({row}, 1)"] = label
        cells[f"({row}, 2)"] = value
    from src.agents.fm.memory_cycle import MID_CYCLE_SCENARIO_REASON
    publication = {
        "status": "ready", "publication_allowed": published,
        "point_estimate_withheld": not published,
        "valuation_method": "dcf",
        "method_values_for_audit": {"perpetual_dcf": PERPETUAL, "exit_multiple_dcf": EXIT},
        "model_value_for_audit": MIDPOINT,
        "comps_included_in_blended_value": False,
    }
    if published:
        publication.update(canonical_fair_value=MIDPOINT,
                           canonical_upside_vs_market=MIDPOINT / PRICE - 1)
    else:
        publication["withheld_reason"] = MID_CYCLE_SCENARIO_REASON
    return {
        "Summary": {"cells": cells},
        "_vynn": {
            "formula_integrity": {"status": "ready"},
            "model_integrity": {"status": "ready"},
            "valuation_publication": publication,
            "model_inputs": model_inputs,
        },
    }


def _run_model_agent(tmp_path, monkeypatch, financials, workbook):
    import importlib
    from src.agents.supervisor.state import FinancialData, FinancialState
    import src.financial_freshness as freshness
    agent = importlib.import_module(
        "src.agents.supervisor.task_agents.model_generation_agent")

    (tmp_path / "financials").mkdir()
    (tmp_path / "financials" / "financials_annual_modeling_latest.json").write_text(
        json.dumps(financials))

    def build(ticker, json_path, output_path, logger=None):
        (tmp_path / "models" / f"{ticker}_financial_model_computed_values.json").write_text(
            json.dumps(workbook))
        return SimpleNamespace(llm_assumptions={})

    monkeypatch.setattr(agent, "create_financial_model", build)
    # Freshness is not under test; keep the fixture's statements current.
    monkeypatch.setattr(freshness, "financial_statement_freshness",
                        lambda raw: {"status": "current"})
    state = FinancialState(user_query="should i buy SNDK", ticker="SNDK",
                           company_name="Sandisk", email="t@example.com",
                           timestamp="t", analysis_path=str(tmp_path))
    state.financial_data = FinancialData(
        ticker="SNDK", company_name="Sandisk",
        key_metrics={"basic_info": financials["company_data"]["basic_info"],
                     "market_data": {"current_price": PRICE}},
        raw_data=financials)
    return asyncio.run(agent.model_generation_agent(state)).financial_model.valuation_metrics


def test_the_chat_agent_publishes_the_mid_cycle_value_peers_left_out(tmp_path, monkeypatch):
    metrics = _run_model_agent(
        tmp_path, monkeypatch, _with_peers(_memory_financials()),
        _workbook({"mid_cycle": MID_CYCLE}, published=True))
    assert metrics["method_suitability"]["primary_method"] == "dcf_mid_cycle"
    # Counting the $3,256 peer leg made the methods 5.8x apart and withheld it.
    assert metrics.get("dispersion_band") != "unreliable"
    assert not metrics.get("point_estimate_withheld")
    assert metrics["fair_value"] == MIDPOINT


def test_the_chat_agent_reads_an_unbuilt_mid_cycle_workbook_as_a_scenario(tmp_path, monkeypatch):
    metrics = _run_model_agent(
        tmp_path, monkeypatch, _memory_financials(), _workbook({}, published=False))
    suitability = metrics["method_suitability"]
    assert suitability["primary_method"] == "scenario_only_pending_cycle_normalization"
    assert suitability["publication_allowed"] is False

    from src.agents.supervisor import supervisor_agent
    runner = supervisor_agent.SupervisorWorkflowRunner.__new__(
        supervisor_agent.SupervisorWorkflowRunner)
    runner.ticker = "SNDK"
    runner.state = SimpleNamespace(
        financial_data=SimpleNamespace(key_metrics={"basic_info": {"currency": "USD"}},
                                       raw_data={}),
        news_analysis=None,
        financial_model=SimpleNamespace(assumptions={}, valuation_metrics=metrics))
    answer = runner._safe_withheld_valuation_answer()
    assert "audit scenario" in answer
    assert "supported valuation-method range" not in answer
    assert f"{PERPETUAL:,.2f}" not in answer


def test_an_ordinary_company_still_counts_its_peers(tmp_path, monkeypatch):
    from test_valuation_runway_and_corroboration import _financials
    metrics = _run_model_agent(
        tmp_path, monkeypatch, _with_peers(_financials()), _workbook({}, published=True))
    # The agent's own check counts the peer leg ($3,256 against $569).
    assert metrics["dispersion_band"] == "unreliable"
    assert metrics["point_estimate_withheld"] is True


# ── B: the report's peer lines ──────────────────────────────────────────────

def _mid_cycle_report():
    from src.report_agent import enforce_valuation_publication_boundary
    from test_run_audit_fixes import _valuation_data
    data = _valuation_data(comps=COMPS)       # carries a qualifying peer set
    data["company_overview"].update(company_name="Sandisk Corporation", current_price=PRICE)
    valuation = data["valuation"]
    valuation["dcf_perpetual"]["intrinsic_value_per_share"] = PERPETUAL
    valuation["dcf_exit"]["intrinsic_value_per_share"] = EXIT
    valuation["summary"].update(dcf_intrinsic=PERPETUAL, exit_intrinsic=EXIT,
                                average_intrinsic=MIDPOINT, upside=MIDPOINT / PRICE - 1)
    data["model_inputs"] = {"mid_cycle": MID_CYCLE}
    return enforce_valuation_publication_boundary(data, _with_peers(_memory_financials()))


def test_the_report_never_calls_a_mid_cycle_value_s_peers_blended():
    from src.report_agent import (
        _publishable_valuation_commentary, build_street_reconciliation_table,
        generate_section_valuation,
    )
    data = _mid_cycle_report()
    valuation = data["valuation"]
    assert valuation["reliability"]["method_suitability"]["primary_method"] == "dcf_mid_cycle"

    street = build_street_reconciliation_table(
        {"market_price_at_run": PRICE}, {}, valuation, data["peer_comps"])
    peer_row = next(line for line in street.splitlines() if "Peer-multiple" in line)
    assert "excluded from blend" in peer_row

    commentary = _publishable_valuation_commentary(
        valuation, data["company_overview"], data)
    assert "included as an independent valuation leg" not in commentary
    assert "same memory-price cycle" in commentary

    section, _ = generate_section_valuation(data, None)
    assert "Present-Valued Comparable Companies" not in section
    assert "Peer Multiple (context only; excluded from fair value)" in section


def test_an_ordinary_report_still_blends_qualifying_peers():
    from src.report_agent import build_street_reconciliation_table, enforce_valuation_publication_boundary
    from test_valuation_runway_and_corroboration import _financials, _report_data
    data = _report_data(exit_value=15.0, exit_multiple=10.0)
    data["valuation"]["summary"]["comps_intrinsic"] = 16.0
    data = enforce_valuation_publication_boundary(data, _with_peers(_financials()))
    street = build_street_reconciliation_table(
        {"market_price_at_run": 372.11}, {}, data["valuation"], dict(QUALIFYING_PEERS))
    assert "included from blend" in next(
        line for line in street.splitlines() if "Peer-multiple" in line)


# ── D: report follow-ups ────────────────────────────────────────────────────

def _saved_run(tmp_path, financials, workbook):
    for folder in ("financials", "models", "screened"):
        (tmp_path / folder).mkdir()
    (tmp_path / "financials" / "financials_annual_modeling_latest.json").write_text(
        json.dumps(financials))
    (tmp_path / "models" / "SNDK_financial_model_computed_values.json").write_text(
        json.dumps(workbook))
    return tmp_path


def _guard_runner(state):
    from src.agents.supervisor import supervisor_agent
    runner = supervisor_agent.SupervisorWorkflowRunner.__new__(
        supervisor_agent.SupervisorWorkflowRunner)
    runner.ticker = "SNDK"
    runner.state = state
    return runner


def test_a_follow_up_on_a_scenario_only_report_states_no_range(tmp_path):
    from src.agents.tools.analysis_tools import _rehydrate_report_guard_state
    workbook = _workbook({}, published=False)
    audit = {"perpetual_dcf": 3656.10, "exit_multiple_dcf": 4014.84}
    workbook["_vynn"]["valuation_publication"]["method_values_for_audit"] = audit
    base = _saved_run(tmp_path, _short_history(_memory_financials()), workbook)

    state = _rehydrate_report_guard_state(base, "SNDK", "")
    suitability = state.financial_model.valuation_metrics["method_suitability"]
    assert suitability["primary_method"] == "scenario_only_pending_cycle_normalization"
    answer = _guard_runner(state)._safe_withheld_valuation_answer()
    assert "audit scenario" in answer
    assert "3,656.10" not in answer and "supported valuation-method range" not in answer


def test_read_report_hands_the_model_no_scenario_range(tmp_path, monkeypatch):
    from src.agents.tools.analysis_tools import ReadReportTool
    workbook = _workbook({}, published=False)
    base = _saved_run(tmp_path, _short_history(_memory_financials()), workbook)
    (base / "SNDK_Professional_Analysis_Report.md").write_text("# Sandisk\n")
    monkeypatch.setattr("path_utils.get_latest_analysis_path", lambda *_: base)
    ctx = SimpleNamespace(email="t@example.com", state=None, ticker=None, company_name=None)
    payload = json.loads(asyncio.run(ReadReportTool(ctx).execute("SNDK")))
    publication = payload["publication"]
    assert publication["no_single_fair_value"] is True
    assert "supported_range_low" not in publication
    assert "audit scenario" in publication["valuation_scenario_only"]


def test_a_follow_up_on_a_mid_cycle_report_says_how_it_was_valued(tmp_path, monkeypatch):
    from src.agents.tools.analysis_tools import ReadReportTool
    base = _saved_run(tmp_path, _memory_financials(),
                      _workbook({"mid_cycle": MID_CYCLE}, published=True))
    (base / "SNDK_Professional_Analysis_Report.md").write_text("# Sandisk\n")
    monkeypatch.setattr("path_utils.get_latest_analysis_path", lambda *_: base)
    ctx = SimpleNamespace(email="t@example.com", state=None, ticker=None, company_name=None)
    payload = json.loads(asyncio.run(ReadReportTool(ctx).execute("SNDK")))
    publication = payload["publication"]
    assert publication["fair_value"] == MIDPOINT
    assert publication["valuation_method_note"].startswith(
        "VYNN values a memory maker on mid-cycle economics")

    answer = _guard_runner(ctx.report_guard_state)._safe_published_valuation_answer(
        {"rating": "STRONG SELL"})
    assert "mid-cycle economics" in answer


# ── E: the scope line for a mid-cycle value ─────────────────────────────────

def _benchmark(method_suitability):
    from src.summary_evidence import external_benchmark
    return external_benchmark({}, valuation_metrics={
        "market_implied_fcf_path_vs_model": 2.35,   # the market is 3.35x the path
        "method_suitability": method_suitability,
    })


def test_a_mid_cycle_answer_explains_its_gap_as_the_peak_lasting():
    from src.summary_evidence import render_external_benchmark, render_external_benchmark_compact
    benchmark = _benchmark({"primary_method": "dcf_mid_cycle", "mid_cycle": MID_CYCLE})
    for text in (render_external_benchmark_compact(benchmark),
                 render_external_benchmark(benchmark)):
        assert "not a comprehensive company value" not in text
        assert "3.35" in text and "peak to last longer" in text


def test_other_answers_keep_the_model_scope_warning():
    from src.summary_evidence import render_external_benchmark_compact
    text = render_external_benchmark_compact(_benchmark({"primary_method": "dcf_only"}))
    assert "Model-scope warning" in text and "not a comprehensive company value" in text


def test_the_guard_takes_the_peak_explanation_for_a_mid_cycle_value():
    from src.agents.supervisor import supervisor_agent
    covers = supervisor_agent.SupervisorWorkflowRunner._answer_covers_external_benchmark
    mid_cycle = _benchmark({"primary_method": "dcf_mid_cycle", "mid_cycle": MID_CYCLE})
    answer = ("The whole-path reverse DCF puts the market at 3.35x the modeled path: "
              "the price pays for about 7 years of peak-cycle cash flow.")
    assert covers(answer, mid_cycle)
    assert not covers(answer, _benchmark({"primary_method": "dcf_only"}))


def test_the_report_states_the_mid_cycle_scope():
    from src.report_agent import build_street_reconciliation_table
    data = _mid_cycle_report()
    valuation = data["valuation"]
    valuation["dcf_perpetual"].update(enterprise_value=100.0)
    valuation.setdefault("reverse_dcf", {})["market_enterprise_value"] = 335.0
    street = build_street_reconciliation_table(
        {"market_price_at_run": PRICE}, {}, valuation, data["peer_comps"])
    assert "Mid-cycle scope" in street and "peak to last longer" in street
    assert "Model-scope warning" not in street
