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
    is_depositary,
    is_home_listing,
    is_otc,
    names_might_match,
    rank_key,
    same_company,
    venue_suffix,
    _enrichment_order,
    _search_queries,
    _tokens,
)


# Real payloads, trimmed to the fields the ranker reads. Captured from the live
# API during the investigation.
PARIS = {
    "longName": "LVMH Moët Hennessy - Louis Vuitton, Société Européenne",
    "currency": "EUR", "financialCurrency": "EUR", "exchange": "PAR",
    "market": "fr_market", "marketCap": 226443575296, "currentPrice": 459.35,
    "averageVolume": 556293, "country": "France",
}
STUTTGART = {
    "longName": "LVMH Moet Hennessy Louis Vuitton SE",
    "currency": "EUR", "financialCurrency": None, "exchange": "STU",
    "market": "dr_market", "marketCap": None, "regularMarketPrice": 458.70,
    "averageVolume": 1377, "country": "France",
}
OTC_ADR = {
    "longName": "LVMH-Moet Hennessy Louis Vuitton SE",
    "currency": "USD", "financialCurrency": "EUR", "exchange": "PNK",
    "fullExchangeName": "OTC Markets OTCPK", "market": "us_market",
    "marketCap": 264278654976, "currentPrice": 133.40,
    "averageVolume": 482625, "country": "France",
}
MOELIS = {
    "longName": "Moelis & Company", "currency": "USD", "financialCurrency": "USD",
    "exchange": "NYQ", "market": "us_market", "marketCap": 5103432704,
    "currentPrice": 68.89, "averageVolume": 700000, "country": "United States",
}
# Prosus: the case where currency == financialCurrency picks OTC junk over the
# Amsterdam primary.
PROSUS_AMS = {
    "longName": "Prosus N.V.", "currency": "EUR", "financialCurrency": "USD",
    "exchange": "AMS", "market": "nl_market", "marketCap": 80489717760,
    "currentPrice": 62.1, "averageVolume": 3365700, "country": "Netherlands",
}
PROSUS_OTC = {
    "longName": "Prosus N.V.", "currency": "USD", "financialCurrency": "USD",
    "exchange": "PNK", "fullExchangeName": "OTC Markets OTCPK",
    "market": "us_market", "marketCap": 93800000000, "currentPrice": 14.2,
    "averageVolume": 1861, "country": "Netherlands",
}
# Infosys: ranking on liquidity alone picks the ADR over the home line.
INFY_NSE = {
    "longName": "Infosys Limited", "currency": "INR", "financialCurrency": "USD",
    "exchange": "NSI", "market": "in_market", "marketCap": 6e12,
    "currentPrice": 1500.0, "averageVolume": 13998754, "country": "India",
}
INFY_ADR = {
    "longName": "Infosys Limited", "currency": "USD", "financialCurrency": "USD",
    "exchange": "NYQ", "market": "us_market", "marketCap": 7e10,
    "currentPrice": 17.0, "averageVolume": 22726406, "country": "India",
}


class TestAnalyzable:
    def test_stuttgart_is_not_analyzable(self):
        """No market cap means the company cannot be sized. This is the tell."""
        assert is_analyzable(STUTTGART) is False

    def test_paris_is_analyzable(self):
        assert is_analyzable(PARIS) is True

    def test_price_may_arrive_as_regular_market_price(self):
        """Yahoo leaves `currentPrice` null on most foreign lines."""
        assert is_analyzable({"marketCap": 1_000, "regularMarketPrice": 12.5}) is True

    def test_previous_close_is_the_last_resort(self):
        assert is_analyzable({"marketCap": 1_000, "previousClose": 9.0}) is True

    def test_priced_but_unsized_is_rejected(self):
        assert is_analyzable({"marketCap": None, "currentPrice": 458.70}) is False

    def test_empty_info_is_rejected(self):
        assert is_analyzable({}) is False


class TestVenueClassification:
    """
    The venue signals, each pinned against a measured counter-example. Several
    plausible-sounding rules were wrong and are recorded here so they are not
    reintroduced.
    """

    @pytest.mark.parametrize("exchange", ["PNK", "OQX", "OID"])
    def test_every_otc_tier_is_detected(self, exchange):
        """
        A PNK-only test misses OTCQX and OTCID, which is where Roche (RHHBY,
        OQX) and Nestlé (NSRGY, OID) sit — two of the most-traded ADRs in the US.
        """
        assert is_otc({"exchange": exchange}) is True

    def test_otc_detected_by_full_exchange_name(self):
        assert is_otc({"exchange": "ZZZ", "fullExchangeName": "OTC Markets OTCPK"}) is True

    def test_real_exchange_is_not_otc(self):
        assert is_otc(PARIS) is False

    def test_dr_market_marks_the_german_regional_lines(self):
        """
        Measured: MOH.SG, MOHF.MU and MOH.HM all report market == "dr_market".
        It does NOT mark US ADRs, which report "us_market" like any other line —
        so this signal complements the OTC test rather than replacing it.
        """
        assert is_depositary(STUTTGART, "MOH.SG") is True
        assert is_depositary(OTC_ADR, "LVMUY") is False

    def test_london_iob_is_a_depositary_venue(self):
        """IOB carries GDRs and reports market == "gb_market", not dr_market."""
        assert is_depositary({"exchange": "IOB", "market": "gb_market"}, "RIGD.IL") is True

    def test_home_listing_matches_domicile_to_suffix(self):
        assert is_home_listing(PARIS, "MC.PA") is True
        assert is_home_listing(PROSUS_AMS, "PRX.AS") is True
        assert is_home_listing(INFY_NSE, "INFY.NS") is True

    def test_cross_listing_is_not_home(self):
        """A French company on a US venue is not its home listing."""
        assert is_home_listing(OTC_ADR, "LVMUY") is False
        assert is_home_listing(INFY_ADR, "INFY") is False

    def test_us_company_on_us_venue_is_home(self):
        assert is_home_listing(MOELIS, "MC") is True

    def test_venue_suffix(self):
        assert venue_suffix("MC.PA") == "PA"
        assert venue_suffix("NVDA") == ""
        assert venue_suffix("") == ""


class TestRanking:
    def _best(self, pairs):
        return max(pairs, key=lambda p: rank_key(p[1], p[0]))[0]

    def test_home_listing_beats_otc_despite_the_currency_match(self):
        """
        THE PROSUS FAILURE. currency == financialCurrency is true for the OTC
        line (USD/USD) and false for the Amsterdam primary (EUR/USD). Scored as a
        strong signal it selected a pink-sheet line trading 1,861 shares a day.
        """
        assert self._best([("PRX.AS", PROSUS_AMS), ("PROSY", PROSUS_OTC)]) == "PRX.AS"

    def test_home_listing_beats_a_more_liquid_adr(self):
        """
        THE INFOSYS FAILURE. The NYSE ADR trades 22.7M against 14.0M on the NSE
        home line, so ranking on liquidity alone picks the wrong venue.
        """
        assert self._best([("INFY.NS", INFY_NSE), ("INFY", INFY_ADR)]) == "INFY.NS"

    def test_home_listing_beats_a_larger_reported_market_cap(self):
        """
        The ADR reports 264B USD against Paris's 226B EUR — the same company in
        another currency. marketCap is denominated in the LISTING currency, and
        GBp lines report it in GBP (a silent 100x), so it can never be compared
        across venues.
        """
        assert self._best([("MC.PA", PARIS), ("LVMUY", OTC_ADR)]) == "MC.PA"
        assert OTC_ADR["marketCap"] > PARIS["marketCap"]

    def test_liquidity_breaks_ties_between_equivalent_venues(self):
        thin = dict(PARIS, averageVolume=10)
        assert self._best([("A.PA", PARIS), ("B.PA", thin)]) == "A.PA"


class TestSameCompany:
    def test_folds_accents_and_corporate_forms(self):
        """'Moet' vs 'Moët', 'SE' vs 'Société Européenne' — same company."""
        assert same_company(STUTTGART["longName"], PARIS["longName"]) is True

    def test_adr_matches_its_underlying(self):
        assert same_company(OTC_ADR["longName"], PARIS["longName"]) is True

    def test_rejects_a_different_company(self):
        assert same_company(PARIS["longName"], MOELIS["longName"]) is False

    def test_rejects_names_sharing_only_generic_words(self):
        """
        THE RICHEMONT FALSE POSITIVE. "Compagnie Financiere Richemont" and
        "Compagnie Financiere Tradition" share two of three tokens, and the
        earlier 60%-overlap rule accepted them as the same company — which would
        have substituted a report onto a different business.
        """
        assert same_company("Compagnie Financière Richemont SA",
                            "Compagnie Financiere Tradition SA") is False

    def test_rejects_a_structured_note_carrying_the_brand(self):
        """
        yf.Search returns "EB MemExpr LVMH SE 23-28" with quoteType EQUITY, so
        the type filter alone does not exclude bonds. Containment is not enough:
        the shared part must be a substantial share of both names.
        """
        assert same_company(STUTTGART["longName"], "EB MemExpr LVMH SE 23-28") is False

    def test_accepts_abbreviated_corporate_form(self):
        assert same_company("Toyota Motor Corporation", "Toyota Motor Corp") is True

    def test_names_made_only_of_structure_words_still_match_themselves(self):
        """
        "Societe Generale" is a bank, not a legal form. Stripping every structure
        word left it with an empty token set, unable to match even itself.
        """
        assert same_company("Societe Generale", "SOCIETE GENERALE SA") is True

    def test_missing_names_never_match(self):
        assert same_company(None, PARIS["longName"]) is False
        assert same_company("", "") is False


class TestLooseScreen:
    """names_might_match filters truncated search snippets, so it is lenient."""

    def test_accepts_a_truncated_snippet(self):
        assert names_might_match(PARIS["longName"], "LVMH Moet Hennessy Louis Vuitto") is True

    def test_accepts_a_brand_only_snippet(self):
        assert names_might_match(PARIS["longName"], "LVMH") is True

    def test_rejects_a_company_sharing_only_a_generic_word(self):
        """"Compagnie du Cambodge" surfaced as a Richemont candidate."""
        assert names_might_match("Compagnie Financiere Richemont SA",
                                 "Compagnie du Cambodge") is False


class TestSearchQueries:
    def test_folds_accents_without_splitting_the_word(self):
        """
        Replacing a combining mark with a space split "Financière" into
        "financie" and "re", and the literal query "Compagnie Financie" went to
        Yahoo. Accents must be removed, not substituted.
        """
        queries = _search_queries("Compagnie Financière Richemont SA")
        assert all("financie " not in q + " " for q in queries)
        assert "compagnie financiere richemont sa" in queries
        assert queries[0] == "Compagnie Financière Richemont SA"

    def test_includes_the_brand_when_it_leads(self):
        """The full legal name returns only German lines; "lvmh" finds MC.PA."""
        assert "lvmh" in _search_queries("LVMH Moet Hennessy Louis Vuitton SE")

    def test_includes_the_brand_when_it_trails(self):
        """
        "Compagnie Financiere" returns a different company and "Koninklijke"
        returns Vopak and Ahold — in both the brand is the LAST meaningful token.
        Length is not the signal: "financiere" is longer than "richemont".
        """
        assert "richemont" in _search_queries("Compagnie Financière Richemont SA")
        assert "philips" in _search_queries("Koninklijke Philips N.V.")

    def test_dotted_forms_do_not_leak_single_letters(self):
        """"N.V." must fold to "nv", not to the tokens "n" and "v"."""
        for q in _search_queries("Koninklijke Philips N.V."):
            assert q.split()[-1] not in ("n", "v")

    def test_deduplicates_single_word_names(self):
        """Raw and folded collapse to one query for an unaccented single word."""
        assert _search_queries("Nestle") == ["Nestle"]

    def test_tries_the_original_spelling_before_the_folded_one(self):
        """
        Folding is a fallback, not a replacement: yf.Search("Nestlé S.A.") ranks
        the Swiss primary first, while "Nestle S.A." drops it off the results.
        """
        queries = _search_queries("Nestlé S.A.")
        assert queries[0] == "Nestlé S.A."
        assert "nestle sa" in queries

    def test_query_count_is_bounded(self):
        """Each form costs a network round trip."""
        assert len(_search_queries("A Very Long Legal Company Name Holdings SE")) <= 5

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
    """The search results Yahoo actually returned, keyed by the folded query."""
    universe = {"MC.PA": PARIS, "LVMUY": OTC_ADR, "MOH.SG": STUTTGART}
    search_results = {
        # The full legal name surfaces only the regional lines — seven of them,
        # which is exactly enough to exhaust a candidate budget on its own.
        "LVMH Moet Hennessy Louis Vuitton SE": [
            {"symbol": s, "quoteType": "EQUITY",
             "shortname": "LVMH MOET HENNESSY VUITTON SE"}
            for s in ("MOH.MU", "MOHF.MU", "MOH.HM", "MOH.HA", "MOHF.SG", "MOHF.DU")
        ],
        # ...while the brand token surfaces the primary and the ADR.
        "lvmh": [
            {"symbol": "MC.PA", "quoteType": "EQUITY", "shortname": "LVMH"},
            {"symbol": "LVMUY", "quoteType": "EQUITY",
             "shortname": "LVMH-Moet Hennessy Louis Vuitto"},
        ],
        "lvmh moet hennessy louis vuitton se": [],
        "lvmh moet": [],
        "vuitton": [],
    }
    monkeypatch.setitem(sys.modules, "yfinance",
                        _fake_yfinance(universe, search_results))
    return universe


class TestBetterListing:
    def test_upgrades_stuttgart_to_the_paris_primary(self, lvmh_yahoo):
        """The regression this whole module exists for. MOH.SG must become MC.PA."""
        result = better_listing("MOH.SG", STUTTGART)
        assert result is not None
        assert result[0] == "MC.PA"

    def test_a_flood_of_regional_lines_does_not_starve_the_brand_query(self, lvmh_yahoo):
        """
        The legal-name search returns six regional lines. Stopping candidate
        collection once "enough" existed meant the brand query that actually
        finds MC.PA never ran, and the upgrade silently returned None.
        """
        assert better_listing("MOH.SG", STUTTGART)[0] == "MC.PA"

    def test_prefers_the_home_listing_over_the_otc_adr(self, lvmh_yahoo):
        symbol, _ = better_listing("MOH.SG", STUTTGART)
        assert symbol == "MC.PA"

    def test_returns_the_resolved_company_name(self, lvmh_yahoo):
        _, name = better_listing("MOH.SG", STUTTGART)
        assert "LVMH" in name

    def test_never_substitutes_a_different_company(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "yfinance", _fake_yfinance(
            {"MC": MOELIS},
            {q: [{"symbol": "MC", "quoteType": "EQUITY", "shortname": "Moelis & Company"}]
             for q in ("LVMH Moet Hennessy Louis Vuitton SE",
                       "lvmh moet hennessy louis vuitton se", "lvmh",
                       "lvmh moet", "vuitton")},
        ))
        assert better_listing("MOH.SG", STUTTGART) is None

    def test_skips_candidates_that_are_themselves_unusable(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "yfinance", _fake_yfinance(
            {"MOH.MU": dict(STUTTGART, exchange="MUN")},
            {"LVMH Moet Hennessy Louis Vuitton SE": [
                {"symbol": "MOH.MU", "quoteType": "EQUITY",
                 "shortname": "LVMH MOET HENNESSY VUITTON SE"}]},
        ))
        assert better_listing("MOH.SG", STUTTGART) is None

    def test_ignores_non_equity_quote_types(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "yfinance", _fake_yfinance(
            {"MC.PA": PARIS},
            {"lvmh": [{"symbol": "MC.PA", "quoteType": "ETF", "shortname": "LVMH"}]},
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


class TestEnrichmentOrder:
    """
    Which candidates are worth a network lookup, decided from the symbol alone.
    """

    def test_regional_lines_go_last(self):
        order = _enrichment_order({"MOH.SG": {}, "MC.PA": {}, "MOH.MU": {}})
        assert order[0] == "MC.PA"

    def test_otc_shaped_symbols_rank_below_home_listings(self):
        order = _enrichment_order({"LVMUY": {}, "MC.PA": {}})
        assert order[0] == "MC.PA"

    def test_known_home_suffix_beats_an_unknown_one(self):
        order = _enrichment_order({"4MC.TI": {}, "MC.PA": {}})
        assert order[0] == "MC.PA"


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
        # Name and currency resolve together in one lookup.
        assert "listing_identity" in source
