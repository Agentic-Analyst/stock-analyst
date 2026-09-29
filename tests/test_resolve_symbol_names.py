"""resolve_symbol names the company asked for, not another carrying its brand.

Venue ranking alone (home listing, then the currency tiebreak, then volume)
handed "Unilever" to PT Unilever Indonesia, "Siemens" to Siemens Energy,
"Infosys" to HCL Infosystems, "Linde" to Lindex, "ABB" to Abbott and
"Meituan" to its renminbi counter, which has no market cap. The order now:
an exact ticker; a listing whose name is exactly the query; venue; no country
the query did not name, where a listing carries the brand without one; a
listing that can be valued; Yahoo's own order; then currency and volume.

Each case is the live search of 2026-09-29, trimmed; offline.
"""
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "src"))

from src.listing_resolver import adds_country, name_match  # noqa: E402
from test_resolve_symbol import _eq, _run  # noqa: E402


from src.listing_resolver import USD_PER_UNIT  # noqa: E402


def _info(name, country, currency, financial, exchange, market, usd=5e10, volume=1e6, price=10.0):
    """A listing; ``usd`` is its market cap in dollars (None: Yahoo gives none)."""
    unit = {"GBp": "GBP"}.get(currency, currency)
    cap = None if usd is None else usd / USD_PER_UNIT[unit]
    return {"longName": name, "country": country, "currency": currency, "financialCurrency": financial,
            "exchange": exchange, "market": market, "marketCap": cap, "currentPrice": price,
            "averageVolume": volume}


US = ("USD", "NYQ", "us_market")


def _us(name, country, financial="USD", **kw):
    return _info(name, country, "USD", financial, "NYQ", "us_market", **kw)


CASES = {
    "Unilever": ("ULVR.L", [
        ("UL", _us("Unilever PLC", "United Kingdom", "EUR", usd=13e10)),
        ("UNVR.JK", _info("PT Unilever Indonesia Tbk", "Indonesia", "IDR", "IDR", "JKT", "id_market", volume=3e7, usd=3.8e9)),
        ("HINDUNILVR.NS", _info("Hindustan Unilever Limited", "India", "INR", "INR", "NSI", "in_market")),
        ("ULVR.L", _info("Unilever PLC", "United Kingdom", "GBp", "EUR", "LSE", "gb_market")),
    ]),
    "Siemens": ("SIE.DE", [
        ("ENR.DE", _info("Siemens Energy AG", "Germany", "EUR", "EUR", "GER", "de_market", volume=9e6, usd=13e10)),
        ("SIE.DE", _info("Siemens Aktiengesellschaft", "Germany", "EUR", "EUR", "GER", "de_market")),
        ("SHL.DE", _info("Siemens Healthineers AG", "Germany", "EUR", "EUR", "GER", "de_market")),
    ]),
    "ABB": ("ABBN.SW", [
        ("ABBV", _us("AbbVie Inc.", "United States", volume=6e6, usd=47e10)),
        ("ABT", _us("Abbott Laboratories", "United States", volume=6e6)),
        ("ABBN.SW", _info("ABB Ltd", "Switzerland", "CHF", "USD", "EBS", "ch_market")),
    ]),
    "Linde": ("LIN", [
        ("LIN", _us("Linde plc", "United Kingdom")),
        ("LINDEX.HE", _info("Lindex Group Oyj", "Finland", "EUR", "EUR", "HEL", "fi_market", usd=3.6e8)),
    ]),
    "Infosys": ("INFY.NS", [
        ("INFY", _us("Infosys Limited", "India")),
        ("INFY.NS", _info("Infosys Limited", "India", "INR", "USD", "NSI", "in_market")),
        ("HCL-INSYS.NS", _info("HCL Infosystems Limited", "India", "INR", "INR", "NSI", "in_market", volume=5e6, usd=4e7)),
    ]),
    "Meituan": ("3690.HK", [
        ("83690.HK", _info("Meituan", "China", "CNY", "CNY", "HKG", "hk_market", usd=None)),
        ("3690.HK", _info("Meituan", "China", "HKD", "CNY", "HKG", "hk_market")),
    ]),
    "Vodafone": ("VOD.L", [
        ("VOD", _us("Vodafone Group Public Limited Company", "United Kingdom", "EUR")),
        ("IDEA.NS", _info("Vodafone Idea Limited", "India", "INR", "INR", "NSI", "in_market", volume=5e8, usd=8e9)),
        ("VOD.L", _info("Vodafone Group Public Limited Company", "United Kingdom", "GBp", "EUR", "LSE", "gb_market")),
    ]),
    # No listing is named exactly "BMW"; Yahoo knows the query means BMW AG,
    # and "BMW Industries" containing the query is no evidence either way.
    "BMW": ("BMW.DE", [
        ("BMW.DE", _info("Bayerische Motoren Werke Aktiengesellschaft", "Germany", "EUR", "EUR", "GER", "de_market")),
        ("BMW.BO", _info("BMW Industries Ltd.", "India", "INR", "INR", "BSE", "in_market", usd=1.3e8)),
    ]),
    "Delta": ("DAL", [
        ("DAL", _us("Delta Air Lines, Inc.", "United States")),
        ("2308.TW", _info("Delta Electronics, Inc.", "Taiwan", "TWD", "TWD", "TAI", "tw_market", volume=1e7, usd=1.54e11)),
        ("DELTA.BK", _info("Delta Electronics (Thailand) Public Company Limited", "Thailand", "THB", "THB", "SET", "th_market")),
        ("DELTACORP.NS", _info("Delta Corp Limited", "India", "INR", "INR", "NSI", "in_market", volume=3e6, usd=2.2e8)),
    ]),
    "Hermes": ("RMS.PA", [
        ("RMS.PA", _info("Hermès International Société en commandite par actions", "France", "EUR", "EUR", "PAR", "fr_market", volume=1e5)),
        ("FHI", _us("Federated Hermes, Inc.", "United States", volume=6e5, usd=4.3e9)),
    ]),
    "Santander": ("SAN.MC", [
        ("SAN", _us("Banco Santander, S.A.", "Spain", "EUR")),
        ("SAN.MC", _info("Banco Santander, S.A.", "Spain", "EUR", "EUR", "MCE", "es_market")),
        ("BSAN.NE", _info("SANTANDER CDR (CAD HEDGED)", "Spain", "CAD", "EUR", "NEO", "ca_market")),
    ]),
    "Diageo": ("DGE.L", [
        ("DGE.L", _info("Diageo plc", "United Kingdom", "GBp", "USD", "LSE", "gb_market", volume=4.5e6)),
        ("DGED.L", _info("Diageo plc", "United Kingdom", "USD", "USD", "LSE", "gb_market", volume=1450)),
    ]),
    # Yahoo lists the Indian affiliate first; Suzuki Motor carries the brand
    # without a country.
    "Suzuki": ("7269.T", [
        ("MARUTI.NS", _info("Maruti Suzuki India Limited", "India", "INR", "INR", "NSI", "in_market")),
        ("7269.T", _info("Suzuki Motor Corporation", "Japan", "JPY", "JPY", "JPX", "jp_market")),
    ]),
    # ...but for "Maruti Suzuki", Maruti Suzuki India is the company.
    "Maruti Suzuki": ("MARUTI.NS", [
        ("MARUTI.NS", _info("Maruti Suzuki India Limited", "India", "INR", "INR", "NSI", "in_market")),
        ("MGIL.BO", _info("Maruti Global Industries Limited", "India", "INR", "INR", "BSE", "in_market", usd=1e7)),
    ]),
    "Hyundai": ("005380.KS", [
        ("005380.KS", _info("Hyundai Motor Company", "South Korea", "KRW", "KRW", "KSC", "kr_market")),
        ("HYUNDAI.NS", _info("Hyundai Motor India Limited", "India", "INR", "INR", "NSI", "in_market", volume=3e6)),
    ]),
    # Yahoo gives Reliance Industries' NSE line no market cap (2026-09-29):
    # "Reliance, Inc." is exactly "Reliance" once "Inc." goes, but Yahoo ranks
    # Reliance Industries above it with no size to compare, and a missing
    # market cap is no reason to prefer another company.
    "Reliance (no NSE market cap)": ("RELIANCE.NS", [
        ("RELIANCE.NS", _info("Reliance Industries Limited", "India", "INR", "INR", "NSI", "in_market", usd=None)),
        ("RS", _us("Reliance, Inc.", "United States", usd=2e10)),
        ("RPOWER.NS", _info("Reliance Power Limited", "India", "INR", "INR", "NSI", "in_market", volume=5e7, usd=None)),
    ]),
    # ...and where one of its lines has the market cap, that line.
    "Reliance Industries": ("RELIANCE.BO", [
        ("RELIANCE.NS", _info("Reliance Industries Limited", "India", "INR", "INR", "NSI", "in_market", usd=None)),
        ("RELIANCE.BO", _info("Reliance Industries Limited", "India", "INR", "INR", "BSE", "in_market", usd=1.8e11)),
    ]),
    # With both sizes known, Reliance, Inc. is a fourteenth the size.
    "Reliance": ("RELIANCE.NS", [
        ("RELIANCE.NS", _info("Reliance Industries Limited", "India", "INR", "INR", "NSI", "in_market", usd=2.15e11)),
        ("RS", _us("Reliance, Inc.", "United States", usd=1.5e10)),
        ("RPOWER.NS", _info("Reliance Power Limited", "India", "INR", "INR", "NSI", "in_market", volume=5e7, usd=2.3e9)),
    ]),
    # Mitsubishi Corporation is exactly "Mitsubishi" and more than a tenth of
    # MUFG's size: the exact name stands.
    "Mitsubishi": ("8058.T", [
        ("MUFG", _us("Mitsubishi UFJ Financial Group, Inc.", "Japan", "JPY", usd=1.47e11)),
        ("8058.T", _info("Mitsubishi Corporation", "Japan", "JPY", "JPY", "JPX", "jp_market", usd=8e10)),
        ("8306.T", _info("Mitsubishi UFJ Financial Group, Inc.", "Japan", "JPY", "JPY", "JPX", "jp_market", usd=1.47e11)),
    ]),
    # A subsidiary asked for by name is still the answer.
    "Siemens Energy": ("ENR.DE", [
        ("ENR.DE", _info("Siemens Energy AG", "Germany", "EUR", "EUR", "GER", "de_market")),
        ("SIE.DE", _info("Siemens Aktiengesellschaft", "Germany", "EUR", "EUR", "GER", "de_market")),
    ]),
    "Hindustan Unilever": ("HINDUNILVR.NS", [
        ("HINDUNILVR.NS", _info("Hindustan Unilever Limited", "India", "INR", "INR", "NSI", "in_market")),
        ("ULVR.L", _info("Unilever PLC", "United Kingdom", "GBp", "EUR", "LSE", "gb_market")),
    ]),
}


@pytest.mark.parametrize("case", list(CASES))
def test_the_company_asked_for_is_the_best_guess(case):
    expected, listings = CASES[case]
    query = case.split(" (")[0]
    universe = dict(listings)
    searches = {query: [_eq(symbol, info["longName"]) for symbol, info in listings]}
    assert _run(query, universe, searches)["best_guess"] == expected


def test_an_exact_ticker_still_wins():
    universe = {"ABT": _us("Abbott Laboratories", "United States"),
                "ABBN.SW": _info("ABB Ltd", "Switzerland", "CHF", "USD", "EBS", "ch_market")}
    searches = {"ABT": [_eq("ABBN.SW", "ABB Ltd"), _eq("ABT", "Abbott Laboratories")]}
    assert _run("ABT", universe, searches)["best_guess"] == "ABT"


def test_the_internal_fields_do_not_reach_the_model():
    expected, listings = CASES["Siemens"]
    out = _run("Siemens", dict(listings), {"Siemens": [_eq(s, i["longName"]) for s, i in listings]})
    assert not any(key.startswith("_") for cand in out["candidates"] for key in cand)


def test_name_match_is_exact_or_contains():
    assert name_match("Unilever", "Unilever PLC") == (1, 1)
    assert name_match("Unilever", "Hindustan Unilever Limited") == (0, 1)
    assert name_match("BMW", "Bayerische Motoren Werke Aktiengesellschaft") == (0, 0)
    assert name_match("Vodafone", "Vodafone Group Public Limited Company") == (1, 1)


def test_a_country_the_query_names_is_not_added():
    assert adds_country("Hyundai", "Hyundai Motor India Limited") is True
    assert adds_country("Nestle India", "Nestlé India Limited") is False
    assert adds_country("Delta", "Delta Air Lines, Inc.") is False


# --------------------------------------------------------------------------
# Review findings (2026-09-29), each reproduced before its fix
# --------------------------------------------------------------------------

def test_public_is_a_name_outside_the_legal_form():
    from src.listing_resolver import same_company
    # "Public" as a noise word made Public Bank Berhad "the same company" as RHB.
    assert same_company("Public Bank Berhad", "RHB Bank Berhad") is False
    assert name_match("Vodafone", "Vodafone Group Public Limited Company") == (1, 1)
    assert name_match("Delta Electronics", "Delta Electronics (Thailand) Public Company Limited")[1] == 1


def test_an_exact_name_without_a_size_does_not_outrank_what_yahoo_lists_first():
    # Delta Corp's .info never arrived (a timeout or the rate limit).
    universe = {"DAL": _us("Delta Air Lines, Inc.", "United States", usd=5.5e10)}
    searches = {"Delta": [_eq("DAL", "Delta Air Lines, Inc."),
                          {"symbol": "DELTACORP.NS", "quoteType": "EQUITY", "shortname": "DELTA CORP",
                           "longname": "Delta Corp Limited"}]}
    assert _run("Delta", universe, searches)["best_guess"] == "DAL"


def test_no_internal_field_reaches_the_model_from_any_result_type():
    expected, listings = CASES["Siemens"]
    searches = {"Siemens": [_eq(s, i["longName"]) for s, i in listings]
                + [{"symbol": "SIEM.ETF", "quoteType": "ETF", "shortname": "Siemens tracker"}]}
    out = _run("Siemens", dict(listings), searches)
    assert not any(key.startswith("_") for cand in out["candidates"] for key in cand)


def test_a_home_listing_found_first_ends_the_search():
    # "Deutsche Boerse" is not every word of "Deutsche Börse AG" ("boerse" vs
    # "borse"); requiring that sent three searches and brought in Deutsche Bank.
    import types
    calls = []
    universe = {"DB1.DE": _info("Deutsche Börse AG", "Germany", "EUR", "EUR", "GER", "de_market")}
    module = types.ModuleType("yfinance")

    class Search:
        def __init__(self, query, max_results=8):
            calls.append(query)
            self.quotes = [_eq("DB1.DE", "Deutsche Börse AG")] if query == "Deutsche Boerse" else []

    class Ticker:
        def __init__(self, symbol):
            self.info = universe.get(symbol, {})

    module.Search, module.Ticker = Search, Ticker
    saved = sys.modules.get("yfinance")
    sys.modules["yfinance"] = module
    try:
        import asyncio, json
        from src.agents.tools.data_tools import ResolveSymbolTool
        out = json.loads(asyncio.run(ResolveSymbolTool().execute("Deutsche Boerse")))
    finally:
        sys.modules["yfinance"] = saved
    assert out["best_guess"] == "DB1.DE" and calls == ["Deutsche Boerse"]


REVIEW_CASES = {
    # A company whose own name holds a country is not an affiliate of a much
    # smaller one without: Telkom Indonesia (listed first) is 12x Telkom SA.
    "Telkom": ("TLKM.JK", [
        ("TLKM.JK", _info("PT Telkom Indonesia (Persero) Tbk", "Indonesia", "IDR", "IDR", "JKT", "id_market", usd=1.8e10)),
        ("TKG.JO", _info("Telkom SA SOC Limited", "South Africa", "ZAR", "ZAR", "JNB", "za_market", usd=1.5e9)),
    ]),
    # One company's lines: the mainland A-share, as before, though Yahoo lists
    # the Hong Kong line first.
    "Ping An": ("601318.SS", [
        ("2318.HK", _info("Ping An Insurance (Group) Company of China, Ltd.", "China", "HKD", "CNY", "HKG", "hk_market")),
        ("601318.SS", _info("Ping An Insurance (Group) Company of China, Ltd.", "China", "CNY", "CNY", "SHH", "cn_market")),
    ]),
    # The company first, then its line: Yahoo lists Ping An Insurance first;
    # its A-share has no market cap on Yahoo, so its Hong Kong line. Ping An
    # Bank's line matching its reporting currency does not pick the company.
    "Ping An (three companies)": ("2318.HK", [
        ("2318.HK", _info("Ping An Insurance (Group) Company of China, Ltd.", "China", "HKD", "CNY", "HKG", "hk_market", usd=1.2e11)),
        ("601318.SS", _info("Ping An Insurance (Group) Company of China, Ltd.", "China", "CNY", "CNY", "SHH", "cn_market", usd=None)),
        ("000001.SZ", _info("Ping An Bank Co., Ltd.", "China", "CNY", "CNY", "SHZ", "cn_market", usd=3e10, volume=1e8)),
        ("1833.HK", _info("Ping An Healthcare and Technology Company Limited", "China", "HKD", "CNY", "HKG", "hk_market", usd=3e9)),
    ]),
}


@pytest.mark.parametrize("case", list(REVIEW_CASES))
def test_review_cases(case):
    expected, listings = REVIEW_CASES[case]
    query = case.split(" (")[0]
    searches = {query: [_eq(s, i["longName"]) for s, i in listings]}
    assert _run(query, dict(listings), searches)["best_guess"] == expected



def test_an_exact_name_must_come_from_yahoos_data_not_a_snippet():
    # A Cboe Europe line Yahoo has no data for, whose search snippet spells
    # "Boerse" exactly as asked, beat the Xetra line of "Deutsche Börse AG".
    universe = {"DB1.DE": _info("Deutsche Börse AG", "Germany", "EUR", "EUR", "GER", "de_market")}
    searches = {"Deutsche Boerse": [
        _eq("DB1.DE", "Deutsche Börse AG"),
        {"symbol": "DB1D.XD", "quoteType": "EQUITY", "shortname": "DEUTSCHE BOERSE AG", "longname": "Deutsche Boerse AG"},
    ]}
    assert _run("Deutsche Boerse", universe, searches)["best_guess"] == "DB1.DE"


def test_a_typed_symbol_is_first_even_among_its_companys_lines():
    universe = {"SHEL": _us("Shell plc", "United Kingdom"),
                "SHEL.L": _info("Shell plc", "United Kingdom", "GBp", "USD", "LSE", "gb_market")}
    searches = {"SHEL": [_eq("SHEL.L", "Shell plc"), _eq("SHEL", "Shell plc")]}
    assert _run("SHEL", universe, searches)["best_guess"] == "SHEL"
