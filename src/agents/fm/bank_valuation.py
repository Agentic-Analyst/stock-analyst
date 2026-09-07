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

# Book value is the right anchor for a BALANCE-SHEET business — banks and
# insurers, whose assets are financial and marked. It is the wrong anchor for
# payments, fintech, exchanges and asset managers, whose value is in intangibles
# and fee streams. "credit services" and the bare word "financial" pulled PayPal
# into a justified P/B x ROE valuation ($61.01) while its report ran a DCF
# ($87.11), and the chat told the user a DCF "was not used".
_FINANCIAL_INDUSTRY_HINTS = (
    "bank", "insurance", "capital markets", "credit services", "financial",
)
# Interest income at or above this share of revenue marks a balance-sheet
# lender. Measured: Capital One 1.22, Synchrony 2.28, Ally 1.71, Bajaj Finance
# 1.56, banks >= 1.0, Amex 0.36, Schwab 0.60 — against PayPal 0.02, Visa -0.01,
# Mastercard -0.02, Coinbase -0.01.
_LENDER_INTEREST_SHARE = 0.30


def is_financial_sector(sector: Optional[str], industry: Optional[str] = None,
                        interest_income_to_revenue: Optional[float] = None) -> bool:
    """
    True for a balance-sheet financial, where a justified P/B x ROE valuation
    is meaningful.

    Yahoo files lenders and payment processors in the same "Credit Services"
    industry, so the taxonomy alone cannot decide: PayPal ($61.01 on P/B x ROE
    against an $87.11 DCF) was the cost of trusting it. When the income
    statement is available the interest-income share decides. When it is not,
    the industry hints decide, exactly as before — narrowing them was itself a
    regression that would have sent Capital One, Synchrony, Ally and Bajaj
    Finance through an FCF DCF.
    """
    financial = (sector or "").strip().lower() == "financial services"
    ind = (industry or "").strip().lower()
    hinted = financial or any(h in ind for h in _FINANCIAL_INDUSTRY_HINTS)
    if not hinted:
        return False
    if isinstance(interest_income_to_revenue, (int, float)):
        return interest_income_to_revenue >= _LENDER_INTEREST_SHARE
    return True


def compute_bank_fair_value(
    company_data: dict,
    terminal_growth: Optional[float] = None,
    capm: Optional[dict] = None,
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
        # One cost of capital per run: when the CAPM build is available the
        # bank's cost of equity is its risk-free rate, its home-index beta and
        # its premium — the same numbers the report's Cost of Capital table
        # prints — rather than a 4.3% + beta x 5% shortcut nothing else uses.
        rf, erp = _RISK_FREE, _EQUITY_RISK_PREMIUM
        source = "4.3% + beta x 5% (no CAPM build available)"
        if isinstance(capm, dict) and isinstance(capm.get("risk_free_rate"), (int, float)) \
                and isinstance(capm.get("equity_risk_premium_total"), (int, float)):
            rf, erp = float(capm["risk_free_rate"]), float(capm["equity_risk_premium_total"])
            if isinstance(capm.get("beta"), (int, float)) and capm["beta"] > 0:
                beta = float(capm["beta"])
            source = f"Rf {rf*100:.2f}% + beta {beta:.2f} x ERP {erp*100:.2f}% (CAPM build)"
        r = rf + beta * erp
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
                "cost_of_equity_source": source,
                "terminal_growth": g,
                "justified_pb": justified_pb,
            },
        }
    except Exception:
        return None
