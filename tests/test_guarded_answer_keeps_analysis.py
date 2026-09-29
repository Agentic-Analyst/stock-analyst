"""A guarded answer carries the run's analysis, never a call.

Reported 2026-09-28: "should i buy/hold xom?" produced six findings (report,
price, 8 articles, 3 catalysts and 3 risks, RSI, a headline) and a chart, then
answered with two sentences. The publication guard answers any draft it cannot
accept with a fixed template, which on its own dropped everything the run had
established. On the production image the same happened to every should-I-buy
and analyze question tried (XOM, SHEL, META, MSFT, TSLA, O).

Two designs were rejected in review before this one. Cutting the calls out of
the draft leaked most phrasings (the user asked for a call, so the draft makes
one). A pattern backstop on a rewritten section still leaked soft calls and
paraphrased targets, and deleted real evidence. Now the model writes the
analysis without the draft in view, and it is published only if it has no
explicit claim (answer_evidence.review_section) AND a yes/no model check finds
no call; anything else, or any failure, leaves the template alone.

The XOM drafts are verbatim gpt-6-luna output from the production image,
captured just before the guard on 2026-09-28.
"""
import asyncio
import os
import re
import sys
import time
import types
from types import SimpleNamespace

import pytest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "src"))

from src.agents.supervisor import supervisor_agent  # noqa: E402,F401
from src.answer_evidence import compose, makes_claim, restates, review_section  # noqa: E402
from src.agents.generalist_agent import GeneralistAgent  # noqa: E402
from agents.findings import extract_findings  # noqa: E402

XOM_DRAFT_2 = (
    "**My take: Hold XOM if you already own it; be selective about buying more at this level.** "
    "It’s a high-quality integrated oil major, but the stock has already had a strong run and "
    "near-term earnings are exposed to commodity prices and unusually strong refining margins.\n\n"
    "- **Price and trend:** XOM was **$160.59** in the latest quote, down **0.96%** on the day, "
    "but up **41.0% over the past year**. It’s above its 50-day ($159.01) and 200-day ($146.49) "
    "averages; RSI is **52**, a fairly neutral reading. The chart shows that strong year-long "
    "advance.\n"
    "- **Main risk:** Earnings can fall if oil and gas prices weaken or refining margins "
    "normalize.\n\n"
    "If you already hold it, the case to keep holding is stronger if you want energy exposure."
)

# The section the model wrote for "should i buy/hold xom?" on the candidate image, 2026-09-28.
XOM_SECTION = (
    "XOM is at **$160.59**, up about **41% over the past year**; it was down **0.96%** on the "
    "latest session. The shares are slightly above the 50-day moving average (**$159.01**) and "
    "above the 200-day (**$146.49**). RSI is **52**, while MACD is below its signal line—mixed, "
    "broadly neutral technical signals.\n\n"
    "Recent coverage highlights **$30.6 billion in trailing-12-month free cash flow** and "
    "interest coverage of **59.5×**, while noting that the cash-flow period includes an unusually "
    "strong second quarter. Potential longer-term production drivers include Guyana and the "
    "Permian; ExxonMobil also signed a 50/50 exploration agreement in Azerbaijan, an early-stage "
    "opportunity with no established near-term earnings contribution.\n\n"
    "The main risks in recent coverage are volatile oil, gas, and refining markets; normalization "
    "of unusually strong refining margins; and operational issues reported at the Joliet refinery. "
    "The Baytown blue hydrogen project was also reported paused because of insufficient demand. "
    "Overall recent news sentiment was neutral."
)


# --------------------------------------------------------------------------
# The deterministic check
# --------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "The report's 12-month price target is USD 150.00.",
    "Our price target is approx. $200.",
    "Price objective: $200.",
    "PT $200.",
    "Our fair-value estimate is $180.",
    "A fair value of $180 per share.",
    "The stock is worth about $180 per share on mid-cycle earnings.",
    "My DCF puts the shares at $180.",
    "The shares look under‑valued.",
    "The stock is overpriced here.",
    "XOM looks attractively valued.",
    "That leaves about 7% upside from here.",
    "Upside of 20% if refining margins hold.",
    "That implies a 20% return from here.",
    "Bull case: $240 if Brent averages $90.",
    "- **Bull:** $240",
    "Rating: Neutral.",
    "Verdict: **Hold**.",
    "Our rating: Strong-Buy.",
    "A strong-buy in my view.",
    "I would rate it a buy.",
    "We recommend a Hold.",
    "Hold.",
    "It's our top pick in energy.",
    "We see it as a Market Perform.",
    "Bottom line: buy.",
    "目标价 $200，合理估值约为180美元，目前被低估",
    "上行空间约20%",
    "Precio objetivo de $200.",
    "Recomendación de compra.",
])
def test_an_explicit_claim_is_caught(text):
    assert makes_claim(text)


@pytest.mark.parametrize("text", [
    # Evidence the first two designs deleted.
    "Exxon agreed to buy Pioneer Natural Resources in 2023.",
    "OPEC+ agreed to hold output steady through December.",
    "The company plans to sell its Singapore chemicals plant.",
    "Support needs to hold near $150 for the uptrend to continue.",
    "XOM continues to outperform the S&P 500 this year.",
    "Exxon targets $20 billion in structural cost savings by 2030.",
    "The Fed kept its 2% inflation target.",
    "Competition from cheap Chinese EVs is intensifying.",
    "Tesla will hold its annual shareholder meeting in November.",
    "The Baytown project was put on hold.",
    "A $10 drop in Brent is the main downside risk.",
    "Earnings beat with an upside surprise of 8%.",
    "Its stake in OpenAI is worth about $135 billion.",
    "Realty Income targets about $5 billion of investment volume.",
    "It has delivered a 13.5% compound annual total return since listing.",
    "Energy stocks saw a broad sell‑off in March as crude fell.",
    "Shell has completed 19 consecutive quarters of buybacks.",
    "- Price: $160.59",
    "RSI is 52, a neutral reading.",
])
def test_evidence_is_not_mistaken_for_a_claim(text):
    assert not makes_claim(text)


def test_soft_calls_pass_this_check_and_are_left_to_the_model_check():
    # Deliberately: a pattern list for these either misses or deletes evidence.
    for soft in ("After the pullback, the risk/reward looks favorable.",
                 "Long-term investors may find value here.",
                 "The shares could climb to $250 as Guyana volumes ramp."):
        assert not makes_claim(soft)


def test_repeats_of_the_fixed_statement_are_stripped_not_counted():
    section = (
        "O: NOT RATED. No rating or fair value is published: it is a REIT.\n\n"
        "Realty Income trades at $55.54, down 3% this year, with a 5.8% dividend yield. "
        "It targets about $5 billion of investment volume in 2026. Analysts rate it a Hold on average."
    )
    review = review_section(section)
    assert review.publishable and not review.claims
    assert len(review.repeated) == 3
    assert review.text.startswith("Realty Income trades at $55.54") and "Hold" not in review.text


def test_a_claim_anywhere_makes_the_section_unpublishable():
    review = review_section(XOM_SECTION + "\n\nThe stock looks undervalued.")
    assert not review.publishable and review.claims == ["The stock looks undervalued."]


def test_the_real_draft_is_not_publishable():
    assert not review_section(XOM_DRAFT_2).publishable


def test_the_real_section_is_publishable_unchanged():
    review = review_section(XOM_SECTION)
    assert review.publishable and review.text == XOM_SECTION


def test_a_label_and_its_figure_on_separate_lines_are_read_together():
    review = review_section("Bull case:\n$240 if Brent averages $90.\n\n" + XOM_SECTION)
    assert not review.publishable


def test_a_table_is_read_whole():
    clean = "| Indicator | Reading |\n|---|---|\n| RSI (14) | 52 |\n| 50-day MA | $159.01 |"
    assert review_section(clean + "\n\n" + XOM_SECTION).publishable
    scenario = "| Scenario | Value per share |\n|---|---|\n| Bull | $240 |\n| Bear | $150 |"
    assert not review_section(scenario + "\n\n" + XOM_SECTION).publishable


def test_what_is_left_keeps_its_shape():
    section = (
        "## Price action\n\nXOM rose 41% over the year. It is NOT RATED.\n\n"
        "Key numbers:\n- Price: $160.59\n- RSI (14): 52\n  - above the 50-day average of $159.01\n"
        "- 200-day MA: $146.49"
    )
    review = review_section(section)
    assert review.publishable
    assert "NOT RATED" not in review.text and "XOM rose 41% over the year." in review.text
    assert "  - above the 50-day average" in review.text and "- 200-day MA: $146.49" in review.text


def test_withheld_figures_are_caught_in_their_rounded_prints():
    tokens = ("167.67", "167.7", "-44.0%", "−44.0%")
    assert makes_claim("The model's point estimate of about $167.7 is below the price.", tokens)
    assert makes_claim("It sits −44.0% from the market.", tokens)


def test_pathological_input_stays_fast():
    started = time.monotonic()
    review_section("1," * 100_000 + " upside")
    review_section("$1. " * 50_000)
    review_section("Refining margins were strong this quarter. " * 5_000)
    assert time.monotonic() - started < 3.0


# From the third review (2026-09-28): real claims just outside the obvious
# phrasings, and ordinary evidence the earlier patterns refused a section over.
NEAR_MISS_CLAIMS = [
    "Upside of 20% if refining margins hold.", "That leaves about 7% upside from here.", "The stock has 20% upside.",
    "Upside to $250 looks plausible.", "Downside to $90 if margins normalize.", "Upside potential of 25%.",
    "a potential upside of roughly 15%", "The upside is about 20%.", "15% further downside is possible.",
    "Bull case: $240 if Brent averages $90.", "Bear case: shares fall to $80 if Brent drops to $55.",
    "Bear case: if oil falls to $55, the stock could drop to $80.", "Bear case: at $55 Brent the shares fall to $80.",
    "Bear case: with Brent at $55 and WTI at $52 the stock would trade near $80.",
    "Bull case: $240 per share if Brent averages $90 a barrel.", "- **Bull:** $240", "| Bull | $240 |",
    "Base case: $180 per share.", "Bull case \u2014 $240.",
    "Overweight.", "Rating: Overweight.", "We rate it Overweight.", "We are overweight the shares.",
    "I'd stay overweight XOM.", "Rated a Buy by our model.", "The stock is rated Buy.", "rate it a hold",
    "Verdict: hold.", "Final verdict: Buy.", "Stance: bullish.", "Call: sell.",
    "Fair value is 12% above the price.", "Fair value of 180.", "A $180 fair value.", "fair value: $1,250",
    "The shares look under-valued.", "The stock is overpriced here.", "XOM looks underpriced.",
    "Exxon looks underpriced.", "The shares were overpriced at the peak.", "an underpriced stock",
    "PT $200.", "Our PT of $200.", "Price target $200.", "target price 200",
    "My DCF puts the shares at $180.", "The model's midpoint implies $167.67.", "Our model gives a value of $180.",
    "The valuation implies $180 per share.",
    "目标价200美元", "合理估值约为180美元", "公允价值约为180美元", "维持买入评级", "评级：买入", "目前被低估",
]
IDIOMS = [
    "The main downside is China exposure, which is about 17% of revenue.",
    "Upside came from Services, which grew 15% to $28.8 billion.",
    "Upside catalysts include a 25% increase in Blackwell shipments next quarter.",
    "Upside risks include OPEC+ cutting output, which lifted Brent 8% in April.",
    "RSI fell to 28 after a 12% drop, signalling strong downside momentum.",
    "In a downside scenario where Brent falls to $60, Exxon says it can still cover the dividend.",
    "The shares have more than tripled from the 2022 bear-market low of $88.09.",
    "The 2023-24 bull run took the stock from $120 to $480.",
    "Tesla launched cheaper Standard trims, with the base Model Y at $39,990.",
    "The base iPhone 17 starts at $799, unchanged from last year.",
    "Management's base case assumes Brent averages $65 a barrel through 2027.",
    "Bull case: every $10/bbl rise in Brent adds roughly $5 billion to annual earnings.",
    "Bear case: if Brent falls to $55, upstream earnings would drop sharply.",
    "Management's NII guidance of about $95.5 billion assumes rates hold near current levels.",
    "Futures price a Fed rate hold in October and one cut by December.",
    "If long-term rates sell off further, REIT funding costs would rise.",
    "Unrealized losses on available-for-sale securities, carried at fair value, narrowed to $4.2 billion.",
    "Net income included a $950 million fair value loss on equity investments.",
    "Underwriting results benefited as catastrophe risk, which the industry had underpriced for years, was repriced.",
    "Zepbound is approved for adults with obesity or overweight with at least one weight-related condition.",
    "The equal-weight S&P 500 has lagged the cap-weighted index by 9 points this year.",
    "BofA's fund manager survey shows investors are net underweight Chinese equities.",
    "- **Earnings call:** positive commentary on Blackwell demand and supply.",
    "- **Fed stance:** neutral, with inflation still above the 2% target.",
    "- **Credit rating:** positive outlook from S&P after the capital raise.",
    "AI services contributed about 16 pts of Azure's 39% growth.",
    "The new Model Y Standard puts the entry price at $39,990.",
    "Tesla's direct-sales model gives it about $2,000 per car of margin advantage.",
    "净利润同比增长16%，主要受所持股权投资公允价值变动收益影响。",
    "穆迪维持阿里巴巴A1信用评级，展望稳定。",
]


@pytest.mark.parametrize("text", NEAR_MISS_CLAIMS)
def test_a_claim_just_outside_the_obvious_phrasing_is_caught(text):
    assert makes_claim(text)


@pytest.mark.parametrize("text", IDIOMS)
def test_an_ordinary_idiom_does_not_sink_a_section(text):
    assert not makes_claim(text)


@pytest.mark.parametrize("text", [
    "JPMorgan raised its price target to $600 after the beat.",
    "Goldman Sachs upgraded the shares to Buy on Tuesday.",
    "Morgan Stanley named it a top pick for 2026.",
    # The rating actions that read as VYNN's own call ("an Outperform rating")
    # and dropped the whole analysis: gate26, Delta Air Lines.
    "Other coverage noted BMO lowered its target while maintaining an Outperform rating, and Delta's "
    "concern about competitive effects of China-U.S. flight-cap policy and unequal Russian airspace access.",
    "Jefferies reiterated its Buy rating after the call.",
    "Barclays kept its Overweight rating.",
    "BMO's Outperform rating stands despite the cut.",
    "The stock is rated Overweight by Morgan Stanley.",
    "Evercore ISI maintains an Outperform on the shares.",
])
def test_a_brokers_rating_action_is_left_out_as_the_streets_view(text):
    review = review_section(XOM_SECTION + "\n\n" + text)
    assert review.publishable and text not in review.text and review.repeated == [text]


@pytest.mark.parametrize("text", [
    "Exxon raised its production target to 5.4 million boe/d.",
    "Realty Income raised its target to $5 billion of investment.",
    "Shell cut its target for chemicals capacity.",
])
def test_a_companys_own_target_is_evidence(text):
    assert not restates(text) and not makes_claim(text)


def test_a_withheld_figure_matches_only_as_a_whole_number():
    tokens = ("318.66", "318.7")
    assert not makes_claim("The 200-day moving average is $318.70.", tokens)
    assert makes_claim("about $318.7 per share", tokens) and makes_claim("$318.66", tokens)


def test_compose_puts_the_answer_first_and_the_benchmark_last():
    template = (
        "XOM: NOT RATED. No rating or fair value is published: reason.\n\n"
        "The Street's view, shown as a benchmark and not as VYNN's rating:\n- mean target 172.55"
    )
    out = compose(template, "Price and trend: up 41% over the year.")
    assert out.index("NOT RATED") < out.index("Price and trend") < out.index("The Street's view")
    assert compose(template, "") == template


# --------------------------------------------------------------------------
# The guard records when it answered with its template
# --------------------------------------------------------------------------

def _exxon_state():
    raw = {
        "company_data": {
            "basic_info": {"quote_type": "EQUITY", "currency": "USD", "sector": "Energy",
                           "industry": "Oil & Gas Integrated"},
            "market_data": {"current_price": 160.59},
        },
        "financial_statements": {"income_statement": {}, "balance_sheet": {}, "cash_flow": {}},
        "external_expectations": {
            "currency": "USD",
            "price_target": {"mean": 172.55, "analyst_count": 22, "source": "yahoo_finance"},
            "recommendations": {},
            "forward_estimates": [],
        },
    }
    return SimpleNamespace(
        total_llm_cost=0.0,
        is_financial_data_collected=lambda: True,
        financial_data=SimpleNamespace(
            key_metrics={"basic_info": {"currency": "USD"}, "market_data": {"current_price": 160.59}},
            raw_data=raw,
        ),
        is_news_analyzed=lambda: True,
        news_analysis=SimpleNamespace(articles_count=8, overall_sentiment="neutral",
                                      freshness={"status": "fresh"}, catalysts=[], risks=[]),
        is_model_generated=lambda: False,
        financial_model=None,
        report=None,
    )


def _withheld_state():
    raw = {
        "company_data": {"basic_info": {"currency": "USD"}},
        "external_expectations": {
            "currency": "USD",
            "price_target": {"mean": 200.0, "analyst_count": 20, "source": "yahoo_finance"},
            "recommendations": {},
            "forward_estimates": [{"revenue": 100e9, "revenue_analyst_count": 15}],
        },
    }
    return SimpleNamespace(
        total_llm_cost=0.0,
        financial_data=SimpleNamespace(
            key_metrics={"basic_info": {"currency": "USD"}, "market_data": {"current_price": 300.0}},
            raw_data=raw,
        ),
        news_analysis=SimpleNamespace(articles_count=6, overall_sentiment="neutral",
                                      freshness={"status": "limited"}, catalysts=[], risks=[]),
        financial_model=SimpleNamespace(
            model_type="DCF",
            valuation_metrics={
                "fair_value": 167.67, "perpetual_price": 153.91, "exit_multiple_price": 183.79,
                "current_price": 300.0, "upside_vs_market": -0.44,
                "point_estimate_withheld": True,
                "publication_withheld_reason": "independent evidence conflicts",
                "model_revenue_forecast": [100e9],
            },
            assumptions={"revenue_growth_source": "yahoo_analyst_consensus_with_deterministic_fade"},
        ),
        report=None,
    )


def _published_state():
    return types.SimpleNamespace(
        financial_data=types.SimpleNamespace(key_metrics={"basic_info": {"currency": "USD"}}),
        financial_model=types.SimpleNamespace(
            valuation_metrics={"fair_value": 134.75, "point_estimate_withheld": False},
        ),
        report=types.SimpleNamespace(content=(
            "## Investment Rating: HOLD\n\n**12-Month Price Target**: USD 142.00\n"
        )),
        news_analysis=None,
    )


def _chat_agent(prompt, state, ticker):
    ag = GeneralistAgent.__new__(GeneralistAgent)
    ag.user_prompt = prompt
    ag.conversation_context = None
    ag._tools_used = set()
    ag.total_cost = 0.0
    ag.ctx = types.SimpleNamespace(ticker=ticker, state=state, company_name=None)
    ag.logs = []
    ag._log = ag.logs.append
    return ag


def test_the_reported_question_gets_the_template_and_it_is_recorded():
    ag = _chat_agent("should i buy/hold xom?", _exxon_state(), "XOM")
    out = ag._guard_final_answer(XOM_DRAFT_2)
    assert out.startswith("XOM: NOT RATED. No rating or fair value is published: its cash flows follow commodity prices")
    assert ag._guard_template == out and "Hold XOM" not in out


def test_the_withheld_template_is_recorded_with_its_point_figures():
    ag = _chat_agent("Give me the bull and bear case for TEST and a verdict.", _withheld_state(), "TEST")
    out = ag._guard_final_answer("Verdict: Buy. The model's midpoint of $167.67 sits well below the price.")
    assert ag._guard_template == out
    assert {"167.67", "167.7", "-44.0%"} <= set(ag._guard_forbidden)


def test_the_published_template_is_recorded_with_the_contradicted_figures():
    ag = _chat_agent("summarize the report", _published_state(), "PG")
    out = ag._guard_final_answer("The report rating is SELL and the report's fair value is $167.67.")
    assert out.startswith("PG audited report headline: investment rating HOLD")
    assert ag._guard_template == out and "167.67" in ag._guard_forbidden


def test_an_accepted_answer_records_no_template():
    ag = _chat_agent("what's the latest news on AAPL?", None, None)
    answer = "Apple's latest headlines are about its foldable iPhone launch and TSMC capacity."
    assert ag._guard_final_answer(answer) == answer
    assert ag._guard_template is None


# --------------------------------------------------------------------------
# The analysis turn and its two checks
# --------------------------------------------------------------------------

class _Provider:
    """Answers the analysis turn, then the check, in order."""

    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []
        self.is_openai = True

    async def call_with_tools(self, messages, tools, temperature=0.4, *, tool_choice=None):
        self.calls.append({"messages": list(messages), "tools": tools,
                           "temperature": temperature, "tool_choice": tool_choice})
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return types.SimpleNamespace(text=reply, cost=0.001, raw={"role": "assistant", "content": reply},
                                     has_tool_calls=False, tool_calls=[])


def _analysis(ag, provider, draft):
    template = ag._guard_final_answer(draft)
    messages = [{"role": "user", "content": ag.user_prompt}]
    out = asyncio.run(ag._add_analysis(messages, provider, template, [{"type": "function"}]))
    return template, out


def test_a_clean_section_that_passes_both_checks_is_published():
    ag = _chat_agent("should i buy/hold xom?", _exxon_state(), "XOM")
    provider = _Provider(XOM_SECTION, "NO")
    template, out = _analysis(ag, provider, XOM_DRAFT_2)

    assert out.index("XOM: NOT RATED") < out.index("Guyana and the Permian") < out.index("The Street's view")
    assert out.count("NOT RATED") == 1 and "172.55" in out
    write, check = provider.calls
    # The section is written without the draft in view, and with no tool.
    assert write["tool_choice"] == "none"
    assert write["messages"][-2] == {"role": "assistant", "content": "I have the tool results above."}
    assert not any("My take" in str(m.get("content")) for m in write["messages"])
    assert "must not contain" in write["messages"][-1]["content"] and template in write["messages"][-1]["content"]
    # The check sees exactly the section, alone, deterministically.
    assert check["tools"] == [] and check["temperature"] == 0.0 and len(check["messages"]) == 1
    assert XOM_SECTION in check["messages"][0]["content"]
    assert ag.total_cost == pytest.approx(0.002)


@pytest.mark.parametrize("verdict", ["YES", "Yes.", "Maybe", "", "NOTE: unclear",
                                     "NO, but the last sentence is a soft call", "NO\nYES",
                                     "No \u2014 although 'constructive' is borderline", "N/A", "\u5426"])
def test_anything_but_a_clear_no_leaves_the_fixed_statement(verdict):
    ag = _chat_agent("should i buy/hold xom?", _exxon_state(), "XOM")
    template, out = _analysis(ag, _Provider(XOM_SECTION, verdict), XOM_DRAFT_2)
    assert out == template


def test_a_soft_call_is_stopped_by_the_model_check():
    ag = _chat_agent("should i buy/hold xom?", _exxon_state(), "XOM")
    section = XOM_SECTION + "\n\nAfter the pullback, the risk/reward looks favorable."
    provider = _Provider(section, "YES")
    template, out = _analysis(ag, provider, XOM_DRAFT_2)
    assert out == template
    assert "risk/reward looks favorable" in provider.calls[1]["messages"][0]["content"]


def test_an_explicit_claim_stops_the_section_before_the_model_check():
    ag = _chat_agent("should i buy/hold xom?", _exxon_state(), "XOM")
    provider = _Provider(XOM_SECTION + "\n\nFair value is about $180 per share.")
    template, out = _analysis(ag, provider, XOM_DRAFT_2)
    assert out == template and len(provider.calls) == 1
    assert any("explicit claim" in line for line in ag.logs)


@pytest.mark.parametrize("replies", [
    (RuntimeError("provider down"),),
    ("",),
    ("埃克森美孚的股价在过去一年上涨了41%，高于50日和200日均线。炼油利润率异常强劲，可能回落。",),
    ("XOM: NOT RATED. Analysts rate it a Hold.",),
    (XOM_SECTION, RuntimeError("check failed")),
    (None,),
])
def test_any_failure_leaves_the_fixed_statement(replies):
    ag = _chat_agent("should i buy/hold xom?", _exxon_state(), "XOM")
    template, out = _analysis(ag, _Provider(*replies), XOM_DRAFT_2)
    assert out == template


def test_a_withheld_section_cannot_repeat_the_point_figures():
    ag = _chat_agent("Give me the bull and bear case for TEST and a verdict.", _withheld_state(), "TEST")
    section = (
        "**Bull case:** ad revenue grew 22% last quarter and engagement keeps rising.\n"
        "**Bear case:** capex runs at 39% of revenue and EU regulators are circling.\n\n"
        "The model's central estimate of $167.7 is below the price."
    )
    template, out = _analysis(ag, _Provider(section, "NO"), "Verdict: Buy. The midpoint of $167.67 is below.")
    assert out == template


def test_a_withheld_section_with_the_bull_and_bear_case_is_published():
    ag = _chat_agent("Give me the bull and bear case for TEST and a verdict.", _withheld_state(), "TEST")
    section = (
        "**Bull case:** ad revenue grew 22% last quarter and engagement keeps rising.\n"
        "**Bear case:** capex runs at 39% of revenue and EU regulators are circling."
    )
    _, out = _analysis(ag, _Provider(section, "NO"), "Verdict: Buy. The midpoint of $167.67 is below.")
    assert "ad revenue grew 22% last quarter" in out and "EU regulators are circling" in out
    assert out.index("Rating: NOT RATED") < out.index("Bull case") < out.index("benchmark reconciliation")


def test_a_published_section_cannot_restate_the_contradicted_figure():
    ag = _chat_agent("summarize the report", _published_state(), "PG")
    draft = "The report rating is SELL and the report's fair value is $167.67."
    section = "The DCF output of $167.67 per share sits above the current price. Organic sales rose 4%."
    template, out = _analysis(ag, _Provider(section, "NO"), draft)
    assert out == template


def test_a_contradicted_published_headline_gets_its_analysis_too():
    ag = _chat_agent("summarize the report", _published_state(), "PG")
    draft = "The report rating is SELL and the report's fair value is $167.67."
    section = ("Organic sales rose 4% as pricing held up across beauty and grooming. "
               "Margins widened for a third straight quarter on lower commodity costs.")
    _, out = _analysis(ag, _Provider(section, "NO"), draft)
    assert out.startswith("PG audited report headline: investment rating HOLD")
    assert "SELL" not in out and "Organic sales rose 4%" in out


def test_an_error_inside_the_analysis_step_never_escapes(monkeypatch):
    ag = _chat_agent("should i buy/hold xom?", _exxon_state(), "XOM")
    template = ag._guard_final_answer(XOM_DRAFT_2)

    async def broken(*args, **kwargs):
        raise ValueError("boom")

    monkeypatch.setattr(ag, "_analysis_with_checks", broken)
    out = asyncio.run(ag._add_analysis([], _Provider(), template, None))
    assert out == template


def test_the_writer_sees_the_transcript_only_up_to_the_tool_work():
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] / "src" / "agents" / "generalist_agent.py").read_text()
    mark = source.index("tool_work = len(messages)")
    report = source.index("final_text = await self._ensure_report_if_requested(", mark)
    step = source.index("self._add_analysis(messages[:tool_work], provider, guarded, tool_defs)", report)
    assert mark < report < step


def test_the_guarded_text_is_committed_before_the_analysis_step():
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] / "src" / "agents" / "generalist_agent.py").read_text()
    guard = source.index("guarded = self._guard_final_answer(final_text)")
    commit = source.index("final_text = guarded", guard)
    condition = source.index("if self._guard_template is not None and guarded == self._guard_template:", guard)
    step = source.index("final_text = await self._add_analysis(messages[:tool_work], provider, guarded, tool_defs)", guard)
    assert guard < commit < condition < step


# --------------------------------------------------------------------------
# The guard's own sentiment edit no longer flattens the answer
# --------------------------------------------------------------------------

def test_removing_a_sentiment_sentence_keeps_the_answers_shape():
    ag = _chat_agent("what's the latest news on AAPL?", None, None)
    answer = (
        "The main themes are:\n\n"
        "- **Leadership change:** Tim Cook stepped down as CEO on September 1.\n"
        "- **Foldable iPhone:** the iPhone Duo starts at $1,999.\n\n"
        "The news analysis rates overall sentiment **neutral**. Coverage is mixed."
    )
    out = ag._guard_final_answer(answer)
    assert "overall sentiment" not in out
    assert "\n- **Leadership change:**" in out and "\n- **Foldable iPhone:**" in out
    assert out.endswith("Coverage is mixed.")


def test_a_turned_bearish_claim_on_stale_news_is_removed():
    runner = supervisor_agent.SupervisorWorkflowRunner.__new__(supervisor_agent.SupervisorWorkflowRunner)
    runner.ticker = "TEST"
    runner.state = SimpleNamespace(news_analysis=SimpleNamespace(freshness={"status": "limited"}))
    patterns = runner._stale_news_patterns()
    assert restates("News sentiment has turned bearish this week.", patterns)


# --------------------------------------------------------------------------
# The findings card
# --------------------------------------------------------------------------

def test_a_declined_report_is_not_announced_as_generated():
    declined = {"status": "not_applicable", "note": "No valuation report for XOM.",
                "ticker": "XOM", "refusal": "commodity_cycle"}
    assert extract_findings("write_report", declined) == []
    assert extract_findings("build_model", declined) == []
    # A report that was written still gets its card.
    assert extract_findings("write_report", {"status": "success"})[0]["value"] == "Generated"



@pytest.mark.parametrize("text", [
    "We maintain an Outperform rating.",
    "VYNN maintains a Buy rating on the shares.",
    "I would keep a Buy rating here.",
    "Our view: we reiterate an Overweight rating.",
])
def test_a_rating_action_in_the_first_person_is_still_a_call(text):
    review = review_section(XOM_SECTION + "\n\n" + text)
    assert not review.publishable and review.claims


@pytest.mark.parametrize("text", [
    "Investors kept a buy-the-dip mentality through the drawdown.",
    "Regulators maintained a hold on the merger review.",
    "The Fed held its benchmark rate steady.",
])
def test_an_action_verb_near_a_rating_word_is_not_a_rating_action(text):
    review = review_section(XOM_SECTION + "\n\n" + text)
    assert review.publishable and text in review.text
