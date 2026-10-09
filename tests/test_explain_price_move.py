"""
"Why did Cerebras crash" (2026-10-08): the answer used today's quote and six
Yahoo titles, found "no clear catalyst", and after the bell even reported the
previous day's -1.2% as today's move. These pin the pieces that replace it.
"""

import asyncio
import json
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd
import pytest

from src import company_news, price_moves, sec_activity
from src.agents.tools import data_tools, move_tools, yf_resilience

# Cerebras daily closes and volumes, 2026-09-03 .. 2026-10-08 (Yahoo).
_DAYS = ["2026-09-03", "2026-09-04", "2026-09-08", "2026-09-09", "2026-09-10", "2026-09-11",
         "2026-09-14", "2026-09-15", "2026-09-16", "2026-09-17", "2026-09-18", "2026-09-21",
         "2026-09-22", "2026-09-23", "2026-09-24", "2026-09-25", "2026-09-28", "2026-09-29",
         "2026-09-30", "2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06", "2026-10-07",
         "2026-10-08"]
_CLOSES = [190.44, 210.05, 199.77, 196.20, 191.34, 191.93, 181.21, 184.03, 190.47, 194.14,
           198.37, 208.49, 212.41, 205.24, 206.41, 206.75, 196.74, 194.95, 177.65, 169.52,
           166.43, 181.55, 177.10, 175.05, 167.92]
_VOLUMES = [4959400, 13761600, 7994400, 4271500, 3404300, 3409800, 5221800, 3563100, 5042800,
            5312600, 10804200, 6890200, 6073400, 3837200, 3178900, 5639500, 5210500, 9465400,
            13896800, 12203300, 12525800, 15493300, 9434000, 5368200, 10029591]


def _daily(closes=_CLOSES, days=_DAYS, volumes=_VOLUMES, first=None):
    """Daily bars; ``first`` prepends a listing-day bar (a recent IPO)."""
    idx = pd.DatetimeIndex(pd.to_datetime(days)).tz_localize("America/New_York")
    frame = pd.DataFrame({"Close": closes, "Volume": volumes}, index=idx, dtype=float)
    frame["High"] = frame["Low"] = frame["Close"]
    if first is not None:
        padding = pd.date_range("2026-05-14", periods=60, freq="B", tz="America/New_York")
        pre = pd.DataFrame({"Close": np.linspace(first, closes[0], 60), "Volume": 5e6}, index=padding)
        pre["High"] = pre["Low"] = pre["Close"]
        frame = pd.concat([pre, frame])
    return frame


def _evening(frame):
    """The same bars as Yahoo serves them after the close: today's has no Close."""
    out = frame.copy()
    out.iloc[-1, out.columns.get_loc("Close")] = np.nan
    return out


# --- the quote after the bell ------------------------------------------------

def test_a_bar_without_a_close_makes_the_last_close_the_previous_close():
    closes = _evening(_daily())["Close"]
    assert price_moves.latest_and_previous_close(closes, live_price=167.92) == (167.92, 175.05)
    # During the session (or a closed bar) nothing changes.
    assert price_moves.latest_and_previous_close(_daily()["Close"]) == (167.92, 175.05)


def test_get_prices_reports_todays_move_after_the_bell(monkeypatch):
    evening = _evening(_daily())
    monkeypatch.setattr(yf_resilience, "fetch_history", lambda *a, **k: evening)
    monkeypatch.setattr(yf_resilience, "fetch_spot", lambda symbol: 167.92)
    monkeypatch.setattr(data_tools, "listing_identity", lambda t: ("Cerebras Systems Inc.", "USD"))
    out = json.loads(asyncio.run(data_tools.GetPricesTool().execute("CBRS", period="1mo")))
    # Was latest 175.05 (October 7's close), previous 177.10, "-1.16% today".
    assert (out["latest_price"], out["previous_close"], out["day_change_pct"]) == (167.92, 175.05, -4.07)


def test_fetch_spot_asks_for_the_live_price_when_todays_bar_has_no_close(monkeypatch):
    evening = _evening(_daily())
    monkeypatch.setattr(yf_resilience, "fetch_history", lambda *a, **k: evening)

    class _Ticker:
        def __init__(self, symbol):
            self.fast_info = type("F", (), {"last_price": 167.92})()

    import yfinance
    monkeypatch.setattr(yfinance, "Ticker", _Ticker)
    assert yf_resilience.fetch_spot("CBRS") == 167.92


# --- the move -----------------------------------------------------------------

def test_the_crash_is_the_slide_not_todays_tick():
    sp500 = pd.Series(np.linspace(6000, 5970, len(_DAYS)), index=_daily().index)
    move = price_moves.describe_move(_evening(_daily(first=311.07)), 167.92, window="1mo",
                                     direction="down", history_days_requested=730,
                                     index_closes=sp500)
    episode = move["episode"]
    assert (episode["start_date"], episode["start_close"]) == ("2026-09-22", 212.41)
    assert (episode["end_date"], episode["end_close"]) == ("2026-10-02", 166.43)
    assert episode["change_pct"] == -21.65 and episode["sessions"] == 8
    assert episode["since_end_pct"] == 0.9
    assert -1 < episode["sp500_same_dates_pct"] < 0     # the market was roughly flat
    assert move["day_change_pct"] == -4.07                # today still counts
    days = {d["date"]: d for d in move["biggest_days"]}
    assert days["2026-09-30"]["change_pct"] == -8.87 and days["2026-09-30"]["volume_vs_average"] >= 1.5
    assert "2026-10-08" in [d["date"] for d in price_moves.biggest_days(
        price_moves.with_live_close(_evening(_daily()), 120.0), 21)]   # a live crash today shows up
    # A recent IPO: its first close is part of the story.
    assert move["listed_since"] == "2026-05-14" and move["first_close"] == 311.07
    assert move["since_first_close_pct"] == -46.02


def test_direction_auto_takes_the_larger_swing():
    closes = pd.Series([100, 90, 95, 140, 120], index=pd.date_range("2026-01-01", periods=5))
    assert price_moves.largest_swing(closes, "down")["change_pct"] == -14.29
    assert price_moves.largest_swing(closes, "up")["change_pct"] == 55.56
    frame = pd.DataFrame({"Close": closes, "Volume": 1.0})
    assert price_moves.describe_move(frame, None, window="5d")["episode"]["direction"] == "up"


# --- the news -----------------------------------------------------------------

def test_company_names_drop_the_legal_suffixes():
    assert company_news.company_names("Cerebras Systems Inc.", "CBRS") == ["CBRS", "Cerebras"]
    assert company_news.company_names("Micron Technology, Inc.", "MU") == ["MU", "Micron"]
    assert company_news.company_names("Advanced Micro Devices, Inc.", "AMD") == ["AMD", "Advanced Micro Devices"]
    assert not company_news._mentions("You MUST read this", ["MU"])


def test_after_close_news_belongs_to_the_next_session():
    sessions = ["2026-09-30", "2026-10-01", "2026-10-02", "2026-10-05"]
    et = lambda s: datetime.fromisoformat(s + "-04:00")
    assert company_news.session_for(et("2026-09-30T10:28:00"), sessions) == "2026-09-30"
    assert company_news.session_for(et("2026-09-30T07:00:00"), sessions) == "2026-09-30"
    assert company_news.session_for(et("2026-09-30T18:13:00"), sessions) == "2026-10-01"
    assert company_news.session_for(et("2026-10-03T12:00:00"), sessions) == "2026-10-05"   # Saturday
    assert company_news.session_for(et("2026-10-05T17:00:00"), sessions) is None


def _row(when, headline, summary="", source="Yahoo"):
    stamp = datetime.fromisoformat(when + "-04:00").timestamp()
    return {"datetime": stamp, "headline": headline, "summary": summary, "source": source, "url": "u"}


def test_the_stories_that_moved_the_stock_lead_their_session():
    rows = [
        _row("2026-09-30T10:28:00", "Cerebras Stock Falls as 19.4 Million-Share Unlock Hits",
             "Shares are trading lower as a new wave of shares hits the market.", "Benzinga"),
        _row("2026-09-30T14:24:00", "Cerebras stock slides as Nvidia reportedly powers OpenAI's 'Ultrafast' tier",
             "Shares tumbled 7% following speculation OpenAI bypassed the startup's hardware."),
        _row("2026-09-30T15:10:00", "Cerebras shares slide as Nvidia reportedly powers OpenAI's Ultrafast tier",
             "", "Investing.com"),
        _row("2026-09-30T21:09:00", "Moderna, Cerebras, Jabil, HPE and More Stocks That Explain Today's Market",
             "Moderna falls after Citi downgrades shares."),
        _row("2026-09-30T11:00:00", "OpenAI's Dots connect to 4,000 apps and never sleep",
             "OpenAI just unveiled Dots."),
        _row("2026-09-29T01:19:00", "Cerebras Systems vs. IonQ: Which Technology Stock Is a Better Buy in 2026?"),
    ]
    items = company_news.normalize_finnhub(rows)
    out = company_news.rank_and_align(items, ["CBRS", "Cerebras"],
                                      ["2026-09-29", "2026-09-30", "2026-10-01"], ["2026-09-30"])
    assert out["articles_considered"] == 6 and out["articles_about_company"] == 5   # Dots is not about Cerebras
    sessions = {s["session"]: s for s in out["by_session"]}
    sept30 = sessions["2026-09-30"]
    assert sept30["big_move_day"]
    titles = [a["title"] for a in sept30["articles"]]
    assert titles[0].startswith("Cerebras stock slides") or titles[0].startswith("Cerebras Stock Falls")
    # Two outlets carried the Ultrafast story: one item, counted twice.
    ultrafast = next(a for a in sept30["articles"] if "Ultrafast" in a["title"])
    assert ultrafast["outlets"] == 2
    # The roundup moved to the next session (after the close) and ranks last there.
    assert sessions["2026-10-01"]["articles"][0]["title"].startswith("Moderna")


def test_news_falls_back_to_yahoo_without_finnhub(monkeypatch):
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    monkeypatch.setattr(company_news, "yahoo_items", lambda t, count=10: company_news.normalize_finnhub(
        [_row("2026-10-08T13:36:58", "Cerebras Stock Has Been a Bust Since Its IPO")]))
    out = company_news.news_for_move("CBRS", "Cerebras Systems Inc.", date(2026, 9, 19), date(2026, 10, 8),
                                     ["2026-10-08"], [])
    assert out["source"].startswith("Yahoo") and out["by_session"][0]["articles"][0]["title"].startswith("Cerebras")


# --- the filings --------------------------------------------------------------

_F144 = """<?xml version="1.0"?><edgarSubmission xmlns="http://www.sec.gov/edgar/ownership"><formData>
<issuerInfo><nameOfPersonForWhoseAccountTheSecuritiesAreToBeSold>A SELLER</nameOfPersonForWhoseAccountTheSecuritiesAreToBeSold>
<relationshipsToIssuer><relationshipToIssuer>Officer</relationshipToIssuer></relationshipsToIssuer></issuerInfo>
<securitiesInformation><noOfUnitsSold>396000</noOfUnitsSold><aggregateMarketValue>77909040.00</aggregateMarketValue>
<approxSaleDate>09/29/2026</approxSaleDate></securitiesInformation></formData></edgarSubmission>"""

_F4 = """<?xml version="1.0"?><ownershipDocument><reportingOwner><reportingOwnerId><rptOwnerName>An Officer</rptOwnerName></reportingOwnerId>
<reportingOwnerRelationship><isDirector>0</isDirector><isOfficer>1</isOfficer><officerTitle>CFO</officerTitle></reportingOwnerRelationship></reportingOwner>
<nonDerivativeTable><nonDerivativeTransaction><transactionDate><value>2026-09-30</value></transactionDate>
<transactionCoding><transactionCode>S</transactionCode></transactionCoding><transactionAmounts>
<transactionShares><value>10000</value></transactionShares><transactionPricePerShare><value>180.50</value></transactionPricePerShare>
<transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode></transactionAmounts></nonDerivativeTransaction>
</nonDerivativeTable></ownershipDocument>"""


def test_filings_say_who_filed_to_sell_and_what_was_sold(monkeypatch, tmp_path):
    from src import sec_filer
    from src.agents.fm import netcache
    monkeypatch.setenv("VYNN_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(sec_filer, "_ciks", lambda: {"CBRS": 2021728})
    recent = {
        "accessionNumber": ["0001-26-1", "0002-26-2", "0003-26-3", "0004-26-4"],
        "filingDate": ["2026-09-29", "2026-09-30", "2026-10-01", "2026-08-01"],
        "form": ["144", "4", "8-K", "144"],
        "items": ["", "", "5.02,9.01", ""],
        "primaryDocument": ["xsl144X01/primary_doc.xml", "xslF345X06/f4.xml", "d8k.htm", "xsl144X01/old.xml"],
    }
    docs = {"primary_doc.xml": _F144, "f4.xml": _F4}

    def http_get(url, timeout=8.0):
        if "submissions" in url:
            return json.dumps({"filings": {"recent": recent}}).encode()
        name = url.rsplit("/", 1)[-1]
        assert "xsl" not in url        # the raw XML, not the rendered page
        return docs[name].encode()

    monkeypatch.setattr(netcache, "http_get", http_get)
    out = sec_activity.filing_activity("CBRS", date(2026, 9, 25), date(2026, 10, 8))
    assert out["counts"] == {"144": 1, "4": 1, "8-K": 1}           # August is outside the window
    notices = out["form144_notices"]
    assert notices["shares"] == 396000 and notices["market_value"] == 77909040.0
    assert notices["largest"][0]["relationship"] == "Officer"
    sale = out["form4_transactions"]["by_code"]["S/D"]
    assert sale["shares"] == 10000 and sale["value_usd"] == 1805000.0 and sale["meaning"].endswith("sale")
    assert out["form4_transactions"]["top_sellers"][0]["role"] == "CFO"
    assert out["other_filings"] == [{"filed": "2026-10-01", "form": "8-K", "items": ["5.02 director or officer change"]}]
    assert "intent" in out["form_meanings"]["144"]


# --- the tool, the card, the prompt --------------------------------------------

def test_the_tool_reads_news_and_filings_for_the_sessions_that_moved(monkeypatch):
    evening = _evening(_daily(first=311.07))
    monkeypatch.setattr(yf_resilience, "fetch_history", lambda symbol, period, **k: evening)
    monkeypatch.setattr(move_tools, "_live_price", lambda t: 167.92)
    monkeypatch.setattr(data_tools, "listing_identity", lambda t: ("Cerebras Systems Inc.", "USD"))
    asked = {}

    def news(ticker, name, start, end, sessions, focus):
        asked.update(start=start, focus=focus)
        return {"source": "test", "by_session": []}

    monkeypatch.setattr(company_news, "news_for_move", news)
    monkeypatch.setattr(sec_activity, "filing_activity", lambda t, s, e: {"counts": {"144": 3}})
    out = json.loads(asyncio.run(move_tools.ExplainPriceMoveTool().execute("CBRS", direction="down")))
    assert out["status"] == "ok" and out["episode"]["start_date"] == "2026-09-22"
    assert out["latest_price"] == 167.92 and out["day_change_pct"] == -4.07
    assert asked["start"] <= date(2026, 9, 19) and "2026-09-30" in asked["focus"]
    assert out["sec_filings"]["counts"] == {"144": 3}


def test_the_findings_show_the_move_and_its_headline():
    from src.agents.findings import extract_findings
    result = {"status": "ok", "episode": {"change_pct": -21.65, "start_date": "2026-09-22", "end_date": "2026-10-02"},
              "news": {"by_session": [
                  {"session": "2026-09-29", "big_move_day": False, "articles": [{"title": "Cerebras vs. IonQ"}]},
                  {"session": "2026-09-30", "big_move_day": True,
                   "articles": [{"title": "Cerebras Stock Falls as 19.4 Million-Share Unlock Hits"}]}]}}
    cards = extract_findings("explain_price_move", result)
    assert [(c["label"], c["value"]) for c in cards][:2] == [
        ("The move", "-21.7%"), ("Key headline", "Cerebras Stock Falls as 19.4 Million-Share Unlock Hits")]
    assert cards[0]["sub"] == "Sep 22 → Oct 2"


def test_the_agent_is_told_to_explain_the_move_not_todays_tick():
    from src.agents.generalist_agent import SYSTEM_PROMPT
    assert "call `explain_price_move`" in SYSTEM_PROMPT
    assert "Never call a Form 144 a sale" in SYSTEM_PROMPT
    assert 'Do not ask "today or since the IPO?"' in SYSTEM_PROMPT
