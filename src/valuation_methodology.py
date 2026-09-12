"""Deterministic valuation-method selection and suitability checks.

The model may still calculate audit scenarios for every operating company, but
this module decides whether those scenarios are suitable for a publishable
point estimate. It never invents a substitute method when the data required by
that method is absent.
"""
from __future__ import annotations

import math
from typing import Any, Dict, Iterable, Optional

from src.agents.fm.bank_valuation import build_bank_valuation_override


_FUND_TYPES = {"ETF", "MUTUALFUND", "MONEYMARKET"}
_CRYPTO_TYPES = {"CRYPTOCURRENCY", "CRYPTO"}
_CONGLOMERATE_HINTS = (
    "conglomerate", "diversified industrial", "diversified holdings",
    "multi-sector holdings",
)


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _metric(row: Dict[str, Any], names: Iterable[str]) -> Optional[float]:
    for name in names:
        value = _number((row or {}).get(name))
        if value is not None:
            return value
    return None


def _common_period_rows(data: Dict[str, Any]) -> list[tuple[str, Dict[str, Any], Dict[str, Any]]]:
    statements = (data or {}).get("financial_statements") or {}
    income = statements.get("income_statement") or {}
    cash_flow = statements.get("cash_flow") or {}
    if not isinstance(income, dict) or not isinstance(cash_flow, dict):
        return []
    periods = sorted(set(income).intersection(cash_flow), key=str, reverse=True)
    return [
        (str(period), income.get(period) or {}, cash_flow.get(period) or {})
        for period in periods
        if isinstance(income.get(period), dict) and isinstance(cash_flow.get(period), dict)
    ]


def _cash_profile(data: Dict[str, Any]) -> Dict[str, Any]:
    bridge = (data or {}).get("ttm_bridge") or {}
    rows = _common_period_rows(data)
    basis = "annual"
    period = rows[0][0] if rows else None
    income = rows[0][1] if rows else {}
    cash_flow = rows[0][2] if rows else {}
    if bridge.get("status") == "current":
        basis = "ttm"
        period = bridge.get("latest_period")
        income = bridge.get("income_statement") or {}
        cash_flow = bridge.get("cash_flow") or {}

    revenue = _metric(income, ("Total Revenue", "Operating Revenue", "Revenue"))
    operating_cf = _metric(
        cash_flow, ("Operating Cash Flow", "Total Cash From Operating Activities")
    )
    capex = _metric(cash_flow, ("Capital Expenditure", "Capital Expenditures"))
    current_fcf = (
        operating_cf + capex
        if operating_cf is not None and capex is not None else
        _metric(cash_flow, ("Free Cash Flow",))
    )

    positive_fcf_periods = 0
    for _, _, annual_cash in rows:
        ocf = _metric(
            annual_cash, ("Operating Cash Flow", "Total Cash From Operating Activities")
        )
        annual_capex = _metric(
            annual_cash, ("Capital Expenditure", "Capital Expenditures")
        )
        fcf = (
            ocf + annual_capex
            if ocf is not None and annual_capex is not None else
            _metric(annual_cash, ("Free Cash Flow",))
        )
        if fcf is not None and fcf > 0:
            positive_fcf_periods += 1

    return {
        "basis": basis,
        "period": period,
        "revenue": revenue,
        "operating_cash_flow": operating_cf,
        "free_cash_flow": current_fcf,
        "annual_common_periods": len(rows),
        "positive_fcf_periods": positive_fcf_periods,
    }


def _segment_readiness(data: Dict[str, Any], industry: str) -> Dict[str, Any]:
    candidates = (
        (data or {}).get("segment_data")
        or (((data or {}).get("company_data") or {}).get("segments"))
        or []
    )
    if isinstance(candidates, dict):
        candidates = [dict(value, name=key) if isinstance(value, dict) else {}
                      for key, value in candidates.items()]
    valid = []
    for segment in candidates if isinstance(candidates, list) else []:
        if not isinstance(segment, dict):
            continue
        revenue = _metric(segment, ("revenue", "Revenue", "segment_revenue"))
        profit = _metric(segment, (
            "operating_income", "Operating Income", "ebitda", "EBITDA",
            "segment_profit",
        ))
        multiple = _metric(segment, (
            "valuation_multiple", "ev_to_ebitda", "ev_to_sales",
        ))
        if segment.get("name") and revenue is not None and profit is not None and multiple is not None:
            valid.append(segment.get("name"))
    candidate = any(hint in (industry or "").lower() for hint in _CONGLOMERATE_HINTS)
    if len(valid) >= 2:
        return {"status": "ready", "segment_count": len(valid), "segments": valid}
    return {
        "status": "data_required" if candidate else "not_indicated",
        "segment_count": len(valid),
        "reason": (
            "A sum-of-the-parts cross-check requires at least two verified segments "
            "with segment revenue, profit, and a supported valuation multiple."
            if candidate else None
        ),
    }


def assess_valuation_methodology(financial_data: Dict[str, Any]) -> Dict[str, Any]:
    """Select the primary method and determine point-publication suitability."""
    company = (financial_data or {}).get("company_data") or {}
    basic = company.get("basic_info") or {}
    quote_type = str(basic.get("quote_type") or basic.get("quoteType") or "EQUITY").upper()
    industry = str(basic.get("industry") or "")
    sector = str(basic.get("sector") or "")
    profile = _cash_profile(financial_data or {})
    segments = _segment_readiness(financial_data or {}, industry)

    if quote_type in _FUND_TYPES:
        return {
            "primary_method": "fund_holdings_nav",
            "quality": "unsuitable",
            "publication_allowed": False,
            "reason": "A corporate free-cash-flow DCF is not valid for a fund; use holdings, NAV, fees, tracking, and factor exposure.",
            "specialized_service": "fund",
            "cash_flow_profile": profile,
            "sotp": segments,
        }
    if quote_type in _CRYPTO_TYPES:
        return {
            "primary_method": "crypto_network_or_protocol",
            "quality": "unsuitable",
            "publication_allowed": False,
            "reason": "A corporate free-cash-flow DCF is not valid for a crypto asset; use network, protocol, token-supply, and on-chain inputs.",
            "specialized_service": "crypto",
            "cash_flow_profile": profile,
            "sotp": segments,
        }

    bank = build_bank_valuation_override(financial_data or {})
    if bank:
        return {
            "primary_method": "justified_pb_roe",
            "quality": "appropriate",
            "publication_allowed": True,
            "reason": "Balance-sheet financial valued with justified P/B and ROE; corporate FCF DCF is suppressed.",
            "cash_flow_profile": profile,
            "sotp": segments,
        }

    reasons = []
    if profile["revenue"] is None or profile["revenue"] <= 0:
        reasons.append("positive current revenue is unavailable")
    if profile["operating_cash_flow"] is None:
        reasons.append("current operating cash flow is unavailable")
    elif profile["operating_cash_flow"] <= 0:
        reasons.append("current operating cash flow is non-positive")
    if profile["annual_common_periods"] < 2:
        reasons.append("fewer than two aligned annual income/cash-flow periods are available")
    if (
        profile["free_cash_flow"] is None or profile["free_cash_flow"] <= 0
    ) and profile["positive_fcf_periods"] < 2:
        reasons.append("free cash flow is not yet established across the current period or history")

    publication_allowed = not reasons
    primary = "dcf_plus_market_comps" if publication_allowed else "scenario_only"
    if segments.get("status") == "ready":
        primary = "dcf_with_sotp_inputs_available"
    elif segments.get("status") == "data_required":
        reasons.append(segments["reason"])

    return {
        "primary_method": primary,
        "quality": "appropriate" if publication_allowed else "limited",
        "publication_allowed": publication_allowed,
        "reason": (
            "Operating-company DCF is supported by positive current cash generation and aligned history."
            if publication_allowed else
            "The DCF may be shown as an auditable scenario, but no point estimate or directional rating should be published because "
            + "; ".join(reasons) + "."
        ),
        "sector": sector or None,
        "industry": industry or None,
        "cash_flow_profile": profile,
        "sotp": segments,
    }
