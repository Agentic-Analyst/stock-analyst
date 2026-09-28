"""A valuation answer gets the price, the technicals and the news with it.

write_report handed the model its headline and a news sentiment and nothing
else, though the run had analysed the news and the price is one fetch away;
whether an answer described the price trend, the technicals or the catalysts
depended on the model happening to call get_prices, get_technicals and
analyze_news as well. MSFT's answer once said "no price quote or technical-
indicator readings were returned". build_model and the refusal result (XOM,
Shell, a REIT) had the same gap.
"""
import asyncio
import json
import os
import sys
from types import SimpleNamespace

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "src"))

from src.agents.tools import analysis_tools  # noqa: E402
from src.agents.tools.analysis_tools import _flat_evidence, _refusal_result, market_evidence  # noqa: E402
from src.agents.tools import data_tools  # noqa: E402

PRICES = {"status": "ok", "ticker": "MSFT", "currency": "USD", "latest_price": 516.17, "previous_close": 498.0,
          "day_change_pct": 3.66, "period": "1y", "period_pct_change": 1.75, "period_high": 549.2,
          "period_low": 348.54, "series": [1, 2, 3]}
TECHNICALS = {"status": "ok", "ticker": "MSFT", "latest_close": 516.17, "rsi_14": 63.3, "sma_50": 505.1,
              "sma_200": 470.2, "above_sma_50": True, "above_sma_200": True, "macd": 4.1, "macd_signal": 3.2,
              "macd_bullish": True, "bollinger_upper": 540.0, "bollinger_lower": 480.0}


def _news_state():
    news = SimpleNamespace(articles_count=14, catalysts=["Azure growth", "Copilot adoption", "Buybacks", "Extra"],
                           risks=["Capex intensity", "Antitrust", "FX", "Extra"], overall_sentiment="bearish",
                           freshness={"status": "fresh", "fresh_articles": 14})
    return SimpleNamespace(news_analysis=news, is_news_analyzed=lambda: True)


def _patch_tools(monkeypatch, prices=PRICES, technicals=TECHNICALS):
    async def fake_prices(self, ticker, period="1y"):
        if isinstance(prices, Exception):
            raise prices
        return json.dumps(prices)

    async def fake_technicals(self, ticker):
        if isinstance(technicals, Exception):
            raise technicals
        return json.dumps(technicals)

    monkeypatch.setattr(data_tools.GetPricesTool, "execute", fake_prices)
    monkeypatch.setattr(data_tools.GetTechnicalsTool, "execute", fake_technicals)


def test_the_evidence_carries_price_technicals_and_news(monkeypatch):
    _patch_tools(monkeypatch)
    evidence = asyncio.run(market_evidence("MSFT", _news_state()))
    assert evidence["price"]["latest_price"] == 516.17 and evidence["price"]["currency"] == "USD"
    assert "series" not in evidence["price"]            # only the summary, not the history
    assert evidence["technicals"]["rsi_14"] == 63.3 and evidence["technicals"]["currency"] == "USD"
    assert evidence["news"]["top_catalysts"] == ["Azure growth", "Copilot adoption", "Buybacks"]
    assert evidence["news"]["top_risks"] == ["Capex intensity", "Antitrust", "FX"]
    assert evidence["news"]["articles_analyzed"] == 14
    assert evidence["news"]["news_sentiment"] == "bearish"


def test_stale_news_publishes_no_sentiment(monkeypatch):
    _patch_tools(monkeypatch)
    state = _news_state()
    state.news_analysis.freshness = {"status": "limited"}
    news = asyncio.run(market_evidence("MSFT", state))["news"]
    assert "news_sentiment" not in news and news["news_freshness"] == {"status": "limited"}


def test_a_failing_part_is_simply_absent(monkeypatch):
    _patch_tools(monkeypatch, prices=RuntimeError("yahoo down"),
                 technicals={"status": "error", "error": "Not enough price data"})
    evidence = asyncio.run(market_evidence("MSFT", None))
    assert evidence == {}


def test_the_evidence_is_for_the_listing_that_was_valued(monkeypatch):
    # TM (dollars) is valued on 7203.T (yen); a dollar price beside yen figures
    # would compare unlike units.
    asked = []

    async def fake(self, ticker, period="1y"):
        asked.append(ticker)
        return json.dumps(PRICES)

    monkeypatch.setattr(data_tools.GetPricesTool, "execute", fake)
    monkeypatch.setattr(data_tools.GetTechnicalsTool, "execute", fake)
    state = _news_state()
    state.ticker = "7203.T"
    asyncio.run(market_evidence("TM", state))
    assert asked == ["7203.T", "7203.T"]


def test_evidence_fields_never_collide_with_the_results_own(monkeypatch):
    _patch_tools(monkeypatch)
    evidence = asyncio.run(market_evidence("MSFT", _news_state()))
    news_payload = {"news_sentiment": "bearish", "news_freshness": {"status": "fresh"}}
    flat = _flat_evidence(evidence, exclude=news_payload)
    assert "news_sentiment" not in flat and "news_freshness" not in flat
    assert set(flat) == {"price", "technicals", "articles_analyzed", "top_catalysts", "top_risks"}
    dict(**news_payload, **flat)     # a duplicate keyword would raise TypeError


def test_a_refusal_carries_the_evidence(monkeypatch):
    _patch_tools(monkeypatch)
    evidence = asyncio.run(market_evidence("XOM", _news_state()))
    body = json.loads(_refusal_result("XOM", {"kind": "commodity_cycle", "reason": "cycle"},
                                      what="valuation report", evidence=evidence))
    assert body["status"] == "not_applicable"
    assert body["price"]["latest_price"] == 516.17 and body["top_risks"][0] == "Capex intensity"
    assert json.loads(_refusal_result("XOM", {"kind": "commodity_cycle", "reason": "cycle"},
                                      what="valuation report"))["status"] == "not_applicable"


def test_both_valuation_tools_attach_the_evidence():
    source = open(os.path.join(_ROOT, "src", "agents", "tools", "analysis_tools.py"), encoding="utf-8").read()
    assert "**_flat_evidence(await market_evidence(ticker, state), exclude=news_payload)," in source   # write_report
    assert "**_flat_evidence(await market_evidence(ticker, state))," in source                         # build_model
    assert source.count("evidence=await market_evidence(ticker, state))") == 2                         # both refusals
