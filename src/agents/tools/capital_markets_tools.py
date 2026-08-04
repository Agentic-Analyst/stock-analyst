"""
Capital-markets tools for the generalist agent: options pricing, portfolio
risk metrics, and portfolio optimization.

These broaden the agent beyond single-stock fundamentals so it can answer
derivatives questions ("price a 30-day NVDA call"), risk questions ("what's the
Sharpe / max drawdown of AAPL"), and allocation questions ("optimize a portfolio
of these names"). They are self-contained (numpy + yfinance only — no scipy) and
follow VYNN's async Tool contract.

The Black-Scholes math and the portfolio-metric definitions are ADAPTED from
Vibe-Trading (MIT-licensed) and standard quantitative-finance references; the
implementations here are numpy-only and rewritten for our async stack.
"""
from __future__ import annotations

import asyncio
import math
from typing import Any, List, Optional

from src.agents.tools.base import Tool, tool_ok, tool_error


# --- normal distribution helpers (stdlib only, no scipy) ---------------------

def _norm_cdf(x: float) -> float:
    """Standard normal CDF via the error function (exact, no scipy)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    """Standard normal PDF."""
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def _bs_price_and_greeks(spot: float, strike: float, T: float, r: float,
                         sigma: float, option_type: str) -> dict:
    """Black-Scholes price + Greeks (delta, gamma, theta/day, vega/1%).

    T is time-to-expiry in years. Handles T<=0 as intrinsic value.
    """
    if T <= 0 or sigma <= 0:
        if option_type == "call":
            price = max(spot - strike, 0.0)
            delta = 1.0 if spot > strike else 0.0
        else:
            price = max(strike - spot, 0.0)
            delta = -1.0 if spot < strike else 0.0
        return {"price": round(price, 6), "delta": delta, "gamma": 0.0, "theta": 0.0, "vega": 0.0}

    sqrt_T = math.sqrt(T)
    d1 = (math.log(spot / strike) + (r + sigma ** 2 / 2.0) * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T
    pdf_d1 = _norm_pdf(d1)

    if option_type == "call":
        price = spot * _norm_cdf(d1) - strike * math.exp(-r * T) * _norm_cdf(d2)
        delta = _norm_cdf(d1)
        theta = (-(spot * pdf_d1 * sigma) / (2 * sqrt_T)
                 - r * strike * math.exp(-r * T) * _norm_cdf(d2))
    else:
        price = strike * math.exp(-r * T) * _norm_cdf(-d2) - spot * _norm_cdf(-d1)
        delta = _norm_cdf(d1) - 1.0
        theta = (-(spot * pdf_d1 * sigma) / (2 * sqrt_T)
                 + r * strike * math.exp(-r * T) * _norm_cdf(-d2))

    gamma = pdf_d1 / (spot * sigma * sqrt_T)
    return {
        "price": round(price, 4),
        "delta": round(delta, 4),
        "gamma": round(gamma, 6),
        "theta_per_day": round(theta / 365.0, 4),
        "vega_per_1pct": round(spot * pdf_d1 * sqrt_T / 100.0, 4),
    }


class PriceOptionTool(Tool):
    name = "price_option"
    description = (
        "Price an equity option with Black-Scholes and return its Greeks (delta, "
        "gamma, theta, vega). Use for 'price a 30-day NVDA 150 call', option "
        "strategy questions, or estimating an option's fair value and risk. If spot "
        "or volatility aren't given, it fetches the live price and estimates implied "
        "volatility from recent history. Returns theoretical price + Greeks."
    )
    parameters = {
        "type": "object",
        "properties": {
            "ticker": {"type": "string", "description": "Underlying ticker, e.g. 'NVDA'. Used to fetch spot + vol if not provided."},
            "strike": {"type": "number", "description": "Strike price."},
            "expiry_days": {"type": "number", "description": "Days until expiry."},
            "option_type": {"type": "string", "enum": ["call", "put"], "description": "call or put."},
            "spot": {"type": "number", "description": "Optional. Underlying price; fetched from ticker if omitted."},
            "volatility": {"type": "number", "description": "Optional. Annualized vol as a decimal (0.4 = 40%); estimated from history if omitted."},
            "risk_free_rate": {"type": "number", "description": "Optional. Annual risk-free rate as a decimal. Defaults to 0.04."},
        },
        "required": ["strike", "expiry_days", "option_type"],
    }
    is_readonly = True

    async def execute(self, strike: float, expiry_days: float, option_type: str,
                      ticker: str = "", spot: Optional[float] = None,
                      volatility: Optional[float] = None,
                      risk_free_rate: float = 0.04) -> str:
        option_type = (option_type or "").strip().lower()
        if option_type not in ("call", "put"):
            return tool_error("option_type must be 'call' or 'put'.")
        if strike <= 0 or expiry_days < 0:
            return tool_error("strike must be positive and expiry_days non-negative.")

        def _fetch_spot_vol():
            import numpy as np
            from .yf_resilience import fetch_history, fetch_spot
            s, v = spot, volatility
            if (s is None or v is None) and ticker:
                hist = fetch_history(ticker.upper(), "6mo")
                if hist is not None and not hist.empty:
                    if s is None:
                        s = float(hist["Close"].iloc[-1])
                    if v is None:
                        rets = np.log(hist["Close"] / hist["Close"].shift(1)).dropna()
                        v = float(rets.std() * np.sqrt(252)) if len(rets) > 5 else 0.4
                if s is None:
                    # History throttled: a fast_info spot still lets us price.
                    s = fetch_spot(ticker.upper())
                if v is None and s is not None:
                    v = 0.4  # conservative default when history is unavailable
            return s, v

        try:
            s, v = await asyncio.to_thread(_fetch_spot_vol)
        except Exception as e:
            return tool_error(f"Could not fetch spot/volatility for {ticker}: {e}")
        if s is None:
            return tool_error("Need a spot price: pass spot=, or a ticker to fetch it.")
        if v is None or v <= 0:
            v = 0.4  # sane default if history was too thin

        greeks = _bs_price_and_greeks(
            spot=float(s), strike=float(strike), T=float(expiry_days) / 365.0,
            r=float(risk_free_rate), sigma=float(v), option_type=option_type,
        )
        return tool_ok(
            ticker=ticker.upper() or None,
            option_type=option_type,
            spot=round(float(s), 2),
            strike=float(strike),
            expiry_days=float(expiry_days),
            volatility_annualized=round(float(v), 4),
            risk_free_rate=float(risk_free_rate),
            **greeks,
            note="Black-Scholes theoretical value + Greeks. Volatility is historical (a proxy for implied) unless you passed one.",
        )


class ComputeRiskMetricsTool(Tool):
    name = "compute_risk_metrics"
    description = (
        "Compute risk-adjusted performance metrics for one or more tickers from "
        "their price history: total return, CAGR, annualized volatility, Sharpe, "
        "Sortino, Calmar, and max drawdown. Use for 'what's AAPL's Sharpe', 'how "
        "risky is this', or comparing risk-adjusted returns. Returns a metrics block "
        "per ticker."
    )
    parameters = {
        "type": "object",
        "properties": {
            "tickers": {"type": "array", "items": {"type": "string"}, "description": "1-8 tickers.", "minItems": 1, "maxItems": 8},
            "period": {"type": "string", "description": "History window, e.g. '1y', '3y', '5y'. Default '3y'.", "default": "3y"},
        },
        "required": ["tickers"],
    }
    is_readonly = True

    async def execute(self, tickers, period: str = "3y") -> str:
        if isinstance(tickers, str):
            tickers = [t.strip() for t in tickers.replace(",", " ").split() if t.strip()]
        tickers = [t.strip().upper() for t in (tickers or []) if t and t.strip()][:8]
        if not tickers:
            return tool_error("Need at least one ticker.")

        def _metrics_one(tkr: str) -> dict:
            import numpy as np
            import yfinance as yf
            try:
                hist = yf.Ticker(tkr).history(period=period)
            except Exception as e:
                return {"ticker": tkr, "error": f"history fetch failed: {e}"}
            if hist.empty or len(hist) < 20:
                return {"ticker": tkr, "error": "not enough price history"}
            close = hist["Close"].astype(float)
            rets = close.pct_change().dropna().to_numpy()
            if rets.size < 10:
                return {"ticker": tkr, "error": "not enough return data"}
            ann = 252.0
            total_return = float(close.iloc[-1] / close.iloc[0] - 1.0)
            years = max(len(close) / ann, 1e-9)
            cagr = float((close.iloc[-1] / close.iloc[0]) ** (1.0 / years) - 1.0)
            vol = float(rets.std() * np.sqrt(ann))
            mean_ann = float(rets.mean() * ann)
            sharpe = float(mean_ann / (vol + 1e-10))
            downside = rets[rets < 0]
            downside_std = float(downside.std() * np.sqrt(ann)) if downside.size else 0.0
            sortino = float(mean_ann / (downside_std + 1e-10)) if downside_std else 0.0
            curve = (1.0 + rets).cumprod()
            peak = np.maximum.accumulate(curve)
            max_dd = float((curve / peak - 1.0).min())
            calmar = float(cagr / abs(max_dd)) if abs(max_dd) > 1e-10 else 0.0
            def _pct(x): return round(x * 100, 2)
            return {
                "ticker": tkr,
                "period": period,
                "total_return_pct": _pct(total_return),
                "cagr_pct": _pct(cagr),
                "annualized_volatility_pct": _pct(vol),
                "sharpe": round(sharpe, 2),
                "sortino": round(sortino, 2),
                "calmar": round(calmar, 2),
                "max_drawdown_pct": _pct(max_dd),
            }

        try:
            rows = await asyncio.gather(*[asyncio.to_thread(_metrics_one, t) for t in tickers])
        except Exception as e:
            return tool_error(f"Risk-metrics computation failed: {e}", tickers=tickers)
        return tool_ok(period=period, metrics=list(rows),
                       note="Risk-adjusted metrics from price history (risk-free rate assumed 0 for Sharpe/Sortino). Synthesize the read for the user.")


class OptimizePortfolioTool(Tool):
    name = "optimize_portfolio"
    description = (
        "Optimize portfolio weights across 2-10 tickers from their historical "
        "returns. Supports 'max_sharpe' (tangency portfolio) and 'risk_parity' "
        "(equal risk contribution), long-only. Use for 'how should I weight these', "
        "'optimize my portfolio', or allocation questions. Returns suggested weights "
        "plus the portfolio's expected return, volatility, and Sharpe."
    )
    parameters = {
        "type": "object",
        "properties": {
            "tickers": {"type": "array", "items": {"type": "string"}, "description": "2-10 tickers.", "minItems": 2, "maxItems": 10},
            "method": {"type": "string", "enum": ["max_sharpe", "risk_parity"], "description": "Optimization objective. Default 'max_sharpe'.", "default": "max_sharpe"},
            "period": {"type": "string", "description": "History window, e.g. '1y', '3y'. Default '3y'.", "default": "3y"},
        },
        "required": ["tickers"],
    }
    is_readonly = True

    async def execute(self, tickers, method: str = "max_sharpe", period: str = "3y") -> str:
        if isinstance(tickers, str):
            tickers = [t.strip() for t in tickers.replace(",", " ").split() if t.strip()]
        tickers = [t.strip().upper() for t in (tickers or []) if t and t.strip()][:10]
        method = (method or "max_sharpe").strip().lower()
        if len(tickers) < 2:
            return tool_error("Need at least 2 tickers to optimize.")
        if method not in ("max_sharpe", "risk_parity"):
            method = "max_sharpe"

        def _optimize() -> dict:
            import numpy as np
            import yfinance as yf
            data = yf.download(tickers, period=period, progress=False)["Close"]
            if hasattr(data, "columns"):
                data = data.dropna(axis=1, how="all").dropna()
            else:  # single-column edge case
                data = data.to_frame()
            cols = list(data.columns)
            if len(cols) < 2 or len(data) < 30:
                return {"error": "not enough overlapping price history for these tickers"}
            rets = data.pct_change().dropna().to_numpy()
            ann = 252.0
            mu = rets.mean(axis=0) * ann          # annualized expected returns
            cov = np.cov(rets, rowvar=False) * ann  # annualized covariance
            n = len(cols)

            if method == "max_sharpe":
                # Tangency portfolio: w ∝ Σ⁻¹ μ, then long-only clip + renormalize.
                try:
                    inv = np.linalg.pinv(cov)
                    w = inv @ mu
                except Exception:
                    w = np.ones(n)
                w = np.clip(w, 0.0, None)
                if w.sum() <= 0:
                    w = np.ones(n)
                w = w / w.sum()
            else:  # risk_parity — iterative equal-risk-contribution (numpy only)
                w = np.ones(n) / n
                for _ in range(500):
                    port_var = float(w @ cov @ w)
                    if port_var <= 0:
                        break
                    mrc = cov @ w                    # marginal risk contribution
                    rc = w * mrc                     # risk contribution
                    target = port_var / n
                    w = w * (target / (rc + 1e-12)) ** 0.5
                    w = np.clip(w, 1e-6, None)
                    w = w / w.sum()

            port_ret = float(w @ mu)
            port_vol = float(np.sqrt(max(w @ cov @ w, 0.0)))
            sharpe = float(port_ret / (port_vol + 1e-10))
            weights = {c: round(float(wi) * 100, 1) for c, wi in zip(cols, w)}
            return {
                "method": method,
                "period": period,
                "weights_pct": weights,
                "expected_return_pct": round(port_ret * 100, 2),
                "expected_volatility_pct": round(port_vol * 100, 2),
                "sharpe": round(sharpe, 2),
            }

        try:
            result = await asyncio.to_thread(_optimize)
        except Exception as e:
            return tool_error(f"Optimization failed: {e}", tickers=tickers)
        if "error" in result:
            return tool_error(result["error"], tickers=tickers)
        return tool_ok(tickers=tickers, **result,
                       note="Long-only weights from historical returns. Explain the allocation and its trade-offs; past performance is not a guarantee.")


def build_capital_markets_tools() -> List[Tool]:
    """Options + portfolio risk/optimization tools (no external API keys)."""
    return [
        PriceOptionTool(),
        ComputeRiskMetricsTool(),
        OptimizePortfolioTool(),
    ]
