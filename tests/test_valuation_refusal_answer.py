"""A run the engine refuses to value must say so plainly, not print a template.

Exxon (Oil & Gas Integrated) is refused by the methodology as a commodity-cycle
business. The chat guard treated "no model" as a published headline and
answered "XOM audited report headline: published without a point headline."
The tool results said "Could not build the valuation model" with the reason
hidden in a detail field the timeline never shows.
"""
import asyncio
import importlib
import json
import logging
import os
import re
import sys
from types import SimpleNamespace

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "src"))

from src.agents.supervisor import supervisor_agent
from src.agents.supervisor.state import FinancialData, FinancialState
from src.agents.tools.analysis_tools import BuildModelTool, WriteReportTool
from src.summary_evidence import plain_refusal_note
from src.valuation_methodology import assess_valuation_methodology


def _exxon_raw():
    return {
        "company_data": {
            "basic_info": {
                "quote_type": "EQUITY", "currency": "USD",
                "sector": "Energy", "industry": "Oil & Gas Integrated",
            },
            "market_data": {"current_price": 160.63},
        },
        "financial_statements": {"income_statement": {}, "balance_sheet": {}, "cash_flow": {}},
        "external_expectations": {
            "currency": "USD",
            "price_target": {"mean": 172.55, "analyst_count": 22, "source": "yahoo_finance"},
            "recommendations": {},
            "forward_estimates": [],
        },
    }


def test_exxon_is_refused_as_a_commodity_cycle_business():
    suitability = assess_valuation_methodology(_exxon_raw())
    assert suitability["specialized_service"] == "commodity_cycle"
    assert suitability["publication_allowed"] is False


def test_plain_refusal_notes_cover_every_refusal_kind():
    for kind in ("commodity_cycle", "reit", "insurance", "fund", "crypto",
                 "unsupported_asset", "bank_valuation_input_gap"):
        note = plain_refusal_note(kind)
        # The sentence says what the answer is, and never reads as a missing
        # rating ("NOT RATED", "No rating ... is published").
        assert note.startswith("VYNN's answer here is the evidence, not a fair value, because ")
        assert not re.search(r"\brat(?:ed|ing)\b|\bpublished\b|\bwithheld\b", note, re.I)
        assert "DCF" not in note and "normalized" not in note
    assert plain_refusal_note("commodity_cycle") == (
        "VYNN's answer here is the evidence, not a fair value, because its cash "
        "flows follow commodity prices, so a cash-flow model built on today's "
        "prices would be a bet on the commodity price rather than a valuation."
    )
    assert "outside the valuation method's scope: because." in plain_refusal_note("new_kind", "because.")
    assert plain_refusal_note(None) == (
        "No valuation model was produced in this run, so there is no fair value "
        "to state."
    )


def _runner(prompt="should i buy/hold xom?"):
    runner = supervisor_agent.SupervisorWorkflowRunner.__new__(
        supervisor_agent.SupervisorWorkflowRunner)
    runner.ticker = "XOM"
    runner.user_prompt = prompt
    runner.logger = logging.getLogger("test_refusal_answer")
    runner.state = SimpleNamespace(
        total_llm_cost=0.0,
        is_financial_data_collected=lambda: True,
        financial_data=SimpleNamespace(
            key_metrics={"basic_info": {"currency": "USD"},
                         "market_data": {"current_price": 160.63}},
            raw_data=_exxon_raw(),
        ),
        is_news_analyzed=lambda: True,
        news_analysis=SimpleNamespace(articles_count=0, overall_sentiment=None,
                                      freshness={"status": "limited"},
                                      catalysts=[], risks=[]),
        is_model_generated=lambda: False,
        financial_model=None,
        report=None,
    )
    return runner


def test_a_refused_run_gets_a_plain_answer_not_a_published_template():
    runner = _runner()
    out = runner._guard_user_answer(
        "XOM audited report headline: published without a point headline.",
        require_full_benchmark=True,
    )
    assert out.startswith(
        "XOM: VYNN's answer here is the evidence, not a fair value, because its "
        "cash flows follow commodity prices")
    assert "NOT RATED" not in out and "No rating" not in out
    assert "published without a point headline" not in out
    assert "172.55" in out          # the Street's view stays, as a benchmark
    assert "not as VYNN's rating" in out


def test_an_honest_refusal_answer_from_the_model_is_kept():
    runner = _runner()
    honest = (
        "VYNN's answer on XOM is the evidence, not a fair value, because an "
        "integrated oil company's cash flows follow commodity prices. Analysts at "
        "yahoo_finance have a mean target of USD 172.55 (+7.4%, 22 analysts); the "
        "consensus from finnhub is BUY."
    )
    for broad in (True, False):
        assert runner._guard_user_answer(honest, require_full_benchmark=broad) == honest


def test_an_answer_that_falls_back_on_the_retired_label_is_replaced():
    # "Not rated" read as "no answer". A valuation answer that says it gets
    # the fixed statement, which says what VYNN's answer is.
    runner = _runner()
    for retired in (
        "XOM is not rated: VYNN states no fair value for an integrated oil "
        "company. Analysts at yahoo_finance have a mean target of USD 172.55 "
        "(+7.4%, 22 analysts); the consensus from finnhub is BUY.",
        "No fair value here; the rating is withheld for commodity producers. "
        "Analysts at yahoo_finance have a mean target of USD 172.55.",
    ):
        out = runner._guard_user_answer(retired, require_full_benchmark=True)
        assert out.startswith("XOM: VYNN's answer here is the evidence, not a fair value"), retired
        assert "not rated" not in out.lower() and "withheld" not in out.lower()


def test_an_invented_rating_or_fair_value_is_replaced_in_any_question():
    runner = _runner()
    for bad in (
        "VYNN gives no fair value for XOM, but our rating would be a BUY given the yield.",
        "XOM: the evidence, not a fair value. The model's fair value of $185 implies upside.",
    ):
        for broad in (True, False):
            out = runner._guard_user_answer(bad, require_full_benchmark=broad)
            assert out.startswith("XOM: VYNN's answer here is the evidence, not a fair value"), bad


def test_a_valuation_question_must_be_answered_with_the_refusal():
    runner = _runner()
    silent = "Exxon looks attractive at 15x earnings and yields 3.4%."
    assert runner._guard_user_answer(silent, require_full_benchmark=True).startswith(
        "XOM: VYNN's answer here is the evidence, not a fair value")
    # A narrower question (news, price) keeps prose that claims nothing.
    assert runner._guard_user_answer(silent, require_full_benchmark=False) == silent


def test_answers_with_no_company_data_are_left_alone():
    # A price, macro or crypto answer has no model and no financials; the
    # guard must not turn it into the valuation statement.
    runner = _runner("should i buy bitcoin?")
    runner.ticker = "BTC-USD"
    runner.state.financial_data = None
    prose = "Bitcoin closed at $61,200, up 2% on the day; volume was light."
    assert runner._guard_user_answer(prose, require_full_benchmark=True) == prose
    assert runner._guard_user_answer(prose, require_full_benchmark=False) == prose


def test_a_build_failure_without_a_refusal_says_so():
    runner = _runner()
    runner.state.financial_data.raw_data["company_data"]["basic_info"]["industry"] = "Software"
    out = runner._guard_user_answer(
        "XOM audited report headline: published without a point headline.",
        require_full_benchmark=True,
    )
    assert out.startswith(
        "XOM: No valuation model was produced in this run, so there is no fair value to state.")


def _state_with_exxon():
    state = FinancialState(user_query="should i buy/hold xom?", ticker="XOM",
                           company_name="Exxon Mobil", email="test@example.com",
                           timestamp="20260928_000000")
    state.financial_data = FinancialData(ticker="XOM", company_name="Exxon Mobil",
                                         key_metrics={"basic_info": {"currency": "USD"}},
                                         raw_data=_exxon_raw())
    return state


def _context(state):
    return SimpleNamespace(state=state, user_prompt=state.user_query,
                           ensure_state_for_ticker=lambda ticker: state)


def test_build_model_reports_the_refusal_instead_of_an_error(monkeypatch):
    state = _state_with_exxon()

    async def declined(incoming):      # what model_generation_agent does for Exxon
        incoming.log_error("model_generation_agent", "A current-run-rate corporate DCF is not sufficient")
        return incoming

    module = importlib.import_module("src.agents.supervisor.task_agents.model_generation_agent")
    monkeypatch.setattr(module, "model_generation_agent", declined)

    payload = json.loads(asyncio.run(BuildModelTool(_context(state)).execute("XOM")))
    assert payload["status"] == "not_applicable"
    assert payload["refusal"] == "commodity_cycle"
    assert payload["note"].startswith(
        "No valuation model for XOM. VYNN's answer here is the evidence, not a "
        "fair value, because its cash flows follow commodity prices")
    # The prose model is told what to say, and what never to call it.
    assert "never call the result not rated, unrated or withheld" in payload["note"]
    assert "Street" in payload["note"]
    assert "normalized commodity price deck" in payload["detail"]


def test_write_report_reports_the_refusal_instead_of_an_error(monkeypatch):
    state = _state_with_exxon()

    async def declined(incoming):
        return incoming

    async def news_done(incoming):
        from src.agents.supervisor.state import NewsAnalysis
        incoming.news_analysis = NewsAnalysis(ticker="XOM")
        return incoming

    model_module = importlib.import_module("src.agents.supervisor.task_agents.model_generation_agent")
    news_module = importlib.import_module("src.agents.supervisor.task_agents.news_analysis_agent")
    monkeypatch.setattr(model_module, "model_generation_agent", declined)
    monkeypatch.setattr(news_module, "news_analysis_agent", news_done)

    payload = json.loads(asyncio.run(WriteReportTool(_context(state)).execute("XOM")))
    assert payload["status"] == "not_applicable"
    assert payload["note"].startswith("No valuation report for XOM.")


def test_a_real_build_failure_is_still_an_error(monkeypatch):
    state = _state_with_exxon()
    state.financial_data.raw_data["company_data"]["basic_info"]["industry"] = "Software"

    async def failed(incoming):
        incoming.log_error("model_generation_agent", "Financial data file not found")
        return incoming

    module = importlib.import_module("src.agents.supervisor.task_agents.model_generation_agent")
    monkeypatch.setattr(module, "model_generation_agent", failed)

    payload = json.loads(asyncio.run(BuildModelTool(_context(state)).execute("XOM")))
    assert payload["status"] == "error"
    assert payload["error"] == "Could not build the valuation model for XOM."
