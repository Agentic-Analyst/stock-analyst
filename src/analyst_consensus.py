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
from copy import deepcopy
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


def _source_name(payload: Dict[str, Any]) -> Optional[str]:
    """Resolve the provider attached to one normalized provider response."""
    target = payload.get("price_target") or {}
    recommendation = payload.get("recommendation") or {}
    providers = payload.get("providers") or []
    source = target.get("source") or recommendation.get("source")
    if not source and len(providers) == 1:
        source = providers[0]
    return str(source) if source else None


def _snapshot(payload: Dict[str, Any]) -> tuple[Optional[str], Dict[str, Any]]:
    """Copy only source-owned evidence; never recursively copy comparisons."""
    source = _source_name(payload)
    if not source:
        return None, {}
    record = {
        "captured_at": payload.get("captured_at"),
        "price_target": deepcopy(payload.get("price_target") or {}),
        "recommendation": deepcopy(payload.get("recommendation") or {}),
    }
    if payload.get("partial_errors"):
        record["partial_errors"] = list(payload["partial_errors"])
    return source, record


def _rating_direction(label: Any) -> Optional[str]:
    normalized = str(label or "").strip().lower().replace("-", "_").replace(" ", "_")
    if normalized in {"strong_buy", "buy", "outperform", "overweight"}:
        return "bullish"
    if normalized in {"hold", "neutral", "market_perform", "equal_weight"}:
        return "neutral"
    if normalized in {"strong_sell", "sell", "underperform", "underweight"}:
        return "bearish"
    return None


def _compare_source_snapshots(snapshots: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Return objective cross-source metadata without manufacturing a consensus.

    Provider means remain separate.  We report their max/min spread only when
    every included target has the same known currency; no target is averaged
    and none of this metadata enters intrinsic value.
    """
    means: Dict[str, float] = {}
    currencies: Dict[str, str] = {}
    labels: Dict[str, str] = {}
    directions: Dict[str, str] = {}
    for source, snapshot in snapshots.items():
        target = snapshot.get("price_target") or {}
        mean = _positive(target.get("mean"))
        if mean is not None:
            means[source] = mean
            currency = str(target.get("currency") or "").strip().upper()
            if currency:
                currencies[source] = currency

        recommendation = snapshot.get("recommendation") or {}
        label = recommendation.get("label")
        if label:
            labels[source] = str(label)
            direction = _rating_direction(label)
            if direction:
                directions[source] = direction

    comparable = (
        len(means) >= 2
        and len(currencies) == len(means)
        and len(set(currencies.values())) == 1
    )
    price_comparison: Dict[str, Any] = {
        "source_count": len(means),
        "mean_by_source": means,
        "currency_by_source": currencies,
        "comparable": comparable,
    }
    if comparable:
        low, high = min(means.values()), max(means.values())
        midpoint = (low + high) / 2.0
        price_comparison.update({
            "mean_target_low": low,
            "mean_target_high": high,
            "mean_target_spread_pct": round((high - low) / midpoint * 100.0, 2),
        })

    recommendation_comparison: Dict[str, Any] = {
        "source_count": len(labels),
        "label_by_source": labels,
        "direction_by_source": directions,
    }
    if len(labels) >= 2:
        recommendation_comparison["exact_agreement"] = len(set(labels.values())) == 1
    if len(directions) >= 2:
        recommendation_comparison["directional_agreement"] = len(set(directions.values())) == 1

    return {
        "price_target": price_comparison,
        "recommendation": recommendation_comparison,
    }


def refresh_source_comparison(consensus: Dict[str, Any]) -> Dict[str, Any]:
    """Recompute comparison metadata after currency normalization."""
    snapshots = consensus.get("source_snapshots") or {}
    if isinstance(snapshots, dict) and snapshots:
        consensus["source_comparison"] = _compare_source_snapshots(snapshots)
    return consensus


def _with_source_evidence(out: Dict[str, Any], *payloads: Dict[str, Any]) -> Dict[str, Any]:
    if not out:
        return {}
    result = deepcopy(out)
    snapshots: Dict[str, Dict[str, Any]] = {}
    for payload in payloads:
        if not payload:
            continue
        source, record = _snapshot(payload)
        if source:
            snapshots[source] = record
    if snapshots:
        result["source_snapshots"] = snapshots
        result["source_comparison"] = _compare_source_snapshots(snapshots)
    return result


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
        return _with_source_evidence(fallback, fallback)
    if not fallback:
        return _with_source_evidence(primary, primary)
    out = deepcopy(primary)
    out["providers"] = list(dict.fromkeys(
        list(primary.get("providers") or []) + list(fallback.get("providers") or [])))
    for section in ("price_target", "recommendation"):
        if not out.get(section):
            out[section] = deepcopy(fallback.get(section) or {})
    return _with_source_evidence(out, primary, fallback)


def collect_consensus(ticker: str, yahoo_guidance: Optional[Dict[str, Any]], *,
                      currency: Optional[str] = None,
                      quote_currency: Optional[str] = None,
                      client: Optional[FinnhubConsensusClient] = None) -> Dict[str, Any]:
    """Collect configured consensus, falling back section-by-section to Yahoo."""
    provider = (os.getenv("ANALYST_CONSENSUS_PROVIDER", "auto") or "auto").strip().lower()
    if provider == "none":
        return {}
    fallback = yahoo_snapshot(yahoo_guidance, currency=currency)
    if provider not in ("auto", "finnhub"):
        return _merge({}, fallback)
    if client is None:
        key = (os.getenv("FINNHUB_API_KEY") or "").strip()
        if not key:
            return _merge({}, fallback)
        client = FinnhubConsensusClient(key)
    return _merge(
        client.fetch(ticker, currency=quote_currency or currency),
        fallback,
    )
