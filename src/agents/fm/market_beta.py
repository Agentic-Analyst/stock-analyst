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
and reports the fit so a weak relationship is visible rather than silent. It
also supplies a country risk premium, added to the equity risk premium for
markets where sovereign and equity risk sit above the mature-market baseline.
Those premiums are methodology constants in the Damodaran style, not market
observations: they are approximate, dated, printed in the report, and can be
overridden per country without a deploy.
"""

from __future__ import annotations

import os
from typing import Optional, Tuple

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

# Country risk premium over the mature-market ERP, in the Damodaran style.
# APPROXIMATE and DATED — seeded from published mid-2025 estimates, not fetched.
# Printed in the report beside the ERP so a reader sees exactly what was added.
# Override any entry with CRP_<COUNTRY>=0.025 (uppercase, spaces as underscores).
_CRP_AS_OF = "2025-07"
_COUNTRY_RISK_PREMIUM = {
    # developed: no premium
    "United States": 0.0, "United Kingdom": 0.0, "Germany": 0.0, "France": 0.0,
    "Netherlands": 0.0, "Switzerland": 0.0, "Japan": 0.0, "Canada": 0.0,
    "Australia": 0.0, "Sweden": 0.0, "Denmark": 0.0, "Norway": 0.0,
    "Finland": 0.0, "Austria": 0.0, "Belgium": 0.0, "Ireland": 0.0,
    "Singapore": 0.0, "New Zealand": 0.0, "Luxembourg": 0.0,
    # developed with a spread
    "Italy": 0.022, "Spain": 0.019, "Portugal": 0.022, "Hong Kong": 0.006,
    "South Korea": 0.006, "Taiwan": 0.008, "Israel": 0.013, "Poland": 0.013,
    "Czechia": 0.010, "Saudi Arabia": 0.013, "United Arab Emirates": 0.008,
    # emerging
    "China": 0.010, "India": 0.029, "Indonesia": 0.027, "Malaysia": 0.016,
    "Thailand": 0.022, "Philippines": 0.027, "Vietnam": 0.040, "Brazil": 0.036,
    "Mexico": 0.024, "Chile": 0.013, "Colombia": 0.036, "Peru": 0.022,
    "South Africa": 0.040, "Turkey": 0.070, "Greece": 0.036, "Egypt": 0.090,
    "Nigeria": 0.090, "Pakistan": 0.120, "Argentina": 0.120,
}

_MIN_MONTHLY_OBS = 36     # below this, fall back to weekly
_MIN_WEEKLY_OBS = 52
_WEAK_FIT_R2 = 0.10       # below this the slope is mostly noise; say so


def home_index(symbol: Optional[str]) -> str:
    """The benchmark a listing should be regressed against."""
    if not symbol or "." not in symbol:
        return _HOME_INDEX[""]
    suffix = symbol.rsplit(".", 1)[1].upper()
    return _HOME_INDEX.get(suffix, _FALLBACK_INDEX)


def country_risk_premium(country: Optional[str]) -> Tuple[float, str]:
    """
    Premium over the mature-market ERP for ``country``, with its provenance.

    Returns ``(premium, label)``. Unknown countries get no premium and a label
    that says so — the alternative, guessing, is how numbers stop being
    arguable.
    """
    name = (country or "").strip()
    if not name:
        return 0.0, "no country on record — no country premium applied"

    key = "CRP_" + name.upper().replace(" ", "_")
    override = os.getenv(key)
    if override:
        try:
            value = float(override)
            if 0.0 <= value <= 0.30:
                return value, f"{name} {value*100:.1f}% ({key} override)"
        except ValueError:
            pass

    if name in _COUNTRY_RISK_PREMIUM:
        value = _COUNTRY_RISK_PREMIUM[name]
        if value == 0.0:
            return 0.0, f"{name}: mature market, no country premium"
        return value, f"{name} {value*100:.1f}% (approx., as of {_CRP_AS_OF})"
    return 0.0, f"{name}: no country premium on record — none applied"


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
            return {
                "raw": raw,
                "blume": 0.67 * raw + 0.33,
                "r_squared": r2,
                "observations": int(len(df)),
                "index": index,
                "window": f"{period} {'monthly' if interval == '1mo' else 'weekly'}",
                "weak_fit": r2 < _WEAK_FIT_R2,
            }
        except Exception:
            continue
    return None
