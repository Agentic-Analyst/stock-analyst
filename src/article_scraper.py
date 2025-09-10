#!/usr/bin/env python3
"""
article_scraper.py - News article scraper and collector for stock analysis.

This module provides the ArticleScraper class for collecting and storing news articles
from Google News via SerpAPI. Compatible with filter.py and screener.py modules.

▶ Usage:
    python src/article_scraper.py --company "NVIDIA" --ticker NVDA --max 15
"""

from __future__ import annotations
import os, csv, time, argparse, pathlib, json
from datetime import datetime
from typing import Dict, List, Optional, Set
from slugify import slugify

from serpapi import GoogleSearch
from newspaper import Article

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
        self.index_csv = self.searched_dir / "articles_index.csv"

        # Logger - will be set by pipeline if available
        self.logger = None
        
        # Statistics tracking
        self.scraped_count = 0
        self.duplicate_count = 0
        self.failed_count = 0
        
        # API configuration
        self.api_key = os.getenv("SERPAPI_API_KEY")
        if not self.api_key:
            raise RuntimeError("SERPAPI_API_KEY environment variable must be set")
    
    def set_logger(self, logger):
        """Set the logger instance."""
        self.logger = logger
    
    def _log(self, level: str, message: str):
        """Log message using logger if available, otherwise print."""
        if self.logger:
            getattr(self.logger, level)(message)
        else:
            print(f"[{level.upper()}] {message}")
    
    def _serpapi_news_links(self, query: str, max_results: int = 20) -> List[str]:
        """Return up to `max_results` news URLs from Google News via SerpAPI."""
        search = GoogleSearch({
            "q": query,
            "tbm": "nws",
            "num": max_results,
            "api_key": self.api_key
        })
        result = search.get_dict()
        news = result.get("news_results", [])
        return [item["link"] for item in news][:max_results]
    
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
    
    def _load_seen_urls(self) -> Set[str]:
        """Load previously scraped URLs to avoid duplicates."""
        if self.index_csv.exists():
            with open(self.index_csv, newline="", encoding="utf-8") as f:
                return {row["url"] for row in csv.DictReader(f)}
        return set()
    
    def _append_to_index(self, url: str, filename: str):
        """Add scraped article to the index file."""
        is_new_file = not self.index_csv.exists()
        with open(self.index_csv, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["url", "file"])
            if is_new_file:
                writer.writeheader()
            writer.writerow({"url": url, "file": filename})
    
    def _save_article_markdown(self, article_data: Dict) -> pathlib.Path:
        """Save article as markdown file with frontmatter."""
        # Ensure directories exist
        self.company_dir.mkdir(parents=True, exist_ok=True)
        self.searched_dir.mkdir(parents=True, exist_ok=True)
        
        # Generate filename with timestamp and title slug
        timestamp = datetime.utcnow().strftime("%Y-%m-%d-%H%M%S")
        title_slug = slugify(article_data['title'][:60])
        filename = f"{timestamp}_{title_slug}.md"
        file_path = self.searched_dir / filename
        
        # Create markdown content with YAML frontmatter
        markdown_content = (
            f"---\n"
            f"title: \"{article_data['title']}\"\n"
            f"source_url: {article_data['url']}\n"
            f"publish_date: {article_data['publish_date']}\n"
            f"word_count: {article_data['word_count']}\n"
            f"scraped_at: {datetime.utcnow().isoformat()}Z\n"
            f"---\n\n"
            f"{article_data['text']}\n"
        )
        
        file_path.write_text(markdown_content, encoding="utf-8")
        return file_path
    
    def scrape_articles(self, max_searched: int = 20, query_override: Optional[str] = None) -> Dict:
        """
        Scrape news articles for the configured company.
        
        Args:
            max_searched: Maximum number of articles to search/scrape
            query_override: Override the default search query
            
        Returns:
            Dictionary with scraping statistics and results
        """
        # Reset statistics
        self.scraped_count = 0
        self.duplicate_count = 0
        self.failed_count = 0
        
        # Build search query
        query = query_override or f"{self.company_name} stock news"
        
        # Get URLs from SerpAPI
        self._log("info", f"Searching for news articles: '{query}'")
        urls = self._serpapi_news_links(query, max_results=max_searched)
        
        if not urls:
            self._log("warning", "No URLs found from news search")
            return self._get_scraping_results()
        
        # Load previously seen URLs
        seen_urls = self._load_seen_urls()
        self._log("info", f"Found {len(urls)} candidate URLs, {len(seen_urls)} already seen")
        
        # Scrape each URL
        scraped_files = []
        for url in urls:
            if url in seen_urls:
                self.duplicate_count += 1
                continue
            
            if self.logger:
                self.logger.scraping_progress(url, "in progress")
            else:
                self._log("info", f"Scraping: {url}")
            
            article_data = self._scrape_article(url)
            
            if not article_data:
                continue  # Failed scraping already counted in _scrape_article
            
            # Save article
            try:
                file_path = self._save_article_markdown(article_data)
                self._append_to_index(url, file_path.name)
                scraped_files.append(file_path)
                self.scraped_count += 1
                
                if self.logger:
                    self.logger.file_operation("Article saved", file_path)
                else:
                    self._log("info", f"Saved: {file_path}")
                
                time.sleep(1)  # Be polite to servers
                
            except Exception as e:
                self._log("error", f"Failed to save article from {url}: {e}")
                self.failed_count += 1
        
        results = self._get_scraping_results()
        results["scraped_files"] = scraped_files
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
            "index_file": str(self.index_csv),
            "total_articles": self.get_scraped_articles_count(),
            "directories_exist": {
                "company_dir": self.company_dir.exists(),
                "searched_dir": self.searched_dir.exists(),
                "index_file": self.index_csv.exists()
            }
        }

def main():
    """Command-line interface for the article scraper."""
    parser = argparse.ArgumentParser(description="Scrape news articles for stock analysis")
    parser.add_argument("--company", required=True, help="Company name, e.g. NVIDIA")
    parser.add_argument("--ticker", required=True, help="Stock ticker, e.g. NVDA")
    parser.add_argument("--max", type=int, default=20, help="Max articles to scrape per run")
    parser.add_argument("--query", help="Override default search query")
    parser.add_argument("--stats", action="store_true", help="Show current storage statistics")
    
    args = parser.parse_args()
    
    try:
        # Initialize scraper
        scraper = ArticleScraper(args.ticker, args.company)
        
        # Show stats if requested
        if args.stats:
            storage_info = scraper.get_storage_info()
            scraper._log("info", f"Storage statistics for {args.ticker}:")
            scraper._log("info", f"  Company directory: {storage_info['company_dir']}")
            scraper._log("info", f"  Total articles: {storage_info['total_articles']}")
            scraper._log("info", f"  Directories exist: {storage_info['directories_exist']}")
            return
        
        # Perform scraping
        results = scraper.scrape_articles(args.max, args.query)
        
        # Display results
        scraper._log("info", f"Scraping completed for {results['ticker']}:")
        scraper._log("info", f"  New articles scraped: {results['scraped_count']}")
        scraper._log("info", f"  Duplicates skipped: {results['duplicate_count']}")
        scraper._log("info", f"  Failed attempts: {results['failed_count']}")
        scraper._log("info", f"  Success rate: {results['success_rate']:.1%}")
        
        if results['scraped_count'] > 0:
            scraper._log("info", f"Articles saved to: {scraper.searched_dir}")
        
    except Exception as e:
        if 'scraper' in locals():
            scraper._log("error", f"Scraping failed: {e}")
        else:
            print(f"[error] Scraping failed: {e}")
        return 1
    
    return 0

if __name__ == "__main__":
    main()
