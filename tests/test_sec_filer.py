"""US filers are valued on their US line.

A foreign company is valued on its home listing, but not one whose main market
is the US. Volumes cannot tell Yum China (1.9x Hong Kong) from Infosys's busy
ADR (1.8x Mumbai); the SEC's filer status can: 10-K for a US domestic issuer,
20-F or 40-F for a foreign one.
"""
import json
import os
import sys
from types import SimpleNamespace

import pytest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "src"))

import src.listing_view as listing_view  # noqa: E402
import src.sec_filer as sec_filer  # noqa: E402
from src.agents.fm import netcache  # noqa: E402
from src.agents.tools.analysis_tools import AgentContext  # noqa: E402
from test_home_listing_valuation import TM, TOYOTA_TOKYO, _rate, _yahoo, ctx  # noqa: E402,F401

TICKERS = {"0": {"cik_str": 1673358, "ticker": "YUMC", "title": "Yum China Holdings, Inc."},
           "1": {"cik_str": 1067491, "ticker": "INFY", "title": "Infosys Ltd"},
           "2": {"cik_str": 1094517, "ticker": "TM", "title": "TOYOTA MOTOR CORP"}}
FORMS = {1673358: ["8-K", "10-Q", "10-K", "DEF 14A"], 1067491: ["6-K", "6-K", "20-F"], 1094517: ["6-K", "20-F"]}


@pytest.fixture
def sec(monkeypatch):
    fetched = []

    def http_get(url, timeout=8.0):
        fetched.append(url)
        if url.endswith("company_tickers.json"):
            return json.dumps(TICKERS).encode()
        cik = int(url.rsplit("CIK", 1)[1].split(".")[0])
        return json.dumps({"filings": {"recent": {"form": FORMS[cik]}}}).encode()

    monkeypatch.setattr(netcache, "http_get", http_get)
    return fetched


def test_a_10k_filer_is_a_us_company(sec):
    assert sec_filer.annual_form("YUMC") == "10-K"
    assert sec_filer.files_as_us_company("yumc") is True


def test_a_20f_filer_is_not(sec):
    assert sec_filer.files_as_us_company("INFY") is False
    assert sec_filer.files_as_us_company("TM") is False


def test_an_unknown_ticker_or_a_failed_fetch_is_unknown(sec, monkeypatch):
    assert sec_filer.files_as_us_company("NOPE") is None
    monkeypatch.setattr(netcache, "http_get", lambda url, timeout=8.0: (_ for _ in ()).throw(OSError("down")))
    assert sec_filer.files_as_us_company("TM") is None


def test_both_files_are_read_once(sec):
    sec_filer.files_as_us_company("YUMC")
    sec_filer.files_as_us_company("YUMC")
    assert len(sec) == 2                      # the ticker table and one company's filings


# --------------------------------------------------------------------------
# The moves
# --------------------------------------------------------------------------

def test_a_us_filers_us_line_does_not_move(monkeypatch):
    _yahoo(monkeypatch, {"7203.T": TOYOTA_TOKYO},
           [{"symbol": "7203.T", "quoteType": "EQUITY", "shortname": "TOYOTA MOTOR CORP"}])
    monkeypatch.setattr(sec_filer, "files_as_us_company", lambda ticker: True)
    assert listing_view.home_line_for("TM", TM, rate=_rate) is None
    monkeypatch.setattr(sec_filer, "files_as_us_company", lambda ticker: False)
    assert listing_view.home_line_for("TM", TM, rate=_rate)["symbol"] == "7203.T"


SHOP_TSX = {"longName": "Shopify Inc.", "country": "Canada", "currency": "CAD", "financialCurrency": "USD",
            "exchange": "TOR", "market": "ca_market", "marketCap": 1, "currentPrice": 204.2,
            "sharesOutstanding": 1219581025}
SHOP_NASDAQ = dict(SHOP_TSX, currency="USD", exchange="NMS", market="us_market", currentPrice=144.01)


def _us_line(monkeypatch, filer):
    monkeypatch.setattr(listing_view, "us_line_for",
                        lambda name, country, shares, implied=None:
                        {"symbol": "SHOP", "info": SHOP_NASDAQ, "ratio": 1.0})
    monkeypatch.setattr(sec_filer, "files_as_us_company", lambda ticker: filer if ticker == "SHOP" else None)
    monkeypatch.setattr(listing_view, "home_line_for", lambda ticker, info: None)


def test_a_named_us_filer_is_valued_on_its_us_line(monkeypatch, ctx):
    _yahoo(monkeypatch, {"SHOP.TO": SHOP_TSX}, [])
    _us_line(monkeypatch, True)
    ctx.user_prompt = "should i buy Shopify?"
    state = ctx.ensure_state_for_ticker("SHOP.TO")
    assert state.ticker == "SHOP"
    assert ctx.ensure_state_for_ticker("SHOP.TO") is state


def test_a_typed_foreign_ticker_is_valued_as_typed(monkeypatch, ctx):
    _yahoo(monkeypatch, {"SHOP.TO": SHOP_TSX}, [])
    _us_line(monkeypatch, True)
    ctx.user_prompt = "should i buy SHOP.TO?"
    assert ctx.ensure_state_for_ticker("SHOP.TO").ticker == "SHOP.TO"


def test_a_named_foreign_filer_stays_on_its_home_line(monkeypatch, ctx):
    _yahoo(monkeypatch, {"SHOP.TO": SHOP_TSX}, [])
    _us_line(monkeypatch, False)
    ctx.user_prompt = "should i buy Shopify?"
    assert ctx.ensure_state_for_ticker("SHOP.TO").ticker == "SHOP.TO"


def test_the_currency_swap_leaves_a_us_filer_alone(monkeypatch, ctx):
    # A US filer reporting in another currency is still valued on its US line.
    logi = {"longName": "Logitech International S.A.", "country": "Switzerland", "currency": "USD",
            "financialCurrency": "CHF", "exchange": "NMS", "marketCap": 1, "currentPrice": 90.0,
            "averageVolume": 900000, "sharesOutstanding": 150000000}
    zurich = dict(logi, currency="CHF", exchange="EBS", market="ch_market", averageVolume=800000)
    _yahoo(monkeypatch, {"LOGI": logi, "LOGN.SW": zurich},
           [{"symbol": "LOGN.SW", "quoteType": "EQUITY", "shortname": "LOGITECH N"}])
    monkeypatch.setattr(listing_view, "home_line_for", lambda ticker, info: None)
    monkeypatch.setattr(sec_filer, "files_as_us_company", lambda ticker: True)
    assert ctx.ensure_state_for_ticker("LOGI").ticker == "LOGI"
    monkeypatch.setattr(sec_filer, "files_as_us_company", lambda ticker: False)
    ctx2 = AgentContext(email="t@vynn.ai", timestamp="t", user_prompt="should i buy LOGI?")
    assert ctx2.ensure_state_for_ticker("LOGI").ticker == "LOGN.SW"
