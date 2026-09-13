"""Comparable-company multiples from an explicitly configured provider."""
from __future__ import annotations

import math
import os
import statistics
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests
import yfinance as yf

FINNHUB_BASE_URL = "https://finnhub.io/api/v1"
MAX_PEERS = 10
_MEGACAP_SECTOR_FALLBACK_USD = 250_000_000_000
_YAHOO_SECTOR_KEYS = {
    "basic materials": "basic-materials",
    "communication services": "communication-services",
    "consumer cyclical": "consumer-cyclical",
    "consumer defensive": "consumer-defensive",
    "energy": "energy",
    "financial services": "financial-services",
    "healthcare": "healthcare",
    "industrials": "industrials",
    "real estate": "real-estate",
    "technology": "technology",
    "utilities": "utilities",
}

# Symbols in one set are separately traded share classes of the same issuer,
# not independent comparable companies.  Provider peer/sector endpoints often
# return both classes (most visibly GOOGL -> GOOG).  Counting the other class
# inflated the observation count and could turn two real peers into the three
# required for a usable median.  Keep the list deliberately explicit: trying
# to infer issuer identity from a trailing ``A`` would incorrectly collapse
# unrelated symbols such as AAP/AAPL.
_SAME_ISSUER_SHARE_CLASSES = (
    frozenset({"GOOG", "GOOGL"}),
    frozenset({"FOX", "FOXA"}),
    frozenset({"NWS", "NWSA"}),
    frozenset({"BRK.A", "BRK.B", "BRK-A", "BRK-B"}),
    frozenset({"HEI", "HEI.A", "HEI-A"}),
)


def _same_issuer_share_class(subject: str, candidate: str) -> bool:
    subject = str(subject or "").strip().upper()
    candidate = str(candidate or "").strip().upper()
    return any(
        subject in group and candidate in group
        for group in _SAME_ISSUER_SHARE_CLASSES
    )

EV_EBITDA_KEYS = (
    # ``evEbitdaTTM`` is the spelling returned by Finnhub's live
    # /stock/metric endpoint. Keep the historical aliases because provider
    # payloads and saved fixtures have used each of them over time.
    "evEbitdaTTM", "evToEbitdaTTM", "currentEv/ebitdaTTM",
    "enterpriseValueOverEBITDATTM",
)
PRICE_SALES_KEYS = (
    "priceToSalesTTM", "psTTM", "price/salesTTM",
)
MARKET_CAP_KEYS = ("marketCapitalization", "marketCapitalizationM")
OPERATING_MARGIN_KEYS = ("operatingMarginTTM",)
REVENUE_GROWTH_KEYS = ("revenueGrowthTTMYoy",)
PRICE_BOOK_KEYS = ("pbQuarterly", "pb", "pbAnnual")
PRICE_EARNINGS_KEYS = ("peTTM", "peExclExtraTTM", "peAnnual")
RETURN_ON_EQUITY_KEYS = ("roeTTM", "roeRfy", "roe5Y")


def _positive(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) and number > 0 else None


def _first(metric: Dict[str, Any], keys) -> Optional[float]:
    for key in keys:
        value = _positive(metric.get(key))
        if value is not None:
            return value
    return None


def _signed_first(metric: Dict[str, Any], keys) -> Optional[float]:
    for key in keys:
        value = metric.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            number = float(value)
            if math.isfinite(number):
                return number
    return None


def _mode() -> str:
    # Opt in. A Finnhub key is also used for analyst ratings, so its presence
    # must not automatically add 10+ peer requests and a weaker valuation leg.
    raw = (os.getenv("PEER_COMPS_ENABLED") or "false").strip().lower()
    if raw in ("0", "false", "no", "off", "disabled"):
        return "disabled"
    if raw in ("1", "true", "yes", "on", "enabled"):
        return "enabled"
    # Historical deployments used ``auto`` to mean "enable whenever the
    # Finnhub analyst-data key exists." That violates the opt-in contract and
    # silently reactivated a valuation leg that had failed peer-quality
    # canaries. Unknown values now fail closed and remain visible in health.
    return "invalid"


def enabled() -> bool:
    """Enable only when requested and provider credentials are present."""
    mode = _mode()
    if mode != "enabled":
        return False
    return bool((os.getenv("FINNHUB_API_KEY") or "").strip())


def configuration_status() -> Dict[str, Any]:
    """Non-secret feature status suitable for logs and health diagnostics."""
    has_key = bool((os.getenv("FINNHUB_API_KEY") or "").strip())
    toggle_configured = os.getenv("PEER_COMPS_ENABLED") is not None
    mode = _mode()
    is_enabled = enabled()
    blockers = []
    if mode == "disabled":
        blockers.append(
            "PEER_COMPS_ENABLED explicitly disables peer comps"
            if toggle_configured else
            "PEER_COMPS_ENABLED is unset; peer comps use the safe off default"
        )
    elif mode == "invalid":
        blockers.append(
            "PEER_COMPS_ENABLED must be explicitly true to enable peer comps"
        )
    if not has_key:
        blockers.append("FINNHUB_API_KEY is not configured")
    return {
        "mode": mode,
        "enabled": is_enabled,
        "provider": "finnhub",
        "provider_key_configured": has_key,
        "ready": is_enabled and has_key,
        "blockers": blockers,
    }


class FinnhubPeerClient:
    def __init__(self, api_key: str, *, session=requests, timeout: float = 10.0):
        self.api_key = (api_key or "").strip()
        self.session = session
        self.timeout = timeout

    def _get(self, path: str, **params) -> Any:
        for attempt in range(3):
            response = self.session.get(
                f"{FINNHUB_BASE_URL}{path}",
                params=params,
                headers={"X-Finnhub-Token": self.api_key},
                timeout=self.timeout,
            )
            status = getattr(response, "status_code", 200)
            if status != 429 and status < 500:
                response.raise_for_status()
                return response.json()
            if attempt < 2:
                retry_after = getattr(response, "headers", {}).get("Retry-After", "")
                try:
                    delay = min(max(float(retry_after), 0.25), 2.0)
                except (TypeError, ValueError):
                    delay = 0.25 * (2 ** attempt)
                time.sleep(delay)
                continue
            response.raise_for_status()
        return {}  # pragma: no cover

    def peers(self, ticker: str) -> List[str]:
        value = self._get("/stock/peers", symbol=ticker, grouping="subIndustry")
        return value if isinstance(value, list) else []

    def metrics(self, ticker: str) -> Dict[str, Any]:
        value = self._get("/stock/metric", symbol=ticker, metric="all")
        return (value.get("metric") or {}) if isinstance(value, dict) else {}


def _yahoo_sector_leaders(sector: Optional[str]) -> List[str]:
    """Best-effort broad-sector leaders for mega-caps with no size peers."""
    key = _YAHOO_SECTOR_KEYS.get(str(sector or "").strip().lower())
    if not key:
        return []
    try:
        frame = yf.Sector(key).top_companies
        return [str(symbol).strip().upper() for symbol in frame.index]
    except Exception:
        return []


def collect_peer_comps(ticker: str, *, client: Optional[FinnhubPeerClient] = None,
                       max_peers: Optional[int] = None,
                       subject_market_cap: Optional[float] = None,
                       sector: Optional[str] = None,
                       fallback_symbols: Optional[List[str]] = None,
                       valuation_method: Optional[str] = None,
                       subject_operating_margin: Optional[float] = None,
                       subject_revenue_growth: Optional[float] = None,
                       subject_return_on_equity: Optional[float] = None) -> Dict[str, Any]:
    """Median trading multiples for same-subindustry peers; empty if unavailable."""
    bank_method = valuation_method == "justified_pb_roe"
    owns_client = client is None
    if client is None:
        if not enabled():
            return {}
        key = (os.getenv("FINNHUB_API_KEY") or "").strip()
        if not key:
            return {}
        client = FinnhubPeerClient(key)
    ticker = (ticker or "").strip().upper()
    if not ticker:
        return {}
    try:
        peers = client.peers(ticker)
    except Exception as error:
        return {
            "source": "finnhub",
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "status": "provider_error",
            "error_type": type(error).__name__,
            "included_in_blended_value": False,
        }

    try:
        configured = int(max_peers if max_peers is not None
                         else (os.getenv("PEER_COMPS_MAX_PEERS") or MAX_PEERS))
    except (TypeError, ValueError):
        configured = MAX_PEERS
    limit = max(1, min(configured, MAX_PEERS))
    # Finnhub's sub-industry list for a dominant company can contain only much
    # smaller hardware vendors (AAPL -> DELL/WDC/HPE/HPQ). The 5% size floor
    # correctly rejects them all, but that also left every mega-cap with no
    # independent market leg. For USD mega-caps only, use Yahoo's transparent
    # top-sector roster as a broader fallback universe while retaining Finnhub
    # as the multiples source and all size/multiple bounds.
    try:
        use_sector_fallback = bool(
            subject_market_cap
            and float(subject_market_cap) >= _MEGACAP_SECTOR_FALLBACK_USD
            and sector
        )
    except (TypeError, ValueError):
        use_sector_fallback = False
    try:
        subject_market_cap_m = (
            float(subject_market_cap) / 1_000_000.0
            if subject_market_cap and float(subject_market_cap) > 0 else None
        )
    except (TypeError, ValueError):
        subject_market_cap_m = None
    try:
        minimum_size_ratio = float(os.getenv("PEER_COMPS_MIN_SIZE_RATIO", "0.05") or 0.05)
    except ValueError:
        minimum_size_ratio = 0.05
    minimum_size_ratio = max(0.01, min(1.0, minimum_size_ratio))
    try:
        request_delay = max(
            0.0, float(os.getenv("PEER_COMPS_REQUEST_DELAY_SECONDS", "1.05") or 1.05)
        )
    except ValueError:
        request_delay = 1.05
    try:
        max_margin_gap = float(
            os.getenv("PEER_COMPS_MAX_OPERATING_MARGIN_GAP_PCT", "15") or 15
        )
    except ValueError:
        max_margin_gap = 15.0
    max_margin_gap = min(max(max_margin_gap, 5.0), 40.0)
    try:
        max_growth_gap = float(
            os.getenv("PEER_COMPS_MAX_REVENUE_GROWTH_GAP_PCT", "20") or 20
        )
    except ValueError:
        max_growth_gap = 20.0
    max_growth_gap = min(max(max_growth_gap, 5.0), 50.0)
    try:
        max_bank_roe_gap = float(
            os.getenv("PEER_COMPS_MAX_BANK_ROE_GAP_PCT", "10") or 10
        )
    except ValueError:
        max_bank_roe_gap = 10.0
    max_bank_roe_gap = min(max(max_bank_roe_gap, 3.0), 20.0)
    subject_margin_pct = (
        float(subject_operating_margin) * 100.0
        if isinstance(subject_operating_margin, (int, float))
        and not isinstance(subject_operating_margin, bool)
        and math.isfinite(float(subject_operating_margin)) else None
    )
    subject_growth_pct = (
        float(subject_revenue_growth) * 100.0
        if isinstance(subject_revenue_growth, (int, float))
        and not isinstance(subject_revenue_growth, bool)
        and math.isfinite(float(subject_revenue_growth)) else None
    )
    fundamental_screen_applied = bool(
        subject_margin_pct is not None or subject_growth_pct is not None
    )
    subject_roe_pct = (
        float(subject_return_on_equity) * 100.0
        if isinstance(subject_return_on_equity, (int, float))
        and not isinstance(subject_return_on_equity, bool)
        and math.isfinite(float(subject_return_on_equity)) else None
    )

    def normalized_symbols(universe: List[str]) -> List[str]:
        result = []
        for raw in universe:
            symbol = str(raw or "").strip().upper()
            if (
                symbol and symbol != ticker and symbol not in result
                and not _same_issuer_share_class(ticker, symbol)
            ):
                result.append(symbol)
            if len(result) >= limit:
                break
        return result

    def observe(symbols_to_fetch: List[str]):
        observations = []
        failed = []
        size_excluded = []
        fundamental_excluded = []
        # One worker already makes several vendor requests and multiple workers
        # can coexist. Avoid a per-worker burst that multiplies into 429s.
        for symbol in symbols_to_fetch:
            try:
                metric = client.metrics(symbol)
            except Exception:
                failed.append(symbol)
                if owns_client and request_delay:
                    time.sleep(request_delay)
                continue
            if owns_client and request_delay:
                time.sleep(request_delay)
            ev_ebitda = _first(metric, EV_EBITDA_KEYS)
            price_sales = _first(metric, PRICE_SALES_KEYS)
            market_cap_m = _first(metric, MARKET_CAP_KEYS)
            if subject_market_cap_m is not None:
                ratio = market_cap_m / subject_market_cap_m if market_cap_m else None
                if (ratio is None or ratio < minimum_size_ratio
                        or ratio > 1.0 / minimum_size_ratio):
                    size_excluded.append(symbol)
                    continue
            operating_margin_pct = _signed_first(metric, OPERATING_MARGIN_KEYS)
            revenue_growth_pct = _signed_first(metric, REVENUE_GROWTH_KEYS)
            fundamental_mismatch = False
            if subject_margin_pct is not None:
                fundamental_mismatch = (
                    operating_margin_pct is None
                    or abs(operating_margin_pct - subject_margin_pct) > max_margin_gap
                )
            if subject_growth_pct is not None:
                fundamental_mismatch = fundamental_mismatch or (
                    revenue_growth_pct is None
                    or abs(revenue_growth_pct - subject_growth_pct) > max_growth_gap
                )
            if fundamental_mismatch:
                fundamental_excluded.append(symbol)
                continue
            if ev_ebitda is not None and not 2.0 <= ev_ebitda <= 80.0:
                ev_ebitda = None
            if price_sales is not None and not 0.1 <= price_sales <= 50.0:
                price_sales = None
            if ev_ebitda is not None or price_sales is not None:
                observations.append({
                    "symbol": symbol,
                    "ev_ebitda_ttm": ev_ebitda,
                    "price_sales_ttm": price_sales,
                    "market_cap_usd_millions": market_cap_m,
                    "operating_margin_ttm_pct": operating_margin_pct,
                    "revenue_growth_ttm_yoy_pct": revenue_growth_pct,
                })
        observations.sort(key=lambda row: row["symbol"])
        return observations, failed, size_excluded, fundamental_excluded

    def values(rows: List[Dict[str, Any]], field: str) -> List[float]:
        return [row[field] for row in rows if row[field] is not None]

    subindustry_symbols = normalized_symbols(list(peers))
    if bank_method:
        observations = []
        failed_symbols = []
        size_excluded_symbols = []
        fundamental_excluded_symbols = []
        for symbol in subindustry_symbols:
            try:
                metric = client.metrics(symbol)
            except Exception:
                failed_symbols.append(symbol)
                if owns_client and request_delay:
                    time.sleep(request_delay)
                continue
            if owns_client and request_delay:
                time.sleep(request_delay)
            market_cap_m = _first(metric, MARKET_CAP_KEYS)
            if subject_market_cap_m is not None:
                ratio = market_cap_m / subject_market_cap_m if market_cap_m else None
                if (ratio is None or ratio < minimum_size_ratio
                        or ratio > 1.0 / minimum_size_ratio):
                    size_excluded_symbols.append(symbol)
                    continue
            peer_roe_pct = _signed_first(metric, RETURN_ON_EQUITY_KEYS)
            if (
                subject_roe_pct is None or peer_roe_pct is None
                or abs(peer_roe_pct - subject_roe_pct) > max_bank_roe_gap
            ):
                fundamental_excluded_symbols.append(symbol)
                continue
            price_to_book = _first(metric, PRICE_BOOK_KEYS)
            price_to_earnings = _first(metric, PRICE_EARNINGS_KEYS)
            if price_to_book is not None and not 0.2 <= price_to_book <= 8.0:
                price_to_book = None
            if price_to_earnings is not None and not 2.0 <= price_to_earnings <= 50.0:
                price_to_earnings = None
            if price_to_book is not None:
                observations.append({
                    "symbol": symbol,
                    "price_to_book": price_to_book,
                    "price_to_earnings": price_to_earnings,
                    "market_cap_usd_millions": market_cap_m,
                    "return_on_equity_ttm_pct": peer_roe_pct,
                })
        observations.sort(key=lambda row: row["symbol"])
        pb_values = values(observations, "price_to_book")
        pe_values = values(observations, "price_to_earnings")
        ready = len(pb_values) >= 3
        screened = bool(
            subject_market_cap_m is not None and subject_roe_pct is not None
        )
        base = {
            "source": "finnhub",
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "status": "ready" if ready else "insufficient_observations",
            "grouping": "subIndustry",
            "peer_universe_source": "finnhub_subindustry",
            "requested_peers": subindustry_symbols,
            "subindustry_requested_peers": subindustry_symbols,
            "observations": observations,
            "screening_stages": [{
                "grouping": "subIndustry",
                "peer_universe_source": "finnhub_subindustry",
                "requested_peers": list(subindustry_symbols),
                "observations": list(observations),
                "price_to_book_peer_count": len(pb_values),
                "price_to_earnings_peer_count": len(pe_values),
                "failed_symbols": list(failed_symbols),
                "size_excluded_symbols": list(size_excluded_symbols),
                "fundamental_excluded_symbols": list(
                    fundamental_excluded_symbols
                ),
            }],
            "median_price_to_book": round(statistics.median(pb_values), 4)
            if ready else None,
            "median_price_to_earnings": round(statistics.median(pe_values), 4)
            if len(pe_values) >= 3 else None,
            "price_to_book_peer_count": len(pb_values),
            "price_to_earnings_peer_count": len(pe_values),
            "selected_method": "price_to_book" if ready else None,
            "selected_peer_count": len(pb_values),
            "selected_peer_symbols": [row["symbol"] for row in observations],
            "confidence": (
                "high" if ready and screened and len(pb_values) >= 5
                else "moderate" if ready and screened else "low"
            ),
            "role": "bank_comparable_company_valuation",
            "included_in_blended_value": bool(ready and screened),
            "size_screen_applied": subject_market_cap_m is not None,
            "fundamental_screen_applied": subject_roe_pct is not None,
            "comparability_thresholds": {
                "max_return_on_equity_gap_pct": max_bank_roe_gap,
            },
            "failed_symbols": failed_symbols,
            "size_excluded_symbols": size_excluded_symbols,
            "fundamental_excluded_symbols": fundamental_excluded_symbols,
            "minimum_subject_size_ratio": minimum_size_ratio
            if subject_market_cap_m else None,
            "methodology": (
                "same-subindustry bounded P/B median; peers must pass USD size "
                f"and {max_bank_roe_gap:.0f}pp trailing-ROE screens. The bank "
                "valuation later normalizes each peer P/B by excess ROE."
            ),
        }
        if not ready:
            base["reason"] = (
                "At least three screened same-subindustry bank P/B observations "
                "are required."
            )
        return base

    symbols = subindustry_symbols
    (observations, failed_symbols, size_excluded_symbols,
     fundamental_excluded_symbols) = observe(symbols)
    ev_values = values(observations, "ev_ebitda_ttm")
    ps_values = values(observations, "price_sales_ttm")
    screening_stages = [{
        "grouping": "subIndustry",
        "peer_universe_source": "finnhub_subindustry",
        "requested_peers": list(symbols),
        "observations": list(observations),
        "ev_ebitda_peer_count": len(ev_values),
        "price_sales_peer_count": len(ps_values),
        "failed_symbols": list(failed_symbols),
        "size_excluded_symbols": list(size_excluded_symbols),
        "fundamental_excluded_symbols": list(fundamental_excluded_symbols),
    }]

    # Only after the same-subindustry set fails coverage do we request the
    # intentionally broader sector universe. Previously every mega-cap jumped
    # straight to this branch, even when qualified close peers existed.
    leaders: List[str] = []
    if len(ev_values) < 3 and len(ps_values) < 3 and use_sector_fallback:
        leaders = list(fallback_symbols) if fallback_symbols is not None else (
            _yahoo_sector_leaders(sector)
        )
        symbols = normalized_symbols(leaders)
        (observations, failed_symbols, size_excluded_symbols,
         fundamental_excluded_symbols) = observe(symbols)
        ev_values = values(observations, "ev_ebitda_ttm")
        ps_values = values(observations, "price_sales_ttm")
        screening_stages.append({
            "grouping": "sector_leaders",
            "peer_universe_source": "yahoo_sector_leaders",
            "requested_peers": list(symbols),
            "observations": list(observations),
            "ev_ebitda_peer_count": len(ev_values),
            "price_sales_peer_count": len(ps_values),
            "failed_symbols": list(failed_symbols),
            "size_excluded_symbols": list(size_excluded_symbols),
            "fundamental_excluded_symbols": list(fundamental_excluded_symbols),
        })
    if len(ev_values) < 3 and len(ps_values) < 3:
        broad_sector = bool(leaders)
        return {
            "source": "finnhub",
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "status": "insufficient_observations",
            "reason": (
                "At least three screened EV/EBITDA or price/sales observations "
                "are required; excluded and failed symbols are listed separately."
            ),
            "grouping": "sector_leaders" if broad_sector else "subIndustry",
            "peer_universe_source": (
                "yahoo_sector_leaders" if broad_sector else "finnhub_subindustry"
            ),
            "requested_peers": symbols,
            "observations": observations,
            "ev_ebitda_peer_count": len(ev_values),
            "price_sales_peer_count": len(ps_values),
            "failed_symbols": failed_symbols,
            "size_excluded_symbols": size_excluded_symbols,
            "fundamental_excluded_symbols": fundamental_excluded_symbols,
            "minimum_subject_size_ratio": minimum_size_ratio if subject_market_cap_m else None,
            "size_screen_applied": subject_market_cap_m is not None,
            "fundamental_screen_applied": fundamental_screen_applied,
            "comparability_thresholds": {
                "max_operating_margin_gap_pct": max_margin_gap,
                "max_revenue_growth_gap_pct": max_growth_gap,
            },
            "selected_method": None,
            "selected_peer_count": 0,
            "selected_peer_symbols": [],
            "confidence": "unavailable",
            "role": "insufficient_comparable_observations",
            "methodology": (
                ("broad-sector mega-cap median" if broad_sector else
                 "same-subindustry median")
                + " of bounded trailing multiples after size, operating-margin "
                  "and revenue-growth comparability screens"
            ),
            "included_in_blended_value": False,
            "subindustry_requested_peers": subindustry_symbols,
            "screening_stages": screening_stages,
        }
    selected_method = "ev_ebitda" if len(ev_values) >= 3 else "price_sales"
    selected_symbols = [
        row["symbol"] for row in observations
        if row["ev_ebitda_ttm" if selected_method == "ev_ebitda" else "price_sales_ttm"]
        is not None
    ]
    broad_sector = bool(leaders)
    size_screen_applied = subject_market_cap_m is not None
    comparability_screen_applied = size_screen_applied and fundamental_screen_applied
    confidence = (
        "low" if broad_sector or not comparability_screen_applied else
        "high" if len(selected_symbols) >= 5 else
        "moderate"
    )
    return {
        "source": "finnhub",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "status": "ready",
        "grouping": "sector_leaders" if leaders else "subIndustry",
        "peer_universe_source": (
            "yahoo_sector_leaders" if leaders else "finnhub_subindustry"
        ),
        "requested_peers": symbols,
        "subindustry_requested_peers": subindustry_symbols,
        "screening_stages": screening_stages,
        "observations": observations,
        "median_ev_ebitda": round(statistics.median(ev_values), 4)
        if len(ev_values) >= 3 else None,
        "median_price_sales": round(statistics.median(ps_values), 4)
        if len(ps_values) >= 3 else None,
        "ev_ebitda_peer_count": len(ev_values),
        "price_sales_peer_count": len(ps_values),
        "selected_method": selected_method,
        "selected_peer_count": len(selected_symbols),
        "selected_peer_symbols": selected_symbols,
        "confidence": confidence,
        "role": (
            "broad_sector_cross_check" if broad_sector
            else "unverified_peer_cross_check" if not comparability_screen_applied
            else "comparable_company_valuation"
        ),
        # Broad sector leaders are useful context, but not close-enough
        # comparables to receive an equal vote in intrinsic value.
        "included_in_blended_value": not broad_sector and comparability_screen_applied,
        "size_screen_applied": size_screen_applied,
        "fundamental_screen_applied": fundamental_screen_applied,
        "comparability_thresholds": {
            "max_operating_margin_gap_pct": max_margin_gap,
            "max_revenue_growth_gap_pct": max_growth_gap,
        },
        "failed_symbols": failed_symbols,
        "size_excluded_symbols": size_excluded_symbols,
        "fundamental_excluded_symbols": fundamental_excluded_symbols,
        "minimum_subject_size_ratio": minimum_size_ratio if subject_market_cap_m else None,
        "methodology": (
            ("broad-sector mega-cap median" if leaders else "same-subindustry median")
            + " of bounded trailing multiples; peers must be "
            f"within {minimum_size_ratio:.0%}x-{1/minimum_size_ratio:.0f}x of subject market cap, "
            f"within {max_margin_gap:.0f}pp operating margin and {max_growth_gap:.0f}pp revenue growth"
            if subject_market_cap_m else
            "same-subindustry median of bounded trailing multiples"
        ),
    }
