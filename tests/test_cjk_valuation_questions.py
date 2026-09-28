"""A valuation question asked in Chinese gets the same publication guard as English.

Found 2026-09-28 while fixing the thin XOM answer: "埃克森美孚值得买入还是持有？"
was not recognised as a valuation question (the pattern was English only), so
the guard never ran and the draft below was published as written: a hold call,
and no NOT RATED, for a company the engine declines to value. The draft is
verbatim gpt-6-luna output from the production image.
"""
import asyncio
import os
import sys

import pytest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "src"))

from src.agents.generalist_agent import _CJK_VALUATION_QUESTION  # noqa: E402
from src.summary_evidence import plain_refusal_note_zh  # noqa: E402
from test_guarded_answer_keeps_analysis import (  # noqa: E402
    XOM_SECTION, _Provider, _chat_agent, _exxon_state, _published_state, _withheld_state,
)

ZH_PROMPT = "埃克森美孚值得买入还是持有？"
ZH_DRAFT = (
    "**简要判断：已有持仓可继续持有；准备新买入则更适合分批，而不是在大涨后一次性追高。** "
    "埃克森美孚（XOM）业务质量和项目储备较强，但盈利仍受油气价格与炼油利润影响，股价也已明显上涨。\n\n"
    "截至最新行情，XOM 报 **160.59 美元**，近一年上涨约 **41%**。技术面上，股价略高于50日均线"
    "（159.01美元）且高于200日均线（146.49美元），RSI为52。\n\n"
    "**怎么做更合适**\n"
    "- **已有持仓：**若持仓比例适中、投资期限较长，可考虑继续持有。\n"
    "- **准备买入：**可以分批建仓，并关注油价、炼油利润和公司后续现金流表现。"
)
ZH_SECTION = (
    "XOM 最新报价为 160.59 美元，过去一年上涨约 41%；股价高于50日均线（159.01美元）和200日均线"
    "（146.49美元），RSI 为 52，MACD 低于信号线。\n\n"
    "近期报道提到过去12个月自由现金流约 306 亿美元，圭亚那和二叠纪盆地项目支撑中长期产量；"
    "主要风险包括油价与炼油利润回落、Joliet 炼厂运营问题，以及 Baytown 蓝氢项目暂停。"
)


@pytest.mark.parametrize("prompt", [
    ZH_PROMPT, "特斯拉现在能买吗？", "分析一下英伟达", "苹果的估值怎么样？", "微软的目标价是多少",
    "要不要买入阿里巴巴", "トヨタは買うべきですか？", "삼성전자 매수해야 하나요?",
])
def test_a_cjk_valuation_question_is_recognised(prompt):
    assert _CJK_VALUATION_QUESTION.search(prompt)


@pytest.mark.parametrize("prompt", ["特斯拉的最新新闻是什么？", "比特币价格多少？", "今天美股收盘怎么样？"])
def test_a_cjk_question_about_something_else_is_not(prompt):
    assert not _CJK_VALUATION_QUESTION.search(prompt)


def test_the_reported_chinese_question_is_guarded_now():
    ag = _chat_agent(ZH_PROMPT, _exxon_state(), "XOM")
    out = ag._guard_final_answer(ZH_DRAFT)
    assert out != ZH_DRAFT and "继续持有" not in out
    assert out.startswith("XOM: NOT RATED.")
    assert ag._guard_template == out and ag._guard_kind == "refused:commodity_cycle"


def _analysis(ag, provider, draft):
    template = ag._guard_final_answer(draft)
    out = asyncio.run(ag._add_analysis([{"role": "user", "content": ag.user_prompt}], provider, template,
                                       [{"type": "function"}]))
    return template, out


def test_a_chinese_question_reads_its_position_in_chinese_first():
    ag = _chat_agent(ZH_PROMPT, _exxon_state(), "XOM")
    template, out = _analysis(ag, _Provider(ZH_SECTION, "NO"), ZH_DRAFT)
    assert out.startswith("XOM：未评级。不发布评级或公允价值：其现金流随大宗商品价格波动")
    assert out.index("未评级") < out.index("XOM: NOT RATED") < out.index("自由现金流") < out.index("The Street's view")
    assert "继续持有" not in out


def test_a_chinese_section_with_a_call_is_stopped_and_the_position_still_reads_in_chinese():
    ag = _chat_agent(ZH_PROMPT, _exxon_state(), "XOM")
    template, out = _analysis(ag, _Provider(ZH_SECTION + "\n\n长期投资者可以考虑继续持有。", "YES"), ZH_DRAFT)
    assert out == "XOM：未评级。不发布评级或公允价值：其现金流随大宗商品价格波动，基于当前价格的现金流模型更像是押注商品价格，而不是估值。\n\n" + template


def test_an_english_question_gets_no_chinese_line():
    ag = _chat_agent("should i buy/hold xom?", _exxon_state(), "XOM")
    template, out = _analysis(ag, _Provider(XOM_SECTION, "NO"), "My take: hold.")
    assert out.startswith("XOM: NOT RATED.") and "未评级" not in out


def test_withheld_and_published_positions_read_in_chinese():
    ag = _chat_agent("给我TEST的看涨和看跌理由，并给出结论", _withheld_state(), "TEST")
    _, out = _analysis(ag, _Provider("ignored"), "结论：买入。")
    assert out.startswith("TEST：未评级。模型估值未能得到独立证据的印证")

    ag = _chat_agent("宝洁的报告评级是什么？分析一下", _published_state(), "PG")
    _, out = _analysis(ag, _Provider("ignored"), "报告评级为卖出，公允价值 167.67 美元。")
    assert out.startswith("PG：VYNN 评级为持有。")


@pytest.mark.parametrize("kind", ["commodity_cycle", "reit", "insurance", "fund", "crypto",
                                  "unsupported_asset", "bank_valuation_input_gap"])
def test_every_refusal_reads_in_chinese(kind):
    assert plain_refusal_note_zh(kind).startswith("不发布评级或公允价值：")


def test_an_unknown_refusal_still_reads_in_chinese():
    assert plain_refusal_note_zh("new_kind") == "不发布评级或公允价值，因为该标的超出估值方法的适用范围。"
    assert plain_refusal_note_zh(None) == "不发布评级或公允价值，因为本次运行没有生成估值模型。"


def test_the_section_is_asked_for_in_the_language_named():
    ag = _chat_agent(ZH_PROMPT, _exxon_state(), "XOM")
    provider = _Provider(ZH_SECTION, "NO")
    _analysis(ag, provider, ZH_DRAFT)
    assert "Write it in Chinese." in provider.calls[0]["messages"][-1]["content"]
    ag = _chat_agent("should i buy/hold xom?", _exxon_state(), "XOM")
    provider = _Provider(XOM_SECTION, "NO")
    _analysis(ag, provider, "My take: hold.")
    assert "Write it in the language the user's message is written in (English for an English message)." in \
        provider.calls[0]["messages"][-1]["content"]


@pytest.mark.parametrize("text", [
    "当前材料没有完整财务报表或估值模型，因此无法据此量化盈利质量、现金流趋势或内在价值。",
    "报告未给出目标价。",
    "下行空间主要来自油价回落的风险。",
])
def test_a_chinese_value_word_without_a_figure_is_not_a_claim(text):
    from src.answer_evidence import makes_claim
    assert not makes_claim(text)


@pytest.mark.parametrize("text", ["目标价 $200", "合理估值约为180美元", "上行空间约20%", "内在价值约为 180 美元"])
def test_a_chinese_value_word_with_a_figure_is_a_claim(text):
    from src.answer_evidence import makes_claim
    assert makes_claim(text)
