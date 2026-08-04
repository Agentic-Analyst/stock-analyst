"""
Prediction-market tool for the generalist agent.

Surfaces live, market-implied probabilities for forward-looking events (Fed
decisions, recession, elections, geopolitics, crypto) as a complement to news
(what happened) and FRED macro (where things stand): what the crowd actually
prices to happen next. This fills a real gap — VYNN's news/macro tools describe
the present, but had no read on market-implied odds of future events.

Uses Polymarket's public Gamma API (no key, no auth). Logic ADAPTED from
TradingAgents (Apache-2.0), rewritten async and returning structured JSON per
VYNN's tool contract.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, List, Optional

from src.agents.tools.base import Tool, tool_ok, tool_error

GAMMA_BASE = "https://gamma-api.polymarket.com"
REQUEST_TIMEOUT = 20
DEFAULT_LIMIT = 6


def _parse_json_list(value) -> list:
    """Gamma encodes outcomes/outcomePrices as JSON-string arrays."""
    if isinstance(value, list):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return []


class GetPredictionMarketsTool(Tool):
    name = "get_prediction_markets"
    description = (
        "Get live, market-implied probabilities for forward-looking events from "
        "Polymarket: Fed rate decisions, recession odds, elections, geopolitics, "
        "crypto, and other macro/political events. Two modes: pass `topic` for a "
        "SPECIFIC event ('Fed rate cut', 'recession 2026'); OMIT topic for the "
        "TRENDING view — the biggest open markets right now, for broad questions "
        "like 'what's happening in prediction markets' or 'what are the odds "
        "lately'. Complements news (what happened) and get_macro (where things "
        "stand). Coverage is macro/political/crypto — a specific single stock "
        "usually has no market. Returns markets with implied probability, traded "
        "volume, resolution date, and 1-week move."
    )
    parameters = {
        "type": "object",
        "properties": {
            "topic": {"type": "string", "description": "Optional event keyword(s), e.g. 'Fed rate cut'. OMIT for the trending/biggest markets overview."},
            "limit": {"type": "integer", "description": "Max markets to return (ranked by volume). Default 6.", "minimum": 1, "maximum": 15},
        },
    }
    is_readonly = True

    async def execute(self, topic: str = "", limit: Optional[int] = None) -> str:
        topic = (topic or "").strip()
        lim = limit or DEFAULT_LIMIT

        def _fetch() -> dict:
            from datetime import datetime, timezone
            import requests

            now = datetime.now(timezone.utc)

            def _forward(m: dict) -> bool:
                if m.get("closed"):
                    return False
                end = m.get("endDate")
                if end:
                    try:
                        if datetime.fromisoformat(end.replace("Z", "+00:00")) < now:
                            return False
                    except ValueError:
                        pass
                return bool(_parse_json_list(m.get("outcomePrices"))) and bool(_parse_json_list(m.get("outcomes")))

            def _extract(candidates: list) -> list:
                candidates.sort(key=lambda m: m.get("volumeNum") or 0, reverse=True)
                markets = []
                for m in candidates[:lim]:
                    prices = _parse_json_list(m.get("outcomePrices"))
                    outcomes = _parse_json_list(m.get("outcomes"))
                    try:
                        prob = float(prices[0])
                    except (ValueError, IndexError):
                        continue
                    wk = m.get("oneWeekPriceChange")
                    markets.append({
                        "question": m.get("question"),
                        "outcome": outcomes[0] if outcomes else "Yes",
                        "implied_probability_pct": round(prob * 100, 1),
                        "volume_usd": round(float(m.get("volumeNum") or 0), 0),
                        "resolves": (m.get("endDate") or "")[:10],
                        "one_week_change_pp": round(wk * 100, 1) if isinstance(wk, (int, float)) and wk else None,
                    })
                return markets

            def _search(query: str) -> list:
                resp = requests.get(
                    f"{GAMMA_BASE}/public-search",
                    params={"q": query, "limit_per_type": 20},
                    timeout=REQUEST_TIMEOUT,
                )
                resp.raise_for_status()
                data = resp.json()
                return [
                    m for event in data.get("events", [])
                    for m in event.get("markets", [])
                    if _forward(m)
                ]

            # Sports/esports dominate raw volume rankings but are noise for a
            # finance product — drop them from the trending view.
            _SKIP_TAGS = {"sports", "esports", "games"}

            def _trending() -> list:
                resp = requests.get(
                    f"{GAMMA_BASE}/events",
                    params={"closed": "false", "order": "volume24hr",
                            "ascending": "false", "limit": 40},
                    timeout=REQUEST_TIMEOUT,
                )
                resp.raise_for_status()
                out = []
                for event in resp.json():
                    tags = {(t.get("label") or "").lower() for t in (event.get("tags") or [])}
                    if tags & _SKIP_TAGS:
                        continue
                    # One market per event (its most-traded forward market), so
                    # a single multi-strike event can't crowd out the list.
                    fwd = [m for m in (event.get("markets") or []) if _forward(m)]
                    if fwd:
                        fwd.sort(key=lambda m: m.get("volumeNum") or 0, reverse=True)
                        out.append(fwd[0])
                return out

            try:
                mode = "search" if topic else "trending"
                candidates = _search(topic) if topic else _trending()
                # A miss on a vague search still deserves a useful answer:
                # fall back to what the crowd is actually trading right now.
                if not candidates and topic:
                    candidates = _trending()
                    mode = "trending_fallback"
            except requests.RequestException as e:
                return {"_error": f"Polymarket unavailable (network error: {e})."}

            return {"markets": _extract(candidates), "mode": mode}

        try:
            result = await asyncio.to_thread(_fetch)
        except Exception as e:
            return tool_error(f"Prediction-market lookup failed: {e}", topic=topic)
        if "_error" in result:
            return tool_error(result["_error"], topic=topic)
        markets = result.get("markets", [])
        mode = result.get("mode", "search")
        if not markets:
            return tool_ok(
                topic=topic or "trending", markets=[],
                note="No open prediction markets found right now. Answer from news/macro instead.",
            )
        note = "Implied probabilities are the crowd's priced odds (higher volume = deeper/more reliable), not certainties. Weave the relevant ones into your answer."
        if mode == "trending_fallback":
            note = (f"No market matched '{topic}' specifically, so these are the "
                    "BIGGEST open markets by 24h volume instead (sports excluded). "
                    "Present them as what the crowd is trading right now. " + note)
        elif mode == "trending":
            note = ("These are the biggest open markets by 24h volume right now "
                    "(sports excluded). " + note)
        return tool_ok(
            topic=topic or "trending",
            markets=markets,
            note=note,
        )


def build_prediction_market_tools() -> List[Tool]:
    """Prediction-market tools (public API, no key needed)."""
    return [GetPredictionMarketsTool()]
