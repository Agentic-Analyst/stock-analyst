"""Picks and comparisons hold every company to its own publication boundary.

Reported 18 Nov 2026 (Sonnet re-check): "Any stocks you would recommend
today?" modelled Alphabet, Meta and JPMorgan. Alphabet's and Meta's models
withheld a single fair value (cash-flow ranges only); JPMorgan's published one.
The guard reads one state, the last company modelled, so it held only
JPMorgan to its rules, and the answer called Alphabet and Meta cheap, quoted
+64% from their withheld ranges and suggested scaling in. The night before, the
same question ended on Verizon (withheld) and recommended nothing.
"""
import asyncio
import os
import sys
import types
from types import SimpleNamespace

import pytest

_HERE = os.path.dirname(__file__)
sys.path.insert(0, _HERE)

import test_guarded_answer_keeps_analysis as base  # noqa: E402
from src.agents.generalist_agent import _NO_CHECKED_ANSWER  # noqa: E402


def _second_withheld_state():
    state = base._withheld_state()
    state.financial_model.valuation_metrics = {
        **state.financial_model.valuation_metrics,
        "fair_value": 1023.70, "perpetual_price": 914.92, "exit_multiple_price": 1132.48,
        "current_price": 617.0, "upside_vs_market": 0.659,
    }
    return state


def _picks_agent(prompt="Any stocks you would recommend today?", published_last=True):
    states = {"GOOGL": base._withheld_state(), "META": _second_withheld_state(),
              "JPM": base._published_state()}
    names = {"GOOGL": "Alphabet Inc.", "META": "Meta Platforms, Inc.", "JPM": "JPMorgan Chase & Co."}
    last = "JPM" if published_last else "META"
    ag = base._chat_agent(prompt, states[last], last)
    ag._company_states = states
    ag._analysis_names = names
    ag.audits = []
    ag._audit = ag.audits.append
    return ag


# What the model wrote on 18 Nov, with the fixtures' figures (GOOGL's withheld
# midpoint 167.67 and its -44.0%; META's +65.9%).
DRAFT = (
    "Three names stand out today: **Alphabet (GOOGL)**, **Meta (META)** and **JPMorgan (JPM)**.\n\n"
    "**1. Alphabet (GOOGL)**\n"
    "- The forward P/E is about 19x, with revenue growing about 25%.\n"
    "- The model's midpoint of $167.67 is -44.0% from the price.\n"
    "- Alphabet looks cheap against its growth.\n\n"
    "**2. Meta (META)**\n"
    "- The forward P/E is about 17x, with 26% revenue growth and a 38% operating margin.\n"
    "- The model gives about 65.9% upside.\n\n"
    "**3. JPMorgan (JPM)**\n"
    "- The forward P/E is about 12.7x.\n"
    "- VYNN's report rates JPM HOLD with a 12-month price target of USD 142.00.\n\n"
    "Both tech names suit someone who accepts AI-capex risk; scaling in would suit that.\n\n"
    "I can run a full research report on any of these if you'd like."
)


def _run(ag, *replies):
    provider = base._Provider(*replies)
    out = asyncio.run(ag._several_company_answer([], provider, DRAFT, None, []))
    return out, provider


def test_the_turn_is_recognised_only_when_a_modelled_company_has_no_view():
    assert _picks_agent()._several_company_turn()
    ag = _picks_agent()
    ag._company_states = {"JPM": base._published_state(), "PG": base._published_state()}
    assert not ag._several_company_turn()
    ag._company_states = {"GOOGL": base._withheld_state()}
    assert not ag._several_company_turn()
    # A report read back this turn is one more company, not a way around the check.
    ag = _picks_agent()
    ag._company_states = {"GOOGL": base._withheld_state()}
    ag._tools_used = {"read_report"}
    ag.ctx.report_guard_state, ag.ctx.report_guard_ticker = base._published_state(), "JPM"
    ag.ctx.report_guard_company_name = "JPMorgan Chase & Co."
    assert ag._several_company_turn()
    assert {p["ticker"] for p in ag._company_positions()} == {"GOOGL", "JPM"}


def test_each_company_s_position_is_read_from_its_own_state():
    positions = {p["ticker"]: p for p in _picks_agent()._company_positions()}
    assert positions["JPM"]["published"] and positions["JPM"]["rating"] == "HOLD"
    assert not positions["GOOGL"]["published"] and not positions["META"]["published"]
    assert "167.67" in positions["GOOGL"]["forbidden"]
    assert "1,023.70" in positions["META"]["forbidden"]
    # A withheld company's line says why, with no figure and no direction:
    # its own statement ("a value above the market, +66% at the midpoint")
    # reads as a pick in a list of picks.
    for ticker in ("GOOGL", "META"):
        line = positions[ticker]["statement"]
        assert line.startswith("no buy or sell call from VYNN, because its valuation is a range")
        assert "%" not in line and "market" not in line and "$" not in line


def test_the_reported_picks_answer_keeps_no_call_on_a_withheld_company():
    ag = _picks_agent()
    out, provider = _run(ag, "NO")
    # The deterministic pass removed every call, figure and judgement on
    # Alphabet and Meta before the model check ran.
    for gone in ("stand out", "167.67", "-44.0%", "looks cheap", "65.9%"):
        assert gone not in out
    # Their facts, and the published company's view, stay.
    assert "forward P/E is about 19x" in out and "rates JPM HOLD" in out
    # Every company's position closes the answer, before the offer.
    assert out.index("Where VYNN stands") < out.index("I can run a full research report")
    assert "- GOOGL:" in out and "- META:" in out and "- JPM:" in out
    check = provider.calls[0]["messages"][0]["content"]
    assert "Alphabet Inc. (GOOGL)" in check and "Meta Platforms, Inc. (META)" in check
    assert "JPMorgan Chase & Co. (JPM): rated HOLD" in check
    assert "167.67" not in check.split("Answer:\n<<<\n", 1)[1]
    # What was removed is in the private log only.
    assert not any("looks cheap" in line for line in ag.logs)
    assert any("looks cheap" in line for line in ag.audits)


def test_a_call_the_patterns_miss_is_quoted_by_the_check_and_left_out():
    ag = _picks_agent()
    soft = "Both tech names suit someone who accepts AI-capex risk; scaling in would suit that."
    # "Both" names no company; the model check reads it as one.
    ag._JUDGEMENT = __import__("re").compile(r"(?!x)x")      # patterns miss everything here
    out, provider = _run(ag, f"YES\n{soft}\nThree names stand out today: Alphabet (GOOGL), Meta "
                             "(META) and JPMorgan (JPM).", "NO")
    assert "scaling in" not in out and "stand out" not in out
    # Narrowed, not replaced: the rest of the answer is the model's own.
    assert "forward P/E is about 12.7x" in out and "I can run a full research report" in out
    assert any("more sentence(s) the check read as a call" in line for line in ag.logs)
    assert len(provider.calls) == 2
    # The second check read the narrowed answer.
    assert "scaling in" not in provider.calls[1]["messages"][0]["content"].split("<<<\n", 1)[1]


@pytest.mark.parametrize("replies", [
    ("YES",),                                                   # names nothing
    ("YES\nAlphabet is a screaming buy here.",),                # quotes nothing in the answer
    ("YES\nBoth tech names suit someone who accepts AI-capex risk; scaling in would suit that.", "YES"),
])
def test_anything_else_gets_the_checked_call_free_answer(replies):
    ag = _picks_agent()
    section = ("Alphabet's revenue grew about 25% and Meta's 26%; JPMorgan's forward P/E is about "
               "12.7x. Capex runs high at both tech companies.")
    out, provider = _run(ag, *replies, section, "NO")
    assert out.startswith("Alphabet's revenue grew about 25%")
    assert "Where VYNN stands" in out and "rates JPM HOLD" in out
    # The writer was told the positions, and the section was checked.
    assert "must not contain" in provider.calls[-2]["messages"][-1]["content"]
    assert "Where VYNN stands" in provider.calls[-2]["messages"][-1]["content"]


def test_the_fallback_section_cannot_repeat_a_withheld_figure():
    ag = _picks_agent()
    section = ("Alphabet's revenue grew about 25%. Its midpoint of $167.67 is below the price. "
               "Capex runs high at both tech companies.")
    out, _ = _run(ag, "YES", section, "NO")
    assert "167.67" not in out
    assert out.startswith("Where VYNN stands")


def test_a_position_that_cannot_be_read_counts_as_no_view():
    ag = _picks_agent()

    class Broken:
        @property
        def financial_model(self):
            raise RuntimeError("corrupt state")

    ag._company_states["JPM"] = Broken()
    positions = {p["ticker"]: p for p in ag._company_positions()}
    assert positions["JPM"]["published"] is False


def test_the_safe_answer_before_the_check_makes_no_call():
    assert "no buy or sell call" in _NO_CHECKED_ANSWER


def test_the_run_uses_the_check_whenever_a_withheld_company_was_modelled():
    import inspect
    from src.agents.generalist_agent import GeneralistAgent
    source = inspect.getsource(GeneralistAgent.run)
    guard = source.index("guarded = self._guard_final_answer(draft)")
    several = source.index("several = self._several_company_turn()", guard)
    # A failure while deciding counts as "check it".
    assert "several = True" in source[several:several + 300]
    # The safe answer is committed before the check, so a failure inside it
    # never publishes the draft the one-company guard let through.
    assert source.index("final_text = _NO_CHECKED_ANSWER", several) < source.index(
        "await self._several_company_answer(", several)
    assert several < source.index("elif self._guard_template is not None", several)


# ---- the independent review's cases (18 Nov 2026, evening) ------------------

def test_the_positions_block_states_no_figure_or_direction_for_a_withheld_company():
    out, _ = _run(_picks_agent(), "NO")
    block = out[out.index("Where VYNN stands"):]
    assert "midpoint" not in block and "above the market" not in block and "66%" not in block
    assert "- META: no buy or sell call from VYNN" in block


def test_a_company_whose_build_was_refused_is_recorded_and_held():
    import json as _json

    class Registry:
        async def execute(self, name, arguments):
            return _json.dumps({"status": "not_applicable", "note": "a commodity producer"})

    ag = _picks_agent()
    ag._company_states = {"JPM": base._published_state()}
    ag.registry = Registry()
    ag._friendly_progress = lambda name, args: ""
    refused = base._exxon_state()                       # no model
    ag.ctx = SimpleNamespace(ticker="XOM", state=refused, company_name="Exxon Mobil Corporation",
                             logger=None)
    asyncio.run(ag._execute_tool("build_model", {"ticker": "XOM"}))
    assert ag._company_states["XOM"] is refused
    assert ag._several_company_turn()
    positions = {p["ticker"]: p for p in ag._company_positions()}
    assert not positions["XOM"]["published"]
    assert "no valuation of this company" in positions["XOM"]["statement"]


def test_a_short_flagged_sentence_is_removed_too():
    ag = _picks_agent()
    draft = DRAFT.replace("**3. JPMorgan (JPM)**", "- META: cheap.\n\n**3. JPMorgan (JPM)**")
    out = asyncio.run(ag._several_company_answer([], base._Provider("NO"), draft, None, []))
    assert "cheap" not in out


def test_a_misstated_published_view_sends_the_answer_to_the_fallback():
    ag = _picks_agent()
    draft = DRAFT.replace("VYNN's report rates JPM HOLD", "The report rates JPM BUY")
    section = ("Alphabet's revenue grew about 25% and Meta's 26%; JPMorgan's forward P/E is about "
               "12.7x. Capex runs high at both tech companies.")
    out = asyncio.run(ag._several_company_answer([], base._Provider(section, "NO"), draft, None, []))
    assert "rates JPM BUY" not in out and out.startswith("Alphabet's revenue grew")
    assert any("misstated VYNN's view on JPM" in line for line in ag.logs)


def test_a_state_that_cannot_be_read_counts_as_no_view():
    ag = _picks_agent()
    ag._company_states["JPM"] = SimpleNamespace(financial_model=SimpleNamespace(valuation_metrics=["junk"]))
    assert ag._several_company_turn()
    assert not {p["ticker"]: p for p in ag._company_positions()}["JPM"]["published"]


@pytest.mark.parametrize("name, ticker, unwanted", [
    ("The Coca-Cola Company", "KO", "The"),
    ("Bank of America Corporation", "BAC", "Bank"),
])
def test_a_generic_first_word_does_not_name_a_company(name, ticker, unwanted):
    ag = _picks_agent()
    words = ag._company_words({"ticker": ticker, "name": name})
    assert not ag._names_one_of(f"{unwanted} results were mixed this quarter.", words)
    assert ag._names_one_of(f"Shares of {name.split(' Corporation')[0]} rose.", words)


def test_short_tickers_match_only_as_tickers():
    ag = _picks_agent()
    on = ag._company_words({"ticker": "ON", "name": "ON Semiconductor Corporation"})
    agilent = ag._company_words({"ticker": "A", "name": "Agilent Technologies, Inc."})
    assert not ag._names_one_of("JPMorgan trades at a discount on book value, with upside.", on)
    assert ag._names_one_of("ON looks cheap here.", on)
    assert not ag._names_one_of("A strong quarter for JPMorgan.", agilent)
    assert ag._names_one_of("Agilent (A) looks cheap.", agilent)
    assert ag._names_one_of("Coca-Cola looks cheap.",
                            ag._company_words({"ticker": "KO", "name": "The Coca-Cola Company"}))


@pytest.mark.parametrize("call", ["- GOOGL: a buy.", "- I'd buy Alphabet here.",
                                  "- Alphabet is my top recommendation."])
def test_a_plain_call_on_a_withheld_company_is_removed_by_the_code(call):
    ag = _picks_agent()
    draft = DRAFT.replace("**3. JPMorgan (JPM)**", f"{call}\n\n**3. JPMorgan (JPM)**")
    out = asyncio.run(ag._several_company_answer([], base._Provider("NO"), draft, None, []))
    assert call[2:] not in out


def test_a_failed_attempt_under_another_symbol_is_not_a_second_company():
    ag = _picks_agent()
    failed = base._exxon_state()                    # data found, no model
    ag._company_states = {"BRK.B": failed, "BRK-B": base._published_state(), "GOOGL": base._withheld_state()}
    ag._company_names = {"BRK.B": "Berkshire Hathaway Inc.", "BRK-B": "Berkshire Hathaway Inc.",
                         "GOOGL": "Alphabet Inc."}
    assert set(ag._all_company_states()) == {"BRK-B", "GOOGL"}


def test_two_published_ratings_do_not_read_as_a_conflict():
    ag = _picks_agent()
    pg = base._published_state()
    pg.report = types.SimpleNamespace(content="## Investment Rating: BUY\n\n**12-Month Price Target**: USD 180.00\n")
    ag._company_states["PG"] = pg
    ag._company_names = {**ag._analysis_names, "PG": "Procter & Gamble"}
    published = [p for p in ag._company_positions() if p["published"]]
    text = "VYNN's report rates JPM HOLD.\n\nThe report rates PG BUY."
    assert ag._contradicts_published(text, published) is None
    assert ag._contradicts_published("The report rates JPM BUY.", published) == "JPM"
    # A sentence about a withheld company can still misstate a published one.
    assert ag._contradicts_published("The report rates the bank BUY, unlike Meta.", published) == "JPM"


def test_the_single_company_section_review_still_trims_a_quote_spanning_two_sentences():
    from src.answer_evidence import review_section
    section = ("Revenue rose 8% on membership fees. Margins rose. The shares look stretched "
               "against peers.\n\nComparable sales grew 6% excluding fuel, and traffic rose 3%.")
    review = review_section(section, drop=["Margins rose. The shares look stretched against peers."])
    assert review.quotes_unmatched == 0 and len(review.dropped) == 2


def test_a_view_the_chat_was_told_is_not_single_counts_as_no_view():
    # 18 Nov: the methods' spread can withhold the point in build_model's
    # answer to the chat without setting point_estimate_withheld.
    ag = _picks_agent()
    spread = base._published_state()
    spread.financial_model.valuation_metrics = {"fair_value": 134.75, "point_estimate_withheld": False,
                                                "chat_no_single_fair_value": True}
    ag._company_states = {"JPM": base._published_state(), "XYZ": spread}
    assert ag._several_company_turn()
    assert not {p["ticker"]: p for p in ag._company_positions()}["XYZ"]["published"]


def test_alphabet_and_meta_published_with_a_dcf_only_caution_are_not_withheld():
    # What the 18 Nov picks runs actually had: publication allowed, no point
    # withheld, a "DCF-only, present as a scenario range" note in the log only.
    ag = _picks_agent()
    ag._company_states = {t: base._published_state() for t in ("GOOGL", "META", "JPM")}
    assert not ag._several_company_turn()


@pytest.mark.parametrize("fact", [
    "Verizon is holding above both its 50-day ($45.69) and 200-day ($45.96) averages.",   # 18 Nov run
    "Alphabet will buy back $70 billion of stock.",
    "Meta shares fell in a broad tech sell-off.",
    "Alphabet picks up share in cloud.",
])
def test_a_fact_with_a_call_like_word_stays(fact):
    ag = _picks_agent()
    draft = DRAFT.replace("**3. JPMorgan (JPM)**", f"- {fact}\n\n**3. JPMorgan (JPM)**")
    out = asyncio.run(ag._several_company_answer([], base._Provider("NO"), draft, None, []))
    assert fact in out


def test_the_no_call_line_is_not_said_twice():
    ag = _picks_agent("Verizon or AT&T, which is the better buy right now?")
    ag._company_states = {"VZ": base._withheld_state(), "T": _second_withheld_state()}
    ag._company_names = {"VZ": "Verizon Communications Inc.", "T": "AT&T Inc."}
    draft = ("**I can't name a winner. VYNN's model gives no single fair value for either stock, so it "
             "gives no call on either.**\n\nVerizon trades at 8.7 times forward earnings and AT&T at 8.5.")
    out = asyncio.run(ag._several_company_answer([], base._Provider("NO"), draft, None, []))
    assert not out.startswith("**Short answer") and out.count("no call on either") == 1
