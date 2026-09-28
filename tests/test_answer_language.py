"""An answer must be in the language the user wrote in.

On 2026-09-26 a user typed "NSE stock analysis" and the chat replied in
Chinese ("你是想分析哪只在 NSE 上市的股票？"); the follow-up "future of
g.co/sc" was answered in Chinese too. Nothing compared the answer's language
with the message's.
"""
import asyncio
import os
import sys
import types

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "src"))

from agents.generalist_agent import (  # noqa: E402
    SYSTEM_PROMPT, GeneralistAgent, answer_language_mismatch, prompt_language,
    report_language,
)

CHINESE = "你是想分析哪只在 NSE 上市的股票？把公司名或代码发我就行，比如 Reliance、TCS、HDFC Bank。"
ENGLISH = "Which NSE-listed stock do you want analysed? Send me a name or ticker, e.g. Reliance, TCS, HDFC Bank."


def test_the_reported_case_is_a_mismatch():
    assert answer_language_mismatch("NSE stock analysis", CHINESE)
    assert answer_language_mismatch("future of g.co/sc", CHINESE)
    assert not answer_language_mismatch("NSE stock analysis", ENGLISH)


def test_a_cjk_question_answered_in_english_is_a_mismatch_too():
    assert answer_language_mismatch("分析英伟达", ENGLISH)
    assert not answer_language_mismatch("分析英伟达", CHINESE)


def test_a_company_name_in_another_script_is_not_a_language():
    # An English question naming a Chinese company, answered in English with
    # the name kept: no mismatch, and no Chinese report either.
    assert not answer_language_mismatch("analyze 腾讯 for me", "Tencent (腾讯, 0700.HK) trades at HK$580; revenue grew 8%.")
    assert prompt_language("analyze 腾讯 for me") == ""
    assert report_language("analyze 腾讯 for me") == ""


def test_short_or_numeric_answers_never_trigger_a_rewrite():
    assert not answer_language_mismatch("NSE stock analysis", "")
    assert not answer_language_mismatch("NSE stock analysis", "AAPL: $250.10 (+1.2%)")
    assert not answer_language_mismatch("分析英伟达", "NVDA $225.07")   # too short to judge


def test_report_language_needs_a_cjk_request_or_an_explicit_ask():
    assert report_language("分析英伟达并用中文写报告") == "Chinese"
    assert report_language("トヨタのレポートを作成してください") == "Japanese"
    assert report_language("삼성전자 보고서 작성해줘") == "Korean"
    assert report_language("analyze NVDA, report in Chinese") == "Chinese"
    assert report_language("write a report on Toyota in Japanese") == "Japanese"
    assert report_language("write a report on NVDA") == ""
    assert report_language("NSE stock analysis") == ""


def test_the_prompt_defaults_to_english():
    assert "If you cannot tell, answer in English" in SYSTEM_PROMPT


class _Provider:
    def __init__(self, texts):
        self.texts, self.calls = list(texts), []
        self.is_openai = True

    async def call_with_tools(self, messages, tools, temperature=0.4, *, tool_choice=None):
        self.calls.append({"messages": list(messages), "tool_choice": tool_choice})
        if isinstance(self.texts[0], Exception):
            raise self.texts.pop(0)
        text = self.texts.pop(0)
        return types.SimpleNamespace(text=text, cost=0.001, raw={"role": "assistant", "content": text},
                                     has_tool_calls=False, tool_calls=[])


def _agent(prompt):
    ag = GeneralistAgent.__new__(GeneralistAgent)
    ag.user_prompt = prompt
    ag.conversation_context = None
    ag._tools_used = set()
    ag.total_cost = 0.0
    ag.logs = []
    ag._log = ag.logs.append
    return ag


def _ensure(ag, provider, draft):
    messages = [{"role": "user", "content": ag.user_prompt}]
    return asyncio.run(ag._ensure_answer_language(messages, provider, draft, [{"type": "function"}])), messages


def test_a_wrong_language_answer_is_rewritten_once_with_the_draft_in_view():
    ag = _agent("NSE stock analysis")
    provider = _Provider([ENGLISH])
    out, messages = _ensure(ag, provider, CHINESE)
    assert out == ENGLISH
    assert len(provider.calls) == 1
    sent = provider.calls[0]["messages"]
    assert sent[-2] == {"role": "assistant", "content": CHINESE}
    assert "Rewrite it in the language the user's message is written in" in sent[-1]["content"]
    assert provider.calls[0]["tool_choice"] == "none"
    assert messages == [{"role": "user", "content": "NSE stock analysis"}]   # transcript untouched
    assert ag.total_cost == 0.001
    assert any("rewriting it" in line for line in ag.logs)


def test_a_cjk_question_names_its_language_in_the_rewrite():
    ag = _agent("分析英伟达")
    provider = _Provider([CHINESE])
    out, _ = _ensure(ag, provider, ENGLISH + " More words about NVIDIA's data centre growth.")
    assert out == CHINESE
    assert "Rewrite it in Chinese" in provider.calls[0]["messages"][-1]["content"]


def test_an_answer_in_the_right_language_costs_nothing():
    ag = _agent("NSE stock analysis")
    provider = _Provider([ENGLISH])
    out, _ = _ensure(ag, provider, ENGLISH)
    assert out == ENGLISH and provider.calls == []


def test_a_rewrite_that_is_still_wrong_keeps_the_draft():
    ag = _agent("NSE stock analysis")
    provider = _Provider([CHINESE])
    out, _ = _ensure(ag, provider, CHINESE)
    assert out == CHINESE
    assert any("still not in the user's language" in line for line in ag.logs)


def test_a_failed_rewrite_keeps_the_draft():
    ag = _agent("NSE stock analysis")
    provider = _Provider([RuntimeError("provider down")])
    out, _ = _ensure(ag, provider, CHINESE)
    assert out == CHINESE
    assert any("Could not rewrite" in line for line in ag.logs)


def test_the_language_check_runs_after_the_report_step_and_before_the_guard():
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] / "src" / "agents" / "generalist_agent.py").read_text()
    report = source.index("final_text = await self._ensure_report_if_requested(")
    language = source.index("final_text = await self._ensure_answer_language(", report)
    guard = source.index("guarded = self._guard_final_answer(final_text)", language)
    analysis = source.index("final_text = await self._add_analysis(", guard)
    assert report < language < guard < analysis
