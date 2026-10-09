"""
What insiders and the company filed with the SEC around a price move.

Insider selling is half of many "why did it fall" stories, and the filings say
it exactly: a Form 144 is a notice that an insider intends to sell (shares,
market value, approximate date), a Form 4 reports a completed transaction with
a code (S open-market sale, P purchase, J other — Benchmark's in-kind
distribution of Cerebras shares to its partners on October 5 was a J). Between
September 1 and October 7, 2026, Cerebras insiders filed six Form 144s; one, on
September 29, gave notice of 396,000 shares worth $77.9 million.

US filers only (the CIK comes from sec_filer's cached ticker table). Each
filing's document is cached for good — a filing never changes — and the whole
lookup runs under a time budget so a slow EDGAR cannot stall a chat answer.
Never raises; None means nothing could be read.
"""

from __future__ import annotations

import json
import time
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import date
from typing import Any, Dict, List, Optional

_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
_ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{document}"
_SUBMISSIONS_MAX_AGE = 3600
_DOCUMENT_MAX_AGE = 10 * 365 * 86400
_MAX_DOCUMENTS = 24

FORM_MEANINGS = {
    "144": "notice of an insider's proposed sale (intent, not a completed sale)",
    "4": "insider transaction report (completed)",
    "8-K": "material event report",
    "S-1": "registration of a share offering", "S-3": "shelf registration (future share sales)",
    "S-8": "registration of employee-plan shares", "424B4": "final offering prospectus",
    "424B5": "offering prospectus supplement", "424B3": "prospectus (resale/offering)",
    "SC 13D": "5%+ holder with intent to influence", "SC 13G": "5%+ passive holder",
    "SC 13D/A": "amended 5%+ holder report", "SC 13G/A": "amended 5%+ holder report",
    "10-Q": "quarterly report", "10-K": "annual report",
}
TRANSACTION_CODES = {
    "S": "open-market or private sale", "P": "open-market or private purchase",
    "M": "option exercise", "A": "grant or award", "F": "shares withheld for tax",
    "G": "gift", "J": "other (e.g. a fund's in-kind distribution to its partners)",
    "C": "conversion", "D": "disposition to the issuer", "X": "option exercise",
}
EIGHT_K_ITEMS = {
    "1.01": "entered a material agreement", "1.02": "ended a material agreement",
    "2.02": "results of operations", "2.03": "new debt or obligation",
    "2.05": "restructuring costs", "2.06": "impairment",
    "3.01": "listing standard notice", "3.02": "unregistered share sale",
    "4.01": "auditor change", "4.02": "prior financials no longer reliable",
    "5.02": "director or officer change", "5.07": "shareholder vote",
    "7.01": "Regulation FD disclosure", "8.01": "other event", "9.01": "exhibits",
}


def _netcache():
    from src.agents.fm import netcache
    return netcache


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _find(root, name: str):
    for element in root.iter():
        if _local(element.tag) == name:
            return element
    return None


def _text(root, name: str) -> Optional[str]:
    element = _find(root, name)
    if element is None:
        return None
    value = _find(element, "value")
    text = (value.text if value is not None else element.text) or ""
    return text.strip() or None


def _number(value: Optional[str]) -> Optional[float]:
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def parse_form144(xml_text: str) -> Optional[Dict[str, Any]]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None
    relationships = [(_local(e.tag), (e.text or "").strip()) for e in root.iter()
                     if _local(e.tag) == "relationshipToIssuer"]
    return {
        "seller": _text(root, "nameOfPersonForWhoseAccountTheSecuritiesAreToBeSold"),
        "relationship": ", ".join(r for _, r in relationships if r) or None,
        "shares": _number(_text(root, "noOfUnitsSold")),
        "market_value": _number(_text(root, "aggregateMarketValue")),
        "approx_sale_date": _text(root, "approxSaleDate"),
    }


def parse_form4(xml_text: str) -> Optional[Dict[str, Any]]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None
    rel = _find(root, "reportingOwnerRelationship")
    role = []
    if rel is not None:
        if (_text(rel, "isDirector") or "") in ("1", "true"):
            role.append("director")
        if (_text(rel, "isOfficer") or "") in ("1", "true"):
            role.append(_text(rel, "officerTitle") or "officer")
        if (_text(rel, "isTenPercentOwner") or "") in ("1", "true"):
            role.append("10% owner")
    transactions = []
    for tx in root.iter():
        if _local(tx.tag) != "nonDerivativeTransaction":
            continue
        transactions.append({
            "date": _text(tx, "transactionDate"),
            "code": _text(tx, "transactionCode"),
            "acquired_or_disposed": _text(tx, "transactionAcquiredDisposedCode"),
            "shares": _number(_text(tx, "transactionShares")),
            "price": _number(_text(tx, "transactionPricePerShare")),
        })
    return {"owner": _text(root, "rptOwnerName"), "role": ", ".join(role) or None,
            "transactions": transactions}


def _document(cik: int, row: Dict[str, Any], deadline: float) -> Optional[str]:
    cache = _netcache()
    accession = str(row.get("accessionNumber") or "").replace("-", "")
    name = f"sec_doc_{accession}"
    cached = cache.cache_get(name, _DOCUMENT_MAX_AGE)
    if isinstance(cached, dict) and "xml" in cached:
        return cached["xml"]
    if time.monotonic() > deadline:
        return None
    # The rendered path (xslF345X06/…) is HTML; the raw XML sits beside it.
    document = str(row.get("primaryDocument") or "").split("/")[-1]
    if not accession or not document.endswith(".xml"):
        return None
    try:
        xml_text = cache.http_get(_ARCHIVE_URL.format(cik=cik, accession=accession, document=document),
                                  timeout=6.0).decode("utf-8", "replace")
    except Exception:
        return None
    cache.cache_put(name, {"xml": xml_text})
    return xml_text


def filing_activity(ticker: str, start: date, end: date, budget_seconds: float = 8.0) -> Optional[Dict[str, Any]]:
    """Counts and parsed details of the SEC filings dated between two days."""
    try:
        from src.sec_filer import _ciks
        cik = _ciks().get((ticker or "").strip().upper())
    except Exception:
        return None
    if not cik:
        return None
    deadline = time.monotonic() + budget_seconds
    cache = _netcache()
    try:
        name = f"sec_submissions_{cik}"
        submissions = cache.cache_get(name, _SUBMISSIONS_MAX_AGE)
        if not isinstance(submissions, dict):
            submissions = json.loads(cache.http_get(_SUBMISSIONS_URL.format(cik=cik), timeout=8.0))
            cache.cache_put(name, submissions)
        recent = submissions["filings"]["recent"]
        rows = [dict(zip(recent.keys(), values)) for values in zip(*recent.values())]
    except Exception:
        return None
    lo, hi = start.isoformat(), end.isoformat()
    rows = [r for r in rows if lo <= str(r.get("filingDate") or "") <= hi]
    counts = Counter(str(r.get("form")) for r in rows)
    out: Dict[str, Any] = {
        "window": f"{lo} to {hi}",
        "counts": dict(counts),
        "form_meanings": {f: FORM_MEANINGS[f] for f in counts if f in FORM_MEANINGS},
    }

    notices = []
    for row in [r for r in rows if r.get("form") == "144"][:_MAX_DOCUMENTS]:
        parsed = parse_form144(_document(cik, row, deadline) or "")
        if parsed:
            notices.append({"filed": row.get("filingDate"), **parsed})
    if notices:
        out["form144_notices"] = {
            "filings": len(notices),
            "shares": sum(n["shares"] or 0 for n in notices),
            "market_value": round(sum(n["market_value"] or 0 for n in notices), 2),
            "largest": sorted(notices, key=lambda n: -(n["market_value"] or 0))[:3],
        }

    by_code: Dict[str, Dict[str, float]] = defaultdict(lambda: {"shares": 0.0, "value": 0.0, "filings": 0})
    owners: Dict[str, Dict[str, Any]] = {}
    parsed4 = 0
    for row in [r for r in rows if r.get("form") == "4"][:_MAX_DOCUMENTS]:
        parsed = parse_form4(_document(cik, row, deadline) or "")
        if not parsed:
            continue
        parsed4 += 1
        codes = set()
        for tx in parsed["transactions"]:
            code = f"{tx['code'] or '?'}/{tx['acquired_or_disposed'] or '?'}"
            codes.add(code)
            by_code[code]["shares"] += tx["shares"] or 0
            by_code[code]["value"] += (tx["shares"] or 0) * (tx["price"] or 0)
            if code.startswith("S/"):
                o = owners.setdefault(parsed["owner"] or "?", {"role": parsed["role"], "shares_sold": 0.0})
                o["shares_sold"] += tx["shares"] or 0
        for code in codes:
            by_code[code]["filings"] += 1
    if parsed4:
        out["form4_transactions"] = {
            "filings_read": parsed4,
            "by_code": {code: {"meaning": TRANSACTION_CODES.get(code.split("/")[0], "other"),
                               "acquired_or_disposed": {"A": "acquired", "D": "disposed"}.get(code.split("/")[1]),
                               "shares": round(v["shares"]), "value_usd": round(v["value"], 2),
                               "filings": int(v["filings"])}
                        for code, v in sorted(by_code.items())},
            "top_sellers": sorted(({"owner": k, **v} for k, v in owners.items()),
                                  key=lambda o: -o["shares_sold"])[:3],
        }

    events = []
    for row in rows:
        form = str(row.get("form"))
        if form == "8-K":
            items = [i.strip() for i in str(row.get("items") or "").split(",") if i.strip()]
            events.append({"filed": row.get("filingDate"), "form": form,
                           "items": [f"{i} {EIGHT_K_ITEMS.get(i, '')}".strip() for i in items if i != "9.01"]})
        elif form in FORM_MEANINGS and form not in ("4", "144"):
            events.append({"filed": row.get("filingDate"), "form": form, "meaning": FORM_MEANINGS[form]})
    if events:
        out["other_filings"] = events[:12]
    if time.monotonic() > deadline:
        out["note"] = "time budget reached; some filings were counted but not read"
    return out
