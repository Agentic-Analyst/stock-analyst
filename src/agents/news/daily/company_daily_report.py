#!/usr/bin/env python3
"""
company_daily_report.py - Daily Company News Intelligence Report Generator

Generates professional, concise daily reports analyzing the last 24 hours of news
for a specific company. Designed for institutional investors who need quick,
actionable intelligence each morning.

Features:
- Screens last 24 hours of news from database
- Batch LLM analysis to identify catalysts, risks, and mitigations
- Generates professional analyst-ready report
- Includes peer company context
- Maps news to financial model levers

Usage:
    python src/agents/news/daily/company_daily_report.py --ticker AAPL
    python src/agents/news/daily/company_daily_report.py --ticker NVDA --output reports/
"""

from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass, asdict
import tiktoken
import re

# Add project root to path
# From src/agents/news/daily/ go up 4 levels to get to project root
project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

# Add src directory to path for imports
src_dir = project_root / "src"
sys.path.insert(0, str(src_dir))

from vynn_core.dao.articles import get_last_n_hours_news
from llms.config import get_llm
from logger import StockAnalystLogger
import yfinance as yf


def load_prompt(prompt_name: str) -> str:
    """Load a prompt template from the prompts directory."""
    # Try project root prompts folder first
    prompt_file = project_root / "prompts" / f"{prompt_name}.md"
    if prompt_file.exists():
        return prompt_file.read_text(encoding="utf-8")
    
    # If not found, construct error message with expected path
    raise FileNotFoundError(f"Prompt file not found: {prompt_file}")


@dataclass
class DirectQuote:
    """Represents a direct quote from an article with context."""
    quote: str
    source_article: str
    source_url: str
    context: str


@dataclass  
class ArticleReference:
    """Represents a reference to a source article."""
    title: str
    url: str


@dataclass
class Catalyst:
    """Represents a growth catalyst identified in news."""
    type: str
    description: str
    confidence: float
    supporting_evidence: List[str]
    timeline: str
    potential_impact: str
    reasoning: str
    direct_quotes: List[DirectQuote]
    source_articles: List[ArticleReference]


@dataclass
class Risk:
    """Represents a risk identified in news."""
    type: str
    description: str
    severity: str
    confidence: float
    supporting_evidence: List[str]
    potential_impact: str
    likelihood: str
    reasoning: str
    direct_quotes: List[DirectQuote]
    source_articles: List[ArticleReference]


@dataclass
class Mitigation:
    """Represents risk mitigation strategies."""
    risk_addressed: str
    strategy: str
    confidence: float
    supporting_evidence: List[str]
    effectiveness: str
    company_action: str
    implementation_timeline: str
    reasoning: str
    direct_quotes: List[DirectQuote]
    source_articles: List[ArticleReference]


@dataclass 
class AnalysisSummary:
    """Overall analysis summary."""
    overall_sentiment: str
    key_themes: List[str]
    confidence_score: float
    articles_analyzed: int
    total_catalysts: int
    total_risks: int
    total_mitigations: int


class CompanyDailyReportGenerator:
    """Generate daily news intelligence reports for a company."""
    
    def __init__(self, ticker: str, output_dir: Optional[Path] = None, logger: Optional[StockAnalystLogger] = None):
        """
        Initialize the daily report generator.
        
        Args:
            ticker: Stock ticker symbol
            output_dir: Output directory for reports (default: project_root/reports/daily)
            logger: Optional logger instance to use (if None, creates new one)
        """
        self.ticker = ticker.upper()
        self.output_dir = output_dir or project_root / "reports" / "daily"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Setup logger - use provided logger or create new one
        if logger:
            self.logger = logger
        else:
            log_dir = project_root / "data" / self.ticker
            self.logger = StockAnalystLogger(
                ticker=self.ticker,
                base_path=log_dir
            )
        
        # LLM setup
        self.llm = get_llm()
        self.total_llm_cost = 0.0
        
        # Token management
        self.encoding = tiktoken.encoding_for_model("gpt-4o-mini")
        self.max_tokens_per_request = 15000
        self.prompt_overhead_tokens = 1000
        
        self.logger.info(f"Initialized daily report generator for {self.ticker}")
    
    def _log(self, level: str, message: str):
        """Log message using logger."""
        getattr(self.logger, level)(message)
    
    def _count_tokens(self, text: str) -> int:
        """Count tokens in text."""
        return len(self.encoding.encode(text))
    
    def fetch_last_24h_news(self) -> List[Dict[str, Any]]:
        """Fetch last 24 hours of news for the company from database."""
        self._log("info", f"📰 Fetching last 24 hours of news for {self.ticker}")
        
        try:
            articles = get_last_n_hours_news(collection_name=self.ticker, n_hours_ago=24)
            self._log("info", f"✅ Found {len(articles)} articles from last 24 hours")
            
            if not articles:
                self._log("warning", f"No articles found for {self.ticker} in the last 24 hours")
                return []
            
            # Convert to expected format
            formatted_articles = []
            for article in articles:
                formatted_articles.append({
                    'title': article.get('title', 'Untitled'),
                    'url': article.get('url', ''),
                    'source': article.get('source', 'Unknown'),
                    'publish_date': article.get('publish_date', ''),
                    'text': article.get('text', ''),
                    'summary': article.get('summary', ''),
                })
            
            return formatted_articles
            
        except Exception as e:
            self._log("error", f"Error fetching articles: {e}")
            return []
    
    def _format_articles_for_analysis(self, articles: List[Dict]) -> str:
        """Format articles for LLM analysis."""
        formatted = ""
        
        for i, article in enumerate(articles, 1):
            formatted += f"\n## Article #{i}\n"
            formatted += f"**Title**: {article['title']}\n"
            formatted += f"**Source**: {article['source']}\n"
            formatted += f"**URL**: {article['url']}\n"
            formatted += f"**Published**: {article['publish_date']}\n"
            formatted += f"**Summary**: {article.get('summary', 'N/A')}\n"
            formatted += f"\n**Full Text**:\n{article['text']}\n"
            formatted += "\n" + "="*80 + "\n"
        
        return formatted
    
    def analyze_news_batch(self, articles: List[Dict]) -> Tuple[List[Catalyst], List[Risk], List[Mitigation], AnalysisSummary]:
        """Analyze batch of articles to extract catalysts, risks, and mitigations."""
        self._log("info", f"🔍 Analyzing {len(articles)} articles for catalysts and risks...")
        
        # Format articles
        articles_content = self._format_articles_for_analysis(articles)
        
        # Load prompts
        system_prompt = load_prompt("daily_catalyst_analysis")
        user_prompt = load_prompt("daily_catalyst_user").format(
            company_ticker=self.ticker,
            num_articles=len(articles),
            articles_content=articles_content
        )
        
        # Create messages
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        try:
            # Call LLM
            self._log("info", "📡 Sending batch to LLM for analysis...")
            response, cost = self.llm(messages)
            self.total_llm_cost += cost
            self._log("info", f"💰 LLM cost: ${cost:.4f}")
            
            # Parse JSON response
            analysis_data = self._parse_llm_json_response(response, "catalyst_analysis")
            
            # Convert to dataclasses
            catalysts = self._parse_catalysts(analysis_data.get('catalysts', []))
            risks = self._parse_risks(analysis_data.get('risks', []))
            mitigations = self._parse_mitigations(analysis_data.get('mitigations', []))
            
            # Create summary
            summary = AnalysisSummary(
                overall_sentiment=analysis_data.get('overall_sentiment', 'neutral'),
                key_themes=analysis_data.get('key_themes', []),
                confidence_score=analysis_data.get('confidence_score', 0.5),
                articles_analyzed=len(articles),
                total_catalysts=len(catalysts),
                total_risks=len(risks),
                total_mitigations=len(mitigations)
            )
            
            self._log("info", f"✅ Analysis complete: {len(catalysts)} catalysts, "
                             f"{len(risks)} risks, {len(mitigations)} mitigations")
            
            return catalysts, risks, mitigations, summary
            
        except Exception as e:
            self._log("error", f"Error analyzing news batch: {e}")
            import traceback
            traceback.print_exc()
            return [], [], [], AnalysisSummary(
                overall_sentiment="neutral",
                key_themes=[],
                confidence_score=0.0,
                articles_analyzed=len(articles),
                total_catalysts=0,
                total_risks=0,
                total_mitigations=0
            )
    
    def _parse_llm_json_response(self, response_text: str, response_type: str) -> Dict:
        """Safely parse LLM JSON response."""
        try:
            # Try to find JSON in response
            start_idx = response_text.find('{')
            end_idx = response_text.rfind('}') + 1
            
            if start_idx == -1 or end_idx == 0:
                self._log("warning", f"No JSON found in {response_type} response")
                return {}
            
            json_str = response_text[start_idx:end_idx]
            return json.loads(json_str)
            
        except json.JSONDecodeError as e:
            self._log("error", f"JSON decode error in {response_type}: {e}")
            self._log("error", f"Response text: {response_text[:500]}...")
            return {}
        except Exception as e:
            self._log("error", f"Error parsing {response_type} response: {e}")
            return {}
    
    def _parse_catalysts(self, catalyst_data: List[Dict]) -> List[Catalyst]:
        """Parse catalyst data into Catalyst objects."""
        catalysts = []
        for data in catalyst_data:
            try:
                # Parse quotes
                quotes = []
                for q in data.get('direct_quotes', []):
                    quotes.append(DirectQuote(
                        quote=q.get('quote', ''),
                        source_article=q.get('source_article', ''),
                        source_url=q.get('source_url', ''),
                        context=q.get('context', '')
                    ))
                
                # Parse source articles
                sources = []
                for s in data.get('source_articles', []):
                    sources.append(ArticleReference(
                        title=s.get('title', ''),
                        url=s.get('url', '')
                    ))
                
                catalyst = Catalyst(
                    type=data.get('type', 'unknown'),
                    description=data.get('description', ''),
                    confidence=data.get('confidence', 0.5),
                    supporting_evidence=data.get('supporting_evidence', []),
                    timeline=data.get('timeline', 'medium-term'),
                    potential_impact=data.get('potential_impact', ''),
                    reasoning=data.get('reasoning', ''),
                    direct_quotes=quotes,
                    source_articles=sources
                )
                catalysts.append(catalyst)
            except Exception as e:
                self._log("warning", f"Error parsing catalyst: {e}")
                continue
        
        return catalysts
    
    def _parse_risks(self, risk_data: List[Dict]) -> List[Risk]:
        """Parse risk data into Risk objects."""
        risks = []
        for data in risk_data:
            try:
                quotes = []
                for q in data.get('direct_quotes', []):
                    quotes.append(DirectQuote(
                        quote=q.get('quote', ''),
                        source_article=q.get('source_article', ''),
                        source_url=q.get('source_url', ''),
                        context=q.get('context', '')
                    ))
                
                sources = []
                for s in data.get('source_articles', []):
                    sources.append(ArticleReference(
                        title=s.get('title', ''),
                        url=s.get('url', '')
                    ))
                
                risk = Risk(
                    type=data.get('type', 'unknown'),
                    description=data.get('description', ''),
                    severity=data.get('severity', 'medium'),
                    confidence=data.get('confidence', 0.5),
                    supporting_evidence=data.get('supporting_evidence', []),
                    potential_impact=data.get('potential_impact', ''),
                    likelihood=data.get('likelihood', 'medium'),
                    reasoning=data.get('reasoning', ''),
                    direct_quotes=quotes,
                    source_articles=sources
                )
                risks.append(risk)
            except Exception as e:
                self._log("warning", f"Error parsing risk: {e}")
                continue
        
        return risks
    
    def _parse_mitigations(self, mitigation_data: List[Dict]) -> List[Mitigation]:
        """Parse mitigation data into Mitigation objects."""
        mitigations = []
        for data in mitigation_data:
            try:
                quotes = []
                for q in data.get('direct_quotes', []):
                    quotes.append(DirectQuote(
                        quote=q.get('quote', ''),
                        source_article=q.get('source_article', ''),
                        source_url=q.get('source_url', ''),
                        context=q.get('context', '')
                    ))
                
                sources = []
                for s in data.get('source_articles', []):
                    sources.append(ArticleReference(
                        title=s.get('title', ''),
                        url=s.get('url', '')
                    ))
                
                mitigation = Mitigation(
                    risk_addressed=data.get('risk_addressed', ''),
                    strategy=data.get('strategy', ''),
                    confidence=data.get('confidence', 0.5),
                    supporting_evidence=data.get('supporting_evidence', []),
                    effectiveness=data.get('effectiveness', 'medium'),
                    company_action=data.get('company_action', ''),
                    implementation_timeline=data.get('implementation_timeline', ''),
                    reasoning=data.get('reasoning', ''),
                    direct_quotes=quotes,
                    source_articles=sources
                )
                mitigations.append(mitigation)
            except Exception as e:
                self._log("warning", f"Error parsing mitigation: {e}")
                continue
        
        return mitigations
    
    def identify_peer_companies(self, company_info: Dict) -> List[str]:
        """Use LLM to identify peer companies for comparative analysis."""
        self._log("info", "🔍 Identifying peer companies...")
        
        # Load prompt
        system_prompt = load_prompt("peer_identification")
        
        # Format user prompt
        user_prompt = system_prompt.format(
            ticker=self.ticker,
            company_name=company_info.get('company_name', self.ticker),
            sector=company_info.get('sector', 'Unknown'),
            industry=company_info.get('industry', 'Unknown'),
            market_cap=company_info.get('market_cap', 'Unknown')
        )
        
        messages = [
            {"role": "user", "content": user_prompt}
        ]
        
        try:
            response, cost = self.llm(messages)
            self.total_llm_cost += cost
            
            # Parse JSON response
            peer_data = self._parse_llm_json_response(response, "peer_identification")
            peer_tickers = peer_data.get('peer_tickers', [])
            
            self._log("info", f"✅ Identified {len(peer_tickers)} peer companies: {', '.join(peer_tickers)}")
            return peer_tickers
            
        except Exception as e:
            self._log("error", f"Error identifying peers: {e}")
            return []
    
    def get_peer_news_context(self, peer_tickers: List[str]) -> Dict[str, Any]:
        """Fetch news for peer companies to provide context."""
        self._log("info", f"📰 Fetching news for {len(peer_tickers)} peer companies...")
        
        peer_context = {}
        for peer_ticker in peer_tickers:
            try:
                articles = get_last_n_hours_news(collection_name=peer_ticker, n_hours_ago=24)
                
                # Fetch peer price data if available
                price_move = None
                try:
                    peer_stock = yf.Ticker(peer_ticker)
                    peer_hist = peer_stock.history(period="5d")
                    if len(peer_hist) >= 2:
                        price_move = ((peer_hist['Close'].iloc[-1] / peer_hist['Close'].iloc[-2]) - 1) * 100
                except Exception:
                    pass  # Skip price data if unavailable
                
                peer_context[peer_ticker] = {
                    'article_count': len(articles),
                    'headlines': [a.get('title', '') for a in articles[:3]],  # Top 3 headlines
                    'price_move': price_move
                }
                self._log("info", f"  {peer_ticker}: {len(articles)} articles" + 
                         (f", {price_move:+.1f}%" if price_move is not None else ""))
            except Exception as e:
                self._log("warning", f"  {peer_ticker}: Error fetching news - {e}")
                peer_context[peer_ticker] = {
                    'article_count': 0,
                    'headlines': [],
                    'price_move': None
                }
        
        return peer_context
    
    def fetch_price_action_data(self, sector: str) -> str:
        """Fetch stock price movement vs sector benchmark for last 24 hours.
        
        Automatically determines the appropriate sector ETF based on the provided sector.
        
        Args:
            sector: Sector name from yfinance (e.g., 'Technology', 'Financial Services')
        
        Returns:
            Formatted markdown table with price action data
        """
        try:
            # Map yfinance sector names to Select Sector SPDR ETFs
            sector_etf_map = {
                'Technology': 'XLK',
                'Financial Services': 'XLF',
                'Financials': 'XLF',  # Alternative name
                'Energy': 'XLE',
                'Healthcare': 'XLV',
                'Industrials': 'XLI',
                'Consumer Cyclical': 'XLY',
                'Consumer Defensive': 'XLP',
                'Basic Materials': 'XLB',
                'Materials': 'XLB',  # Alternative name
                'Utilities': 'XLU',
                'Real Estate': 'XLRE',
                'Communication Services': 'XLC'
            }
            
            # Get sector ETF or default to SPY (S&P 500)
            sector_etf = sector_etf_map.get(sector, 'SPY')
            
            self._log("info", f"📊 Fetching price action for {self.ticker} ({sector}) vs {sector_etf}...")
            
            # Fetch data for stock and sector
            stock = yf.Ticker(self.ticker)
            sector_ticker = yf.Ticker(sector_etf)
            
            # Get last 5 days of data to ensure we have 24h comparison
            stock_hist = stock.history(period="5d")
            sector_hist = sector_ticker.history(period="5d")
            
            if len(stock_hist) < 2 or len(sector_hist) < 2:
                self._log("warning", "Insufficient price data available")
                return "**Price data unavailable** (insufficient trading data)"
            
            # Calculate 1-day return (most recent close vs previous close)
            stock_return = ((stock_hist['Close'].iloc[-1] / stock_hist['Close'].iloc[-2]) - 1) * 100
            sector_return = ((sector_hist['Close'].iloc[-1] / sector_hist['Close'].iloc[-2]) - 1) * 100
            relative_return = stock_return - sector_return
            
            # Get current price
            current_price = stock_hist['Close'].iloc[-1]
            
            # Format the data
            price_data = f"""| Metric | Value | Δ vs Sector ({sector_etf}) |
| ------ | ----- | ----------- |
| {self.ticker} 1-Day Move | {stock_return:+.2f}% | {relative_return:+.2f}% |
| Current Price | ${current_price:.2f} | - |
| Sector Move | {sector_return:+.2f}% | - |
| Relative Performance | {'Outperforming' if relative_return > 0 else 'Underperforming'} | {abs(relative_return):.2f}% {'ahead' if relative_return > 0 else 'behind'} |"""
            
            self._log("info", f"✅ Price action: {self.ticker} {stock_return:+.2f}% vs {sector_etf} {sector_return:+.2f}%")
            return price_data
            
        except Exception as e:
            self._log("error", f"Error fetching price data: {e}")
            return f"**Price data unavailable** (error: {str(e)})"
    
    def generate_report(
        self,
        catalysts: List[Catalyst],
        risks: List[Risk],
        mitigations: List[Mitigation],
        summary: AnalysisSummary,
        articles: List[Dict],
        company_info: Dict,
        peer_context: Dict,
        price_action_data: str
    ) -> str:
        """Generate the final daily report using LLM."""
        self._log("info", "📝 Generating final daily report...")
        
        # Prepare data summaries
        catalysts_summary = self._format_catalysts_summary(catalysts)
        risks_summary = self._format_risks_summary(risks)
        mitigations_summary = self._format_mitigations_summary(mitigations)
        articles_list = self._format_articles_list(articles)
        peer_tickers = list(peer_context.keys())
        peer_context_str = self._format_peer_context(peer_context)
        
        # Load prompts
        system_prompt = load_prompt("daily_report_generation")
        user_prompt = load_prompt("daily_report_user").format(
            company_name=company_info.get('company_name', self.ticker),
            ticker=self.ticker,
            sector=company_info.get('sector', 'Unknown'),
            report_date=datetime.now().strftime("%Y-%m-%d"),
            price_action_data=price_action_data,
            num_catalysts=len(catalysts),
            catalysts_summary=catalysts_summary,
            num_risks=len(risks),
            risks_summary=risks_summary,
            num_mitigations=len(mitigations),
            mitigations_summary=mitigations_summary,
            sentiment=summary.overall_sentiment,
            themes=', '.join(summary.key_themes),
            confidence=f"{summary.confidence_score:.1%}",
            num_articles=len(articles),
            articles_list=articles_list,
            peer_tickers=', '.join(peer_tickers) if peer_tickers else 'N/A',
            peer_context=peer_context_str
        )
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        try:
            response, cost = self.llm(messages)
            self.total_llm_cost += cost
            self._log("info", f"💰 Report generation cost: ${cost:.4f}")
            
            return response
            
        except Exception as e:
            self._log("error", f"Error generating report: {e}")
            return "Error generating report"
    
    def _format_catalysts_summary(self, catalysts: List[Catalyst]) -> str:
        """Format catalysts for report generation."""
        if not catalysts:
            return "None identified"
        
        summary = ""
        for i, catalyst in enumerate(catalysts, 1):
            summary += f"\n{i}. **{catalyst.type.upper()}**: {catalyst.description}\n"
            summary += f"   - Timeline: {catalyst.timeline}\n"
            summary += f"   - Impact: {catalyst.potential_impact}\n"
            summary += f"   - Confidence: {catalyst.confidence:.0%}\n"
        
        return summary
    
    def _format_risks_summary(self, risks: List[Risk]) -> str:
        """Format risks for report generation."""
        if not risks:
            return "None identified"
        
        summary = ""
        for i, risk in enumerate(risks, 1):
            summary += f"\n{i}. **{risk.type.upper()}**: {risk.description}\n"
            summary += f"   - Severity: {risk.severity}\n"
            summary += f"   - Impact: {risk.potential_impact}\n"
            summary += f"   - Confidence: {risk.confidence:.0%}\n"
        
        return summary
    
    def _format_mitigations_summary(self, mitigations: List[Mitigation]) -> str:
        """Format mitigations for report generation."""
        if not mitigations:
            return "None identified"
        
        summary = ""
        for i, mitigation in enumerate(mitigations, 1):
            summary += f"\n{i}. **Risk**: {mitigation.risk_addressed}\n"
            summary += f"   - Strategy: {mitigation.strategy}\n"
            summary += f"   - Effectiveness: {mitigation.effectiveness}\n"
        
        return summary
    
    def _format_articles_list(self, articles: List[Dict]) -> str:
        """Format article list for report."""
        if not articles:
            return "No articles"
        
        articles_str = ""
        for i, article in enumerate(articles, 1):
            articles_str += f"\n{i}. [{article['title']}]({article['url']}) - {article['source']}\n"
        
        return articles_str
    
    def _format_peer_context(self, peer_context: Dict) -> str:
        """Format peer company context."""
        if not peer_context:
            return "No peer data available"
        
        context_str = ""
        for ticker, data in peer_context.items():
            price_move_str = ""
            if data.get('price_move') is not None:
                price_move_str = f" ({data['price_move']:+.1f}%)"
            
            context_str += f"\n**{ticker}**: {data['article_count']} articles in last 24h{price_move_str}\n"
            if data['headlines']:
                context_str += "  Headlines:\n"
                for headline in data['headlines']:
                    context_str += f"  - {headline}\n"
        
        return context_str
    
    def save_report(self, report_text: str, filename: Optional[str] = None):
        """Save report to file."""
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d")
            filename = f"{self.ticker}_daily_report_{timestamp}.md"
        
        output_path = self.output_dir / filename
        
        try:
            output_path.write_text(report_text, encoding='utf-8')
            self._log("info", f"✅ Report saved to: {output_path}")
            print(f"\n📄 Report saved to: {output_path}")
        except Exception as e:
            self._log("error", f"Error saving report: {e}")
    
    def _validate_report_consistency(self, report_text: str, articles: List[Dict]) -> List[str]:
        """Validate report for common hallucination issues.
        
        Returns list of warnings if potential issues detected.
        """
        warnings = []
        
        # Check for mixed Q1/Q2/Q3/Q4 references that might indicate confusion
        # BUT: Allow mentions of consecutive quarters (e.g., Q1 results + Q2 guidance is normal)
        quarters = re.findall(r'Q[1-4]', report_text)
        unique_quarters = set(quarters)
        
        # Only warn if there are 3+ different quarters mentioned (likely mixing up data)
        if len(unique_quarters) >= 3:
            warnings.append(
                f"WARNING: Multiple fiscal quarters mentioned: {unique_quarters}. "
                "Verify these are from the same news story and not mixed up."
            )
        
        # Check for very large revenue numbers that seem unrealistic
        # Match patterns like $100B or $800M with context
        revenue_patterns = re.findall(r'\$(\d+(?:\.\d+)?)\s*([BM])', report_text)
        
        for value_str, unit in revenue_patterns:
            value = float(value_str)
            
            # Check for unrealistic quarterly revenue (>$200B for any single company)
            # or insider sales >$5B (very unusual)
            if unit == 'B':
                if value > 200:
                    # Check if this is in context of insider selling or market cap
                    pattern = re.escape(f"${value_str}{unit}")
                    matches = list(re.finditer(pattern, report_text))
                    
                    is_insider_sale = False
                    is_market_cap = False
                    
                    for match in matches:
                        start = max(0, match.start() - 100)
                        end = min(len(report_text), match.end() + 100)
                        context = report_text[start:end].lower()
                        
                        if any(term in context for term in ['sell', 'sale', 'sold', 'insider', 'stock sale']):
                            is_insider_sale = True
                        if any(term in context for term in ['market cap', 'valuation', 'market value']):
                            is_market_cap = True
                    
                    # Only warn if it's not clearly an insider sale or market cap
                    if not is_insider_sale and not is_market_cap:
                        warnings.append(
                            f"WARNING: Very large revenue figure detected: ${value_str}{unit}. "
                            "Verify this is accurate and not a hallucination."
                        )
        
        # Check for speculative language without attribution
        # This helps catch LLM hallucinations where it makes claims without source data
        speculative_phrases = [
            "concerns over potential",
            "fears of",
            "analysts expect",
            "market expects"
        ]
        
        for phrase in speculative_phrases:
            if phrase.lower() in report_text.lower():
                # Check if it has a source nearby (within 150 chars)
                idx = report_text.lower().find(phrase.lower())
                context = report_text[max(0, idx-75):idx+150]
                
                # Look for attribution signals
                has_source = any(source in context.lower() for source in [
                    'analyst', 'report', 'according to', 'cited', 'source',
                    'morgan stanley', 'goldman sachs', 'jp morgan', 'bank of america',
                    'article', 'reuters', 'bloomberg', 'cnbc', 'mentioned'
                ])
                
                if not has_source:
                    warnings.append(
                        f"WARNING: Speculative language without clear source: '{phrase}'. "
                        "Ensure this is backed by actual analyst reports or news sources."
                    )
        
        return warnings
    
    def generate_daily_report(self, company_info: Optional[Dict] = None) -> str:
        """Main method to generate complete daily report."""
        self._log("info", f"🚀 Starting daily report generation for {self.ticker}")
        
        # Default company info
        if not company_info:
            company_info = {
                'company_name': self.ticker,
                'sector': 'Unknown',
                'industry': 'Unknown',
                'market_cap': 'Unknown'
            }
        
        # Step 1: Fetch news
        articles = self.fetch_last_24h_news()
        if not articles:
            self._log("warning", "No articles found - cannot generate report")
            return "No news articles found for the last 24 hours."
        
        # Step 2: Fetch price action data using sector from company_info
        sector = company_info.get('sector', 'Unknown')
        price_action_data = self.fetch_price_action_data(sector)
        
        # Step 3: Analyze news
        catalysts, risks, mitigations, summary = self.analyze_news_batch(articles)
        
        # Step 4: Identify peers
        peer_tickers = self.identify_peer_companies(company_info)
        
        # Step 5: Get peer context
        peer_context = self.get_peer_news_context(peer_tickers) if peer_tickers else {}
        
        # Step 6: Generate report
        report = self.generate_report(
            catalysts=catalysts,
            risks=risks,
            mitigations=mitigations,
            summary=summary,
            articles=articles,
            company_info=company_info,
            peer_context=peer_context,
            price_action_data=price_action_data
        )
        
        # Step 7: Save report
        self.save_report(report)
        
        # Step 8: Validate report for potential issues
        warnings = self._validate_report_consistency(report, articles)
        if warnings:
            self._log("warning", "⚠️ Report validation warnings:")
            for warning in warnings:
                self._log("warning", f"  {warning}")
                print(f"\n{warning}")
        
        self._log("info", f"✅ Daily report generation complete. Total cost: ${self.total_llm_cost:.4f}")
        
        return report

