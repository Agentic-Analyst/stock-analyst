#!/usr/bin/env python3
"""
main.py - Comprehensive Stock Analysis Pipeline

This module orchestrates the complete 6-step stock analysis workflow:
1. Financial Scraping - Collect financial statements and company data  
2. Financial Model Generation - Build DCF models with LLM-powered strategy selection and parameter optimization
3. News Scraping - Collect recent news articles from Google News
4. Article Filtering - Filter for relevance and quality  
5. Article Screening - Extract investment insights using LLM
6. Price Adjustment - Combine quantitative model with qualitative factors

Enhanced Features:
- LLM-powered automatic DCF strategy selection (saas_dcf, reit_dcf, bank_excess_returns, etc.)
- Agentic parameter generation with AI-optimized WACC, terminal growth, and modeling assumptions
- Deterministic event→parameter mapping with audit logging
- Configuration-driven defaults and guardrails with manual override options
- Comprehensive audit trail for conversions and overrides
- Integrated Excel/CSV export with scenario comparison

▶ Usage Examples:
    # Full LLM-powered analysis (AI selects strategy and optimizes parameters)
    python main.py --ticker NVDA --company "NVIDIA" --pipeline comprehensive
    
    # LLM analysis with manual strategy override
    python main.py --ticker AAPL --company "Apple Inc" --pipeline comprehensive --strategy hardware_dcf
    
    # Traditional analysis without LLM (deterministic defaults)
    python main.py --ticker TSLA --company "Tesla" --pipeline comprehensive --wacc 0.095

    # Force manual overrides even with LLM enabled
    python main.py --ticker MSFT --company "Microsoft" --pipeline comprehensive --term-growth 0.025
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

# Add src directory to path for imports
sys.path.insert(0, str(pathlib.Path(__file__).parent / "src"))

# Import all pipeline modules
from logger import setup_logger, StockAnalystLogger
from financial_scraper import FinancialScraper
from financial_model_generator import FinancialModelGenerator  
from article_scraper import ArticleScraper
from article_filter import ArticleFilter
from article_screener import ArticleScreener
from price_adjustor import compute_adjustment, parse_screening_report
from event_param_mapping import aggregate_mapped_parameter_deltas, classify_event
from path_utils import get_analysis_path, ensure_analysis_paths
from reporting import build_llm_explanation, save_explanation_reports, build_deterministic_summary

class ComprehensiveStockAnalysisPipeline:
    """Integrated 6-step pipeline for complete stock analysis workflow."""

    def __init__(self, ticker: str, company_name: str, email: str, timestamp: str):
        """
        Initialize the comprehensive analysis pipeline.
        
        Args:
            ticker: Stock ticker symbol (e.g., 'NVDA')
            company_name: Full company name (e.g., 'NVIDIA')
            email: User's email for data organization
        """
        self.ticker = ticker.upper()
        self.company_name = company_name
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
        for component in [self.article_scraper, self.article_screener]:
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
            "price_adjustment": {}
        }
        
        # Store company data for use across pipeline stages
        self.company_data = {}
        
        self.logger.info(f"🎯 Comprehensive pipeline initialized for {self.ticker} ({self.company_name})")
        self.logger.info(f"📊 All logs will be saved to: {self.logger.get_log_file_path()}")
    
    def run_comprehensive_pipeline(self,
                                  # Financial modeling parameters
                                  model_type: str = "comprehensive",
                                  projection_years: int = 5,
                                  term_growth: Optional[float] = None,
                                  wacc_override: Optional[float] = None,
                                  strategy: Optional[str] = None,
                                  peers: Optional[str] = None,
                                  # News analysis parameters  
                                  max_searched: int = 20,
                                  query_override: Optional[str] = None,
                                  min_filter_score: float = 3.0,
                                  max_filtered: int = 10,
                                  min_confidence: float = 0.5,
                                  # Price adjustment parameters
                                  scaling: float = 0.15,
                                  adjustment_cap: float = 0.20,
                                  generate_reports: bool = True) -> Dict:
        """
        Run the complete 6-step analysis pipeline.
        
        Args:
            model_type: Financial model type ('dcf', 'comparable', 'comprehensive')
            projection_years: Number of projection years (default: 5)
            term_growth: Terminal growth rate (auto-infer if None)
            wacc_override: Override WACC (auto-infer if None)  
            strategy: Force specific forecast strategy (auto-select if None)
            peers: Comma-separated peer tickers for comparable analysis (e.g., 'AAPL,MSFT,GOOGL')
            max_searched: Maximum articles to search/scrape
            query_override: Override default search query for news articles
            min_filter_score: Minimum relevance score for filtering (0-10)
            max_filtered: Maximum filtered articles to keep
            min_confidence: Minimum confidence for screening insights (0-1)
            scaling: Base scaling factor for qualitative adjustment
            adjustment_cap: Maximum adjustment percentage (±)
            generate_reports: Whether to generate analysis reports
            
        Note: Deterministic event→parameter mapping and LLM scenarios are always enabled.
            
        Returns:
            Dictionary with complete pipeline results
        """
        self.logger.stage_start(
            "COMPREHENSIVE PIPELINE", 
            f"Analyzing {self.company_name} ({self.ticker}) with 6-step workflow"
        )
        
        # Step 1: Financial Scraping
        self.logger.stage_start("FINANCIAL SCRAPING", "Collecting financial statements and company data")
        financial_results = self.run_financial_scraping_stage()
        
        # Step 2: Financial Model Generation
        self.logger.stage_start("FINANCIAL MODEL GENERATION", "Building DCF and comparable models with LLM insights")
        model_results = self.run_model_generation_stage(
            model_type, projection_years, term_growth, wacc_override, strategy, peers
        )
        
        if not model_results.get("model"):
            self.logger.error("❌ Financial model generation failed. Cannot continue to price adjustment.")
            return self._get_pipeline_results()

        # Step 3: Article Scraping
        self.logger.stage_start("ARTICLE SCRAPING", "Collecting news articles from Google News")
        news_results = self.run_news_scraping_stage(max_searched, query_override)
        
        # Step 4: Article Filtering
        self.logger.stage_start("ARTICLE FILTERING", "Filtering articles for relevance and quality using LLM")
        # Generate default query if none provided
        filter_query = query_override or f"{self.company_name} financial outlook earnings growth investment analysis"
        filtering_results = self.run_filtering_stage(filter_query, min_filter_score, max_filtered)
        
        # Step 5: Article Screening
        self.logger.stage_start("ARTICLE SCREENING", "Extracting investment insights using LLM")
        screening_results = self.run_screening_stage(
            filtering_results.get("filtered_articles", []), min_confidence, generate_reports
        )
        
        # Step 6: Price Adjustment
        self.logger.stage_start("PRICE ADJUSTMENT", "Combining quantitative model with qualitative factors")
        price_results = self.run_price_adjustment_stage(
            model_results, screening_results, scaling, adjustment_cap  # Mapped deltas and LLM scenarios always enabled
        )

        # Generate analyst explanation report (LLM-enhanced) as part of the main workflow
        try:
            if price_results.get("success"):
                pa = price_results.get("price_analysis", {})
                def _to_dict(x):
                    try:
                        return asdict(x)
                    except Exception:
                        return x if isinstance(x, dict) else dict(x.__dict__) if hasattr(x, '__dict__') else {"value": x}
                factors = {
                    "catalysts": [_to_dict(c) for c in screening_results.get("catalysts", [])],
                    "risks": [_to_dict(r) for r in screening_results.get("risks", [])],
                    "mitigations": [_to_dict(m) for m in screening_results.get("mitigations", [])],
                }
                meta = {"model": model_type, "years": projection_years, "term_growth": term_growth}
                det_md = build_deterministic_summary(self.ticker, pa, factors, meta)
                self.logger.info(f"📝 Generating deterministic explanation report for {self.ticker}...")
                self.logger.info(f"📄 Deterministic explanation report content:\n{det_md}")
                llm_md = build_llm_explanation(self.ticker, pa, factors, argparse.Namespace(model=model_type, years=projection_years, term_growth=term_growth or 0.0, wacc=None))
                self.logger.info(f"📝 Generating LLM explanation report for {self.ticker}...")
                self.logger.info(f"📄 LLM explanation report content:\n{llm_md}")
                saved = save_explanation_reports(self.ticker, det_md, llm_md, self.analysis_path)
                self.logger.info(f"📝 Explanation report saved: {saved['path']} (latest: {saved['latest']})")
        except Exception as e:
            self.logger.warning(f"⚠️ Failed to generate explanation report: {e}")
        
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
            
            # Save the financial data to file for the model generator to use
            file_path = self.financial_scraper.save_financial_data(financial_data, annual=True, statements_scraped=["modeling"])
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
    
    def run_model_generation_stage(self, model_type: str, projection_years: int,
                                  term_growth: Optional[float], wacc_override: Optional[float],
                                  strategy: Optional[str], peers: Optional[str] = None) -> Dict:
        """Run the financial model generation stage."""
        try:
            # Initialize model generator with LLM control
            self.model_generator = FinancialModelGenerator(
                self.ticker, 
                data_file=None, 
                base_path=self.analysis_path, 
                email=self.email
            )
            # Inject centralized logger for unified output
            if hasattr(self.model_generator, 'set_logger'):
                self.model_generator.set_logger(self.logger)
            
            # Handle force overrides - if enabled, pre-populate overrides to bypass LLM agentic system
            if term_growth is not None:
                self.model_generator.overrides['terminal_growth'] = term_growth
            if wacc_override is not None:
                self.model_generator.overrides['wacc'] = wacc_override
            
            self.logger.info(f"🔢 Generating {model_type} model for {self.ticker}...")            
            # Parse peers if provided
            peer_list = None
            if peers:
                peer_list = [p.strip().upper() for p in peers.split(',') if p.strip().upper() != self.ticker]
                if peer_list:
                    self.logger.info(f"📊 Including peer comparison with: {', '.join(peer_list)}")
                else:
                    self.logger.info("⚠️ No valid peer tickers provided after filtering")
            
            # Generate comprehensive financial model
            model = self.model_generator.generate_financial_model(
                model_type=model_type,
                projection_years=projection_years,
                term_growth=term_growth,
                override_wacc=wacc_override,
                strategy=strategy,
                peers=peer_list,
                generate_sensitivities=True
            )
            
            # Save model outputs (always enabled in production)
            excel_path = None
            try:
                excel_path = self.model_generator.save_model_to_excel(model)
                self.logger.info(f"📊 Model saved to Excel: {excel_path}")
                self.logger.info(f"📁 Latest version available as: financial_model_{model_type}_latest.xlsx")
            except Exception as e:
                self.logger.warning(f"⚠️ Excel export failed: {e}")
                # Continue without Excel - model is still valid
            
            # Update statistics
            self.stats["model_generation"] = {
                "model_type": model_type,
                "projection_years": projection_years,
                "strategy_used": model.get("strategy_info", {}).get("name", "unknown"),
                "implied_price": model.get("valuation_summary", {}).get("Implied Price"),
                "peers_included": peer_list if peer_list else [],
                "excel_saved": str(excel_path) if excel_path else "Failed"
            }
            self.stats["stages_completed"].append("model_generation")
            
            # Log results
            valuation = model.get("valuation_summary", {})
            stats = {
                "Model strategy": model.get("strategy_info", {}).get("name", "N/A"),
                "Implied price": f"${valuation.get('Implied Price', 0):,.2f}" if valuation.get('Implied Price') else "N/A",
                "WACC used": f"{valuation.get('WACC', 0)*100:.1f}%" if valuation.get('WACC') else "N/A",
                "Terminal growth": f"{valuation.get('Terminal Growth', 0)*100:.1f}%" if valuation.get('Terminal Growth') else "N/A"
            }
            if peer_list:
                stats["Peer comparison"] = f"{len(peer_list)} peers included"
            self.logger.stage_end("FINANCIAL MODEL GENERATION", True, stats)
            
            return {"success": True, "model": model, "excel_path": excel_path}
            
        except Exception as e:
            self.logger.error(f"❌ Financial model generation failed: {e}")
            return {"success": False, "error": str(e)}
    
    def run_news_scraping_stage(self, max_searched: int = 20, query_override: Optional[str] = None) -> Dict:
        """Run the news article scraping stage."""
        try:
            # Check current storage status
            storage_info = self.article_scraper.get_storage_info()
            current_count = storage_info["total_articles"]
            
            self.logger.info(f"📊 Current articles in storage: {current_count}")
            
            # Perform scraping
            scraping_results = self.article_scraper.scrape_articles(max_searched, query_override)
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
    
    def run_filtering_stage(self, query: str, min_score: float = 6.0, max_searched: int = 10) -> Dict:
        """Run the article filtering stage with LLM-powered intelligence."""
        try:
            # Initialize article filter with query (required for LLM filtering)
            if not self.article_filter:
                self.article_filter = ArticleFilter(self.ticker, query, base_path=self.analysis_path)
                if hasattr(self.article_filter, 'set_logger'):
                    self.article_filter.set_logger(self.logger)
            
            # Perform LLM-powered filtering
            result = self.article_filter.filter_articles(num_articles=max_searched, min_score=min_score)
            
            if not result.get("filtered_articles"):
                self.logger.warning("⚠️  No articles met the filtering criteria")
                return {"filtered_articles": [], "filtered_count": 0, "llm_cost": 0.0}
            
            # Generate LLM report
            report = self.article_filter.generate_llm_report(result["filtered_articles"])
            report_path = self.article_filter.filtered_dir / "filtered_report.md"
            report_path.write_text(report, encoding='utf-8')
            
            # Update statistics
            filtering_results = {
                "filtered_articles": result["filtered_articles"],
                "filtered_count": len(result["filtered_articles"]),
                "min_score_used": min_score,
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
            
            # Log top articles
            self.logger.info(f"📄 Top {len(result['filtered_articles'])} articles:")
            for i, article in enumerate(result["filtered_articles"][:3], 1):
                score = article["llm_score"]
                title = article["title"][:60]
                self.logger.info(f"   {i}. [{score:.2f}] {title}...")
            
            self.logger.stage_end("ARTICLE FILTERING", True, stats)
            
            return filtering_results
            
        except Exception as e:
            self.logger.error(f"❌ Article filtering stage failed: {e}")
            return {"filtered_articles": [], "filtered_count": 0, "error": str(e)}
    
    def run_screening_stage(self, 
                           filtered_articles: List = None, 
                           min_confidence: float = 0.5,
                           generate_reports: bool = True) -> Dict:
        """Run the article screening/analysis stage."""
        try:
            # Load articles if not provided
            if filtered_articles is None:
                articles_data = self.article_screener.load_filtered_articles()
                if not articles_data:
                    self.logger.error("❌ No filtered articles found for screening")
                    return {"catalysts": [], "risks": [], "mitigations": []}
            else:
                # Convert filtered articles to format expected by screener
                articles_data = []
                for article_info in filtered_articles:
                    # article_info is a dict with metadata about the filtered article
                    # We need to load the actual article content for screening
                    filename = article_info.get('filename') or article_info.get('original_filename')
                    if filename:
                        # Load article content from the filtered directory
                        article_path = self.article_filter.filtered_dir / filename
                        if article_path.exists():
                            content = article_path.read_text(encoding='utf-8')
                            
                            # Parse frontmatter if present (to match screener's load_filtered_articles format)
                            if content.startswith("---"):
                                parts = content.split("---", 2)
                                if len(parts) >= 3:
                                    try:
                                        import yaml
                                        frontmatter = yaml.safe_load(parts[1]) or {}
                                        text_content = parts[2].strip()
                                    except:
                                        frontmatter = {}
                                        text_content = content
                                else:
                                    frontmatter = {}
                                    text_content = content
                            else:
                                frontmatter = {}
                                text_content = content
                            
                            # Create article data in the format screener expects
                            article_data = {
                                'file_path': article_path,
                                'file_name': filename,  # screener expects this key
                                'title': frontmatter.get('title', article_info.get('title', '')),
                                'source_url': frontmatter.get('source_url', ''),
                                'publish_date': frontmatter.get('publish_date', ''),
                                'text': text_content,  # screener expects 'text', not 'content'
                                'word_count': len(text_content.split()),
                                'llm_score': article_info.get('llm_score', 0.0)
                            }
                            articles_data.append(article_data)
            
            self.logger.info(f"🔍 Analyzing {len(articles_data)} articles with LLM...")
            
            # Extract insights using LLM (efficient single-pass analysis)
            catalysts, risks, mitigations, analysis_summary = self.article_screener.analyze_all_articles(articles_data)
            
            # Filter by confidence
            high_conf_catalysts = [c for c in catalysts if c.confidence >= min_confidence]
            high_conf_risks = [r for r in risks if r.confidence >= min_confidence]
            high_conf_mitigations = [m for m in mitigations if m.confidence >= min_confidence]
            
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
            report_file = self.analysis_path / "screened" / "screening_report.md"
            data_file = self.analysis_path / "screened" / "screening_data.json"
            if generate_reports:
                self.article_screener.generate_screening_report(
                    high_conf_catalysts, high_conf_risks, high_conf_mitigations, analysis_summary, report_file
                )
                self.article_screener.save_structured_data(
                    high_conf_catalysts, high_conf_risks, high_conf_mitigations, analysis_summary, data_file
                )
                self.logger.file_operation("Report generated", report_file)
                self.logger.file_operation("Structured data saved", data_file)
            else:
                self.logger.info("🛈 Report generation disabled (generate_reports=False)")
                report_file = None
                data_file = None
            
            # Log results
            stats = {
                "Growth catalysts": f"{len(high_conf_catalysts)} (of {len(catalysts)} total)",
                "Risks identified": f"{len(high_conf_risks)} (of {len(risks)} total)",
                "Mitigation strategies": f"{len(high_conf_mitigations)} (of {len(mitigations)} total)",
                "LLM cost": f"${screening_results['llm_cost']:.6f} USD ({screening_results['llm_calls']} calls)"
            }
            self.logger.stage_end("LLM ANALYSIS & SCREENING", True, stats)
            
            # Persist artifact paths
            screening_results['report_file'] = str(report_file) if report_file else None
            screening_results['data_file'] = str(data_file) if data_file else None
            return screening_results
            
        except Exception as e:
            self.logger.error(f"❌ Screening stage failed: {e}")
            return {"catalysts": [], "risks": [], "mitigations": [], "error": str(e)}
    
    def run_price_adjustment_stage(self, model_results: Dict, screening_results: Dict,
                                  scaling: float, adjustment_cap: float) -> Dict:
        """Run the price adjustment stage combining quantitative model with qualitative factors."""
        try:
            model = model_results.get("model", {})
            base_price = model.get("valuation_summary", {}).get("Implied Price")
            
            if not base_price:
                self.logger.error("❌ No base price available from financial model")
                return {"success": False, "error": "No base price available"}
            
            self.logger.info(f"💰 Base implied price: ${base_price:,.2f}")
            
            # Log comparison with current market price if available
            current_price = self.company_data.get("market_data", {}).get("current_price")
            if current_price:
                price_diff = ((base_price / current_price) - 1) * 100
                self.logger.info(f"📊 vs Current market price: ${current_price:.2f} ({price_diff:+.1f}%)")
            
            # Use proper parse_screening_report function to parse from the markdown file
            screening_report_path = self.analysis_path / "screened" / "screening_report.md"
            
            if screening_report_path.exists():
                # Parse the screening report using the dedicated function
                factors = parse_screening_report(screening_report_path)
                self.logger.info(f"📋 Parsed screening report: {len(factors.get('catalysts', []))} catalysts, {len(factors.get('risks', []))} risks, {len(factors.get('mitigations', []))} mitigations")
            else:
                # Fallback: convert screening_results dataclasses to dict format
                self.logger.warning("⚠️ No screening report file found, using direct screening results")
                def _to_dict(x):
                    try:
                        return asdict(x)
                    except Exception:
                        if isinstance(x, dict):
                            return x
                        return dict(x.__dict__) if hasattr(x, '__dict__') else {"value": x}
                
                factors = {
                    "catalysts": [_to_dict(c) for c in screening_results.get("catalysts", [])],
                    "risks": [_to_dict(r) for r in screening_results.get("risks", [])],
                    "mitigations": [_to_dict(m) for m in screening_results.get("mitigations", [])]
                }
            # Classify events for mapping if not already classified
            for kind in ("catalysts", "risks"):
                for item in factors[kind]:
                    if 'event_type' not in item or not item['event_type']:
                        try:
                            item['event_type'] = classify_event(item.get('description','') or item.get('type',''), item.get('description',''))
                        except Exception:
                            pass
            
            # Step 1: Compute qualitative adjustment (legacy scalar overlay)
            # Use company sector if available for better adjustment calibration
            sector = self.company_data.get("basic_info", {}).get("sector")
            adj = compute_adjustment(base_price, factors, scaling=scaling, cap=adjustment_cap, sector=sector)
            
            output = {
                'ticker': self.ticker,
                'base_model_price': base_price,
                'adjusted_price': adj.get('adjusted_price'),
                'adjustment_pct': adj.get('adjustment_pct'),
                'bull_price': adj.get('bull_price'),
                'bear_price': adj.get('bear_price'),
                'qualitative_inputs': adj.get('inputs'),
                'screen_file_present': True,
            }
            
            # Step 2: Deterministic mapped parameter deltas (always enabled)
            try:
                # Aggregate catalysts (positive) and risks (negative)
                cat_map = aggregate_mapped_parameter_deltas(factors.get('catalysts', []), is_risk=False)
                risk_map = aggregate_mapped_parameter_deltas(factors.get('risks', []), is_risk=True)
                
                # Combine effective deltas with conversion audit
                mapped_result = {
                    'catalyst_contributions': cat_map['contributions'],
                    'risk_contributions': risk_map['contributions'],
                    'effective': {
                        'growth_delta_dec': (cat_map['effective']['growth_delta_dec'] + risk_map['effective']['growth_delta_dec']),
                        'margin_uplift_dec': (cat_map['effective']['margin_uplift_dec'] + risk_map['effective']['margin_uplift_dec']),
                        'capex_rate_delta_dec': (cat_map['effective']['capex_rate_delta_dec'] + risk_map['effective']['capex_rate_delta_dec']),
                        'wacc_delta_dec': (cat_map['effective']['wacc_delta_dec'] + risk_map['effective']['wacc_delta_dec']),
                    },
                    'conversion_log': cat_map.get('conversion_log', []) + risk_map.get('conversion_log', []),
                }
                
                # Apply parameter deltas and recompute price
                effective_values = mapped_result['effective']
                if any(abs(v) > 1e-8 for v in effective_values.values()):
                    # Create model with adjusted parameters
                    adjusted_model = self._apply_parameter_deltas_to_model(model, mapped_result['effective'])
                    mapped_price = adjusted_model.get("valuation_summary", {}).get("Implied Price")
                    if mapped_price:
                        mapped_result['mapped_total_change_pct'] = (mapped_price / base_price) - 1
                        output['mapped_result'] = mapped_result
                        output['mapped_model_price'] = mapped_price
                        self.logger.info(f"📊 Mapped parameter price: ${mapped_price:,.2f} (Δ {mapped_result['mapped_total_change_pct']*100:+.1f}%)")
                else:
                    self.logger.info("🛈 No qualifying event parameter deltas (all effective deltas = 0.0)")
                
            except Exception as e:
                self.logger.warning(f"⚠️ Mapped parameter deltas failed: {e}")
                output['mapped_deltas_error'] = str(e)
            
            # Step 3: Scenario generation (always enabled)
            try:
                scenarios = [
                    {"name": "Base", "price": base_price},
                    {"name": "Adjusted", "price": output.get('adjusted_price'), "delta_pct": output.get('adjustment_pct')},
                    {"name": "Bull", "price": output.get('bull_price')},
                    {"name": "Bear", "price": output.get('bear_price')},
                ]
                output['scenarios'] = scenarios
                self.logger.info("🗺️  Generated placeholder scenarios (LLM scenario engine TBD)")
            except Exception as e:
                self.logger.warning(f"⚠️ Scenario generation failed: {e}")

            # Update statistics
            self.stats["price_adjustment"] = {
                "base_price": base_price,
                "adjusted_price": output.get('adjusted_price'),
                "adjustment_pct": output.get('adjustment_pct'),
                "mapped_price": output.get('mapped_model_price'),
                "factors_processed": {
                    "catalysts": len(factors['catalysts']),
                    "risks": len(factors['risks']),
                    "mitigations": len(factors['mitigations'])
                },
                "scenarios_generated": bool(output.get('scenarios'))
            }
            self.stats["stages_completed"].append("price_adjustment")
            
            # Log results
            stats = {
                "Base price": f"${base_price:,.2f}",
                "Adjusted price": f"${output.get('adjusted_price', 0):,.2f}",
                "Adjustment": f"{output.get('adjustment_pct', 0)*100:+.1f}%",
                "Bull/Bear range": f"${output.get('bear_price', 0):,.2f} - ${output.get('bull_price', 0):,.2f}"
            }
            if output.get('mapped_model_price'):
                stats["Mapped price"] = f"${output['mapped_model_price']:,.2f}"
            
            self.logger.stage_end("PRICE ADJUSTMENT", True, stats)
            
            return {"success": True, "price_analysis": output}
            
        except Exception as e:
            self.logger.error(f"❌ Price adjustment stage failed: {e}")
            return {"success": False, "error": str(e)}
    
    def _apply_parameter_deltas_to_model(self, base_model: Dict, deltas: Dict) -> Dict:
        """Apply parameter deltas to base model and recompute valuation."""
        try:
            if not self.model_generator:
                return base_model
            # Capture original overrides
            original_overrides = dict(self.model_generator.overrides)
            new_overrides = dict(original_overrides)
            # Map deltas to model overrides
            gd = deltas.get('growth_delta_dec')
            if gd and abs(gd) > 1e-8:
                base_g = original_overrides.get('first_year_growth') or 0.0
                new_overrides['first_year_growth'] = max(0.0, base_g + gd)
            mu = deltas.get('margin_uplift_dec')
            if mu and abs(mu) > 1e-8:
                base_mu = original_overrides.get('margin_uplift') or 0.0
                new_overrides['margin_uplift'] = base_mu + mu
            capx = deltas.get('capex_rate_delta_dec')
            if capx and abs(capx) > 1e-8:
                base_capex = original_overrides.get('capex_rate') or 0.0
                new_overrides['capex_rate'] = max(0.0, base_capex + capx)
            wacc_d = deltas.get('wacc_delta_dec')
            if wacc_d and abs(wacc_d) > 1e-8:
                base_wacc = base_model.get('valuation_summary', {}).get('WACC')
                if base_wacc:
                    new_overrides['override_wacc'] = max(0.01, base_wacc + wacc_d)
            # Apply and regenerate model (reuse original model generation parameters from stats)
            self.model_generator.overrides = new_overrides
            gen_stats = self.stats.get('model_generation', {})
            model_type = gen_stats.get('model_type', 'dcf')
            projection_years = gen_stats.get('projection_years', 5)
            term_growth = base_model.get('valuation_summary', {}).get('Terminal Growth')
            override_wacc = new_overrides.get('override_wacc')
            adjusted_model = self.model_generator.generate_financial_model(
                model_type=model_type,
                projection_years=projection_years,
                term_growth=term_growth,
                override_wacc=override_wacc,
                strategy=None,
                peers=None,
                generate_sensitivities=False
            )
            # Restore overrides to original to avoid side-effects for subsequent operations
            self.model_generator.overrides = original_overrides
            return adjusted_model
        except Exception as e:
            self.logger.warning(f"⚠️ Re-forecast with parameter deltas failed: {e}")
            return base_model
    
    def _get_comprehensive_pipeline_results(self) -> Dict:
        """Get complete comprehensive pipeline results."""
        self.stats["end_time"] = datetime.now()
        self.stats["total_duration"] = (self.stats["end_time"] - self.stats["start_time"]).total_seconds()
        return {
            "ticker": self.ticker,
            "company_name": self.company_name,
            "pipeline_type": "comprehensive_6_step",
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

def main():
    """Main entry point for the comprehensive stock analysis pipeline."""
    parser = argparse.ArgumentParser(
        description="Comprehensive 6-Step Stock Analysis Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Full LLM-powered analysis (AI selects optimal DCF strategy and parameters)
  python main.py --ticker NVDA --company "NVIDIA" --pipeline comprehensive
  
  # LLM analysis with manual strategy override (force specific DCF approach)
  python main.py --ticker AAPL --company "Apple Inc" --pipeline comprehensive --strategy hardware_dcf
  
  # Traditional analysis without LLM (deterministic parameters)
  python main.py --ticker TSLA --company "Tesla" --pipeline comprehensive --wacc 0.095
  
  # LLM analysis with forced manual overrides
  python main.py --ticker MSFT --company "Microsoft" --pipeline comprehensive --term-growth 0.025

  # Financial model only with LLM optimization
  python main.py --ticker REIT --company "Realty Income" --pipeline financial-model --strategy reit_dcf
  
  # SaaS company with peer comparison
  python main.py --ticker CRM --company "Salesforce" --pipeline comprehensive --peers "MSFT,ORCL,ADBE"
        """
    )
    
    # Required arguments
    parser.add_argument("--ticker", required=True, help="Stock ticker symbol (e.g., NVDA)")
    parser.add_argument("--company", required=True, help="Company name (e.g., 'NVIDIA')")
    parser.add_argument("--email", required=True, help="User email for data organization")
    parser.add_argument("--timestamp", required=True, help="Custom timestamp for analysis folder (YYYYMMDD_HHMMSS)")
    
    # Pipeline control
    parser.add_argument("--pipeline", 
                       choices=["comprehensive", "financial-statements", "financial-model", "search-news",
                                "screen-news", "news-to-price"], 
                       default="comprehensive", 
                       help="Pipeline stages to execute")
    
    parser.add_argument("--base_price", type=float, help="Base price for adjustment (required for news-to-price)")
    
    # Financial modeling parameters
    parser.add_argument("--model", choices=["dcf", "comparable", "comprehensive"], 
                       default="comprehensive", help="Financial model type (LLM will auto-select optimal DCF strategy)")
    parser.add_argument("--years", type=int, default=5, help="Projection years (LLM can suggest optimal range 3-10)")
    parser.add_argument("--term-growth", type=float, help="Terminal growth rate override (LLM auto-infers if omitted)")
    parser.add_argument("--wacc", type=float, help="WACC override (LLM auto-infers if omitted)")
    parser.add_argument("--strategy", help="Force specific DCF strategy (e.g., 'saas_dcf', 'reit_dcf', 'bank_excess_returns', 'hardware_dcf') - LLM auto-selects if omitted")
    parser.add_argument("--peers", help="Comma-separated peer tickers for comparable analysis (e.g., 'AAPL,MSFT,GOOGL')")
    
    # News analysis parameters  
    parser.add_argument("--max-searched", type=int, default=20, help="Maximum articles to search/scrape")
    parser.add_argument("--query", help="Override default search query for news articles")
    parser.add_argument("--min-score", type=float, default=3.0, help="Minimum relevance score (0-10)")
    parser.add_argument("--max-filtered", type=int, default=10, help="Maximum filtered articles")
    parser.add_argument("--min-confidence", type=float, default=0.5, help="Minimum confidence for insights (0-1)")
    
    # Price adjustment parameters
    parser.add_argument("--scaling", type=float, default=0.15, help="Base scaling factor for qualitative adjustment")
    parser.add_argument("--adjustment-cap", type=float, default=0.20, help="Maximum adjustment percentage (±)")
    
    # Other options
    parser.add_argument("--stats", action="store_true", help="Show current storage statistics")
    
    args = parser.parse_args()
    
    try:
        # Initialize comprehensive pipeline
        pipeline = ComprehensiveStockAnalysisPipeline(args.ticker, args.company, args.email, args.timestamp)
        
        # Show stats if requested
        if args.stats:
            # Show financial scraper stats
            try:
                financial_storage = pipeline.financial_scraper.get_current_data_status()
                pipeline.logger.info(f"📊 Financial data status for {args.ticker}:")
                pipeline.logger.info(f"   Available statements: {financial_storage.get('available_statements', 'Unknown')}")
            except:
                pass
            
            # Show news scraper stats  
            try:
                storage_info = pipeline.article_scraper.get_storage_info()
                pipeline.logger.info(f"📰 News articles status for {args.ticker}:")
                pipeline.logger.info(f"   Directory: {storage_info['company_dir']}")
                pipeline.logger.info(f"   Total articles: {storage_info['total_articles']}")
            except:
                pass
            return 0
        
        # Run selected pipeline
        if args.pipeline == "comprehensive":
            results = pipeline.run_comprehensive_pipeline(
                # Financial model parameters
                model_type=args.model,
                projection_years=args.years,
                term_growth=args.term_growth,
                wacc_override=args.wacc,
                strategy=args.strategy,
                peers=args.peers,
                # News analysis parameters
                max_searched=args.max_searched,
                query_override=args.query,
                min_filter_score=args.min_score,
                max_filtered=args.max_filtered,
                min_confidence=args.min_confidence,
                # Price adjustment parameters
                scaling=args.scaling,
                adjustment_cap=args.adjustment_cap
                # Note: Mapped deltas and LLM scenarios are always enabled
            )
        
        elif args.pipeline == "financial-statements":
            results = pipeline.run_financial_statement_stage()

        elif args.pipeline == "financial-model":
            financial_results = pipeline.run_financial_scraping_stage()
            if financial_results.get("success"):
                results = pipeline.run_model_generation_stage(
                    args.model, args.years, args.term_growth, args.wacc, args.strategy, args.peers
                )
            else:
                results = financial_results

        elif args.pipeline == "search-news":
            news_results = pipeline.run_news_scraping_stage(args.max_searched, args.query)
            # Proceed to filtering if we either scraped new content OR have a pre-existing corpus
            if news_results.get("scraped_count", 0) > 0 or news_results.get('pre_existing', 0) > 0:
                # Generate default query if none provided
                filter_query = args.query or f"{pipeline.company_name} financial outlook earnings growth investment analysis"
                results = pipeline.run_filtering_stage(filter_query, args.min_score, args.max_filtered)

        elif args.pipeline == "screen-news":
            news_results = pipeline.run_news_scraping_stage(args.max_searched, args.query)
            # Proceed to filtering if we either scraped new content OR have a pre-existing corpus
            if news_results.get("scraped_count", 0) > 0 or news_results.get('pre_existing', 0) > 0:
                # Generate default query if none provided
                filter_query = args.query or f"{pipeline.company_name} financial outlook earnings growth investment analysis"
                filtering_results = pipeline.run_filtering_stage(filter_query, args.min_score, args.max_filtered)
                if filtering_results.get("filtered_articles"):
                    results = pipeline.run_screening_stage(
                        filtering_results["filtered_articles"], args.min_confidence
                    )
                else:
                    results = filtering_results
            else:
                results = news_results
                
        elif args.pipeline == "news-to-price":
            # News analysis through price adjustment (requires existing financial model)
            news_results = pipeline.run_news_scraping_stage(args.max_searched, args.query)
            if news_results.get("scraped_count", 0) > 0:
                # Generate default query if none provided
                filter_query = args.query or f"{pipeline.company_name} financial outlook earnings growth investment analysis"
                filtering_results = pipeline.run_filtering_stage(filter_query, args.min_score, args.max_filtered)
                if filtering_results.get("filtered_articles"):
                    screening_results = pipeline.run_screening_stage(
                        filtering_results["filtered_articles"], args.min_confidence
                    )
                    if not args.base_price:
                        pipeline.logger.error("❌ No base price available from financial model")
                        return 1

                    # Load existing model results or create basic model
                    model_results = {"success": True, "model": {"valuation_summary": {"Implied Price": args.base_price}}}
                    # Try to load existing financial model
                    # Implementation would load saved model data
                    
                    results = pipeline.run_price_adjustment_stage(
                        model_results, screening_results, args.scaling, args.adjustment_cap
                    )  # Mapped deltas and LLM scenarios always enabled
                else:
                    results = filtering_results
            else:
                results = news_results
        
        # Pipeline execution completed successfully
        pipeline.logger.program_end()
        time.sleep(3)
        return 0
        
    except KeyboardInterrupt:
        if 'pipeline' in locals():
            pipeline.logger.warning("\n⏹️  Pipeline interrupted by user")
            pipeline.logger.program_end()
        else:
            print("\n⏹️  Pipeline interrupted by user")
        time.sleep(3)
        return 1
    except Exception as e:
        if 'pipeline' in locals():
            pipeline.logger.error(f"❌ Pipeline failed: {e}")
            pipeline.logger.program_end()
        else:
            print(f"❌ Pipeline failed: {e}")
        time.sleep(3)
        return 1

if __name__ == "__main__":
    exit(main())
