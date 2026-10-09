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
    monkeypatch.setattr(yf_resilience, "live_price", lambda symbol: 167.92)
    monkeypatch.setattr(data_tools, "listing_identity", lambda t: ("Cerebras Systems Inc.", "USD"))
    out = json.loads(asyncio.run(data_tools.GetPricesTool().execute("CBRS", period="1mo")))
    # Was latest 175.05 (October 7's close), previous 177.10, "-1.16% today".
    assert (out["latest_price"], out["previous_close"], out["day_change_pct"]) == (167.92, 175.05, -4.07)
    # No live price at all: no change is reported, never yesterday's close as today's (a 0.0% day).
    monkeypatch.setattr(yf_resilience, "live_price", lambda symbol: None)
    monkeypatch.setattr(yf_resilience, "fetch_spot", lambda symbol: 175.05)
    out = json.loads(asyncio.run(data_tools.GetPricesTool().execute("CBRS", period="1mo")))
    assert out["previous_close"] == 175.05 and "day_change_pct" not in out and "not available" in out["note"]


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
    assert episode["market_index"] == "S&P 500"
    assert -1 < episode["market_same_dates_pct"] < 0     # the market was roughly flat
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


def test_a_coin_counts_calendar_days():
    # Bitcoin: 252 daily bars are 8.3 months, so the "52-week high" was the
    # September high, not the one in October of the year before.
    days = pd.date_range("2025-09-01", "2026-10-08", freq="D", tz="UTC")
    closes = np.full(len(days), 80000.0)
    closes[list(days.date).index(pd.Timestamp("2025-10-13").date())] = 115271.0
    frame = pd.DataFrame({"Close": closes, "Volume": 1e9, "High": closes, "Low": closes}, index=days)
    move = price_moves.describe_move(frame, None, window="1y")
    assert move["high_52w"] == 115271.0 and move["high_52w_date"] == "2025-10-13"
    assert price_moves.window_bars("1mo", frame["Close"]) == 30
    assert price_moves.window_bars("1mo", _daily()["Close"]) == 21


def test_window_aliases_and_ytd():
    assert price_moves.normalize_window("3M") == "3mo" and price_moves.normalize_window("ytd") == "ytd"
    assert price_moves.normalize_window("1W") == "5d" and price_moves.normalize_window("bogus") == "1mo"
    assert price_moves.describe_move(_daily(), None, window="3M")["window"] == "3mo"


def test_a_session_still_trading_has_partial_volume():
    days = price_moves.biggest_days(_daily(), 21, count=21, session_open=True)
    today = next(d for d in days if d["date"] == "2026-10-08")
    assert today["session_in_progress"] and "volume_vs_average" not in today
    assert "volume_so_far_vs_full_day_average" in today


def test_without_a_live_price_today_is_not_reported_as_moved():
    move = price_moves.describe_move(_evening(_daily()), None)
    assert move["latest_session_missing"] == "2026-10-08" and move["as_of_session"] == "2026-10-07"
    assert "not available" in move["note"]


def test_technicals_and_option_spot_survive_the_evening_bar(monkeypatch):
    long = _daily(first=311.07)
    evening = _evening(long)
    monkeypatch.setattr(yf_resilience, "fetch_history", lambda *a, **k: evening)
    monkeypatch.setattr(yf_resilience, "live_price", lambda symbol: 167.92)
    tech = json.loads(asyncio.run(data_tools.GetTechnicalsTool().execute("CBRS")))
    assert tech["latest_close"] == 167.92 and tech["sma_50"] is not None and tech["bollinger_upper"] == tech["bollinger_upper"]
    from src.agents.tools.capital_markets_tools import PriceOptionTool
    option = json.loads(asyncio.run(PriceOptionTool().execute(ticker="CBRS", strike=170, expiry_days=30,
                                                                option_type="call")))
    assert option["status"] == "ok" and option["spot"] == 167.92 and option["price"] == option["price"]


# --- the news -----------------------------------------------------------------

def test_company_names_are_what_headlines_call_the_company():
    names = company_news.company_names
    assert names("Cerebras Systems Inc.", "CBRS") == ["CBRS", "Cerebras"]
    assert names("Micron Technology, Inc.", "MU") == ["MU", "Micron"]
    assert names("Advanced Micro Devices, Inc.", "AMD") == ["AMD", "Advanced Micro Devices"]
    assert not company_news._mentions("You MUST read this", ["MU"])
    # Every Goldman Sachs and Boeing story was dropped: the names kept "The".
    assert company_news._mentions("Boeing Down 10.6% in a Month", names("The Boeing Company", "BA"))
    assert company_news._mentions("Goldman Sachs stock loses nearly all year-to-date gains",
                                  names("The Goldman Sachs Group, Inc.", "GS"))
    assert company_news._mentions("How Is Eli Lilly's Oncology Portfolio Shaping Up?",
                                  names("Eli Lilly and Company", "LLY"))
    assert company_news._mentions("Jeff Bezos explains why Amazon is still cutting jobs",
                                  names("Amazon.com, Inc.", "AMZN"))
    assert company_news._mentions("Google Raises Stakes in Enterprise AI Battle", names("Alphabet Inc.", "GOOGL"))
    assert "State" not in names("State Street SPDR S&P 500 ETF Trust", "SPY")


def test_one_story_needs_the_same_figures_and_direction():
    same = company_news._similar
    assert same("Cerebras stock slides as Nvidia reportedly powers OpenAI's 'Ultrafast' tier",
                "Cerebras shares slide as Nvidia reportedly powers OpenAI's Ultrafast tier")
    assert not same("Citigroup Adjusts Price Target on Super Micro Computer to $45",
                    "Mizuho Adjusts Price Target on Super Micro Computer to $43")
    assert not same("Robinhood Insider Sold Shares Worth $42,643,527",
                    "Robinhood Insider Sold Shares Worth $1,137,100")
    assert not same("Why Cerebras Stock Soared Today", "Why Cerebras Stock Plunged Today")


def test_sessions_follow_the_listings_own_close():
    et = lambda s: datetime.fromisoformat(s + "-04:00")
    us = ["2026-10-08", "2026-10-09"]
    # "Why Sandisk Stock Dropped on Thursday", 17:13 ET: about the day that closed.
    assert company_news.session_for(et("2026-10-08T17:13:00"), us, "Why Sandisk Stock Dropped on Thursday") == "2026-10-08"
    assert company_news.session_for(et("2026-10-08T17:13:00"), us, "Sandisk names a new CFO") == "2026-10-09"
    paris = ["2026-10-07", "2026-10-08"]
    at = lambda s: datetime.fromisoformat(s + "+02:00")
    assert company_news.session_for(at("2026-10-07T17:00:00"), paris, "", "Europe/Paris") == "2026-10-07"
    assert company_news.session_for(at("2026-10-07T19:00:00"), paris, "", "Europe/Paris") == "2026-10-08"
    coin = ["2026-10-07", "2026-10-08"]
    utc = lambda s: datetime.fromisoformat(s + "+00:00")
    assert company_news.session_for(utc("2026-10-07T21:30:00"), coin, "", "UTC") == "2026-10-07"


def test_finnhub_gets_the_key_in_a_header_and_us_spellings(monkeypatch):
    assert company_news.finnhub_symbol("BRK-B") == "BRK.B"
    assert company_news.finnhub_symbol("MC.PA") is None and company_news.finnhub_symbol("BTC-USD") is None
    seen = {}

    class _Response:
        status_code = 200

        def json(self):
            return []

    def get(url, params=None, timeout=None, headers=None):
        seen.update(url=url, params=params, headers=headers)
        return _Response()

    import requests
    monkeypatch.setattr(requests, "get", get)
    monkeypatch.setenv("FINNHUB_API_KEY", "k-secret")
    company_news.fetch_finnhub_news("BRK-B", date(2026, 10, 1), date(2026, 10, 8))
    assert seen["params"]["symbol"] == "BRK.B" and "token" not in seen["params"]
    assert seen["headers"]["X-Finnhub-Token"] == "k-secret" and "k-secret" not in seen["url"]


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
    # Published after the close about the close: it explains September 30,
    # and as a roundup it ranks last there.
    assert sept30["articles"][-1]["title"].startswith("Moderna")
    assert "2026-10-01" not in sessions


def test_busy_rally_days_cannot_crowd_out_the_selloff_day():
    # SNDK, October 8: five big-move days (mostly September rallies) with
    # heavy coverage took every slot; October 7's "Toshiba storage fears"
    # story behind the current selloff never reached the model, and quiet
    # sessions came back as empty lists.
    rally_days = ["2026-09-14", "2026-09-17", "2026-09-18", "2026-09-22", "2026-10-08"]
    words = ("alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima mike "
             "november oscar papa quebec romeo sierra tango uniform victor whiskey xray yankee "
             "zulu amber birch cedar dune ember fjord").split()
    rows = []
    for d, day in enumerate(rally_days):
        for k in range(6):     # six distinct stories each day, all inside the session
            a, b, c = (words[(d * 6 + k + j * 11) % len(words)] for j in range(3))
            rows.append(_row(f"{day}T{9 + k:02d}:00:00", f"Sandisk {a} {b} {c}"))
    # Named only in the summary: it ranks below every headline that names the company.
    rows.append(_row("2026-10-07T09:00:00", "Memory stocks decline on Toshiba storage fears",
                     "Micron, Sandisk and SK Hynix fell after a report on Toshiba capacity."))
    rows.append(_row("2026-10-01T09:00:00", "Sandisk quiet-day note"))
    sessions = ["2026-09-14", "2026-09-17", "2026-09-18", "2026-09-22", "2026-10-01", "2026-10-07", "2026-10-08"]
    out = company_news.rank_and_align(company_news.normalize_finnhub(rows), ["SNDK", "Sandisk"], sessions,
                                      rally_days, max_items=12, recent_sessions=["2026-10-07", "2026-10-08"])
    by = {s["session"]: s["articles"] for s in out["by_session"]}
    assert by["2026-10-07"][0]["title"].startswith("Memory stocks decline on Toshiba")
    assert all(articles for articles in by.values())            # no empty sessions
    assert sum(len(a) for a in by.values()) <= 12
    assert all(len(by[d]) >= 2 for d in rally_days)
    # The same headline days apart is two days' news.
    again = company_news.rank_and_align(company_news.normalize_finnhub([
        _row("2026-09-30T10:00:00", "Cerebras stock falls again on OpenAI worries"),
        _row("2026-10-02T10:00:00", "Cerebras stock falls again on OpenAI worries")]),
        ["Cerebras"], ["2026-09-30", "2026-10-02"])
    assert [s["session"] for s in again["by_session"]] == ["2026-09-30", "2026-10-02"]


def test_news_falls_back_to_yahoo_without_finnhub(monkeypatch):
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    monkeypatch.setattr(company_news, "yahoo_items", lambda t, count=10: company_news.normalize_finnhub(
        [_row("2026-10-08T13:36:58", "Cerebras Stock Has Been a Bust Since Its IPO")]))
    out = company_news.news_for_move("CBRS", "Cerebras Systems Inc.", date(2026, 9, 19), date(2026, 10, 8),
                                     ["2026-10-08"], [])
    assert out["source"].startswith("Yahoo") and out["by_session"][0]["articles"][0]["title"].startswith("Cerebras")
    # The feed reaches back to October 8 only: earlier sessions are outside it.
    assert out["coverage"] == {"earliest": "2026-10-08", "latest": "2026-10-08"}


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
    assert "partial" not in notices
    assert sec_activity.FORM_MEANINGS["SCHEDULE 13D"].startswith("5%+")
    # More notices than are read (CoreWeave filed 73 in two months): the totals say so.
    recent["accessionNumber"].append("0005-26-5"); recent["filingDate"].append("2026-09-30")
    recent["form"].append("144"); recent["items"].append(""); recent["primaryDocument"].append("xsl144X01/primary_doc.xml")
    monkeypatch.setattr(sec_activity, "_MAX_DOCUMENTS", 1)
    monkeypatch.setattr(netcache, "cache_get", lambda name, age: None)
    capped = sec_activity.filing_activity("CBRS", date(2026, 9, 25), date(2026, 10, 8))
    assert capped["counts"]["144"] == 2
    assert capped["form144_notices"]["partial"] == "totals cover 1 of 2 filings (the newest)"


# --- the tool, the card, the prompt --------------------------------------------

def test_the_tool_reads_news_and_filings_for_the_sessions_that_moved(monkeypatch):
    evening = _evening(_daily(first=311.07))
    sp500 = _evening(_daily())
    sp500["Close"] = np.linspace(6000, 5970, len(sp500))
    sp500.iloc[-1, sp500.columns.get_loc("Close")] = np.nan
    smh = sp500.copy()
    frames = {"CBRS": evening, "^GSPC": sp500, "SMH": smh}
    monkeypatch.setattr(yf_resilience, "fetch_history", lambda symbol, period, **k: frames[symbol])
    monkeypatch.setattr(move_tools, "_live_price", lambda t: {"CBRS": 167.92, "^GSPC": 5940.0, "SMH": 297.0}[t])
    monkeypatch.setattr(move_tools, "_identity", lambda t: {
        "name": "Cerebras Systems Inc.", "currency": "USD", "sector": "Technology",
        "industry": "Semiconductors", "exchange_tz": "America/New_York", "quote_type": "EQUITY"})
    asked = {}

    def news(ticker, name, start, end, sessions, focus, recent, exchange_tz, require_name):
        asked.update(start=start, focus=focus, recent=recent, tz=exchange_tz, require_name=require_name)
        return {"source": "test", "by_session": []}

    monkeypatch.setattr(company_news, "news_for_move", news)
    monkeypatch.setattr(sec_activity, "filing_activity", lambda t, s, e: {"counts": {"144": 3}})
    out = json.loads(asyncio.run(move_tools.ExplainPriceMoveTool().execute("CBRS", direction="down")))
    assert out["status"] == "ok" and out["episode"]["start_date"] == "2026-09-22"
    assert out["latest_price"] == 167.92 and out["day_change_pct"] == -4.07
    assert asked["start"] <= date(2026, 9, 19) and "2026-09-30" in asked["focus"]
    assert asked["recent"] == ["2026-10-07", "2026-10-08"]
    assert out["sec_filings"]["counts"] == {"144": 3}
    # The market and the sector after the bell: today's live level, not
    # yesterday's close (the evening bars have no Close).
    assert out["market_today"]["index_today_pct"] == round((5940.0 / sp500["Close"].iloc[-2] - 1) * 100, 2)
    assert asked["tz"] == "America/New_York" and asked["require_name"]
    assert out["sector_fund"]["symbol"] == "SMH" and "SMH_today_pct" in out["market_today"]
    assert out["from_window_high"]["date"] == "2026-09-22"


def test_each_listing_is_measured_against_its_own_market():
    assert move_tools.market_index("MC.PA") == ("^FCHI", "CAC 40")
    assert move_tools.market_index("7203.T") == ("^N225", "Nikkei 225")
    assert move_tools.market_index("ETH-USD") == ("BTC-USD", "Bitcoin")
    assert move_tools.market_index("CBRS") == ("^GSPC", "S&P 500")
    from datetime import datetime
    from zoneinfo import ZoneInfo
    tokyo_morning = datetime(2026, 10, 9, 9, 41, tzinfo=ZoneInfo("Asia/Tokyo"))
    assert move_tools.session_open("2026-10-09", "Asia/Tokyo", tokyo_morning)
    assert not move_tools.session_open("2026-10-08", "America/New_York",
                                       datetime(2026, 10, 8, 20, 0, tzinfo=ZoneInfo("America/New_York")))
    assert not move_tools.session_open("2026-10-08", "UTC")


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
