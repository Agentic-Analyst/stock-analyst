"""Point-in-time analyst consensus from explicitly configured data providers.

Broker research is licensed data, not ordinary public web content.  This
module deliberately uses provider APIs and never logs credentials or scrapes
authenticated IBKR/Robinhood/Moomoo pages.  Yahoo fields already collected by
the financial scraper remain a fallback; a Finnhub key enables the first
licensed adapter without making the valuation pipeline depend on it.

Consensus is evidence and a calibration benchmark.  It is not intrinsic value
and is never silently averaged into the DCF/comps headline.
"""
from __future__ import annotations

import math
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import requests

FINNHUB_BASE_URL = "https://finnhub.io/api/v1"


def _positive(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) and number > 0 else None


def _count(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return max(number, 0)


def _recommendation(counts: Dict[str, Any], *, period: Optional[str],
                    source: str) -> Dict[str, Any]:
    normalized = {
        "strong_buy": _count(counts.get("strongBuy", counts.get("strong_buy"))),
        "buy": _count(counts.get("buy")),
        "hold": _count(counts.get("hold")),
        "sell": _count(counts.get("sell")),
        "strong_sell": _count(counts.get("strongSell", counts.get("strong_sell"))),
    }
    total = sum(normalized.values())
    if not total:
        return {}
    score = (
        2 * normalized["strong_buy"] + normalized["buy"]
        - normalized["sell"] - 2 * normalized["strong_sell"]
    ) / total
    if score >= 0.75:
        label = "strong_buy"
    elif score >= 0.20:
        label = "buy"
    elif score > -0.20:
        label = "hold"
    elif score > -0.75:
        label = "sell"
    else:
        label = "strong_sell"
    return {
        **normalized,
        "total": total,
        "bullish_share": round(
            (normalized["strong_buy"] + normalized["buy"]) / total, 4),
        "bearish_share": round(
            (normalized["sell"] + normalized["strong_sell"]) / total, 4),
        "score": round(score, 4),
        "label": label,
        "period": period,
        "source": source,
    }


def yahoo_snapshot(guidance: Optional[Dict[str, Any]], *,
                   currency: Optional[str] = None) -> Dict[str, Any]:
    """Normalize the aggregate Yahoo fields the scraper already receives."""
    guidance = guidance or {}
    mean = _positive(guidance.get("target_mean_price"))
    median = _positive(guidance.get("target_median_price"))
    high = _positive(guidance.get("target_high_price"))
    low = _positive(guidance.get("target_low_price"))
    count = _count(guidance.get("number_of_analyst_opinions"))
    if not any((mean, median, high, low, count)):
        return {}
    return {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "providers": ["yahoo_finance"],
        "price_target": {
            "mean": mean,
            "median": median,
            "high": high,
            "low": low,
            "analyst_count": count,
            "currency": currency,
            "as_of": None,
            "source": "yahoo_finance",
        },
        "recommendation": {
            "label": guidance.get("recommendation_key"),
            "mean": guidance.get("recommendation_mean"),
            "analyst_count": count,
            "period": None,
            "source": "yahoo_finance",
        },
    }


class FinnhubConsensusClient:
    """Small HTTP adapter; injectable session keeps network out of unit tests."""

    def __init__(self, api_key: str, *, session=requests, timeout: float = 10.0):
        self.api_key = (api_key or "").strip()
        self.session = session
        self.timeout = timeout

    def _get(self, path: str, ticker: str) -> Any:
        response = self.session.get(
            f"{FINNHUB_BASE_URL}{path}",
            params={"symbol": ticker},
            headers={"X-Finnhub-Token": self.api_key},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def fetch(self, ticker: str, *, currency: Optional[str] = None) -> Dict[str, Any]:
        ticker = (ticker or "").strip().upper()
        if not ticker or not self.api_key:
            return {}

        target, trends, errors = {}, [], []
        try:
            value = self._get("/stock/price-target", ticker)
            target = value if isinstance(value, dict) else {}
        except Exception as error:
            # Price targets are plan-dependent. Recommendation trends can still
            # be useful, so one denied endpoint must not discard the other.
            errors.append(f"price_target:{type(error).__name__}")
        try:
            value = self._get("/stock/recommendation", ticker)
            trends = value if isinstance(value, list) else []
        except Exception as error:
            errors.append(f"recommendation:{type(error).__name__}")

        price_target = {
            "mean": _positive(target.get("targetMean")),
            "median": _positive(target.get("targetMedian")),
            "high": _positive(target.get("targetHigh")),
            "low": _positive(target.get("targetLow")),
            "analyst_count": _count(target.get("numberAnalysts")),
            "currency": currency,
            "as_of": target.get("lastUpdated"),
            "source": "finnhub",
        }
        if not any(price_target.get(k) for k in ("mean", "median", "high", "low", "analyst_count")):
            price_target = {}

        latest = max(
            (row for row in trends if isinstance(row, dict)),
            key=lambda row: str(row.get("period") or ""),
            default={},
        )
        recommendation = _recommendation(
            latest, period=latest.get("period"), source="finnhub") if latest else {}

        if not price_target and not recommendation:
            return {}
        out = {
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "providers": ["finnhub"],
            "price_target": price_target,
            "recommendation": recommendation,
        }
        if errors:
            out["partial_errors"] = errors
        return out


def _merge(primary: Dict[str, Any], fallback: Dict[str, Any]) -> Dict[str, Any]:
    if not primary:
        return fallback
    if not fallback:
        return primary
    out = dict(primary)
    out["providers"] = list(dict.fromkeys(
        list(primary.get("providers") or []) + list(fallback.get("providers") or [])))
    for section in ("price_target", "recommendation"):
        if not out.get(section):
            out[section] = fallback.get(section) or {}
    return out


def collect_consensus(ticker: str, yahoo_guidance: Optional[Dict[str, Any]], *,
                      currency: Optional[str] = None,
                      client: Optional[FinnhubConsensusClient] = None) -> Dict[str, Any]:
    """Collect configured consensus, falling back section-by-section to Yahoo."""
    provider = (os.getenv("ANALYST_CONSENSUS_PROVIDER", "auto") or "auto").strip().lower()
    if provider == "none":
        return {}
    fallback = yahoo_snapshot(yahoo_guidance, currency=currency)
    if provider not in ("auto", "finnhub"):
        return fallback
    if client is None:
        key = (os.getenv("FINNHUB_API_KEY") or "").strip()
        if not key:
            return fallback
        client = FinnhubConsensusClient(key)
    return _merge(client.fetch(ticker, currency=currency), fallback)

