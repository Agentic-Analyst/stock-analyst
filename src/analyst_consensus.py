"""Point-in-time analyst consensus from explicitly configured data providers.

Broker research is licensed data, not ordinary public web content. This
module deliberately uses provider APIs and never logs credentials or scrapes
authenticated IBKR/Robinhood/Moomoo pages. Yahoo fields already collected by
the financial scraper remain a fallback. Benzinga is preferred when configured,
Finnhub remains a licensed fallback, and TipRanks is an explicitly enabled,
quota-bounded secondary snapshot.

Consensus is evidence and a calibration benchmark.  It is not intrinsic value
and is never silently averaged into the DCF/comps headline.
"""
from __future__ import annotations

import json
import math
import os
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any, Dict, Optional

import requests

FINNHUB_BASE_URL = "https://finnhub.io/api/v1"
BENZINGA_CONSENSUS_URL = "https://api.benzinga.com/api/v1/consensus-ratings"
TIPRANKS_MCP_URL = "https://mcp.tipranks.com/mcp/"
TIPRANKS_PROTOCOL_VERSION = "2025-03-26"

# A stock-analyst worker is normally one analysis process. Keep the optional
# TipRanks cross-check one-wide inside that process as a second guard behind
# the provider's account-level monthly quota. Scheduled workers never receive
# the credential (api-runner enforces that boundary).
_tipranks_budget_lock = Lock()
_tipranks_calls = 0


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


def _normalized_label(label: Any) -> Optional[str]:
    value = str(label or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "strongbuy": "strong_buy",
        "strong_buy": "strong_buy",
        "top_pick": "strong_buy",
        "buy": "buy",
        "moderate_buy": "buy",
        "outperform": "buy",
        "overweight": "buy",
        "hold": "hold",
        "neutral": "hold",
        "market_perform": "hold",
        "equal_weight": "hold",
        "sell": "sell",
        "moderate_sell": "sell",
        "underperform": "sell",
        "underweight": "sell",
        "strongsell": "strong_sell",
        "strong_sell": "strong_sell",
    }
    return aliases.get(value)


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


class BenzingaConsensusClient:
    """Aggregate analyst ratings from Benzinga's licensed REST endpoint."""

    def __init__(self, api_key: str, *, session=requests, timeout: float = 10.0,
                 clock=None):
        self.api_key = (api_key or "").strip()
        self.session = session
        self.timeout = timeout
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def fetch(self, ticker: str, *, currency: Optional[str] = None) -> Dict[str, Any]:
        ticker = (ticker or "").strip().upper()
        if not ticker or not self.api_key:
            return {}
        now = self.clock()
        try:
            lookback_days = int(os.getenv("BENZINGA_CONSENSUS_LOOKBACK_DAYS", "365") or "365")
        except ValueError:
            lookback_days = 365
        lookback_days = min(max(lookback_days, 30), 730)
        date_to = now.date().isoformat()
        date_from = (now - timedelta(days=lookback_days)).date().isoformat()
        try:
            response = self.session.get(
                BENZINGA_CONSENSUS_URL,
                params={
                    "token": self.api_key,
                    "parameters[tickers]": ticker,
                    "aggregate_type": "number",
                    "simplify": "false",
                    "pagesize": 1,
                    "parameters[date_from]": date_from,
                    "parameters[date_to]": date_to,
                },
                headers={"accept": "application/json"},
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception:
            # Never include an exception string here: requests may echo the
            # credential-bearing query URL in it.
            return {}

        if isinstance(payload, list):
            payload = payload[0] if payload else {}
        if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
            payload = payload["data"]
        if not isinstance(payload, dict):
            return {}

        analyst_count = _count(
            payload.get("unique_analyst_count") or payload.get("total_analyst_count"))
        price_target = {
            "mean": _positive(payload.get("consensus_price_target")),
            "median": None,
            "high": _positive(payload.get("high_price_target")),
            "low": _positive(payload.get("low_price_target")),
            "analyst_count": analyst_count,
            "currency": currency,
            "as_of": payload.get("updated_at"),
            "source": "benzinga",
        }
        if not any(price_target.get(key) for key in ("mean", "high", "low", "analyst_count")):
            price_target = {}

        distribution = payload.get("aggregate_ratings")
        recommendation = _recommendation(
            distribution if isinstance(distribution, dict) else {},
            period=payload.get("updated_at"), source="benzinga",
        )
        provider_label = _normalized_label(payload.get("consensus_rating"))
        if recommendation and provider_label:
            recommendation["label"] = provider_label
        elif provider_label:
            recommendation = {
                "label": provider_label,
                "analyst_count": analyst_count,
                "period": payload.get("updated_at"),
                "source": "benzinga",
            }
        if recommendation:
            recommendation["provider_score"] = _positive(payload.get("consensus_rating_val"))
            recommendation["unique_analyst_count"] = analyst_count
            recommendation["total_rating_count"] = _count(payload.get("total_analyst_count"))

        if not price_target and not recommendation:
            return {}
        return {
            "captured_at": now.isoformat(),
            "providers": ["benzinga"],
            "window": {"date_from": date_from, "date_to": date_to,
                       "lookback_days": lookback_days},
            "price_target": price_target,
            "recommendation": recommendation,
        }


def _tipranks_call_allowed() -> bool:
    try:
        configured = int(os.getenv("TIPRANKS_MAX_CALLS_PER_WORKER", "1") or "1")
    except ValueError:
        configured = 1
    limit = min(max(configured, 0), 5)
    global _tipranks_calls
    with _tipranks_budget_lock:
        if _tipranks_calls >= limit:
            return False
        _tipranks_calls += 1
        return True


def _mcp_payload(response: Any) -> Dict[str, Any]:
    text = str(getattr(response, "text", "") or "")
    headers = getattr(response, "headers", {}) or {}
    candidates = [text]
    if "text/event-stream" in str(headers.get("content-type", "")):
        candidates = [line[6:] for line in text.splitlines() if line.startswith("data: ")]
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except (TypeError, ValueError):
            continue
        if isinstance(value, dict):
            return value
    return {}


class TipRanksConsensusClient:
    """Quota-bounded MCP adapter used only when explicitly enabled."""

    def __init__(self, api_key: str, *, session=requests, timeout: float = 15.0):
        self.api_key = (api_key or "").strip()
        self.session = session
        self.timeout = timeout

    def _post(self, payload: Dict[str, Any],
              session_id: Optional[str] = None) -> tuple[Any, Dict[str, Any]]:
        headers = {
            "accept": "application/json, text/event-stream",
            "content-type": "application/json",
        }
        if session_id:
            headers["Mcp-Session-Id"] = session_id
        response = self.session.post(
            TIPRANKS_MCP_URL,
            params={"apikey": self.api_key},
            headers=headers,
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response, _mcp_payload(response)

    def fetch(self, ticker: str, *, currency: Optional[str] = None) -> Dict[str, Any]:
        ticker = (ticker or "").strip().upper()
        if not ticker or not self.api_key or not _tipranks_call_allowed():
            return {}
        try:
            response, initialized = self._post({
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": TIPRANKS_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "vynn-stock-analyst", "version": "1"},
                },
            })
            if not isinstance(initialized.get("result"), dict):
                return {}
            session_id = (getattr(response, "headers", {}) or {}).get("Mcp-Session-Id")
            self._post({
                "jsonrpc": "2.0", "method": "notifications/initialized",
            }, session_id)
            _, message = self._post({
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "get_assets_data",
                    "arguments": {"tickers": [ticker]},
                },
            }, session_id)
        except Exception:
            # The key is a query parameter, so exception text is secret-bearing.
            return {}

        result = message.get("result") if isinstance(message, dict) else None
        if not isinstance(result, dict) or result.get("isError"):
            return {}
        data: Dict[str, Any] = {}
        structured = result.get("structuredContent")
        if isinstance(structured, dict):
            data = structured
        if not data:
            for item in result.get("content") or []:
                if not isinstance(item, dict) or item.get("type") != "text":
                    continue
                try:
                    decoded = json.loads(item.get("text") or "{}")
                except (TypeError, ValueError):
                    continue
                if isinstance(decoded, dict):
                    data = decoded
                    break
        rows = data.get("assetsData") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            return {}
        row = next((entry for entry in rows if isinstance(entry, dict)
                    and str(entry.get("ticker") or "").upper() == ticker), None)
        if not row:
            return {}

        target = _positive(row.get("priceTarget"))
        label = _normalized_label(row.get("analystConsensus"))
        source_url = row.get("url")
        price_target = ({
            "mean": target,
            "median": None,
            "high": None,
            "low": None,
            "analyst_count": 0,
            "currency": currency,
            "as_of": None,
            "source": "tipranks",
            "source_url": source_url,
        } if target is not None else {})
        recommendation = ({
            "label": label,
            "analyst_count": 0,
            "period": None,
            "source": "tipranks",
            "source_url": source_url,
        } if label else {})
        if not price_target and not recommendation:
            return {}
        return {
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "providers": ["tipranks"],
            "price_target": price_target,
            "recommendation": recommendation,
        }


def _merge_many(*payloads: Dict[str, Any],
                evidence_only: tuple[Dict[str, Any], ...] = ()) -> Dict[str, Any]:
    usable = [payload for payload in payloads if payload]
    evidence = [payload for payload in evidence_only if payload]
    if not usable and evidence:
        # If no normal source exists, an explicitly requested low-coverage
        # snapshot is still better than manufacturing a value.
        usable = [evidence.pop(0)]
    if not usable:
        return {}
    out = deepcopy(usable[0])
    all_payloads = usable + evidence
    out["providers"] = list(dict.fromkeys(
        provider
        for payload in all_payloads
        for provider in list(payload.get("providers") or [])
    ))
    for payload in usable[1:]:
        for section in ("price_target", "recommendation"):
            if not out.get(section):
                out[section] = deepcopy(payload.get(section) or {})
    return _with_source_evidence(out, *all_payloads)


def _merge(primary: Dict[str, Any], fallback: Dict[str, Any]) -> Dict[str, Any]:
    return _merge_many(primary, fallback)


def _coverage_count(payload: Dict[str, Any]) -> int:
    target = payload.get("price_target") or {}
    recommendation = payload.get("recommendation") or {}
    return max(
        _count(target.get("analyst_count")),
        _count(recommendation.get("unique_analyst_count")),
        _count(recommendation.get("analyst_count")),
        _count(recommendation.get("total")),
    )


def _minimum_analysts() -> int:
    try:
        configured = int(os.getenv("ANALYST_CONSENSUS_MIN_ANALYSTS", "3") or "3")
    except ValueError:
        configured = 3
    return min(max(configured, 1), 20)


def collect_consensus(ticker: str, yahoo_guidance: Optional[Dict[str, Any]], *,
                      currency: Optional[str] = None,
                      quote_currency: Optional[str] = None,
                      client: Optional[FinnhubConsensusClient] = None,
                      benzinga_client: Optional[BenzingaConsensusClient] = None,
                      tipranks_client: Optional[TipRanksConsensusClient] = None) -> Dict[str, Any]:
    """Collect licensed consensus with explicit, non-blended provenance."""
    provider = (os.getenv("ANALYST_CONSENSUS_PROVIDER", "auto") or "auto").strip().lower()
    tipranks_contract = (
        os.getenv("TIPRANKS_DURABLE_OUTPUTS_LICENSED", "false") or ""
    ).strip().lower() in ("1", "true", "yes")
    if provider == "tipranks" and not tipranks_contract:
        # Ordinary MCP terms allow transient operational caching, while this
        # pipeline persists inputs and reports. Require an explicit amended
        # license before TipRanks data can enter durable artifacts.
        provider = "auto"
    if provider == "none":
        return {}
    fallback = yahoo_snapshot(yahoo_guidance, currency=currency)
    if provider not in ("auto", "benzinga", "finnhub", "tipranks"):
        return _merge({}, fallback)

    listing_currency = quote_currency or currency
    primary: Dict[str, Any] = {}
    supporting: list[Dict[str, Any]] = []
    evidence_only: list[Dict[str, Any]] = []

    if provider in ("auto", "benzinga"):
        if benzinga_client is None:
            key = (os.getenv("BENZINGA_API_KEY") or "").strip()
            benzinga_client = BenzingaConsensusClient(key) if key else None
        if benzinga_client is not None:
            primary = benzinga_client.fetch(ticker, currency=listing_currency)
            if primary and _coverage_count(primary) < _minimum_analysts():
                evidence_only.append(primary)
                primary = {}

    # Finnhub remains the automatic licensed fallback when Benzinga is absent,
    # unavailable, or returns only one of the two normalized sections.
    needs_finnhub = provider == "finnhub" or (
        provider == "auto" and (not primary or not primary.get("price_target")
                                or not primary.get("recommendation")))
    if needs_finnhub:
        if client is None:
            key = (os.getenv("FINNHUB_API_KEY") or "").strip()
            client = FinnhubConsensusClient(key) if key else None
        if client is not None:
            finnhub = client.fetch(ticker, currency=listing_currency)
            if not primary:
                primary = finnhub
            elif finnhub:
                supporting.append(finnhub)

    if provider == "tipranks":
        if tipranks_client is None:
            key = (os.getenv("TIPRANKS_API_KEY") or "").strip()
            tipranks_client = TipRanksConsensusClient(key) if key else None
        tipranks = (tipranks_client.fetch(ticker, currency=listing_currency)
                    if tipranks_client is not None else {})
        if tipranks:
            evidence_only.append(tipranks)
    elif (tipranks_contract and
          (os.getenv("ANALYST_CONSENSUS_SECONDARY", "none") or "none").strip().lower()
          == "tipranks"):
        if tipranks_client is None:
            key = (os.getenv("TIPRANKS_API_KEY") or "").strip()
            tipranks_client = TipRanksConsensusClient(key) if key else None
        if tipranks_client is not None:
            secondary = tipranks_client.fetch(ticker, currency=listing_currency)
            if secondary:
                evidence_only.append(secondary)

    return _merge_many(primary, *supporting, fallback,
                       evidence_only=tuple(evidence_only))
