"""
News Analysis Agent Node

Performs comprehensive news analysis: Database Check → Scraping (if needed) → Filtering → Screening

This agent:
1. Checks database for existing articles first
2. Scrapes news articles using ArticleScraper (if database has insufficient articles)
3. Filters articles by relevance using ArticleFilter (if scraping was triggered)
4. Screens articles for insights using ArticleScreener
5. Extracts catalysts, risks, and mitigations
6. Updates state.news_analysis
7. Marks pipeline stage as NEWS_ANALYSIS_COMPLETED
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
from src.config import MIN_CONFIDENCE
from src.config import MAX_ARTICLES
from vynn_core import find_recent


def _check_database_for_articles(ticker: str) -> int:
    """
    Check if database has sufficient recent articles for the ticker.
    
    Args:
        ticker: Stock ticker symbol
        min_articles: Minimum number of articles required
        
    Returns:
        Number of articles found in database
    """
    try:
        recent_articles = find_recent(limit=MAX_ARTICLES, collection_name=ticker)
        article_count = len(recent_articles) if recent_articles else 0
        return article_count
    except Exception as e:
        # If database check fails, return 0 to trigger fallback
        return 0


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
        
        # Use state's analysis_path directly
        analysis_path = Path(state.analysis_path) if isinstance(state.analysis_path, str) else state.analysis_path
        
        # Use effective logger from state
        effective_logger = state.get_effective_logger("news_analysis_agent")
        
        # ==================== PART 0: DATABASE CHECK ====================
        state.log_action(
            "news_analysis_agent",
            "[0/3] Checking database for existing articles..."
        )
        
        # Check if we have sufficient articles in database
        min_articles_threshold = 15  # Configurable threshold
        db_article_count = _check_database_for_articles(state.ticker)
        
        state.log_action(
            "news_analysis_agent",
            f"📊 Database check: Found {db_article_count} articles for {state.ticker}"
        )
        
        # Determine if scraping is needed
        needs_scraping = db_article_count < min_articles_threshold
        
        if needs_scraping:
            state.log_action(
                "news_analysis_agent",
                f"⚠️  Insufficient articles in database ({db_article_count} < {min_articles_threshold})"
            )
            state.log_action(
                "news_analysis_agent",
                "🔄 Triggering fallback: Scraping and filtering new articles..."
            )
        else:
            state.log_action(
                "news_analysis_agent",
                f"✅ Sufficient articles in database ({db_article_count} >= {min_articles_threshold})"
            )
            state.log_action(
                "news_analysis_agent",
                "⏭️  Skipping scraping and filtering, using existing database articles"
            )
        
        # ==================== PART 1: SCRAPING (CONDITIONAL) ====================
        if needs_scraping:
            state.log_action(
                "news_analysis_agent",
                "[1/3] Scraping news articles (using config defaults)..."
            )
            
            scraper = ArticleScraper(state.ticker, state.company_name, analysis_path)
            if effective_logger:
                scraper.set_logger(effective_logger)
            
            # Check current storage
            storage_info = scraper.get_storage_info()
            current_count = storage_info.get("total_articles", 0)
            state.log_action("news_analysis_agent", f"Articles currently in local storage: {current_count}")
            
            # Perform comprehensive scraping (uses config internally)
            scraping_results = scraper.run_comprehensive_scraping()
            
            state.log_action(
                "news_analysis_agent",
                f"Scraped: {scraping_results.get('scraped_count', 0)} new articles, "
                f"Duplicates skipped: {scraping_results.get('duplicate_count', 0)}"
            )
            
            # ==================== PART 2: FILTERING (CONDITIONAL) ====================
            state.log_action(
                "news_analysis_agent",
                "[2/3] Filtering articles by relevance (using config defaults)..."
            )
            
            # Generate search query
            filter_query = f"{state.company_name} financial outlook earnings growth investment analysis"
            
            article_filter = ArticleFilter(state.ticker, filter_query, analysis_path)
            if effective_logger:
                article_filter.set_logger(effective_logger)
            
            filtering_results = article_filter.filter_articles()  # Uses config internally
            
            filtered_articles = filtering_results.get("filtered_articles", [])
            filter_llm_cost = filtering_results.get("llm_cost", 0.0)
            
            state.log_action(
                "news_analysis_agent",
                f"Filtered articles: {len(filtered_articles)}, LLM cost: ${filter_llm_cost:.4f}"
            )
            
            # Track filtering LLM cost
            state.total_llm_cost += filter_llm_cost
        else:
            state.log_action(
                "news_analysis_agent",
                "[1-2/3] Scraping and filtering skipped (using database articles)"
            )
        
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
        
        # Filter by confidence threshold (using config or PipelineConfig override)
        min_confidence_threshold = config.min_confidence_for_insights if config else MIN_CONFIDENCE
        high_conf_catalysts = [c for c in catalysts if c.confidence >= min_confidence_threshold]
        high_conf_risks = [r for r in risks if r.confidence >= min_confidence_threshold]
        high_conf_mitigations = [m for m in mitigations if m.confidence >= min_confidence_threshold]
        
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
