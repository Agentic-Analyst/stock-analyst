"""
Sovereign 10-year yields by currency, from official feeds, with provenance.

Before this module the risk-free rate was live for USD (^TNX), a dated table
entry for EUR, and a US proxy for everything else: Toyota's yen cash flows were
discounted on a Treasury yield, PC Jeweller's rupee flows likewise. The report
said so, which beats hiding it, but a labelled wrong number is still wrong —
the yen 10Y is 2.9%, not 4.8%, and the Swiss one is 0.3%.

Sources, in the order tried for each currency:

  USD   Yahoo ^TNX (intraday)            then FRED DGS10 (daily)
  EUR   ECB euro-area AAA 10Y (daily)     then FRED Germany (monthly)
  JPY   Japan MOF JGB 10Y (daily)         then FRED Japan (monthly)
  GBP CHF INR KRW AUD CAD MXN ZAR SEK NOK DKK NZD PLN ILS HUF CZK CLP
        FRED "long-term government bond yields" (OECD, monthly, ~2-month lag)

FRED's fredgraph.csv endpoint is public and needs no key. Each resolved rate is
cached for a few hours (see netcache) so a basket of runs does not hit the
sources once per company.

When every feed fails, the module falls back to a dated snapshot of the same
series (below), then — only for currencies with neither feed nor snapshot — to
the US yield, and labels each case. The label is printed in the report beside
the number, and RISK_FREE_<CCY> still overrides the final rate without a deploy.
"""

from __future__ import annotations

import csv
import io
import logging
import re
from typing import Callable, Dict, List, Optional, Tuple

from . import netcache

_log = logging.getLogger(__name__)

_TIMEOUT = 8.0
_CACHE_TTL = 6 * 3600          # a resolved rate is reused for six hours
_MAX_AGE_DAYS = 400            # older than this and the series is dead, not lagged

_FRED = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={id}"
_ECB = ("https://data-api.ecb.europa.eu/service/data/YC/"
        "B.U2.EUR.4F.G_N_A.SV_C_YM.SR_10Y?lastNObservations=5&format=csvdata")
_MOF = "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/jgbcme.csv"

# currency -> FRED series, instrument label
_FRED_SERIES = {
    "USD": ("DGS10", "US 10Y Treasury"),
    "EUR": ("IRLTLT01DEM156N", "10Y German Bund"),
    "GBP": ("IRLTLT01GBM156N", "10Y Gilt"),
    "JPY": ("IRLTLT01JPM156N", "10Y JGB"),
    "CHF": ("IRLTLT01CHM156N", "10Y Swiss Confederation bond"),
    "INR": ("INDIRLTLT01STM", "10Y India G-Sec"),
    "KRW": ("IRLTLT01KRM156N", "10Y Korea Treasury bond"),
    "AUD": ("IRLTLT01AUM156N", "10Y Australian government bond"),
    "CAD": ("IRLTLT01CAM156N", "10Y Canadian government bond"),
    "MXN": ("IRLTLT01MXM156N", "10Y Mexican government bond"),
    "ZAR": ("IRLTLT01ZAM156N", "10Y South African government bond"),
    "SEK": ("IRLTLT01SEM156N", "10Y Swedish government bond"),
    "NOK": ("IRLTLT01NOM156N", "10Y Norwegian government bond"),
    "DKK": ("IRLTLT01DKM156N", "10Y Danish government bond"),
    "NZD": ("IRLTLT01NZM156N", "10Y New Zealand government bond"),
    "PLN": ("IRLTLT01PLM156N", "10Y Polish government bond"),
    "ILS": ("IRLTLT01ILM156N", "10Y Israeli government bond"),
    "HUF": ("IRLTLT01HUM156N", "10Y Hungarian government bond"),
    "CZK": ("IRLTLT01CZM156N", "10Y Czech government bond"),
    "CLP": ("IRLTLT01CLM156N", "10Y Chilean government bond"),
}

# Offline fallback: the same series, as last observed. Dated, labelled as a
# snapshot when used, and never preferred to a live read. Markets with no free
# feed at all (CNY, HKD, TWD, SGD, BRL, IDR, THB, MYR) are only ever served
# from here, which the label says.
#   currency: (rate, instrument, as_of)
_SNAPSHOT: Dict[str, Tuple[float, str, str]] = {
    "USD": (0.0477, "US 10Y Treasury", "2026-09-03"),
    "EUR": (0.0336, "euro-area AAA 10Y", "2026-09-03"),
    "JPY": (0.0291, "10Y JGB", "2026-09-04"),
    "GBP": (0.0480, "10Y Gilt", "2026-06"),
    "CHF": (0.0031, "10Y Swiss Confederation bond", "2026-06"),
    "INR": (0.0689, "10Y India G-Sec", "2026-06"),
    "KRW": (0.0418, "10Y Korea Treasury bond", "2026-06"),
    "AUD": (0.0483, "10Y Australian government bond", "2026-06"),
    "CAD": (0.0342, "10Y Canadian government bond", "2026-06"),
    "MXN": (0.0945, "10Y Mexican government bond", "2026-05"),
    "ZAR": (0.0870, "10Y South African government bond", "2026-06"),
    "SEK": (0.0278, "10Y Swedish government bond", "2026-06"),
    "NOK": (0.0420, "10Y Norwegian government bond", "2026-06"),
    "DKK": (0.0281, "10Y Danish government bond", "2026-06"),
    "NZD": (0.0446, "10Y New Zealand government bond", "2026-06"),
    "PLN": (0.0551, "10Y Polish government bond", "2026-06"),
    "ILS": (0.0381, "10Y Israeli government bond", "2026-06"),
    "HUF": (0.0526, "10Y Hungarian government bond", "2026-06"),
    "CZK": (0.0470, "10Y Czech government bond", "2026-06"),
    "CLP": (0.0552, "10Y Chilean government bond", "2026-06"),
    "CNY": (0.0168, "10Y China government bond", "2026-09-04"),
    "HKD": (0.0332, "10Y Hong Kong government bond", "2026-06-12"),
    "TWD": (0.0170, "10Y Taiwan government bond", "2026-07-14"),
    "SGD": (0.0239, "10Y Singapore government bond", "2026-09-04"),
    "BRL": (0.1435, "10Y Brazilian government bond", "2026-09-04"),
    "IDR": (0.0723, "10Y Indonesian government bond", "2026-09-02"),
    "THB": (0.0236, "10Y Thai government bond", "2026-09"),
    "MYR": (0.0374, "10Y Malaysian government bond", "2026-08-07"),
}
_FALLBACK = 0.043   # last resort for a currency with nothing at all


# Yahoo quotes some listings in minor units: pence (GBp/GBX), South African
# cents (ZAc), Israeli agorot (ILA). The bond behind them is the major unit's.
_MINOR_UNITS = {"GBX": "GBP", "GBP": "GBP", "ZAC": "ZAR", "ILA": "ILS"}

# One resolution per currency per process, including the fallbacks: a run
# builds the cost of capital more than once, and a feed outage must be paid
# for once, not on every call.
_memo: Dict[str, Dict[str, object]] = {}


def _reset_memo() -> None:
    _memo.clear()


def normalise_currency(currency: Optional[str]) -> str:
    c = (currency or "USD").strip().upper()
    return _MINOR_UNITS.get(c, c) or "USD"


# ---------------------------------------------------------------- feeds ----

def _sane(rate: float) -> bool:
    return -0.01 <= rate <= 0.30


def _days_between(as_of: str, today: str) -> Optional[int]:
    import datetime as dt
    try:
        a = dt.date.fromisoformat(as_of if len(as_of) == 10 else as_of + "-01")
        t = dt.date.fromisoformat(today)
        return (t - a).days
    except ValueError:
        return None


def _today() -> str:
    import datetime as dt
    return dt.date.today().isoformat()


def _fresh_enough(as_of: str) -> bool:
    days = _days_between(as_of, _today())
    return days is None or days <= _MAX_AGE_DAYS


def _yahoo_tnx() -> Optional[Tuple[float, str]]:
    """US 10Y via ^TNX, quoted as yield x10 on most days (47.7 = 4.77%)."""
    try:
        import yfinance as yf
        h = yf.Ticker("^TNX").history(period="5d")
        if h is None or h.empty:
            return None
        close = float(h["Close"].iloc[-1])
        as_of = str(h.index[-1])[:10]
        for scale in (1000.0, 100.0):
            rf = close / scale
            if 0.02 <= rf <= 0.08:
                return rf, as_of
    except Exception:
        pass
    return None


def parse_fred_csv(text: str) -> Optional[Tuple[float, str]]:
    """Last dated, numeric observation of a fredgraph.csv (missing days are ".")."""
    last = None
    for row in csv.reader(io.StringIO(text)):
        if len(row) < 2 or not re.match(r"^\d{4}-\d{2}-\d{2}$", row[0]):
            continue
        try:
            last = (float(row[1]) / 100.0, row[0])
        except ValueError:
            continue
    return last


def _fred(series_id: str) -> Optional[Tuple[float, str]]:
    text = netcache.http_get(_FRED.format(id=series_id), _TIMEOUT).decode("utf-8", "replace")
    got = parse_fred_csv(text)
    if not got or not _sane(got[0]) or not _fresh_enough(got[1]):
        return None
    if series_id != "DGS10":
        got = (got[0], got[1][:7])       # monthly series: label the month
    return got


def parse_ecb_csv(text: str) -> Optional[Tuple[float, str]]:
    last = None
    for row in csv.DictReader(io.StringIO(text)):
        try:
            last = (float(row["OBS_VALUE"]) / 100.0, row["TIME_PERIOD"][:10])
        except (KeyError, ValueError, TypeError):
            continue
    return last


def _ecb() -> Optional[Tuple[float, str]]:
    got = parse_ecb_csv(netcache.http_get(_ECB, _TIMEOUT).decode("utf-8", "replace"))
    return got if got and _sane(got[0]) and _fresh_enough(got[1]) else None


def parse_mof_csv(text: str) -> Optional[Tuple[float, str]]:
    """The MOF file: a title line, a "Date,1Y,...,10Y,..." header, daily rows."""
    col = None
    last = None
    for row in csv.reader(io.StringIO(text)):
        if not row:
            continue
        if row[0].strip() == "Date":
            col = next((i for i, h in enumerate(row) if h.strip() == "10Y"), None)
            continue
        m = re.match(r"^(\d{4})/(\d{1,2})/(\d{1,2})$", row[0].strip())
        if not m or col is None or col >= len(row):
            continue
        try:
            last = (float(row[col]) / 100.0, f"{m[1]}-{int(m[2]):02d}-{int(m[3]):02d}")
        except ValueError:
            continue
    return last


def _mof() -> Optional[Tuple[float, str]]:
    got = parse_mof_csv(netcache.http_get(_MOF, _TIMEOUT).decode("utf-8", "replace"))
    return got if got and _sane(got[0]) and _fresh_enough(got[1]) else None


def _feeds(ccy: str) -> List[Tuple[str, str, Callable[[], Optional[Tuple[float, str]]]]]:
    """(source name, instrument, fetcher) in the order to try."""
    out = []
    if ccy == "USD":
        out.append(("Yahoo", "US 10Y Treasury", _yahoo_tnx))
    elif ccy == "EUR":
        out.append(("ECB", "euro-area AAA 10Y", _ecb))
    elif ccy == "JPY":
        out.append(("Japan MOF", "10Y JGB", _mof))
    if ccy in _FRED_SERIES:
        sid, instrument = _FRED_SERIES[ccy]
        out.append(("FRED", instrument, lambda sid=sid: _fred(sid)))
    return out


# ------------------------------------------------------------- resolver ----

def _label(rate: float, instrument: str, source: str, as_of: str) -> str:
    return f"{instrument} {rate*100:.2f}% ({source}, as of {as_of})"


def _valid(entry: object) -> bool:
    """
    A disk-cache hit is untrusted input: the file is shared by every worker
    image that has ever run on the host and can be edited by hand. A
    well-formed JSON of the wrong shape must read as a miss, not raise in the
    middle of a run or seed a 9,899% risk-free rate into a workbook.
    """
    if not isinstance(entry, dict):
        return False
    rate = entry.get("rate")
    if isinstance(rate, bool) or not isinstance(rate, (int, float)) or not _sane(float(rate)):
        return False
    return all(isinstance(entry.get(k), str) and entry.get(k) for k in ("label", "source", "instrument", "as_of"))


def sovereign_yield(currency: Optional[str]) -> Dict[str, object]:
    """
    The 10-year government yield for ``currency`` and where it came from.

    Returns a dict with ``rate``, ``instrument``, ``source`` (Yahoo / ECB /
    Japan MOF / FRED / snapshot / proxy / fallback), ``as_of``, ``proxy``
    (True when the number is a US yield standing in for a currency we cannot
    source) and ``label`` — the sentence printed in the report. Never raises.
    """
    ccy = normalise_currency(currency)
    hit = _memo.get(ccy)
    if hit is None:
        hit = _resolve(ccy)
        _memo[ccy] = hit
    return dict(hit)


def _resolve(ccy: str) -> Dict[str, object]:
    key = f"sovereign_{ccy}"

    cached = netcache.cache_get(key, _CACHE_TTL)
    if _valid(cached):
        return dict(cached)

    for source, instrument, fetch in _feeds(ccy):
        try:
            got = fetch()
        except Exception as exc:
            _log.debug("sovereign yield: %s feed failed for %s: %s", source, ccy, exc)
            got = None
        if got:
            rate, as_of = got
            result = {"currency": ccy, "rate": float(rate), "instrument": instrument,
                      "source": source, "as_of": as_of, "proxy": False,
                      "label": _label(rate, instrument, source, as_of)}
            netcache.cache_put(key, result)
            return result

    # Every feed is down. A copy an earlier run left on disk — this morning's
    # FRED read, say — is newer than anything embedded below, so it comes
    # first, relabelled so the reader sees it was not fetched today.
    stale = netcache.cache_get(key, _MAX_AGE_DAYS * 86400)
    if _valid(stale):
        out = dict(stale)
        out["source"] = f"{stale['source']}, cached"
        out["label"] = (f"{stale['instrument']} {float(stale['rate'])*100:.2f}% ({stale['source']}, "
                        f"as of {stale['as_of']}; cached — live feed unavailable)")
        return out

    if ccy in _SNAPSHOT:
        rate, instrument, as_of = _SNAPSHOT[ccy]
        why = " — live feed unavailable" if ccy in _FRED_SERIES else " — no live feed for this market"
        is_stale = not _fresh_enough(as_of)
        if is_stale:
            _log.warning("sovereign yield for %s is a STALE snapshot as of %s; set SOVEREIGN "
                         "RISK_FREE_%s or refresh the snapshot", ccy, as_of, ccy)
        return {"currency": ccy, "rate": rate, "instrument": instrument, "source": "snapshot",
                "as_of": as_of, "proxy": False, "stale": is_stale,
                "label": f"{instrument} {rate*100:.2f}% ({'STALE ' if is_stale else ''}snapshot as of {as_of}{why})"}

    # Nothing for this currency at all. Say so rather than pretending the US
    # rate is this currency's risk-free — and say where the US number itself
    # came from, since it may be a snapshot too.
    us = sovereign_yield("USD")
    if us.get("source") != "fallback":
        rate = float(us["rate"])
        return {"currency": ccy, "rate": rate, "instrument": "US 10Y Treasury", "source": "proxy",
                "proxy_source": us.get("source"), "as_of": us.get("as_of"), "proxy": True,
                "label": f"{us['label']} used as a proxy — no {ccy} sovereign yield source available"}
    return {"currency": ccy, "rate": _FALLBACK, "instrument": None, "source": "fallback",
            "as_of": None, "proxy": True,
            "label": f"fallback {_FALLBACK*100:.2f}% — no {ccy} sovereign yield source available"}
