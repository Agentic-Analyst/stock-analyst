"""Read-only prediction-market research for the generalist agent.

The portfolio API owns canonical saved-position quotes and settlement. This
tool is the research counterpart: it discovers open Polymarket markets and
returns provider identities and *indicative* Gamma probabilities. It never
calls an indicative probability executable and never claims settlement data.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

from src.agents.tools.base import Tool, tool_error, tool_ok

GAMMA_BASE = "https://gamma-api.polymarket.com"
REQUEST_TIMEOUT = 10
DEFAULT_LIMIT = 6
CACHE_TTL_SECONDS = 60.0
STALE_CACHE_SECONDS = 15 * 60.0
MAX_CACHE_ENTRIES = 64
MAX_UPSTREAM_BYTES = 5 * 1024 * 1024
_TOKEN_ID = re.compile(r"^[0-9]{1,100}$")
_cache: Dict[Tuple[str, int], Tuple[float, Dict[str, Any]]] = {}
logger = logging.getLogger(__name__)

_SEARCH_STOPWORDS = {
    "a", "an", "and", "any", "are", "as", "at", "be", "before", "by",
    "do", "does", "for", "from", "happen", "in", "is", "it", "of", "on",
    "or", "the", "to", "what", "when", "which", "who", "will", "with",
}
_SEARCH_CONCEPTS = {
    "rates": "rate",
    "cuts": "cut", "cutting": "cut", "decrease": "cut", "decreases": "cut",
    "decreased": "cut", "fall": "cut", "falls": "cut", "lower": "cut",
    "lowered": "cut", "lowering": "cut", "reduce": "cut", "reduced": "cut",
    "hikes": "hike", "hiking": "hike", "increase": "hike", "increases": "hike",
    "increased": "hike", "raise": "hike", "raises": "hike", "raised": "hike",
    "results": "earnings", "earning": "earnings",
}


def _search_queries(topic: str) -> List[str]:
    """Small deterministic aliases for common market terminology.

    Gamma search is literal enough that natural names can miss markets using
    their trading shorthand (live: ``Federal Reserve rate cut`` returned none
    while ``Fed`` returned the current decision event).  Keep the expansion
    narrow and auditable rather than falling back to unrelated trending data.
    """
    original = str(topic or "").strip()
    lower = original.casefold()
    aliases = []
    for phrase, alias in (
        ("federal reserve", "Fed"),
        ("rate cut", "Fed"),
        ("interest rate", "Fed"),
        ("bitcoin", "BTC"),
        ("ethereum", "ETH"),
        ("s&p 500", "SPX"),
        ("standard & poor's 500", "SPX"),
    ):
        if phrase in lower and alias.casefold() != lower:
            aliases.append(alias)
    return list(dict.fromkeys([original, *aliases]))[:3]


def _search_concepts(value: Any) -> set[str]:
    """Return conservative lexical concepts for provider-result validation.

    Gamma search is intentionally fuzzy. Its result list is discovery input,
    not proof that a market answers the user's query. Requiring every material
    query concept prevents unrelated high-volume events from being presented
    as matches while still allowing a small, explicit synonym vocabulary.
    """
    text = str(value or "").casefold()
    for pattern, replacement in (
        (r"standard\s*(?:&|and)\s*poor(?:'s|s)?\s*500|s\s*&\s*p\s*500", " spx "),
        (r"federal\s+reserve|\bfomc\b", " fed "),
        (r"initial\s+public\s+offering", " ipo "),
        (r"\bbitcoin\b", " btc "),
        (r"\bethereum\b", " eth "),
    ):
        text = re.sub(pattern, replacement, text)
    concepts = set()
    for token in re.findall(r"[a-z0-9]+", text):
        if token in _SEARCH_STOPWORDS or len(token) < 2:
            continue
        concepts.add(_SEARCH_CONCEPTS.get(token, token))
    return concepts


def _relevant_to_topic(topic: str, market: Any, event: Any = None) -> bool:
    required = _search_concepts(topic)
    if not required or not isinstance(market, dict):
        return False
    parent = event if isinstance(event, dict) else {}
    searchable = " ".join(str(value or "") for value in (
        market.get("question"), market.get("slug"),
        parent.get("title"), parent.get("slug"),
    ))
    return required.issubset(_search_concepts(searchable))


def _parse_json_list(value: Any) -> list:
    """Gamma encodes outcomes, prices and token IDs as JSON-string arrays."""
    if isinstance(value, list):
        return value
    if not isinstance(value, str):
        return []
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError, ValueError):
        return []
    return parsed if isinstance(parsed, list) else []


def _text(value: Any, maximum: int = 500, *, multiline: bool = False) -> Optional[str]:
    if value is None:
        return None
    output = str(value).strip()
    allowed_controls = {"\n", "\r", "\t"} if multiline else set()
    if (not output or len(output) > maximum or any(
            ord(char) < 32 and char not in allowed_controls for char in output)):
        return None
    if multiline:
        output = output.replace("\r\n", "\n").replace("\r", "\n")
    return output


def _number(value: Any) -> Optional[float]:
    try:
        if isinstance(value, bool):
            return None
        output = float(value)
    except (TypeError, ValueError):
        return None
    return output if math.isfinite(output) else None


def _probability(value: Any) -> Optional[float]:
    output = _number(value)
    return output if output is not None and 0 <= output <= 1 else None


def _indicative_probability_vector(
    prices: list[Any], outcome_count: int,
) -> tuple[list[Optional[float]], str, Optional[float]]:
    """Validate a complete Gamma probability vector without renormalizing it."""
    if len(prices) != outcome_count:
        return [None] * outcome_count, "incomplete", None
    values = [_probability(value) for value in prices]
    if any(value is None for value in values):
        return [None] * outcome_count, "invalid", None
    total = sum(value for value in values if value is not None)
    if not math.isclose(total, 1.0, rel_tol=0.0, abs_tol=0.02):
        return [None] * outcome_count, "incoherent", total
    return values, "coherent", total


def _captured_at() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _future_open_market(market: Any, now: datetime) -> bool:
    if not isinstance(market, dict) or market.get("closed") is True:
        return False
    if market.get("active") is False:
        return False
    end = _text(market.get("endDateIso") or market.get("endDate"), 60)
    if end:
        try:
            parsed = datetime.fromisoformat(end.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            if parsed.astimezone(timezone.utc) < now:
                return False
        except ValueError:
            # An open-market claim without a parseable resolution timestamp is
            # not safe to present as currently resolvable.
            return False
    return bool(_parse_json_list(market.get("outcomes")))


def _normalize_market(market: Any, parent: Optional[dict] = None) -> Optional[dict]:
    if not isinstance(market, dict):
        return None
    labels = _parse_json_list(market.get("outcomes"))
    prices = _parse_json_list(market.get("outcomePrices"))
    token_ids = _parse_json_list(market.get("clobTokenIds"))
    question = _text(market.get("question"), 500)
    if not question or len(labels) < 2:
        return None

    probabilities, probability_status, probability_sum = (
        _indicative_probability_vector(prices, len(labels))
    )

    identities_complete = len(token_ids) == len(labels)
    outcomes = []
    for index, raw_label in enumerate(labels):
        label = _text(raw_label, 160)
        if not label:
            return None
        token = _text(token_ids[index], 240) if identities_complete else None
        if token and not _TOKEN_ID.fullmatch(token):
            token = None
            identities_complete = False
        outcomes.append({
            "outcome_id": token,
            "label": label,
            "indicative_probability": probabilities[index],
        })
    if not identities_complete:
        for outcome in outcomes:
            outcome["outcome_id"] = None

    event = parent if isinstance(parent, dict) else {}
    if not event:
        events = market.get("events")
        event = events[0] if isinstance(events, list) and events and isinstance(events[0], dict) else {}
    slug = _text(event.get("slug"), 300) or _text(market.get("slug"), 300)
    description = (
        _text(market.get("description"), 5000, multiline=True)
        or _text(event.get("description"), 5000, multiline=True)
    )
    resolution_source = (
        _text(market.get("resolutionSource"), 2000, multiline=True)
        or _text(event.get("resolutionSource"), 2000, multiline=True)
    )
    resolution_url = (
        resolution_source if resolution_source and
        resolution_source.lower().startswith(("https://", "http://")) else None
    )
    week_change = _number(market.get("oneWeekPriceChange"))
    first_probability = outcomes[0]["indicative_probability"]
    return {
        "venue": "Polymarket",
        "market_id": _text(market.get("conditionId"), 240),
        "provider_market_id": _text(market.get("id"), 100),
        "event_id": _text(event.get("id"), 100),
        "question": question,
        "status": "open",
        "resolves_at": _text(
            market.get("endDateIso") or market.get("endDate")
            or event.get("endDate"), 60,
        ),
        "resolution_url": resolution_url,
        "resolution_source_text": None if resolution_url else resolution_source,
        "resolution_metadata_available": bool(description or resolution_source),
        "description": description,
        "market_url": (
            f"https://polymarket.com/event/{quote(slug, safe='')}" if slug else None
        ),
        "quote_currency": "PUSD",
        "volume": _number(market.get("volumeNum") or market.get("volume")),
        "liquidity": _number(market.get("liquidityNum") or market.get("liquidity")),
        "outcome_identities_complete": identities_complete,
        "indicative_probability_status": probability_status,
        "indicative_probability_sum": probability_sum,
        "outcomes": outcomes,
        "outcome": outcomes[0]["label"],
        "implied_probability_pct": (
            round(first_probability * 100, 1) if first_probability is not None else None
        ),
        "one_week_change_pp": (
            round(week_change * 100, 1) if week_change is not None else None
        ),
    }


def _cache_get(key: Tuple[str, int], maximum_age: float) -> Optional[dict]:
    cached = _cache.get(key)
    if cached and time.monotonic() - cached[0] <= maximum_age:
        fresh = maximum_age == CACHE_TTL_SECONDS
        return {**cached[1], "cache": "hit" if fresh else "stale", "stale": not fresh}
    return None


def _cache_put(key: Tuple[str, int], value: dict) -> dict:
    if len(_cache) >= MAX_CACHE_ENTRIES and key not in _cache:
        _cache.pop(min(_cache, key=lambda item: _cache[item][0]), None)
    _cache[key] = (time.monotonic(), value)
    return {**value, "cache": "miss", "stale": False}


def _get_json_once(path: str, *, params: Dict[str, Any]) -> Any:
    """Fetch one fixed-host Gamma document with a hard response-size bound."""
    import requests

    response = requests.get(
        f"{GAMMA_BASE}{path}", params=params, timeout=REQUEST_TIMEOUT,
        headers={"Accept": "application/json", "User-Agent": "VynnAI/1.0 market-data"},
        allow_redirects=False, stream=True,
    )
    try:
        response.raise_for_status()
        length = (getattr(response, "headers", {}) or {}).get("Content-Length")
        if length is not None:
            try:
                if int(length) > MAX_UPSTREAM_BYTES:
                    raise ValueError("upstream response exceeds size limit")
            except (TypeError, ValueError) as error:
                if isinstance(error, ValueError) and str(error).startswith("upstream"):
                    raise
        iterator = getattr(response, "iter_content", None)
        if not callable(iterator):
            return response.json()
        body = bytearray()
        for chunk in iterator(chunk_size=64 * 1024):
            if not chunk:
                continue
            body.extend(chunk)
            if len(body) > MAX_UPSTREAM_BYTES:
                raise ValueError("upstream response exceeds size limit")
        return json.loads(bytes(body).decode("utf-8-sig"))
    finally:
        close = getattr(response, "close", None)
        if callable(close):
            close()


def _get_json(path: str, *, params: Dict[str, Any]) -> Any:
    """Retry one transient Gamma transport failure, never a bad request."""
    import requests

    for attempt in range(2):
        try:
            return _get_json_once(path, params=params)
        except (requests.Timeout, requests.ConnectionError):
            if attempt:
                raise
            time.sleep(0.2)
    raise RuntimeError("unreachable")  # pragma: no cover


class GetPredictionMarketsTool(Tool):
    name = "get_prediction_markets"
    description = (
        "Discover open Polymarket markets and indicative market-implied "
        "probabilities for forward-looking events. Pass `topic` for a specific "
        "event or omit it for a non-sports trending view. Returns every outcome, "
        "durable provider IDs when available, volume, liquidity, resolution "
        "metadata and freshness. Probabilities are indicative Gamma data, not an "
        "executable quote or forecast certainty. Saved-position valuation uses "
        "the portfolio service's canonical CLOB outcome resolution separately."
    )
    parameters = {
        "type": "object",
        "properties": {
            "topic": {"type": "string", "maxLength": 80,
                      "description": "Optional event keywords; omit for trending."},
            "limit": {"type": "integer", "minimum": 1, "maximum": 15,
                      "description": "Maximum markets, ranked by volume. Default 6."},
        },
    }
    is_readonly = True

    async def execute(self, topic: str = "", limit: Optional[int] = None) -> str:
        topic = str(topic or "").strip()
        if len(topic) > 80:
            return tool_error("Prediction-market topic must be 80 characters or fewer.")
        if isinstance(limit, bool) or (limit is not None and not isinstance(limit, int)):
            return tool_error("Prediction-market limit must be an integer from 1 to 15.")
        lim = DEFAULT_LIMIT if limit is None else limit
        if not 1 <= lim <= 15:
            return tool_error("Prediction-market limit must be from 1 to 15.")
        key = (topic.casefold(), lim)
        cached = _cache_get(key, CACHE_TTL_SECONDS)
        if cached is not None:
            return tool_ok(note=_note(cached.get("markets", [])), **cached)

        def _fetch() -> dict:
            now = datetime.now(timezone.utc)
            if topic:
                queries = _search_queries(topic)
                candidates = []
                queries_tried = []
                for query in queries:
                    queries_tried.append(query)
                    raw = _get_json(
                        "/public-search",
                        params={
                            "q": query,
                            "events_status": "active",
                            "limit_per_type": min(lim, 10),
                            "keep_closed_markets": 0,
                            "search_profiles": "false",
                            # Without this explicit projection flag Gamma's
                            # live public-search response can omit the parent
                            # event description/resolutionSource even when
                            # ``optimized=false``.  The dashboard API already
                            # sends it; keep the agent research path aligned so
                            # the same market does not lose its rules in chat.
                            "search_tags": "false",
                            # The optimized schema omits durable market/token
                            # identities, liquidity and volume. Those fields are
                            # necessary evidence, so keep the full schema and
                            # control size through the result limit instead.
                            "optimized": "false",
                        },
                    )
                    candidates = [
                        (market, event)
                        for event in (
                            raw.get("events") if isinstance(raw, dict) else []
                        ) or []
                        if isinstance(event, dict) and event.get("closed") is not True
                        for market in (event.get("markets") or [])
                        if (_future_open_market(market, now)
                            and _relevant_to_topic(topic, market, event))
                    ]
                    if candidates:
                        break
                mode = "search"
            else:
                queries_tried = []
                raw = _get_json(
                    "/events",
                    params={"closed": "false", "order": "volume24hr",
                            "active": "true", "archived": "false",
                            "include_chat": "false", "include_template": "false",
                            "ascending": "false",
                            "limit": min(20, max(10, lim * 2))},
                )
                candidates = []
                for event in raw if isinstance(raw, list) else []:
                    if not isinstance(event, dict):
                        continue
                    tags = {str(tag.get("label") or "").casefold()
                            for tag in event.get("tags", []) if isinstance(tag, dict)}
                    if tags & {"sports", "esports", "games"}:
                        continue
                    markets = [m for m in event.get("markets", [])
                               if _future_open_market(m, now)]
                    if markets:
                        markets.sort(key=lambda m: _number(m.get("volumeNum") or m.get("volume")) or 0,
                                     reverse=True)
                        candidates.append((markets[0], event))
                mode = "trending"

            candidates.sort(
                key=lambda item: _number(item[0].get("volumeNum") or item[0].get("volume")) or 0,
                reverse=True,
            )
            markets = []
            for market, event in candidates:
                normalized = _normalize_market(market, event)
                if normalized:
                    markets.append(normalized)
                if len(markets) >= lim:
                    break
            return {
                "topic": topic or "trending", "mode": mode,
                "query_variants_tried": queries_tried,
                "provider": "polymarket", "source": "gamma_indicative",
                "as_of": _captured_at(), "markets": markets, "count": len(markets),
                "capabilities": {
                    "discovery": True, "indicative_probabilities": True,
                    "executable_quotes": False, "settlement_confirmation": False,
                    "trading": False,
                },
            }

        try:
            payload = _cache_put(key, await asyncio.to_thread(_fetch))
        except Exception as error:
            stale = _cache_get(key, STALE_CACHE_SECONDS)
            if stale is None:
                logger.warning("prediction research upstream unavailable: %s", type(error).__name__)
                return tool_error(
                    "Prediction-market data is unavailable right now. Try again later.",
                    topic=topic or "trending",
                )
            logger.warning("prediction research upstream unavailable; serving stale cache: %s",
                           type(error).__name__)
            payload = stale
        return tool_ok(note=_note(payload.get("markets", [])), **payload)


def _note(markets: list) -> str:
    if not markets:
        return ("No matching open prediction markets were found. Do not substitute "
                "unrelated trending markets; use relevant news or macro data instead.")
    missing_resolution = sum(
        not bool(market.get("resolution_metadata_available"))
        for market in markets if isinstance(market, dict)
    )
    resolution_note = (
        f" Gamma omitted resolution metadata for {missing_resolution} returned "
        "market(s); inspect the linked venue page before relying on the outcome."
        if missing_resolution else
        " Use the returned resolution metadata when judging the outcome."
    )
    return ("Gamma probabilities are indicative crowd prices, not executable quotes, "
            "verified forecasts, or certainties. Compare all outcomes and use "
            "volume/liquidity when judging signal quality." + resolution_note)


def build_prediction_market_tools() -> List[Tool]:
    return [GetPredictionMarketsTool()]
