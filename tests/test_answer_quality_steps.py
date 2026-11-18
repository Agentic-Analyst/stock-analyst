"""Three steps a blind review of twelve real questions asked for (17 Nov 2026).

1. "Should I buy X?" answered first: the fixed statement opens with its
   answer to the question asked.
2. The numbers checked: one more turn on the same transcript returns
   exact-match corrections, applied before the guard and the section checks.
3. One language per answer: English paragraphs in an answer to a Chinese,
   Japanese or Korean question are translated, and a translation is used
   only when it keeps every figure.
"""
import asyncio
import json
import os
import sys

import pytest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "src"))

from src.agents.generalist_agent import (  # noqa: E402
    _BUY_QUESTION, _NUMBER_CHECK_NOTE, apply_corrections, english_paragraph,
    parse_corrections, translation_keeps_facts,
)
from test_confidence_alert_surfaces import _flagged_state  # noqa: E402
from test_guarded_answer_keeps_analysis import (  # noqa: E402
    XOM_DRAFT_2, XOM_SECTION, _Provider, _chat_agent, _exxon_state, _published_state,
    _withheld_state,
)


# ---- 1. a direct answer -----------------------------------------------------------

@pytest.mark.parametrize("prompt", [
    "should i buy tesla today?", "Should we invest in NVDA now?", "Is Costco a good investment at today's price?",
    "is AAPL a good buy here", "good time to buy MSFT?", "is it worth buying PG", "特斯拉值得买吗？",
    "现在能买吗", "トヨタは買うべきですか？", "삼성전자 사야 할까요?",
])
def test_a_buy_question_is_recognised(prompt):
    assert _BUY_QUESTION.search(prompt)


@pytest.mark.parametrize("prompt", [
    "what is hansen technologies asx like?", "why did HOOD go up", "analyze this company",
    "any stocks you would recommend today?", "how would falling rates affect banks",
])
def test_other_questions_are_not(prompt):
    assert not _BUY_QUESTION.search(prompt)


def _short(prompt, state, ticker, draft):
    ag = _chat_agent(prompt, state, ticker)
    template = ag._guard_final_answer(draft)
    assert ag._guard_template == template
    return template, ag._with_short_answer(template)


def test_a_published_hold_answers_a_buy_question_first():
    template, out = _short("should I buy PG?", _published_state(), "PG",
                           "The report rating is SELL and the report's fair value is $167.67.")
    assert out == "**Short answer: not at today's price, on VYNN's numbers.**\n\n" + template


def test_a_low_confidence_view_says_so_in_the_first_line():
    template, out = _short("Should I buy META today?", _flagged_state(), "META", "The report rating is BUY.")
    assert out.startswith("**Short answer: no, on VYNN's numbers, but with low confidence.**\n\n")
    assert out.endswith(template)


def test_a_run_without_a_valuation_says_it_gives_no_call():
    _, out = _short("should i buy xom?", _exxon_state(), "XOM", XOM_DRAFT_2)
    assert out.startswith("**Short answer: VYNN gives no buy or sell call here, because it has no valuation")


def test_a_withheld_range_says_it_gives_no_call():
    _, out = _short("should i buy TEST?", _withheld_state(), "TEST", "Verdict: Buy at $167.67.")
    assert out.startswith("**Short answer: VYNN gives no buy or sell call here, because its valuation is a range")


@pytest.mark.parametrize("prompt", ["should I sell PG?", "should I buy or sell PG?", "summarize the report"])
def test_sell_and_other_questions_keep_the_statement_as_it_is(prompt):
    template, out = _short(prompt, _published_state(), "PG", "The report rating is SELL.")
    assert out == template


# ---- 2. the numbers check ---------------------------------------------------------

def test_corrections_are_read_from_the_reply_and_junk_is_ignored():
    reply = 'Here you go: [{"wrong": "40% above", "right": "22% above"}, {"wrong": 3}] done'
    assert parse_corrections(reply) == [{"wrong": "40% above", "right": "22% above"}]
    assert parse_corrections("[]") == []
    assert parse_corrections("NO") == []
    assert parse_corrections('{"wrong": "a", "right": "b"}') == []
    assert parse_corrections("[not json") == []


def test_a_correction_applies_only_where_its_text_occurs_exactly_once():
    text = "Up 12% on the day. Margin 20%. Margin 20%."
    out, applied = apply_corrections(text, [
        {"wrong": "Up 12%", "right": "Up 2.1%"},          # once: applied
        {"wrong": "Margin 20%", "right": "Margin 19%"},   # twice: ambiguous, skipped
        {"wrong": "Down 5%", "right": "Down 4%"},         # absent: skipped
    ])
    assert out == "Up 2.1% on the day. Margin 20%. Margin 20%."
    assert [fix["wrong"] for fix in applied] == ["Up 12%"]


ANSWER = ("Costco trades at $905.10, 40% above its 52-week low of $788.70. "
          "Its forward P/E of 48x is below the trailing 52x, which means growth is expected to slow.")
FIXES = [
    {"wrong": "40% above its 52-week low", "right": "about 14.8% above its 52-week low"},
    {"wrong": "which means growth is expected to slow", "right": "which means earnings are expected to grow"},
]


def _numbers_agent():
    ag = _chat_agent("Is Costco a good investment at today's price?", None, "COST")
    ag._tools_used = {"get_prices"}
    return ag


def test_the_check_runs_on_the_same_transcript_and_applies_its_fixes():
    ag = _numbers_agent()
    provider = _Provider(json.dumps(FIXES))
    transcript = [{"role": "user", "content": "q"}, {"role": "assistant", "content": "tools"},
                  {"role": "user", "content": "tool results"}]
    out = asyncio.run(ag._check_numbers(transcript, provider, ANSWER, [{"type": "function"}]))
    assert "about 14.8% above its 52-week low" in out and "earnings are expected to grow" in out
    sent = provider.calls[0]["messages"]
    assert sent[:3] == transcript
    assert sent[3] == {"role": "assistant", "content": ANSWER}
    assert sent[4] == {"role": "user", "content": _NUMBER_CHECK_NOTE}
    # A text-only turn: tools stay defined, none may be called.
    assert provider.calls[0]["tool_choice"] == "none"
    assert any("2 correction(s) applied of 2 proposed" in line for line in ag.logs)


def test_no_check_without_figures_or_without_tool_results():
    ag = _numbers_agent()
    provider = _Provider()
    assert asyncio.run(ag._check_numbers([], provider, "Costco is a warehouse club.", None)) == \
        "Costco is a warehouse club."
    ag._tools_used = set()
    assert asyncio.run(ag._check_numbers([], provider, ANSWER, None)) == ANSWER
    assert provider.calls == []


def test_a_failed_check_keeps_the_text():
    ag = _numbers_agent()
    out = asyncio.run(ag._check_numbers([], _Provider(RuntimeError("throttled")), ANSWER, None))
    assert out == ANSWER and any("Number check failed" in line for line in ag.logs)


def test_an_accepted_draft_is_checked_and_guarded_again():
    ag = _chat_agent("how is COST doing?", None, None)
    ag._tools_used = {"get_prices"}
    guarded = ag._guard_final_answer(ANSWER)
    assert ag._guard_template is None
    out = asyncio.run(ag._checked_draft([], _Provider(json.dumps(FIXES)), ANSWER, guarded, None))
    assert "about 14.8% above" in out and "40% above" not in out


def test_the_analysis_section_is_checked_before_both_section_checks():
    ag = _chat_agent("should i buy/hold xom?", _exxon_state(), "XOM")
    ag._tools_used = {"get_prices", "get_global_news"}
    template = ag._guard_final_answer(XOM_DRAFT_2)
    wrong = "160.59"
    assert wrong in XOM_SECTION
    fix = [{"wrong": f"${wrong}", "right": "$160.95"}] if f"${wrong}" in XOM_SECTION else \
        [{"wrong": wrong, "right": "160.95"}]
    provider = _Provider(XOM_SECTION, json.dumps(fix), "NO")
    out = asyncio.run(ag._add_analysis([{"role": "user", "content": ag.user_prompt}], provider, template,
                                       [{"type": "function"}]))
    assert "160.95" in out and "160.59" not in out
    # The yes/no section check read the corrected section.
    assert "160.95" in provider.calls[2]["messages"][0]["content"]


# ---- 3. one language per answer ---------------------------------------------------

ENGLISH = ("000002.SZ: No valuation model was produced in this run, so there is no fair value "
           "to state.")
BLOCK = ("What analysts think, for comparison (not VYNN's view):\n"
         "- Average price target: ¥3.34 from 8 analysts, 13.5% above today's price (Yahoo Finance).\n"
         "- Their targets range from ¥1.85 to ¥8.30 (middle: ¥2.90).")
BLOCK_ZH = ("分析师观点（仅供对比，并非 VYNN 的观点）：\n"
            "- 平均目标价：¥3.34，来自 8 位分析师，比当前股价高 13.5%（Yahoo Finance）。\n"
            "- 目标价区间为 ¥1.85 至 ¥8.30（中位数：¥2.90）。")
ENGLISH_ZH = "000002.SZ：本次运行没有生成估值模型，因此没有可给出的公允价值。"


def test_a_translation_must_keep_every_figure():
    assert translation_keeps_facts(BLOCK, BLOCK_ZH, "Chinese")
    assert not translation_keeps_facts(BLOCK, BLOCK_ZH.replace("13.5%", "约13%"), "Chinese")
    assert not translation_keeps_facts(BLOCK, BLOCK, "Chinese")          # not translated at all
    assert not translation_keeps_facts(BLOCK, BLOCK_ZH + "目标价 99 元", "Chinese")   # a new figure
    # A month number from a translated date is the one addition allowed.
    assert translation_keeps_facts("Shares fell on Nov 17 by 4.2%.", "股价在11月17日下跌4.2%。", "Chinese")


def test_a_translated_rating_must_still_say_the_rating():
    source = "VYNN's report rates TSLA STRONG SELL, with a model fair value of $20.25 USD."
    assert translation_keeps_facts(source, "VYNN 的报告给予 TSLA 强烈卖出评级，模型公允价值为 $20.25 USD。", "Chinese")
    assert not translation_keeps_facts(source, "VYNN 的报告给予 TSLA 买入评级，模型公允价值为 $20.25 USD。", "Chinese")


def test_paragraphs_in_a_cjk_answer_are_found_by_script():
    assert english_paragraph(ENGLISH) and english_paragraph(BLOCK)
    assert not english_paragraph(ENGLISH_ZH) and not english_paragraph("000002.SZ")


def _zh_agent():
    ag = _chat_agent("分析万科股票", None, "000002.SZ")
    ag._local_prefix = ENGLISH_ZH
    return ag


def test_english_paragraphs_in_a_chinese_answer_are_translated_and_the_repeat_dropped():
    ag = _zh_agent()
    answer = "\n\n".join([ENGLISH_ZH, ENGLISH, "万科近期股价……", BLOCK])
    provider = _Provider(f"<<1>>\n{ENGLISH_ZH}\n\n<<2>>\n{BLOCK_ZH}")
    out = asyncio.run(ag._localize(provider, answer))
    assert out == "\n\n".join([ENGLISH_ZH, "万科近期股价……", BLOCK_ZH])
    assert "No valuation model" not in out and "What analysts think" not in out
    assert "Chinese" in provider.calls[0]["messages"][0]["content"]


def test_an_unfaithful_translation_keeps_the_english_and_the_chinese_line():
    ag = _zh_agent()
    answer = "\n\n".join([ENGLISH_ZH, ENGLISH, BLOCK])
    provider = _Provider(f"<<1>>\n{ENGLISH_ZH}\n\n<<2>>\n{BLOCK_ZH.replace('13.5%', '15%')}")
    out = asyncio.run(ag._localize(provider, answer))
    assert out == "\n\n".join([ENGLISH_ZH, ENGLISH_ZH, BLOCK])


def test_translations_made_alongside_the_analysis_are_reused():
    ag = _zh_agent()
    provider = _Provider(f"<<1>>\n{BLOCK_ZH}")
    asyncio.run(ag._translate(provider, [BLOCK]))
    out = asyncio.run(ag._localize(provider, "万科近期股价……\n\n" + BLOCK))
    assert out == "万科近期股价……\n\n" + BLOCK_ZH
    assert len(provider.calls) == 1


def test_english_questions_are_left_alone():
    ag = _chat_agent("analyze vanke", None, "000002.SZ")
    provider = _Provider()
    answer = ENGLISH + "\n\n" + BLOCK
    assert asyncio.run(ag._localize(provider, answer)) == answer
    assert provider.calls == []


def test_a_failed_translation_keeps_the_answer():
    ag = _zh_agent()
    answer = ENGLISH_ZH + "\n\n" + BLOCK
    out = asyncio.run(ag._localize(_Provider(RuntimeError("down")), answer))
    assert out == answer


# ---- European languages ----------------------------------------------------------

@pytest.mark.parametrize("prompt,language", [
    ("Is het slim om nu in te stappen in Applovin?", "Dutch"),
    ("Target ASTS, wat wordt het wellicht waard?", "Dutch"),
    ("Wat zijn de verwachtingen voor komend jaar?", "Dutch"),
    ("Nederlands graag, ik wil alles over ASTS weten.", "Dutch"),
    ("Soll ich die Aktie von Tesla jetzt kaufen?", "German"),
    ("Est-ce que je dois acheter l'action LVMH?", "French"),
    ("¿Debo comprar acciones de Tesla hoy?", "Spanish"),
    ("Conviene comprare azioni Ferrari oggi?", "Italian"),
])
def test_a_european_question_is_recognised(prompt, language):
    from src.agents.generalist_agent import answer_language, latin_language
    assert latin_language(prompt) == language
    assert answer_language(prompt) == language


@pytest.mark.parametrize("prompt", [
    "should i buy tesla today?", "what is the price of ASML today", "analyze this company",
    "any stocks you would recommend today?", "SNDK", "netease", "how would falling rates affect banks",
    "is the die-hard bull case for NVDA still valid?", "分析万科股票",
])
def test_english_and_cjk_questions_are_not_taken_for_european(prompt):
    from src.agents.generalist_agent import latin_language
    assert latin_language(prompt) == ""


def test_the_fixed_text_of_a_dutch_answer_is_translated():
    ag = _chat_agent("Is het slim om nu in te stappen in Applovin?", None, "APP")
    english = "**Short answer: no, on VYNN's numbers, but with low confidence.**"
    dutch_block = "Analisten: gemiddeld koersdoel $412,48 van 40 analisten."
    answer = "\n\n".join([english, "De koers van AppLovin is dit jaar sterk gestegen en het aandeel is volatiel.",
                          dutch_block])
    provider = _Provider("<<1>>\n**Kort antwoord: nee, volgens de cijfers van VYNN, maar met weinig vertrouwen.**")
    out = asyncio.run(ag._localize(provider, answer))
    assert out.startswith("**Kort antwoord: nee")
    # Only the English paragraph was sent; the Dutch ones were left alone.
    sent = provider.calls[0]["messages"][0]["content"]
    assert "Short answer" in sent and "De koers" not in sent and "Dutch" in sent


def test_a_dutch_closing_question_is_not_taken_for_english():
    from src.agents.generalist_agent import english_paragraph
    dutch = ("Zal ik de bull/base/bear-scenario's uitwerken of AppLovin naast peers zoals Unity of "
             "AppLovin's concurrenten in ad-tech zetten?")
    assert not english_paragraph(dutch, "Dutch")
    assert english_paragraph("**Short answer: no, on VYNN's numbers, but with low confidence.**", "Dutch")


def test_a_correction_never_takes_a_caution_away():
    # Kioxia, 18 Nov: the split warning was "corrected" into a weaker sentence.
    from src.agents.generalist_agent import apply_corrections
    text = ("期間高値は37,503円で、そこから-78.6%です。ただし時価総額と株価から逆算した株数が想定とずれています。"
            "株式分割などで価格系列が調整されていない可能性があるため、この下落率は参考程度にしてください。")
    fix = {"wrong": "ただし時価総額と株価から逆算した株数が想定とずれています。株式分割などで価格系列が調整されていない"
                    "可能性があるため、この下落率は参考程度にしてください。",
           "right": "ただし、この高値がいつ付いたかは取得データから確認できていません。"}
    out, applied = apply_corrections(text, [fix])
    assert applied == [] and out == text
    # A correction of a figure inside a cautious sentence still applies.
    text2 = "The price may be 12% below the high of $5.90."
    out2, applied2 = apply_corrections(text2, [{"wrong": "12% below", "right": "39% below"}])
    assert applied2 and "39% below" in out2
    eng = "The high may come from a price series not adjusted for a split, so check it."
    assert apply_corrections(eng, [{"wrong": eng, "right": "The high's date is unknown."}])[1] == []


def test_a_wrong_month_named_may_can_still_be_corrected():
    from src.agents.generalist_agent import apply_corrections
    out, applied = apply_corrections("The results came in May 2025.", [{"wrong": "in May 2025", "right": "in June 2025"}])
    assert applied and out == "The results came in June 2025."


def test_the_local_position_line_goes_when_it_is_second(monkeypatch):
    # A safeguard review: with the short answer first, the Chinese line was kept twice.
    import types as _types
    from src.agents.generalist_agent import GeneralistAgent
    ag = GeneralistAgent.__new__(GeneralistAgent)
    ag.user_prompt = "万科可以买吗?"
    ag._local_prefix = "万科:不给出买卖判断。"
    ag._translations = {"**Short answer: VYNN gives no buy or sell call here.**": "**简短回答:VYNN 在这里不给出买卖判断。**",
                        "000002.SZ: the model is a scenario.": "000002.SZ:模型仅为情景。"}

    async def _no_call(provider, paragraphs):
        return None

    ag._translate = _no_call
    text = ("**Short answer: VYNN gives no buy or sell call here.**\n\n万科:不给出买卖判断。\n\n"
            "000002.SZ: the model is a scenario.")
    out = asyncio.run(ag._localize(None, text))
    assert out == "**简短回答:VYNN 在这里不给出买卖判断。**\n\n000002.SZ:模型仅为情景。"
