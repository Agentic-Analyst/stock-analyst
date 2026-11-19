"""Internal tool names never reach the reader (full-stack run, 19 Nov 2026).

"I can run `explain_price_move` over a 1-year window to find what drove the
drop" offered a tool by its internal name.
"""
import pytest

from src.answer_evidence import plain_tool_names


@pytest.mark.parametrize("answer, expected", [
    ("I can run `explain_price_move` over a 1-year window to find what drove the drop.",
     "I can run a breakdown of the price move over a 1-year window to find what drove the drop."),
    ("Want me to call build_model next?", "Want me to call the valuation model next?"),
    ("I can use `write_report()` for that.", "I can use the full report for that."),
    # The review's cases: the article and "tool" go with the name.
    ("I can run the `explain_price_move` tool next.", "I can run a breakdown of the price move next."),
    ("Using the get_financials tool, I found it.", "Using the financial data, I found it."),
    ("The `build_model` function is ready.", "The valuation model is ready."),
])
def test_tool_names_become_plain_words(answer, expected):
    text, replaced = plain_tool_names(answer)
    assert text == expected and replaced


@pytest.mark.parametrize("answer", [
    "Its build model is sound.",                       # ordinary words
    "See https://example.com/get_prices/today.",       # inside an address
    "The my_build_model_v2 file.",                     # part of a longer name
])
def test_ordinary_text_is_left_alone(answer):
    assert plain_tool_names(answer) == (answer, [])


def test_a_registered_tool_without_words_gets_its_name_spelled_out():
    text, replaced = plain_tool_names("Try `scan_dividends`.", {"scan_dividends"})
    assert text == "Try scan dividends." and replaced == ["scan_dividends"]


def test_the_hook_uses_the_registry_and_logs_privately():
    from types import SimpleNamespace
    from src.agents.generalist_agent import GeneralistAgent
    audits = []
    agent = SimpleNamespace(registry=SimpleNamespace(_tools={"explain_price_move": object()}),
                            user_prompt="why is it down?", _audit=audits.append, _log=lambda m: None)
    out = GeneralistAgent._tool_names_plain(agent, "I can run `explain_price_move`.")
    assert out == "I can run a breakdown of the price move." and "explain_price_move" in audits[0]


def test_an_answer_in_another_language_is_left_alone():
    # The review's case: English words would sit inside a Chinese sentence.
    from types import SimpleNamespace
    from src.agents.generalist_agent import GeneralistAgent
    agent = SimpleNamespace(registry=None, user_prompt="为什么下跌？", _audit=lambda m: None, _log=lambda m: None)
    answer = "需要我运行 `explain_price_move` 吗"
    assert GeneralistAgent._tool_names_plain(agent, answer) == answer
