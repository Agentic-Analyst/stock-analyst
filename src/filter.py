#!/usr/bin/env python3
"""
filter.py - Filter scraped articles to keep only the most relevant ones.

▶ Usage:
    python filter.py --ticker NVDA --min-score 5.0 --max-articles 5
"""

from __future__ import annotations
import os, csv, argparse, pathlib, re, json
from datetime import datetime, timedelta
from typing import Dict, List, Tuple
import yaml

# Use environment variable for data path, default to local development
DATA_ROOT = pathlib.Path(os.getenv('DATA_PATH', 'data'))

class ArticleFilter:
    def __init__(self, ticker: str):
        self.ticker = ticker.upper()
        self.company_dir = DATA_ROOT / self.ticker
        
        # Logger - will be set by pipeline if available
        self.logger = None
        
        # Define relevance keywords and their weights
        self.relevance_keywords = {
            # High relevance - core investment topics
            "high": {
                "stock price": 3.0,
                "price target": 3.0,
                "analyst rating": 3.0,
                "buy rating": 3.0,
                "sell rating": 3.0,
                "earnings": 2.8,
                "revenue": 2.8,
                "profit": 2.5,
                "financial results": 2.5,
                "quarterly results": 2.5,
                "guidance": 2.5,
                "forecast": 2.3,
                "outlook": 2.3,
                "valuation": 2.3,
                "market cap": 2.0,
                "dividend": 2.0,
                "investment": 2.0,
            },
            # Medium relevance - business and market topics
            "medium": {
                "data center": 1.8,
                "artificial intelligence": 1.8,
                "ai": 1.8,
                "gpu": 1.5,
                "semiconductor": 1.5,
                "chip": 1.5,
                "competition": 1.5,
                "market share": 1.5,
                "partnership": 1.3,
                "acquisition": 1.3,
                "merger": 1.3,
                "expansion": 1.3,
                "growth": 1.3,
                "innovation": 1.0,
                "technology": 1.0,
            },
            # Low relevance - general mentions
            "low": {
                "announcement": 0.8,
                "news": 0.5,
                "update": 0.5,
                "report": 0.5,
            }
        }
        
        # Negative keywords that reduce relevance
        self.negative_keywords = {
            "advertisement": -2.0,
            "sponsored": -2.0,
            "cookie": -1.5,
            "privacy policy": -1.5,
            "terms of service": -1.5,
            "subscribe": -1.0,
            "newsletter": -1.0,
        }
        
        # Quality indicators
        self.quality_indicators = {
            "analyst": 1.0,
            "wall street": 1.0,
            "morgan stanley": 0.8,
            "goldman sachs": 0.8,
            "jpmorgan": 0.8,
            "bank of america": 0.8,
            "credit suisse": 0.8,
            "financial": 0.5,
        }
    
    def set_logger(self, logger):
        """Set the logger instance."""
        self.logger = logger
    
    def _log(self, level: str, message: str):
        """Log message using logger if available, otherwise print."""
        if self.logger:
            getattr(self.logger, level)(message)
        else:
            print(f"[{level.upper()}] {message}")
    
    def load_article(self, file_path: pathlib.Path) -> Dict | None:
        """Load and parse a markdown article file."""
        try:
            content = file_path.read_text(encoding="utf-8")
            
            # Split frontmatter and content
            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    frontmatter = yaml.safe_load(parts[1]) or {}
                    text_content = parts[2].strip()
                else:
                    frontmatter = {}
                    text_content = content
            else:
                frontmatter = {}
                text_content = content
            
            return {
                "file_path": file_path,
                "title": frontmatter.get("title", ""),
                "source_url": frontmatter.get("source_url", ""),
                "publish_date": frontmatter.get("publish_date", ""),
                "text": text_content,
                "word_count": len(text_content.split()),
            }
        except Exception as e:
            self._log("warning", f"Could not load {file_path}: {e}")
            return None
    
    def calculate_relevance_score(self, article: Dict) -> float:
        """Calculate relevance score based on content analysis (0.0 to 1.0 scale)."""
        full_text = f"{article['title']} {article['text']}".lower()
        word_count = article["word_count"]
        
        # Base score components
        raw_score = 0.0
        total_possible_score = 0.0
        
        # 1. Ticker symbol mentions (highest priority)
        ticker_mentions = len(re.findall(rf'\b{self.ticker.lower()}\b', full_text))
        ticker_score = min(ticker_mentions * 0.15, 0.3)  # Cap at 30% of total
        raw_score += ticker_score
        
        # 2. Relevance keywords with diminishing returns
        keyword_score = 0.0
        for category, keywords in self.relevance_keywords.items():
            for keyword, base_weight in keywords.items():
                mentions = len(re.findall(rf'\b{re.escape(keyword.lower())}\b', full_text))
                if mentions > 0:
                    # Diminishing returns: first mention = full weight, subsequent = 50%
                    weight = base_weight * 0.02  # Scale down base weights
                    contribution = weight + (mentions - 1) * weight * 0.5
                    keyword_score += min(contribution, weight * 2)  # Cap per keyword
        
        keyword_score = min(keyword_score, 0.4)  # Cap at 40% of total
        raw_score += keyword_score
        
        # 3. Quality indicators
        quality_score = 0.0
        for keyword, base_weight in self.quality_indicators.items():
            mentions = len(re.findall(rf'\b{re.escape(keyword.lower())}\b', full_text))
            if mentions > 0:
                quality_score += base_weight * 0.02
        
        quality_score = min(quality_score, 0.2)  # Cap at 20% of total
        raw_score += quality_score
        
        # 4. Apply negative keywords (penalties)
        penalty = 0.0
        for keyword, base_weight in self.negative_keywords.items():
            mentions = len(re.findall(rf'\b{re.escape(keyword.lower())}\b', full_text))
            if mentions > 0:
                penalty += abs(base_weight) * 0.05 * mentions
        
        penalty = min(penalty, 0.3)  # Cap penalty at 30%
        raw_score = max(0.0, raw_score - penalty)
        
        # 5. Content length adjustment
        if word_count > 1000:
            length_multiplier = 1.1  # Bonus for very long articles
        elif word_count > 500:
            length_multiplier = 1.05  # Small bonus for substantial articles
        elif word_count < 100:
            length_multiplier = 0.7   # Penalty for very short articles
        elif word_count < 200:
            length_multiplier = 0.85  # Small penalty for short articles
        else:
            length_multiplier = 1.0   # Neutral for medium articles
        
        final_score = raw_score * length_multiplier
        
        # Ensure score is between 0.0 and 1.0
        return max(0.0, min(1.0, final_score))
    
    def calculate_freshness_score(self, article: Dict) -> float:
        """Calculate freshness score based on publication date."""
        if not article["publish_date"]:
            return 0.5  # Default score for articles without date
        
        try:
            # Parse ISO format date
            pub_date = datetime.fromisoformat(article["publish_date"].replace("Z", "+00:00"))
            now = datetime.now(pub_date.tzinfo) if pub_date.tzinfo else datetime.now()
            
            days_old = (now - pub_date).days
            
            # Fresher articles get higher scores
            if days_old <= 1:
                return 1.0
            elif days_old <= 3:
                return 0.8
            elif days_old <= 7:
                return 0.6
            elif days_old <= 30:
                return 0.4
            else:
                return 0.2
        except:
            return 0.5
    
    def calculate_source_quality_score(self, article: Dict) -> float:
        """Calculate source quality score based on the source URL."""
        url = article["source_url"].lower()
        
        # High-quality financial sources
        high_quality_sources = [
            "fool.com", "finance.yahoo.com", "bloomberg.com", "reuters.com",
            "cnbc.com", "marketwatch.com", "wsj.com", "ft.com", "barrons.com",
            "seekingalpha.com", "investorplace.com", "zacks.com", "tipranks.com"
        ]
        
        # Medium-quality sources
        medium_quality_sources = [
            "nasdaq.com", "investing.com", "benzinga.com", "thestreet.com",
            "investors.com", "morningstar.com"
        ]
        
        for source in high_quality_sources:
            if source in url:
                return 1.0
        
        for source in medium_quality_sources:
            if source in url:
                return 0.7
        
        return 0.5  # Default for unknown sources
    
    def calculate_overall_score(self, article: Dict) -> float:
        """Calculate overall score combining all factors (0.0 to 10.0 scale for user-friendly display)."""
        relevance = self.calculate_relevance_score(article)  # 0.0 to 1.0
        freshness = self.calculate_freshness_score(article)  # 0.0 to 1.0
        source_quality = self.calculate_source_quality_score(article)  # 0.0 to 1.0
        
        # Weighted combination (still 0.0 to 1.0)
        normalized_score = (
            relevance * 0.6 +      # Relevance is most important
            freshness * 0.2 +      # Freshness matters
            source_quality * 0.2   # Source quality matters
        )
        
        # Scale to 0-10 for user-friendly display
        return normalized_score * 10.0
    
    def filter_articles(self, min_score: float = 3.0, max_articles: int = 10) -> List[Tuple[Dict, float]]:
        """Filter articles and return the best ones with their scores."""
        if not self.company_dir.exists():
            self._log("error", f"Directory {self.company_dir} does not exist")
            return []
        
        articles_with_scores = []
        
        # Load all markdown files
        searched_dir = self.company_dir / "searched"
        if not searched_dir.exists():
            self._log("error", f"Searched directory {searched_dir} does not exist")
            return []

        for md_file in searched_dir.glob("*.md"):
            if md_file.name == "README.md":  # Skip README files
                continue
            
            article = self.load_article(md_file)
            if not article:
                continue
            
            score = self.calculate_overall_score(article)
            if score >= min_score:
                articles_with_scores.append((article, score))
        
        # Sort by score (descending) and limit results
        articles_with_scores.sort(key=lambda x: x[1], reverse=True)
        return articles_with_scores[:max_articles]
    
    def generate_filtered_report(self, filtered_articles: List[Tuple[Dict, float]], output_file: pathlib.Path):
        """Generate a report with the filtered articles."""
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(f"# Filtered {self.ticker} Stock Analysis Report\n\n")
            f.write(f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Total articles analyzed: {len(list(self.company_dir.glob('*.md')))}\n")
            f.write(f"Articles meeting criteria: {len(filtered_articles)}\n\n")
            
            for i, (article, score) in enumerate(filtered_articles, 1):
                f.write(f"## Article {i}: {article['title']}\n\n")
                f.write(f"**Relevance Score:** {score:.2f}\n")
                f.write(f"**Source:** {article['source_url']}\n")
                f.write(f"**Published:** {article['publish_date']}\n")
                f.write(f"**Word Count:** {article['word_count']}\n\n")
                
                # Include first paragraph or summary
                text_lines = article['text'].split('\n')
                first_paragraph = next((line.strip() for line in text_lines if line.strip() and not line.startswith('#')), "")
                if first_paragraph and len(first_paragraph) > 50:
                    f.write(f"**Summary:** {first_paragraph[:300]}{'...' if len(first_paragraph) > 300 else ''}\n\n")
                
                f.write("---\n\n")
    
    def save_filtered_articles(self, filtered_articles: List[Tuple[Dict, float]], output_dir: pathlib.Path):
        """Save filtered articles to a new directory."""
        output_dir.mkdir(exist_ok=True)
        
        # Create a new index file
        index_file = output_dir / "filtered_articles_index.csv"
        with open(index_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["score", "title", "source_url", "file", "publish_date"])
            writer.writeheader()
            
            for i, (article, score) in enumerate(filtered_articles, 1):
                # Create new filename with score prefix
                original_name = article["file_path"].name
                new_name = f"filtered_{i:02d}_score_{score:.1f}_{original_name}"
                new_path = output_dir / new_name
                
                # Copy the article content
                new_path.write_text(article["file_path"].read_text(encoding="utf-8"), encoding="utf-8")
                
                # Write to index
                writer.writerow({
                    "score": f"{score:.2f}",
                    "title": article["title"],
                    "source_url": article["source_url"],
                    "file": new_name,
                    "publish_date": article["publish_date"]
                })

def main():
    parser = argparse.ArgumentParser(description="Filter scraped articles for relevance")
    parser.add_argument("--ticker", required=True, help="Stock ticker, e.g. NVDA")
    parser.add_argument("--min-score", type=float, default=3.0, help="Minimum relevance score (0.0-10.0)")
    parser.add_argument("--max-articles", type=int, default=10, help="Maximum number of articles to keep")
    parser.add_argument("--output-report", action="store_true", help="Generate a summary report")
    parser.add_argument("--save-filtered", action="store_true", help="Save filtered articles to separate directory")
    
    args = parser.parse_args()
    
    # Initialize filter
    filter_engine = ArticleFilter(args.ticker)
    
    # Filter articles
    filter_engine._log("info", f"Filtering articles for {args.ticker} with min score {args.min_score}")
    filtered_articles = filter_engine.filter_articles(args.min_score, args.max_articles)
    
    if not filtered_articles:
        filter_engine._log("warning", "No articles met the filtering criteria")
        return
    
    filter_engine._log("info", f"Found {len(filtered_articles)} relevant articles:")
    
    # Display results
    for i, (article, score) in enumerate(filtered_articles, 1):
        filter_engine._log("info", f"  {i}. [{score:.2f}] {article['title'][:80]}...")
    
    # Generate report if requested
    if args.output_report:
        report_file = DATA_ROOT / args.ticker / "filtered_report.md"
        filter_engine.generate_filtered_report(filtered_articles, report_file)
        filter_engine._log("info", f"Report generated: {report_file}")
    
    # Save filtered articles if requested
    if args.save_filtered:
        filtered_dir = DATA_ROOT / args.ticker / "filtered"
        filter_engine.save_filtered_articles(filtered_articles, filtered_dir)
        filter_engine._log("info", f"Filtered articles saved to: {filtered_dir}")

if __name__ == "__main__":
    main()
