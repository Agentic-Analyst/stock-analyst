"""Deterministic valuation-method selection and suitability checks.

The model may still calculate audit scenarios for every operating company, but
this module decides whether those scenarios are suitable for a publishable
point estimate. It never invents a substitute method when the data required by
that method is absent.
"""
from __future__ import annotations

import math
from typing import Any, Dict, Iterable, Optional

from src.agents.fm.bank_valuation import (
    build_bank_valuation_override,
    is_balance_sheet_financial,
)


_FUND_TYPES = {"ETF", "MUTUALFUND", "MONEYMARKET"}
_CRYPTO_TYPES = {"CRYPTOCURRENCY", "CRYPTO"}
_REIT_INDUSTRY_HINTS = (
    "reit", "real estate investment trust",
)
_COMMODITY_CYCLE_INDUSTRY_HINTS = (
    "oil & gas integrated", "oil & gas e&p", "oil & gas refining",
    "oil & gas drilling", "uranium", "gold", "copper", "silver",
    "other industrial metals", "steel", "aluminum", "coking coal",
    "thermal coal",
)
_CONGLOMERATE_HINTS = (
    "conglomerate", "diversified industrial", "diversified holdings",
    "multi-sector holdings",
)
_CAPTIVE_FINANCE_SEGMENT_HINTS = (
    "financial products segment",
    "financial services segment",
    "credit segment",
)


def normalize_peer_comps_policy(peer_comps: Any) -> Dict[str, Any]:
    """Return one publication policy for current and legacy peer artifacts.

    Older saved runs predate the explicit confidence fields, but already mark
    Yahoo's broad fallback through ``grouping`` or ``peer_universe_source``.
    Missing new fields must not let cached broad peers regain a valuation vote.
    """
    peers = peer_comps if isinstance(peer_comps, dict) else {}
    broad_sector = bool(
        peers.get("grouping") == "sector_leaders"
        or peers.get("peer_universe_source") == "yahoo_sector_leaders"
        or peers.get("role") == "broad_sector_cross_check"
    )
    explicit_status = peers.get("status")
    usable = bool(peers and (explicit_status is None or explicit_status == "ready"))
    confidence = peers.get("confidence") or ("low" if broad_sector else "moderate")
    role = peers.get("role") or (
        "broad_sector_cross_check" if broad_sector
        else "comparable_company_valuation"
    )
    # A valuation vote is opt-in, never inferred. Saved artifacts from before
    # size screening carried a Finnhub ``subIndustry`` label but no confidence,
    # role, status, or explicit inclusion decision; replaying those artifacts
    # made AAPL's much smaller storage/hardware vendors look like validated
    # independent evidence. Keep legacy figures visible as context, but only a
    # current collector result with the complete policy contract can enter the
    # headline value.
    industrial_policy_complete = bool(
        explicit_status == "ready"
        and peers.get("included_in_blended_value") is True
        and peers.get("confidence") in {"moderate", "high"}
        and peers.get("role") == "comparable_company_valuation"
        and peers.get("selected_method") in {"ev_ebitda", "price_sales"}
        and peers.get("size_screen_applied") is True
        and peers.get("fundamental_screen_applied") is True
        and isinstance(peers.get("selected_peer_count"), int)
        and peers.get("selected_peer_count") >= 3
    )
    bank_policy_complete = bool(
        explicit_status == "ready"
        and peers.get("included_in_blended_value") is True
        and peers.get("confidence") in {"moderate", "high"}
        and peers.get("role") == "bank_comparable_company_valuation"
        and peers.get("selected_method") == "price_to_book"
        and peers.get("size_screen_applied") is True
        and peers.get("fundamental_screen_applied") is True
        and isinstance(peers.get("selected_peer_count"), int)
        and peers.get("selected_peer_count") >= 3
    )
    policy_complete = industrial_policy_complete or bank_policy_complete
    included = bool(usable and policy_complete and not broad_sector)
    return {
        "confidence": confidence,
        "role": role,
        "included_in_blended_value": included,
        "broad_sector": broad_sector,
        "usable": usable,
        "policy_complete": policy_complete,
    }


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
    quote_type = str(basic.get("quote_type") or basic.get("quoteType") or "UNKNOWN").upper()
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
    if quote_type != "EQUITY":
        return {
            "primary_method": "unsupported_asset_type",
            "quality": "unsuitable",
            "publication_allowed": False,
            "reason": (
                f"A corporate free-cash-flow DCF is not valid for quote type "
                f"{quote_type}; route this instrument to a verified "
                "asset-specific service before publishing a valuation."
            ),
            "specialized_service": "unsupported_asset",
            "cash_flow_profile": profile,
            "sotp": segments,
        }

    # Public REITs report operating cash flow, but corporate FCFF is not the
    # right equity-value anchor because property depreciation, recurring
    # maintenance capital, asset sales, and required distributions make FFO,
    # AFFO and NAV/cap-rate evidence materially different. Yahoo normally
    # labels these securities as EQUITY, so quote type alone cannot protect
    # the model. Until the dedicated REIT inputs exist, retain any corporate
    # DCF only as an audit scenario and withhold the point call.
    industry_key = industry.casefold()
    if any(hint in industry_key for hint in _REIT_INDUSTRY_HINTS):
        return {
            "primary_method": "reit_affo_nav",
            "quality": "unsuitable",
            "publication_allowed": False,
            "reason": (
                "A corporate free-cash-flow DCF is not a sufficient primary method "
                "for a REIT; use normalized FFO/AFFO, property-level NAV and cap "
                "rates, recurring maintenance capital, leverage, and distribution "
                "coverage."
            ),
            "specialized_service": "reit",
            "cash_flow_profile": profile,
            "sotp": segments,
        }

    if "insurance" in industry_key and "broker" not in industry_key:
        return {
            "primary_method": "insurance_book_value_embedded_value",
            "quality": "unsuitable",
            "publication_allowed": False,
            "reason": (
                "A generic corporate free-cash-flow DCF is not a sufficient primary "
                "method for an insurer. The analysis requires normalized book-value "
                "growth and ROE, reserve adequacy, underwriting profitability, float "
                "and investment-income economics, capital requirements, and—where "
                "applicable—a sum-of-the-parts valuation."
            ),
            "specialized_service": "insurance",
            "cash_flow_profile": profile,
            "sotp": segments,
        }

    if any(hint in industry_key for hint in _COMMODITY_CYCLE_INDUSTRY_HINTS):
        return {
            "primary_method": "cyclically_normalized_dcf",
            "quality": "limited",
            "publication_allowed": False,
            "reason": (
                "A current-run-rate corporate DCF is not sufficient for this "
                "commodity-cycle business. A point call requires a normalized "
                "commodity price deck, mid-cycle volumes and margins, reserve or "
                "resource life, sustaining capital, and balance-sheet stress cases."
            ),
            "specialized_service": "commodity_cycle",
            "cash_flow_profile": profile,
            "sotp": segments,
        }

    bank_applicable = is_balance_sheet_financial(financial_data or {})
    bank = build_bank_valuation_override(financial_data or {}) if bank_applicable else None
    if bank_applicable:
        if not bank:
            return {
                "primary_method": "justified_pb_roe",
                "quality": "unsuitable",
                "publication_allowed": False,
                "reason": (
                    "This balance-sheet financial requires a justified P/B and normalized-ROE "
                    "valuation, but positive common book value per share and a supportable ROE "
                    "are not both available. Corporate free-cash-flow DCF is suppressed."
                ),
                "specialized_service": "bank_valuation_input_gap",
                "cash_flow_profile": profile,
                "sotp": segments,
            }
        return {
            "primary_method": "justified_pb_roe",
            "quality": "appropriate",
            "publication_allowed": True,
            "reason": "Balance-sheet financial valued with justified P/B and ROE; corporate FCF DCF is suppressed.",
            "cash_flow_profile": profile,
            "sotp": segments,
        }

    reasons = []
    business_summary = str(
        basic.get("business_summary") or basic.get("long_business_summary") or ""
    ).casefold()
    has_captive_finance_segment = any(
        hint in business_summary for hint in _CAPTIVE_FINANCE_SEGMENT_HINTS
    ) and any(token in business_summary for token in ("financ", "lease", "credit"))
    if has_captive_finance_segment:
        # Consolidated receivables, debt and cash flow combine an operating
        # manufacturer with a leveraged lender.  Treating the finance book as
        # ordinary working capital can create a large false reinvestment charge
        # (CAT is the canonical case).  Keep the consolidated DCF as a scenario,
        # but require an operating/finance split before publication.
        reasons.append(
            "a disclosed captive-finance segment is consolidated with the operating "
            "business; a point call requires segment earnings and cash flow, finance "
            "receivables, matched funding debt, credit losses, and a reconciled "
            "operating-company plus finance-book sum-of-the-parts valuation"
        )
    listing_currency = str(basic.get("listing_currency") or "").upper()
    financial_currency = str(basic.get("currency") or "").upper()
    fx_rate = _number((company.get("market_data") or {}).get(
        "fx_listing_to_financial"
    ))
    if (
        listing_currency and financial_currency
        and listing_currency != financial_currency
        and (fx_rate is None or fx_rate <= 0)
    ):
        reasons.append(
            "listing-to-reporting currency conversion is unavailable"
        )
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

    peer_comps = (((financial_data or {}).get("industry_data") or {}).get("peer_comps") or {})
    comps_policy = normalize_peer_comps_policy(peer_comps)
    primary = "dcf_only"
    if has_captive_finance_segment:
        primary = "scenario_only_pending_operating_finance_sotp"
    elif segments.get("status") == "ready":
        # Input readiness is not the same as a completed SOTP.  Until segment
        # values, corporate costs, net debt and cross-holdings are actually
        # calculated and reconciled, a consolidated DCF cannot become the
        # point answer merely because raw segment rows exist.
        primary = "scenario_only_pending_sotp"
        reasons.append(
            "verified segment inputs exist, but a reconciled sum-of-the-parts "
            "valuation has not been completed"
        )
    elif segments.get("status") == "data_required":
        primary = "scenario_only_pending_sotp"
        reasons.append(segments["reason"])
    publication_allowed = not reasons
    if publication_allowed:
        if comps_policy["included_in_blended_value"]:
            primary = "dcf_plus_market_comps"
        elif comps_policy["usable"] and comps_policy["broad_sector"]:
            primary = "dcf_with_broad_market_cross_check"
        else:
            primary = "dcf_only"
    elif not primary.startswith("scenario_only_pending"):
        primary = "scenario_only"

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
