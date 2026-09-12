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


def _mode() -> str:
    raw = (os.getenv("PEER_COMPS_ENABLED") or "auto").strip().lower()
    if raw in ("0", "false", "no", "off", "disabled"):
        return "disabled"
    if raw in ("1", "true", "yes", "on", "enabled"):
        return "enabled"
    return "auto"


def enabled() -> bool:
    """Enable automatically when provider credentials are present."""
    mode = _mode()
    if mode == "disabled":
        return False
    return bool((os.getenv("FINNHUB_API_KEY") or "").strip())


def configuration_status() -> Dict[str, Any]:
    """Non-secret feature status suitable for logs and health diagnostics."""
    has_key = bool((os.getenv("FINNHUB_API_KEY") or "").strip())
    mode = _mode()
    is_enabled = enabled()
    blockers = []
    if mode == "disabled":
        blockers.append("PEER_COMPS_ENABLED explicitly disables peer comps")
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
                       fallback_symbols: Optional[List[str]] = None) -> Dict[str, Any]:
    """Median trading multiples for same-subindustry peers; empty if unavailable."""
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
    except Exception:
        return {}

    try:
        configured = int(max_peers if max_peers is not None
                         else (os.getenv("PEER_COMPS_MAX_PEERS") or 6))
    except (TypeError, ValueError):
        configured = 6
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
    leaders = (
        list(fallback_symbols) if fallback_symbols is not None
        else (_yahoo_sector_leaders(sector) if use_sector_fallback else [])
    )
    universe = leaders + list(peers) if leaders else list(peers)
    symbols = []
    for raw in universe:
        symbol = str(raw or "").strip().upper()
        if symbol and symbol != ticker and symbol not in symbols:
            symbols.append(symbol)
        if len(symbols) >= limit:
            break

    observations = []
    failed_symbols = []
    size_excluded_symbols = []
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
    # One worker already makes several vendor requests and multiple workers can
    # coexist. Avoid a per-worker burst that multiplies into account-wide 429s.
    for symbol in symbols:
        try:
            metric = client.metrics(symbol)
        except Exception:
            failed_symbols.append(symbol)
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
            if ratio is None or ratio < minimum_size_ratio or ratio > 1.0 / minimum_size_ratio:
                size_excluded_symbols.append(symbol)
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
            })
    observations.sort(key=lambda row: row["symbol"])
    ev_values = [row["ev_ebitda_ttm"] for row in observations
                 if row["ev_ebitda_ttm"] is not None]
    ps_values = [row["price_sales_ttm"] for row in observations
                 if row["price_sales_ttm"] is not None]
    if len(ev_values) < 3 and len(ps_values) < 3:
        return {}
    return {
        "source": "finnhub",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "grouping": "sector_leaders" if leaders else "subIndustry",
        "peer_universe_source": (
            "yahoo_sector_leaders" if leaders else "finnhub_subindustry"
        ),
        "requested_peers": symbols,
        "observations": observations,
        "median_ev_ebitda": round(statistics.median(ev_values), 4)
        if len(ev_values) >= 3 else None,
        "median_price_sales": round(statistics.median(ps_values), 4)
        if len(ps_values) >= 3 else None,
        "ev_ebitda_peer_count": len(ev_values),
        "price_sales_peer_count": len(ps_values),
        "failed_symbols": failed_symbols,
        "size_excluded_symbols": size_excluded_symbols,
        "minimum_subject_size_ratio": minimum_size_ratio if subject_market_cap_m else None,
        "methodology": (
            ("broad-sector mega-cap median" if leaders else "same-subindustry median")
            + " of bounded trailing multiples; peers must be "
            f"within {minimum_size_ratio:.0%}x-{1/minimum_size_ratio:.0f}x of subject market cap"
            if subject_market_cap_m else
            "same-subindustry median of bounded trailing multiples"
        ),
    }
