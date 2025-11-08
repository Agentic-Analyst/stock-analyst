"""
Financial Summary Agent - Task Agent Wrapper
Generates professional financial model summary after model generation.

This is a wrapper around the standalone financial_summary_agent.py that integrates
it into the supervisor workflow.
"""

import asyncio
from pathlib import Path

from src.financial_summary_agent import generate_and_save_financial_summary
from src.agents.supervisor.state import FinancialState


async def financial_summary_agent(state: FinancialState) -> FinancialState:
    """
    Generate financial model summary for MODEL_ONLY objective.
    
    Prerequisites:
        - Financial model must be generated
        - Financial data must be collected
    
    Args:
        state: Current workflow state with financial_model populated
        
    Returns:
        Updated FinancialState with financial_summary_path populated
    """
    logger = state.get_effective_logger("financial_summary_agent")
    
    try:
        # Validate prerequisites
        if not state.is_model_generated():
            error_msg = "Cannot generate financial summary: financial model not generated"
            logger.error(f"❌ {error_msg}")
            state.log_error("financial_summary_agent", error_msg)
            return state
        
        if not state.is_financial_data_collected():
            error_msg = "Cannot generate financial summary: financial data not collected"
            logger.error(f"❌ {error_msg}")
            state.log_error("financial_summary_agent", error_msg)
            return state
        
        logger.info(f"📝 Generating financial summary for {state.ticker}...")
        
        # Run the summary generation in executor (it's synchronous)
        loop = asyncio.get_event_loop()
        summary_result = await loop.run_in_executor(
            None,
            generate_and_save_financial_summary,
            Path(state.analysis_path),  # analysis_path
            state.ticker,               # ticker
            logger                      # logger (optional)
        )
        
        # Unpack the tuple result: (content, path, cost)
        summary_content, summary_path, llm_cost = summary_result
        
        if not summary_path:
            error_msg = "Summary generation returned no path"
            logger.error(f"❌ {error_msg}")
            state.log_error("financial_summary_agent", error_msg)
            return state
        
        # Update state
        state.financial_summary_path = str(summary_path)
        state.total_llm_cost += llm_cost
        
        logger.info(f"✅ Financial summary generated: {summary_path}")
        state.log_action(
            "financial_summary_agent",
            "generated_financial_summary",
            {"summary_path": str(summary_path), "llm_cost": llm_cost}
        )
        
        return state
        
    except Exception as e:
        error_msg = f"Financial summary generation failed: {str(e)}"
        logger.error(f"❌ {error_msg}")
        state.log_error("financial_summary_agent", error_msg, {"exception": str(e)})
        
        return state
