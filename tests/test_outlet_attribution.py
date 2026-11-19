"""An answer names only news outlets its evidence mentions (19 Nov 2026).

The real answers from that night are the first test: both name only outlets
in their data. Hansen's "Reuters-sourced headline" looked invented, but the
TradingView item's address is tradingview.com/news/reuters.com,...: a Reuters
story. The evidence is read case-insensitively, web addresses included.
"""
import json
import pathlib

import pytest

from src.answer_evidence import unsourced_outlets, without_unsourced_outlets

REAL = json.loads((pathlib.Path(__file__).parent / "fixtures" / "outlet_attribution_2026_11_19.json").read_text())


@pytest.mark.parametrize("ticker", ["HSN.AX", "HOOD"])
def test_the_real_answers_are_left_alone(ticker):
    case = REAL[ticker]
    text, removed = without_unsourced_outlets(case["answer"], case["tool_result"])
    assert removed == [] and text == case["answer"]


EVIDENCE = '{"source": "Benzinga", "title": "Robinhood Stock Plunges", "url": "https://www.wsj.com/articles/x"}'


@pytest.mark.parametrize("answer, expected", [
    ("A Reuters-sourced headline said revenue would grow in FY28.",
     "A headline said revenue would grow in FY28."),
    ("The stock fell 10% on Nov 5 (Benzinga, Reuters).", "The stock fell 10% on Nov 5 (Benzinga)."),
    ("The stock fell 10% on Nov 5 (Reuters).", "The stock fell 10% on Nov 5."),
    ("Shares fell 5%, according to Bloomberg.", "Shares fell 5%, according to reports."),
    ("According to CNBC, shares fell after the call.", "According to reports, shares fell after the call."),
    ("Shares fell 4% per the Financial Times.", "Shares fell 4% according to reports."),
    ("Margins held up, and a Bloomberg report said demand slowed.",
     "Margins held up, and a report said demand slowed."),
    ("An AFR article said the deal was close.", "An article said the deal was close."),
    # The re-check's cases: a thousands comma and the wording inside brackets.
    ("The index fell (down 1,234 points; Reuters).", "The index fell (down 1,234 points)."),
    ("Both fell (revenue and EBIT down, Reuters).", "Both fell (revenue and EBIT down)."),
    ("(Reuters) Hansen fell.", "Hansen fell."),
    ("It fell (Reuters) and recovered.", "It fell and recovered."),
])
def test_an_unsupported_attribution_is_made_general_and_the_claim_kept(answer, expected):
    text, changed = without_unsourced_outlets(answer, EVIDENCE)
    assert text == expected and changed


@pytest.mark.parametrize("answer", [
    # The review's cases: a name used as a name, never as an attribution.
    "FactSet's main rival is Bloomberg, whose terminal dominates trading desks.",
    "- **Peers**: Thomson Reuters (TRI) and Wolters Kluwer trade at 30x earnings.",
    "It ranks 45th on the Forbes Global 2000 list.",
    "Zacks Rank #3 (Hold) and a consensus target of $52.",
    "AGG tracks the Bloomberg U.S. Aggregate Bond Index, with a 0.03% fee.",
    "1. Reuters: the CEO resigned.",
    "| Nov 12 | Reuters | Hansen expects growth. |",
    "Michael Bloomberg said the city would back it.",
    "Reuters reported a recall.",
    "Prix : 45 € (Benzinga).",
    "Data via Bloomberg terminal show it.",
    "According to Bloomberg Intelligence, demand is soft.",
    "It sits per the Forbes 400 list.",
    "That is according to Zacks consensus estimates.",
])
def test_a_name_that_is_not_an_attribution_form_is_left_alone(answer):
    text, changed = without_unsourced_outlets(answer, EVIDENCE)
    assert text == answer and changed == []


def test_outlets_in_the_evidence_or_its_addresses_are_kept():
    # wsj.com in a link supports The Wall Street Journal; Benzinga is a source.
    answer = "The Wall Street Journal reported the deal (Benzinga)."
    assert unsourced_outlets(answer, EVIDENCE) == []


def test_a_company_named_like_an_outlet_is_not_touched_when_the_data_names_it():
    answer = "Thomson Reuters rose 2% after its results."
    assert unsourced_outlets(answer, '{"name": "Thomson Reuters Corporation"}') == []


def _messages():
    return [
        {"role": "system", "content": "Name the outlets (Reuters, Bloomberg)."},
        {"role": "user", "content": "why is it down? Earlier answer: CNBC covered the launch."},
        {"role": "assistant", "content": [{"type": "text", "text": "It fell (Reuters)."}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "1", "content": EVIDENCE}]},
    ]


def _agent(audits):
    from types import SimpleNamespace
    return SimpleNamespace(_audit=audits.append, _log=lambda m: None)


def test_the_hook_reads_tool_results_and_the_question_not_the_prompt_or_the_model():
    from src.agents.generalist_agent import GeneralistAgent
    audits = []
    out = GeneralistAgent._outlets_checked(
        _agent(audits), "It fell 10% (Benzinga, Reuters). CNBC covered the launch.", _messages())
    assert out == "It fell 10% (Benzinga). CNBC covered the launch."
    assert audits and "Reuters" in audits[0]


def test_a_report_run_after_the_model_s_turns_counts_as_evidence():
    # The review's case: write_report run by the harness; its result arrives
    # in a later user-role note and carries the analysts' source.
    from src.agents.generalist_agent import GeneralistAgent
    messages = _messages() + [
        {"role": "assistant", "content": "Draft (Zacks)."},
        {"role": "user", "content": "[HARNESS NOTE] write_report result: {\"source\": \"Zacks\"}"},
    ]
    answer = "Average target $52 from 9 analysts (Zacks)."
    assert GeneralistAgent._outlets_checked(_agent([]), answer, messages) == answer
