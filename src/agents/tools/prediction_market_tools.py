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
        "crypto, and other macro/political events. Use when the user asks 'what are "
        "the odds of X', 'is the market pricing a rate cut', or forward-looking "
        "macro/event questions. Complements news (what happened) and get_macro (where "
        "things stand). Coverage is macro/political/crypto — a specific single stock "
        "usually has no market. Returns the top markets with implied probability, "
        "traded volume, resolution date, and 1-week move."
    )
    parameters = {
        "type": "object",
        "properties": {
            "topic": {"type": "string", "description": "Event keyword(s), e.g. 'Fed rate cut', 'recession 2026', 'US election'."},
            "limit": {"type": "integer", "description": "Max markets to return (ranked by volume). Default 6.", "minimum": 1, "maximum": 15},
        },
        "required": ["topic"],
    }
    is_readonly = True

    async def execute(self, topic: str, limit: Optional[int] = None) -> str:
        topic = (topic or "").strip()
        if not topic:
            return tool_error("A topic is required, e.g. 'Fed rate cut'.")
        lim = limit or DEFAULT_LIMIT

        def _fetch() -> dict:
            from datetime import datetime, timezone
            import requests
            try:
                resp = requests.get(
                    f"{GAMMA_BASE}/public-search",
                    params={"q": topic, "limit_per_type": 20},
                    timeout=REQUEST_TIMEOUT,
                )
                resp.raise_for_status()
                data = resp.json()
            except requests.RequestException as e:
                return {"_error": f"Polymarket unavailable (network error: {e})."}

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

            candidates = [
                m for event in data.get("events", [])
                for m in event.get("markets", [])
                if _forward(m)
            ]
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
            return {"markets": markets}

        try:
            result = await asyncio.to_thread(_fetch)
        except Exception as e:
            return tool_error(f"Prediction-market lookup failed: {e}", topic=topic)
        if "_error" in result:
            return tool_error(result["_error"], topic=topic)
        markets = result.get("markets", [])
        if not markets:
            return tool_ok(
                topic=topic, markets=[],
                note=f"No open prediction markets matched '{topic}'. Polymarket coverage is macro/political/geopolitical/crypto; a specific equity may have none. Answer from news/macro instead.",
            )
        return tool_ok(
            topic=topic,
            markets=markets,
            note="Implied probabilities are the crowd's priced odds (higher volume = deeper/more reliable), not certainties. Weave the relevant ones into your answer.",
        )


def build_prediction_market_tools() -> List[Tool]:
    """Prediction-market tools (public API, no key needed)."""
    return [GetPredictionMarketsTool()]
