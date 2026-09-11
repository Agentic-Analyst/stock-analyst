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


class TestProviderRawShape:
    def test_openai_raw_has_no_tool_calls_key_for_a_text_turn(self):
        from llms import async_client as ac
        import inspect
        src = inspect.getsource(ac._call_openai_tools)
        assert 'if msg.tool_calls:' in src and 'raw_assistant["tool_calls"] = msg.tool_calls' in src
