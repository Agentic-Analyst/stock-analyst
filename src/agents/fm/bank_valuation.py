"""
bank_valuation.py — sector-appropriate valuation for financials.

A standard FCF DCF is structurally unfit for banks and other balance-sheet
businesses: deposit/loan flows swamp "free cash flow", so the model produces
negative or absurd fair values (FBP and JPM both shipped "valuation not
meaningful" to real users). The finance-standard alternative is a Gordon-style
justified P/B on book value:

    justified P/B = (ROE - g) / (r - g)
    fair value    = justified P/B x book value per share

with r = cost of equity (CAPM: risk-free + beta x equity risk premium) and
g = terminal growth. All inputs are already in the financials JSON the
pipeline scrapes (yfinance bookValue is per-share, returnOnEquity, beta).

Kept as its own module so both model_generation_agent and the chat tools can
import it without cycles.
"""

from __future__ import annotations

from typing import Optional

# CAPM parameters: ~10y risk-free plus a standard equity risk premium. The
# cost of equity is clamped to a sane band so a broken beta can't produce a
# silly discount rate.
_RISK_FREE = 0.043
_EQUITY_RISK_PREMIUM = 0.05
_COST_OF_EQUITY_MIN = 0.08
_COST_OF_EQUITY_MAX = 0.14

# Justified P/B clamp: bounds the damage from distorted ROE (one-offs,
# negative equity) and from roe < g edge cases.
_PB_MIN = 0.4
_PB_MAX = 3.0

_FINANCIAL_INDUSTRY_HINTS = (
    "bank", "insurance", "capital markets", "credit services", "financial",
)


def is_financial_sector(sector: Optional[str], industry: Optional[str] = None) -> bool:
    """True when yfinance classifies the company as a financial."""
    if (sector or "").strip().lower() == "financial services":
        return True
    ind = (industry or "").strip().lower()
    return any(h in ind for h in _FINANCIAL_INDUSTRY_HINTS)


def compute_bank_fair_value(
    company_data: dict,
    terminal_growth: Optional[float] = None,
) -> Optional[dict]:
    """
    Justified P/B x ROE fair value from the scraped company_data block.

    Returns a dict with fair_value, upside_vs_market (FRACTION — downstream
    multiplies by 100), method label, and the inputs used — or None when the
    required fields are missing/unusable (caller keeps the DCF behavior).
    """
    try:
        vm = company_data.get("valuation_metrics", {}) or {}
        gp = company_data.get("growth_profitability", {}) or {}
        md = company_data.get("market_data", {}) or {}
        cs = company_data.get("capital_structure", {}) or {}

        bvps = vm.get("book_value")
        roe = gp.get("return_on_equity")
        price = md.get("current_price")
        beta = cs.get("beta")

        if not bvps or bvps <= 0 or roe is None:
            return None

        beta = float(beta) if beta else 1.0
        g = min(terminal_growth if terminal_growth is not None else 0.025, 0.03)
        r = _RISK_FREE + beta * _EQUITY_RISK_PREMIUM
        r = max(_COST_OF_EQUITY_MIN, min(_COST_OF_EQUITY_MAX, r))

        justified_pb = (float(roe) - g) / (r - g)
        justified_pb = max(_PB_MIN, min(_PB_MAX, justified_pb))

        fair_value = round(justified_pb * float(bvps), 2)
        upside = (fair_value / float(price) - 1.0) if price else None

        return {
            "fair_value": fair_value,
            "upside_vs_market": upside,
            "method": "justified_pb_roe",
            "inputs": {
                "bvps": float(bvps),
                "roe": float(roe),
                "beta": beta,
                "cost_of_equity": r,
                "terminal_growth": g,
                "justified_pb": justified_pb,
            },
        }
    except Exception:
        return None
