"""
Resilient yfinance fetch helpers for the agent tools.

Yahoo throttles bursts from a shared IP (the prod server also runs a 10s price
poller), so a single un-retried .history() call intermittently comes back empty
— which used to surface to users as "live price unavailable" even though the
next request would have succeeded. Every agent tool that hits yfinance goes
through these helpers: short exponential backoff, then a fast_info fallback for
spot prices so a throttled history call still yields a usable quote.

Sync functions — call them inside the executor thread the tools already use.
"""

from __future__ import annotations

import time
from typing import Optional

_ATTEMPTS = 3
_BASE_DELAY = 1.2  # seconds; 1.2 -> 2.4 between retries


def fetch_history(symbol: str, period: str, interval: Optional[str] = None,
                  attempts: int = _ATTEMPTS):
    """yf.Ticker(symbol).history with retry/backoff. Returns a DataFrame or None."""
    import yfinance as yf

    kwargs = {"period": period}
    if interval:
        kwargs["interval"] = interval
    last_df = None
    for i in range(attempts):
        try:
            df = yf.Ticker(symbol).history(**kwargs)
            if df is not None and not df.empty:
                return df
            last_df = df
        except Exception:
            pass
        if i < attempts - 1:
            time.sleep(_BASE_DELAY * (2 ** i))
    return last_df if last_df is not None and not last_df.empty else None


def fetch_spot(symbol: str) -> Optional[float]:
    """
    Best-effort live spot price:
      1. 5d daily history (retried) — most reliable when Yahoo is healthy.
      2. fast_info.last_price — cheap endpoint that often survives throttling.
    Returns None only when both fail.
    """
    import yfinance as yf

    df = fetch_history(symbol, "5d", attempts=2)
    if df is not None and not df.empty:
        try:
            px = float(df["Close"].dropna().iloc[-1])
            if px > 0:
                return px
        except Exception:
            pass

    for i in range(2):
        try:
            fi = yf.Ticker(symbol).fast_info
            px = getattr(fi, "last_price", None)
            if px:
                return float(px)
        except Exception:
            pass
        time.sleep(_BASE_DELAY)
    return None
