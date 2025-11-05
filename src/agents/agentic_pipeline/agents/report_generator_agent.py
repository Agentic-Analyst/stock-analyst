"""
Report Generator Agent Node

Generates a comprehensive professional analyst report.

This agent:
1. Collects data from all pipeline outputs (financial, model, news analysis)
2. Calls generate_and_save_professional_report()
3. Generates markdown analyst report
4. Updates state.report
5. Marks pipeline stage as REPORT_GENERATED
"""

import pathlib
import sys
from typing import Optional
from datetime import datetime

# Add src directory to path
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent.parent))

from agents.agentic_pipeline.state import FinancialState, Report, PipelineStage, PipelineConfig
from report_agent import generate_and_save_professional_report
from logger import StockAnalystLogger, get_agent_logger


async def report_generator_agent(
    state: FinancialState,
    config: Optional[PipelineConfig] = None
) -> FinancialState:
    """
    Generate a professional analyst report.
    
    This agent:
    - Reads: state.ticker, state.analysis_path, state.logger
    - Executes: Report generation by synthesizing all pipeline data
    - Updates: state.report, state.current_stage
    - Returns: Updated FinancialState with report generated
    
    Args:
        state: Current FinancialState (all prerequisites should be met)
        config: Optional PipelineConfig for parameters
        
    Returns:
        Updated FinancialState with report generated
    """
    try:
        state.log_action(
            "report_generator_agent",
            f"Starting professional report generation for {state.ticker}..."
        )
        
        # Get agent-specific logger
        agent_logger = get_agent_logger("report_generator_agent")
        effective_logger = agent_logger if agent_logger else state.logger
        
        # Validate prerequisites
        if not state.financial_data:
            state.log_error(
                "report_generator_agent",
                "Prerequisites not met: financial_data not collected"
            )
            state.current_stage = PipelineStage.FAILED
            return state
        
        if not state.financial_model:
            state.log_error(
                "report_generator_agent",
                "Prerequisites not met: financial_model not generated"
            )
            state.current_stage = PipelineStage.FAILED
            return state
        
        if not state.news_analysis:
            state.log_error(
                "report_generator_agent",
                "Prerequisites not met: news_analysis not completed"
            )
            state.current_stage = PipelineStage.FAILED
            return state
        
        state.log_action(
            "report_generator_agent",
            "All prerequisites met. Generating comprehensive analyst report..."
        )
        
        # Convert analysis_path string to Path for file operations
        analysis_path = pathlib.Path(state.analysis_path)
        
        try:
            # Generate professional report
            report_text, report_path = generate_and_save_professional_report(
                analysis_path,
                state.ticker,
                logger=effective_logger
            )
            
            state.log_action(
                "report_generator_agent",
                f"✅ Professional report generated successfully"
            )
            
            state.log_action(
                "report_generator_agent",
                f"Report details: "
                f"{len(report_text):,} characters, "
                f"saved to {report_path.name}"
            )
            
        except Exception as report_error:
            state.log_error(
                "report_generator_agent",
                f"Report generation failed: {str(report_error)}"
            )
            state.current_stage = PipelineStage.FAILED
            return state
        
        # Update FinancialState with generated report
        state.report = Report(
            ticker=state.ticker,
            report_type="professional_analyst",
            report_path=str(report_path),
            content=report_text,
            generated_at=datetime.now(),
            llm_cost=state.total_llm_cost
        )
        
        # Update pipeline stage
        state.current_stage = PipelineStage.REPORT_GENERATED
        
        state.log_action(
            "report_generator_agent",
            f"✅ COMPLETED: Professional report generation finished successfully"
        )
        
        state.log_action(
            "report_generator_agent",
            f"📊 Report Summary: {len(report_text):,} characters, saved to {report_path.name}"
        )
        
        return state
        
    except Exception as e:
        state.log_error("report_generator_agent", f"Failed: {str(e)}")
        state.current_stage = PipelineStage.FAILED
        return state
