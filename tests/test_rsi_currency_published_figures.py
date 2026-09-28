"""Three data problems found in the 2026-09-28 answers, and their fixes.

1. RSI: get_technicals took a plain 14-day rolling mean (Cutler's RSI), not
   Wilder's RSI(14) that every broker shows. Realty Income read 4.8 where the
   standard figure is 17.4; NVDA and TSLA were off by about ten points.
2. Currency: get_financials returned a London listing's price in the currency
   the company reports in ("47.80 USD" beside get_prices' 3,611 GBp) and its
   market cap, which is in pounds, labelled USD: an answer said Shell's market
   cap was "about $206 billion" (it is $272.7 billion, or 206 billion pounds).
3. Published figures: for a published rating the analysis check refused a
   section that restated the model's own DCF values, so MSFT sometimes
   answered with the fixed statement alone.
"""
import asyncio
import json
import os
import sys
import types
from types import SimpleNamespace

import pandas as pd
import pytest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "src"))

from src.agents.tools.data_tools import GetTechnicalsTool, wilder_rsi  # noqa: E402
from src.agents.tools.analysis_tools import AgentContext, GetFinancialsTool, listing_figures  # noqa: E402
from src.agents.supervisor.supervisor_agent import SupervisorWorkflowRunner  # noqa: E402
from src.answer_evidence import makes_claim, review_section  # noqa: E402
from agents.findings import extract_findings  # noqa: E402
from test_guarded_answer_keeps_analysis import _Provider, _chat_agent, _published_state  # noqa: E402

# --------------------------------------------------------------------------
# 1. RSI
# --------------------------------------------------------------------------

# The worked example in StockCharts' ChartSchool (cs-rsi.xls) and its published RSI(14) values.
CHARTSCHOOL_CLOSES = [
    44.3389, 44.0902, 44.1497, 43.6124, 44.3278, 44.8264, 45.0955, 45.4245, 45.8433, 46.0826,
    45.8931, 46.0328, 45.6140, 46.2820, 46.2820, 46.0028, 46.0328, 46.4116, 46.2222, 45.6439,
    46.2122, 46.2521, 45.7137, 46.4515, 45.7835, 45.3548, 44.0288, 44.1783, 44.2181, 44.5672,
    43.4205, 42.6628, 43.1314,
]
CHARTSCHOOL_RSI = [70.53, 66.32, 66.55, 69.41, 66.36, 57.97, 62.93, 63.26, 56.06, 62.38, 54.71,
                   50.42, 39.99, 41.46, 41.87, 45.46, 37.30, 33.08, 37.77]


def test_rsi_matches_the_published_worked_example():
    got = [round(wilder_rsi(CHARTSCHOOL_CLOSES[:n]), 2) for n in range(15, len(CHARTSCHOOL_CLOSES) + 1)]
    assert got == CHARTSCHOOL_RSI


def test_rsi_edges():
    assert wilder_rsi([100.0] * 30) == 50.0
    assert wilder_rsi(list(range(1, 31))) == 100.0
    assert wilder_rsi(list(range(30, 0, -1))) == 0.0
    assert wilder_rsi([1.0] * 14) is None


def test_the_technicals_tool_reports_wilders_rsi(monkeypatch):
    import src.agents.tools.yf_resilience as yf_resilience
    frame = pd.DataFrame({"Close": CHARTSCHOOL_CLOSES})
    monkeypatch.setattr(yf_resilience, "fetch_history", lambda ticker, period: frame)
    body = json.loads(asyncio.run(GetTechnicalsTool().execute("TEST")).split("\n", 1)[-1])
    assert body["rsi_14"] == 37.8


def test_an_rsi_of_zero_still_gets_its_card():
    assert extract_findings("get_technicals", {"status": "ok", "rsi_14": 0.0}) == [
        {"kind": "technical", "label": "RSI (14)", "value": "0"}
    ]


# --------------------------------------------------------------------------
# 2. Currency
# --------------------------------------------------------------------------

SHEL_L_BASIC = {"currency": "USD", "listing_currency": "GBP", "sector": "Energy", "industry": "Oil & Gas Integrated"}
SHEL_L_MARKET = {  # as the scraper stored Shell's London line on 2026-09-28
    "current_price": 47.80312279820442, "current_price_listing": 36.11, "current_price_currency": "USD",
    "fx_listing_to_financial": 1.3238195180892944, "market_cap": 205990526976,
    "market_cap_financial": 272694280152.32812, "trailing_pe": 13.1,
}


def test_a_london_line_reports_its_own_price_and_market_cap_in_pounds():
    figures = listing_figures(SHEL_L_BASIC, SHEL_L_MARKET)
    assert (figures["currency"], figures["current_price"], figures["market_cap"]) == ("GBP", 36.11, 205990526976)
    assert figures["reporting_currency"] == "USD"
    assert figures["current_price_in_reporting_currency"] == pytest.approx(47.80, abs=0.01)
    assert figures["market_cap_in_reporting_currency"] == pytest.approx(272.69e9, rel=1e-4)
    assert "GBP" in figures["currency_note"] and "USD" in figures["currency_note"]


def test_a_same_currency_listing_is_unchanged():
    basic = {"currency": "USD", "listing_currency": "USD"}
    market = {"current_price": 95.78, "current_price_listing": 95.78, "current_price_currency": "USD",
              "market_cap": 273189879808, "market_cap_financial": 273189879808}
    assert listing_figures(basic, market) == {"currency": "USD", "current_price": 95.78, "market_cap": 273189879808}


def test_without_a_rate_nothing_is_offered_as_converted():
    market = dict(SHEL_L_MARKET, current_price=36.11, current_price_currency="GBP",
                  fx_listing_to_financial=None, market_cap_financial=205990526976)
    figures = listing_figures(SHEL_L_BASIC, market)
    assert figures["current_price"] == 36.11 and figures["currency"] == "GBP"
    assert "current_price_in_reporting_currency" not in figures
    assert "market_cap_in_reporting_currency" not in figures
    assert "no exchange rate" in figures["currency_note"]


def test_get_financials_returns_the_listing_figures(monkeypatch):
    import importlib
    # The package re-exports a function under the module's name; patch the module.
    fda = importlib.import_module("src.agents.supervisor.task_agents.financial_data_agent")
    state = SimpleNamespace(
        company_name="Shell plc", last_error=None, is_financial_data_collected=lambda: True,
        financial_data=SimpleNamespace(key_metrics={"basic_info": SHEL_L_BASIC, "market_data": SHEL_L_MARKET}),
    )

    async def fake_agent(st):
        return state

    monkeypatch.setattr(fda, "financial_data_agent", fake_agent)
    ctx = AgentContext(email="t@vynn.ai", timestamp="t", user_prompt="should i buy shel?")
    monkeypatch.setattr(ctx, "ensure_state_for_ticker", lambda ticker: state)
    body = json.loads(asyncio.run(GetFinancialsTool(ctx).execute("SHEL.L")).split("\n", 1)[-1])
    assert (body["currency"], body["current_price"], body["market_cap"]) == ("GBP", 36.11, 205990526976)
    assert body["reporting_currency"] == "USD" and body["trailing_pe"] == 13.1
    card = extract_findings("get_financials", body)[0]
    assert card["value"].startswith("£") and "206" in card["value"]


def test_a_typed_ticker_is_resolved_as_typed():
    from pathlib import Path
    prompt = (Path(__file__).resolve().parents[1] / "src" / "agents" / "generalist_agent.py").read_text()
    assert "When the user typed a ticker symbol themselves" in prompt
    assert "call resolve_symbol with exactly that symbol, not the company name" in prompt


# --------------------------------------------------------------------------
# 3. Published figures
# --------------------------------------------------------------------------

MSFT_VIEW = {"rating": "BUY", "values": [604.09, 540.51, 667.67, 604.09], "percents": [17.03]}


RESTATEMENTS = [
    "The perpetual-growth and exit-multiple DCF values were $540.51 and $667.67, blended to a $604.09 fair value.",
    "VYNN rates MSFT a BUY with a 12-month price target of $604.09.",
    "The model implies about 17% upside.",
    "Our rating is BUY.",
    "我们维持买入评级，目标价604.09美元。",
]


@pytest.mark.parametrize("text", RESTATEMENTS)
def test_without_the_published_view_the_same_sentences_are_claims(text):
    assert makes_claim(text)


@pytest.mark.parametrize("text", RESTATEMENTS)
def test_restating_the_published_view_is_not_a_claim(text):
    assert not makes_claim(text, published=MSFT_VIEW)


@pytest.mark.parametrize("text", [
    "A bull case of $700 per share.",
    "The stock is rated SELL.",
    "A price target of $650 looks reachable.",
    "The price target over the next 12 months is $650.",
    "The shares look undervalued.",
    "It is our top pick.",
    "Strong buy.",
    "评级为卖出。",
])
def test_anything_beyond_the_published_view_still_counts(text):
    assert makes_claim(text, published=MSFT_VIEW)


def test_a_fair_value_before_a_comma_is_still_a_claim():
    # The figure pattern rejected a decimal followed by a comma: "180.50," never
    # matched, so the sentence was not a claim. ("180," passed only because the
    # comma was swallowed as a thousands separator.)
    assert makes_claim("The model gives a fair value of 180.50, per the report.")
    assert makes_claim("The model gives a fair value of 180, per the report.")


def test_the_refused_msft_section_passes_the_deterministic_check_either_way():
    # In the gate run it was the model check that refused this section; the
    # fix for that is the published view in the check's prompt (tested below).
    section = (
        "The report used a DCF-only valuation; its perpetual-growth and exit-multiple cases were $540.51 and "
        "$667.67, respectively, and share the same underlying cash-flow forecast and terminal assumptions. "
        "No independent market-comparables valuation was available."
    )
    assert review_section(section).publishable
    assert review_section(section, published=MSFT_VIEW).publishable


def test_the_guard_records_the_published_view():
    view = SupervisorWorkflowRunner._published_view(
        "BUY",
        {"fair_value": 604.09, "perpetual_price": 540.51, "exit_multiple_price": 667.67, "upside_vs_market": 0.1703},
        {"price_target_12m": "USD 604.09"},
    )
    assert view["rating"] == "BUY"
    assert view["values"] == [604.09, 540.51, 667.67, 604.09]
    assert view["percents"] == [pytest.approx(17.03)]


def _analysis(ag, provider, draft):
    template = ag._guard_final_answer(draft)
    out = asyncio.run(ag._add_analysis([{"role": "user", "content": ag.user_prompt}], provider, template,
                                       [{"type": "function"}]))
    return template, out


def test_a_published_analysis_restating_the_view_is_published_and_the_check_is_told():
    ag = _chat_agent("summarize the report", _published_state(), "PG")
    draft = "The report rating is SELL and the report's fair value is $167.67."
    section = ("The model's fair value is $134.75 and its 12-month target is USD 142.00. "
               "Organic sales rose 4% as pricing held up across beauty and grooming.")
    provider = _Provider(section, "NO")
    template, out = _analysis(ag, provider, draft)
    assert out != template and "Organic sales rose 4%" in out and "$134.75" in out
    check_prompt = provider.calls[1]["messages"][0]["content"]
    assert "VYNN publishes a HOLD rating on this stock with these per-share figures: 134.75, 142.00" in check_prompt


def test_a_published_analysis_cannot_restate_the_contradicted_figure():
    ag = _chat_agent("summarize the report", _published_state(), "PG")
    draft = "The report rating is SELL and the report's fair value is $167.67."
    section = "The DCF fair value of $167.67 per share sits above the price. Organic sales rose 4%."
    template, out = _analysis(ag, _Provider(section, "NO"), draft)
    assert out == template
