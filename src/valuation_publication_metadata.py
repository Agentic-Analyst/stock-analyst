"""Attach the deterministic publication decision to a computed model artifact.

The workbook deliberately retains raw scenario arithmetic for audit.  A model-
only run has no report header, however, so downstream services otherwise cannot
tell an auditable midpoint from a publishable fair value.  This compact block is
the machine-readable equivalent of the report's publication boundary.
"""
from __future__ import annotations

import math
from typing import Any, Dict, Optional


SCHEMA_VERSION = 1


def _finite(value: Any, *, positive: bool = False) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or (positive and number <= 0):
        return None
    return number


def build_publication_metadata(
    computed_values: Dict[str, Any],
    financial_data: Dict[str, Any],
    *,
    assumptions: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Reapply the common report boundary and return a bounded public summary."""
    from src.agents.fm.bank_valuation import build_bank_valuation_override
    from src.report_agent import (
        apply_valuation_override,
        enforce_valuation_publication_boundary,
        extract_company_overview,
        extract_projections,
        extract_valuation,
    )

    assumptions = assumptions if isinstance(assumptions, dict) else {}
    persisted_model_inputs = (
        ((computed_values or {}).get("_vynn") or {}).get("model_inputs") or {}
    )
    model_inputs = {
        **assumptions,
        **(persisted_model_inputs if isinstance(persisted_model_inputs, dict) else {}),
    }
    data = {
        "company_overview": extract_company_overview(financial_data or {}),
        "projections": extract_projections(computed_values or {}),
        "valuation": extract_valuation(computed_values or {}),
        # Publication runs before `_vynn` is attached during a fresh model
        # build. Carry the grounded assumptions into the common boundary so a
        # rolling NTM model is never compared with unaligned fiscal-year Street
        # rows merely because the sidecar metadata has not been written yet.
        "model_inputs": model_inputs,
    }
    bank_override = build_bank_valuation_override(
        financial_data or {},
        terminal_growth=assumptions.get("terminal_growth_rate"),
        capm=assumptions.get("capm"),
    )
    if bank_override:
        data = apply_valuation_override(data, bank_override)
    data = enforce_valuation_publication_boundary(data, financial_data or {})

    valuation = data.get("valuation") or {}
    summary = valuation.get("summary") or {}
    reliability = valuation.get("reliability") or {}
    withheld = bool(reliability.get("point_estimate_withheld"))
    # A finite non-positive DCF can be a legitimate *audit* result for a
    # pre-cash-flow company.  It must never become a published target, but it
    # is not an internal metadata failure either.  Keeping these states
    # separate matters operationally: ``status=error`` means the publication
    # policy itself did not run, whereas ``status=ready`` plus ``withheld``
    # means it ran and deliberately rejected the model conclusion.
    model_value = _finite(summary.get("average_intrinsic"))
    positive_model_value = (
        model_value if model_value is not None and model_value > 0 else None
    )
    if not withheld and positive_model_value is None:
        # Defensive backstop.  The common boundary should already withhold
        # this case, but metadata must never grant permission on malformed or
        # non-positive arithmetic if that invariant regresses.
        withheld = True
    canonical_value = None if withheld else positive_model_value
    canonical_upside = (
        None if withheld else _finite(summary.get("upside"))
    )
    bank_inputs = ((valuation.get("bank") or {}).get("inputs") or {})
    method_values_for_audit = {}
    for name, raw in (reliability.get("legs") or {}).items():
        value = _finite(raw)
        if value is not None:
            method_values_for_audit[str(name)[:80]] = value
    failed_method_values = {
        name: value for name, value in method_values_for_audit.items()
        if value <= 0
    }
    from src.external_expectations import (
        implied_fcf_path_scale_for_enterprise_value,
    )
    market_path = implied_fcf_path_scale_for_enterprise_value(
        (valuation.get("reverse_dcf") or {}).get("market_enterprise_value"),
        model_enterprise_value=(valuation.get("dcf_perpetual") or {}).get(
            "enterprise_value"
        ),
    )
    path_delta = market_path.get("implied_fcf_path_vs_model")
    extreme_scope_gap = bool(
        withheld and isinstance(path_delta, (int, float))
        and not isinstance(path_delta, bool) and path_delta + 1 >= 3.0
    )
    method_inputs = None
    if valuation.get("bank"):
        method_inputs = {
            "book_value_per_share": _finite(bank_inputs.get("bvps"), positive=True),
            "return_on_equity": _finite(bank_inputs.get("roe")),
            "beta": _finite(bank_inputs.get("beta"), positive=True),
            "cost_of_equity": _finite(bank_inputs.get("cost_of_equity"), positive=True),
            "terminal_growth": _finite(bank_inputs.get("terminal_growth")),
            "justified_price_to_book": _finite(
                bank_inputs.get("justified_pb"), positive=True),
            "raw_justified_price_to_book": _finite(
                bank_inputs.get("raw_justified_pb"), positive=True),
            "intrinsic_fair_value": _finite(
                bank_inputs.get("intrinsic_fair_value"), positive=True),
            "forward_consensus_fair_value": _finite(
                bank_inputs.get("forward_consensus_fair_value"), positive=True),
            "forward_consensus_return_on_equity": _finite(
                bank_inputs.get("forward_consensus_roe")),
            "forward_consensus_justified_price_to_book": _finite(
                bank_inputs.get("forward_consensus_justified_pb"), positive=True),
            "forward_consensus_return_on_equity_source": (
                str(bank_inputs.get("forward_consensus_roe_source"))[:500]
                if bank_inputs.get("forward_consensus_roe_source") else None
            ),
            "forward_consensus_return_on_equity_status": (
                str(bank_inputs.get("forward_consensus_roe_status"))[:50]
                if bank_inputs.get("forward_consensus_roe_status") else None
            ),
            "peer_fair_value": _finite(
                bank_inputs.get("peer_fair_value"), positive=True),
            "peer_implied_price_to_book": _finite(
                bank_inputs.get("peer_implied_price_to_book"), positive=True),
            "peer_observation_count": _finite(
                bank_inputs.get("peer_observation_count")),
            "peer_subject_return_on_equity": _finite(
                bank_inputs.get("peer_subject_return_on_equity")),
            "peer_subject_return_on_equity_source": (
                str(bank_inputs.get("peer_subject_return_on_equity_source"))[:500]
                if bank_inputs.get("peer_subject_return_on_equity_source") else None
            ),
            "cost_of_equity_clamped": bool(
                bank_inputs.get("cost_of_equity_clamped")),
            "price_to_book_clamped": bool(
                bank_inputs.get("price_to_book_clamped")),
            "input_boundary_triggered": bool(
                bank_inputs.get("input_boundary_triggered")),
            "book_value_cross_check_failed": bool(
                bank_inputs.get("book_value_cross_check_failed")),
            "book_value_provider_gap": _finite(
                bank_inputs.get("book_value_provider_gap")),
            "cost_of_equity_source": (
                str(bank_inputs.get("cost_of_equity_source"))[:500]
                if bank_inputs.get("cost_of_equity_source") else None
            ),
            "book_value_per_share_source": (
                str(bank_inputs.get("book_value_per_share_source"))[:500]
                if bank_inputs.get("book_value_per_share_source") else None
            ),
            "return_on_equity_source": (
                str(bank_inputs.get("return_on_equity_source"))[:500]
                if bank_inputs.get("return_on_equity_source") else None
            ),
            "peer_method": (
                str(bank_inputs.get("peer_method"))[:500]
                if bank_inputs.get("peer_method") else None
            ),
        }
    range_low = _finite(reliability.get("range_low"), positive=True)
    range_high = _finite(reliability.get("range_high"), positive=True)
    support_shape = (
        "single_estimate"
        if range_low is not None and range_high is not None
        and round(range_low, 2) == round(range_high, 2)
        else "range" if range_low is not None and range_high is not None
        else "unavailable"
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "ready",
        "valuation_method": (
            "justified_pb_roe" if valuation.get("bank") else
            ((reliability.get("method_suitability") or {}).get("primary_method") or "dcf")
        ),
        "publication_allowed": not withheld,
        "point_estimate_withheld": withheld,
        "valuation_conclusion": (
            "inconclusive" if withheld else "published_point_estimate"
        ),
        "withheld_reason": reliability.get("withheld_reason") or (
            "No finite positive intrinsic-value output was produced; the "
            "model remains an audit scenario and cannot support a point "
            "conclusion."
            if withheld else None
        ),
        "valuation_confidence": reliability.get("band"),
        "valuation_method_inputs": method_inputs,
        "range_low": range_low,
        "range_high": range_high,
        "support_shape": support_shape,
        "method_values_for_audit": method_values_for_audit,
        "failed_method_values": failed_method_values,
        "canonical_fair_value": canonical_value,
        "canonical_upside_vs_market": canonical_upside,
        "model_value_for_audit": model_value,
        "market_implied_fcf_path_vs_model": path_delta,
        "model_scope": (
            "bank_balance_sheet_valuation" if valuation.get("bank") else
            "modeled_operating_cash_flow_path_only"
            if extreme_scope_gap else "corporate_dcf"
        ),
        "model_scope_warning": (
            "The observed market enterprise value requires at least three times "
            "the modeled free-cash-flow path. Method outputs value only the modeled "
            "operating cash-flow path, not a comprehensive company value, until "
            "the missing expectations are explicitly reconciled."
            if extreme_scope_gap else None
        ),
        "workbook_headline_value": _finite(
            summary.get("workbook_headline_value"), positive=True),
        "comps_included_in_blended_value": bool(
            summary.get("comps_included_in_blended_value")
        ) if not valuation.get("bank") else False,
    }


def fail_closed_publication_metadata(error: Exception) -> Dict[str, Any]:
    """Never let a metadata-generation failure turn into permission to publish."""
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "error",
        "error_type": type(error).__name__,
        "valuation_method": None,
        "publication_allowed": False,
        "point_estimate_withheld": True,
        "valuation_conclusion": "inconclusive",
        "withheld_reason": (
            "The deterministic valuation publication check did not complete; "
            "the model remains available for audit but no point fair value may be published."
        ),
        "valuation_confidence": None,
        "valuation_method_inputs": None,
        "range_low": None,
        "range_high": None,
        "support_shape": "unavailable",
        "method_values_for_audit": {},
        "failed_method_values": {},
        "canonical_fair_value": None,
        "canonical_upside_vs_market": None,
        "model_value_for_audit": None,
        "market_implied_fcf_path_vs_model": None,
        "model_scope": None,
        "model_scope_warning": None,
        "workbook_headline_value": None,
        "comps_included_in_blended_value": False,
    }
