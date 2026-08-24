"""
Listing resolution — pick the venue that can actually be analyzed.

A company can be quoted on a dozen venues, and Yahoo's name search returns them
in an order that frequently puts the wrong one first. A real LVMH run committed
to MOH.SG (Stuttgart), which reports no market cap and no share count, so the
model valued a company it could not size and the report shipped NOT RATED.

WHAT THE LIVE API ACTUALLY DOES — measured, not assumed:

  * Searching an accented legal name returns NOTHING. yf.Search of LVMH's real
    longName ("LVMH Moët Hennessy - Louis Vuitton, Société Européenne") and of
    Richemont's ("Compagnie Financière Richemont SA") both return zero quotes.
    De-accenting them returns only German regional lines. The brand token fixes
    both. So queries must be accent-folded AND tried in more than one form.

  * currency == financialCurrency is NOT a reliable home-listing test. It picks
    the US line over the home line for every issuer reporting in a foreign
    currency (Shell, AstraZeneca, Rio Tinto, BHP, Infosys) and matches nothing at
    all for Spotify, Alibaba or Tencent. For Prosus it is actively perverse: it
    rejects the Amsterdam primary and accepts two OTC pink lines, one trading
    1,861 shares a day. It survives here only as a last tiebreak.

  * Ranking by market cap is a unit lottery. marketCap is denominated in the
    listing's currency, and GBp lines report it in GBP — a silent 100x (measured
    mc/(price*shares) = 0.0100 for SHEL.L and AZN.L against 1.0000 elsewhere).

  * Ranking by liquidity picks the wrong venue too: Infosys's NYSE ADR trades
    22.7M against 14.0M on its NSE home line.

  * `country` IS reliable. It reports the issuer's domicile identically across
    every venue, so matching it against the symbol's exchange suffix is the
    strongest available signal for "this is the home listing".
"""

from __future__ import annotations

import re
import unicodedata
from typing import Optional, Tuple

# Corporate-form and structure words carry no identifying information and differ
# between venues for the same company ("SE" vs "SA", "ADR" vs nothing).
_NOISE = {
    "sa", "se", "ag", "nv", "plc", "inc", "corp", "corporation", "co", "ltd",
    "limited", "the", "company", "holding", "holdings", "group", "adr", "spa",
    "ab", "as", "oyj", "cie", "kgaa", "sas", "bv", "class", "reg",
    # Trailing corporate forms spelled out, so the last meaningful token of
    # "... Société Européenne" is the brand and not the legal form.
    "societe", "europeenne", "anonyme", "aktiengesellschaft", "incorporated",
    # Generic structure words in other languages. Without these, "Compagnie du
    # Cambodge" matches "Compagnie Financiere Richemont" on the shared word for
    # "company", and "Koninklijke Philips" matches every other Dutch royal
    # charter (Vopak, Ahold).
    "compagnie", "groupe", "grupo", "gruppo", "koninklijke", "kabushiki",
    "aktiebolag", "naamloze", "vennootschap",
}

# OTC Markets tiers. A PNK-only test misses OTCQX and OTCID, which is where two
# of the most-traded ADRs in the US sit: Roche (RHHBY, OQX) and Nestlé
# (NSRGY, OID).
_OTC_EXCHANGES = {"PNK", "OTC", "OQX", "OID", "OTCQ", "OBB"}

# London's International Order Book carries GDRs (RIGD.IL, KAP.IL). They report
# market == "gb_market", so venue country cannot be read off `market`.
_GDR_EXCHANGES = {"IOB"}

# Yahoo's own label for depositary-receipt venues. This is what marks the German
# regional lines the LVMH run landed on — MOH.SG, MOHF.MU and MOH.HM all report
# it. It does NOT mark US ADRs, which report "us_market" like any other listing.
_DR_MARKETS = {"dr_market"}

# Exchange suffix -> issuer domicile, for "is this the company's home venue?".
# US listings carry no suffix. Germany's primary is Xetra (.DE); .SG/.MU/.HM/.DU
# /.HA/.BE/.F are the regional floors that started this whole investigation.
_SUFFIX_COUNTRY = {
    "PA": "France", "AS": "Netherlands", "BR": "Belgium", "L": "United Kingdom",
    "DE": "Germany", "SW": "Switzerland", "MI": "Italy", "MC": "Spain",
    "ST": "Sweden", "OL": "Norway", "CO": "Denmark", "HE": "Finland",
    "VI": "Austria", "LS": "Portugal", "IR": "Ireland", "AT": "Greece",
    "WA": "Poland", "T": "Japan", "KS": "South Korea", "KQ": "South Korea",
    "HK": "Hong Kong", "TW": "Taiwan", "TWO": "Taiwan", "SI": "Singapore",
    "SS": "China", "SZ": "China", "NS": "India", "BO": "India",
    "AX": "Australia", "NZ": "New Zealand", "TO": "Canada", "V": "Canada",
    "SA": "Brazil", "MX": "Mexico", "JO": "South Africa", "TA": "Israel",
    "IS": "Turkey", "BK": "Thailand", "JK": "Indonesia", "KL": "Malaysia",
}

_US_COUNTRY = "United States"

# German regional floors. These are the venues that started this investigation:
# they quote a price, report no market cap and no share count, and dominate the
# results of a full-legal-name search. Xetra (.DE) is Germany's primary and is
# deliberately NOT in this set.
_REGIONAL_SUFFIXES = {"SG", "MU", "HM", "DU", "HA", "BE", "F"}

_MAX_CANDIDATES = 6  # bounds the .info calls on the failure path


def _fold(text: object) -> str:
    """
    Lowercase, accent-folded ASCII.

    Combining marks are REMOVED, not replaced with a space. Substituting a space
    splits a word at its accent — "Financière" became the tokens "financie" and
    "re", which then went out as the literal search query "Compagnie Financie".
    """
    folded = unicodedata.normalize("NFKD", str(text or ""))
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    return folded.lower()


def _tokens(name: object) -> set:
    """Noise-stripped token set for company-name matching."""
    folded = _fold(name)
    # Collapse dotted corporate forms BEFORE splitting so "S.A." becomes the
    # noise word "sa" rather than the single letters "s" and "a", which survive
    # the noise filter and can match between unrelated companies.
    folded = folded.replace(".", "")
    folded = re.sub(r"[^a-z0-9 ]+", " ", folded)
    words = [t for t in folded.split() if len(t) > 1]
    tokens = {t for t in words if t not in _NOISE}
    # Some real names consist ENTIRELY of structure words — "Societe Generale"
    # is a bank, not a legal form. Returning an empty set there would make the
    # company unable to match even itself, so fall back to the raw words.
    return tokens or set(words)


def names_might_match(a: object, b: object) -> bool:
    """
    Loose screen for search-result snippets.

    Yahoo's snippets are truncated ("LVMH Moet Hennessy Louis Vuitto") and
    sometimes carry only the brand, so the strict test would discard the very
    candidate we are looking for. Anything surviving this is re-checked against
    the candidate's authoritative longName by same_company().
    """
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return False
    return bool(ta & tb)


def same_company(a: object, b: object) -> bool:
    """
    Whether two listing names denote the same company.

    One name's tokens must be a SUBSET of the other's. An overlap ratio is not
    enough: "Compagnie Financiere Richemont" and "Compagnie Financiere Tradition"
    share two of three tokens and are different companies, and a 60%-overlap rule
    accepted them. Under the subset rule neither contains the other's
    distinguishing token, so the pair is correctly rejected, while genuine
    matches still pass — Stuttgart's "LVMH Moet Hennessy Louis Vuitton SE" is a
    subset of Paris's "LVMH Moët Hennessy - Louis Vuitton, Société Européenne".

    The subset must also be substantial. "LVMH" alone is a subset of the
    structured note "EB MemExpr LVMH SE 23-28", which yf.Search returns as a
    quoteType of EQUITY, so a bare containment test would accept a bond.
    """
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return False
    smaller, larger = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    if not smaller <= larger:
        return False
    return len(smaller) / len(larger) >= 0.5


def _search_queries(name: object) -> list:
    """
    Query forms to try, in order.

    Accent-folded, because the accented legal name returns zero quotes. The brand
    token is included because the folded legal name returns only regional lines —
    but it is not trusted on its own: "Compagnie Financiere" finds a different
    company entirely, so every result is still name-checked.
    """
    folded = _fold(name).replace(".", "")   # "N.V." -> "nv", not "n" + "v"
    toks = [t for t in re.sub(r"[^a-z0-9 ]+", " ", folded).split() if len(t) > 1]
    out = []
    if toks:
        # The ORIGINAL spelling first. Folding is a fallback, not a replacement:
        # yf.Search("Nestlé S.A.") ranks the Swiss primary first, while the
        # de-accented "Nestle S.A." drops it off the results entirely. The
        # reverse is also true (LVMH's accented name returns nothing), which is
        # why both forms are tried.
        raw = str(name).strip()
        if raw:
            out.append(raw)
        out.append(" ".join(toks))          # full name, accent-folded
        out.append(toks[0])                 # leading/brand token
        if len(toks) >= 2:
            out.append(" ".join(toks[:2]))
        # The brand is not always the FIRST word. "Koninklijke Philips" leads
        # with a Dutch honorific that returns Vopak and Ahold, and "Compagnie
        # Financiere Richemont" leads with two generic words that return a
        # different company (Compagnie Financière Tradition). In both the brand
        # is the last meaningful token, so try that too. Length is not the
        # signal — "financiere" is longer than "richemont".
        core = [t for t in toks if t not in _NOISE]
        if core:
            out.append(core[-1])
    # Deduped case-insensitively: for a single-word unaccented name the raw and
    # folded forms are the same query, and each one costs a round trip.
    seen, uniq = set(), []
    for q in out:
        if q and q.lower() not in seen:
            seen.add(q.lower())
            uniq.append(q)
    return uniq[:5]


def is_analyzable(info: dict) -> bool:
    """
    A listing we can size and price. Missing either makes valuation meaningless.

    Deliberately narrow. It detects the venues that report nothing (the German
    regional lines, IOB GDRs) but NOT thin lines that echo the full company
    figures on negligible volume — AAPL.VI carries Apple's entire market cap on
    626 shares a day. Those are caught by venue and liquidity ranking instead.
    """
    if not info:
        return False
    price = (
        info.get("currentPrice")
        or info.get("regularMarketPrice")
        or info.get("previousClose")
    )
    return bool(info.get("marketCap")) and bool(price)


def venue_suffix(symbol: str) -> str:
    """Yahoo exchange suffix for a symbol; "" for US listings."""
    if not symbol or "." not in symbol:
        return ""
    return symbol.rsplit(".", 1)[1].upper()


def is_otc(info: dict) -> bool:
    """OTC Markets across all tiers — OTCPK, OTCQX and OTCID."""
    if str(info.get("fullExchangeName") or "").startswith("OTC Markets"):
        return True
    return str(info.get("exchange") or "").upper() in _OTC_EXCHANGES


def is_depositary(info: dict, symbol: str = "") -> bool:
    """A depositary-receipt line rather than a share listing."""
    if str(info.get("exchange") or "").upper() in _GDR_EXCHANGES:
        return True
    return str(info.get("market") or "") in _DR_MARKETS


def is_home_listing(info: dict, symbol: str) -> bool:
    """
    Whether this venue sits in the issuer's country of domicile.

    The strongest signal available: `country` is reported identically across
    every venue for an issuer, so comparing it against the symbol's exchange
    suffix identifies the home line without touching currency or market cap.
    """
    country = info.get("country")
    if not country:
        return False
    return _SUFFIX_COUNTRY.get(venue_suffix(symbol), _US_COUNTRY) == country


def rank_key(info: dict, symbol: str) -> tuple:
    """
    Sort key for candidate listings, best first (use reverse=True).

    Order of authority: a real share listing beats a receipt, the home venue
    beats a foreign cross-listing, then liquidity. currency == financialCurrency
    is last and worth little, because on its own it prefers OTC pink sheets to
    the Amsterdam primary.
    """
    score = 0
    if not is_otc(info):
        score += 400
    if not is_depositary(info, symbol):
        score += 200
    if is_home_listing(info, symbol):
        score += 100
    ccy, fccy = info.get("currency"), info.get("financialCurrency")
    if ccy and fccy and ccy == fccy:
        score += 10
    return (score, info.get("averageVolume") or 0)


def _enrichment_order(candidates: dict) -> list:
    """
    Which candidates are worth an .info call, best-looking first.

    Only the symbol is available at this stage, and each lookup costs a network
    round trip, so this is a cheap pre-sort — not the real ranking, which runs on
    fetched data. It exists so the enrichment budget is not spent entirely on the
    regional lines a legal-name search returns in bulk.
    """
    def key(symbol: str) -> tuple:
        suffix = venue_suffix(symbol)
        known_home = suffix in _SUFFIX_COUNTRY
        regional = suffix in _REGIONAL_SUFFIXES
        # US OTC tickers are conventionally five letters ending in Y (sponsored
        # ADR) or F (ordinary foreign share). Neither is a home listing.
        otc_shaped = not suffix and len(symbol) == 5 and symbol[-1] in ("Y", "F")
        return (not regional, known_home, not otc_shaped)

    return sorted(candidates, key=key, reverse=True)


def better_listing(ticker: str, info: dict) -> Optional[Tuple[str, str]]:
    """
    Find a usable listing for the company currently quoted under ``ticker``.

    Returns ``(symbol, company_name)`` or None. Never raises: a resolution
    failure must degrade to "analyze what was asked for", not abort the run.
    """
    try:
        import yfinance as yf
    except Exception:
        return None

    name = info.get("longName") or info.get("shortName")
    if not name:
        return None

    # Run EVERY query form before enriching anything. Stopping once enough
    # candidates existed meant the full-legal-name search — which returns seven
    # German regional lines for LVMH — filled the quota by itself and the brand
    # query that actually finds MC.PA never ran.
    candidates = {}
    for query in _search_queries(name):
        try:
            quotes = yf.Search(query, max_results=8).quotes or []
        except Exception:
            continue
        for quote in quotes:
            symbol = quote.get("symbol")
            if not symbol or symbol == ticker or quote.get("quoteType") != "EQUITY":
                continue
            # Loose screen only — snippets are truncated. The authoritative
            # check happens below, against the candidate's own longName.
            if not names_might_match(name, quote.get("shortname") or quote.get("longname")):
                continue
            candidates.setdefault(symbol, quote)

    ranked = []
    for symbol in _enrichment_order(candidates)[:_MAX_CANDIDATES]:
        try:
            cand_info = yf.Ticker(symbol).info
        except Exception:
            continue
        if not is_analyzable(cand_info):
            continue
        cand_name = cand_info.get("longName") or cand_info.get("shortName")
        if not same_company(name, cand_name):
            continue
        ranked.append((rank_key(cand_info, symbol), symbol, cand_name or name))

    if not ranked:
        return None
    ranked.sort(key=lambda r: r[0], reverse=True)
    _, symbol, cand_name = ranked[0]
    return symbol, cand_name
