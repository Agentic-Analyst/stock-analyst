"""
UI directive tools — let the agent drive the chat frontend, not just answer in
text.

show_chart emits a one-line "[CHART_DIRECTIVE] {json}" marker into the run's
info.log (the same channel the [ANSWER_BEGIN]/[ANSWER_END] markers use).
api-runner's SSE stream consumes that line — it never appears in the visible
technical log — and forwards it as a `chart` event; the chat UI renders an
interactive live price chart inline with the answer.

The tool sends only a SPEC (symbol/timeframe/title). The frontend fetches the
actual price data itself from the realtime API, so the chart is genuinely live
(user can change timeframes) rather than a static snapshot of tool output.
"""

from __future__ import annotations

import json
import time

from .base import Tool, tool_ok, tool_error
from .crypto_utils import normalize_crypto_symbol, search_crypto_symbol

_TIMEFRAMES = ("1D", "1W", "1M", "3M", "1Y", "ALL")

# Symbols recently verified to return price data — avoids re-probing on
# repeat/comparison charts. symbol -> verified_at (epoch seconds).
_PROBE_CACHE: dict = {}
_PROBE_TTL = 600.0


def _has_price_data(sym: str) -> bool:
    """Cheap history probe so we never claim a chart for a dead symbol."""
    hit = _PROBE_CACHE.get(sym)
    if hit and time.time() - hit < _PROBE_TTL:
        return True
    try:
        from .yf_resilience import fetch_history
        df = fetch_history(sym, "5d", attempts=2)
        ok = df is not None and not df.empty
    except Exception:
        ok = False
    if ok:
        _PROBE_CACHE[sym] = time.time()
    return ok


class ShowChartTool(Tool):
    name = "show_chart"
    description = (
        "Display an interactive live price chart to the user inside the chat, "
        "right alongside your answer. Call this whenever the user asks about a "
        "price, performance, trend, momentum, or 'how has X done' — a chart makes "
        "those answers dramatically better. Works for stocks (symbol='NVDA') and "
        "crypto (symbol='BTC-USD' — always the -USD pair for coins). Call it "
        "BEFORE writing your final answer, then reference the chart naturally "
        "('as the chart shows…'). The chart is live and interactive; you only "
        "pick the symbol and initial timeframe. Use alongside get_prices/"
        "get_crypto/get_technicals — this displays, they fetch data for your text."
    )
    parameters = {
        "type": "object",
        "properties": {
            "symbol": {
                "type": "string",
                "description": "Ticker to chart: 'NVDA', 'AAPL', or a crypto pair 'BTC-USD'.",
            },
            "name": {
                "type": "string",
                "description": "Display name, e.g. 'NVIDIA' or 'Bitcoin'. Optional.",
            },
            "timeframe": {
                "type": "string",
                "description": "Initial timeframe: 1D, 1W, 1M, 3M, 1Y, or ALL. Default 1M.",
            },
            "title": {
                "type": "string",
                "description": "Optional short caption above the chart.",
            },
        },
        "required": ["symbol"],
    }
    repeatable = True  # comparing two names legitimately charts twice

    def __init__(self, ctx):
        self.ctx = ctx

    async def execute(self, symbol: str, name: str = "", timeframe: str = "1M",
                      title: str = "") -> str:
        import asyncio

        sym = (symbol or "").strip().upper()
        if not sym:
            return tool_error("symbol is required")
        # Coins normalize to their Yahoo -USD pair so the frontend's data
        # endpoints (which are yfinance-backed) resolve them.
        sym = normalize_crypto_symbol(sym) or sym

        # Validate BEFORE emitting: a directive for a symbol with no data
        # renders a broken/wrong chart while the model tells the user "I
        # displayed the chart" (happened in prod with TAO-USD, which is a
        # different, dead asset — Bittensor is TAO22974-USD).
        ok = await asyncio.to_thread(_has_price_data, sym)
        if not ok and sym.endswith("-USD"):
            # Unknown coin pair — resolve via live search using the display
            # name the model supplied ('Bittensor') or the base symbol.
            base = sym.rsplit("-", 1)[0]
            resolved = await asyncio.to_thread(
                search_crypto_symbol, (name or "").strip() or base
            )
            if resolved and resolved != sym:
                if await asyncio.to_thread(_has_price_data, resolved):
                    sym = resolved
                    ok = True
        if not ok:
            if sym.endswith("-USD"):
                # Crypto pairs get the hard gate: a wrong/dead pair renders a
                # wrong chart while the model claims success (the TAO bug).
                return tool_error(
                    f"No price data exists for '{sym}' — the chart was NOT "
                    "displayed; do not tell the user a chart was shown. Resolve "
                    "the correct symbol first (get_crypto for coins, "
                    "resolve_symbol for stocks), then call show_chart again.",
                    symbol=sym,
                )
            # Equities: a failed probe is far more likely a transient Yahoo
            # throttle than a bad symbol (the ticker usually came from
            # resolve_symbol or the user). The frontend fetches its own data,
            # so emit anyway rather than block a valid chart.

        tf = (timeframe or "1M").strip().upper()
        if tf not in _TIMEFRAMES:
            tf = "1M"

        spec = {
            "id": f"{sym}-{tf}",
            "kind": "price",
            "symbol": sym,
            "name": (name or "").strip() or sym,
            "timeframe": tf,
        }
        if (title or "").strip():
            spec["title"] = title.strip()

        # The SSE stream reads info.log — a bare print() never reaches it.
        self.ctx.ensure_base_logger()
        self.ctx.logger.info(
            "[CHART_DIRECTIVE] " + json.dumps(spec, ensure_ascii=False, separators=(",", ":"))
        )
        return tool_ok(
            note="Interactive live chart is now displayed to the user in the chat.",
            **spec,
        )


def build_ui_tools(ctx):
    return [ShowChartTool(ctx)]
