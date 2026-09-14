"""
Beta against the listing's HOME index, and a country risk premium.

Yahoo's `beta` field is computed against the S&P 500 for every listing on
earth. For a US stock that is the right benchmark and our own regression
reproduces it (Apple 1.09 vs Yahoo 1.085; NVIDIA 2.19 vs 2.217). For anything
else it measures how much a foreign stock co-moves with an American index —
which is mostly "not much" — and reads as low risk:

    Reliance    Yahoo 0.15   vs Nifty 0.98
    Infosys     Yahoo 0.11   vs Nifty 0.70
    PC Jeweller Yahoo 0.33   vs Nifty 3.28
    Shell       Yahoo -0.22  vs FTSE  0.72
    LVMH        Yahoo 0.84   vs CAC   1.38

Every NSE listing therefore hit the CAPM's 0.6 floor, and with a US-proxy
risk-free rate PC Jeweller — a small-cap jeweller that swings 50% — was
discounted at 7.9% and rated BUY at +48.6%.

This module regresses five years of monthly returns on the home index (two
years of weekly returns when history is short), applies the Blume adjustment,
and reports the fit so a weak relationship is visible rather than silent. The
country risk premium that used to live here as a hand-typed table now comes
from Damodaran's published one (country_risk); the name is re-exported so
existing callers and tests keep working.
"""

from __future__ import annotations

import hashlib
from typing import Optional

# Exchange suffix -> home index. Verified against live history for the first
# group; the rest are Yahoo's standard symbols for those markets.
_HOME_INDEX = {
    "NS": "^NSEI", "BO": "^BSESN", "PA": "^FCHI", "DE": "^GDAXI", "F": "^GDAXI",
    "L": "^FTSE", "T": "^N225", "KS": "^KS11", "KQ": "^KQ11", "HK": "^HSI",
    "SW": "^SSMI", "AS": "^AEX", "MI": "FTSEMIB.MI", "TO": "^GSPTSE",
    "V": "^GSPTSE", "AX": "^AXJO", "SA": "^BVSP", "MX": "^MXX", "TW": "^TWII",
    "TWO": "^TWII", "": "^GSPC",
    "BR": "^BFX", "MC": "^IBEX", "ST": "^OMX", "CO": "^OMXC25", "HE": "^OMXH25",
    "VI": "^ATX", "LS": "PSI20.LS", "IR": "^ISEQ", "NZ": "^NZ50", "SI": "^STI",
    "SS": "000001.SS", "SZ": "399001.SZ", "JO": "^J203.JO", "TA": "^TA125.TA",
    "BK": "^SET.BK", "JK": "^JKSE", "KL": "^KLSE",
}
_FALLBACK_INDEX = "^GSPC"

_MIN_MONTHLY_OBS = 36     # below this, fall back to weekly
_MIN_WEEKLY_OBS = 52
_WEAK_FIT_R2 = 0.10       # below this the slope is mostly noise; say so


def home_index(symbol: Optional[str]) -> str:
    """The benchmark a listing should be regressed against."""
    if not symbol or "." not in symbol:
        return _HOME_INDEX[""]
    suffix = symbol.rsplit(".", 1)[1].upper()
    return _HOME_INDEX.get(suffix, _FALLBACK_INDEX)


from .country_risk import country_risk_premium  # noqa: E402,F401  (re-export)


def _returns(symbol: str, period: str, interval: str):
    import yfinance as yf
    h = yf.Ticker(symbol).history(period=period, interval=interval, auto_adjust=True)
    if h is None or h.empty or "Close" not in h:
        return None
    return h["Close"].pct_change().dropna()


def compute_beta(symbol: Optional[str]) -> Optional[dict]:
    """
    Raw and Blume-adjusted beta of ``symbol`` against its home index.

    Returns None when history is insufficient — the caller decides on a
    fallback and labels it. Never raises.
    """
    if not symbol:
        return None
    try:
        import numpy as np
        import pandas as pd
    except Exception:
        return None

    index = home_index(symbol)
    for period, interval, minimum in (("5y", "1mo", _MIN_MONTHLY_OBS), ("2y", "1wk", _MIN_WEEKLY_OBS)):
        try:
            s = _returns(symbol, period, interval)
            i = _returns(index, period, interval)
            if s is None or i is None:
                continue
            df = pd.concat([s, i], axis=1, keys=["s", "i"]).dropna()
            if len(df) < minimum:
                continue
            cov = np.cov(df["s"], df["i"])
            if cov[1, 1] <= 0:
                continue
            raw = float(cov[0, 1] / cov[1, 1])
            corr = np.corrcoef(df["s"], df["i"])[0, 1]
            r2 = float(corr * corr) if np.isfinite(corr) else 0.0
            # Persist the exact aligned sample identity without redistributing
            # provider price history. Float.hex() is lossless and stable, so a
            # later audit can verify that it is looking at the same returns.
            digest = hashlib.sha256()
            for observed_at, row in df.iterrows():
                stamp = (
                    observed_at.isoformat()
                    if hasattr(observed_at, "isoformat") else str(observed_at)
                )
                digest.update(
                    (
                        f"{stamp}|{float(row['s']).hex()}|"
                        f"{float(row['i']).hex()}\n"
                    ).encode("utf-8")
                )
            start = df.index.min()
            end = df.index.max()
            return {
                "raw": raw,
                "blume": 0.67 * raw + 0.33,
                "r_squared": r2,
                "observations": int(len(df)),
                "index": index,
                "window": f"{period} {'monthly' if interval == '1mo' else 'weekly'}",
                "period": period,
                "interval": interval,
                "observation_start": (
                    start.isoformat() if hasattr(start, "isoformat") else str(start)
                ),
                "observation_end": (
                    end.isoformat() if hasattr(end, "isoformat") else str(end)
                ),
                "observations_sha256": digest.hexdigest(),
                "series_source": "Yahoo Finance via yfinance",
                "series_adjustment": "auto_adjust=True",
                "sufficient_statistics": {
                    "security_return_mean": float(df["s"].mean()),
                    "benchmark_return_mean": float(df["i"].mean()),
                    "security_return_variance": float(cov[0, 0]),
                    "benchmark_return_variance": float(cov[1, 1]),
                    "return_covariance": float(cov[0, 1]),
                    "return_correlation": float(corr),
                },
                "weak_fit": r2 < _WEAK_FIT_R2,
            }
        except Exception:
            continue
    return None
