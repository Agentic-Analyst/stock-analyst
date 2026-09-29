"""A foreign company is valued on its home listing and answered in the user's.

A US line regresses against the S&P 500, which it barely moves with:
AstraZeneca's NYSE shares gave a beta of 0.50 against 0.96 for London, and the
same model published a $159.47 fair value on one and withheld a $106.61 one on
the other. So a US line (AZN, TM, SHEL) is valued on the home line, and the
answer is stated back per US share in dollars; a company the user named rather
than typed is answered per share of its US-exchange line when it has one.

Payloads are the live API's on 2026-09-28, trimmed to the fields read.
"""
import asyncio
import json
import os
import sys
import types
from types import SimpleNamespace

import pytest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "src"))

import src.listing_view as listing_view  # noqa: E402
from src.listing_view import (  # noqa: E402
    build_view, home_line_for, lead_paragraph, per_us_share, price_premium,
    quote_unit_supported, receipt_ratio, view_figures,
)
from src.agents.tools import analysis_tools, data_tools  # noqa: E402
from src.agents.tools.analysis_tools import AgentContext, market_evidence  # noqa: E402
from src.agents.supervisor.supervisor_agent import SupervisorWorkflowRunner  # noqa: E402
from agents.findings import extract_findings  # noqa: E402
from test_guarded_answer_keeps_analysis import _chat_agent, _published_state, _withheld_state  # noqa: E402

TM = {"longName": "Toyota Motor Corporation", "country": "Japan", "currency": "USD",
      "financialCurrency": "JPY", "exchange": "NYQ", "fullExchangeName": "NYSE", "market": "us_market",
      "quoteType": "EQUITY", "currentPrice": 188.3, "marketCap": 222981734400,
      "sharesOutstanding": 1184183366, "impliedSharesOutstanding": 1184183366}
TOYOTA_TOKYO = {"longName": "Toyota Motor Corporation", "country": "Japan", "currency": "JPY",
                "financialCurrency": "JPY", "exchange": "JPX", "market": "jp_market",
                "quoteType": "EQUITY", "currentPrice": 2986.5, "marketCap": 35365637324800,
                "sharesOutstanding": 11841833660, "averageVolume": 25000000}
AZN = {"longName": "AstraZeneca PLC", "country": "United Kingdom", "currency": "USD",
       "financialCurrency": "USD", "exchange": "NYQ", "fullExchangeName": "NYSE", "market": "us_market",
       "quoteType": "EQUITY", "currentPrice": 166.15, "marketCap": 257681342464,
       "sharesOutstanding": 1550895914}
AZN_LONDON = {"longName": "AstraZeneca PLC", "country": "United Kingdom", "currency": "GBp",
              "financialCurrency": "USD", "exchange": "LSE", "market": "gb_market",
              "quoteType": "EQUITY", "currentPrice": 12492.0, "marketCap": 193737916416,
              "sharesOutstanding": 1550895914, "averageVolume": 2000000}
TEVA = {"longName": "Teva Pharmaceutical Industries Limited", "country": "Israel", "currency": "USD",
        "financialCurrency": "USD", "exchange": "NYQ", "market": "us_market", "currentPrice": 38.88,
        "marketCap": 45345456128, "sharesOutstanding": 1166292643}
TEVA_TEL_AVIV = {"longName": "Teva Pharmaceutical Industries Limited", "country": "Israel",
                 "currency": "ILA", "financialCurrency": "USD", "exchange": "TLV", "market": "il_market",
                 "currentPrice": 11840.0, "marketCap": 45000000000, "sharesOutstanding": 1166292643}

RATES = {("JPY", "USD"): 1 / 157.38, ("GBP", "USD"): 1.32561, ("TWD", "USD"): 0.031466,
         # An agorot rate as if one were quoted: only the unit rule stops Tel Aviv.
         ("ILA", "USD"): 0.0027,
         ("EUR", "USD"): 1.1378, ("EUR", "JPY"): 179.05}


def _rate(a, b):
    return 1.0 if a == b else RATES.get((a, b))


def _yahoo(monkeypatch, universe, quotes):
    class _Search:
        def __init__(self, query, max_results=8):
            self.quotes = quotes

    class _Ticker:
        def __init__(self, symbol):
            self.info = universe.get(symbol, {})

    module = types.ModuleType("yfinance")
    module.Search, module.Ticker = _Search, _Ticker
    monkeypatch.setitem(sys.modules, "yfinance", module)


# --------------------------------------------------------------------------
# The receipt ratio
# --------------------------------------------------------------------------

def test_the_ratio_comes_from_the_share_counts():
    assert receipt_ratio((11841833660, 1184183366)) == 10.0          # Toyota
    assert receipt_ratio((25932370065, 5186474013)) == 5.0           # TSMC
    assert receipt_ratio((1.0, 3.0)) == pytest.approx(1 / 3)         # one share per three ADRs


def test_an_unclean_quotient_is_no_ratio():
    # TSMC's price quotient (5.82) is not a ratio: its ADR trades at a premium.
    assert receipt_ratio((5.82, 1.0)) is None
    assert receipt_ratio((None, 1.0), (0, 1.0)) is None


def test_only_ratios_in_use_count():
    # Past twenty, a relative tolerance lets any quotient round to a whole
    # number; only the ratios depositaries use are taken.
    assert receipt_ratio((137.4, 1.0)) is None
    assert receipt_ratio((1.0, 150.6)) is None
    assert receipt_ratio((100.2, 1.0)) == 100.0          # Telkom Indonesia
    assert receipt_ratio((1.0, 4.0)) == 0.25             # POSCO


def test_the_implied_count_is_the_fallback():
    assert receipt_ratio((None, 1184183366), (11841833660, 1184183366)) == 10.0


def test_the_price_premium_of_an_adr():
    # TSM $452.88 against five Taiwan shares at NT$2,475 (US$77.88 each).
    assert price_premium(452.88, 2475.0 * 0.031466, 5) == pytest.approx(0.163, abs=0.002)


@pytest.mark.parametrize("currency, ok", [("USD", True), ("GBp", True), ("JPY", True),
                                          ("ILA", False), ("ZAc", False), (None, False)])
def test_quote_units_the_scraper_reads(currency, ok):
    assert quote_unit_supported(currency) is ok


# --------------------------------------------------------------------------
# Which US lines move
# --------------------------------------------------------------------------

def _toyota_yahoo(monkeypatch, home=TOYOTA_TOKYO):
    _yahoo(monkeypatch, {"7203.T": home},
           [{"symbol": "7203.T", "quoteType": "EQUITY", "shortname": "TOYOTA MOTOR CORP"}])


def test_a_us_line_moves_to_its_home_line_with_the_ratio(monkeypatch):
    _toyota_yahoo(monkeypatch)
    home = home_line_for("TM", TM, rate=_rate)
    assert (home["symbol"], home["ratio"]) == ("7203.T", 10.0)


def test_a_same_currency_us_line_moves_too(monkeypatch):
    # AstraZeneca's NYSE shares report and trade in dollars; the old currency
    # rule never moved them, and their S&P 500 beta was 0.50.
    _yahoo(monkeypatch, {"AZN.L": AZN_LONDON},
           [{"symbol": "AZN.L", "quoteType": "EQUITY", "shortname": "ASTRAZENECA PLC ORD SHS $0.25"}])
    home = home_line_for("AZN", AZN, rate=_rate)
    assert (home["symbol"], home["ratio"]) == ("AZN.L", 1.0)


def test_a_line_quoted_in_agorot_does_not_move(monkeypatch):
    _yahoo(monkeypatch, {"TEVA.TA": TEVA_TEL_AVIV},
           [{"symbol": "TEVA.TA", "quoteType": "EQUITY", "shortname": "TEVA"}])
    assert home_line_for("TEVA", TEVA, rate=_rate) is None


def test_a_us_company_does_not_move(monkeypatch):
    _toyota_yahoo(monkeypatch)
    assert home_line_for("TM", dict(TM, country="United States"), rate=_rate) is None


def test_no_move_without_a_clean_ratio(monkeypatch):
    _toyota_yahoo(monkeypatch, home=dict(TOYOTA_TOKYO, sharesOutstanding=12500000000))
    assert home_line_for("TM", TM, rate=_rate) is None


def test_no_move_when_the_prices_disagree(monkeypatch):
    # A ratio of 10 with a Tokyo price half the ADR's is a unit or identity error.
    _toyota_yahoo(monkeypatch, home=dict(TOYOTA_TOKYO, currentPrice=1400.0))
    assert home_line_for("TM", TM, rate=_rate) is None


def test_no_move_when_the_home_price_cannot_be_converted(monkeypatch):
    _yahoo(monkeypatch, {"AZN.L": AZN_LONDON},
           [{"symbol": "AZN.L", "quoteType": "EQUITY", "shortname": "ASTRAZENECA PLC"}])
    no_gbp_usd = lambda a, b: None if (a, b) == ("GBP", "USD") else _rate(a, b)  # noqa: E731
    assert home_line_for("AZN", AZN, rate=no_gbp_usd) is None


def test_a_cross_listing_that_is_not_home_does_not_move(monkeypatch):
    # Priced in euros at Toyota's value, with an exchange rate: only the home
    # check stands between TM and a Frankfurt line.
    frankfurt = dict(TOYOTA_TOKYO, currency="EUR", exchange="FRA", market="de_market",
                     currentPrice=16.68)
    _yahoo(monkeypatch, {"TOM.F": frankfurt},
           [{"symbol": "TOM.F", "quoteType": "EQUITY", "shortname": "TOYOTA MOTOR CORP"}])
    assert home_line_for("TM", TM, rate=_rate) is None


# --------------------------------------------------------------------------
# ensure_state_for_ticker
# --------------------------------------------------------------------------

@pytest.fixture
def ctx(monkeypatch, tmp_path):
    import path_utils
    import logger as run_logger
    monkeypatch.setattr(path_utils, "get_analysis_path", lambda email, ticker, ts=None: tmp_path / ticker)
    monkeypatch.setattr(path_utils, "ensure_analysis_paths", lambda path: None)
    monkeypatch.setattr(run_logger, "setup_logger", lambda *a, **k: SimpleNamespace(info=lambda *_: None))
    return AgentContext(email="t@vynn.ai", timestamp="20260928_000000", user_prompt="should i buy TM?")


def test_the_context_values_the_home_line_and_remembers_the_asked_one(monkeypatch, ctx):
    _yahoo(monkeypatch, {"TM": TM}, [])
    monkeypatch.setattr(listing_view, "home_line_for", lambda ticker, info: {
        "symbol": "7203.T", "name": "Toyota Motor Corporation", "info": TOYOTA_TOKYO, "ratio": 10.0})
    state = ctx.ensure_state_for_ticker("tm")
    assert state.ticker == "7203.T"
    assert ctx._asked_listing["7203.T"]["symbol"] == "TM"
    assert ctx.ensure_state_for_ticker("TM") is state          # the second request lands on it


def test_a_move_onto_the_listing_already_analysed_keeps_its_state(monkeypatch, ctx):
    _yahoo(monkeypatch, {"TM": TM, "7203.T": TOYOTA_TOKYO}, [])
    monkeypatch.setattr(listing_view, "home_line_for", lambda ticker, info: (
        {"symbol": "7203.T", "name": "Toyota Motor Corporation", "info": TOYOTA_TOKYO, "ratio": 10.0}
        if ticker == "TM" else None))
    first = ctx.ensure_state_for_ticker("7203.T")
    first.financial_model = "built"
    assert ctx.ensure_state_for_ticker("TM") is first


SPOT = {"longName": "Spotify Technology S.A.", "country": "Sweden", "currency": "USD",
        "financialCurrency": "EUR", "exchange": "NYQ", "market": "us_market", "marketCap": 1,
        "currentPrice": 497.5, "averageVolume": 1694268, "sharesOutstanding": 205584205}
SPOT_FRANKFURT = dict(SPOT, currency="EUR", exchange="GER", market="de_market", currentPrice=437.3,
                      averageVolume=430)
STLA = {"longName": "Stellantis N.V.", "country": "Netherlands", "currency": "USD",
        "financialCurrency": "EUR", "exchange": "NYQ", "market": "us_market", "marketCap": 1,
        "currentPrice": 4.62, "averageVolume": 21246501, "sharesOutstanding": 2900941252}
STLA_MILAN = dict(STLA, currency="EUR", exchange="MIL", market="it_market", currentPrice=4.0475,
                  averageVolume=40124066)


def test_the_old_currency_swap_skips_a_thin_cross_listing(monkeypatch, ctx):
    # Spotify: NYSE in dollars over euro books. Its Frankfurt line trades in
    # euros, 430 shares a day, and is not its home market.
    _yahoo(monkeypatch, {"SPOT": SPOT, "639.DE": SPOT_FRANKFURT},
           [{"symbol": "639.DE", "quoteType": "EQUITY", "shortname": "Spotify Technology S.A."}])
    assert ctx.ensure_state_for_ticker("SPOT").ticker == "SPOT"


def test_the_old_currency_swap_keeps_a_line_the_company_trades_on(monkeypatch, ctx):
    # Stellantis is registered in the Netherlands and trades mostly in Milan,
    # which is not "home" by domicile; the swap to it, and the answer per NYSE
    # share, stand.
    _yahoo(monkeypatch, {"STLA": STLA, "STLAM.MI": STLA_MILAN},
           [{"symbol": "STLAM.MI", "quoteType": "EQUITY", "shortname": "STELLANTIS"}])
    assert ctx.ensure_state_for_ticker("STLA").ticker == "STLAM.MI"
    assert ctx._asked_listing["STLAM.MI"]["symbol"] == "STLA"
    assert ctx._asked_listing["STLAM.MI"]["ratio"] == 1.0


def test_liquidity_is_compared_in_us_share_units():
    from src.listing_view import trades_at_scale
    assert trades_at_scale(STLA_MILAN, STLA) is True
    assert trades_at_scale(SPOT_FRANKFURT, SPOT) is False
    airbus_adr = {"averageVolume": 425998, "sharesOutstanding": 3165921956}     # EADSY, 4 per share
    paris = {"averageVolume": 977019, "sharesOutstanding": 791480489}
    assert trades_at_scale(paris, airbus_adr) is True
    # Ten receipts per share (Genmab): 50,000 Copenhagen shares a day are
    # 500,000 in US-share units, well over a fifth of 400,000 receipts.
    receipts = {"averageVolume": 400000, "sharesOutstanding": 640000000}
    copenhagen = {"averageVolume": 50000, "sharesOutstanding": 64000000}
    assert trades_at_scale(copenhagen, receipts) is True
    assert trades_at_scale({"averageVolume": None}, airbus_adr) is False


# --------------------------------------------------------------------------
# The view, and the answer's opening
# --------------------------------------------------------------------------

def _tm_view():
    return build_view("TM", TM, 10.0, home_symbol="7203.T", reporting_currency="JPY",
                      home_price=2986.5, to_usd=lambda c: 1 / 157.38)


def test_the_view_states_the_price_ratio_and_rate():
    view = _tm_view()
    assert (view["ticker"], view["exchange"], view["price"], view["home_shares_per_share"]) == \
        ("TM", "NYSE", 188.3, 10.0)
    assert view["premium"] == pytest.approx(-0.0077, abs=0.0005)
    assert view["market_cap"] == 222981734400


def test_a_value_per_home_share_is_converted_per_us_share():
    assert per_us_share(_tm_view(), 3500.0) == pytest.approx(3500 / 157.38 * 10, abs=0.01)


def test_the_view_refuses_what_it_cannot_anchor():
    assert build_view("TM", TM, 10.0, home_symbol="7203.T", reporting_currency="JPY",
                      home_price=2986.5, to_usd=lambda c: None) is None
    assert build_view("TM", dict(TM, currency="EUR"), 10.0, home_symbol="7203.T",
                      reporting_currency="JPY", home_price=2986.5, to_usd=lambda c: 1 / 157.38) is None
    # A price off by the ratio: the counts and the quotes disagree.
    assert build_view("TM", TM, 10.0, home_symbol="7203.T", reporting_currency="JPY",
                      home_price=298.65, to_usd=lambda c: 1 / 157.38) is None


def test_the_published_opening_in_the_users_listing():
    view = _tm_view()
    figures = view_figures(view, {"fair_value": 3500.0}, {"price_target_12m": "JPY 3,600"})
    text = lead_paragraph(view, company="Toyota Motor Corporation", kind="published", figures=figures)
    assert text.startswith("TM (NYSE, $188.30): Toyota Motor Corporation is valued on its home "
                           "listing, 7203.T; one TM share represents 10 7203.T shares.")
    assert "at 1 USD = 157.38 JPY" in text
    assert f"${3500 / 157.38 * 10:,.2f}" in text and f"${3600 / 157.38 * 10:,.2f}" in text
    assert "rating is set against" not in text                 # a 0.8% gap is noise


def test_a_target_in_another_currency_is_not_converted():
    figures = view_figures(_tm_view(), {"fair_value": 3500.0}, {"price_target_12m": "USD 24.00"})
    assert "price_target_12m" not in figures


def test_an_adr_premium_is_stated_with_the_price_that_sets_the_rating():
    view = build_view("TSM", dict(TM, currentPrice=452.88), 5.0, home_symbol="2330.TW",
                      reporting_currency="TWD", home_price=2475.0, to_usd=lambda c: 0.031466)
    text = lead_paragraph(view, company="TSMC", kind="published",
                          figures=view_figures(view, {"fair_value": 2846.25}, {}))
    assert "trades 16% above them" in text
    assert "-1.1% against $452.88" in text
    assert text.endswith("The rating is set against the 2330.TW price.")


def test_the_withheld_opening_gives_the_range_per_us_share():
    view = build_view("AZN", AZN, 1.0, home_symbol="AZN.L", reporting_currency="USD",
                      home_price=165.60, to_usd=lambda c: 1.0)
    metrics = {"point_estimate_withheld": True, "perpetual_price": 106.61, "exit_multiple_price": 134.73}
    text = lead_paragraph(view, company="AstraZeneca PLC", kind="withheld",
                          figures=view_figures(view, metrics, {}))
    assert text == ("AZN (NYSE, $166.15): AstraZeneca PLC is valued on its home listing, AZN.L; "
                    "one AZN share is one AZN.L share. Per AZN share, the supported "
                    "valuation-method range is $106.61–$134.73.")


def test_a_withheld_view_publishes_no_point():
    metrics = {"point_estimate_withheld": True, "fair_value": 120.0,
               "perpetual_price": 106.61, "exit_multiple_price": 134.73}
    assert set(view_figures(_tm_view(), metrics, {})) == {"range"}


def test_the_refused_opening_names_the_listing_only():
    view = build_view("SHEL", dict(AZN, currentPrice=96.47), 2.0, home_symbol="SHEL.L",
                      reporting_currency="USD", home_price=48.44, to_usd=lambda c: 1.0)
    assert lead_paragraph(view, company="Shell plc", kind="refused") == (
        "SHEL (NYSE, $96.47): Shell plc is analysed on its home listing, SHEL.L; "
        "one SHEL share represents 2 SHEL.L shares.")


# --------------------------------------------------------------------------
# Which answers get a view
# --------------------------------------------------------------------------

def _valued_state(ticker, *, converted=True):
    km = {"basic_info": {"currency": "JPY", "long_name": "Toyota Motor Corporation", "country": "Japan"},
          "market_data": {"current_price": 2986.5, "current_price_currency": "JPY" if converted else "USD",
                          "shares_outstanding_basic": 11841833660}}
    return SimpleNamespace(ticker=ticker, company_name="Toyota Motor Corporation",
                           financial_data=SimpleNamespace(key_metrics=km))


@pytest.fixture
def jpy(monkeypatch):
    monkeypatch.setattr(listing_view, "_fx_rate", lambda a, b: 1 / 157.38 if (a, b) == ("JPY", "USD") else None)


def test_a_moved_line_is_answered_per_us_share(jpy):
    ctx = AgentContext(email="t@vynn.ai", timestamp="t", user_prompt="should i buy TM?")
    ctx._asked_listing["7203.T"] = {"symbol": "TM", "info": TM, "ratio": 10.0}
    state = _valued_state("7203.T")
    view = ctx.listing_view(state)
    assert view["ticker"] == "TM" and state.listing_view is view


def test_a_named_company_is_answered_in_its_us_exchange_line(monkeypatch, jpy):
    monkeypatch.setattr(listing_view, "us_line_for",
                        lambda name, country, shares, implied=None: {"symbol": "TM", "info": TM, "ratio": 10.0})
    ctx = AgentContext(email="t@vynn.ai", timestamp="t", user_prompt="should i buy Toyota?")
    assert ctx.listing_view(_valued_state("7203.T"))["ticker"] == "TM"


def test_a_typed_home_ticker_is_answered_as_typed(monkeypatch, jpy):
    monkeypatch.setattr(listing_view, "us_line_for",
                        lambda *a, **k: pytest.fail("no lookup for a typed home ticker"))
    ctx = AgentContext(email="t@vynn.ai", timestamp="t", user_prompt="should i buy 7203.t?")
    assert ctx.listing_view(_valued_state("7203.T")) is None


def test_no_view_over_an_unconverted_price(jpy):
    ctx = AgentContext(email="t@vynn.ai", timestamp="t", user_prompt="should i buy TM?")
    ctx._asked_listing["7203.T"] = {"symbol": "TM", "info": TM, "ratio": 10.0}
    assert ctx.listing_view(_valued_state("7203.T", converted=False)) is None


def test_a_us_valuation_has_no_view(monkeypatch):
    monkeypatch.setattr(listing_view, "us_line_for", lambda *a, **k: pytest.fail("no lookup for a US line"))
    ctx = AgentContext(email="t@vynn.ai", timestamp="t", user_prompt="should i buy MSFT?")
    assert ctx.listing_view(SimpleNamespace(ticker="MSFT")) is None


# --------------------------------------------------------------------------
# The templates and the guard
# --------------------------------------------------------------------------

AZN_VIEW = {"ticker": "AZN", "exchange": "NYSE", "currency": "USD", "price": 166.15,
            "home_ticker": "AZN.L", "home_shares_per_share": 1.0, "reporting_currency": "USD",
            "usd_per_reporting_unit": 1.0, "premium": 0.0033}


def _london_withheld_state():
    state = _withheld_state()
    state.financial_data.key_metrics["basic_info"] = {
        "currency": "USD", "listing_currency": "GBP", "long_name": "AstraZeneca PLC"}
    return state


def test_a_london_line_reporting_in_dollars_is_labelled_in_dollars():
    runner = SupervisorWorkflowRunner.__new__(SupervisorWorkflowRunner)
    runner.state, runner.ticker = _london_withheld_state(), "AZN.L"
    answer = runner._safe_withheld_valuation_answer()
    assert "$153.91–$183.79 USD" in answer
    assert "£" not in answer and "GBP" not in answer


def test_the_withheld_template_opens_in_the_users_listing():
    runner = SupervisorWorkflowRunner.__new__(SupervisorWorkflowRunner)
    state = _london_withheld_state()
    state.listing_view = AZN_VIEW
    runner.state, runner.ticker = state, "AZN.L"
    answer = runner._safe_withheld_valuation_answer()
    assert answer.startswith("AZN (NYSE, $166.15): AstraZeneca PLC is valued on its home listing, AZN.L")
    assert "\n\nAZN.L: " in answer


TM_PUBLISHED_VIEW = {"ticker": "TMX", "exchange": "NYSE", "currency": "USD", "price": 250.0,
                     "home_ticker": "PG.X", "home_shares_per_share": 2.0, "reporting_currency": "USD",
                     "usd_per_reporting_unit": 1.0, "premium": 0.0}


def _published_with_view():
    state = _published_state()
    state.listing_view = TM_PUBLISHED_VIEW
    return state


def test_a_fair_value_restated_per_us_share_is_the_published_one():
    ag = _chat_agent("what is the fair value per share?", _published_with_view(), "PG.X")
    draft = "The model's fair value is $269.50 per TMX share."        # 134.75 x 2
    assert ag._guard_final_answer(draft) == draft


@pytest.mark.parametrize("draft", [
    # The per-home-share figures, quoted against the US share and price.
    "The model's fair value is $134.75 per TMX share, 46% below the $250.00 TMX price.",
    "The report's price target is $142.00 per TMX share.",
])
def test_a_home_figure_quoted_against_the_us_share_is_a_contradiction(draft):
    ag = _chat_agent("what is the fair value per share?", _published_with_view(), "PG.X")
    assert ag._guard_final_answer(draft) != draft


def test_where_the_figures_are_the_same_the_home_figure_is_fine():
    state = _published_state()
    state.listing_view = dict(TM_PUBLISHED_VIEW, home_shares_per_share=1.0)
    ag = _chat_agent("what is the fair value per share?", state, "PG.X")
    draft = "The model's fair value is $134.75 per share."
    assert ag._guard_final_answer(draft) == draft


def test_any_other_fair_value_is_still_a_contradiction():
    ag = _chat_agent("what is the fair value per share?", _published_with_view(), "PG.X")
    out = ag._guard_final_answer("The model's fair value is $300.00 per TMX share.")
    assert out != "The model's fair value is $300.00 per TMX share."
    assert out.startswith("TMX (NYSE, $250.00): ")


def test_where_the_figures_differ_only_those_per_us_share_are_published():
    view = SupervisorWorkflowRunner._published_view(
        "HOLD", {"fair_value": 134.75, "upside_vs_market": 0.05},
        {"price_target_12m": "USD 142.00"}, TM_PUBLISHED_VIEW)
    assert set(view["values"]) == {269.5, 284.0}
    assert view["percents"] == [pytest.approx(7.8)]                   # 269.50 against $250.00


def test_where_the_figures_are_the_same_the_home_ones_are_published_too():
    same = dict(TM_PUBLISHED_VIEW, home_shares_per_share=1.0, price=125.0)
    view = SupervisorWorkflowRunner._published_view(
        "HOLD", {"fair_value": 134.75, "upside_vs_market": 0.05},
        {"price_target_12m": "USD 142.00"}, same)
    assert {134.75, 142.0} <= set(view["values"])
    assert pytest.approx(5.0) in view["percents"]


# A withheld answer that passes every other check: it says it is not rated and
# uses the Street benchmark (_withheld_state's 200.00 target, 15 revenue analysts).
WITHHELD_OK = ("TEST is not rated: the valuation is withheld. The Street's analyst consensus "
               "target is 200.00 (yahoo_finance), on revenue estimates from 15 analysts.")


def _withheld_with_view(**view):
    state = _withheld_state()
    state.listing_view = dict(TM_PUBLISHED_VIEW, **{"price": 600.0, **view})
    return state


def test_the_withheld_control_answer_is_accepted():
    ag = _chat_agent("tell me about TEST", _withheld_with_view(), "PG.X")
    assert ag._guard_final_answer(WITHHELD_OK) == WITHHELD_OK


def test_a_withheld_midpoint_per_us_share_is_as_unpublishable():
    ag = _chat_agent("tell me about TEST", _withheld_with_view(), "PG.X")
    draft = WITHHELD_OK + " Its midpoint works out to $335.34 per TMX share."      # 167.67 x 2
    assert ag._guard_final_answer(draft) == ag._guard_template
    assert "335.34" in ag._guard_forbidden


def test_where_the_figures_differ_the_home_range_cannot_be_quoted():
    ag = _chat_agent("tell me about TEST", _withheld_with_view(), "PG.X")
    home = WITHHELD_OK + " The supported range is $153.91-$183.79."
    assert ag._guard_final_answer(home) == ag._guard_template
    ag = _chat_agent("tell me about TEST", _withheld_with_view(), "PG.X")
    per_us = WITHHELD_OK + " The supported range is $307.82-$367.58 per TMX share."
    assert ag._guard_final_answer(per_us) == per_us


def test_a_figure_is_matched_as_a_whole_number():
    # The midpoint per US share is 8.0% above a $310.50 price; "18.0%" is not it.
    ag = _chat_agent("tell me about TEST", _withheld_with_view(price=310.5), "PG.X")
    draft = WITHHELD_OK + " Revenue grew 18.0% last year."
    assert ag._guard_final_answer(draft) == draft


# --------------------------------------------------------------------------
# The cards and the evidence
# --------------------------------------------------------------------------

def test_the_fair_value_card_is_in_the_users_listing():
    card = extract_findings("build_model", {
        "status": "ok", "currency": "JPY", "fair_value": 3500.0, "upside_vs_market": 0.17,
        "listing_view": {"ticker": "TM", "fair_value": 222.39, "upside": 0.181}})[0]
    assert (card["value"], card["sub"]) == ("$222.39", "per TM share · +18.1% vs market")


def test_the_market_cap_card_is_in_the_users_listing():
    card = extract_findings("get_financials", {
        "status": "ok", "currency": "GBP", "market_cap": 193737916416, "company_name": "AstraZeneca PLC",
        "listing_view": {"ticker": "AZN", "market_cap": 257681342464}})[0]
    assert card["value"].startswith("$257") and card["sub"] == "market cap · AZN"


def test_the_price_evidence_is_for_the_users_listing(monkeypatch):
    asked = []

    async def fake(self, ticker, period="1y"):
        asked.append(ticker)
        return json.dumps({"status": "error"})

    monkeypatch.setattr(data_tools.GetPricesTool, "execute", fake)
    monkeypatch.setattr(data_tools.GetTechnicalsTool, "execute", fake)
    state = SimpleNamespace(ticker="7203.T", listing_view={"ticker": "TM"})
    asyncio.run(market_evidence("TM", state))
    assert asked == ["TM", "TM"]


def test_every_valuation_result_carries_the_view():
    source = open(os.path.join(_ROOT, "src", "agents", "tools", "analysis_tools.py"), encoding="utf-8").read()
    assert source.count("_view_for(self.ctx, state)") == 6                      # + read_report
    assert "**_listing_view_payload(view, metrics, headline, _street_of(state))," in source    # read_report
    # Each names the listing its figures are for, not the ticker asked about.
    assert source.count('getattr(state, "ticker", None) or ticker') >= 5
    assert "**_listing_view_payload(view, vm, street=_street_of(state))," in source            # build_model
    assert "**_listing_view_payload(view, vm, bounded_headline, _street_of(state))," in source  # write_report
    assert "**_listing_view_payload(view, street=street)," in source                           # refusals


# --------------------------------------------------------------------------
# The view is rebuilt until it can be, and is kept per US line
# --------------------------------------------------------------------------

def test_a_view_that_could_not_be_built_is_tried_again(monkeypatch):
    # The exchange rate is down on the first call and back on the second.
    rates = iter([None, 1 / 157.38])
    monkeypatch.setattr(listing_view, "_fx_rate", lambda a, b: next(rates))
    ctx = AgentContext(email="t@vynn.ai", timestamp="t", user_prompt="should i buy TM?")
    ctx._asked_listing["7203.T"] = {"symbol": "TM", "info": TM, "ratio": 10.0}
    assert ctx.listing_view(_valued_state("7203.T")) is None
    assert ctx.listing_view(_valued_state("7203.T"))["ticker"] == "TM"


def test_each_us_line_keeps_its_own_view(jpy):
    ctx = AgentContext(email="t@vynn.ai", timestamp="t", user_prompt="compare the two lines")
    ctx._asked_listing["7203.T"] = {"symbol": "TM", "info": TM, "ratio": 10.0}
    assert ctx.listing_view(_valued_state("7203.T"))["ticker"] == "TM"
    ctx._asked_listing["7203.T"] = {"symbol": "TMX", "info": dict(TM, currentPrice=18.8), "ratio": 1.0}
    assert ctx.listing_view(_valued_state("7203.T"))["ticker"] == "TMX"


def test_several_us_shares_to_one_home_share_read_that_way():
    view = build_view("EADSY", dict(TM, currentPrice=54.97), 0.25, home_symbol="AIR.PA",
                      reporting_currency="EUR", home_price=193.1, to_usd=lambda c: 1.1378)
    text = lead_paragraph(view, company="Airbus SE", kind="refused")
    assert "4 EADSY shares represent one AIR.PA share" in text


# --------------------------------------------------------------------------
# A follow-up finds the report where the move filed it
# --------------------------------------------------------------------------

def test_a_follow_up_reads_the_report_filed_under_the_home_listing(monkeypatch, tmp_path):
    import path_utils
    monkeypatch.setattr(path_utils, "DATA_ROOT", tmp_path)
    run = tmp_path / "t@vynn.ai" / "AZN.L" / "20260928_220419"
    (run / "financials").mkdir(parents=True)
    (run / "AZN.L_Professional_Analysis_Report.md").write_text(
        "## Investment Rating: NOT RATED\n\nAstraZeneca report body.\n", encoding="utf-8")
    (run / "financials" / "financials_annual_modeling_latest.json").write_text(json.dumps({
        "company_data": {
            "basic_info": {"currency": "USD", "listing_currency": "GBP", "long_name": "AstraZeneca PLC",
                           "country": "United Kingdom"},
            "market_data": {"current_price": 165.60, "current_price_currency": "USD",
                            "shares_outstanding_basic": 1550895914},
        }}), encoding="utf-8")
    ctx = AgentContext(email="t@vynn.ai", timestamp="t", user_prompt="what did the AZN report say?")

    def home_listing_of(ticker):
        ctx._asked_listing["AZN.L"] = {"symbol": "AZN", "info": AZN, "ratio": 1.0}
        return "AZN.L"

    monkeypatch.setattr(ctx, "home_listing_of", home_listing_of)
    monkeypatch.setattr(listing_view, "_fx_rate", lambda a, b: 1.0 if a == b else None)
    body = json.loads(asyncio.run(analysis_tools.ReadReportTool(ctx).execute("AZN")).split("\n", 1)[-1])
    assert body["status"] == "ok" and body["ticker"] == "AZN.L"
    assert body["listing_view"]["ticker"] == "AZN"
    assert ctx.report_guard_state.listing_view["ticker"] == "AZN"
    assert ctx.report_guard_ticker == "AZN.L"


def test_a_main_listing_outside_the_domicile_is_not_called_home(monkeypatch, ctx, jpy):
    _yahoo(monkeypatch, {"STLA": STLA, "STLAM.MI": STLA_MILAN},
           [{"symbol": "STLAM.MI", "quoteType": "EQUITY", "shortname": "STELLANTIS"}])
    state = ctx.ensure_state_for_ticker("STLA")
    assert ctx._asked_listing["STLAM.MI"]["home_market"] is False
    view = build_view("STLA", STLA, 1.0, home_symbol="STLAM.MI", reporting_currency="EUR",
                      home_price=4.0475, to_usd=lambda c: 1.1378, home_market=False)
    assert "is analysed on its main listing, STLAM.MI" in lead_paragraph(view, company="Stellantis N.V.",
                                                                          kind="refused")
    assert state.ticker == "STLAM.MI"



# --------------------------------------------------------------------------
# The Street's target, per US share
# --------------------------------------------------------------------------

SHEL_VIEW = {"ticker": "SHEL", "exchange": "NYSE", "currency": "USD", "price": 96.47,
             "home_ticker": "SHEL.L", "home_market": True, "home_shares_per_share": 2.0,
             "reporting_currency": "USD", "usd_per_reporting_unit": 1.0, "premium": -0.004}


def test_the_street_target_is_converted_per_us_share():
    # Shell's Street target, $52.04 per London share, beside the $96.47 NYSE price.
    figures = view_figures(SHEL_VIEW, {}, None, {"currency": "USD", "target_mean": 52.04})
    assert figures["street_target_mean"] == 104.08
    assert lead_paragraph(SHEL_VIEW, company="Shell plc", kind="refused", figures=figures).endswith(
        "The Street's mean target is $104.08 per SHEL share.")


def test_a_street_target_in_another_currency_is_not_converted():
    figures = view_figures(SHEL_VIEW, {}, None, {"currency": "GBP", "target_mean": 39.0})
    assert "street_target_mean" not in figures


def test_the_street_block_names_the_share_its_targets_are_for():
    from src.answer_evidence import compose
    runner = SupervisorWorkflowRunner.__new__(SupervisorWorkflowRunner)
    state = _london_withheld_state()
    state.listing_view = SHEL_VIEW
    runner.state, runner.ticker = state, "SHEL.L"
    answer = runner._safe_withheld_valuation_answer()
    assert "benchmark reconciliation (per SHEL.L share, in USD):" in answer
    assert "The Street's mean target is $400.00 per SHEL share." in answer      # 200.00 x 2
    # The analysis still goes in before the Street block.
    composed = compose(answer, "ANALYSIS")
    assert composed.index("ANALYSIS") < composed.index("benchmark reconciliation (per SHEL.L share")


def test_where_the_figures_are_the_same_the_street_block_is_unlabelled():
    runner = SupervisorWorkflowRunner.__new__(SupervisorWorkflowRunner)
    state = _london_withheld_state()
    state.listing_view = AZN_VIEW
    runner.state, runner.ticker = state, "AZN.L"
    answer = runner._safe_withheld_valuation_answer()
    assert "benchmark reconciliation:" in answer and "(per AZN.L share" not in answer
