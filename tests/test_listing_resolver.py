"""
The analysis must run on a listing that can actually be valued.

THE BUG. A user asked for an LVMH sell-side initiation. The agent committed to
MOH.SG — LVMH on the Stuttgart regional exchange — and the report came back
NOT RATED with a market price of 0, after a mid-run tool call for "MC" returned
$68.90, which is Moelis & Company, a different business entirely.

Two independent defects produced that. Stuttgart quotes LVMH fine
(regularMarketPrice 458.70) but reports no market cap and no share count, and
the scraper read only `currentPrice`, which Yahoo leaves null on most non-US and
secondary lines — so the price arrived as None and every derived figure div-by-
zeroed. And nothing ever checked that the chosen venue was the company's home
listing.

These tests pin both. They run offline against a fake yfinance: which venue wins
is pure ranking logic, and a test that needs the network to prove it would be
untrustworthy on exactly the days it matters.

Run:  python -m pytest tests/test_listing_resolver.py -q
"""

import os
import sys
import types

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "src"))

# Import the REAL module. A previous test in this repo exec'd an extracted slice
# of its target with a hand-built namespace, which supplied the very import the
# module was missing and let a NameError ship to production. Never again.
from src.listing_resolver import (
    better_listing,
    is_analyzable,
    same_company,
    _search_queries,
    _tokens,
)


# Real payloads, trimmed to the fields the ranker reads. Captured from the live
# API on the day of the incident.
PARIS = {
    "longName": "LVMH Moët Hennessy - Louis Vuitton, Société Européenne",
    "currency": "EUR", "financialCurrency": "EUR", "exchange": "PAR",
    "market": "fr_market", "marketCap": 226443575296, "currentPrice": 459.35,
    "averageVolume": 556293,
}
STUTTGART = {
    "longName": "LVMH Moet Hennessy Louis Vuitton SE",
    "currency": "EUR", "financialCurrency": None, "exchange": "STU",
    "market": "dr_market", "marketCap": None, "regularMarketPrice": 458.70,
    "averageVolume": 1377,
}
OTC_ADR = {
    "longName": "LVMH-Moet Hennessy Louis Vuitton SE",
    "currency": "USD", "financialCurrency": "EUR", "exchange": "PNK",
    "market": "us_market", "marketCap": 264278654976, "currentPrice": 133.40,
    "averageVolume": 482625,
}
MOELIS = {
    "longName": "Moelis & Company", "currency": "USD", "financialCurrency": "USD",
    "exchange": "NYQ", "market": "us_market", "marketCap": 5103432704,
    "currentPrice": 68.89, "averageVolume": 700000,
}


class TestAnalyzable:
    def test_stuttgart_is_not_analyzable(self):
        """No market cap means the company cannot be sized. This is the tell."""
        assert is_analyzable(STUTTGART) is False

    def test_paris_is_analyzable(self):
        assert is_analyzable(PARIS) is True

    def test_price_may_arrive_as_regular_market_price(self):
        """
        Yahoo leaves `currentPrice` null on most foreign lines. A listing that
        quotes only `regularMarketPrice` is still priced.
        """
        listing = {"marketCap": 1_000, "regularMarketPrice": 12.5}
        assert is_analyzable(listing) is True

    def test_previous_close_is_the_last_resort(self):
        assert is_analyzable({"marketCap": 1_000, "previousClose": 9.0}) is True

    def test_priced_but_unsized_is_rejected(self):
        assert is_analyzable({"marketCap": None, "currentPrice": 458.70}) is False

    def test_empty_info_is_rejected(self):
        assert is_analyzable({}) is False


class TestSameCompany:
    def test_folds_accents_and_corporate_forms(self):
        """'Moet' vs 'Moët', 'SE' vs 'Société Européenne' — same company."""
        assert same_company(STUTTGART["longName"], PARIS["longName"]) is True

    def test_adr_matches_its_underlying(self):
        assert same_company(OTC_ADR["longName"], PARIS["longName"]) is True

    def test_rejects_a_different_company(self):
        """
        The guard that matters: the bare ticker "MC" is Moelis & Company. A
        substitution across a name mismatch hands back a report on the wrong
        business, which is far worse than declining to substitute.
        """
        assert same_company(PARIS["longName"], MOELIS["longName"]) is False

    def test_noise_words_alone_never_match(self):
        """"The Group Holding Co" shares only stopwords with anything."""
        assert same_company("The Group Holding Co", "Holdings Group Ltd") is False

    def test_missing_names_never_match(self):
        assert same_company(None, PARIS["longName"]) is False
        assert same_company("", "") is False


class TestSearchQueries:
    def test_includes_the_leading_brand_token(self):
        """
        Searching the full legal name returns only German regional lines; the
        first token is what surfaces the Paris primary. Both must be tried.
        """
        queries = _search_queries("LVMH Moet Hennessy Louis Vuitton SE")
        assert "LVMH Moet Hennessy Louis Vuitton SE" in queries
        assert "LVMH" in queries

    def test_deduplicates_single_word_names(self):
        assert _search_queries("Nestle") == ["Nestle"]

    def test_tokens_drop_noise(self):
        assert _tokens("Nestlé S.A.") == {"nestle"}


def _fake_yfinance(universe, search_results):
    """A stand-in yfinance whose Search and Ticker read from fixed dicts."""
    module = types.ModuleType("yfinance")

    class _Search:
        def __init__(self, query, max_results=8):
            self.quotes = search_results.get(query, [])

    class _Ticker:
        def __init__(self, symbol):
            self._symbol = symbol

        @property
        def info(self):
            return universe.get(self._symbol, {})

    module.Search = _Search
    module.Ticker = _Ticker
    return module


@pytest.fixture
def lvmh_yahoo(monkeypatch):
    """The search results Yahoo actually returned, in the order it returned them."""
    universe = {"MC.PA": PARIS, "LVMUY": OTC_ADR, "MOH.SG": STUTTGART}
    search_results = {
        # The full legal name surfaces only the regional lines...
        "LVMH Moet Hennessy Louis Vuitton SE": [
            {"symbol": "MOH.MU", "quoteType": "EQUITY",
             "shortname": "LVMH MOET HENNESSY VUITTON SE"},
        ],
        # ...while the brand token surfaces the primary and the ADR.
        "LVMH": [
            {"symbol": "MC.PA", "quoteType": "EQUITY", "shortname": "LVMH"},
            {"symbol": "LVMUY", "quoteType": "EQUITY",
             "shortname": "LVMH-Moet Hennessy Louis Vuitto"},
        ],
    }
    monkeypatch.setitem(sys.modules, "yfinance",
                        _fake_yfinance(universe, search_results))
    return universe


class TestBetterListing:
    def test_upgrades_stuttgart_to_the_paris_primary(self, lvmh_yahoo):
        """The regression. MOH.SG must become MC.PA."""
        result = better_listing("MOH.SG", STUTTGART)
        assert result is not None
        assert result[0] == "MC.PA"

    def test_prefers_the_home_listing_over_a_larger_reported_market_cap(self, lvmh_yahoo):
        """
        The ADR reports 264B USD against Paris's 226B EUR — the same company in
        a different currency. Ranking on raw market cap picks the ADR, which is
        why the ranker keys on `currency == financialCurrency` instead.
        """
        symbol, _ = better_listing("MOH.SG", STUTTGART)
        assert symbol == "MC.PA"
        assert OTC_ADR["marketCap"] > PARIS["marketCap"]

    def test_returns_the_resolved_company_name(self, lvmh_yahoo):
        _, name = better_listing("MOH.SG", STUTTGART)
        assert "LVMH" in name

    def test_never_substitutes_a_different_company(self, monkeypatch):
        """A search that returns only a same-ticker-different-company match yields nothing."""
        monkeypatch.setitem(sys.modules, "yfinance", _fake_yfinance(
            {"MC": MOELIS},
            {"LVMH Moet Hennessy Louis Vuitton SE": [
                {"symbol": "MC", "quoteType": "EQUITY", "shortname": "Moelis & Company"}],
             "LVMH": [{"symbol": "MC", "quoteType": "EQUITY",
                       "shortname": "Moelis & Company"}]},
        ))
        assert better_listing("MOH.SG", STUTTGART) is None

    def test_skips_candidates_that_are_themselves_unusable(self, monkeypatch):
        """Another regional line is no better than the one we started on."""
        monkeypatch.setitem(sys.modules, "yfinance", _fake_yfinance(
            {"MOH.MU": dict(STUTTGART, exchange="MUN")},
            {"LVMH Moet Hennessy Louis Vuitton SE": [
                {"symbol": "MOH.MU", "quoteType": "EQUITY",
                 "shortname": "LVMH MOET HENNESSY VUITTON SE"}],
             "LVMH": []},
        ))
        assert better_listing("MOH.SG", STUTTGART) is None

    def test_ignores_non_equity_quote_types(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "yfinance", _fake_yfinance(
            {"MC.PA": PARIS},
            {"LVMH Moet Hennessy Louis Vuitton SE": [],
             "LVMH": [{"symbol": "MC.PA", "quoteType": "ETF", "shortname": "LVMH"}]},
        ))
        assert better_listing("MOH.SG", STUTTGART) is None

    def test_survives_a_search_that_raises(self, monkeypatch):
        """A resolution failure must degrade to 'analyze what was asked', not abort."""
        module = types.ModuleType("yfinance")

        class _Boom:
            def __init__(self, *a, **k):
                raise RuntimeError("Yahoo is down")

        module.Search = _Boom
        module.Ticker = _Boom
        monkeypatch.setitem(sys.modules, "yfinance", module)
        assert better_listing("MOH.SG", STUTTGART) is None

    def test_unnamed_listing_is_not_searchable(self, lvmh_yahoo):
        assert better_listing("???", {"marketCap": None}) is None


class TestScraperPriceFallback:
    """
    The other half of the incident: the scraper read only `currentPrice`, so a
    listing quoting `regularMarketPrice` arrived priced at None.
    """

    def test_scraper_falls_back_past_current_price(self):
        import re
        source = open(os.path.join(_ROOT, "src", "financial_scraper.py"),
                      encoding="utf-8").read()
        block = re.search(r'"current_price":\s*\((.*?)\),', source, re.S)
        assert block, "current_price is no longer a fallback chain"
        assert "regularMarketPrice" in block.group(1)
        assert "previousClose" in block.group(1)


class TestCompanyLabel:
    """
    A price payload that carries only a symbol lets a wrong guess pass silently.
    The run that prompted this asked for LVMH, called get_prices("MC"), and got
    Moelis & Company's $68.90 back with nothing to mark it as another company.
    """

    def _tool_module(self):
        from src.agents.tools import data_tools
        return data_tools

    def test_names_the_issuer(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "yfinance",
                            _fake_yfinance({"MC.PA": PARIS}, {}))
        assert "LVMH" in self._tool_module().company_label("MC.PA")

    def test_falls_back_to_short_name(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "yfinance", _fake_yfinance(
            {"X": {"shortName": "Acme Corp"}}, {}))
        assert self._tool_module().company_label("X") == "Acme Corp"

    def test_never_raises(self, monkeypatch):
        """An unnamed quote is still a usable quote; lookup failure must not abort."""
        module = types.ModuleType("yfinance")

        class _Boom:
            def __init__(self, *a, **k):
                raise RuntimeError("Yahoo is down")

        module.Ticker = _Boom
        monkeypatch.setitem(sys.modules, "yfinance", module)
        assert self._tool_module().company_label("MC") is None

    def test_unknown_ticker_yields_no_name(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "yfinance", _fake_yfinance({}, {}))
        assert self._tool_module().company_label("ZZZZ") is None

    def test_price_payload_carries_the_company(self):
        """The lookup must stay wired into the result the model reads."""
        import inspect
        from src.agents.tools.data_tools import GetPricesTool
        source = inspect.getsource(GetPricesTool.execute)
        assert 'payload["company"] = name' in source
        assert "company_label" in source
