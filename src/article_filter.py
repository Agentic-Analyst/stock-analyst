#!/usr/bin/env python3
"""
article_filter.py - LLM-powered intelligent article filter for stock analysis.

This module filters scraped articles using LLM intelligence to identify articles
most relevant to the search query and investment analysis objectives.

Features:
- LLM-based relevance assessment using search query context
- Efficient batch processing for large-scale news filtering
- Intelligent report generation with investment insights
- Configurable filtering thresholds and article limits

▶ Usage:
    python article_filter.py --ticker NVDA --query "nvidia ai data center growth" --min-score 5.0 --max-articles 8
"""

from __future__ import annotations
import os, argparse, pathlib, re, json, logging
from datetime import datetime
from typing import Dict, List, Tuple, Optional
from llms.config import get_llm
from dotenv import load_dotenv
load_dotenv()

# Import centralized configuration
from config import MIN_SCORE

# Import vynn_core for MongoDB integration
try:
    from vynn_core import Article, init_indexes, upsert_articles, find_recent, get_article_by_url, utc_now
    VYNN_CORE_AVAILABLE = True
except ImportError as e:
    print(f"Warning: vynn_core not available: {e}")
    print("Please install vynn_core: pip install git+https://github.com/Agentic-Analyst/vynn-core.git")
    VYNN_CORE_AVAILABLE = False

class ArticleFilter:
    def __init__(self, ticker: str, query: str, base_path: pathlib.Path):
        """
        Initialize LLM-powered article filter with MongoDB integration.
        
        Args:
            ticker: Stock ticker symbol (e.g., 'NVDA')
            query: Investment query for LLM-based relevance assessment (required)
            base_path: Base path for data organization
        """
        self.ticker = ticker.upper()
        self.query = query
        self.company_dir = base_path
        
        # Logger - will be set by pipeline if available
        self.logger = None
        
        self.min_score = MIN_SCORE
        
        # LLM tracking
        self.total_llm_cost = 0.0
        self.llm_call_count = 0
        
        # Batch processing configuration
        self.batch_size = 10  # Process articles in batches for efficiency
        
        # Company sector and industry (fetched from articles metadata)
        self.company_sector = None
        self.company_industry = None
        
        # MongoDB integration - Initialize database if available
        self.db_enabled = VYNN_CORE_AVAILABLE
        self._log(f"🔧 Initializing MongoDB integration (vynn_core available: {VYNN_CORE_AVAILABLE})", "info")
        
        if self.db_enabled:
            try:
                self._log(f"🔄 Initializing MongoDB indexes for collection '{self.ticker}'...", "info")
                init_indexes(self.ticker)
                
                # Test database connection
                self._log("🔄 Testing MongoDB connection...", "info")
                from vynn_core.db.mongo import test_connection
                connection_result = test_connection()
                
                if connection_result.get("status") == "connected":
                    self._log(f"✅ MongoDB connected - DB: {connection_result.get('database')}, "
                             f"Collections: {connection_result.get('collections', [])}", "info")
                else:
                    self._log(f"❌ MongoDB connection failed: {connection_result.get('error')}", "error")
                    self.db_enabled = False
                    
            except Exception as e:
                self._log(f"❌ MongoDB initialization failed: {e}", "error")
                import traceback
                self._log(f"Full traceback: {traceback.format_exc()}", "error")
                self.db_enabled = False
        else:
            self._log("⚠️  MongoDB integration disabled - vynn_core not available", "warning")
        
        # Load prompts from files
        self.prompts_dir = pathlib.Path(__file__).parent.parent / "prompts"
        self._load_prompts()

    def _load_prompts(self):
        """Load prompt templates from markdown files."""
        # Load article relevance scoring prompt
        relevance_path = self.prompts_dir / "article_relevance_scoring.md"
        self.relevance_prompt_template = relevance_path.read_text(encoding='utf-8')
             
    def set_logger(self, logger):
        """Set the logger instance."""
        self.logger = logger
    
    def _log(self, message: str, level: str = "info"):
        """Log message using logger if available, otherwise print."""
        if self.logger:
            getattr(self.logger, level)(message)
        else:
            print(f"[{level.upper()}] {message}")

    def filter_articles(self) -> dict:
        """
        Filter articles using LLM intelligence based on the query.
        
        Uses configuration values from self.min_score.
        
        Returns:
            Dictionary with filtering results and metadata
        """
        self._log(f"Starting LLM-powered filtering for {self.ticker}")
        self._log(f"Query: {self.query}, Min score: {self.min_score}")
        
        # Load and prepare articles
        searched_dir = self.company_dir / "searched"
        articles_data = self._load_articles_metadata(searched_dir)
        
        if not articles_data:
            self._log("No articles found to filter")
            return {"filtered_articles": [], "total_processed": 0, "llm_cost": 0.0}
        
        self._log(f"Found {len(articles_data)} articles to process")
        
        # Process all articles with LLM scoring
        scored_articles = self._score_articles_with_llm(articles_data)
        
        # Log all scores for transparency
        self._log("=" * 80)
        self._log(f"📊 LLM SCORING RESULTS (All {len(scored_articles)} articles)")
        self._log("=" * 80)
        for i, article in enumerate(scored_articles, 1):
            score = article.get('llm_score', 0.0)
            title = article.get('title', 'Untitled')[:80]
            status = "✅ PASS" if score >= self.min_score else "❌ FAIL"
            self._log(f"{i:2d}. [{score:.1f}/10] {status} - {title}")
        self._log("=" * 80)
        
        # Filter by minimum score and limit count
        filtered_articles = self._select_final_articles(scored_articles)

        # Copy filtered articles and generate index
        result = self._finalize_filtering(filtered_articles)
        
        # Add metadata
        result.update({
            "query": self.query,
            "total_processed": len(articles_data),
            "llm_cost": self.total_llm_cost,
            "llm_calls": self.llm_call_count
        })
        
        # Log filtering summary
        passed_count = len([a for a in scored_articles if a.get('llm_score', 0) >= self.min_score])
        failed_count = len(scored_articles) - passed_count
        
        self._log("=" * 80)
        self._log(f"📋 FILTERING SUMMARY")
        self._log("=" * 80)
        self._log(f"Total articles processed: {len(articles_data)}")
        self._log(f"Passed threshold (≥{self.min_score}): {passed_count}")
        self._log(f"Failed threshold (<{self.min_score}): {failed_count}")
        self._log(f"Final selected: {len(result['filtered_articles'])}")
        self._log(f"LLM cost: ${self.total_llm_cost:.4f} ({self.llm_call_count} calls)")
        self._log("=" * 80)
        
        if failed_count > 0:
            self._log(f"ℹ️  {failed_count} articles were below the minimum score threshold of {self.min_score}")
            avg_score = sum(a.get('llm_score', 0) for a in scored_articles) / len(scored_articles) if scored_articles else 0
            self._log(f"ℹ️  Average score across all articles: {avg_score:.2f}/10")
            if avg_score < self.min_score:
                self._log(f"💡 Consider lowering min_score threshold (current: {self.min_score}) to get more results")
        
        self._log(f"Filtering complete: {len(result['filtered_articles'])} articles selected")
        self._log(f"Total LLM cost: ${self.total_llm_cost:.4f} ({self.llm_call_count} calls)")
        
        return result

    def _load_articles_metadata(self, searched_dir: pathlib.Path) -> list:
        """Load article metadata from searched directory."""
        articles = []
        
        if not searched_dir.exists():
            return articles
            
        for article_file in searched_dir.glob("*.md"):
            try:
                content = article_file.read_text(encoding='utf-8')
                
                # Extract metadata from content
                metadata = self._extract_article_metadata(content, article_file.name)
                if metadata:
                    articles.append(metadata)
                    
            except Exception as e:
                self._log(f"Error reading {article_file}: {e}")
                
        return articles

    def _extract_article_metadata(self, content: str, filename: str) -> dict:
        """Extract all metadata from article YAML frontmatter."""
        metadata = {
            'filename': filename,
            'word_count': len(content.split()),
            'llm_score': 0.0,
        }
        
        # Extract just the main content (without YAML frontmatter)
        article_content = content
        
        # Check if content starts with YAML frontmatter
        if content.startswith('---'):
            try:
                # Find the end of YAML frontmatter
                yaml_end = content.find('---', 3)
                if yaml_end != -1:
                    frontmatter = content[3:yaml_end].strip()
                    # Extract main content after the second ---
                    article_content = content[yaml_end + 3:].strip()
                    
                    # Parse all YAML fields
                    for line in frontmatter.split('\n'):
                        line = line.strip()
                        if ':' in line and not line.startswith('#'):
                            key, value = line.split(':', 1)
                            key = key.strip()
                            value = value.strip()
                            
                            # Clean quotes from values
                            if value.startswith('"') and value.endswith('"'):
                                value = value[1:-1]
                            elif value.startswith("'") and value.endswith("'"):
                                value = value[1:-1]
                            
                            # Parse lists (simple parsing for arrays)
                            if value.startswith('[') and value.endswith(']'):
                                # Remove brackets and split by comma
                                value = value[1:-1]
                                if value.strip():
                                    metadata[key] = [item.strip().strip("'\"") for item in value.split(',')]
                                else:
                                    metadata[key] = []
                            else:
                                metadata[key] = value
                                
            except Exception as e:
                self._log(f"Error parsing YAML frontmatter in {filename}: {e}", "warning")
        
        # Set the content to just the article text (without frontmatter)
        metadata['content'] = article_content
        
        # Fallback: Extract title and URL from markdown headers if not in frontmatter
        if 'title' not in metadata or not metadata['title']:
            lines = article_content.split('\n')
            for line in lines[:20]:  # Check first 20 lines
                line = line.strip()
                if line.startswith('# '):
                    metadata['title'] = line[2:].strip()
                    break
                elif line.startswith('**') and line.endswith('**') and len(line) > 10:
                    metadata['title'] = line[2:-2].strip()
                    break
        
        # Fallback: Extract URL if not in frontmatter
        if 'source_url' not in metadata or not metadata['source_url']:
            lines = article_content.split('\n')
            for line in lines[:20]:
                if line.strip().startswith('**URL:**'):
                    metadata['source_url'] = line.split(':', 1)[1].strip()
                    break
                
        return metadata

    def _convert_to_vynn_article(self, article_metadata: dict) -> dict:
        """
        Convert article metadata to a flat key-value structure matching the YAML frontmatter.
        
        Args:
            article_metadata: Article metadata from _extract_article_metadata
            
        Returns:
            Flat dictionary with all YAML fields as direct key-value pairs plus content
        """
        if not self.db_enabled:
            return None
            
        try:
            # Start with all metadata fields from YAML frontmatter
            article_data = {}
            
            # Copy all fields except the ones we don't want
            excluded_fields = {'filename', 'llm_score'}
            for key, value in article_metadata.items():
                if key not in excluded_fields:
                    article_data[key] = value
            
            # Map source_url to url for vynn_core compatibility
            if 'source_url' in article_data:
                article_data['url'] = article_data['source_url']
                        
            return article_data
            
        except Exception as e:
            self._log(f"Error converting article to flat format: {e}", "error")
            return None

    def _score_articles_with_llm(self, articles: list) -> list:
        """Score all articles using LLM intelligence."""
        self._log(f"Scoring {len(articles)} articles with LLM")
        
        # Process in batches to optimize API usage
        scored_articles = []
        for i in range(0, len(articles), self.batch_size):
            batch = articles[i:i + self.batch_size]
            batch_results = self._process_llm_batch(batch)
            scored_articles.extend(batch_results)
            
        # Sort by LLM score
        return sorted(scored_articles, key=lambda x: x['llm_score'], reverse=True)

    def _process_llm_batch(self, batch: list) -> list:
        """Process a batch of articles with LLM for relevance scoring."""
        try:
            # Prepare prompt with article summaries
            prompt = self._build_relevance_prompt(batch)
            
            # Call LLM with proper message format
            messages = [
                {"role": "system", "content": "You are a senior financial analyst filtering investment articles."},
                {"role": "user", "content": prompt},
            ]
            response, cost = get_llm()(messages, temperature=0.1)
            self.llm_call_count += 1
            
            # Track actual cost from LLM call
            self.total_llm_cost += cost
            
            # Parse LLM response
            scores = self._parse_llm_scores(response, len(batch))
            
            # Apply scores to articles
            for i, article in enumerate(batch):
                llm_score = scores[i] if i < len(scores) else 5.0
                article['llm_score'] = llm_score
                
        except Exception as e:
            self._log(f"LLM scoring failed: {e}", "warning")
            # Fallback to default scores
            for article in batch:
                article['llm_score'] = 5.0
                
        return batch

    def _build_relevance_prompt(self, articles: list) -> str:
        """Build prompt for LLM relevance assessment using template.
        
        Cost-optimized: Uses only title and serpapi_snippet instead of full content.
        """
        # Prepare articles summary using only title and snippet (cost-effective)
        articles_summary = ""
        for i, article in enumerate(articles, 1):
            title = article.get('title', 'Untitled')[:100]
            # Use serpapi_snippet if available, otherwise fallback to short content preview
            snippet = article.get('serpapi_snippet', '')
            if not snippet:
                # Fallback to first 200 chars of content if snippet not available
                snippet = article.get('content', '')[:200].replace('\n', ' ')
            
            articles_summary += f"\n{i}. Title: {title}\nSnippet: {snippet}\n"
        
        # Use template
        return self.relevance_prompt_template.format(
            query=self.query,
            articles_summary=articles_summary
        )

    def _parse_llm_scores(self, response: str, expected_count: int) -> list:
        """Parse LLM response to extract numerical scores."""
        scores = []
        
        # Look for pattern like "1:8 2:6 3:9"
        pattern = r'(\d+):(\d+(?:\.\d+)?)'
        matches = re.findall(pattern, response)
        
        # Convert to scores array
        score_dict = {int(match[0]): float(match[1]) for match in matches}
        
        for i in range(1, expected_count + 1):
            scores.append(score_dict.get(i, 5.0))  # Default to 5.0 if not found
            
        return scores

    def _select_final_articles(self, articles: list) -> list:
        """Select final articles based on LLM score criteria."""
        # Filter by minimum score
        qualified_articles = [
            article for article in articles
            if article['llm_score'] >= self.min_score
        ]
        
        # Take top N articles
        return qualified_articles

    def _finalize_filtering(self, filtered_articles: list) -> dict:
        """Save filtered articles to MongoDB database (no local file storage needed)."""
        
        # Prepare articles for MongoDB storage
        db_articles = []
        final_articles = []
        
        for i, article in enumerate(filtered_articles, 1):
            score = article['llm_score']
            original_name = article['filename']
            
            try:
                # Prepare for database storage
                article['llm_score'] = score  # Update with final score
                db_article = self._convert_to_vynn_article(article)
                if db_article:
                    db_articles.append(db_article)
                
                final_articles.append({
                    "rank": i,
                    "original_filename": original_name,
                    "llm_score": score,
                    "title": article['title']
                })
                    
            except Exception as e:
                self._log(f"Error preparing article {original_name}: {e}", "error")
                continue
        
        # Save to MongoDB (primary storage)
        db_result = self._save_to_mongodb(db_articles)
        
        result = {"filtered_articles": final_articles}
        if db_result:
            result["mongodb_result"] = db_result
        
        return result

    def _save_to_mongodb(self, articles: list) -> dict:
        """
        Save filtered articles to MongoDB in multiple collections: ticker, sector, and industry.
        
        This enables:
        1. Ticker-specific news analysis (existing functionality)
        2. Sector-wide news aggregation (for sector daily reports)
        3. Industry-wide news aggregation (for industry analysis)
        """
        if not self.db_enabled:
            self._log("MongoDB storage skipped - vynn_core not enabled", "warning")
            return None
        
        if not articles:
            self._log("MongoDB storage skipped - no articles to save", "info")
            return None
            
        try:
            # Extract sector and industry from first article (all should have same company metadata)
            if articles and not self.company_sector and not self.company_industry:
                first_article = articles[0]
                self.company_sector = first_article.get('sector')
                self.company_industry = first_article.get('industry')
                
                if self.company_sector:
                    self._log(f"� Detected sector: {self.company_sector}", "info")
                if self.company_industry:
                    self._log(f"🏭 Detected industry: {self.company_industry}", "info")
            
            # Save to multiple collections
            all_results = {}
            
            # 1. Save to ticker collection (primary - existing functionality)
            self._log(f"🔄 Saving {len(articles)} articles to MongoDB collection '{self.ticker}'", "info")
            
            ticker_result = upsert_articles(articles, collection_name=self.ticker)
            
            all_results["ticker"] = {
                "collection": self.ticker,
                "created": len(ticker_result['created']),
                "updated": len(ticker_result['updated']),
                "skipped": len(ticker_result['skipped'])
            }
            
            self._log(f"✅ MongoDB storage complete in collection '{self.ticker}' - Created: {len(ticker_result['created'])}, "
                     f"Updated: {len(ticker_result['updated'])}, Skipped: {len(ticker_result['skipped'])}", "info")
            
            # 2. Save to sector collection (NEW - for sector daily reports)
            if self.company_sector and self.company_sector != "Unknown":
                try:
                    sector_collection = self.company_sector.upper().replace(" ", "_")
                    self._log(f"🔄 Saving {len(articles)} articles to sector collection '{sector_collection}'", "info")
                    
                    init_indexes(sector_collection)
                    sector_result = upsert_articles(articles, collection_name=sector_collection)
                    
                    all_results["sector"] = {
                        "collection": sector_collection,
                        "created": len(sector_result['created']),
                        "updated": len(sector_result['updated']),
                        "skipped": len(sector_result['skipped'])
                    }
                    
                    self._log(f"✅ Sector collection '{sector_collection}' - Created: {len(sector_result['created'])}, "
                             f"Updated: {len(sector_result['updated'])}, Skipped: {len(sector_result['skipped'])}", "info")
                             
                except Exception as e:
                    self._log(f"❌ Error saving to sector collection '{sector_collection}': {e}", "error")
                    all_results["sector"] = {"error": str(e)}
            
            # 3. Save to industry collection (NEW - for industry analysis)
            if self.company_industry and self.company_industry != "Unknown":
                try:
                    industry_collection = self.company_industry.upper().replace(" ", "_")
                    self._log(f"🔄 Saving {len(articles)} articles to industry collection '{industry_collection}'", "info")
                    
                    init_indexes(industry_collection)
                    industry_result = upsert_articles(articles, collection_name=industry_collection)
                    
                    all_results["industry"] = {
                        "collection": industry_collection,
                        "created": len(industry_result['created']),
                        "updated": len(industry_result['updated']),
                        "skipped": len(industry_result['skipped'])
                    }
                    
                    self._log(f"✅ Industry collection '{industry_collection}' - Created: {len(industry_result['created'])}, "
                             f"Updated: {len(industry_result['updated'])}, Skipped: {len(industry_result['skipped'])}", "info")
                             
                except Exception as e:
                    self._log(f"❌ Error saving to industry collection '{industry_collection}': {e}", "error")
                    all_results["industry"] = {"error": str(e)}
            
            return all_results
            
        except Exception as e:
            self._log(f"❌ Error saving to MongoDB: {e}", "error")
            import traceback
            self._log(f"Full traceback: {traceback.format_exc()}", "error")
            return None
    
    # REMOVED: generate_llm_report(), _build_report_prompt(), _generate_fallback_report()
    # Reason: Cost optimization - report generation is expensive and not essential
    # Filtered articles with rankings are available in filtered/ directory
    
    # News Feed System Methods

