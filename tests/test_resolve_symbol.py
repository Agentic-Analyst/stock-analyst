"""
resolve_symbol must hand back the listing a company actually trades on.

THE GAP. The tool ranked candidates as "equities first, then Yahoo's raw order"
and set best_guess = ranked[0]. Yahoo's raw order is not the company's home
listing: searching LVMH's legal name returns six German regional floors and
never the Paris primary, and searching Toyota's returns the NYSE ADR ahead of
Tokyo.

A guard added to ensure_state_for_ticker corrected this for the full analysis
path, but the ordering in a real run was:

    [FINDING] Resolved MC.PA
    [FINDING] MC.PA  €459.35
    [SUPERVISOR] ✅ Identified ticker: MC.PA

— resolve_symbol and get_prices both ran BEFORE the guard. A plain chat question
therefore priced whatever resolve_symbol returned, unchecked.

These tests run offline against a fake yfinance. Which venue wins is ranking
logic, and a test needing the network to prove it would be least trustworthy on
exactly the days it matters.

Run:  python -m pytest tests/test_resolve_symbol.py -q
"""

import asyncio
import json
import os
import sys
import types

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "src"))

from src.agents.tools.data_tools import ResolveSymbolTool

from test_listing_resolver import (  # noqa: E402  — reuse the captured payloads
    PARIS, STUTTGART, OTC_ADR, INFY_NSE, INFY_ADR, _fake_yfinance,
)

TOKYO = {
    "longName": "Toyota Motor Corporation", "currency": "JPY",
    "financialCurrency": "JPY", "exchange": "JPX", "market": "jp_market",
    "marketCap": 37003290738688, "currentPrice": 3125.0,
    "averageVolume": 29443076, "country": "Japan",
}
TOYOTA_ADR = {
    "longName": "Toyota Motor Corporation", "currency": "USD",
    "financialCurrency": "JPY", "exchange": "NYQ", "market": "us_market",
    "marketCap": 230314393600, "currentPrice": 194.5,
    "averageVolume": 488146, "country": "Japan",
}


def _run(query, universe, searches):
    """Execute the tool against a fixed universe and return the parsed payload."""
    module = _fake_yfinance(universe, searches)
    saved = sys.modules.get("yfinance")
    sys.modules["yfinance"] = module
    try:
        return json.loads(asyncio.run(ResolveSymbolTool().execute(query)))
    finally:
        if saved is not None:
            sys.modules["yfinance"] = saved
        else:
            sys.modules.pop("yfinance", None)


def _eq(symbol, name):
    return {"symbol": symbol, "quoteType": "EQUITY", "shortname": name}


class TestHomeListingWins:
    def test_adr_does_not_outrank_the_home_listing(self):
        """
        Measured: searching "Toyota Motor Corporation" returns TM at rank 0 and
        7203.T at rank 1, under BOTH the legal name and the brand. No query
        rewriting fixes this — only re-ranking does.
        """
        out = _run(
            "Toyota Motor Corporation",
            {"TM": TOYOTA_ADR, "7203.T": TOKYO},
            {"Toyota Motor Corporation": [_eq("TM", "Toyota Motor Corp"),
                                          _eq("7203.T", "Toyota Motor Corporation")]},
        )
        assert out["best_guess"] == "7203.T"

    def test_regional_line_does_not_win(self):
        """The LVMH case, at the tool that produced it."""
        out = _run(
            "LVMH",
            {"MOH.SG": STUTTGART, "MC.PA": PARIS},
            {"LVMH": [_eq("MOH.SG", "LVMH Moet Hennessy Louis Vuitto"),
                      _eq("MC.PA", "LVMH")]},
        )
        assert out["best_guess"] == "MC.PA"

    def test_otc_adr_does_not_win(self):
        out = _run(
            "LVMH",
            {"LVMUY": OTC_ADR, "MC.PA": PARIS},
            {"LVMH": [_eq("LVMUY", "LVMH-Moet Hennessy Louis Vuitto"), _eq("MC.PA", "LVMH")]},
        )
        assert out["best_guess"] == "MC.PA"

    def test_more_liquid_adr_does_not_win(self):
        """Infosys's ADR trades 22.7M against 14.0M on its NSE home line."""
        out = _run(
            "Infosys",
            {"INFY": INFY_ADR, "INFY.NS": INFY_NSE},
            {"Infosys": [_eq("INFY", "Infosys Limited"), _eq("INFY.NS", "Infosys Limited")]},
        )
        assert out["best_guess"] == "INFY.NS"


class TestQueryRetry:
    def test_retries_on_the_brand_when_the_legal_name_finds_only_regionals(self):
        """
        Searching the folded legal name returns German floors and nothing else.
        The tool must notice that no candidate is a real listing and try again.
        """
        out = _run(
            "LVMH Moet Hennessy Louis Vuitton SE",
            {"MOH.SG": STUTTGART, "MOHF.MU": STUTTGART, "MC.PA": PARIS},
            {
                "LVMH Moet Hennessy Louis Vuitton SE": [
                    _eq("MOH.SG", "LVMH Moet Hennessy Louis Vuitto"),
                    _eq("MOHF.MU", "LVMH ADR /2 EO-,30"),
                ],
                "lvmh": [_eq("MC.PA", "LVMH")],
            },
        )
        assert out["best_guess"] == "MC.PA"

    def test_no_retry_when_the_first_search_already_found_a_home_listing(self):
        """The common path stays a single search."""
        calls = []

        universe = {"MC.PA": PARIS}
        searches = {"LVMH": [_eq("MC.PA", "LVMH")]}
        module = _fake_yfinance(universe, searches)
        original = module.Search

        class Counting(original):
            def __init__(self, query, max_results=8):
                calls.append(query)
                super().__init__(query, max_results)

        module.Search = Counting
        sys.modules["yfinance"] = module
        try:
            out = json.loads(asyncio.run(ResolveSymbolTool().execute("LVMH")))
        finally:
            sys.modules.pop("yfinance", None)
        assert out["best_guess"] == "MC.PA"
        assert calls == ["LVMH"]

    def test_retry_does_not_admit_a_different_company(self):
        """
        The brand token is not trustworthy on its own — "Compagnie Financiere"
        returns Compagnie Financière Tradition. Retry results are name-checked.
        """
        out = _run(
            "Compagnie Financiere Richemont SA",
            {"RITN.SG": dict(STUTTGART, longName="Compagnie Financiere Richemont SA"),
             "CFI.SG": dict(STUTTGART, longName="Compagnie Financiere Tradition SA")},
            {
                "Compagnie Financiere Richemont SA": [
                    _eq("RITN.SG", "Compagnie Financiere Richemont")],
                "compagnie": [_eq("CFI.SG", "Compagnie FinanciereTradition S")],
                "compagnie financiere": [_eq("CFI.SG", "Compagnie FinanciereTradition S")],
                "richemont": [],
            },
        )
        assert out["best_guess"] != "CFI.SG"


class TestCandidateShape:
    def test_candidates_explain_the_venue(self):
        """
        The model has to choose. Exchange codes alone do not tell it that STU is
        a regional floor — and the code is not even stable across calls (the same
        symbol came back as TKS and JPX, NYQ and NYS).
        """
        out = _run(
            "LVMH",
            {"MC.PA": PARIS, "LVMUY": OTC_ADR},
            {"LVMH": [_eq("MC.PA", "LVMH"), _eq("LVMUY", "LVMH-Moet Hennessy")]},
        )
        by_ticker = {c["ticker"]: c for c in out["candidates"]}
        assert "home" in by_ticker["MC.PA"]["venue"]
        assert "OTC" in by_ticker["LVMUY"]["venue"]

    def test_candidates_carry_size_and_currency(self):
        out = _run("LVMH", {"MC.PA": PARIS}, {"LVMH": [_eq("MC.PA", "LVMH")]})
        cand = out["candidates"][0]
        assert cand["market_cap"] == PARIS["marketCap"]
        assert cand["currency"] == "EUR"
        assert cand["country"] == "France"

    def test_note_warns_against_bare_tickers(self):
        """
        The run that started this called get_prices("MC") and took back Moelis &
        Company's price as LVMH's.
        """
        out = _run("LVMH", {"MC.PA": PARIS}, {"LVMH": [_eq("MC.PA", "LVMH")]})
        assert "suffix" in out["note"].lower()

    def test_output_keys_are_unchanged(self):
        """findings.py reads best_guess; the agent reads candidates."""
        out = _run("LVMH", {"MC.PA": PARIS}, {"LVMH": [_eq("MC.PA", "LVMH")]})
        for key in ("query", "candidates", "best_guess", "note"):
            assert key in out


class TestDegradation:
    def test_no_results_returns_a_clean_note_not_a_crash(self):
        """
        ranked[0] on an empty list is an IndexError. The tool must explain
        itself instead.
        """
        out = _run("Nonexistent Company", {}, {})
        assert out["candidates"] == []
        assert "No ticker found" in out["note"]

    def test_non_equities_do_not_become_best_guess(self):
        """
        The same searches return ETFs, indices, mutual funds and tokenised-stock
        crypto lines — "Novo Nordisk" returns NVOX-USD.
        """
        out = _run(
            "LVMH",
            {"MC.PA": PARIS},
            {"LVMH": [{"symbol": "LVMH-ETF", "quoteType": "ETF", "shortname": "LVMH 2x"},
                      _eq("MC.PA", "LVMH")]},
        )
        assert out["best_guess"] == "MC.PA"

    def test_survives_info_lookups_that_raise(self):
        """An unenriched candidate is still a candidate."""
        module = types.ModuleType("yfinance")

        class _Search:
            def __init__(self, query, max_results=8):
                self.quotes = [_eq("MC.PA", "LVMH")] if query == "LVMH" else []

        class _Ticker:
            def __init__(self, symbol):
                raise RuntimeError("Yahoo is down")

        module.Search = _Search
        module.Ticker = _Ticker
        sys.modules["yfinance"] = module
        try:
            out = json.loads(asyncio.run(ResolveSymbolTool().execute("LVMH")))
        finally:
            sys.modules.pop("yfinance", None)
        assert out["best_guess"] == "MC.PA"

    def test_empty_query_is_rejected(self):
        out = _run("", {}, {})
        assert out.get("status") == "error"


class TestCryptoShortCircuit:
    def test_crypto_still_bypasses_the_equity_path(self):
        """A coin has no home listing, no market cap and no DCF."""
        out = _run("Bitcoin", {}, {})
        assert out["best_guess"] == "BTC-USD"
        assert out["asset_class"] == "crypto"


NESTLE_SWISS = {
    "longName": "Nestlé S.A.", "currency": "CHF", "financialCurrency": "CHF",
    "exchange": "EBS", "market": "ch_market", "marketCap": 206960803840,
    "currentPrice": 80.46, "averageVolume": 4000000, "country": "Switzerland",
}
NESTLE_MILAN = {
    "longName": "Nestle SA", "currency": "EUR", "financialCurrency": "CHF",
    "exchange": "MIL", "market": "it_market", "marketCap": 200000000000,
    "currentPrice": 86.0, "averageVolume": 1200, "country": "Switzerland",
}
MOELIS = {
    "longName": "Moelis & Company", "currency": "USD", "financialCurrency": "USD",
    "exchange": "NYQ", "market": "us_market", "marketCap": 5103432704,
    "currentPrice": 68.89, "averageVolume": 700000, "country": "United States",
}
FREEPORT = {
    "longName": "Freeport-McMoRan Inc.", "currency": "USD",
    "financialCurrency": "USD", "exchange": "NYQ", "market": "us_market",
    "marketCap": 60000000000, "currentPrice": 42.0,
    "averageVolume": 25000000, "country": "United States",
}


class TestExactSymbolWins:
    def test_exact_ticker_beats_a_more_liquid_fuzzy_match(self):
        """
        Yahoo answers a short query with fuzzy matches: "MC" returns
        Freeport-McMoRan and McDonald's alongside Moelis, and both dwarf it on
        volume. Ranking purely on venue quality handed back FCX for a user who
        typed MC.
        """
        out = _run(
            "MC",
            {"MC": MOELIS, "FCX": FREEPORT},
            {"MC": [_eq("FCX", "Freeport-McMoRan Inc."), _eq("MC", "Moelis & Company")]},
        )
        assert out["best_guess"] == "MC"

    def test_the_ambiguous_symbol_is_named(self):
        """
        The whole point: the model asked for LVMH, guessed "MC", and had nothing
        telling it the answer was Moelis. Now the name comes back with it.
        """
        out = _run("MC", {"MC": MOELIS}, {"MC": [_eq("MC", "Moelis & Company")]})
        assert out["candidates"][0]["name"] == "Moelis & Company"

    def test_exact_match_suppresses_the_retry(self):
        """A symbol the user named outright is not second-guessed."""
        calls = []
        module = _fake_yfinance({"MC": MOELIS},
                                {"MC": [_eq("MC", "Moelis & Company")]})
        original = module.Search

        class Counting(original):
            def __init__(self, query, max_results=8):
                calls.append(query)
                super().__init__(query, max_results)

        module.Search = Counting
        sys.modules["yfinance"] = module
        try:
            asyncio.run(ResolveSymbolTool().execute("MC"))
        finally:
            sys.modules.pop("yfinance", None)
        assert calls == ["MC"]


class TestRetryOnCrossListing:
    def test_a_tradeable_cross_listing_is_not_good_enough(self):
        """
        THE NESTLE CASE. De-accenting drops NESN.SW off the results entirely and
        leaves a thin Milan line, which is tradeable — so a retry condition of
        "nothing usable found" never fires and the wrong venue ships.
        """
        out = _run(
            "Nestle S.A.",
            {"1NESN.MI": NESTLE_MILAN, "NESN.SW": NESTLE_SWISS},
            {
                "Nestle S.A.": [_eq("1NESN.MI", "Nestle SA")],
                "nestle sa": [_eq("1NESN.MI", "Nestle SA")],
                "nestle": [_eq("NESN.SW", "NESTLE N")],
            },
        )
        assert out["best_guess"] == "NESN.SW"

    def test_no_retry_once_the_home_listing_is_present(self):
        calls = []
        module = _fake_yfinance({"NESN.SW": NESTLE_SWISS},
                                {"Nestle": [_eq("NESN.SW", "NESTLE N")]})
        original = module.Search

        class Counting(original):
            def __init__(self, query, max_results=8):
                calls.append(query)
                super().__init__(query, max_results)

        module.Search = Counting
        sys.modules["yfinance"] = module
        try:
            out = json.loads(asyncio.run(ResolveSymbolTool().execute("Nestle")))
        finally:
            sys.modules.pop("yfinance", None)
        assert out["best_guess"] == "NESN.SW"
        assert calls == ["Nestle"]
