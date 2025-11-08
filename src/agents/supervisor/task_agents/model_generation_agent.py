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
                average_price = None
                upside_vs_market = None
                wacc = None
                terminal_growth = None
                exit_multiple = None
                
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
                        elif "Average of Methods (Per-Share)" in label and col == 2:
                            average_price = cell_value
                        elif "Upside vs Market" in label and col == 2:
                            upside_vs_market = cell_value
                        elif "WACC (Perpetual DCF)" in label and col == 2:
                            wacc = cell_value
                        elif "Terminal Growth g" in label and col == 2:
                            terminal_growth = cell_value
                        elif "Exit Multiple (EV/EBITDA)" in label and col == 2:
                            exit_multiple = cell_value
                
                # Populate valuation_metrics dictionary
                if average_price is not None:
                    valuation_metrics["fair_value"] = average_price
                if perpetual_price is not None:
                    valuation_metrics["perpetual_price"] = perpetual_price
                if exit_multiple_price is not None:
                    valuation_metrics["exit_multiple_price"] = exit_multiple_price
                if current_price is not None:
                    valuation_metrics["current_price"] = current_price
                if upside_vs_market is not None:
                    valuation_metrics["upside_vs_market"] = upside_vs_market
                
                # Populate assumptions dictionary
                if wacc is not None:
                    assumptions["wacc"] = wacc
                if terminal_growth is not None:
                    assumptions["terminal_growth"] = terminal_growth
                if exit_multiple is not None:
                    assumptions["exit_multiple"] = exit_multiple
                
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
        
        # Update FinancialState with generated model
        state.financial_model = FinancialModel(
            ticker=state.ticker,
            model_type="comprehensive_dcf",
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
