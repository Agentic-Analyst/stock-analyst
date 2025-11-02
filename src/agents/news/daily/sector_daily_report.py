#!/usr/bin/env python3
"""
sector_daily_report.py - Daily Sector News Intelligence Report Generator

Generates professional, sector-level daily reports analyzing the last 24 hours of news
across all companies in a sector. Designed for institutional investors who need quick,
actionable sector intelligence for portfolio positioning.

Features:
- Aggregates last 24 hours of news from all companies in a sector
- Identifies sector-wide catalysts, risks, and competitive shifts
- Analyzes price action and rotation trends
- Maps sector themes and provides peer benchmarking
- Generates professional analyst-ready report

Usage:
    python src/agents/news/daily/sector_daily_report.py --sector "Technology" --output reports/
    python src/agents/news/daily/sector_daily_report.py --sector "Healthcare" --companies AAPL,MSFT,GOOGL
"""

from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass, asdict
import tiktoken
from collections import defaultdict

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

# Add src directory to path for imports
src_dir = project_root / "src"
sys.path.insert(0, str(src_dir))

# Load environment variables from project root
from dotenv import load_dotenv
load_dotenv(dotenv_path=project_root / ".env")

from vynn_core.dao.articles import get_last_n_hours_news
from llms.config import get_llm
from logger import StockAnalystLogger
import yfinance as yf

def load_prompt(prompt_name: str) -> str:
    """Load a prompt template from the prompts directory."""
    prompt_file = project_root / "prompts" / f"{prompt_name}.md"
    if prompt_file.exists():
        return prompt_file.read_text(encoding="utf-8")
    raise FileNotFoundError(f"Prompt file not found: {prompt_file}")


@dataclass
class SectorMover:
    """Represents a company that moved significantly in the sector."""
    ticker: str
    company_name: str
    price_change: float  # Percentage
    key_catalyst: str
    sentiment: str  # 'positive', 'neutral', 'negative'
    actionability: str  # 'high', 'medium', 'low'


@dataclass
class SectorCatalyst:
    """Represents a sector-wide catalyst."""
    headline: str
    sub_sector: str  # e.g., "Cloud", "AI", "Auto"
    driver_type: str  # 'demand', 'earnings', 'regulation', 'technology', 'macro'
    sentiment: str  # 'positive', 'neutral', 'negative'
    materiality_score: float  # 0-100
    affected_companies: List[str]  # Ticker symbols
    impact_description: str
    supporting_articles: List[str]  # Article titles


@dataclass
class SectorImpact:
    """Represents financial impact on the sector."""
    lever: str  # 'revenue_growth', 'margins', 'regulatory_risk', 'cost_of_capital'
    direction: str  # 'up', 'down', 'neutral'
    magnitude: str  # e.g., "50 bps", "5%"
    commentary: str


@dataclass
class SectorTheme:
    """Represents a thematic signal in the sector."""
    theme: str  # e.g., "AI Capex", "Pricing Power"
    signal: str  # 'strengthening', 'weakening', 'neutral'
    thesis_impact: str  # 'bullish', 'neutral', 'bearish'
    watchpoint: str


@dataclass
class PeerBenchmark:
    """Represents relative positioning of a company in the sector."""
    ticker: str
    valuation_vs_sector: str  # 'premium', 'fair', 'discount'
    valuation_delta: float  # Percentage vs sector average
    sentiment_trend: str  # 'improving', 'neutral', 'deteriorating'
    risk_reward: str  # 'favorable', 'balanced', 'elevated_risk'


@dataclass
class SectorRisk:
    """Represents a sector-wide risk."""
    trigger: str
    probability: float  # 0-100
    downside_potential: str  # e.g., "$5B", "10%"
    coverage_impact: str  # 'high', 'medium', 'low'
    status: str  # 'monitoring', 'escalating', 'de-escalating'


class SectorDailyReportGenerator:
    """Generate daily news intelligence reports for a sector."""
    
    def __init__(self, 
                 sector: str,
                 output_dir: Optional[Path] = None, 
                 logger: Optional[StockAnalystLogger] = None):
        """
        Initialize the sector daily report generator.
        
        Args:
            sector: Sector name (e.g., "Technology", "Healthcare")
            companies: Optional list of companies with {'ticker': 'AAPL', 'name': 'Apple Inc.'}
                      If None, will query MongoDB sector collection
            output_dir: Output directory for reports (default: project_root/reports/daily/sectors)
            logger: Optional logger instance to use (if None, creates new one)
        """
        self.sector = sector
        self.sector_collection = sector.upper().replace(" ", "_")  # e.g., "TECHNOLOGY"
        self.companies = []
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.logger = logger
        
        # LLM setup
        self.llm = get_llm()
        self.total_llm_cost = 0.0
        
        # Token management
        self.encoding = tiktoken.encoding_for_model("gpt-4o-mini")
        self.max_tokens_per_request = 15000
        self.prompt_overhead_tokens = 1000
        
        self.logger.info(f"Initialized sector daily report generator for {self.sector}")
    
    def _log(self, level: str, message: str):
        """Log message using logger."""
        getattr(self.logger, level)(message)
    
    def _count_tokens(self, text: str) -> int:
        """Count tokens in text."""
        return len(self.encoding.encode(text))
    
    def fetch_sector_news_24h(self) -> List[Dict[str, Any]]:
        """
        Fetch last 24 hours of news for the entire sector from MongoDB.
        
        Returns aggregated news from the sector collection (e.g., TECHNOLOGY collection).
        """
        self._log("info", f"📰 Fetching last 24 hours of sector news for {self.sector}")
        
        try:
            # Query sector collection (e.g., "TECHNOLOGY")
            articles = get_last_n_hours_news(collection_name=self.sector_collection, n_hours_ago=24)
            self._log("info", f"✅ Found {len(articles)} articles for sector {self.sector} in last 24 hours")
            
            if not articles:
                self._log("warning", f"No articles found for sector {self.sector} in the last 24 hours")
                return []
            
            # Convert to expected format and group by company
            formatted_articles = []
            for article in articles:
                formatted_articles.append({
                    'title': article.get('title', 'Untitled'),
                    'url': article.get('url', ''),
                    'ticker': article.get('ticker', 'UNKNOWN'),
                    'company': article.get('company', 'Unknown Company'),
                    'source': article.get('serpapi_source', 'Unknown'),
                    'publish_date': article.get('publish_date', ''),
                    'text': article.get('text', ''),
                    'summary': article.get('summary', article.get('serpapi_snippet', '')),
                    'sector': article.get('sector', self.sector),
                    'industry': article.get('industry', ''),
                })
            
            # Extract unique companies from articles if not provided
            company_set = set()
            for article in formatted_articles:
                if article['ticker'] != 'UNKNOWN':
                    company_set.add((article['ticker'], article['company']))
            self.companies = [{'ticker': t, 'name': n} for t, n in sorted(company_set)]
            self._log("info", f"📊 Identified {len(self.companies)} companies in sector: {[c['ticker'] for c in self.companies]}")
            
            return formatted_articles
            
        except Exception as e:
            self._log("error", f"Error fetching sector articles: {e}")
            import traceback
            self._log("error", traceback.format_exc())
            return []
    
    def fetch_price_action_data(self) -> Dict[str, Any]:
        """
        Fetch price action data for sector companies using yfinance.
        
        Returns sector metrics including top gainers, laggards, and overall move.
        """
        self._log("info", f"📈 Fetching price action data for {len(self.companies)} companies")
        
        try:
            price_data = []
            for company in self.companies:
                ticker = company['ticker']
                try:
                    stock = yf.Ticker(ticker)
                    hist = stock.history(period="5d")  # Last 5 days for context
                    
                    if len(hist) >= 2:
                        latest_close = hist['Close'].iloc[-1]
                        prev_close = hist['Close'].iloc[-2]
                        change_pct = ((latest_close - prev_close) / prev_close) * 100
                        
                        price_data.append({
                            'ticker': ticker,
                            'company': company['name'],
                            'change_pct': change_pct,
                            'latest_close': latest_close
                        })
                except Exception as e:
                    self._log("warning", f"Could not fetch price data for {ticker}: {e}")
            
            # Calculate sector average move
            avg_move = sum(p['change_pct'] for p in price_data) / len(price_data)
            
            # Find top gainer and laggard (only if we have multiple companies)
            if len(price_data) >= 2:
                top_gainer = max(price_data, key=lambda x: x['change_pct'])
                top_laggard = min(price_data, key=lambda x: x['change_pct'])
            else:
                # For single company, set to None to avoid showing same ticker twice
                top_gainer = None
                top_laggard = None
            
            # Determine sentiment
            if avg_move > 1.0:
                sentiment = 'bullish'
                rotation = 'money_flowing_in'
            elif avg_move < -1.0:
                sentiment = 'bearish'
                rotation = 'money_flowing_out'
            else:
                sentiment = 'neutral'
                rotation = 'neutral'
            
            return {
                'sector_1d_move': round(avg_move, 2),
                'top_gainer': top_gainer,
                'top_laggard': top_laggard,
                'sentiment': sentiment,
                'rotation_trend': rotation,
                'company_moves': price_data
            }
        except Exception as e:
            self._log("error", f"Error fetching price action data: {e}")
            import traceback
            self._log("error", traceback.format_exc())
    
    def _format_articles_for_sector_analysis(self, articles: List[Dict]) -> str:
        """Format articles for sector-level LLM analysis."""
        # Group articles by company
        articles_by_company = defaultdict(list)
        for article in articles:
            ticker = article.get('ticker', 'UNKNOWN')
            articles_by_company[ticker].append(article)
        
        formatted = f"# Sector: {self.sector}\n"
        formatted += f"# Companies Covered: {len(articles_by_company)}\n"
        formatted += f"# Total Articles: {len(articles)}\n\n"
        
        for ticker, company_articles in sorted(articles_by_company.items()):
            company_name = company_articles[0].get('company', ticker)
            formatted += f"\n## {ticker} - {company_name} ({len(company_articles)} articles)\n\n"
            
            for i, article in enumerate(company_articles, 1):
                formatted += f"### Article #{i}\n"
                formatted += f"**Title**: {article['title']}\n"
                formatted += f"**Source**: {article['source']}\n"
                formatted += f"**Published**: {article['publish_date']}\n"
                formatted += f"**Summary**: {article.get('summary', 'N/A')}\n"
                formatted += f"\n**Key Excerpts**:\n{article['text'][:1000]}...\n"  # Truncate for token efficiency
                formatted += "\n" + "-"*60 + "\n"
        
        return formatted
    
    def analyze_sector_catalysts(self, articles: List[Dict], price_data: Dict) -> List[SectorCatalyst]:
        """
        Analyze articles to identify sector-wide catalysts.
        
        Uses LLM to identify material sector catalysts ranked by impact.
        """
        self._log("info", f"🔍 Analyzing sector catalysts from {len(articles)} articles...")
        
        articles_content = self._format_articles_for_sector_analysis(articles)
        
        # Load prompts
        system_prompt = load_prompt("sector_catalyst_analysis")
        user_prompt_template = load_prompt("sector_catalyst_user")
        
        user_prompt = user_prompt_template.format(
            sector=self.sector,
            num_companies=len(self.companies),
            num_articles=len(articles),
            articles_content=articles_content,
            price_data_summary=json.dumps(price_data, indent=2)
        )
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        try:
            self._log("info", "📡 Sending to LLM for sector catalyst analysis...")
            response, cost = self.llm(messages)
            self.total_llm_cost += cost
            self._log("info", f"💰 LLM cost: ${cost:.4f}")
            
            # Parse JSON response
            analysis_data = self._parse_llm_json_response(response, "sector_catalysts")
            
            # Convert to dataclass objects
            catalysts = []
            for cat_data in analysis_data.get('catalysts', []):
                catalysts.append(SectorCatalyst(
                    headline=cat_data.get('headline', ''),
                    sub_sector=cat_data.get('sub_sector', ''),
                    driver_type=cat_data.get('driver_type', 'unknown'),
                    sentiment=cat_data.get('sentiment', 'neutral'),
                    materiality_score=cat_data.get('materiality_score', 50.0),
                    affected_companies=cat_data.get('affected_companies', []),
                    impact_description=cat_data.get('impact_description', ''),
                    supporting_articles=cat_data.get('supporting_articles', [])
                ))
            
            self._log("info", f"✅ Identified {len(catalysts)} sector catalysts")
            return catalysts
            
        except Exception as e:
            self._log("error", f"Error analyzing sector catalysts: {e}")
            import traceback
            self._log("error", traceback.format_exc())
            return []
    
    def _parse_llm_json_response(self, response: str, response_type: str) -> Dict:
        """Parse JSON from LLM response."""
        try:
            # Try to find JSON in markdown code blocks
            import re
            json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                # Try to find raw JSON
                json_match = re.search(r'\{.*\}', response, re.DOTALL)
                if json_match:
                    json_str = json_match.group(0)
                else:
                    raise ValueError("No JSON found in response")
            
            return json.loads(json_str)
        except Exception as e:
            self._log("error", f"Error parsing {response_type} JSON: {e}")
            self._log("error", f"Response: {response[:500]}...")
            return {}
    
    def generate_sector_report(self) -> str:
        """
        Generate complete sector daily report.
        
        Returns path to generated report.
        """
        self._log("info", f"🚀 Generating sector daily report for {self.sector}")
        
        # Step 1: Fetch sector news
        articles = self.fetch_sector_news_24h()
        if not articles:
            self._log("warning", "No articles found - cannot generate report")
            return None
        
        # Step 2: Fetch price action data
        price_data = self.fetch_price_action_data()
        
        # Step 3: Analyze sector catalysts
        catalysts = self.analyze_sector_catalysts(articles, price_data)
        
        # Step 4: Generate final report using template
        report_content = self._generate_report_from_template(
            articles=articles,
            price_data=price_data,
            catalysts=catalysts
        )
        
        # Step 5: Save report
        report_path = self._save_report(report_content)
        
        self._log("info", f"✅ Sector report generated: {report_path}")
        self._log("info", f"💰 Total LLM cost: ${self.total_llm_cost:.4f}")
        
        return report_path
    
    def _generate_report_from_template(self, 
                                       articles: List[Dict], 
                                       price_data: Dict,
                                       catalysts: List[SectorCatalyst]) -> str:
        """Generate final report using template and LLM."""
        self._log("info", "📝 Generating final report from template...")
        
        # Load report generation prompts
        system_prompt = load_prompt("sector_report_generation")
        user_prompt_template = load_prompt("sector_report_user")
        
        # Prepare data summaries
        catalysts_summary = "\n".join([
            f"{i+1}. {cat.headline} (Materiality: {cat.materiality_score:.0f}%, Sentiment: {cat.sentiment})"
            for i, cat in enumerate(catalysts[:10])  # Top 10
        ])
        
        # Safely extract top gainer/laggard data
        top_gainer = price_data.get('top_gainer') if price_data else None
        top_laggard = price_data.get('top_laggard') if price_data else None
        
        top_gainer_str = (
            f"{top_gainer.get('ticker')} ({top_gainer.get('change_pct', 0):.2f}%)" 
            if top_gainer else "N/A"
        )
        top_laggard_str = (
            f"{top_laggard.get('ticker')} ({top_laggard.get('change_pct', 0):.2f}%)" 
            if top_laggard else "N/A"
        )
        
        price_summary = f"""
Sector 1-Day Move: {price_data.get('sector_1d_move', 0) if price_data else 0:.2f}%
Sentiment: {price_data.get('sentiment', 'neutral') if price_data else 'neutral'}
Top Gainer: {top_gainer_str}
Top Laggard: {top_laggard_str}
"""
        
        user_prompt = user_prompt_template.format(
            sector=self.sector,
            num_companies=len(self.companies),
            num_articles=len(articles),
            date=datetime.now().strftime("%B %d, %Y"),
            price_summary=price_summary,
            catalysts_summary=catalysts_summary
        )
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        try:
            self._log("info", "📡 Sending to LLM for final report generation...")
            response, cost = self.llm(messages)
            self.total_llm_cost += cost
            self._log("info", f"💰 LLM cost for report generation: ${cost:.4f}")
            
            return response
            
        except Exception as e:
            self._log("error", f"Error generating final report: {e}")
            return self._generate_fallback_report(articles, price_data, catalysts)
    
    def _generate_fallback_report(self, articles, price_data, catalysts) -> str:
        """Generate a basic fallback report if LLM fails."""
        report = f"""# {self.sector} Sector - 24H News Intelligence Report

**Date:** {datetime.now().strftime("%B %d, %Y")}
**Companies Monitored:** {len(self.companies)}
**Articles Analyzed:** {len(articles)}

## Price Action Summary

- Sector 1-Day Move: {price_data.get('sector_1d_move', 0):.2f}%
- Sentiment: {price_data.get('sentiment', 'neutral')}
- Top Gainer: {price_data.get('top_gainer', {}).get('ticker', 'N/A')}
- Top Laggard: {price_data.get('top_laggard', {}).get('ticker', 'N/A')}

## Key Catalysts

"""
        for i, cat in enumerate(catalysts[:5], 1):
            report += f"{i}. **{cat.headline}** (Materiality: {cat.materiality_score:.0f}%)\n"
            report += f"   - Sentiment: {cat.sentiment}\n"
            report += f"   - Affected Companies: {', '.join(cat.affected_companies)}\n\n"
        
        report += "\n---\n*Report generation incomplete - using fallback format*\n"
        return report
    
    def _save_report(self, report_content: str) -> Path:
        """Save report to file."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{self.sector_collection}_daily_report_{timestamp}.md"
        report_path = self.output_dir / filename
        
        report_path.write_text(report_content, encoding='utf-8')
        self._log("info", f"📄 Report saved to: {report_path}")
        
        return report_path


