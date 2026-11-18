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
from src.currency import currency_symbol


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

        # Every chat message starts a fresh worker, and a follow-up about the
        # same company downloaded its statements again (4 s median, 24 s at
        # the 90th percentile). The saved file, which the model builder reads,
        # is reused for a few minutes; a missing cache only means no reuse.
        cached = _recent_financials(state.ticker)
        if cached is not None:
            state.log_action(
                "financial_data_agent",
                f"Reusing financial data for {state.ticker} downloaded in the last "
                f"{_FINANCIALS_REUSE_SECONDS // 60} minutes.",
            )
            return _finish(state, scraper, cached)

        # This pipeline builds issuer financial statements and a DCF. Yahoo can
        # return prices for funds, crypto, indices, and other instruments too,
        # but treating that as company data produces plausible-looking nonsense.
        # Keep the prompt-level routing rule backed by a hard boundary here.
        instrument_info = scraper.yf_ticker.info or {}
        quote_type = str(instrument_info.get("quoteType") or "").strip().upper()
        if quote_type and quote_type != "EQUITY":
            raise ValueError(
                f"{state.ticker} is classified as {quote_type}, not an operating "
                "company; issuer financials and DCF are disabled for this instrument"
            )
        
        # Use effective logger from state
        effective_logger = state.get_effective_logger("financial_data_agent")
        if effective_logger:
            scraper.set_logger(effective_logger)
        
        # Scrape comprehensive financial data
        state.log_action("financial_data_agent", "Scraping financial statements...")
        financial_data = scraper.scrape_financial_modeling_data(annual=True)
        
        state.log_action("financial_data_agent", "Saving financial data to JSON...")
        state = _finish(state, scraper, financial_data)
        _remember_financials(state.ticker, state.financial_data.json_path if state.financial_data else None)
        return state

    except Exception as e:
        state.log_error("financial_data_agent", f"Failed: {str(e)}")
        state.current_stage = PipelineStage.FAILED
        return state


_FINANCIALS_REUSE_SECONDS = 15 * 60


def _financials_cache_name(ticker: str) -> str:
    import re
    return "financials_" + re.sub(r"[^A-Za-z0-9._-]", "_", str(ticker or "").upper())


def _recent_financials(ticker: str):
    try:
        from src.agents.fm.netcache import cache_get
        data = cache_get(_financials_cache_name(ticker), _FINANCIALS_REUSE_SECONDS)
    except Exception:
        return None
    basic = ((data or {}).get("company_data") or {}).get("basic_info") or {} if isinstance(data, dict) else {}
    quote_type = str(basic.get("quote_type") or "").strip().upper()
    # Only a company's data is kept, so the instrument check below is not skipped.
    return data if isinstance(data, dict) and quote_type == "EQUITY" else None


def _remember_financials(ticker: str, json_path) -> None:
    """Keep the saved file's contents, exactly as the model builder reads them.

    Only a complete download: statements for three or more years and a price.
    A partial one is downloaded again next time.
    """
    try:
        import json
        from src.agents.fm.netcache import cache_put
        with open(json_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        completeness = (data.get("data_summary") or {}).get("data_completeness") or {}
        market = (data.get("company_data") or {}).get("market_data") or {}
        if int(completeness.get("income_statement_periods") or 0) < 3 or not market.get("current_price"):
            return
        cache_put(_financials_cache_name(ticker), data)
    except Exception:
        return


def _finish(state: FinancialState, scraper: "FinancialScraper", financial_data: dict) -> FinancialState:
    """Save the data, put it on the state and log what was collected."""
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
        company_context += (
            f" • Current: {currency_symbol(basic_info.get('currency'))}"
            f"{market_data['current_price']:.2f}"
        )

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
