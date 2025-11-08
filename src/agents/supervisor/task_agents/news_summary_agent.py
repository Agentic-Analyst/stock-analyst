"""
News Summary Agent - Task Agent Wrapper
Generates professional news analysis summary after news analysis.

This is a wrapper around the standalone news_summary_agent.py that integrates
it into the supervisor workflow.
"""

import asyncio
from pathlib import Path

from src.news_summary_agent import generate_and_save_news_summary
from src.agents.supervisor.state import FinancialState


async def news_summary_agent(state: FinancialState) -> FinancialState:
    """
    Generate news analysis summary for QUICK_NEWS objective.
    
    Prerequisites:
        - News analysis must be completed
    
    Args:
        state: Current workflow state with news_analysis populated
        
    Returns:
        Updated FinancialState with news_summary_path populated
    """
    logger = state.get_effective_logger("news_summary_agent")
    
    try:
        # Validate prerequisites
        if not state.is_news_analyzed():
            error_msg = "Cannot generate news summary: news analysis not completed"
            logger.error(f"❌ {error_msg}")
            state.log_error("news_summary_agent", error_msg)
            return state
        
        logger.info(f"📰 Generating news summary for {state.ticker}...")
        
        # Run the summary generation in executor (it's synchronous)
        loop = asyncio.get_event_loop()
        summary_result = await loop.run_in_executor(
            None,
            generate_and_save_news_summary,
            Path(state.analysis_path),  # analysis_path
            state.ticker,               # ticker
            state.company_name,         # company_name (optional)
            logger                      # logger (optional)
        )
        
        # Unpack the tuple result: (content, path, cost)
        summary_content, summary_path, llm_cost = summary_result
        
        if not summary_path:
            error_msg = "Summary generation returned no path"
            logger.error(f"❌ {error_msg}")
            state.log_error("news_summary_agent", error_msg)
            return state
        
        # Update state
        state.news_summary_path = str(summary_path)
        state.total_llm_cost += llm_cost
        
        logger.info(f"✅ News summary generated: {summary_path}")
        state.log_action(
            "news_summary_agent",
            "generated_news_summary",
            {"summary_path": str(summary_path), "llm_cost": llm_cost}
        )
        
        return state
        
    except Exception as e:
        error_msg = f"News summary generation failed: {str(e)}"
        logger.error(f"❌ {error_msg}")
        state.log_error("news_summary_agent", error_msg, {"exception": str(e)})
        
        return state
