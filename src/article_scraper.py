#!/usr/bin/env python3
"""
article_scraper.py - Comprehensive news article scraper for stock analysis.

This module provides the ArticleScraper class for collecting and storing news articles
from multiple perspectives using AI-generated search queries. Supports comprehensive
multi-aspect analysis including company news, financial activities, management updates,
and industry trends.

Features:
- AI-powered industry classification
- Dynamic search query generation
- Multi-category article collection (overview, financial, management, industry)
- Intelligent duplicate detection
- Rich metadata and categorization
- Compatible with filter.py and screener.py modules

▶ Usage:
    # Comprehensive scraping (always enabled)
    python src/article_scraper.py --company "NVIDIA Corporation" --ticker NVDA --max 80
    
    # Comprehensive scraping with additional custom query
    python src/article_scraper.py --company "Tesla" --ticker TSLA --max 80 --query "Tesla earnings Q3 2024"
    
    # View statistics for existing articles
    python src/article_scraper.py --company "NVIDIA" --ticker NVDA --stats
"""

from __future__ import annotations
import os, csv, time, argparse, pathlib, json, re
from typing import List, Dict, Optional, Any, Tuple
from datetime import datetime

# Import centralized configuration
from config import MAX_ARTICLES
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set
from slugify import slugify

from serpapi import GoogleSearch
from newspaper import Article
from llms.config import get_llm
from financial_scraper import FinancialScraper

class ArticleScraper:
    """News article scraper for collecting stock-related news articles."""
    
    def __init__(self, ticker: str, company_name: str, base_path: pathlib.Path):
        """
        Initialize the scraper for a specific stock.
        
        Args:
            ticker: Stock ticker symbol (e.g., 'NVDA')
            company_name: Full company name (e.g., 'NVIDIA Corporation')
            base_path: Optional base path for data organization. If None, uses default.
        """
        self.ticker = ticker.upper()
        self.company_name = company_name
        self.company_dir = base_path
        self.searched_dir = self.company_dir / "searched"

        # Logger - will be set by pipeline if available
        self.logger = None
        
        # Load configuration
        self.max_articles = MAX_ARTICLES
        
        # Statistics tracking
        self.scraped_count = 0
        self.duplicate_count = 0
        self.failed_count = 0
        
        # API configuration
        self.api_key = os.getenv("SERPAPI_API_KEY")
        if not self.api_key:
            raise RuntimeError("SERPAPI_API_KEY environment variable must be set")
        
        # Cache for industry classification and search queries
        self.industry_info = None
        self.search_queries = None
        
        # Company sector and industry (fetched from financial data)
        self.company_sector = None
        self.company_industry = None
    
    def set_logger(self, logger):
        """Set the logger instance."""
        self.logger = logger
    
    def _log(self, level: str, message: str):
        """Log message using logger if available, otherwise print."""
        if self.logger:
            getattr(self.logger, level)(message)
        else:
            print(f"[{level.upper()}] {message}")
    
    def fetch_sector_industry_from_financial_data(self) -> Dict:
        """
        Fetch sector and industry from financial scraper instead of using LLM.
        
        This is more accurate and cost-effective than LLM classification.
        Falls back to LLM if financial data is unavailable.
        
        Returns:
            Dictionary with sector and industry information
        """
        if self.company_sector and self.company_industry:
            # Already fetched
            return {
                "sector": self.company_sector,
                "industry": self.company_industry,
                "source": "cached"
            }
        
        try:
            self._log("info", f"📊 Fetching sector/industry from financial data for {self.company_name}")
            
            # Create financial scraper instance
            financial_scraper = FinancialScraper(self.ticker, base_path=self.company_dir)
            financial_scraper.set_logger(self.logger)
            
            # Fetch comprehensive company data
            company_data = financial_scraper.scrape_comprehensive_company_data()
            basic_info = company_data.get("basic_info", {})
            
            sector = basic_info.get("sector", "Unknown")
            industry = basic_info.get("industry", "Unknown")
            
            # Cache the results
            self.company_sector = sector
            self.company_industry = industry
            
            self._log("info", f"✅ Financial data: Sector = {sector}, Industry = {industry}")
            
            return {
                "sector": sector,
                "industry": industry,
                "source": "financial_data"
            }
            
        except Exception as e:
            self._log("warning", f"⚠️  Could not fetch from financial data: {e}. Falling back to LLM.")
            # Fallback to LLM classification
            llm_result = self._classify_industry_with_llm()
            
            # Extract sector and industry from LLM result and ensure they're set
            self.company_sector = llm_result.get("broad_sector", "Unknown")
            self.company_industry = llm_result.get("primary_industry", "Unknown")
            
            return {
                "sector": self.company_sector,
                "industry": self.company_industry,
                "source": "llm_fallback"
            }
    
    def _load_prompt_template(self, filename: str) -> str:
        """Load prompt template from prompts folder."""
        prompt_path = pathlib.Path(__file__).parent.parent / "prompts" / filename
        if not prompt_path.exists():
            raise FileNotFoundError(f"Prompt template not found: {prompt_path}")
        return prompt_path.read_text(encoding='utf-8')
    
    def _parse_relative_time(self, relative_time_str: str, reference_time: datetime) -> str:
        """
        Parse relative time expressions (e.g., '6 hours ago', '2 days ago') into ISO timestamp.
        
        Args:
            relative_time_str: Relative time string from SerpAPI (e.g., "6 hours ago", "2 days ago")
            reference_time: Reference timestamp (scraped_at time)
            
        Returns:
            ISO 8601 formatted timestamp string, or original string if parsing fails
        """
        if not relative_time_str or not isinstance(relative_time_str, str):
            return relative_time_str
        
        # If it's already an ISO timestamp or a standard date, return as-is
        if 'T' in relative_time_str or '-' in relative_time_str[:10]:
            return relative_time_str
        
        # Parse relative time expressions
        relative_time_lower = relative_time_str.lower().strip()
        
        try:
            # Pattern: "X unit(s) ago" where unit can be: second, minute, hour, day, week, month, year
            match = re.match(r'(\d+)\s+(second|minute|hour|day|week|month|year)s?\s+ago', relative_time_lower)
            
            if match:
                amount = int(match.group(1))
                unit = match.group(2)
                
                # Calculate the actual timestamp
                if unit == 'second':
                    actual_time = reference_time - timedelta(seconds=amount)
                elif unit == 'minute':
                    actual_time = reference_time - timedelta(minutes=amount)
                elif unit == 'hour':
                    actual_time = reference_time - timedelta(hours=amount)
                elif unit == 'day':
                    actual_time = reference_time - timedelta(days=amount)
                elif unit == 'week':
                    actual_time = reference_time - timedelta(weeks=amount)
                elif unit == 'month':
                    # Approximate: 1 month = 30 days
                    actual_time = reference_time - timedelta(days=amount * 30)
                elif unit == 'year':
                    # Approximate: 1 year = 365 days
                    actual_time = reference_time - timedelta(days=amount * 365)
                else:
                    return relative_time_str
                
                return actual_time.isoformat()
            
            # Handle "a X ago" (e.g., "an hour ago", "a day ago")
            match_a = re.match(r'an?\s+(second|minute|hour|day|week|month|year)\s+ago', relative_time_lower)
            if match_a:
                unit = match_a.group(1)
                amount = 1
                
                if unit == 'second':
                    actual_time = reference_time - timedelta(seconds=amount)
                elif unit == 'minute':
                    actual_time = reference_time - timedelta(minutes=amount)
                elif unit == 'hour':
                    actual_time = reference_time - timedelta(hours=amount)
                elif unit == 'day':
                    actual_time = reference_time - timedelta(days=amount)
                elif unit == 'week':
                    actual_time = reference_time - timedelta(weeks=amount)
                elif unit == 'month':
                    actual_time = reference_time - timedelta(days=30)
                elif unit == 'year':
                    actual_time = reference_time - timedelta(days=365)
                else:
                    return relative_time_str
                
                return actual_time.isoformat()
            
            # If no pattern matched, return original
            return relative_time_str
            
        except Exception as e:
            self._log("warning", f"Failed to parse relative time '{relative_time_str}': {e}")
            return relative_time_str
    
    def _classify_industry(self) -> Dict:
        """
        Classify company's industry and sector.
        
        Primary method: Fetch from financial data (accurate and free)
        Fallback method: Use LLM classification (costs money but works if financial data unavailable)
        """
        if self.industry_info:
            return self.industry_info
        
        # Try financial data first (preferred method)
        sector_industry = self.fetch_sector_industry_from_financial_data()
        
        # Ensure self.company_sector and self.company_industry are set
        # (fetch_sector_industry_from_financial_data already sets these, but double-check)
        if not self.company_sector:
            self.company_sector = sector_industry.get("sector", "Unknown")
        if not self.company_industry:
            self.company_industry = sector_industry.get("industry", "Unknown")
        
        self.industry_info = {
            "primary_industry": sector_industry.get("industry", "Unknown"),
            "broad_sector": sector_industry.get("sector", "Unknown"),
            "description": f"{self.company_name} - {sector_industry.get('sector')} sector, {sector_industry.get('industry')} industry",
            "source": sector_industry.get("source", "unknown")
        }
        
        return self.industry_info
    
    def _classify_industry_with_llm(self) -> Dict:
        """Use LLM to classify the company's industry (fallback method)."""
        self._log("info", f"🏭 Classifying industry for {self.company_name} using LLM")
        
        try:
            prompt_template = self._load_prompt_template("industry_classification.md")
            prompt = prompt_template.format(
                company_name=self.company_name,
                ticker=self.ticker
            )
            
            messages = [
                {"role": "system", "content": "You are a business and industry classification expert."},
                {"role": "user", "content": prompt}
            ]
            
            response, cost = get_llm()(messages, temperature=0.1)
            
            # Extract JSON from response
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                industry_data = json.loads(json_match.group(0))
                self.industry_info = industry_data
                
                # Set self.company_sector and self.company_industry from LLM result
                self.company_sector = industry_data.get('broad_sector', 'Unknown')
                self.company_industry = industry_data.get('primary_industry', 'Unknown')
                
                self._log("info", f"📊 Industry classified: {industry_data.get('primary_industry', 'Unknown')}")
                return industry_data
            else:
                self._log("warning", "Could not parse industry classification response")
                return self._get_fallback_industry()
                
        except Exception as e:
            self._log("error", f"Industry classification failed: {e}")
            return self._get_fallback_industry()
    
    def _get_fallback_industry(self) -> Dict:
        """Provide fallback industry classification."""
        # Set fallback values for sector and industry
        self.company_sector = "Unknown"
        self.company_industry = "Unknown"
        
        return {
            "primary_industry": "unknown",
            "broad_sector": "general",
            "description": f"Industry classification unavailable for {self.company_name}"
        }
    
    def _generate_comprehensive_queries(self) -> Dict[str, str]:
        """Use LLM to generate comprehensive search queries."""
        if self.search_queries:
            return self.search_queries
            
        self._log("info", f"🔍 Generating comprehensive search queries for {self.company_name}")
        
        # Get industry classification first
        industry_info = self._classify_industry()
        
        try:
            prompt_template = self._load_prompt_template("comprehensive_news_queries.md")
            industry_str = f"{industry_info.get('primary_industry', '')} ({industry_info.get('broad_sector', '')})"
            
            prompt = prompt_template.format(
                company_name=self.company_name,
                ticker=self.ticker,
                industry=industry_str
            )
            
            messages = [
                {"role": "system", "content": "You are an expert financial analyst and news researcher."},
                {"role": "user", "content": prompt}
            ]
            
            response, cost = get_llm()(messages, temperature=0.2)
            
            # Extract JSON from response
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                queries = json.loads(json_match.group(0))
                self.search_queries = queries
                self._log("info", f"📝 Generated {len(queries)} search query categories")
                return queries
            else:
                self._log("warning", "Could not parse search queries response")
                return self._get_fallback_queries()
                
        except Exception as e:
            self._log("error", f"Query generation failed: {e}")
            return self._get_fallback_queries()
    
    def _get_fallback_queries(self) -> Dict[str, str]:
        """Provide fallback search queries."""
        return {
            "company_overview": f"{self.company_name} {self.ticker} news",
            "financial_activities": f"{self.company_name} earnings revenue financial",
            "management_leadership": f"{self.company_name} CEO management leadership",
            "industry_trends": f"{self.company_name} industry market trends"
        }
    
    def _serpapi_news_links(self, query: str) -> List[Dict]:
        """
        Return up to `max_results` news metadata from Google News via SerpAPI.
        
        Returns list of dictionaries containing:
        - url: Article URL
        - title: Article title from SerpAPI
        - source_name: Source publication name
        - authors: List of author names  
        - published_date: Publication date
        - snippet: Article snippet/summary
        - thumbnail: Article image URL
        """
        try:
            search = GoogleSearch({
                "q": query,
                "tbm": "nws",
                "num": self.max_articles,
                "tbs": "qdr:d",  # Last 24 hours
                "api_key": self.api_key
            })
            result = search.get_dict()
            
            if not isinstance(result, dict):
                self._log("warning", f"Unexpected SerpAPI response type: {type(result)}")
                return []
            
            # Check for API errors
            if "error" in result:
                self._log("error", f"❌ SerpAPI returned error: {result['error']}")
                if "message" in result:
                    self._log("error", f"   Error details: {result['message']}")
                return []
            
            # Log response for debugging
            self._log("debug", f"SerpAPI response keys: {list(result.keys())}")
                
            news_results = result.get("news_results", [])
            
            if not news_results:
                self._log("warning", f"No news results found for query: {query}")
                # Log additional info for debugging
                search_params = result.get("search_parameters", {})
                self._log("debug", f"   Search params used: {search_params}")
                if "serpapi_pagination" in result:
                    self._log("debug", f"   Pagination info: {result['serpapi_pagination']}")
                return []
            
            enhanced_results = []
            for item in news_results:
                if not isinstance(item, dict):
                    self._log("warning", f"Unexpected news item type: {type(item)}")
                    continue
                    
                # Extract comprehensive metadata from SerpAPI response
                news_metadata = {
                    "url": item.get("link", ""),
                    "title": item.get("title", ""),
                    "snippet": item.get("snippet", ""),
                    "thumbnail": item.get("thumbnail", ""),
                    "published_date": item.get("date", ""),
                    "source_name": "",
                    "authors": [],
                    "source_icon": ""
                }
                
                # Extract source information
                source = item.get("source", {})
                if source and isinstance(source, dict):
                    news_metadata["source_name"] = source.get("name", "")
                    news_metadata["source_icon"] = source.get("icon", "")
                    news_metadata["authors"] = source.get("authors", [])
                
                # Only include if we have a valid URL
                if news_metadata["url"]:
                    enhanced_results.append(news_metadata)
                    
            return enhanced_results
            
        except KeyError as e:
            self._log("error", f"❌ SerpAPI response missing expected key: {e}")
            self._log("error", f"   Available keys: {list(result.keys()) if 'result' in locals() else 'N/A'}")
            return []
        except Exception as e:
            self._log("error", f"❌ SerpAPI search failed for query '{query}'")
            self._log("error", f"   Exception type: {type(e).__name__}")
            self._log("error", f"   Exception details: {str(e)}")
            
            # Check if it's an API key issue
            if "api_key" in str(e).lower() or "authentication" in str(e).lower() or "unauthorized" in str(e).lower():
                self._log("error", f"   ⚠️  Possible API key issue - verify SERPAPI_API_KEY is valid")
            elif "rate" in str(e).lower() or "limit" in str(e).lower() or "quota" in str(e).lower():
                self._log("error", f"   ⚠️  Possible rate limit or quota issue - check SerpAPI dashboard")
            
            return []
    
    def _scrape_article(self, url: str) -> Optional[Dict]:
        """Download & parse an article. Returns dict or None on failure."""
        try:
            art = Article(url, language="en")
            art.download()
            art.parse()
            return {
                "url": url,
                "title": art.title or "Untitled",
                "publish_date": art.publish_date.isoformat() if art.publish_date else "",
                "text": art.text,
                "word_count": len(art.text.split()) if art.text else 0
            }
        except Exception as e:
            self._log("warning", f"Could not scrape {url}: {e}")
            self.failed_count += 1
            return None
    
    def _save_article_markdown(self, article_data: Dict) -> pathlib.Path:
        """Save article as markdown file with enhanced frontmatter including SerpAPI metadata and sector/industry."""
        # Ensure directories exist
        self.company_dir.mkdir(parents=True, exist_ok=True)
        self.searched_dir.mkdir(parents=True, exist_ok=True)
        
        # Generate filename with timestamp and title slug
        scraped_at = datetime.utcnow()
        timestamp = scraped_at.strftime("%Y-%m-%d-%H%M%S")
        # Use SerpAPI title if available, fallback to scraped title
        title_for_filename = article_data.get('serpapi_title') or article_data.get('title', 'untitled')
        title_slug = slugify(title_for_filename[:60])
        filename = f"{timestamp}_{title_slug}.md"
        file_path = self.searched_dir / filename
        
        # Prepare enhanced frontmatter with SerpAPI metadata
        search_category = article_data.get('search_category', 'general').replace('_', ' ')
        
        # Parse relative time to actual timestamp
        raw_publish_date = article_data.get('serpapi_published_date') or article_data.get('publish_date', '')
        publish_date = self._parse_relative_time(raw_publish_date, scraped_at)
        
        # Use SerpAPI title if available, fallback to scraped title
        title = article_data.get('serpapi_title') or article_data.get('title', 'Untitled Article')
        
        # Clean snippet text for YAML (escape quotes)
        snippet = article_data.get('serpapi_snippet', '').replace('"', '\\"')
        
        # Create markdown content with enhanced YAML frontmatter (including sector/industry for filter)
        markdown_content = f"""---
title: "{title}"
source_url: {article_data['url']}
publish_date: {publish_date}
publish_date_raw: {raw_publish_date}
word_count: {article_data['word_count']}
search_category: {search_category}
scraped_at: {scraped_at.isoformat()}Z
ticker: {self.ticker}
company: {self.company_name}
sector: {self.company_sector or 'Unknown'}
industry: {self.company_industry or 'Unknown'}
# SerpAPI Enhanced Metadata
serpapi_source: "{article_data.get('serpapi_source', '')}"
serpapi_authors: {article_data.get('serpapi_authors', [])}
serpapi_snippet: "{snippet}"
serpapi_thumbnail: "{article_data.get('serpapi_thumbnail', '')}"
serpapi_source_icon: "{article_data.get('serpapi_source_icon', '')}"
---

{article_data['text']}
"""
        
        file_path.write_text(markdown_content, encoding="utf-8")
        return file_path
    
    def scrape_articles(self, query_override: Optional[str] = None) -> Dict:
        """
        Scrape news articles for the configured company using comprehensive multi-aspect searching.
        
        Args:
            max_searched: Maximum number of articles to search/scrape (distributed across query types)
            query_override: Additional custom query to include alongside comprehensive search
            
        Returns:
            Dictionary with scraping statistics and results
        """
        # Reset statistics
        self.scraped_count = 0
        self.duplicate_count = 0
        self.failed_count = 0
        
        scraped_files = []
        all_urls = []
        
        # Always run comprehensive multi-aspect searching
        self._log("info", f"🚀 Starting comprehensive news search for {self.company_name}")
        
        # Generate comprehensive queries
        queries = self._generate_comprehensive_queries()
        industry_info = self._classify_industry()
        
        # If query override is provided, add it as an additional category
        if query_override:
            queries["custom_query"] = query_override
            self._log("info", f"➕ Added custom query: '{query_override}'")

        for i, (category, query) in enumerate(queries.items()):
            self._log("info", f"📰 {category.replace('_', ' ').title()}: '{query}'")
            category_metadata = self._serpapi_news_links(query)
            # Store both metadata and category info
            for metadata in category_metadata:
                all_urls.append((metadata, category))
            
            # Brief pause between different query types
            time.sleep(0.5)
        
        if not all_urls:
            self._log("warning", "No URLs found from news search")
            return self._get_scraping_results()
        
        # Remove duplicates while preserving metadata and category information
        unique_articles = {}
        for metadata, category in all_urls:
            url = metadata["url"]
            if url not in unique_articles:
                metadata["search_category"] = category.replace('_', ' ')
                unique_articles[url] = metadata

        # Scrape each article
        for url, metadata in unique_articles.items():
            if self.logger:
                self.logger.scraping_progress(url, "in progress")
            else:
                self._log("info", f"🌐 Scraping in progress: {url}")
            
            article_data = self._scrape_article(url)
            
            if not article_data:
                continue  # Failed scraping already counted in _scrape_article
            
            # Merge SerpAPI metadata with scraped content
            article_data.update({
                'serpapi_title': metadata.get('title', ''),
                'serpapi_source': metadata.get('source_name', ''),
                'serpapi_authors': metadata.get('authors', []),
                'serpapi_published_date': metadata.get('published_date', ''),
                'serpapi_snippet': metadata.get('snippet', ''),
                'serpapi_thumbnail': metadata.get('thumbnail', ''),
                'serpapi_source_icon': metadata.get('source_icon', ''),
                'search_category': metadata.get('search_category', '')
            })
            
            # Save article to local markdown file only (MongoDB save happens in article_filter after filtering)
            try:
                # Save to local markdown file (existing functionality)
                file_path = self._save_article_markdown(article_data)
                scraped_files.append(file_path)
                self.scraped_count += 1
                
                if self.logger:
                    self.logger.file_operation("Article saved", file_path)
                    self.logger.debug(f"   📊 Sector: {self.company_sector}, Industry: {self.company_industry}")
                else:
                    self._log("info", f"📁 Article saved: {file_path}")
                    self._log("debug", f"   📊 Sector: {self.company_sector}, Industry: {self.company_industry}")
                
                time.sleep(1)  # Be polite to servers
                
            except Exception as e:
                self._log("error", f"Failed to save article from {url}: {e}")
                self.failed_count += 1
        
        results = self._get_scraping_results()
        results["scraped_files"] = scraped_files
        results["industry_info"] = self.industry_info
        results["search_queries"] = self.search_queries
        return results
    
    def _get_scraping_results(self) -> Dict:
        """Get current scraping statistics."""
        return {
            "ticker": self.ticker,
            "company_name": self.company_name,
            "scraped_count": self.scraped_count,
            "duplicate_count": self.duplicate_count,
            "failed_count": self.failed_count,
            "total_processed": self.scraped_count + self.duplicate_count + self.failed_count,
            "success_rate": self.scraped_count / max(1, self.scraped_count + self.failed_count)
        }
    
    def get_comprehensive_stats(self) -> Dict:
        """Get comprehensive statistics including category breakdown."""
        if not self.searched_dir.exists():
            return {"error": "No scraped articles directory found"}
        
        category_stats = {}
        total_articles = 0
        
        # Analyze all markdown files for category distribution
        for md_file in self.searched_dir.glob("*.md"):
            try:
                content = md_file.read_text(encoding='utf-8')
                # Extract search_category from YAML frontmatter
                if 'search_category:' in content:
                    category_line = [line for line in content.split('\n') if 'search_category:' in line][0]
                    category = category_line.split('search_category:')[1].strip().replace('_', ' ')
                    category_stats[category] = category_stats.get(category, 0) + 1
                    total_articles += 1
            except Exception as e:
                self._log("warning", f"Could not analyze file {md_file}: {e}")
        
        return {
            "total_articles": total_articles,
            "category_breakdown": category_stats,
            "industry_info": self.industry_info,
            "search_queries_used": self.search_queries,
            "storage_info": self.get_storage_info()
        }
    
    def run_comprehensive_scraping(self, query_override: Optional[str] = None) -> Dict:
        """
        Run comprehensive multi-aspect news scraping with detailed reporting.
        
        Args:
            query_override: Additional custom query to include alongside comprehensive search
            
        Returns:
            Comprehensive results including statistics and analysis
        """
        self._log("info", f"🚀 Starting comprehensive news analysis for {self.company_name} ({self.ticker})")
        
        # Run comprehensive scraping
        results = self.scrape_articles(query_override=query_override)
        
        # Get comprehensive statistics
        stats = self.get_comprehensive_stats()
        
        # Combine results
        comprehensive_results = {
            **results,
            **stats,
            "scraping_mode": "comprehensive",
            "max_articles_requested": self.max_articles
        }
        
        # Log summary
        self._log("info", f"📊 Comprehensive scraping completed:")
        self._log("info", f"   • Total articles scraped: {results['scraped_count']}")
        self._log("info", f"   • Duplicates skipped: {results['duplicate_count']}")
        self._log("info", f"   • Failed scrapes: {results['failed_count']}")
        self._log("info", f"   • Success rate: {results['success_rate']:.1%}")
        
        if stats.get('category_breakdown'):
            self._log("info", f"   • Category distribution:")
            for category, count in stats['category_breakdown'].items():
                self._log("info", f"     - {category.replace('_', ' ').title()}: {count} articles")
        
        return comprehensive_results
    
    def get_scraped_articles_count(self) -> int:
        """Get total number of articles scraped for this ticker."""
        if not self.searched_dir.exists():
            return 0
        return len(list(self.searched_dir.glob("*.md")))
    
    def get_storage_info(self) -> Dict:
        """Get information about stored articles."""
        return {
            "company_dir": str(self.company_dir),
            "searched_dir": str(self.searched_dir),
            "total_articles": self.get_scraped_articles_count(),
            "directories_exist": {
                "company_dir": self.company_dir.exists(),
                "searched_dir": self.searched_dir.exists(),
            }
        }

