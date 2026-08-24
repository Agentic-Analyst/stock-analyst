"""
Listing resolution — pick the venue that can actually be analyzed.

A company can be quoted on a dozen venues. Yahoo returns them all from a name
search, and the ones it returns *first* are frequently the wrong ones: a search
for "LVMH Moet Hennessy Louis Vuitton SE" returns six German regional lines
(Stuttgart, Munich, Hamburg, Dusseldorf) and never the Paris primary. A real run
picked up MOH.SG that way, and Stuttgart reports no market cap and no shares
outstanding — so the model valued a company it could not size, and the report
shipped as NOT RATED.

The fix is to notice the bad listing rather than to hope the agent guesses well.
A missing market cap is a reliable tell: legitimate foreign primaries (7203.T,
NESN.SW, ASML.AS) all carry complete data, so this never fires on a healthy
non-US ticker. Only when a listing looks unusable do we search for a better line
of the *same* company.

Ranking cannot be "biggest market cap" — LVMH's OTC ADR reports 264B USD against
the Paris line's 226B EUR, which is the same company measured in a different
currency. The signal that identifies a home listing is that it trades in the
currency the company reports its financials in.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Optional, Tuple

# Corporate-form and structure words carry no identifying information, and they
# differ between venues for the same company ("SE" vs "SA", "ADR" vs nothing).
_NOISE = {
    "sa", "se", "ag", "nv", "plc", "inc", "corp", "corporation", "co", "ltd",
    "limited", "the", "company", "holding", "holdings", "group", "adr", "spa",
    "ab", "as", "oyj", "cie", "kgaa", "sas", "bv", "class",
}

# Venues that are not a company's home line. "dr_market" is Yahoo's own label
# for depositary-receipt venues; PNK is OTC Markets, where unsponsored ADRs sit.
_OTC_EXCHANGES = {"PNK", "OTC"}
_DR_MARKETS = {"dr_market"}

_MAX_CANDIDATES = 6  # bounds the extra network calls on the failure path


def _tokens(name: object) -> set:
    """Accent-folded, noise-stripped token set for loose company-name matching."""
    if not name:
        return set()
    folded = unicodedata.normalize("NFKD", str(name))
    folded = "".join(c for c in folded if not unicodedata.combining(c)).lower()
    # Collapse dotted corporate forms BEFORE splitting: "S.A." must become the
    # noise word "sa", not the tokens "s" and "a". Left as single letters they
    # survive the noise filter and can match between unrelated companies.
    folded = folded.replace(".", "")
    folded = re.sub(r"[^a-z0-9 ]+", " ", folded)
    return {t for t in folded.split() if len(t) > 1 and t not in _NOISE}


def same_company(a: object, b: object) -> bool:
    """
    Whether two listing names denote the same company.

    Deliberately strict enough to never swap companies: the ticker "MC" alone
    resolves to Moelis & Company, and substituting across a name mismatch would
    hand the user a report on the wrong business. Requires most of the shorter
    name's tokens to be present, after folding "Moet"/"Moët".
    """
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return False
    overlap = len(ta & tb)
    return overlap >= 1 and overlap >= min(len(ta), len(tb)) * 0.6


def _search_queries(name: object) -> list:
    """
    Yahoo's name search is prefix-sensitive: the full legal name surfaces only
    regional lines, while the leading brand token surfaces the primary. Try both
    rather than betting on either.
    """
    folded = unicodedata.normalize("NFKD", str(name or ""))
    toks = [t for t in re.sub(r"[^A-Za-z0-9 ]+", " ", folded).split() if t]
    out = []
    if name:
        out.append(str(name))
    if toks:
        out.append(toks[0])
    if len(toks) >= 2:
        out.append(" ".join(toks[:2]))
    seen, uniq = set(), []
    for q in out:
        if q.lower() not in seen:
            seen.add(q.lower())
            uniq.append(q)
    return uniq


def is_analyzable(info: dict) -> bool:
    """A listing we can size and price. Missing either makes valuation meaningless."""
    if not info:
        return False
    price = (
        info.get("currentPrice")
        or info.get("regularMarketPrice")
        or info.get("previousClose")
    )
    return bool(info.get("marketCap")) and bool(price)


def _score(info: dict) -> tuple:
    """Rank candidates: home listing first, OTC/DR venues last, liquidity breaks ties."""
    score = 0
    ccy, fccy = info.get("currency"), info.get("financialCurrency")
    if ccy and fccy and ccy == fccy:
        score += 100
    if info.get("exchange") in _OTC_EXCHANGES:
        score -= 50
    if info.get("market") in _DR_MARKETS:
        score -= 50
    return (score, info.get("averageVolume") or 0)


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
            if not same_company(name, quote.get("shortname") or quote.get("longname")):
                continue
            candidates.setdefault(symbol, quote)
        if len(candidates) >= _MAX_CANDIDATES:
            break

    ranked = []
    for symbol in list(candidates)[:_MAX_CANDIDATES]:
        try:
            cand_info = yf.Ticker(symbol).info
        except Exception:
            continue
        if not is_analyzable(cand_info):
            continue
        cand_name = cand_info.get("longName") or cand_info.get("shortName")
        # Re-check against the authoritative name, not the search snippet.
        if not same_company(name, cand_name):
            continue
        ranked.append((_score(cand_info), symbol, cand_name or name))

    if not ranked:
        return None
    ranked.sort(key=lambda r: r[0], reverse=True)
    _, symbol, cand_name = ranked[0]
    return symbol, cand_name
