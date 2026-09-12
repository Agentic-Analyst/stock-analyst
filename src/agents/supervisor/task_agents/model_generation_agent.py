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
from typing import Optional

from src.agents.supervisor.state import FinancialState, FinancialModel, PipelineStage, PipelineConfig
from src.agents.fm import create_financial_model


async def model_generation_agent(
    state: FinancialState,
    config: Optional[PipelineConfig] = None
) -> FinancialState:
    """
    Generate a banker-grade DCF financial model.
    
    This agent:
    - Reads: state.ticker, state.analysis_path, state.logger
    - Executes: Financial model generation with LLM-inferred assumptions
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
            f"Building banker-grade DCF model with LLM-inferred assumptions..."
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
            
            # Optionally evaluate formulas and save computed values
            state.log_action(
                "model_generation_agent",
                "Evaluating formulas and generating computed values JSON..."
            )
            
            try:
                builder.evaluate_and_save_json(json_output_path)
                state.log_action(
                    "model_generation_agent",
                    f"✅ Computed values JSON saved: {json_output_path.name}"
                )
                computed_values_path = str(json_output_path)
            except Exception as eval_error:
                state.log_action(
                    "model_generation_agent",
                    f"⚠️  Formula evaluation encountered issues: {eval_error}. Continuing..."
                )
                computed_values_path = None
            
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
                revenue_growth_rates = []
                
                for cell_key, cell_value in summary_cells.items():
                    # Get the corresponding label from one cell to the left
                    row, col = eval(cell_key)
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
                        elif ("Blended Fair Value (Per-Share)" in label or
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
                
                # Extract revenue growth rates from LLM_Inferred tab
                llm_inferred_cells = computed_data.get("LLM_Inferred", {}).get("cells", {})
                for cell_key, cell_value in llm_inferred_cells.items():
                    row, col = eval(cell_key)
                    label_key = f"({row}, 1)"
                    label = llm_inferred_cells.get(label_key, "")
                    
                    if isinstance(label, str) and "Revenue Growth Rate" in label:
                        # Collect FY1-FY5 growth rates (columns 2-6)
                        if col >= 2 and col <= 6 and isinstance(cell_value, (int, float)):
                            revenue_growth_rates.append(cell_value)
                
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
                    ratio, band, spread_note = valuation_dispersion({
                        "perpetual DCF": perpetual_price,
                        "exit multiple DCF": exit_multiple_price,
                        "market comps": comps_price,
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

                    raw = state.financial_data.raw_data or {}
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
                            "market_comps": comps_price,
                        },
                        fair_value=average_price,
                        current_price=current_price,
                        is_mega_cap=is_mega_cap,
                        analyst_target=valuation_metrics.get("analyst_target"),
                        analyst_count=valuation_metrics.get("analyst_count"),
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
                        valuation_metrics["publication_withheld_reason"] = freshness_reason
                        state.log_action(
                            "model_generation_agent",
                            f"⚠️ Point estimate and rating withheld: {freshness_reason}",
                        )
                except Exception as _disp_err:
                    # Never let a diagnostic break model generation.
                    state.log_action(
                        "model_generation_agent",
                        f"dispersion check skipped: {_disp_err}"
                    )

                state.log_action(
                    "model_generation_agent",
                    f"📊 Extracted valuation: Fair Value=${valuation_metrics.get('fair_value', 'N/A'):.2f}, "
                    f"Current=${valuation_metrics.get('current_price', 'N/A'):.2f}, "
                    f"Upside={valuation_metrics.get('upside_vs_market', 0)*100:.1f}%"
                )

            except Exception as extract_error:
                state.log_action(
                    "model_generation_agent",
                    f"⚠️  Could not extract valuation metrics from JSON: {extract_error}"
                )

        # Financial-sector override: an FCF DCF is structurally unfit for
        # banks/insurers (deposit and loan flows swamp "FCF" — FBP and JPM
        # both shipped meaningless valuations to real users). Swap in a
        # Gordon justified P/B x ROE fair value; keep the DCF numbers under
        # dcf_* keys for transparency.
        model_type = "comprehensive_dcf"
        try:
            from src.agents.fm.bank_valuation import build_bank_valuation_override
            raw_financials = state.financial_data.raw_data if state.financial_data else {}
            bank_override = build_bank_valuation_override(
                raw_financials or {}, assumptions.get("terminal_growth"), capm=_capm
            )
            if bank_override:
                bank = {
                    "fair_value": bank_override["fair_value"],
                    "upside_vs_market": bank_override.get("upside_vs_market"),
                    "inputs": bank_override.get("bank_inputs") or {},
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
                # The FCF methods were explicitly superseded because they
                # are structurally inapplicable to this balance-sheet
                # business. Their dispersion must not lower confidence in,
                # or withhold, the bank method that replaced them.
                valuation_metrics.pop("dispersion_band", None)
                valuation_metrics.pop("dispersion_ratio", None)
                valuation_metrics.pop("valuation_warning", None)
                # A publication block derived from the discarded FCF legs is
                # not evidence against the replacement bank method. Reapply
                # only method-independent input-quality boundaries below.
                valuation_metrics.pop("point_estimate_withheld", None)
                valuation_metrics.pop("publication_withheld_reason", None)
                financial_freshness = valuation_metrics.get("financial_freshness") or {}
                if financial_freshness.get("status") in {"stale", "unavailable"}:
                    valuation_metrics["point_estimate_withheld"] = True
                    valuation_metrics["publication_withheld_reason"] = (
                        financial_freshness.get("reason")
                        or "The financial statements needed for the valuation are unavailable."
                    )
                for k, v in bank["inputs"].items():
                    assumptions[f"bank_{k}"] = v
                model_type = "bank_justified_pb_roe"
                state.log_action(
                    "model_generation_agent",
                    f"🏦 Financial-sector valuation: justified P/B x ROE fair value "
                    f"${bank['fair_value']:.2f} (P/B {bank['inputs']['justified_pb']:.2f}, "
                    f"ROE {bank['inputs']['roe']*100:.1f}%, r {bank['inputs']['cost_of_equity']*100:.1f}%) "
                    f"— FCF DCF suppressed as not meaningful for financials"
                )
        except Exception as bank_error:
            state.log_action(
                "model_generation_agent",
                f"⚠️  Bank valuation override skipped: {bank_error}"
            )

        # Method suitability is separate from whether the spreadsheet could
        # finish its arithmetic. Loss-making/pre-revenue companies still get
        # auditable DCF scenarios, but those scenarios cannot become a point
        # value or rating merely because every formula evaluated.
        try:
            from src.valuation_methodology import assess_valuation_methodology
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
            state.log_action(
                "model_generation_agent",
                f"method-suitability check skipped: {suitability_error}",
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
