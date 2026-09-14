"""
Model Generation Agent Node

Builds a banker-grade DCF financial model using financial data.

This agent:
1. Finds the latest financial JSON from financial_data_agent
2. Calls create_financial_model() to build Excel model
3. Optionally evaluates formulas and saves computed values
4. Updates state.financial_model
5. Marks pipeline stage as MODEL_GENERATED
"""

from pathlib import Path
import ast
import math
from typing import Optional

from src.agents.supervisor.state import FinancialState, FinancialModel, PipelineStage, PipelineConfig
from src.agents.fm import create_financial_model


def _publication_audit_value(computed_data, fallback=None):
    """Return the arithmetic value used to recheck publication policy.

    The workbook deliberately relabels a withheld headline as a *scenario
    midpoint (not published)*.  Downstream code used to find the number by
    matching display text containing ``Fair Value``; once the safer label was
    applied, that parser concluded that no positive valuation existed and
    replaced the real withholding reason with a false one.  The sidecar's
    machine publication envelope is the canonical handoff.
    """
    internal = (computed_data.get("_vynn") or {}) if isinstance(computed_data, dict) else {}
    publication = internal.get("valuation_publication") or {}
    for candidate in (
        publication.get("model_value_for_audit"),
        publication.get("canonical_fair_value"),
        fallback,
    ):
        if (isinstance(candidate, (int, float)) and not isinstance(candidate, bool)
                and math.isfinite(float(candidate)) and float(candidate) > 0):
            return float(candidate)
    return None


def _valuation_log_summary(metrics):
    """Name an unpublished midpoint as audit arithmetic, never fair value."""
    metrics = metrics or {}

    def display(value, *, percent=False):
        if (isinstance(value, (int, float)) and not isinstance(value, bool)
                and math.isfinite(float(value))):
            return (
                f"{float(value) * 100:.1f}%" if percent else f"{float(value):.2f}"
            )
        return "N/A"

    current = display(metrics.get("current_price"))
    if metrics.get("point_estimate_withheld"):
        return (
            "📊 Extracted valuation: "
            f"Audit midpoint={display(metrics.get('fair_value'))}, "
            f"Current={current}, Point estimate=WITHHELD, Upside=WITHHELD"
        )
    return (
        "📊 Extracted valuation: "
        f"Fair Value={display(metrics.get('fair_value'))}, Current={current}, "
        f"Upside={display(metrics.get('upside_vs_market'), percent=True)}"
    )


def _merge_machine_publication_boundary(valuation_metrics, computed_data):
    """Make the durable workbook boundary authoritative for model-only chat.

    The builder evaluates the complete report publication policy, including
    forecast/profitability reconciliation.  Reconstructing only part of that
    policy in this agent could make ``build_model`` publish a value that the
    subsequently generated report correctly withheld.  A stricter in-memory
    decision is retained; a machine denial can never be loosened here.
    """
    metrics = dict(valuation_metrics or {})
    internal = (computed_data.get("_vynn") or {}) if isinstance(computed_data, dict) else {}
    publication = internal.get("valuation_publication") or {}
    ready = publication.get("status") == "ready"
    allowed = publication.get("publication_allowed") is True
    manifest_withheld = bool(publication.get("point_estimate_withheld"))
    metrics["stored_publication_status"] = publication.get("status") or "missing"
    # Copy the machine contract, not only its deny bit. Downstream chat/report
    # paths need the same method range, scope warning, and audit-vs-published
    # distinction that the downloadable workbook carries. Reconstructing these
    # fields from display labels is both lossy and a source of drift.
    handoff_fields = {
        "publication_allowed": "publication_allowed",
        "valuation_method": "valuation_method",
        "valuation_conclusion": "valuation_conclusion",
        "range_low": "publication_range_low",
        "range_high": "publication_range_high",
        "method_values_for_audit": "method_values_for_audit",
        "failed_method_values": "failed_method_values",
        "model_value_for_audit": "model_value_for_audit",
        "canonical_fair_value": "canonical_fair_value",
        "canonical_upside_vs_market": "canonical_upside_vs_market",
        "market_implied_fcf_path_vs_model": "market_implied_fcf_path_vs_model",
        "model_scope": "model_scope",
        "model_scope_warning": "model_scope_warning",
        "comps_included_in_blended_value": "comps_included_in_blended_value",
    }
    for source_key, destination_key in handoff_fields.items():
        if source_key in publication:
            metrics[destination_key] = publication.get(source_key)
    # Display labels are deliberately free to change as the workbook becomes
    # clearer.  Once publication is allowed, restore the public upside from
    # the machine contract instead of relying on a fragile Summary-cell label.
    # Without this assignment the full report eventually recomputes the value,
    # but the model-only chat path and the generation log incorrectly see N/A.
    canonical_upside = publication.get("canonical_upside_vs_market")
    if (ready and allowed and not manifest_withheld
            and isinstance(canonical_upside, (int, float))
            and not isinstance(canonical_upside, bool)
            and math.isfinite(float(canonical_upside))):
        metrics["upside_vs_market"] = float(canonical_upside)
    if not ready or not allowed or manifest_withheld:
        metrics["point_estimate_withheld"] = True
        manifest_reason = publication.get("withheld_reason") if ready else None
        if not manifest_reason:
            manifest_reason = (
                "The model's machine-readable publication decision is missing or "
                "incomplete; the workbook remains available only as an audit scenario."
            )
        existing = str(metrics.get("publication_withheld_reason") or "").strip()
        if not existing:
            metrics["publication_withheld_reason"] = manifest_reason
        elif manifest_reason not in existing and existing not in manifest_reason:
            metrics["publication_withheld_reason"] = f"{existing} {manifest_reason}"
        metrics["valuation_conclusion"] = "inconclusive"
    confidence = publication.get("valuation_confidence")
    if confidence and not metrics.get("dispersion_band"):
        metrics["dispersion_band"] = confidence
    return metrics


async def model_generation_agent(
    state: FinancialState,
    config: Optional[PipelineConfig] = None
) -> FinancialState:
    """
    Generate a banker-grade DCF financial model.
    
    This agent:
    - Reads: state.ticker, state.analysis_path, state.logger
    - Executes: Financial model generation with deterministic, source-grounded assumptions
    - Updates: state.financial_model, state.current_stage
    - Returns: Updated FinancialState with model generated
    
    Args:
        state: Current FinancialState (must have financial_data collected)
        config: Optional PipelineConfig for parameters
        
    Returns:
        Updated FinancialState with financial model generated
    """
    try:
        state.log_action(
            "model_generation_agent",
            f"Starting financial model generation for {state.ticker}..."
        )
        
        # Use effective logger from state
        effective_logger = state.get_effective_logger("model_generation_agent")
        
        # Validate prerequisites
        if not state.financial_data:
            state.log_error(
                "model_generation_agent",
                "Prerequisites not met: financial_data not collected"
            )
            state.current_stage = PipelineStage.FAILED
            return state

        raw_financials = state.financial_data.raw_data or {}
        from src.valuation_methodology import assess_valuation_methodology
        initial_suitability = assess_valuation_methodology(raw_financials)
        if initial_suitability.get("specialized_service"):
            reason = initial_suitability.get("reason") or (
                "This instrument requires a specialized valuation service."
            )
            state.log_error("model_generation_agent", reason)
            state.current_stage = PipelineStage.FAILED
            return state
        
        # Use state's analysis_path directly
        analysis_path = Path(state.analysis_path) if isinstance(state.analysis_path, str) else state.analysis_path
        json_file = analysis_path / "financials" / "financials_annual_modeling_latest.json"
        
        if not json_file.exists():
            state.log_error(
                "model_generation_agent",
                f"Financial data file not found: {json_file}"
            )
            state.current_stage = PipelineStage.FAILED
            return state
        
        state.log_action("model_generation_agent", f"Found financial data: {json_file.name}")
        
        # Create output paths
        models_dir = analysis_path / "models"
        models_dir.mkdir(parents=True, exist_ok=True)
        
        output_file = models_dir / f"{state.ticker}_financial_model.xlsx"
        json_output_path = models_dir / f"{state.ticker}_financial_model_computed_values.json"
        
        state.log_action(
            "model_generation_agent",
            "Building banker-grade DCF model with source-grounded assumptions..."
        )
        
        # Build the financial model
        try:
            builder = create_financial_model(
                ticker=state.ticker,
                json_path=str(json_file),
                output_path=str(output_file),
                logger=effective_logger
            )
            
            state.log_action(
                "model_generation_agent",
                f"✅ Excel model generated successfully"
            )
            
            # create_financial_model already evaluates and saves this artifact
            # exactly once. A second pass doubled latency and could overwrite
            # the publication metadata attached by the first pass.
            if json_output_path.is_file() and json_output_path.stat().st_size > 0:
                state.log_action(
                    "model_generation_agent",
                    f"✅ Computed values JSON saved: {json_output_path.name}"
                )
                computed_values_path = str(json_output_path)
            else:
                raise RuntimeError("Computed values artifact was not created")
            
        except Exception as model_error:
            state.log_error("model_generation_agent", f"Model generation failed: {str(model_error)}")
            state.current_stage = PipelineStage.FAILED
            return state
        
        # The grounded cost-of-capital build, so the bank valuation and the
        # terminal-value reconciliation use the same numbers the workbook did.
        _grounded = getattr(builder, "llm_assumptions", None) or {}
        _capm = _grounded.get("capm") or {}
        # Extract valuation metrics from computed values JSON
        valuation_metrics = {}
        assumptions = {}
        if computed_values_path and Path(computed_values_path).exists():
            try:
                import json
                with open(computed_values_path, 'r') as f:
                    computed_data = json.load(f)
                integrity = ((computed_data.get("_vynn") or {}).get(
                    "formula_integrity") or {})
                if integrity and integrity.get("status") != "ready":
                    raise RuntimeError(
                        "The workbook contains failed formulas and cannot support "
                        "a report or recommendation."
                    )
                semantic_integrity = ((computed_data.get("_vynn") or {}).get(
                    "model_integrity") or {})
                if semantic_integrity and semantic_integrity.get("status") != "ready":
                    raise RuntimeError(
                        "The workbook failed accounting or valuation identity checks "
                        "and cannot support a report or recommendation."
                    )
                reinvestment_sensitivity = (
                    (computed_data.get("_vynn") or {}).get(
                        "reinvestment_sensitivity") or {}
                )
                if isinstance(reinvestment_sensitivity, dict):
                    valuation_metrics["reinvestment_sensitivity"] = (
                        reinvestment_sensitivity
                    )
                
                # Extract Summary tab data
                summary_cells = computed_data.get("Summary", {}).get("cells", {})
                
                # Extract key valuation metrics
                current_price = None
                perpetual_price = None
                exit_multiple_price = None
                comps_price = None
                average_price = None
                upside_vs_market = None
                wacc = None
                terminal_growth = None
                exit_multiple = None
                ebitda_terminal = None
                fcf_terminal = None
                market_implied_terminal_fcf = None
                market_implied_vs_model = None
                revenue_growth_by_column = {}
                model_revenue_by_column = {}
                
                for cell_key, cell_value in summary_cells.items():
                    # Get the corresponding label from one cell to the left
                    try:
                        parsed = ast.literal_eval(cell_key)
                    except (ValueError, SyntaxError):
                        continue
                    if (not isinstance(parsed, tuple) or len(parsed) != 2
                            or not all(isinstance(value, int) for value in parsed)):
                        continue
                    row, col = parsed
                    label_key = f"({row}, 1)"
                    label = summary_cells.get(label_key, "")
                    
                    if isinstance(label, str):
                        if "Current Market Price" in label and col == 2:
                            current_price = cell_value
                        elif "Value per Share (Perpetual DCF)" in label and col == 2:
                            perpetual_price = cell_value
                        elif "Value per Share (Exit Multiple DCF)" in label and col == 2:
                            exit_multiple_price = cell_value
                        elif "Value per Share (Market Comps)" in label and col == 2:
                            # The present-valued market methodology used beside
                            # the single DCF view in the headline blend.
                            comps_price = cell_value
                        elif ("DCF Fair Value (Per-Share)" in label or
                              "Blended Fair Value (Per-Share)" in label or
                              "Average of Methods (Per-Share)" in label) and col == 2:
                            # Accept the old label when reading historical
                            # workbooks, while new runs use the accurate name.
                            average_price = cell_value
                        elif "Upside vs Market" in label and col == 2:
                            upside_vs_market = cell_value
                        elif "WACC (Perpetual DCF)" in label and col == 2:
                            wacc = cell_value
                        elif "Terminal Growth g" in label and col == 2:
                            terminal_growth = cell_value
                        elif "Exit Multiple (EV/EBITDA)" in label and col == 2:
                            exit_multiple = cell_value
                        elif label.strip().startswith("EBITDA (FY") and col == 2:
                            ebitda_terminal = cell_value
                        elif label.strip().startswith("FCF (FY") and col == 2:
                            fcf_terminal = cell_value
                        elif "Market-Implied Terminal FCF" in label and col == 2:
                            market_implied_terminal_fcf = cell_value
                        elif "Market-Implied FCF vs Model" in label and col == 2:
                            market_implied_vs_model = cell_value

                # Publication labels are presentation, not an interchange
                # schema.  Recover the auditable midpoint from the immutable
                # machine envelope so a correctly withheld workbook does not
                # turn into a false "no positive value" result downstream.
                average_price = _publication_audit_value(
                    computed_data, fallback=average_price,
                )
                
                # Extract revenue growth rates from the grounded input tab. Keep the
                # column index until the end: JSON object order is not a model
                # contract, and appending in iteration order can relabel FY3 as
                # FY1 in the user-facing summary.
                model_input_cells = (
                    computed_data.get("Model_Inputs", {}).get("cells", {})
                    or computed_data.get("LLM_Inferred", {}).get("cells", {})
                )
                for cell_key, cell_value in model_input_cells.items():
                    try:
                        parsed = ast.literal_eval(cell_key)
                    except (ValueError, SyntaxError):
                        continue
                    if (not isinstance(parsed, tuple) or len(parsed) != 2
                            or not all(isinstance(value, int) for value in parsed)):
                        continue
                    row, col = parsed
                    label_key = f"({row}, 1)"
                    label = model_input_cells.get(label_key, "")
                    
                    if isinstance(label, str) and "Revenue Growth Rate" in label:
                        # Collect FY1-FY5 growth rates (columns 2-6)
                        if (2 <= col <= 6 and isinstance(cell_value, (int, float))
                                and not isinstance(cell_value, bool)
                                and math.isfinite(float(cell_value))):
                            revenue_growth_by_column[col] = float(cell_value)

                # Preserve the actual model revenue forecast in state so the
                # final chat answer can compare FY1/FY2 directly with human
                # analyst estimates instead of mentioning consensus as an
                # unrelated footnote.
                projection_cells = computed_data.get("Projections", {}).get("cells", {})
                revenue_rows = set()
                for cell_key, label in projection_cells.items():
                    try:
                        parsed = ast.literal_eval(cell_key)
                    except (ValueError, SyntaxError):
                        continue
                    if (isinstance(parsed, tuple) and len(parsed) == 2
                            and all(isinstance(value, int) for value in parsed)
                            and parsed[1] == 1 and isinstance(label, str)
                            and label.strip().casefold() == "revenue"):
                        revenue_rows.add(parsed[0])
                for row in sorted(revenue_rows):
                    for col in range(2, 7):
                        value = projection_cells.get(f"({row}, {col})")
                        if (isinstance(value, (int, float)) and not isinstance(value, bool)
                                and math.isfinite(float(value)) and float(value) > 0):
                            model_revenue_by_column[col] = float(value)
                    if model_revenue_by_column:
                        break

                revenue_growth_rates = [
                    revenue_growth_by_column[col]
                    for col in sorted(revenue_growth_by_column)
                ]
                
                # Populate valuation_metrics dictionary
                if average_price is not None:
                    valuation_metrics["fair_value"] = average_price
                if perpetual_price is not None:
                    valuation_metrics["perpetual_price"] = perpetual_price
                if exit_multiple_price is not None:
                    valuation_metrics["exit_multiple_price"] = exit_multiple_price
                if comps_price is not None:
                    valuation_metrics["comps_price"] = comps_price
                if current_price is not None:
                    valuation_metrics["current_price"] = current_price
                if upside_vs_market is not None:
                    valuation_metrics["upside_vs_market"] = upside_vs_market
                if market_implied_terminal_fcf is not None:
                    valuation_metrics["market_implied_terminal_fcf"] = market_implied_terminal_fcf
                if market_implied_vs_model is not None:
                    valuation_metrics["market_implied_fcf_vs_model"] = market_implied_vs_model
                # Consensus remains outside intrinsic value, but its coverage
                # and target are needed by the publication boundary.  A large
                # mega-cap DCF gap that independent evidence does not support
                # must not become a precise rating merely because the workbook
                # arithmetic completed.
                if isinstance(_grounded.get("analyst_target_mean"), (int, float)):
                    valuation_metrics["analyst_target"] = _grounded["analyst_target_mean"]
                if isinstance(_grounded.get("analyst_count"), (int, float)):
                    valuation_metrics["analyst_count"] = int(_grounded["analyst_count"])
                
                # Populate assumptions dictionary
                if wacc is not None:
                    assumptions["wacc"] = wacc
                if terminal_growth is not None:
                    assumptions["terminal_growth"] = terminal_growth
                if isinstance(_capm.get("risk_free_rate"), (int, float)):
                    assumptions["risk_free_rate"] = _capm["risk_free_rate"]
                    assumptions["currency"] = _capm.get("currency")
                if exit_multiple is not None:
                    assumptions["exit_multiple"] = exit_multiple
                # Terminal-year cash flows. Terminal value dominates both
                # valuation legs, and these two figures are what let the
                # perpetuity assumption and the exit multiple be checked
                # against each other (see fm/terminal_value.py) instead of
                # silently contradicting each other inside an average.
                if fcf_terminal is not None:
                    assumptions["fcf_terminal"] = fcf_terminal
                if ebitda_terminal is not None:
                    assumptions["ebitda_terminal"] = ebitda_terminal
                if revenue_growth_rates:
                    assumptions["revenue_growth_rates"] = revenue_growth_rates
                if isinstance(_grounded.get("revenue_growth_source"), str):
                    assumptions["revenue_growth_source"] = _grounded[
                        "revenue_growth_source"
                    ]
                if isinstance(_grounded.get("forecast_basis"), dict):
                    forecast_basis = dict(_grounded["forecast_basis"])
                    assumptions["forecast_basis"] = forecast_basis
                    valuation_metrics["forecast_basis"] = forecast_basis
                if model_revenue_by_column:
                    valuation_metrics["model_revenue_forecast"] = [
                        model_revenue_by_column[col]
                        for col in sorted(model_revenue_by_column)
                    ]
                
                # Do the legs actually agree?
                #
                # This check existed only in the generalist agent's build_model
                # tool, so the SUPERVISOR path — the one that writes full
                # analyst reports — shipped blended fair values with no idea how
                # far its methods diverged. A real user asked for an ASTS DCF
                # and got "DCF fair value from the model: $31.78" when BOTH DCF
                # legs had returned negative per-share values (-$17.64 and
                # -$6.98) and $31.78 was the market-comps leg alone. The number
                # presented as a DCF was not one.
                try:
                    from src.agents.tools.analysis_tools import (
                        _megacap_threshold,
                        valuation_dispersion,
                        valuation_publication_boundary,
                    )
                    raw = state.financial_data.raw_data or {}
                    # Put the licensed/public human target on the same economic
                    # footing as the DCF.  This does not calibrate intrinsic
                    # value to consensus; it quantifies the terminal cash flow
                    # embedded in the external target while holding our explicit
                    # forecast, discounting and terminal-growth convention fixed.
                    try:
                        from src.external_expectations import (
                            implied_discount_rate_for_enterprise_value,
                            implied_fcf_path_scale_for_enterprise_value,
                            implied_terminal_growth_for_enterprise_value,
                            implied_terminal_fcf_for_enterprise_value,
                        )
                        target_ev = (((raw.get("external_expectations") or {}).get(
                            "valuation_cross_check") or {}).get(
                                "target_implied_enterprise_value"))
                        dcf_cells = (computed_data.get("Valuation (DCF)", {}) or {}).get(
                            "cells", {})
                        target_reverse = implied_terminal_fcf_for_enterprise_value(
                            target_ev,
                            pv_explicit_fcf=dcf_cells.get("(19, 2)"),
                            pv_terminal_value=dcf_cells.get("(26, 2)"),
                            model_terminal_fcf=dcf_cells.get("(24, 2)"),
                        )
                        if target_reverse.get("available"):
                            valuation_metrics.update({
                                "analyst_target_implied_terminal_fcf":
                                    target_reverse["implied_terminal_fcf"],
                                "analyst_target_implied_fcf_vs_model":
                                    target_reverse["implied_fcf_vs_model"],
                            })
                        model_ev = dcf_cells.get("(27, 2)")
                        market_ev = ((computed_data.get("Summary", {}) or {}).get(
                            "cells", {}) or {}).get("(51, 2)")
                        market_scale = implied_fcf_path_scale_for_enterprise_value(
                            market_ev, model_enterprise_value=model_ev
                        )
                        target_scale = implied_fcf_path_scale_for_enterprise_value(
                            target_ev, model_enterprise_value=model_ev
                        )
                        if market_scale.get("available"):
                            valuation_metrics["market_implied_fcf_path_vs_model"] = (
                                market_scale["implied_fcf_path_vs_model"]
                            )
                        if target_scale.get("available"):
                            valuation_metrics["analyst_target_implied_fcf_path_vs_model"] = (
                                target_scale["implied_fcf_path_vs_model"]
                            )
                        explicit_fcf = [
                            dcf_cells.get(f"(16, {column})")
                            for column in range(2, 12)
                        ]
                        dcf_wacc = dcf_cells.get("(12, 2)")
                        dcf_growth = dcf_cells.get("(23, 2)")
                        mid_year_adjustment = (
                            (computed_data.get("Sensitivity") or {}).get(
                                "cells", {}
                            ).get("(4, 2)", 0.0)
                        )
                        for prefix, benchmark_ev in (
                            ("market", market_ev),
                            ("analyst_target", target_ev),
                        ):
                            implied_rate = implied_discount_rate_for_enterprise_value(
                                benchmark_ev,
                                explicit_fcf=explicit_fcf,
                                terminal_growth=dcf_growth,
                                model_wacc=dcf_wacc,
                                mid_year_adjustment=mid_year_adjustment,
                            )
                            if implied_rate.get("available"):
                                valuation_metrics[f"{prefix}_implied_wacc"] = (
                                    implied_rate["implied_wacc"]
                                )
                                valuation_metrics[f"{prefix}_implied_wacc_vs_model"] = (
                                    implied_rate["implied_wacc_vs_model"]
                                )
                            implied_growth = (
                                implied_terminal_growth_for_enterprise_value(
                                    benchmark_ev,
                                    explicit_fcf=explicit_fcf,
                                    wacc=dcf_wacc,
                                    model_terminal_growth=dcf_growth,
                                    mid_year_adjustment=mid_year_adjustment,
                                )
                            )
                            if implied_growth.get("available"):
                                valuation_metrics[
                                    f"{prefix}_implied_terminal_growth"
                                ] = implied_growth["implied_terminal_growth"]
                                valuation_metrics[
                                    f"{prefix}_implied_terminal_growth_vs_model"
                                ] = implied_growth[
                                    "implied_terminal_growth_vs_model"
                                ]
                    except Exception:
                        # The target benchmark is optional. Current-market
                        # reverse DCF and the publication boundary remain valid.
                        pass
                    peer_comps = ((raw.get("industry_data") or {}).get("peer_comps") or {})
                    from src.valuation_methodology import normalize_peer_comps_policy
                    comps_policy = normalize_peer_comps_policy(peer_comps)
                    comps_publishable = comps_policy["included_in_blended_value"]
                    valuation_metrics["comps_included_in_blended_value"] = comps_publishable
                    valuation_metrics["comps_confidence"] = comps_policy["confidence"]
                    valuation_metrics["comps_role"] = comps_policy["role"]
                    authoritative_comps = comps_price if comps_publishable else None
                    ratio, band, spread_note = valuation_dispersion({
                        "perpetual DCF": perpetual_price,
                        "exit multiple DCF": exit_multiple_price,
                        "market comps": authoritative_comps,
                    })
                    if band:
                        valuation_metrics["dispersion_band"] = band
                    if ratio:
                        valuation_metrics["dispersion_ratio"] = ratio
                    if spread_note:
                        # Carried on the state so the report generator and the
                        # answer writer both see it; logged so it is auditable
                        # in the run's info.log afterwards.
                        valuation_metrics["valuation_warning"] = spread_note
                        state.log_action("model_generation_agent", f"⚠️ {spread_note}")

                    from src.financial_freshness import financial_statement_freshness
                    # Recompute from source periods for every run. A cached
                    # "current" flag must not keep aging statements current.
                    financial_freshness = financial_statement_freshness(raw)
                    valuation_metrics["financial_freshness"] = financial_freshness
                    company = raw.get("company_data") or {}
                    market = company.get("market_data") or {}
                    basic = company.get("basic_info") or {}
                    market_cap = market.get("market_cap")
                    currency = basic.get("listing_currency") or basic.get("currency")
                    is_mega_cap = bool(
                        isinstance(market_cap, (int, float))
                        and not isinstance(market_cap, bool)
                        and market_cap >= _megacap_threshold(currency)
                    )
                    withheld, withheld_reason = valuation_publication_boundary(
                        band=band,
                        legs={
                            "perpetual_dcf": perpetual_price,
                            "exit_multiple_dcf": exit_multiple_price,
                            "market_comps": authoritative_comps,
                        },
                        fair_value=average_price,
                        current_price=current_price,
                        is_mega_cap=is_mega_cap,
                        analyst_target=valuation_metrics.get("analyst_target"),
                        analyst_count=valuation_metrics.get("analyst_count"),
                        analyst_rating=_grounded.get("analyst_consensus_rating"),
                        analyst_rating_count=_grounded.get(
                            "analyst_consensus_rating_count"),
                        analyst_rating_evidence=(
                            ((raw.get("external_expectations") or {}).get(
                                "recommendations") or {}).get("source_evidence")
                            or {}
                        ),
                        analyst_target_evidence=(
                            ((raw.get("external_expectations") or {}).get(
                                "price_target") or {}).get("source_evidence")
                            or {}
                        ),
                        reverse_dcf_gap=market_implied_vs_model,
                    )
                    if withheld:
                        valuation_metrics["point_estimate_withheld"] = True
                        valuation_metrics["publication_withheld_reason"] = withheld_reason
                        state.log_action(
                            "model_generation_agent",
                            f"⚠️ Point estimate and rating withheld: {withheld_reason}",
                        )
                    if financial_freshness.get("status") in {"stale", "unavailable"}:
                        freshness_reason = financial_freshness.get("reason") or (
                            "The financial statements needed for the valuation are unavailable."
                        )
                        valuation_metrics["point_estimate_withheld"] = True
                        existing_reason = valuation_metrics.get(
                            "publication_withheld_reason"
                        )
                        valuation_metrics["publication_withheld_reason"] = (
                            f"{existing_reason} {freshness_reason}"
                            if existing_reason and freshness_reason not in existing_reason
                            else freshness_reason
                        )
                        state.log_action(
                            "model_generation_agent",
                            f"⚠️ Point estimate and rating withheld: {freshness_reason}",
                        )
                except Exception as _disp_err:
                    # Publication controls are safety checks, not optional
                    # diagnostics. Keep the workbook for audit, but fail closed
                    # when the engine cannot establish whether a point value is
                    # safe to show.
                    valuation_metrics["point_estimate_withheld"] = True
                    valuation_metrics["publication_withheld_reason"] = (
                        "The valuation publication safety check could not be completed; "
                        "the model is available only as an audit scenario."
                    )
                    state.log_action(
                        "model_generation_agent",
                        f"publication safety check failed closed: {_disp_err}"
                    )

                state.log_action(
                    "model_generation_agent",
                    _valuation_log_summary(valuation_metrics),
                )

            except Exception as extract_error:
                state.log_error(
                    "model_generation_agent",
                    f"Could not safely extract valuation metrics from JSON: {extract_error}"
                )
                state.current_stage = PipelineStage.FAILED
                return state

        # Financial-sector override: an FCF DCF is structurally unfit for
        # banks/insurers (deposit and loan flows swamp "FCF" — FBP and JPM
        # both shipped meaningless valuations to real users). Swap in a
        # Gordon justified P/B x ROE fair value; keep the DCF numbers under
        # dcf_* keys for transparency.
        model_type = "comprehensive_dcf"
        try:
            raw_financials = state.financial_data.raw_data if state.financial_data else {}
            # Use the exact override that built the downloaded workbook. A
            # second calculation could disagree if inputs changed or an
            # exception occurred, leaving chat on an industrial DCF while the
            # workbook showed a bank method.
            bank_override = getattr(builder, "bank_valuation_override", None)
            bank_required = initial_suitability.get("primary_method") == "justified_pb_roe"
            if bank_required and not bank_override:
                raise RuntimeError(
                    "The selected bank valuation was unavailable after workbook generation."
                )
            if bank_override:
                bank = {
                    "fair_value": bank_override["fair_value"],
                    "upside_vs_market": bank_override.get("upside_vs_market"),
                    "inputs": bank_override.get("bank_inputs") or {},
                    "intrinsic_fair_value": bank_override.get("intrinsic_fair_value"),
                    "forward_consensus_fair_value": bank_override.get(
                        "forward_consensus_fair_value"
                    ),
                    "peer_fair_value": bank_override.get("peer_fair_value"),
                }
                company_data = (raw_financials or {}).get("company_data", {}) or {}
                if valuation_metrics.get("fair_value") is not None:
                    valuation_metrics["dcf_fair_value"] = valuation_metrics["fair_value"]
                ref_price = valuation_metrics.get("current_price") or (
                    (company_data.get("market_data", {}) or {}).get("current_price")
                )
                valuation_metrics["fair_value"] = bank["fair_value"]
                if ref_price:
                    valuation_metrics["upside_vs_market"] = (
                        bank["fair_value"] / float(ref_price) - 1.0
                    )
                elif bank.get("upside_vs_market") is not None:
                    valuation_metrics["upside_vs_market"] = bank["upside_vs_market"]
                valuation_metrics["valuation_method"] = "justified_pb_roe"
                valuation_metrics["bank_intrinsic_fair_value"] = bank.get(
                    "intrinsic_fair_value")
                valuation_metrics["bank_forward_consensus_fair_value"] = bank.get(
                    "forward_consensus_fair_value"
                )
                valuation_metrics["bank_peer_fair_value"] = bank.get("peer_fair_value")
                # Report override contract (separate from the tool-friendly
                # aliases above): preserve the bank scenarios and audited
                # inputs all the way to the common publication boundary.
                valuation_metrics["intrinsic_fair_value"] = bank.get(
                    "intrinsic_fair_value")
                valuation_metrics["forward_consensus_fair_value"] = bank.get(
                    "forward_consensus_fair_value"
                )
                valuation_metrics["peer_fair_value"] = bank.get("peer_fair_value")
                valuation_metrics["bank_inputs"] = bank["inputs"]
                valuation_metrics["reliability_legs"] = bank_override.get(
                    "reliability_legs")
                # The FCF methods were explicitly superseded because they
                # are structurally inapplicable to this balance-sheet
                # business. Their dispersion must not lower confidence in,
                # or withhold, the bank method that replaced them.
                valuation_metrics["dispersion_band"] = bank_override.get("dispersion_band")
                valuation_metrics["dispersion_ratio"] = bank_override.get("dispersion_ratio")
                valuation_metrics["valuation_warning"] = bank_override.get("valuation_warning")
                # A publication block derived from the discarded FCF legs is
                # not evidence against the replacement bank method. Reapply
                # only method-independent input-quality boundaries below.
                valuation_metrics.pop("point_estimate_withheld", None)
                valuation_metrics.pop("publication_withheld_reason", None)
                if bank_override.get("point_estimate_withheld"):
                    valuation_metrics["point_estimate_withheld"] = True
                    valuation_metrics["publication_withheld_reason"] = (
                        bank_override.get("publication_withheld_reason")
                        or "The bank valuation did not pass its publication boundary."
                    )
                financial_freshness = valuation_metrics.get("financial_freshness") or {}
                if financial_freshness.get("status") in {"stale", "unavailable"}:
                    valuation_metrics["point_estimate_withheld"] = True
                    freshness_reason = (
                        financial_freshness.get("reason") or
                        "The financial statements needed for the valuation are unavailable."
                    )
                    existing_reason = valuation_metrics.get(
                        "publication_withheld_reason"
                    )
                    valuation_metrics["publication_withheld_reason"] = (
                        f"{existing_reason} {freshness_reason}"
                        if existing_reason and freshness_reason not in existing_reason
                        else freshness_reason
                    )
                for k, v in bank["inputs"].items():
                    assumptions[f"bank_{k}"] = v
                model_type = "bank_justified_pb_roe"
                state.log_action(
                    "model_generation_agent",
                    f"🏦 Financial-sector valuation: normalized-ROE justified P/B "
                    f"${bank.get('intrinsic_fair_value') or bank['fair_value']:.2f}"
                    + (f", ROE-adjusted peer P/B ${bank['peer_fair_value']:.2f}, "
                       f"audit midpoint ${bank['fair_value']:.2f}"
                       if isinstance(bank.get('peer_fair_value'), (int, float)) else "")
                    + f" (P/B {bank['inputs']['justified_pb']:.2f}, "
                    f"ROE {bank['inputs']['roe']*100:.1f}%, r {bank['inputs']['cost_of_equity']*100:.1f}%) "
                    + ("— point estimate withheld; " if bank_override.get("point_estimate_withheld")
                       else "— point estimate publishable; ")
                    + "FCF DCF suppressed as not meaningful for financials"
                )
        except Exception as bank_error:
            state.log_error(
                "model_generation_agent",
                f"Bank valuation failed closed: {bank_error}"
            )
            state.current_stage = PipelineStage.FAILED
            return state

        # Method suitability is separate from whether the spreadsheet could
        # finish its arithmetic. Loss-making/pre-revenue companies still get
        # auditable DCF scenarios, but those scenarios cannot become a point
        # value or rating merely because every formula evaluated.
        try:
            raw = state.financial_data.raw_data if state.financial_data else {}
            suitability = assess_valuation_methodology(raw or {})
            valuation_metrics["method_suitability"] = suitability
            if not suitability.get("publication_allowed"):
                valuation_metrics["point_estimate_withheld"] = True
                valuation_metrics["publication_withheld_reason"] = suitability.get("reason")
                state.log_action(
                    "model_generation_agent",
                    "⚠️ Point estimate and rating withheld by method-suitability check: "
                    + str(suitability.get("reason")),
                )
        except Exception as suitability_error:
            valuation_metrics["point_estimate_withheld"] = True
            valuation_metrics["publication_withheld_reason"] = (
                "The valuation-method suitability check could not be completed; "
                "the model is available only as an audit scenario."
            )
            state.log_action(
                "model_generation_agent",
                f"method-suitability check failed closed: {suitability_error}",
            )

        # The self-contained computed artifact ran the complete common
        # publication policy.  Apply it last so no lighter-weight conversational
        # path can accidentally loosen a denial made by that policy.
        valuation_metrics = _merge_machine_publication_boundary(
            valuation_metrics, computed_data
        )

        # Update FinancialState with generated model
        state.financial_model = FinancialModel(
            ticker=state.ticker,
            model_type=model_type,
            excel_path=str(output_file),
            json_computed_values_path=computed_values_path,
            valuation_metrics=valuation_metrics,
            assumptions=assumptions
        )
        
        # Update pipeline stage
        state.current_stage = PipelineStage.MODEL_GENERATED
        
        state.log_action(
            "model_generation_agent",
            f"✅ COMPLETED: Financial model generation finished successfully"
        )
        
        state.log_action(
            "model_generation_agent",
            f"📊 Model Summary: {state.financial_model.model_type} model, Excel: {output_file.name}"
        )
        
        return state
        
    except Exception as e:
        state.log_error("model_generation_agent", f"Failed: {str(e)}")
        state.current_stage = PipelineStage.FAILED
        return state
