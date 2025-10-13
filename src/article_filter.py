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
    python article_filter.py --ticker NVDA --query "nvidia ai data center growth" --min-score 6.0 --max-articles 8
"""

from __future__ import annotations
import os, csv, argparse, pathlib, re, json, logging
from datetime import datetime
from typing import Dict, List, Tuple, Optional
from llms.config import get_llm

# Import vynn_core for MongoDB integration
try:
    from vynn_core import Article, init_indexes, upsert_articles, find_recent, get_article_by_url, utc_now
    VYNN_CORE_AVAILABLE = True
    print("✅ vynn_core imported successfully for MongoDB integration")
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
        self.filtered_dir = self.company_dir / "filtered"
        
        # Logger - will be set by pipeline if available
        self.logger = None
        
        # LLM tracking
        self.total_llm_cost = 0.0
        self.llm_call_count = 0
        
        # Batch processing configuration
        self.batch_size = 5  # Process articles in batches for efficiency
        
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
        try:
            # Load article relevance scoring prompt
            relevance_path = self.prompts_dir / "article_relevance_scoring.md"
            self.relevance_prompt_template = relevance_path.read_text(encoding='utf-8')
            
            # Load investment report generation prompt
            report_path = self.prompts_dir / "investment_report_generation.md"
            self.report_prompt_template = report_path.read_text(encoding='utf-8')
            
        except Exception as e:
            self._log(f"Error loading prompt templates: {e}", "error")
            # Fallback to simple prompts
            self.relevance_prompt_template = "Rate the relevance of these articles to: {query}\n{articles_summary}\nProvide scores as: 1:X 2:Y etc."
            self.report_prompt_template = "Generate an investment report for {ticker} based on:\n{articles_content}"
    
    def set_logger(self, logger):
        """Set the logger instance."""
        self.logger = logger
    
    def _log(self, message: str, level: str = "info"):
        """Log message using logger if available, otherwise print."""
        if self.logger:
            getattr(self.logger, level)(message)
        else:
            print(f"[{level.upper()}] {message}")

    def filter_articles(self, max_filtered: int = 15, min_score: float = 6.0) -> dict:
        """
        Filter articles using LLM intelligence based on the query.
        
        Args:
            max_filtered: Maximum number of articles to filter
            min_score: Minimum LLM score threshold for article inclusion (1-10 scale)
            
        Returns:
            Dictionary with filtering results and metadata
        """
        self._log(f"Starting LLM-powered filtering for {self.ticker}")
        self._log(f"Query: {self.query}, Target articles: {max_filtered}, Min score: {min_score}")
        
        # Load and prepare articles
        searched_dir = self.company_dir / "searched"
        articles_data = self._load_articles_metadata(searched_dir)
        
        if not articles_data:
            self._log("No articles found to filter")
            return {"filtered_articles": [], "total_processed": 0, "llm_cost": 0.0}
        
        self._log(f"Found {len(articles_data)} articles to process")
        
        # Process all articles with LLM scoring
        scored_articles = self._score_articles_with_llm(articles_data)
        
        # Filter by minimum score and limit count
        filtered_articles = self._select_final_articles(scored_articles, max_filtered, min_score)

        # Copy filtered articles and generate index
        result = self._finalize_filtering(filtered_articles)
        
        # Add metadata
        result.update({
            "query": self.query,
            "total_processed": len(articles_data),
            "llm_cost": self.total_llm_cost,
            "llm_calls": self.llm_call_count
        })
        
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
        """Build prompt for LLM relevance assessment using template."""
        # Prepare articles summary
        articles_summary = ""
        for i, article in enumerate(articles, 1):
            title = article['title'][:100]
            content_preview = article['content'][:500].replace('\n', ' ')
            articles_summary += f"\n{i}. Title: {title}\nPreview: {content_preview}...\n"
        
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

    def _select_final_articles(self, articles: list, max_filtered: int, min_score: float) -> list:
        """Select final articles based on LLM score criteria."""
        # Filter by minimum score
        qualified_articles = [
            article for article in articles 
            if article['llm_score'] >= min_score
        ]
        
        # Take top N articles
        return qualified_articles[:max_filtered]

    def _finalize_filtering(self, filtered_articles: list) -> dict:
        """Copy filtered articles to filtered directory, create index, and save to MongoDB."""
        # Create filtered directory
        self.filtered_dir.mkdir(parents=True, exist_ok=True)
        
        # Clear existing filtered articles
        for existing_file in self.filtered_dir.glob("filtered_*.md"):
            existing_file.unlink()
            
        # Prepare articles for MongoDB storage
        db_articles = []
        final_articles = []
        
        for i, article in enumerate(filtered_articles, 1):
            score = article['llm_score']
            original_name = article['filename']
            
            # Create new filename with ranking and score
            new_filename = f"filtered_{i:02d}_score_{score:.1f}_{original_name}"
            new_path = self.filtered_dir / new_filename
            
            try:
                # Copy the article content
                searched_dir = self.company_dir / "searched"
                source_path = searched_dir / original_name
                
                if source_path.exists():
                    new_path.write_text(
                        source_path.read_text(encoding='utf-8'),
                        encoding='utf-8'
                    )
                    
                    # Prepare for database storage
                    article['llm_score'] = score  # Update with final score
                    db_article = self._convert_to_vynn_article(article)
                    if db_article:
                        db_articles.append(db_article)
                    
                    final_articles.append({
                        "rank": i,
                        "filename": new_filename,
                        "original_filename": original_name,
                        "llm_score": score,
                        "title": article['title']
                    })
                    
            except Exception as e:
                self._log(f"Error copying {original_name}: {e}", "error")
                continue
        
        # Save to MongoDB
        db_result = self._save_to_mongodb(db_articles)
        
        # Create articles index
        self._create_articles_index(final_articles)
        
        result = {"filtered_articles": final_articles}
        if db_result:
            result["mongodb_result"] = db_result
        
        return result

    def _save_to_mongodb(self, articles: list) -> dict:
        """Save filtered articles to MongoDB using vynn_core."""
        if not self.db_enabled:
            self._log("MongoDB storage skipped - vynn_core not enabled", "warning")
            return None
        
        if not articles:
            self._log("MongoDB storage skipped - no articles to save", "info")
            return None
            
        try:
            self._log(f"🔄 Attempting to save {len(articles)} articles to MongoDB collection '{self.ticker}'", "info")
            
            # Debug: Print sample article data
            self._log(f"Sample article data: {articles[0].keys() if articles else 'No articles'}", "debug")
            
            # Use vynn_core to save articles to ticker-specific collection
            result = upsert_articles(articles, collection_name=self.ticker)
            
            self._log(f"✅ MongoDB storage complete in collection '{self.ticker}' - Created: {len(result['created'])}, "
                     f"Updated: {len(result['updated'])}, Skipped: {len(result['skipped'])}", "info")
            
            # Debug: Print detailed results
            if result['created']:
                self._log(f"Created article IDs: {result['created'][:3]}...", "debug")
            
            return result
            
        except Exception as e:
            self._log(f"❌ Error saving to MongoDB: {e}", "error")
            import traceback
            self._log(f"Full traceback: {traceback.format_exc()}", "error")
            return None

    def _create_articles_index(self, articles: list):
        """Create CSV index with LLM scoring information."""
        index_path = self.filtered_dir / "filtered_articles_index.csv"
        
        try:
            with open(index_path, 'w', newline='', encoding='utf-8') as csvfile:
                fieldnames = ['rank', 'filename', 'original_filename', 'title', 'llm_score']
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                
                for article in articles:
                    writer.writerow(article)
                    
            self._log(f"Created articles index at {index_path}")
            
        except Exception as e:
            self._log(f"Error creating articles index: {e}", "error")
    
    def generate_llm_report(self, filtered_articles: list) -> str:
        """
        Generate an intelligent investment report using LLM analysis of filtered articles.
        
        Args:
            filtered_articles: List of filtered article metadata
            
        Returns:
            Generated report as markdown string
        """
        if not filtered_articles:
            return "# Investment Analysis Report\n\nNo relevant articles found for analysis."
            
        self._log(f"Generating LLM report for {len(filtered_articles)} articles")
        
        try:
            # Build comprehensive prompt for report generation
            prompt = self._build_report_prompt(filtered_articles)
            
            # Generate report using LLM with proper message format
            messages = [
                {"role": "system", "content": "You are a senior financial analyst generating concise research-ready notes."},
                {"role": "user", "content": prompt},
            ]
            report, cost = get_llm()(messages, temperature=0.3)
            self.llm_call_count += 1
            
            # Track actual cost from LLM call
            self.total_llm_cost += cost
            
            # Add metadata footer
            report += f"\n\n---\n*Report generated using AI analysis of {len(filtered_articles)} filtered articles*\n"
            report += f"*Query: {self.query}*\n"
            report += f"*LLM calls: {self.llm_call_count}, Total cost: ${self.total_llm_cost:.4f}*"
            
            return report
            
        except Exception as e:
            self._log(f"LLM report generation failed: {e}", "error")
            return self._generate_fallback_report(filtered_articles)

    def _build_report_prompt(self, articles: list) -> str:
        """Build comprehensive prompt for investment report generation using template."""
        # Prepare articles content
        articles_content = ""
        for i, article in enumerate(articles[:8], 1):  # Limit to top 8 for token management
            title = article['title']
            score = article['llm_score']
            
            # Read article content for analysis
            try:
                searched_dir = self.company_dir / "searched"
                source_path = searched_dir / article['original_filename']
                if source_path.exists():
                    content = source_path.read_text(encoding='utf-8')
                    # Extract key sections (first 500 words)
                    content_preview = ' '.join(content.split()[:500])
                else:
                    content_preview = "Content not available"
            except:
                content_preview = "Content not available"
                
            articles_content += f"\n--- Article {i} (Score: {score:.1f}) ---\n"
            articles_content += f"Title: {title}\n"
            articles_content += f"Content: {content_preview}\n"
        
        # Use template
        return self.report_prompt_template.format(
            ticker=self.ticker,
            query=self.query,
            articles_content=articles_content
        )

    def _generate_fallback_report(self, articles: list) -> str:
        """Generate basic report without LLM when LLM fails."""
        report = f"# Investment Analysis Report - {self.ticker}\n\n"
        report += f"**Query:** {self.query}\n\n"
        report += f"**Analysis Date:** {datetime.now().strftime('%Y-%m-%d')}\n\n"
        
        report += "## Executive Summary\n\n"
        report += f"Analyzed {len(articles)} relevant articles for {self.ticker} investment insights.\n\n"
        
        report += "## Key Articles\n\n"
        for i, article in enumerate(articles[:5], 1):
            score = article['llm_score']
            report += f"{i}. **{article['title']}** (Score: {score:.1f})\n"
            
        report += "\n*Note: Detailed analysis unavailable due to LLM service issues.*\n"
        
        return report

    # News Feed System Methods

    def get_recent_articles_from_db(self, limit: int = 50, min_score: float = 5.0) -> list:
        """
        Retrieve recent articles from MongoDB for news feed system.
        
        Args:
            limit: Maximum number of articles to retrieve
            min_score: Minimum LLM score threshold
            
        Returns:
            List of articles sorted by relevance and recency
        """
        if not self.db_enabled:
            self._log("MongoDB not available for news feed", "warning")
            return []
            
        try:
            self._log(f"Retrieving recent articles for {self.ticker} (limit: {limit}, min_score: {min_score})")
            
            # Get recent articles from database
            recent_articles = find_recent(limit=limit * 2)  # Get more to allow filtering
            
            # Filter by ticker and score
            filtered_articles = []
            for article in recent_articles:
                # Check if article is relevant to our ticker
                entities = article.get('entities', {})
                tickers = entities.get('tickers', [])
                quality = article.get('quality', {})
                llm_score = quality.get('llmScore', 0.0)
                
                if self.ticker in tickers and llm_score >= min_score:
                    # Add ranking score for news feed
                    article['feed_score'] = self._calculate_feed_score(article)
                    filtered_articles.append(article)
            
            # Sort by feed score (combination of LLM score and recency)
            filtered_articles.sort(key=lambda x: x.get('feed_score', 0), reverse=True)
            
            result = filtered_articles[:limit]
            self._log(f"Retrieved {len(result)} articles for news feed")
            
            return result
            
        except Exception as e:
            self._log(f"Error retrieving articles from database: {e}", "error")
            return []

    def _calculate_feed_score(self, article: dict) -> float:
        """
        Calculate feed ranking score combining LLM score and recency.
        
        Args:
            article: Article dictionary from database
            
        Returns:
            Combined feed score for ranking
        """
        try:
            # Get LLM score
            quality = article.get('quality', {})
            llm_score = quality.get('llmScore', 5.0)
            
            # Calculate recency factor
            published_at = article.get('publishedAt')
            if published_at:
                if hasattr(published_at, 'timestamp'):
                    age_hours = (datetime.utcnow().timestamp() - published_at.timestamp()) / 3600
                else:
                    # Handle datetime object
                    age_hours = (datetime.utcnow() - published_at).total_seconds() / 3600
                
                # Recency decay: newer articles get higher scores
                recency_factor = max(0.1, 1.0 / (1 + age_hours / 24))  # Decay over days
            else:
                recency_factor = 0.1
            
            # Combine scores (weighted average)
            feed_score = (llm_score * 0.7) + (recency_factor * 10 * 0.3)
            
            return feed_score
            
        except Exception as e:
            self._log(f"Error calculating feed score: {e}", "warning")
            return 5.0

    def check_article_exists(self, url: str) -> dict:
        """
        Check if an article already exists in the database.
        
        Args:
            url: Article URL to check
            
        Returns:
            Article data if exists, None otherwise
        """
        if not self.db_enabled:
            return None
            
        try:
            return get_article_by_url(url)
        except Exception as e:
            self._log(f"Error checking article existence: {e}", "error")
            return None

    def update_article_score(self, article_id: str, new_score: float, reason: str) -> bool:
        """
        Update an article's LLM score in the database.
        
        Args:
            article_id: MongoDB ObjectId of the article
            new_score: New LLM score
            reason: Reason for the score update
            
        Returns:
            True if successful, False otherwise
        """
        if not self.db_enabled:
            return False
            
        try:
            # Note: This would require extending vynn_core with an update method
            # For now, just log the intent
            self._log(f"Would update article {article_id} score to {new_score}: {reason}")
            return True
        except Exception as e:
            self._log(f"Error updating article score: {e}", "error")
            return False

    @classmethod
    def create_news_feed_filter(cls, ticker: str, query: str = None):
        """
        Factory method to create an ArticleFilter optimized for news feed operations.
        
        Args:
            ticker: Stock ticker symbol
            query: Optional query string (defaults to ticker-based query)
            
        Returns:
            ArticleFilter instance configured for news feed
        """
        if not query:
            query = f"{ticker} stock analysis market performance earnings"
            
        # Use a temporary path since we're primarily using database
        base_path = pathlib.Path.cwd() / "temp_news_feed" / ticker
        
        filter_instance = cls(ticker=ticker, query=query, base_path=base_path)
        filter_instance._log(f"Created news feed filter for {ticker}")
        
        return filter_instance


