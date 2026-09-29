"""
Whether a company reports to the SEC as a US company.

A foreign company is valued on its home listing (src/listing_view.py), but not
one whose main market is the US: Yum China (Delaware, NYSE, with a secondary
listing in Hong Kong), Waste Connections and Shopify (Toronto listings, US
filers). Trading volume cannot tell those from a foreign company with a busy
ADR (Infosys's NYSE line trades 1.8x its Mumbai line, Yum China's 1.9x Hong
Kong's), and Yahoo does not mark receipts. The SEC does: a company that files
its annual report on Form 10-K reports as a US domestic issuer, one that files
20-F or 40-F as a foreign private issuer. Measured 2026-09-28: YUMC, WCN, SHOP,
TEVA, LOGI, FLUT and CRH file 10-K; INFY, AZN, RIO, TSM, NVO, SAP, SONY, HDB,
BABA, SPOT, ARM, STLA and RACE file 20-F; TRI, BN, AEM, WPM and NTR file 40-F.

Both files are public and cached on disk (the ticker table for a week, each
company's form for a month). Never raises: None means "not known", and the
caller keeps its default.
"""

from __future__ import annotations

import json
from typing import Optional

_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
_TICKERS_MAX_AGE = 7 * 86400
_FORM_MAX_AGE = 30 * 86400

# Annual-report forms: True for a US domestic filer, False for a foreign one.
_ANNUAL_FORMS = {
    "10-K": True, "10-K/A": True, "10-KT": True, "10-KT/A": True,
    "20-F": False, "20-F/A": False, "40-F": False, "40-F/A": False,
}


def _netcache():
    from src.agents.fm import netcache
    return netcache


def _ciks() -> dict:
    """US ticker -> SEC CIK, cached."""
    cache = _netcache()
    table = cache.cache_get("sec_company_tickers", _TICKERS_MAX_AGE)
    if isinstance(table, dict) and table:
        return table
    raw = json.loads(cache.http_get(_TICKERS_URL, timeout=10.0))
    table = {str(row["ticker"]).upper(): int(row["cik_str"])
             for row in (raw.values() if isinstance(raw, dict) else raw)
             if isinstance(row, dict) and row.get("ticker") and row.get("cik_str")}
    if table:
        cache.cache_put("sec_company_tickers", table)
    return table


def annual_form(ticker: str) -> Optional[str]:
    """The form of the company's latest annual report (10-K, 20-F, 40-F), or None."""
    try:
        cik = _ciks().get((ticker or "").strip().upper())
        if not cik:
            return None
        cache = _netcache()
        name = f"sec_annual_form_{cik}"
        cached = cache.cache_get(name, _FORM_MAX_AGE)
        if isinstance(cached, dict) and "form" in cached:
            return cached["form"]
        submissions = json.loads(cache.http_get(_SUBMISSIONS_URL.format(cik=cik), timeout=10.0))
        forms = (((submissions or {}).get("filings") or {}).get("recent") or {}).get("form") or []
        form = next((f for f in forms if f in _ANNUAL_FORMS), None)
        cache.cache_put(name, {"form": form})
        return form
    except Exception:
        return None


def files_as_us_company(ticker: str) -> Optional[bool]:
    """True for a 10-K filer, False for a 20-F or 40-F filer, None when unknown."""
    return _ANNUAL_FORMS.get(annual_form(ticker) or "")
