"""
News Analysis Agent Node

Performs comprehensive news analysis: Scraping → Filtering → Screening

This agent:
1. Scrapes news articles using ArticleScraper
2. Filters articles by relevance using ArticleFilter
3. Screens articles for insights using ArticleScreener
4. Extracts catalysts, risks, and mitigations
5. Updates state.news_analysis
6. Marks pipeline stage as NEWS_ANALYSIS_COMPLETED
"""

from pathlib import Path
from typing import Optional
from dataclasses import asdict

from src.agents.supervisor.state import (
    FinancialState, NewsAnalysis, PipelineStage, PipelineConfig
)
from src.article_scraper import ArticleScraper
from src.article_filter import ArticleFilter
from src.article_screener import ArticleScreener
from src.logger import get_agent_logger, StockAnalystLogger


async def news_analysis_agent(
    state: FinancialState,
    config: Optional[PipelineConfig] = None
) -> FinancialState:
    """
    Perform comprehensive news analysis (Scraping → Filtering → Screening).
    
    This agent:
    - Reads: state.ticker, state.company_name, state.analysis_path, state.logger
    - Executes: 3-step news pipeline
    - Updates: state.news_analysis, state.current_stage
    - Tracks: LLM costs
    - Returns: Updated FinancialState with news analysis
    
    Args:
        state: Current FinancialState
        config: Optional PipelineConfig for parameters
        
    Returns:
        Updated FinancialState with news analysis completed
    """
    try:
        state.log_action(
            "news_analysis_agent",
            f"Starting news analysis for {state.ticker}..."
        )
        
        # Get parameters from config or use defaults
        max_articles_to_search = 80
        min_filter_score = 6.0
        max_filtered = 15
        min_confidence = 0.6
        
        if config:
            max_articles_to_search = config.max_articles_to_search
            min_filter_score = config.min_filter_score
            min_confidence = config.min_confidence_for_insights
        
        # ==================== PART 1: SCRAPING ====================
        state.log_action(
            "news_analysis_agent",
            f"[1/3] Scraping news articles (max {max_articles_to_search})..."
        )
        
        # Use state's analysis_path directly
        analysis_path = Path(state.analysis_path) if isinstance(state.analysis_path, str) else state.analysis_path
        
        # Use effective logger from state
        effective_logger = state.get_effective_logger("news_analysis_agent")
        
        scraper = ArticleScraper(state.ticker, state.company_name, analysis_path)
        if effective_logger:
            scraper.set_logger(effective_logger)
        
        # Check current storage
        storage_info = scraper.get_storage_info()
        current_count = storage_info.get("total_articles", 0)
        state.log_action("news_analysis_agent", f"Articles currently in storage: {current_count}")
        
        # Perform comprehensive scraping
        scraping_results = scraper.run_comprehensive_scraping(max_articles=max_articles_to_search)
        
        state.log_action(
            "news_analysis_agent",
            f"Scraped: {scraping_results.get('scraped_count', 0)} new articles, "
            f"Duplicates skipped: {scraping_results.get('duplicate_count', 0)}"
        )
        
        # ==================== PART 2: FILTERING ====================
        state.log_action(
            "news_analysis_agent",
            f"[2/3] Filtering articles by relevance (min score: {min_filter_score})..."
        )
        
        # Generate search query
        filter_query = f"{state.company_name} financial outlook earnings growth investment analysis"
        
        article_filter = ArticleFilter(state.ticker, filter_query, analysis_path)
        if effective_logger:
            article_filter.set_logger(effective_logger)
        
        filtering_results = article_filter.filter_articles(
            max_filtered=max_filtered,
            min_score=min_filter_score
        )
        
        filtered_articles = filtering_results.get("filtered_articles", [])
        filter_llm_cost = filtering_results.get("llm_cost", 0.0)
        
        state.log_action(
            "news_analysis_agent",
            f"Filtered articles: {len(filtered_articles)}, LLM cost: ${filter_llm_cost:.4f}"
        )
        
        # Track filtering LLM cost
        state.total_llm_cost += filter_llm_cost
        
        # ==================== PART 3: SCREENING ====================
        state.log_action(
            "news_analysis_agent",
            f"[3/3] Screening articles for investment insights..."
        )
        
        screener = ArticleScreener(state.ticker, analysis_path)
        if effective_logger:
            screener.set_logger(effective_logger)
        
        # Load articles from database
        articles_data = screener.load_articles_from_db(limit=50)
        state.log_action("news_analysis_agent", f"Analyzing {len(articles_data)} articles...")
        
        # Extract insights using LLM
        catalysts, risks, mitigations, analysis_summary = screener.analyze_all_articles(
            articles_data
        )
        
        # Filter by confidence threshold
        high_conf_catalysts = [c for c in catalysts if c.confidence >= min_confidence]
        high_conf_risks = [r for r in risks if r.confidence >= min_confidence]
        high_conf_mitigations = [m for m in mitigations if m.confidence >= min_confidence]
        
        # Track screening LLM cost
        screener_cost = screener.total_llm_cost
        state.total_llm_cost += screener_cost
        
        state.log_action(
            "news_analysis_agent",
            f"Extracted insights: {len(high_conf_catalysts)} catalysts, "
            f"{len(high_conf_risks)} risks, {len(high_conf_mitigations)} mitigations"
        )
        
        # Save structured data to JSON
        data_file = analysis_path / "screened" / "screening_data.json"
        screener.save_structured_data(
            high_conf_catalysts,
            high_conf_risks,
            high_conf_mitigations,
            analysis_summary,
            data_file
        )
        
        state.log_action("news_analysis_agent", f"Structured data saved to: {data_file}")
        
        # ==================== UPDATE STATE ====================
        
        # Convert dataclass objects to dictionaries for NewsAnalysis
        catalysts_dicts = [asdict(c) for c in high_conf_catalysts] if high_conf_catalysts else []
        risks_dicts = [asdict(r) for r in high_conf_risks] if high_conf_risks else []
        mitigations_dicts = [asdict(m) for m in high_conf_mitigations] if high_conf_mitigations else []
        
        # Update FinancialState with news analysis results
        state.news_analysis = NewsAnalysis(
            ticker=state.ticker,
            articles_count=len(catalysts) + len(risks) + len(mitigations),
            catalysts=catalysts_dicts,
            risks=risks_dicts,
            mitigations=mitigations_dicts,
            overall_sentiment=analysis_summary.get("overall_sentiment", "neutral") if isinstance(analysis_summary, dict) else "neutral",
            key_themes=[c.type for c in high_conf_catalysts[:5]] if high_conf_catalysts else [],
            screening_data_path=str(data_file),
            llm_cost=state.total_llm_cost
        )
        
        # Update pipeline stage
        state.current_stage = PipelineStage.NEWS_ANALYSIS_COMPLETED
        
        state.log_action(
            "news_analysis_agent",
            f"✅ COMPLETED: News analysis finished successfully"
        )
        
        state.log_action(
            "news_analysis_agent",
            f"📊 Analysis Summary: Total LLM cost: ${state.total_llm_cost:.4f}"
        )
        
        return state
        
    except Exception as e:
        state.log_error("news_analysis_agent", f"Failed: {str(e)}")
        state.current_stage = PipelineStage.FAILED
        return state
