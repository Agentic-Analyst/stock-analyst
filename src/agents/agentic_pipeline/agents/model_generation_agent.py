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

import pathlib
import sys
from typing import Optional

# Add src directory to path
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent.parent))

from agents.agentic_pipeline.state import FinancialState, FinancialModel, PipelineStage, PipelineConfig
from agents.fm import create_financial_model
from logger import StockAnalystLogger, get_agent_logger


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
        
        # Get agent-specific logger
        agent_logger = get_agent_logger("model_generation_agent")
        effective_logger = agent_logger if agent_logger else state.logger
        
        # Validate prerequisites
        if not state.financial_data:
            state.log_error(
                "model_generation_agent",
                "Prerequisites not met: financial_data not collected"
            )
            state.current_stage = PipelineStage.FAILED
            return state
        
        # Find the latest financial JSON file
        # Convert analysis_path string to Path for file operations
        analysis_path = pathlib.Path(state.analysis_path)
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
        
        # Update FinancialState with generated model
        state.financial_model = FinancialModel(
            ticker=state.ticker,
            model_type="comprehensive_dcf",
            excel_path=str(output_file),
            json_computed_values_path=computed_values_path
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
