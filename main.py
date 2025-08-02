#!/usr/bin/env python3
"""
main.py - Integrated stock analysis pipeline combining scraping, filtering, and screening.

This is the main entry point that orchestrates the complete stock analysis workflow:
1. Scrape news articles from Google News (ArticleScraper)
2. Filter articles for relevance (ArticleFilter) 
3. Analyze filtered articles with LLM (ArticleScreener)

▶ Usage:
    
    python main.py --ticker NVDA --company "NVIDIA" --pipeline scrape-only
    python main.py --ticker NVDA --company "NVIDIA" --pipeline filter-screen
"""

from __future__ import annotations
import argparse
import pathlib
import sys
from typing import Optional, Dict, List
from datetime import datetime

# Add src directory to path for imports
sys.path.insert(0, str(pathlib.Path(__file__).parent / "src"))

from scraper import ArticleScraper
from filter import ArticleFilter
from screener import ArticleScreener

class StockAnalysisPipeline:
    """Integrated pipeline for complete stock analysis workflow."""
    
    def __init__(self, ticker: str, company_name: str):
        """
        Initialize the analysis pipeline.
        
        Args:
            ticker: Stock ticker symbol (e.g., 'NVDA')
            company_name: Full company name (e.g., 'NVIDIA')
        """
        self.ticker = ticker.upper()
        self.company_name = company_name
        
        # Initialize all components
        self.scraper = ArticleScraper(ticker, company_name)
        self.filter = ArticleFilter(ticker)
        self.screener = ArticleScreener(ticker)
        
        # Pipeline statistics
        self.stats = {
            "start_time": datetime.now(),
            "stages_completed": [],
            "scraping": {},
            "filtering": {},
            "screening": {}
        }
    
    def run_full_pipeline(self, 
                         max_articles: int = 20,
                         min_filter_score: float = 3.0,
                         max_filtered: int = 10,
                         min_confidence: float = 0.5,
                         generate_reports: bool = True) -> Dict:
        """
        Run the complete analysis pipeline.
        
        Args:
            max_articles: Maximum articles to scrape
            min_filter_score: Minimum relevance score for filtering (0-10)
            max_filtered: Maximum filtered articles to keep
            min_confidence: Minimum confidence for screening insights (0-1)
            generate_reports: Whether to generate analysis reports
            
        Returns:
            Dictionary with complete pipeline results
        """
        print(f"🚀 Starting full analysis pipeline for {self.ticker} ({self.company_name})")
        print("=" * 80)
        
        # Stage 1: Scraping
        print("\n📰 STAGE 1: Article Scraping")
        print("-" * 40)
        scraping_results = self.run_scraping_stage(max_articles)
        
        if scraping_results["scraped_count"] == 0:
            print("❌ No new articles scraped.")
        
        # Stage 2: Filtering  
        print("\n🔍 STAGE 2: Article Filtering")
        print("-" * 40)
        filtering_results = self.run_filtering_stage(min_filter_score, max_filtered)
        
        if not filtering_results["filtered_articles"]:
            print("❌ No articles passed filtering. Pipeline cannot continue.")
            return self._get_pipeline_results()
        
        # Stage 3: Screening
        print("\n🤖 STAGE 3: LLM Analysis & Screening")
        print("-" * 40)
        screening_results = self.run_screening_stage(
            filtering_results["filtered_articles"], 
            min_confidence, 
            generate_reports
        )
        
        # Final results
        print(f"\n✅ Pipeline completed for {self.ticker}")
        self._print_final_summary()
        
        return self._get_pipeline_results()
    
    def run_scraping_stage(self, max_articles: int = 20) -> Dict:
        """Run only the article scraping stage."""
        try:
            # Check current storage status
            storage_info = self.scraper.get_storage_info()
            current_count = storage_info["total_articles"]
            
            print(f"📊 Current articles in storage: {current_count}")
            
            # Perform scraping
            scraping_results = self.scraper.scrape_articles(max_articles)
            
            # Update statistics
            self.stats["scraping"] = scraping_results
            self.stats["stages_completed"].append("scraping")
            
            # Display results
            print(f"✅ Scraping completed:")
            print(f"   New articles: {scraping_results['scraped_count']}")
            print(f"   Duplicates skipped: {scraping_results['duplicate_count']}")
            print(f"   Failed attempts: {scraping_results['failed_count']}")
            print(f"   Success rate: {scraping_results['success_rate']:.1%}")
            
            return scraping_results
            
        except Exception as e:
            print(f"❌ Scraping stage failed: {e}")
            return {"scraped_count": 0, "error": str(e)}
    
    def run_filtering_stage(self, min_score: float = 3.0, max_articles: int = 10) -> Dict:
        """Run only the article filtering stage."""
        try:
            # Perform filtering
            filtered_articles = self.filter.filter_articles(min_score, max_articles)
            
            if not filtered_articles:
                print("⚠️  No articles met the filtering criteria")
                return {"filtered_articles": [], "filtered_count": 0}
            
            # Save filtered articles
            from pathlib import Path
            filtered_dir = Path("data") / self.ticker / "filtered"
            self.filter.save_filtered_articles(filtered_articles, filtered_dir)
            
            # Update statistics
            filtering_results = {
                "filtered_articles": filtered_articles,
                "filtered_count": len(filtered_articles),
                "min_score_used": min_score,
                "avg_score": sum(score for _, score in filtered_articles) / len(filtered_articles)
            }
            self.stats["filtering"] = filtering_results
            self.stats["stages_completed"].append("filtering")
            
            # Display results
            print(f"✅ Filtering completed:")
            print(f"   Articles meeting criteria: {len(filtered_articles)}")
            print(f"   Average score: {filtering_results['avg_score']:.2f}")
            print(f"   Score range: {filtered_articles[-1][1]:.2f} - {filtered_articles[0][1]:.2f}")
            
            # Show top articles
            print(f"   Top 3 articles:")
            for i, (article, score) in enumerate(filtered_articles[:3], 1):
                print(f"     {i}. [{score:.2f}] {article['title'][:60]}...")
            
            return filtering_results
            
        except Exception as e:
            print(f"❌ Filtering stage failed: {e}")
            return {"filtered_articles": [], "error": str(e)}
    
    def run_screening_stage(self, 
                           filtered_articles: List = None, 
                           min_confidence: float = 0.5,
                           generate_reports: bool = True) -> Dict:
        """Run only the screening/analysis stage."""
        try:
            # Load articles if not provided
            if filtered_articles is None:
                articles_data = self.screener.load_filtered_articles()
                if not articles_data:
                    print("❌ No filtered articles found for screening")
                    return {"catalysts": [], "risks": [], "mitigations": []}
            else:
                # Convert filtered articles to format expected by screener
                articles_data = []
                for article, score in filtered_articles:
                    # Ensure article has file_name key that screener expects
                    article_copy = article.copy()
                    if 'file_path' in article_copy and 'file_name' not in article_copy:
                        article_copy['file_name'] = article_copy['file_path'].name
                    articles_data.append(article_copy)
            
            print(f"🔍 Analyzing {len(articles_data)} articles with LLM...")
            
            # Extract insights using LLM (efficient single-pass analysis)
            catalysts, risks, mitigations = self.screener.analyze_all_articles(articles_data)
            
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
                "llm_cost": self.screener.total_llm_cost,
                "llm_calls": self.screener.llm_call_count
            }
            self.stats["screening"] = screening_results
            self.stats["stages_completed"].append("screening")
            
            # Generate reports if requested
            if generate_reports:
                from pathlib import Path
                data_dir = Path("data") / self.ticker
                
                # Generate screening report
                report_file = data_dir / "screening_report.md"
                self.screener.generate_screening_report(
                    high_conf_catalysts, high_conf_risks, high_conf_mitigations, report_file
                )
                
                # Save structured data
                data_file = data_dir / "screening_data.json"
                self.screener.save_structured_data(
                    high_conf_catalysts, high_conf_risks, high_conf_mitigations, data_file
                )
                
                print(f"📄 Reports generated:")
                print(f"   Screening report: {report_file}")
                print(f"   Structured data: {data_file}")
            
            # Display results
            print(f"✅ Screening completed:")
            print(f"   Growth catalysts: {len(high_conf_catalysts)} (of {len(catalysts)} total)")
            print(f"   Risks identified: {len(high_conf_risks)} (of {len(risks)} total)")
            print(f"   Mitigation strategies: {len(high_conf_mitigations)} (of {len(mitigations)} total)")
            print(f"   LLM cost: ${screening_results['llm_cost']:.6f} USD ({screening_results['llm_calls']} calls)")
            
            return screening_results
            
        except Exception as e:
            print(f"❌ Screening stage failed: {e}")
            return {"catalysts": [], "risks": [], "mitigations": [], "error": str(e)}
    
    def _get_pipeline_results(self) -> Dict:
        """Get complete pipeline results."""
        self.stats["end_time"] = datetime.now()
        self.stats["total_duration"] = (self.stats["end_time"] - self.stats["start_time"]).total_seconds()
        return {
            "ticker": self.ticker,
            "company_name": self.company_name,
            "statistics": self.stats
        }
    
    def _print_final_summary(self):
        """Print final pipeline summary."""
        duration = (datetime.now() - self.stats["start_time"]).total_seconds()
        
        print("\n" + "=" * 80)
        print(f"📈 FINAL SUMMARY - {self.ticker} Analysis")
        print("=" * 80)
        print(f"🕒 Total Duration: {duration:.1f} seconds")
        print(f"✅ Stages Completed: {', '.join(self.stats['stages_completed'])}")
        
        if "scraping" in self.stats:
            s = self.stats["scraping"]
            print(f"📰 Scraping: {s.get('scraped_count', 0)} new articles")
        
        if "filtering" in self.stats:
            f = self.stats["filtering"]
            print(f"🔍 Filtering: {f.get('filtered_count', 0)} articles selected")
        
        if "screening" in self.stats:
            sc = self.stats["screening"]
            print(f"🤖 Screening: {len(sc.get('catalysts', []))} catalysts, {len(sc.get('risks', []))} risks")
            if sc.get('llm_cost', 0) > 0:
                print(f"💰 LLM Cost: ${sc['llm_cost']:.6f} USD")

def main():
    """Main entry point for the stock analysis pipeline."""
    parser = argparse.ArgumentParser(
        description="Integrated Stock Analysis Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py --ticker NVDA --company "NVIDIA" --pipeline full
  python main.py --ticker AAPL --company "Apple Inc" --pipeline scrape-only --max-articles 30
  python main.py --ticker TSLA --company "Tesla" --pipeline filter-screen --min-score 4.0
        """
    )
    
    # Required arguments
    parser.add_argument("--ticker", required=True, help="Stock ticker symbol (e.g., NVDA)")
    parser.add_argument("--company", required=True, help="Company name (e.g., 'NVIDIA')")
    
    # Pipeline control
    parser.add_argument("--pipeline", choices=["full", "scrape-only", "filter-only", "screen-only", "filter-screen"], 
                       default="full", help="Which stages to run")
    
    # Scraping parameters
    parser.add_argument("--max-articles", type=int, default=20, help="Maximum articles to scrape")
    parser.add_argument("--search-query", help="Override default search query")
    
    # Filtering parameters
    parser.add_argument("--min-score", type=float, default=3.0, help="Minimum relevance score (0-10)")
    parser.add_argument("--max-filtered", type=int, default=10, help="Maximum filtered articles")
    
    # Screening parameters
    parser.add_argument("--min-confidence", type=float, default=0.5, help="Minimum confidence for insights (0-1)")
    parser.add_argument("--no-reports", action="store_true", help="Skip generating reports")
    
    # Other options
    parser.add_argument("--stats", action="store_true", help="Show current storage statistics")
    
    args = parser.parse_args()
    
    try:
        # Initialize pipeline
        pipeline = StockAnalysisPipeline(args.ticker, args.company)
        
        # Show stats if requested
        if args.stats:
            storage_info = pipeline.scraper.get_storage_info()
            print(f"📊 Current storage statistics for {args.ticker}:")
            print(f"   Directory: {storage_info['company_dir']}")
            print(f"   Total articles: {storage_info['total_articles']}")
            print(f"   Directories: {storage_info['directories_exist']}")
            return 0
        
        # Run selected pipeline
        if args.pipeline == "full":
            results = pipeline.run_full_pipeline(
                max_articles=args.max_articles,
                min_filter_score=args.min_score,
                max_filtered=args.max_filtered,
                min_confidence=args.min_confidence,
                generate_reports=not args.no_reports
            )
            
        elif args.pipeline == "scrape-only":
            results = pipeline.run_scraping_stage(args.max_articles)
            
        elif args.pipeline == "filter-only":
            results = pipeline.run_filtering_stage(args.min_score, args.max_filtered)
            
        elif args.pipeline == "screen-only":
            results = pipeline.run_screening_stage(
                min_confidence=args.min_confidence,
                generate_reports=not args.no_reports
            )
            
        elif args.pipeline == "filter-screen":
            # Run filtering then screening
            filtering_results = pipeline.run_filtering_stage(args.min_score, args.max_filtered)
            if filtering_results["filtered_articles"]:
                screening_results = pipeline.run_screening_stage(
                    filtering_results["filtered_articles"],
                    args.min_confidence,
                    not args.no_reports
                )
        
        return 0
        
    except KeyboardInterrupt:
        print("\n⏹️  Pipeline interrupted by user")
        return 1
    except Exception as e:
        print(f"❌ Pipeline failed: {e}")
        return 1

if __name__ == "__main__":
    exit(main())
