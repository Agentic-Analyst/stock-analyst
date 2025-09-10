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
from llms import gpt_4o_mini

class ArticleFilter:
    def __init__(self, ticker: str, query: str, base_path: pathlib.Path):
        """
        Initialize LLM-powered article filter.
        
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

    def filter_articles(self, num_articles: int = 10, min_score: float = 6.0) -> dict:
        """
        Filter articles using LLM intelligence based on the query.
        
        Args:
            num_articles: Maximum number of articles to filter
            min_score: Minimum LLM score threshold for article inclusion (1-10 scale)
            
        Returns:
            Dictionary with filtering results and metadata
        """
        self._log(f"Starting LLM-powered filtering for {self.ticker}")
        self._log(f"Query: {self.query}, Target articles: {num_articles}, Min score: {min_score}")
        
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
        filtered_articles = self._select_final_articles(scored_articles, num_articles, min_score)
        
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
        """Extract key metadata from article content."""
        lines = content.split('\n')
        metadata = {
            'filename': filename,
            'title': '',
            'url': '',
            'content': content,
            'word_count': len(content.split()),
            'llm_score': 0.0
        }
        
        # Extract title and URL from markdown headers
        for line in lines[:20]:  # Check first 20 lines
            line = line.strip()
            if line.startswith('# ') and not metadata['title']:
                metadata['title'] = line[2:].strip()
            elif line.startswith('**URL:**') or line.startswith('URL:'):
                metadata['url'] = line.split(':', 1)[1].strip()
                break
                
        return metadata

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
            response, cost = gpt_4o_mini(messages, temperature=0.1)
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
            content_preview = article['content'][:300].replace('\n', ' ')
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

    def _select_final_articles(self, articles: list, num_articles: int, min_score: float) -> list:
        """Select final articles based on LLM score criteria."""
        # Filter by minimum score
        qualified_articles = [
            article for article in articles 
            if article['llm_score'] >= min_score
        ]
        
        # Take top N articles
        return qualified_articles[:num_articles]

    def _finalize_filtering(self, filtered_articles: list) -> dict:
        """Copy filtered articles to filtered directory and create index."""
        # Create filtered directory
        self.filtered_dir.mkdir(parents=True, exist_ok=True)
        
        # Clear existing filtered articles
        for existing_file in self.filtered_dir.glob("filtered_*.md"):
            existing_file.unlink()
            
        # Copy filtered articles with new naming
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
                    
                    final_articles.append({
                        "rank": i,
                        "filename": new_filename,
                        "original_filename": original_name,
                        "llm_score": score,
                        "title": article['title']
                    })
                    
                    self._log(f"Filtered #{i}: {new_filename} (score: {score:.1f})")
                    
            except Exception as e:
                self._log(f"Error copying {original_name}: {e}", "error")
                continue
        
        # Create articles index
        self._create_articles_index(final_articles)
        
        return {"filtered_articles": final_articles}

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
            report, cost = gpt_4o_mini(messages, temperature=0.3)
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

def main():
    """
    Command-line interface for LLM-powered article filtering.
    """
    parser = argparse.ArgumentParser(description="Filter articles using LLM intelligence")
    parser.add_argument("--ticker", required=True, help="Stock ticker symbol (e.g., NVDA)")
    parser.add_argument("--query", required=True, help="Investment query for LLM-based relevance assessment")
    parser.add_argument("--num-articles", type=int, default=10, help="Maximum articles to filter")
    parser.add_argument("--min-score", type=float, default=6.0, help="Minimum LLM relevance score (1-10)")
    
    args = parser.parse_args()
    
    # Initialize filter with data path and query
    base_path = pathlib.Path("data") / args.ticker
    filter_engine = ArticleFilter(args.ticker, args.query, base_path)
    
    # Configure logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    logger = logging.getLogger(__name__)
    filter_engine.set_logger(logger)
    
    # Run LLM-powered filtering
    logger.info(f"Starting LLM-powered filtering for {args.ticker}")
    logger.info(f"Investment query: {args.query}")
    
    result = filter_engine.filter_articles(
        num_articles=args.num_articles,
        min_score=args.min_score
    )
    
    if not result['filtered_articles']:
        logger.warning("No articles met the filtering criteria")
        return
    
    logger.info(f"Successfully filtered {len(result['filtered_articles'])} articles")
    logger.info(f"LLM cost: ${result['llm_cost']:.4f} ({result['llm_calls']} calls)")
    
    # Display results
    for article in result['filtered_articles']:
        score = article['llm_score']
        title = article['title'][:80]
        logger.info(f"  [{score:.1f}] {title}...")
    
    # Generate LLM report if requested
    if result['filtered_articles']:
        logger.info("Generating LLM-powered investment report...")
        report = filter_engine.generate_llm_report(result['filtered_articles'])
        
        # Save report
        report_path = filter_engine.filtered_dir / "filtered_report.md"
        report_path.write_text(report, encoding='utf-8')
        logger.info(f"Investment report saved: {report_path}")
    
    logger.info("Article filtering complete!")

if __name__ == "__main__":
    main()
