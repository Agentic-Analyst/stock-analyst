#!/usr/bin/env python3
"""
main.py - Comprehensive Stock Analysis Pipeline

This module orchestrates the complete 7-step stock analysis workflow:
1. Financial Scraping - Collect financial statements and company data  
2. Financial Model Generation - Build DCF models with LLM-powered strategy selection and parameter optimization
3. News Scraping - Collect recent news articles from Google News
4. Article Filtering - Filter for relevance and quality  
5. Article Screening - Extract investment insights using LLM
6. Price Adjustment - Combine quantitative model with qualitative factors
7. Professional Report Generation - Generate analyst-style research report with LLM synthesis

Enhanced Features:
- LLM-powered automatic DCF strategy selection (saas_dcf, reit_dcf, bank_excess_returns, etc.)
- Agentic parameter generation with AI-optimized WACC, terminal growth, and modeling assumptions
- Deterministic event→parameter mapping with audit logging
- Configuration-driven defaults and guardrails with manual override options
- Comprehensive audit trail for conversions and overrides
- Integrated Excel/CSV export with scenario comparison

▶ Usage Examples:
    # Full LLM-powered analysis (AI selects strategy and optimizes parameters)
    python main.py --ticker NVDA --pipeline comprehensive
    
    # LLM analysis with manual strategy override
    python main.py --ticker AAPL --pipeline comprehensive --strategy hardware_dcf
    
    # Traditional analysis without LLM (deterministic defaults)
    python main.py --ticker TSLA --pipeline comprehensive --wacc 0.095

    # Force manual overrides even with LLM enabled
    python main.py --ticker MSFT --pipeline comprehensive --term-growth 0.025
"""

from __future__ import annotations
import argparse
import pathlib
import sys
from dataclasses import asdict
from typing import Optional, Dict, List, Any, Tuple
from datetime import datetime
import json
import time

from src.config import MAX_ARTICLES

# Add src directory to path for imports
sys.path.insert(0, str(pathlib.Path(__file__).parent / "src"))

# Import all pipeline modules
from logger import setup_logger, StockAnalystLogger
from financial_scraper import FinancialScraper
# NEW: Use the rewritten financial model builder from agents/fm
from agents.fm import create_financial_model
from article_scraper import ArticleScraper
from article_filter import ArticleFilter
from article_screener import ArticleScreener
# NEW: Price adjustor for news-based model adjustment (V2 - builds from scratch)
# from price_adjustor import adjust_price
from path_utils import get_analysis_path, ensure_analysis_paths
from report_agent import generate_and_save_professional_report
# NEW: Daily company news intelligence report
from agents.news.daily.company_daily_report import CompanyDailyReportGenerator
from agents.news.daily.sector_daily_report import SectorDailyReportGenerator
import yfinance as yf
# Import LLM system
from llms.config import init_llm, list_models, list_available_models
from dotenv import load_dotenv
load_dotenv()
import traceback
import asyncio

# Import supervisor workflow
from src.agents.supervisor.supervisor_agent import SupervisorWorkflowRunner

class ComprehensiveStockAnalysisPipeline:
    """Integrated 7-step pipeline for complete stock analysis workflow."""

    def __init__(self, ticker: str, email: str, timestamp: str):
        """
        Initialize the comprehensive analysis pipeline.
        
        Args:
            ticker: Stock ticker symbol (e.g., 'NVDA')
            company_name: Full company name (e.g., 'NVIDIA')
            email: User's email for data organization
        """
        self.ticker = ticker.upper()
        self.company_name = yf.Ticker(self.ticker).info.get("longName")
        self.email = email.lower()
        self.timestamp = timestamp
        
        # Generate timestamped analysis path
        self.analysis_path = get_analysis_path(self.email, self.ticker, self.timestamp)
        ensure_analysis_paths(self.analysis_path)
        
        # Setup centralized logging with analysis path
        self.logger = setup_logger(self.ticker, base_path=self.analysis_path)
        
        # Initialize pipeline components with analysis path
        self.financial_scraper = FinancialScraper(self.ticker, base_path=self.analysis_path)
        self.model_generator = None  # Initialized when needed with data file
        self.article_scraper = ArticleScraper(self.ticker, self.company_name, base_path=self.analysis_path)
        # ArticleFilter will be initialized when needed with specific query
        self.article_filter = None
        self.article_screener = ArticleScreener(self.ticker, base_path=self.analysis_path)
        
        # Pass logger to components that support it
        for component in [self.financial_scraper, self.article_scraper, self.article_screener]:
            if hasattr(component, 'set_logger'):
                component.set_logger(self.logger)
        
        # Pipeline tracking
        self.stats = {
            "start_time": datetime.now(),
            "stages_completed": [],
            "financial_scraping": {},
            "model_generation": {},
            "news_scraping": {},
            "article_filtering": {},
            "article_screening": {},
            "price_adjustment": {},
            "report_generation": {}
        }
        
        # Store company data for use across pipeline stages
        self.company_data = {}
        
        self.logger.info(f"🎯 Pipeline initialized for {self.ticker} ({self.company_name})")
        self.logger.info(f"📊 All logs will be saved to: {self.logger.get_log_file_path()}")
    
    def run_comprehensive_pipeline(self,
                                  query_override: Optional[str] = None) -> Dict:
        """
        Run the complete analysis pipeline.
        
        Pipeline Stages:
        1. Financial Scraping - Collect financial statements
        2. Financial Model Generation - Build banker-grade DCF model (LLM-powered)
        3. News Analysis - Smart workflow:
           a) Check database for existing filtered articles
           b) If found (recent run): Load from DB → Screen
           c) If not found: Scrape → Filter → Save to DB → Screen
        4. Price Adjustment - Build adjusted model based on news insights (NEW in V2)
        5. Report Generation - Generate professional analyst report
        
        Workflow Optimization:
        - First run: Full news pipeline (scrape → filter → save to DB → screen)
        - Subsequent runs: Fast path (load from DB → screen)
        - Saves costs by avoiding re-scraping and re-filtering
        
        New in V2:
        - Price adjustment now builds a brand new model from scratch
        - Original model preserved for comparison
        - All tab builders reused automatically
        
        Args:
            max_searched: Maximum articles to search/scrape (only used if DB empty)
            query_override: Override default search query for news articles
            min_filter_score: Minimum relevance score for filtering (0-10)
            min_confidence: Minimum confidence for screening insights (0-1)
            
        Returns:
            Dictionary with complete pipeline results
        """
        self.logger.stage_start(
            "COMPREHENSIVE PIPELINE", 
            f"Analyzing {self.company_name} ({self.ticker}) with 7-step workflow"
        )
        
        # Step 1: Financial Scraping
        self.logger.stage_start("FINANCIAL SCRAPING", "Collecting financial statements and company data")
        financial_results = self.run_financial_scraping_stage()
        
        if financial_results.get("success"):
            # Step 2: Financial Model Generation
            self.logger.stage_start("FINANCIAL MODEL GENERATION", "Building DCF model with LLM-inferred assumptions")
            model_results = self.run_model_generation_stage()
        else:
            self.logger.error("❌ Skipping model generation due to failed financial scraping")
            model_results = {"success": False, "reason": "Financial scraping failed"}
        
        if not model_results.get("success"):
            self.logger.error("❌ Financial model generation failed. Continuing with news analysis...")
        
        # Step 3-5: Smart News Analysis Workflow
        self.logger.stage_start("NEWS ANALYSIS", "Analyzing news articles for investment insights")
        
        # Check if we have recent articles in the database to avoid re-scraping
        self.logger.info("🔍 Checking for existing filtered articles in database...")
        existing_articles = self.article_screener.load_articles_from_db(limit=MAX_ARTICLES)

        if len(existing_articles) >= MAX_ARTICLES:
            # Fast path: Articles already in database
            self.logger.info(f"✅ Found {len(existing_articles)} recent articles in database")
            self.logger.info("⚡ Fast path: Skipping scraping & filtering, loading from database")

            # Go directly to screening with database articles
            self.logger.stage_start("ARTICLE SCREENING", "Extracting investment insights using LLM")
            screening_results = self.run_screening_stage(articles_data=existing_articles)
            
            skip_scraping = True
        else:
            # Need to scrape: Not enough articles in database
            self.logger.info(f"⚠️  Only found {len(existing_articles)} articles in database (need {MAX_ARTICLES})")
            self.logger.info("🔄 Full pipeline: Will scrape → filter → save to DB → screen")
            skip_scraping = False

        if not skip_scraping:
            # Full news pipeline: Scrape → Filter → Save to DB → Screen
            
            # Step 3a: Scrape news articles
            self.logger.stage_start("ARTICLE SCRAPING", "Collecting news articles from Google News")
            # Full news pipeline: Scrape → Filter → Save to DB → Screen
            news_results = self.run_news_scraping_stage(query_override)
            
            # Step 3b: Filter articles and save to database
            self.logger.stage_start("ARTICLE FILTERING", "Filtering articles for relevance using LLM and saving to database")
            # Generate default query if none provided
            filter_query = query_override or f"{self.company_name} financial outlook earnings growth investment analysis"
            filtering_results = self.run_filtering_stage(filter_query)
            
            # Step 3c: Screen articles for investment insights
            self.logger.stage_start("ARTICLE SCREENING", "Extracting investment insights using LLM")
            screening_results = self.run_screening_stage()
                
        # Step 7: Professional Report Generation (if model and screening succeeded)
        if model_results.get("success") and screening_results:
            self.logger.stage_start("PROFESSIONAL REPORT GENERATION", "Generating comprehensive analyst-style research report")
            try:
                # NEW: Use rewritten report agent that collects data from all pipeline outputs
                report, report_path = generate_and_save_professional_report(
                    self.analysis_path,
                    self.ticker,
                    self.logger  # Pass logger instance
                )
                
                self.logger.info(f"✅ Professional report generated successfully")
                self.logger.info(f"   Report length: {len(report):,} characters")
                self.logger.info(f"   Saved to: {report_path}")
                
                self.stats["report_generated"] = True
                self.stats["report_path"] = str(report_path)
                self.stats["stages_completed"].append("report_generation")
                
            except Exception as e:
                self.logger.warning(f"⚠️  Failed to generate professional report: {e}")
                self.stats["report_generated"] = False
        else:
            self.logger.info("⏭️  Skipping report generation (prerequisites not met)")
            self.stats["report_generated"] = False

        # Pipeline completion
        duration = (datetime.now() - self.stats["start_time"]).total_seconds()
        self.logger.session_end(duration, self.stats["stages_completed"])
        
        return self._get_comprehensive_pipeline_results()
    
    def run_financial_scraping_stage(self) -> Dict:
        """Run the financial data scraping stage."""
        try:
            self.logger.info(f"📊 Scraping financial data for {self.ticker}...")
            
            # Scrape comprehensive financial data for modeling
            financial_data = self.financial_scraper.scrape_financial_modeling_data(annual=True)

            if self.financial_scraper.failed_statements:
                self.logger.warning(f"⚠️  Some financial statements failed to scrape: {self.financial_scraper.failed_statements}")
                return {"success": False, "error": "Failed to scrape all required financial statements"}
            
            # Save the financial data to file for the model generator to use
            file_path = self.financial_scraper.save_financial_data(financial_data)
            self.logger.info(f"💾 Financial data saved to: {file_path}")
            
            # Update statistics
            data_completeness = financial_data.get("data_summary", {}).get("data_completeness", {})
            financial_statements = financial_data.get("financial_statements", {})
            company_data = financial_data.get("company_data", {})
            
            # Extract useful company information
            basic_info = company_data.get("basic_info", {})
            market_data = company_data.get("market_data", {})
            
            self.stats["financial_scraping"] = {
                "success": True,
                "income_periods": data_completeness.get("income_statement_periods", 0),
                "balance_periods": data_completeness.get("balance_sheet_periods", 0),
                "cashflow_periods": data_completeness.get("cash_flow_periods", 0),
                "company_info_available": data_completeness.get("company_data_available", False),
                # Add company context from scraped data
                "company_context": {
                    "sector": basic_info.get("sector"),
                    "industry": basic_info.get("industry"),
                    "employees": basic_info.get("employees"),
                    "current_price": market_data.get("current_price"),
                    "shares_outstanding": market_data.get("shares_outstanding_basic")
                }
            }
            self.stats["stages_completed"].append("financial_scraping")
            
            # Store company data for pipeline use
            self.company_data = company_data
            
            # Enhanced logging with company context
            company_context = ""
            if basic_info.get("sector") and basic_info.get("industry"):
                company_context = f" ({basic_info['sector']} - {basic_info['industry']})"
            if basic_info.get("employees"):
                company_context += f" • {basic_info['employees']:,} employees"
            if market_data.get("current_price"):
                company_context += f" • Current: ${market_data['current_price']:.2f}"
            
            if company_context:
                self.logger.info(f"🏢 Company: {basic_info.get('long_name', self.company_name)}{company_context}")
            
            # Log results
            stats = {
                "Years of data": data_completeness.get("income_statement_periods", 0),
                "Statement types": len([k for k in financial_statements.keys() if financial_statements.get(k)]),
                "Company info": "✓" if data_completeness.get("company_data_available") else "✗"
            }
            self.logger.stage_end("FINANCIAL SCRAPING", True, stats)
            
            return {"success": True, "financial_data": financial_data}
            
        except Exception as e:
            self.logger.error(f"❌ Financial scraping failed: {e}")
            return {"success": False, "error": str(e)}
    
    def run_model_generation_stage(self) -> Dict:
        """Run the financial model generation stage using NEW FinancialModelBuilder.
        
        The NEW implementation:
        - Always generates comprehensive 9-tab banker-grade DCF model
        - Always uses LLM to automatically infer assumptions (WACC, terminal growth, etc.)
        - Always projects 5 years forward (FY1-FY5)
        - Outputs Excel file only (no Python dict)
        """
        try:
            self.logger.info(f"🔢 Generating banker-grade DCF model for {self.ticker}...")
            
            # Find the latest modeling JSON file
            json_file = self.analysis_path / "financials" / "financials_annual_modeling_latest.json"
            
            if not json_file.exists():
                self.logger.error(f"❌ Financial data file not found: {json_file}")
                return {"success": False, "error": "Financial data file not found"}
            
            # Create output path
            output_file = self.analysis_path / "models" / f"{self.ticker}_financial_model.xlsx"
            output_file.parent.mkdir(parents=True, exist_ok=True)
            
            # Build the model using NEW FinancialModelBuilder
            # This automatically calls LLM to infer all assumptions
            self.logger.info(f"📊 Building model with LLM-inferred assumptions...")
            
            builder = create_financial_model(
                ticker=self.ticker,
                json_path=str(json_file),
                output_path=str(output_file),
                logger=self.logger
            )
            
            self.logger.info(f"✅ Model saved to Excel: {output_file}")
            
            # NEW: Evaluate all formulas and save to JSON
            self.logger.info(f"🧮 Evaluating formulas and generating computed values JSON...")
            json_output_path = output_file.parent / f"{self.ticker}_financial_model_computed_values.json"
            
            try:
                builder.evaluate_and_save_json(json_output_path)
                self.logger.info(f"✅ Computed values saved to: {json_output_path}")
            except Exception as eval_error:
                self.logger.warning(f"⚠️  Formula evaluation encountered issues: {eval_error}")
                # Continue execution even if evaluation fails
            
            # Update statistics
            self.stats["model_generation"] = {
                "model_type": "comprehensive_dcf",
                "projection_years": 5,
                "strategy_used": "llm_inferred",
                "excel_path": str(output_file),
                "tabs_generated": 10,  # 9 visible + 1 hidden LLM_Inferred
                "computed_values_json": str(json_output_path) if json_output_path.exists() else None
            }
            self.stats["stages_completed"].append("model_generation")
            
            # Log results
            stats = {
                "Model type": "Banker-grade DCF (9 tabs)",
                "Implementation": "NEW FinancialModelBuilder",
                "Tabs": "Raw, Keys_Map, Assumptions, Historical, Projections, 2×DCF, Sensitivity, Summary",
                "LLM": "Assumptions automatically inferred",
                "Excel file": str(output_file.name),
                "JSON computed values": str(json_output_path.name) if json_output_path.exists() else "N/A"
            }
            self.logger.stage_end("FINANCIAL MODEL GENERATION", True, stats)
            
            return {"success": True, "excel_path": str(output_file)}
            
        except Exception as e:
            self.logger.error(f"❌ Financial model generation failed: {e}")
            # self.logger.error(traceback.format_exc())
            return {"success": False, "error": str(e)}
    
    def run_news_scraping_stage(self, query_override: Optional[str] = None) -> Dict:
        """Run the news article scraping stage.
        
        ArticleScraper loads max_articles from config internally.
        """
        try:
            # Check current storage status
            storage_info = self.article_scraper.get_storage_info()
            current_count = storage_info["total_articles"]
            
            self.logger.info(f"📊 Current articles in storage: {current_count}")
            
            # Perform comprehensive scraping
            scraping_results = self.article_scraper.run_comprehensive_scraping(query_override=query_override)
            # Record pre-existing corpus size for downstream logic (news-only reuse)
            scraping_results['pre_existing'] = current_count
            
            # Update statistics
            self.stats["news_scraping"] = scraping_results
            self.stats["stages_completed"].append("news_scraping")
            
            # Log results
            stats = {
                "New articles": scraping_results['scraped_count'],
                "Duplicates skipped": scraping_results['duplicate_count'],
                "Failed attempts": scraping_results['failed_count'],
                "Success rate": f"{scraping_results['success_rate']:.1%}"
            }
            self.logger.stage_end("NEWS SCRAPING", True, stats)
            
            return scraping_results
            
        except Exception as e:
            self.logger.error(f"❌ News scraping stage failed: {e}")
            return {"scraped_count": 0, "error": str(e)}
    
    def run_filtering_stage(self, query: str) -> Dict:
        """Run the article filtering stage with LLM-powered intelligence.
        """
        try:
            # Initialize article filter with query (required for LLM filtering)
            if not self.article_filter:
                self.article_filter = ArticleFilter(self.ticker, query, base_path=self.analysis_path)
                if hasattr(self.article_filter, 'set_logger'):
                    self.article_filter.set_logger(self.logger)
            
            # Perform LLM-powered filtering
            result = self.article_filter.filter_articles()

            if not result.get("filtered_articles"):
                self.logger.warning("⚠️  No articles met the filtering criteria")
                return {"filtered_articles": [], "filtered_count": 0, "llm_cost": 0.0}
            
            # Note: LLM report generation removed to save costs
            # Filtered articles are available in filtered/ directory with rankings
            
            # Update statistics
            filtering_results = {
                "filtered_articles": result["filtered_articles"],
                "filtered_count": len(result["filtered_articles"]),
                "min_score_used": self.article_filter.min_score,
                "query_used": query,
                "llm_cost": result.get("llm_cost", 0.0),
                "llm_calls": result.get("llm_calls", 0),
                "avg_score": sum(article["llm_score"] for article in result["filtered_articles"]) / len(result["filtered_articles"]) if result["filtered_articles"] else 0
            }
            self.stats["article_filtering"] = filtering_results
            self.stats["stages_completed"].append("article_filtering")
            
            # Log results
            stats = {
                "Articles meeting criteria": len(result["filtered_articles"]),
                "Average LLM score": f"{filtering_results['avg_score']:.2f}",
                "LLM cost": f"${result.get('llm_cost', 0):.4f}",
                "Query used": query[:50] + "..." if len(query) > 50 else query
            }

            # Log filtered articles
            self.logger.info(f"📄 Filtered {len(result['filtered_articles'])} articles:")
            for i, article in enumerate(result["filtered_articles"], 1):
                title = article["title"]
                self.logger.info(f"   {i}. {title}")
            
            self.logger.stage_end("ARTICLE FILTERING", True, stats)
            
            return filtering_results
            
        except Exception as e:
            self.logger.error(f"❌ Article filtering stage failed: {e}")
            return {"filtered_articles": [], "filtered_count": 0, "error": str(e)}
    
    def run_screening_stage(self, articles_data: Optional[List[Dict]] = None) -> Dict:
        """Run the article screening/analysis stage.
        
        ArticleScreener loads min_confidence from config internally.
        
        Args:
            articles_data: Optional list of filtered articles. If None, will try to load from database first.
        """
        try:
            self.logger.info("📂 Loading articles from database...")
            if articles_data is None:
                articles_data = self.article_screener.load_articles_from_db(limit=50)
            
            self.logger.info(f"🔍 Analyzing {len(articles_data)} articles with LLM...")
            
            # Extract insights using LLM (efficient single-pass analysis)
            catalysts, risks, mitigations, analysis_summary = self.article_screener.analyze_all_articles(articles_data)
            
            # Filter by confidence (using config value)
            high_conf_catalysts = [c for c in catalysts if c.confidence >= self.article_screener.min_confidence]
            high_conf_risks = [r for r in risks if r.confidence >= self.article_screener.min_confidence]
            high_conf_mitigations = [m for m in mitigations if m.confidence >= self.article_screener.min_confidence]
            
            # Update statistics
            screening_results = {
                "catalysts": high_conf_catalysts,
                "risks": high_conf_risks,
                "mitigations": high_conf_mitigations,
                "total_catalysts": len(catalysts),
                "total_risks": len(risks),
                "total_mitigations": len(mitigations),
                "llm_cost": self.article_screener.total_llm_cost,
                "llm_calls": self.article_screener.llm_call_count
            }
            self.stats["article_screening"] = screening_results
            self.stats["stages_completed"].append("article_screening")
            
            # Generate reports (always enabled in production)
            data_file = self.analysis_path / "screened" / "screening_data.json"
            self.article_screener.save_structured_data(
                high_conf_catalysts, high_conf_risks, high_conf_mitigations, analysis_summary, data_file
            )
            self.logger.file_operation("Structured data saved", data_file)
            
            # Log results
            stats = {
                "Growth catalysts": f"{len(high_conf_catalysts)} (of {len(catalysts)} total)",
                "Risks identified": f"{len(high_conf_risks)} (of {len(risks)} total)",
                "Mitigation strategies": f"{len(high_conf_mitigations)} (of {len(mitigations)} total)",
                "LLM cost": f"${screening_results['llm_cost']:.6f} USD ({screening_results['llm_calls']} calls)"
            }
            self.logger.stage_end("LLM ANALYSIS & SCREENING", True, stats)
            
            # Persist artifact paths
            screening_results['data_file'] = str(data_file) if data_file else None
            return screening_results
            
        except Exception as e:
            self.logger.error(f"❌ Screening stage failed: {e}")
            return {"catalysts": [], "risks": [], "mitigations": [], "error": str(e)}
    
    def run_company_daily_report_stage(self) -> Dict:
        """Run the company daily news intelligence report generation stage.
        
        This stage:
        1. Fetches last 24 hours of news from database
        2. Fetches company data (sector, industry, etc.) from financial scraper
        3. Generates company daily report (catalysts, risks, price action)
        
        Returns:
            Dictionary with report generation results
        """
        try:
            self.logger.stage_start("COMPANY DAILY REPORT", "Generating company daily news intelligence report")
            
            # Step 1: Get company data from financial scraper (for sector, industry, etc.)
            self.logger.info("📊 Fetching company information...")
            try:
                company_data = self.financial_scraper.scrape_comprehensive_company_data()
                basic_info = company_data.get("basic_info", {})
                company_name = basic_info.get("long_name", self.company_name)
                market_data = company_data.get("market_data", {})
                
                company_info = {
                    'company_name': company_name,
                    'sector': basic_info.get('sector', 'Unknown'),
                    'industry': basic_info.get('industry', 'Unknown'),
                    'market_cap': market_data.get('market_cap', 'Unknown')
                }
                
                self.logger.info(f"✅ Company data: {company_info['sector']} sector, {company_info['industry']} industry")
                
            except Exception as e:
                self.logger.warning(f"⚠️  Could not fetch company data: {e}. Using defaults.")
                company_info = {
                    'company_name': self.company_name,
                    'sector': 'Unknown',
                    'industry': 'Unknown',
                    'market_cap': 'Unknown'
                }
            
            # Step 2: Initialize reports directory
            reports_dir = self.analysis_path / "reports"
            
            # Generate Company Daily Report
            self.logger.info("=" * 60)
            self.logger.info("📄 GENERATING COMPANY DAILY REPORT")
            self.logger.info("=" * 60)
            
            daily_report_generator = CompanyDailyReportGenerator(
                ticker=self.ticker,
                output_dir=reports_dir,
                logger=self.logger  # Pass the main pipeline logger
            )
            
            self.logger.info("📝 Generating company daily intelligence report...")
            company_report = daily_report_generator.generate_daily_report(company_info=company_info)
            company_llm_cost = daily_report_generator.total_llm_cost
            
            self.logger.info(f"✅ Company report generated (Cost: ${company_llm_cost:.4f})")
            
            # Update Statistics
            self.stats["company_daily_report"] = {
                "success": True,
                "company_report_generated": True,
                "company_llm_cost": company_llm_cost,
                "sector": company_info.get('sector', 'Unknown'),
                "report_path": str(reports_dir)
            }
            self.stats["stages_completed"].append("company_daily_report")
            
            # Log results
            stats = {
                "Company report": "✓",
                "Sector": company_info.get('sector', 'Unknown'),
                "LLM cost": f"${company_llm_cost:.4f}",
                "Output directory": str(reports_dir)
            }
            self.logger.stage_end("COMPANY DAILY REPORT", True, stats)
            
            return {
                "success": True,
                "company_report": company_report,
                "company_llm_cost": company_llm_cost,
                "sector": company_info.get('sector', 'Unknown')
            }
            
        except Exception as e:
            self.logger.error(f"❌ Company daily report generation failed: {e}")
            self.logger.error(traceback.format_exc())
            return {"success": False, "error": str(e)}
    
    def run_sector_daily_report_stage(self) -> Dict:
        """Run the sector daily news intelligence report generation stage.
        
        This stage:
        1. Fetches last 24 hours of sector-wide news from database
        2. Analyzes sector-level catalysts and trends
        3. Generates sector daily report (sector catalysts, rotation trends, company movers)
        
        Args:
            sector: Sector name (e.g., 'TECHNOLOGY', 'HEALTHCARE')
        
        Returns:
            Dictionary with report generation results
        """
        try:
            sector = self.ticker
            self.logger.stage_start("SECTOR DAILY REPORT", f"Generating sector daily news intelligence report for {sector}")
            
            # Initialize reports directory
            reports_dir = self.analysis_path / "reports"
            reports_dir.mkdir(parents=True, exist_ok=True)
            
            # Generate Sector Daily Report
            self.logger.info("=" * 60)
            self.logger.info(f"📊 GENERATING SECTOR DAILY REPORT: {sector}")
            self.logger.info("=" * 60)
            
            sector_report_generator = SectorDailyReportGenerator(
                sector=sector,
                output_dir=reports_dir,
                logger=self.logger  # Pass the main pipeline logger
            )
            
            self.logger.info(f"📝 Generating sector daily report for {sector}...")
            sector_report_path = sector_report_generator.generate_sector_report()
            sector_llm_cost = sector_report_generator.total_llm_cost
            
            if sector_report_path:
                self.logger.info(f"✅ Sector report generated (Cost: ${sector_llm_cost:.4f})")
                self.logger.info(f"📄 Sector report saved to: {sector_report_path}")
            else:
                self.logger.warning("⚠️  Sector report generation returned None")
                return {"success": False, "error": "Report generation returned None"}
            
            # Update Statistics
            self.stats["sector_daily_report"] = {
                "success": True,
                "sector_report_generated": True,
                "sector_llm_cost": sector_llm_cost,
                "sector": sector,
                "report_path": str(sector_report_path)
            }
            self.stats["stages_completed"].append("sector_daily_report")
            
            # Log results
            stats = {
                "Sector report": "✓",
                "Sector": sector,
                "LLM cost": f"${sector_llm_cost:.4f}",
                "Output file": str(sector_report_path.name)
            }
            self.logger.stage_end("SECTOR DAILY REPORT", True, stats)
            
            return {
                "success": True,
                "sector_report_path": str(sector_report_path),
                "sector_llm_cost": sector_llm_cost,
                "sector": sector
            }
            
        except Exception as e:
            self.logger.error(f"❌ Sector daily report generation failed: {e}")
            self.logger.error(traceback.format_exc())
            return {"success": False, "error": str(e)}
    
    def _get_comprehensive_pipeline_results(self) -> Dict:
        """Get complete comprehensive pipeline results."""
        self.stats["end_time"] = datetime.now()
        self.stats["total_duration"] = (self.stats["end_time"] - self.stats["start_time"]).total_seconds()
        return {
            "ticker": self.ticker,
            "company_name": self.company_name,
            "pipeline_type": "comprehensive_7_step",
            "statistics": self.stats
        }
    
    def _get_pipeline_results(self) -> Dict:
        """Get complete pipeline results."""
        self.stats["end_time"] = datetime.now()
        self.stats["total_duration"] = (self.stats["end_time"] - self.stats["start_time"]).total_seconds()
        return {
            "ticker": self.ticker,
            "company_name": self.company_name,
            "statistics": self.stats
        }
    
def _print_pipeline_failure_summary(pipeline):
    """Print time and cost summary when pipeline fails."""
    try:
        if hasattr(pipeline, 'stats') and hasattr(pipeline, 'logger'):
            end_time = datetime.now()
            start_time = pipeline.stats.get("start_time", end_time)
            duration = (end_time - start_time).total_seconds()
            
            pipeline.logger.info("")
            pipeline.logger.info("=" * 80)
            pipeline.logger.info("📊 FAILURE SUMMARY")
            pipeline.logger.info("=" * 80)
            pipeline.logger.info(f"   Total Duration: {duration:.2f}s")
            pipeline.logger.info("=" * 80)
            pipeline.logger.info("")
    except Exception:
        pass  # Silently ignore if we can't print summary

def _print_supervisor_failure_summary(supervisor_runner):
    """Print time and cost summary when supervisor fails."""
    try:
        if hasattr(supervisor_runner, 'stats') and hasattr(supervisor_runner, 'logger'):
            end_time = datetime.now()
            start_time = supervisor_runner.stats.get("start_time", end_time)
            duration = (end_time - start_time).total_seconds()
            
            # Get LLM cost if available
            llm_cost = 0.0
            if hasattr(supervisor_runner, 'state') and supervisor_runner.state and hasattr(supervisor_runner.state, 'total_llm_cost'):
                llm_cost = supervisor_runner.state.total_llm_cost
            
            supervisor_runner.logger.info("")
            supervisor_runner.logger.info("=" * 80)
            supervisor_runner.logger.info("📊 FAILURE SUMMARY")
            supervisor_runner.logger.info("=" * 80)
            if hasattr(supervisor_runner, 'ticker') and supervisor_runner.ticker:
                supervisor_runner.logger.info(f"   Ticker: {supervisor_runner.ticker} ({supervisor_runner.company_name or 'Unknown'})")
            supervisor_runner.logger.info(f"   Total Duration: {duration:.2f}s")
            supervisor_runner.logger.info(f"   💰 Total LLM Cost: ${llm_cost:.4f}")
            if hasattr(supervisor_runner.stats, '__getitem__'):
                iterations = supervisor_runner.stats.get("iterations", 0)
                agents_executed = supervisor_runner.stats.get("agents_executed", [])
                supervisor_runner.logger.info(f"   Iterations: {iterations}")
                supervisor_runner.logger.info(f"   Agents Executed: {len(agents_executed)}")
            supervisor_runner.logger.info("=" * 80)
            supervisor_runner.logger.info("")
    except Exception:
        pass  # Silently ignore if we can't print summary

def main():
    """Main entry point for the comprehensive stock analysis pipeline."""
    parser = argparse.ArgumentParser(
        description="Comprehensive Stock Analysis Pipeline with Banker-Grade DCF Model",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Full analysis (financial model + news analysis + reports)
  python main.py --ticker NVDA --email user@example.com --timestamp 20250101_120000
  
  # Use Claude Sonnet for LLM analysis
  python main.py --ticker AAPL --email user@example.com --timestamp 20250101_120000 --llm claude-3.5-sonnet
  
  # Just build financial model
  python main.py --ticker MSFT --email user@example.com --timestamp 20250101_120000 --pipeline financial-model
  
  # Generate daily news intelligence report
  python main.py --ticker NVDA --email user@example.com --timestamp 20250101_120000 --pipeline company-daily-report
  
  # Generate sector daily intelligence report
  python main.py --ticker NVDA --email user@example.com --timestamp 20250101_120000 --pipeline sector-daily-report --sector TECHNOLOGY
  
  # Supervisor agent (AI-powered agentic workflow with natural language prompt)
  python main.py --email user@example.com --timestamp 20250101_120000 --pipeline chat --prompt "Analyze NVDA comprehensively with focus on AI chip market"
  
  # List available models
  python main.py --list-llms
        """
    )
    
    # Required arguments
    parser.add_argument("--ticker", help="Stock ticker symbol (e.g., NVDA)")
    parser.add_argument("--email", help="User email for data organization")
    parser.add_argument("--timestamp", help="Custom timestamp for analysis folder (YYYYMMDD_HHMMSS)")
    # Supervisor pipeline parameters
    parser.add_argument("--user-prompt", help="Natural language prompt for supervisor agent (e.g., 'Analyze NVDA comprehensively')")
    parser.add_argument("--session-id", help="Custom session ID for continuous chat (empty means starting a new session)")

    # Pipeline control
    parser.add_argument("--pipeline", 
                       choices=["comprehensive", "financial-statements", "financial-model", "search-news",
                                "screen-news", "company-daily-report", "sector-daily-report", "chat"], 
                       default="comprehensive", 
                       help="Pipeline stages to execute")
    
    # News analysis parameters (using centralized config defaults)
    parser.add_argument("--query", help="Override default search query for news articles")
        
    # LLM selection parameters
    parser.add_argument("--llm", choices=["gpt-4o-mini", "claude-3.5-sonnet", "claude-3.5-haiku", "claude-3-opus"], 
                       default="gpt-4o-mini", help="LLM model to use for analysis")
    parser.add_argument("--list-llms", action="store_true", help="List available LLM models and exit")
    
    args = parser.parse_args()
    
    # Handle --list-llms flag first
    if args.list_llms:
        all_models = list_models()
        available_models = list_available_models()
        
        print("Available LLM models:")
        for model in all_models:
            if model in available_models:
                print(f"  ✅ {model}")
            else:
                print(f"  ❌ {model} (API key missing)")
        
        if not available_models:
            print("\nNo models available. Set OPENAI_API_KEY or ANTHROPIC_API_KEY environment variables.")
        
        return 0
    
    # Check required arguments based on pipeline
    if args.pipeline == "chat":
        # Chat pipeline needs email, timestamp, and user prompt
        if not all([args.email, args.timestamp, args.user_prompt]):
            parser.error("--email, --timestamp, and --user-prompt are required for chat pipeline")
    else:
        # Other pipelines need ticker, email, timestamp
        if not all([args.ticker, args.email, args.timestamp]):
            parser.error("--ticker, --email, and --timestamp are required for analysis operations")
            
    try:
        # Initialize LLM model
        init_llm(args.llm)

        # Initialize comprehensive pipeline (skip for chat)
        if args.pipeline != "chat":
            pipeline = ComprehensiveStockAnalysisPipeline(args.ticker, args.email, args.timestamp)
        
        # Run selected pipeline
        if args.pipeline == "comprehensive":
            results = pipeline.run_comprehensive_pipeline(
                # News analysis parameters (using config defaults)
                query_override=args.query
            )
        
        elif args.pipeline == "financial-statements":
            results = pipeline.run_financial_scraping_stage()

        elif args.pipeline == "financial-model":
            financial_results = pipeline.run_financial_scraping_stage()
            if financial_results.get("success"):
                results = pipeline.run_model_generation_stage()
            else:
                results = financial_results

        elif args.pipeline == "search-news":
            # Search-news pipeline: Scrape → Filter → Save to DB
            # This prepares articles for later screening in comprehensive mode
            news_results = pipeline.run_news_scraping_stage(args.query)
            # Proceed to filtering if we either scraped new content OR have a pre-existing corpus
            if news_results.get("scraped_count", 0) > 0 or news_results.get('pre_existing', 0) > 0:
                # Generate default query if none provided
                filter_query = args.query or f"{pipeline.company_name} financial outlook earnings growth investment analysis"
                # Filter and save to database (no local file storage)
                results = pipeline.run_filtering_stage(filter_query)  # Uses config defaults
                pipeline.logger.info(f"✅ Articles filtered and saved to database for {pipeline.ticker}")
                pipeline.logger.info(f"💡 Tip: Run with --pipeline comprehensive to analyze these articles")
            else:
                results = news_results

        elif args.pipeline == "screen-news":
            # Screen-news pipeline: Load DB → Screen
            results = pipeline.run_screening_stage()  # Uses config default for min_confidence
        
        elif args.pipeline == "company-daily-report":
            # Company daily report pipeline: Fetch company data → Generate daily report
            results = pipeline.run_company_daily_report_stage()
        
        elif args.pipeline == "sector-daily-report":
            # Sector daily report pipeline: Generate sector-wide daily report
            results = pipeline.run_sector_daily_report_stage()
        
        elif args.pipeline == "chat":
            # Supervisor agentic pipeline: AI-powered multi-agent stock analysis workflow
            # The supervisor will automatically extract ticker from the prompt and initialize everything
            supervisor_runner = None
            try:
                supervisor_runner = SupervisorWorkflowRunner(
                    email=args.email,
                    timestamp=args.timestamp,
                    user_prompt=args.user_prompt,
                    session_id=args.session_id
                )
                    
                results = asyncio.run(supervisor_runner.run_workflow())
            except Exception as e:
                # If error happens before initialization, supervisor_runner.logger won't exist
                # So we log to console and also try to save to logger if it exists
                if supervisor_runner and supervisor_runner.logger:
                    supervisor_runner.logger.error(f"❌ Pipeline failed: {e}")
                    # Try to save session with error state if session was created
                    if supervisor_runner.session_manager and supervisor_runner.current_conversation_index is not None:
                        supervisor_runner.session_manager.update_conversation(
                            conversation_index=supervisor_runner.current_conversation_index,
                            completion_status="failed",
                            error_message=str(e)
                        )
                    # Print summary even on failure
                    _print_supervisor_failure_summary(supervisor_runner)
                    supervisor_runner.logger.program_end()
                else:
                    print(f"❌ Pipeline failed: {e}")
                time.sleep(3)
                return 1

        # Pipeline execution completed successfully
        if 'pipeline' in locals():
            pipeline.logger.program_end()
        time.sleep(3)
        return 0
        
    except KeyboardInterrupt:
        if 'pipeline' in locals():
            pipeline.logger.warning("\n⏹️  Pipeline interrupted by user")
            _print_pipeline_failure_summary(pipeline)
            pipeline.logger.program_end()
        elif 'supervisor_runner' in locals() and supervisor_runner.logger:
            supervisor_runner.logger.warning("\n⏹️  Pipeline interrupted by user")
            _print_supervisor_failure_summary(supervisor_runner)
            supervisor_runner.logger.program_end()
        else:
            print("\n⏹️  Pipeline interrupted by user")
        time.sleep(3)
        return 1
    except Exception as e:
        if 'pipeline' in locals():
            pipeline.logger.error(f"❌ Pipeline failed: {e}")
            _print_pipeline_failure_summary(pipeline)
            pipeline.logger.program_end()
        elif 'supervisor_runner' in locals() and supervisor_runner.logger:
            supervisor_runner.logger.error(f"❌ Pipeline failed: {e}")
            _print_supervisor_failure_summary(supervisor_runner)
            supervisor_runner.logger.program_end()
        else:
            print(f"❌ Pipeline failed: {e}")
        time.sleep(3)
        return 1

if __name__ == "__main__":
    exit(main())
