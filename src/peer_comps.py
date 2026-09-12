"""Comparable-company multiples from an explicitly configured provider."""
from __future__ import annotations

import math
import os
import statistics
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

FINNHUB_BASE_URL = "https://finnhub.io/api/v1"
MAX_PEERS = 10

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


def enabled() -> bool:
    return (os.getenv("PEER_COMPS_ENABLED", "false") or "").strip().lower() in (
        "1", "true", "yes")


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


def collect_peer_comps(ticker: str, *, client: Optional[FinnhubPeerClient] = None,
                       max_peers: Optional[int] = None) -> Dict[str, Any]:
    """Median trading multiples for same-subindustry peers; empty if unavailable."""
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
    symbols = []
    for raw in peers:
        symbol = str(raw or "").strip().upper()
        if symbol and symbol != ticker and symbol not in symbols:
            symbols.append(symbol)
        if len(symbols) >= limit:
            break

    observations = []
    failed_symbols = []
    # One worker already makes several vendor requests and multiple workers can
    # coexist. Avoid a per-worker burst that multiplies into account-wide 429s.
    for symbol in symbols:
        try:
            metric = client.metrics(symbol)
        except Exception:
            failed_symbols.append(symbol)
            continue
        ev_ebitda = _first(metric, EV_EBITDA_KEYS)
        price_sales = _first(metric, PRICE_SALES_KEYS)
        if ev_ebitda is not None and not 2.0 <= ev_ebitda <= 80.0:
            ev_ebitda = None
        if price_sales is not None and not 0.1 <= price_sales <= 50.0:
            price_sales = None
        if ev_ebitda is not None or price_sales is not None:
            observations.append({
                "symbol": symbol,
                "ev_ebitda_ttm": ev_ebitda,
                "price_sales_ttm": price_sales,
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
        "grouping": "subIndustry",
        "requested_peers": symbols,
        "observations": observations,
        "median_ev_ebitda": round(statistics.median(ev_values), 4)
        if len(ev_values) >= 3 else None,
        "median_price_sales": round(statistics.median(ps_values), 4)
        if len(ps_values) >= 3 else None,
        "ev_ebitda_peer_count": len(ev_values),
        "price_sales_peer_count": len(ps_values),
        "failed_symbols": failed_symbols,
        "methodology": "same-subindustry median of bounded trailing multiples",
    }
