"""
Financial Data Agent Node

Collects financial data from Yahoo Finance and populates FinancialState.

This agent:
1. Instantiates FinancialScraper
2. Scrapes financial statements (income, balance sheet, cash flow)
3. Saves data to JSON file
4. Updates state.financial_data
5. Marks pipeline stage as FINANCIAL_DATA_COLLECTED
"""

from pathlib import Path
from typing import Optional
from datetime import datetime

from src.agents.supervisor.state import FinancialState, FinancialData, PipelineStage, PipelineConfig
from src.financial_scraper import FinancialScraper
from src.logger import get_agent_logger


async def financial_data_agent(
    state: FinancialState,
    config: Optional[PipelineConfig] = None
) -> FinancialState:
    """
    Collect financial data for the given ticker.
    
    This agent:
    - Reads: state.ticker, state.company_name, state.analysis_path
    - Executes: Financial data scraping from Yahoo Finance
    - Updates: state.financial_data, state.current_stage
    - Returns: Updated FinancialState
    
    Args:
        state: Current FinancialState
        config: Optional PipelineConfig for parameters
        
    Returns:
        Updated FinancialState with financial data collected
    """
    try:
        state.log_action(
            "financial_data_agent",
            f"Starting financial data collection for {state.ticker}..."
        )
        
        # Use state's analysis_path directly (already a Path object or string)
        analysis_path = Path(state.analysis_path) if isinstance(state.analysis_path, str) else state.analysis_path
        scraper = FinancialScraper(state.ticker, analysis_path)
        
        # Use effective logger from state
        effective_logger = state.get_effective_logger("financial_data_agent")
        if effective_logger:
            scraper.set_logger(effective_logger)
        
        # Scrape comprehensive financial data
        state.log_action("financial_data_agent", "Scraping financial statements...")
        financial_data = scraper.scrape_financial_modeling_data(annual=True)
        
        # Save financial data to JSON file
        state.log_action("financial_data_agent", "Saving financial data to JSON...")
        file_path = scraper.save_financial_data(financial_data)
        
        # Extract company context from scraped data
        company_data = financial_data.get("company_data", {})
        basic_info = company_data.get("basic_info", {})
        market_data = company_data.get("market_data", {})
        data_completeness = financial_data.get("data_summary", {}).get("data_completeness", {})
        
        # Update FinancialState with collected data
        state.financial_data = FinancialData(
            ticker=state.ticker,
            company_name=state.company_name,
            json_path=str(file_path),
            scraped_at=datetime.now(),
            data_completeness=data_completeness,
            key_metrics={
                "basic_info": basic_info,
                "market_data": market_data
            },
            raw_data=financial_data
        )
        
        # Update pipeline stage
        state.current_stage = PipelineStage.FINANCIAL_DATA_COLLECTED
        
        # Log completion with context
        company_context = ""
        if basic_info.get("sector") and basic_info.get("industry"):
            company_context = f" ({basic_info['sector']} - {basic_info['industry']})"
        if basic_info.get("employees"):
            company_context += f" • {basic_info['employees']:,} employees"
        if market_data.get("current_price"):
            company_context += f" • Current: ${market_data['current_price']:.2f}"
        
        stats = {
            "Years of data": data_completeness.get("income_statement_periods", 0),
            "Company": f"{basic_info.get('long_name', state.company_name)}{company_context}",
            "Data file": Path(file_path).name
        }
        
        state.log_action(
            "financial_data_agent",
            f"✅ COMPLETED: Financial data collection finished successfully"
        )
        
        state.log_action(
            "financial_data_agent",
            f"📊 Data Summary: {data_completeness.get('income_statement_periods', 0)} years, {basic_info.get('long_name', state.company_name)}{company_context}"
        )
        
        return state
        
    except Exception as e:
        state.log_error("financial_data_agent", f"Failed: {str(e)}")
        state.current_stage = PipelineStage.FAILED
        return state
