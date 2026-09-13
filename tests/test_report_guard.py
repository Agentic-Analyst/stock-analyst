"""
A request for a report produces a report — and only a request does.

On "Build a full DCF model and research report for PCJEWELLER.NS with a price
target" one run in seven built the model, read the news and answered — no
report, no download. The model plans the turn; whether an explicit request is
honoured is not its call. The harness now writes the report itself when the
model ends the turn without doing so, and asks it to restate the answer.

The first cut of this guard was reviewed adversarially and lost on four
counts, each pinned below: it fired on a declined offer ("don't write a
report, just the price"), on coins and screeners the prompt excludes from
write_report, on follow-ups about an existing report, and it told the model a
report was ready when the tool had failed.

Run:  python -m pytest tests/test_report_guard.py -q
"""

import asyncio
import json
import os
import sys
import types

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "src"))

from agents.generalist_agent import GeneralistAgent, report_language, wants_report


class TestWantsReport:
    @pytest.mark.parametrize("prompt", [
        "Build a full DCF model and research report for PCJEWELLER.NS with a price target.",
        "write a report on NVDA",
        "Write me a research report about Tesla",
        "generate an equity research report for AAPL",
        "Can you prepare an investment report for Apple?",
        "I need a full report on LVMH, sell-side style",
        "Please produce a detailed analysis report for 7203.T",
        "put together a valuation report for Shell",
        "analyze NVDA and give me a research report",
        "Run a report on NVDA",
        "Can you do a deep-dive report on NVDA?",
        "regenerate the report for AAPL",
        "Write a full report on Apple in the same format as your last report",
        "分析英伟达并用中文写报告",
        "请给我做一份关于腾讯的研究报告",
        "トヨタのレポートを作成してください",
    ])
    def test_creation_requests(self, prompt):
        assert wants_report(prompt) is True

    @pytest.mark.parametrize("prompt", [
        "what did the earnings report say about margins?",
        "summarize the report",
        "summarize the full report in plain English",
        "what were the risks in the report?",
        "explain the valuation in the research report you wrote",
        "read back the generated report and extract the key assumptions",
        "how does the annual report describe the segments",
        "what is NVDA's price?",
        "should I buy Apple?",
        "report the latest price of Tesla",
        "According to the report, what is the fair value?",
        # declined offers
        "please don't generate a full report, just the fair value for NVDA",
        "don't write a report, just tell me the price",
        "no, don't write a report, just give me NVDA's fair value",
        "I don't need a full report, just the fair value",
        "no report needed, just the fair value",
        "without writing a report, what's NVDA's fair value?",
        "不要写报告，只要股价",
        "别写报告了，告诉我股价就行",
        # edits of an existing report
        "make the report shorter",
        "I want the report in Chinese",
        "make the report more detailed",
        "Give me the report as a PDF",
        "Send me the report you generated",
        "can you give me the report again?",
        "",
        None,
    ])
    def test_references_declines_and_unrelated_questions(self, prompt):
        assert wants_report(prompt) is False

    def test_language_of_a_cjk_request(self):
        assert report_language("分析英伟达并用中文写报告") == "Chinese"
        assert report_language("トヨタのレポートを作成してください") == "Japanese"
        assert report_language("삼성전자 보고서 작성해줘") == "Korean"
        assert report_language("write a report on NVDA") == ""


class _Provider:
    def __init__(self, text="Restated answer with the report's rating.", fail=False, openai=True):
        self.text, self.fail, self.calls, self.is_openai = text, fail, [], openai

    async def call_with_tools(self, messages, tools, temperature=0.4, *, tool_choice=None):
        self.calls.append({"messages": list(messages), "tools": list(tools), "tool_choice": tool_choice})
        if self.fail:
            raise RuntimeError("provider down")
        return types.SimpleNamespace(text=self.text, cost=0.01, raw={"role": "assistant", "content": self.text},
                                     has_tool_calls=False, tool_calls=[])


class _Registry:
    def __init__(self, status="ok"):
        self.calls, self.status = [], status

    async def execute(self, name, params):
        self.calls.append((name, dict(params)))
        if self.status != "ok":
            return json.dumps({"status": "error", "error": "Could not gather all prerequisites for PCJEWELLER.NS"})
        return json.dumps({"status": "ok", "note": "Report written", "report_path": f"/data/x/{params['ticker']}/reports/r.md",
                           "rating": "SELL", "fair_value": 12.61})


TOOLS = [{"type": "function", "function": {"name": "write_report"}}]


def _agent(prompt, tools_used=(), ctx_ticker=None, context=None, registry=None):
    ag = GeneralistAgent.__new__(GeneralistAgent)
    ag.user_prompt = prompt
    ag.conversation_context = context
    ag._tools_used = set(tools_used)
    ag.total_cost = 0.0
    ag.ctx = types.SimpleNamespace(ticker=ctx_ticker)
    ag.registry = registry or _Registry()
    ag.logs = []
    ag._log = ag.logs.append
    return ag


ASK = "Build a full DCF model and research report for PCJEWELLER.NS with a price target."


class TestTheGuard:
    def _run(self, ag, provider, messages=None):
        messages = messages if messages is not None else [{"role": "user", "content": ag.user_prompt}]
        text = asyncio.run(ag._ensure_report_if_requested(messages, provider, "Original answer.",
                                                          {"role": "assistant", "content": "Original answer."}, TOOLS))
        return text, messages

    def test_writes_the_report_the_model_skipped_and_restates_the_answer(self):
        ag = _agent(ASK, tools_used={"build_model", "get_financials", "analyze_news"}, ctx_ticker="PCJEWELLER.NS")
        provider = _Provider()
        text, messages = self._run(ag, provider)
        assert ag.registry.calls == [("write_report", {"ticker": "PCJEWELLER.NS"})]
        assert text == "Restated answer with the report's rating."
        assert "write_report" in ag._tools_used
        # The transcript gets a plain-content assistant message (never the provider's raw with a null
        # tool_calls field, which Chat Completions rejects) and then the harness note.
        assert messages[-2] == {"role": "assistant", "content": "Original answer."}
        assert "tool_calls" not in messages[-2]
        assert messages[-1]["role"] == "user" and "HARNESS NOTE" in messages[-1]["content"]
        assert "UNTRUSTED DATA" in messages[-1]["content"] and "Report written" in messages[-1]["content"]
        # The restating turn keeps the tools defined and forbids using one.
        last = provider.calls[-1]
        assert last["tools"] == TOOLS and last["tool_choice"] == "none"
        assert any("running write_report for PCJEWELLER.NS" in l for l in ag.logs)
        assert any(l.startswith("📋 Running the full analysis for PCJEWELLER.NS") for l in ag.logs)
        assert any(l.startswith("[SUPERVISOR] 🔧 write_report(") for l in ag.logs)

    def test_anthropic_gets_the_dict_form_of_tool_choice(self):
        ag = _agent(ASK, tools_used={"build_model"}, ctx_ticker="PCJEWELLER.NS")
        provider = _Provider(openai=False)
        self._run(ag, provider)
        assert provider.calls[-1]["tool_choice"] == {"type": "none"}

    def test_a_failed_report_is_reported_as_failed_not_as_ready(self):
        ag = _agent(ASK, tools_used={"build_model"}, ctx_ticker="PCJEWELLER.NS", registry=_Registry(status="error"))
        provider = _Provider()
        text, messages = self._run(ag, provider)
        assert ag.registry.calls[0][0] == "write_report"
        assert provider.calls == []                                   # no restate turn
        assert text.startswith("Original answer.")
        assert "could not be produced: Could not gather all prerequisites" in text
        assert not any("HARNESS NOTE" in str(m.get("content")) for m in messages)
        assert any("write_report failed" in l for l in ag.logs)

    def test_a_cjk_request_gets_its_language(self):
        ag = _agent("请给我做一份关于腾讯的研究报告", tools_used={"build_model"}, ctx_ticker="0700.HK")
        self._run(ag, _Provider())
        assert ag.registry.calls == [("write_report", {"ticker": "0700.HK", "output_language": "Chinese"})]

    def test_leaves_the_answer_when_the_report_was_written(self):
        ag = _agent(ASK, tools_used={"write_report"}, ctx_ticker="PCJEWELLER.NS")
        text, _ = self._run(ag, _Provider())
        assert text == "Original answer." and ag.registry.calls == []

    def test_leaves_the_answer_on_a_follow_up_that_read_the_report(self):
        ag = _agent("summarize the report", tools_used={"read_report"}, ctx_ticker="PCJEWELLER.NS")
        text, _ = self._run(ag, _Provider())
        assert text == "Original answer." and ag.registry.calls == []

    def test_leaves_the_answer_when_a_report_for_this_company_already_exists_in_the_session(self):
        ctx = "Turn 1: Report Generated — /data/u/PCJEWELLER.NS/reports/x.md (SELL, ₹12.61)"
        ag = _agent("give me the report in Chinese please", tools_used={"get_prices"}, ctx_ticker="PCJEWELLER.NS", context=ctx)
        text, _ = self._run(ag, _Provider())
        assert ag.registry.calls == []

    def test_leaves_the_answer_when_no_report_was_asked_for(self):
        ag = _agent("what is PC Jeweller's price?", tools_used={"get_prices"}, ctx_ticker="PCJEWELLER.NS")
        text, _ = self._run(ag, _Provider())
        assert text == "Original answer." and ag.registry.calls == []

    def test_a_declined_offer_is_not_a_request(self):
        ag = _agent("no, don't write a report, just give me NVDA's fair value", tools_used={"build_model"}, ctx_ticker="NVDA")
        text, _ = self._run(ag, _Provider())
        assert ag.registry.calls == []

    @pytest.mark.parametrize("prompt,used,ticker", [
        ("write me a report on Bitcoin", {"get_crypto"}, None),
        ("write me a report on VOO", {"get_fund"}, None),
        ("Give me a report on the 5 cheapest semiconductor stocks", {"compare_tickers"}, "NVDA"),
        ("Prepare a research report for NVDA and AMD", {"compare_tickers"}, "NVDA"),
        ("Write a market report on how the S&P did this week", {"get_prices"}, None),
        ("Create a watchlist report for my portfolio: NVDA, AMD, TSLA", {"get_prices"}, "NVDA"),
        ("give me a report on the tech sector", {"get_global_news"}, None),
    ])
    def test_stays_out_of_what_the_prompt_excludes_from_write_report(self, prompt, used, ticker):
        ag = _agent(prompt, tools_used=used, ctx_ticker=ticker)
        self._run(ag, _Provider())
        assert ag.registry.calls == []

    @pytest.mark.parametrize("ticker", [None, "", "CHAT", "PENDING", "UNKNOWN", "^GSPC", "GC=F", "BTC-USD", "EURUSD=X"])
    def test_only_a_listed_company_committed_this_turn_counts(self, ticker):
        ag = _agent(ASK, tools_used={"get_prices"}, ctx_ticker=ticker)
        text, _ = self._run(ag, _Provider())
        assert ag.registry.calls == []
        assert any("no listed company was established" in l for l in ag.logs)

    def test_keeps_the_original_answer_if_the_restating_turn_fails(self):
        ag = _agent(ASK, tools_used={"build_model"}, ctx_ticker="PCJEWELLER.NS")
        text, _ = self._run(ag, _Provider(fail=True))
        assert ag.registry.calls[0][0] == "write_report"      # the report still exists
        assert text == "Original answer."
        assert any("Could not restate" in l for l in ag.logs)


def test_generalist_final_answer_uses_shared_withheld_and_analyst_guard():
    ag = _agent("Build a full AAPL report", ctx_ticker="AAPL")
    ag.ctx.state = types.SimpleNamespace(
        financial_data=types.SimpleNamespace(
            key_metrics={"basic_info": {"currency": "USD"}},
            raw_data={
                "external_expectations": {
                    "currency": "USD",
                    "price_target": {
                        "mean": 335.72,
                        "return_vs_market": 0.01,
                        "analyst_count": 26,
                        "source": "benzinga",
                        "provider_as_of": "2026-09-12",
                        "qualified_for_corroboration": True,
                    },
                    "recommendations": {},
                    "forward_estimates": [],
                },
            },
        ),
        news_analysis=types.SimpleNamespace(freshness={"status": "limited"}),
        financial_model=types.SimpleNamespace(
            assumptions={},
            valuation_metrics={
                "perpetual_price": 154.04,
                "exit_multiple_price": 180.33,
                "point_estimate_withheld": True,
                "publication_withheld_reason": "market and analyst evidence conflicts",
                "market_implied_terminal_fcf": 619e9,
                "market_implied_fcf_vs_model": 2.09,
            },
        ),
    )

    guarded = ag._guard_final_answer(
        "AAPL is NOT RATED. Overall sentiment: bearish. "
        "Analysts were considered as a cross-check."
    )

    assert guarded.startswith("AAPL is NOT RATED")
    assert "154.04–$180.33" in guarded
    assert "human-analyst mean target USD 335.72" in guarded
    assert "reverse DCF" in guarded
    assert "209.0% above the model" in guarded
    assert "overall sentiment" not in guarded.lower()


def test_crypto_answer_guard_removes_unsupported_valuation_labels_only():
    ag = _agent(
        "Is Bitcoin attractive?", tools_used={"get_crypto", "get_technicals"},
        ctx_ticker="BTC-USD",
    )
    answer = (
        "Bitcoin looks constructive, but not cheap in a valuation sense.\n"
        "- Price: $77,250\n"
        "- RSI: 46.3\n"
        "- Bottom line: accumulate on pullbacks rather than call it a bargain.\n"
        "Volatility remains high."
    )

    guarded = ag._guard_specialized_answer(answer)

    assert guarded.startswith("This crypto snapshot has no defensible")
    assert "Bitcoin looks constructive" not in guarded
    assert "call it a bargain" not in guarded
    assert "Price: $77,250" in guarded
    assert "RSI: 46.3" in guarded
    assert "Volatility remains high" in guarded


def test_crypto_answer_guard_leaves_supported_risk_language_untouched():
    ag = _agent("Analyze BTC", tools_used={"get_crypto"}, ctx_ticker="BTC-USD")
    answer = "BTC has high volatility and neutral RSI; suitability depends on horizon."
    assert ag._guard_specialized_answer(answer) == answer


def test_crypto_answer_guard_blocks_valuation_synonyms_and_snapshot_health_labels():
    ag = _agent(
        "Analyze BTC and tell me if it is cheap", tools_used={"get_crypto"},
        ctx_ticker="BTC-USD",
    )
    answer = (
        "### Network health\n"
        "The network data looks functional and active.\n"
        "- Block height: 966,761\n"
        "- Market structure: strong liquidity from $12.8B of reported volume.\n"
        "- It is not a screaming buy on valuation.\n"
        "- One-year volatility: 44.4%."
    )

    guarded = ag._guard_specialized_answer(answer)

    assert guarded.startswith("This crypto snapshot has no defensible")
    assert "Point-in-time network" in guarded
    assert "### Network health" in guarded
    assert "Block height: 966,761" in guarded
    assert "One-year volatility: 44.4%" in guarded
    assert "functional and active" not in guarded
    assert "strong liquidity" not in guarded
    assert "buy on valuation" not in guarded


def test_crypto_snapshot_guard_does_not_delete_supported_technical_labels():
    ag = _agent("Analyze BTC", tools_used={"get_crypto", "get_technicals"})
    answer = "MACD is weak, volatility is high, and RSI is neutral."
    assert ag._guard_specialized_answer(answer) == answer


def test_crypto_snapshot_guard_uses_heading_context_and_removes_empty_subheadings():
    ag = _agent("Analyze BTC", tools_used={"get_crypto"})
    answer = (
        "## Network health\n"
        "### Network interpretation\n"
        "- Healthy from a functionality standpoint\n"
        "- Not overheated\n"
        "## Risk\n"
        "- One-year max drawdown: -53%."
    )
    guarded = ag._guard_specialized_answer(answer)
    assert "Point-in-time network" in guarded
    assert "Network interpretation" not in guarded
    assert "Healthy" not in guarded
    assert "overheated" not in guarded
    assert "## Risk" in guarded
    assert "One-year max drawdown: -53%" in guarded


def test_crypto_snapshot_guard_removes_quality_labels_repeated_in_conclusion():
    ag = _agent("Analyze BTC and give a rating", tools_used={"get_crypto"})
    answer = (
        "### Liquidity and market structure\n"
        "- $12.9B in volume is substantial.\n"
        "- Broad global participation.\n"
        "### My conclusion: Buy, Hold, or Sell?\n"
        "**Hold** is my base-case conclusion.\n"
        "- The network is functioning well.\n"
        "- Liquidity is excellent.\n"
        "- One-year volatility is 44%."
    )
    guarded = ag._guard_specialized_answer(answer)
    assert "volume is substantial" not in guarded
    assert "Broad global participation" not in guarded
    assert "network is functioning well" not in guarded
    assert "Liquidity is excellent" not in guarded
    assert "**Hold** is my base-case conclusion" in guarded
    assert "risk-and-momentum stance" in guarded
    assert "One-year volatility is 44%" in guarded


def test_prediction_tool_is_refused_when_the_user_did_not_ask_for_event_odds():
    ag = _agent("Analyze BTC valuation and network health", tools_used={"get_crypto"})
    result = asyncio.run(ag._execute_tool("get_prediction_markets", {
        "topic": "Bitcoin price", "limit": 5,
    }))
    payload = json.loads(result.split("\n", 1)[1])
    assert payload["status"] == "not_applicable"
    assert payload["markets"] == []
    assert "get_prediction_markets" not in ag._tools_used
    assert ag.registry.calls == []


def test_prediction_tool_remains_available_for_explicit_odds_questions():
    ag = _agent("What are the odds Bitcoin will hit $100k by December?")
    result = asyncio.run(ag._execute_tool("get_prediction_markets", {
        "topic": "Bitcoin 100k", "limit": 5, "ticker": "BTC-USD",
    }))
    assert json.loads(result.split("\n", 1)[1])["status"] == "ok"
    assert ag.registry.calls[0][0] == "get_prediction_markets"
    assert "get_prediction_markets" in ag._tools_used


def test_prediction_tool_respects_an_explicit_do_not_use_instruction():
    ag = _agent("Analyze BTC, but do not use prediction markets")
    result = asyncio.run(ag._execute_tool("get_prediction_markets", {
        "topic": "Bitcoin price", "limit": 5,
    }))
    assert json.loads(result.split("\n", 1)[1])["status"] == "not_applicable"
    assert ag.registry.calls == []
    assert "get_prediction_markets" not in ag._tools_used


def test_generalist_session_context_never_persists_withheld_midpoint_or_stale_sentiment():
    ag = _agent("Build a full AAPL report", ctx_ticker="AAPL")
    ag.ctx.state = types.SimpleNamespace(
        financial_data=types.SimpleNamespace(
            key_metrics={"basic_info": {"currency": "USD"}},
        ),
        financial_model=types.SimpleNamespace(
            model_type="DCF",
            valuation_metrics={
                "current_price": 332.27,
                "fair_value": 167.18,
                "upside_vs_market": -0.4968,
                "perpetual_price": 154.04,
                "exit_multiple_price": 180.33,
                "point_estimate_withheld": True,
                "publication_withheld_reason": "external evidence conflicts",
            },
        ),
        news_analysis=types.SimpleNamespace(
            overall_sentiment="bearish",
            freshness={"status": "limited"},
            catalysts=[], risks=[],
        ),
        report=None,
    )

    results = ag._collect_analysis_results()

    valuation = results["valuation"]
    assert valuation["point_estimate_withheld"] is True
    assert valuation["range_low"] == 154.04
    assert valuation["range_high"] == 180.33
    assert "fair_value" not in valuation
    assert "upside_downside" not in valuation
    assert results["news_summary"]["freshness_status"] == "limited"
    assert "overall_sentiment" not in results["news_summary"]


def test_generalist_session_payload_marks_equal_method_outputs_as_one_estimate():
    ag = _agent("Build a full TSM report", ctx_ticker="TSM")
    ag.ctx.state = types.SimpleNamespace(
        financial_data=types.SimpleNamespace(
            key_metrics={"basic_info": {"currency": "TWD"}},
        ),
        financial_model=types.SimpleNamespace(
            model_type="DCF",
            valuation_metrics={
                "perpetual_price": 13245.003,
                "exit_multiple_price": 13245.004,
                "point_estimate_withheld": True,
            },
        ),
        news_analysis=None,
        report=None,
    )

    valuation = ag._collect_analysis_results()["valuation"]

    assert valuation["support_shape"] == "single_estimate"
    assert valuation["range_low"] == 13245.003
    assert valuation["range_high"] == 13245.004


def test_news_tool_payload_never_publishes_sentiment_without_fresh_coverage():
    from agents.tools.analysis_tools import _bounded_news_payload

    limited = types.SimpleNamespace(
        overall_sentiment="bearish",
        freshness={"status": "limited", "fresh_articles": 1},
    )
    fresh = types.SimpleNamespace(
        overall_sentiment="bearish",
        freshness={"status": "fresh", "fresh_articles": 8},
    )

    limited_payload = _bounded_news_payload(
        limited, sentiment_key="news_sentiment", freshness_key="news_freshness"
    )
    fresh_payload = _bounded_news_payload(
        fresh, sentiment_key="news_sentiment", freshness_key="news_freshness"
    )

    assert limited_payload["news_freshness"]["status"] == "limited"
    assert "news_sentiment" not in limited_payload
    assert fresh_payload["news_sentiment"] == "bearish"


def test_published_report_guard_corrects_conflicting_headline_claims():
    ag = _agent("summarize the report", ctx_ticker="PG")
    ag.ctx.state = types.SimpleNamespace(
        financial_data=types.SimpleNamespace(
            key_metrics={"basic_info": {"currency": "USD"}},
        ),
        financial_model=types.SimpleNamespace(
            valuation_metrics={
                "fair_value": 134.75,
                "point_estimate_withheld": False,
            },
        ),
        report=types.SimpleNamespace(content=(
            "## Investment Rating: HOLD\n\n"
            "**12-Month Price Target**: USD 142.00\n"
        )),
        news_analysis=None,
    )

    guarded = ag._guard_final_answer(
        "The report rating is SELL, the report's fair value is $167.67, "
        "and the report's 12-month price target is $190."
    )

    assert "investment rating HOLD" in guarded
    assert "model fair value $134.75 USD" in guarded
    assert "12-month price target USD 142.00" in guarded
    assert "167.67" not in guarded
    assert "190" not in guarded


def test_published_report_guard_leaves_nonconflicting_discussion_untouched():
    ag = _agent("summarize the report", ctx_ticker="PG")
    ag.ctx.state = types.SimpleNamespace(
        financial_data=types.SimpleNamespace(
            key_metrics={"basic_info": {"currency": "USD"}},
        ),
        financial_model=types.SimpleNamespace(
            valuation_metrics={
                "fair_value": 134.75,
                "point_estimate_withheld": False,
            },
        ),
        report=types.SimpleNamespace(content=(
            "## Investment Rating: HOLD\n\n"
            "**12-Month Price Target**: USD 142.00\n"
        )),
        news_analysis=None,
    )
    answer = (
        "The report rating is HOLD and the model's fair value is USD 134.75. "
        "Street analysts have a separate BUY consensus."
    )

    assert ag._guard_final_answer(answer) == answer


def test_read_report_rehydrates_withheld_boundary_for_a_fresh_process(
    tmp_path, monkeypatch,
):
    from agents.tools.analysis_tools import ReadReportTool

    base = tmp_path / "analysis"
    (base / "financials").mkdir(parents=True)
    (base / "models").mkdir()
    (base / "screened").mkdir()
    report = (
        "# AAPL Professional Analysis\n\n"
        "## Investment Rating: SELL\n\n"
        "**12-Month Price Target**: USD 269.67\n\n"
        "**Expected Return**: -18.8%\n\n"
        "The workbook audit midpoint is USD 167.67.\n"
    )
    (base / "AAPL_Professional_Analysis_Report.md").write_text(report)
    (base / "financials" / "financials_annual_modeling_latest.json").write_text(
        json.dumps({
            "company_data": {
                "basic_info": {"long_name": "Apple Inc.", "currency": "USD"},
                "market_data": {"current_price": 332.27},
            },
            "external_expectations": {
                "currency": "USD",
                "price_target": {
                    "mean": 335.72,
                    "return_vs_market": 0.01,
                    "analyst_count": 26,
                    "source": "benzinga",
                    "provider_as_of": "2026-09-12",
                    "qualified_for_corroboration": True,
                },
                "recommendations": {},
                "forward_estimates": [],
            },
        })
    )
    (base / "models" / "AAPL_financial_model_computed_values.json").write_text(
        json.dumps({
            "Summary": {"cells": {
                "(53, 2)": 619e9,
                "(55, 2)": 2.09,
            }},
            "_vynn": {
                "valuation_publication": {
                    "status": "ready",
                    "valuation_method": "dcf",
                    "point_estimate_withheld": True,
                    "withheld_reason": "market and analyst evidence conflicts",
                    "valuation_confidence": "wide",
                    "range_low": 154.04,
                    "range_high": 180.33,
                    "method_values_for_audit": {
                        "perpetual_dcf": 154.04,
                        "exit_multiple_dcf": 180.33,
                    },
                    "canonical_fair_value": None,
                    "canonical_upside_vs_market": None,
                    "model_value_for_audit": 167.67,
                    "comps_included_in_blended_value": False,
                },
                "model_inputs": {"revenue_growth_source": "historical_fallback"},
            },
        })
    )
    (base / "screened" / "screening_data.json").write_text(json.dumps({
        "freshness": {"status": "limited", "fresh_articles": 1},
        "analysis_summary": {"overall_sentiment": "bearish"},
    }))
    monkeypatch.setattr("path_utils.get_latest_analysis_path", lambda *_: base)
    ctx = types.SimpleNamespace(
        email="launch@example.com", state=None, ticker=None, company_name=None,
    )

    payload = json.loads(asyncio.run(ReadReportTool(ctx).execute("AAPL")))

    assert payload["publication"]["point_estimate_withheld"] is True
    assert payload["publication"]["supported_range_low"] == 154.04
    assert payload["publication"]["supported_range_high"] == 180.33
    assert payload["publication"]["rating"] == "NOT RATED"
    assert "fair_value" not in payload["publication"]
    assert payload["rating"] == "NOT RATED"
    assert "price_target_12m" not in payload
    assert "price_target_expected_return_pct" not in payload
    assert payload["news_freshness"]["status"] == "limited"
    assert ctx.state.financial_model.valuation_metrics["fair_value"] == 167.67

    ag = _agent("summarize the report", ctx_ticker="AAPL")
    ag.ctx = ctx
    guarded = ag._guard_final_answer(
        "The report is bearish and its fair value is USD 167.67."
    )
    assert guarded.startswith("AAPL is NOT RATED")
    assert "154.04–$180.33" in guarded
    assert "human-analyst mean target USD 335.72" in guarded
    assert "reverse DCF" in guarded
    assert "209.0% above the model" in guarded


class TestForcedTextTurns:
    def test_the_last_iteration_keeps_tools_defined_and_forbids_them(self):
        ag = _agent("x")
        provider = _Provider()
        asyncio.run(ag._text_only_turn([{"role": "user", "content": "x"}], provider, TOOLS))
        assert provider.calls[-1]["tools"] == TOOLS and provider.calls[-1]["tool_choice"] == "none"

    def test_the_prompt_tells_the_model_the_rule_and_its_exceptions(self):
        from agents.generalist_agent import SYSTEM_PROMPT
        assert "A request for a REPORT on a single listed company is a request to call `write_report`" in SYSTEM_PROMPT
        assert "a declined offer" in SYSTEM_PROMPT
        assert "use `get_fund`" in SYSTEM_PROMPT
        assert "NEVER call get_financials, build_model, compare_tickers, or write_report for it" in SYSTEM_PROMPT
        assert "NEVER call a coin cheap, expensive, undervalued" in SYSTEM_PROMPT
        assert "has no good/bad baseline by itself" in SYSTEM_PROMPT


class TestProviderRawShape:
    def test_openai_raw_has_no_tool_calls_key_for_a_text_turn(self):
        from llms import async_client as ac
        import inspect
        src = inspect.getsource(ac._call_openai_tools)
        assert 'if msg.tool_calls:' in src and 'raw_assistant["tool_calls"] = msg.tool_calls' in src
