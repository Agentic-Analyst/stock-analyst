#!/usr/bin/env python3
"""
screener.py - Batch LLM-powered stock screening and analysis of filtered articles.

This module uses batch processing to analyze multiple articles simultaneously with LLM,
providing efficient analysis of investment insights including growth catalysts, risks, 
and mitigation strategies.

▶ Usage:
    python src/screener.py --ticker NVDA --output-report
    python src/screener.py --ticker NVDA --min-confidence 0.7 --detailed-analysis
"""

from __future__ import annotations
import os, csv, argparse, pathlib, re, json
from datetime import datetime
from typing import Dict, List, Tuple, Set, Optional
from dataclasses import dataclass, asdict
from collections import defaultdict, Counter
import yaml
import tiktoken
from llms.config import get_llm
from vynn_core import find_recent, get_article_by_url

PROMPTS_ROOT = pathlib.Path("prompts")

def load_prompt(prompt_name: str) -> str:
    """Load a prompt template from the prompts directory."""
    prompt_file = PROMPTS_ROOT / f"{prompt_name}.md"
    if not prompt_file.exists():
        raise FileNotFoundError(f"Prompt file not found: {prompt_file}")
    return prompt_file.read_text(encoding="utf-8")

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
    """Represents a growth catalyst identified in articles."""
    type: str  # 'product', 'market', 'partnership', 'technology', 'financial'
    description: str
    confidence: float  # 0.0 to 1.0
    supporting_evidence: List[str]
    timeline: str  # 'immediate', 'short-term', 'medium-term', 'long-term'
    llm_reasoning: Optional[str] = None  # AI reasoning for this catalyst
    llm_confidence: Optional[float] = None  # LLM-provided confidence score
    reasoning: Optional[str] = None  # Detailed explanation from LLM
    direct_quotes: List[DirectQuote] = None  # Direct quotes supporting this catalyst
    source_articles: List[ArticleReference] = None  # Source articles for this catalyst
    potential_impact: Optional[str] = None  # Expected impact description
    
    def __post_init__(self):
        if self.direct_quotes is None:
            self.direct_quotes = []
        if self.source_articles is None:
            self.source_articles = []

@dataclass
class Risk:
    """Represents a risk identified in articles."""
    type: str  # 'market', 'competitive', 'regulatory', 'technological', 'financial'
    description: str
    severity: str  # 'low', 'medium', 'high', 'critical'
    confidence: float  # 0.0 to 1.0
    supporting_evidence: List[str]
    potential_impact: str
    llm_reasoning: Optional[str] = None  # AI reasoning for this risk
    llm_confidence: Optional[float] = None  # LLM-provided confidence score
    reasoning: Optional[str] = None  # Detailed explanation from LLM
    direct_quotes: List[DirectQuote] = None  # Direct quotes supporting this risk
    source_articles: List[ArticleReference] = None  # Source articles for this risk
    likelihood: Optional[str] = None  # Likelihood assessment: low|medium|high
    
    def __post_init__(self):
        if self.direct_quotes is None:
            self.direct_quotes = []
        if self.source_articles is None:
            self.source_articles = []

@dataclass
class Mitigation:
    """Represents risk mitigation strategies."""
    risk_addressed: str
    strategy: str
    confidence: float
    supporting_evidence: List[str]
    effectiveness: str  # 'low', 'medium', 'high'
    company_action: Optional[str] = None  # What the company is doing/planning
    llm_reasoning: Optional[str] = None  # AI reasoning for this mitigation
    llm_confidence: Optional[float] = None  # LLM-provided confidence score
    reasoning: Optional[str] = None  # Detailed explanation from LLM
    direct_quotes: List[DirectQuote] = None  # Direct quotes supporting this mitigation
    source_articles: List[ArticleReference] = None  # Source articles for this mitigation
    implementation_timeline: Optional[str] = None  # When mitigation is expected
    
    def __post_init__(self):
        if self.direct_quotes is None:
            self.direct_quotes = []
        if self.source_articles is None:
            self.source_articles = []

@dataclass 
class AnalysisSummary:
    """Represents overall analysis summary from unified analysis."""
    overall_sentiment: str  # 'bullish', 'neutral', 'bearish'
    key_themes: List[str]
    confidence_score: float  # 0.0 to 1.0
    articles_analyzed: int = 0
    total_catalysts: int = 0
    total_risks: int = 0
    total_mitigations: int = 0

class ArticleScreener:
    def __init__(self, ticker: str, base_path: pathlib.Path):
        self.ticker = ticker.upper()
        self.company_dir = base_path
        
        # Logger - will be set by pipeline if available
        self.logger = None
        
        # Cost tracking for LLM usage
        self.total_llm_cost = 0.0
        self.llm_call_count = 0
        
        # Token management for handling long articles
        self.encoding = tiktoken.encoding_for_model("gpt-4o-mini")
        self.max_tokens_per_request = 15000  # Conservative limit for GPT-4o-mini (16k context)
        self.prompt_overhead_tokens = 1000  # Reserve for system prompts and response
    
    def set_logger(self, logger):
        """Set the logger instance."""
        self.logger = logger
    
    def _log(self, level: str, message: str):
        """Log message using logger if available, otherwise print."""
        if self.logger:
            getattr(self.logger, level)(message)
        else:
            print(f"[{level.upper()}] {message}")

    # ============= TOKEN MANAGEMENT METHODS =============
    def _count_tokens(self, text: str) -> int:
        """Count tokens in a text string."""
        return len(self.encoding.encode(text))

    # ============= BATCH PROCESSING METHODS =============
    
    def _create_batch_analysis_prompt(self, batch_content: str, company_ticker: str, batch_size: int) -> List[Dict]:
        """Create batch prompt for comprehensive analysis of multiple articles."""
        system_prompt = load_prompt("batch_analysis")
        user_prompt = load_prompt("batch_user").format(
            company_ticker=company_ticker,
            batch_content=batch_content,
            batch_size=batch_size
        )
        
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
    
    def _format_articles_for_batch(self, articles: List[Dict]) -> str:
        """Format a batch of articles for LLM analysis."""
        batch_content = ""
        
        for i, article in enumerate(articles, 1):
            batch_content += f"### ARTICLE {i}: {article['file_name']}\n"
            batch_content += f"**Title:** {article['title']}\n"
            batch_content += f"**Source:** {article.get('source_url', 'N/A')}\n"
            batch_content += f"**Date:** {article.get('publish_date', 'N/A')}\n\n"
            batch_content += f"**Content:**\n{article['text']}\n\n"
            batch_content += "---\n\n"
        
        return batch_content
    
    def _analyze_article_batch(self, articles: List[Dict], batch_num: int, depth: int = 0) -> Tuple[List[Catalyst], List[Risk], List[Mitigation]]:
        """
        Analyze a batch of articles using LLM for comprehensive insights.
        Automatically splits batch if rate limit error occurs.
        
        Strategy: Try the request first regardless of size. Only split if it fails due to rate limits.
        
        Args:
            articles: List of articles to analyze
            batch_num: Batch number for logging
            depth: Recursion depth (for sub-batch tracking)
        """
        batch_size = len(articles)
        indent = "  " * depth  # Indent for sub-batch logging
        self._log("info", f"{indent}🔍 Analyzing batch {batch_num} with {batch_size} article(s)...")
        
        # Format articles for batch analysis
        batch_content = self._format_articles_for_batch(articles)
        
        # Log token count for monitoring (but don't block based on it)
        total_tokens = self._count_tokens(batch_content)
        self._log("info", f"{indent}📊 Batch {batch_num} size: {total_tokens:,} tokens")
        
        catalysts = []
        risks = []
        mitigations = []
        
        try:
            # Create batch analysis prompt
            batch_prompt = self._create_batch_analysis_prompt(batch_content, self.ticker, batch_size)
            
            # Make LLM call - try regardless of token count
            self._log("info", f"{indent}🤖 Processing batch {batch_num} - extracting insights across {batch_size} article(s)...")
            response, cost = get_llm()(batch_prompt)
            self.total_llm_cost += cost
            self.llm_call_count += 1
            
            # Parse response
            analysis_data = self._parse_llm_json_response(response, "batch_analysis")
            
            # Extract catalysts with enhanced information
            for cat_data in analysis_data.get("catalysts", []):
                # Parse direct quotes
                direct_quotes = []
                for quote_data in cat_data.get("direct_quotes", []):
                    direct_quotes.append(DirectQuote(
                        quote=quote_data.get("quote", ""),
                        source_article=quote_data.get("source_article", ""),
                        source_url=quote_data.get("source_url", ""),
                        context=quote_data.get("context", "")
                    ))
                
                # Parse source articles
                source_articles = []
                for source_data in cat_data.get("source_articles", []):
                    if isinstance(source_data, dict):
                        source_articles.append(ArticleReference(
                            title=source_data.get("title", ""),
                            url=source_data.get("url", "")
                        ))
                    else:
                        # Handle legacy string format
                        source_articles.append(ArticleReference(title=str(source_data), url=""))
                
                catalyst = Catalyst(
                    type=cat_data.get("type", "unknown").lower(),
                    description=cat_data.get("description", ""),
                    confidence=cat_data.get("confidence", 0.5),
                    supporting_evidence=cat_data.get("supporting_evidence", []),
                    timeline=cat_data.get("timeline", "medium-term").lower().replace("_", "-"),
                    llm_reasoning=cat_data.get("reasoning", ""),
                    llm_confidence=cat_data.get("confidence", 0.5),
                    reasoning=cat_data.get("reasoning", ""),
                    direct_quotes=direct_quotes,
                    source_articles=source_articles,
                    potential_impact=cat_data.get("potential_impact", "")
                )
                catalysts.append(catalyst)

            # Extract risks with enhanced information
            for risk_data in analysis_data.get("risks", []):
                # Parse direct quotes
                direct_quotes = []
                for quote_data in risk_data.get("direct_quotes", []):
                    direct_quotes.append(DirectQuote(
                        quote=quote_data.get("quote", ""),
                        source_article=quote_data.get("source_article", ""),
                        source_url=quote_data.get("source_url", ""),
                        context=quote_data.get("context", "")
                    ))
                
                # Parse source articles
                source_articles = []
                for source_data in risk_data.get("source_articles", []):
                    if isinstance(source_data, dict):
                        source_articles.append(ArticleReference(
                            title=source_data.get("title", ""),
                            url=source_data.get("url", "")
                        ))
                    else:
                        # Handle legacy string format
                        source_articles.append(ArticleReference(title=str(source_data), url=""))
                
                risk = Risk(
                    type=risk_data.get("type", "unknown").lower(),
                    description=risk_data.get("description", ""),
                    severity=risk_data.get("severity", "medium").lower(),
                    confidence=risk_data.get("confidence", 0.5),
                    supporting_evidence=risk_data.get("supporting_evidence", []),
                    potential_impact=risk_data.get("potential_impact", ""),
                    llm_reasoning=risk_data.get("reasoning", ""),
                    llm_confidence=risk_data.get("confidence", 0.5),
                    reasoning=risk_data.get("reasoning", ""),
                    direct_quotes=direct_quotes,
                    source_articles=source_articles,
                    likelihood=risk_data.get("likelihood", "medium")
                )
                risks.append(risk)
            
            # Extract mitigations with enhanced information
            for mit_data in analysis_data.get("mitigations", []):
                # Parse direct quotes
                direct_quotes = []
                for quote_data in mit_data.get("direct_quotes", []):
                    direct_quotes.append(DirectQuote(
                        quote=quote_data.get("quote", ""),
                        source_article=quote_data.get("source_article", ""),
                        source_url=quote_data.get("source_url", ""),
                        context=quote_data.get("context", "")
                    ))
                
                # Parse source articles
                source_articles = []
                for source_data in mit_data.get("source_articles", []):
                    if isinstance(source_data, dict):
                        source_articles.append(ArticleReference(
                            title=source_data.get("title", ""),
                            url=source_data.get("url", "")
                        ))
                    else:
                        # Handle legacy string format
                        source_articles.append(ArticleReference(title=str(source_data), url=""))
                
                mitigation = Mitigation(
                    risk_addressed=mit_data.get("risk_addressed", ""),
                    strategy=mit_data.get("strategy", ""),
                    confidence=mit_data.get("confidence", 0.5),
                    supporting_evidence=mit_data.get("supporting_evidence", []),
                    effectiveness=mit_data.get("effectiveness", "medium").lower(),
                    company_action=mit_data.get("company_action", ""),
                    llm_reasoning=mit_data.get("reasoning", ""),
                    llm_confidence=mit_data.get("confidence", 0.5),
                    reasoning=mit_data.get("reasoning", ""),
                    direct_quotes=direct_quotes,
                    source_articles=source_articles,
                    implementation_timeline=mit_data.get("implementation_timeline", "")
                )
                mitigations.append(mitigation)

            # Display batch results
            self._log("info", f"✅ Batch {batch_num} complete: {len(catalysts)}🚀 {len(risks)}⚠️ {len(mitigations)}🛡️")
            self._log("info", f"💰 Batch cost: ${cost:.4f} USD | Running total: ${self.total_llm_cost:.4f} USD")
            
            # Show top insight from batch
            if catalysts:
                top_catalyst = max(catalysts, key=lambda x: x.confidence)
                self._log("info", f"   🚀 Top Catalyst: {top_catalyst.type.title()} ({top_catalyst.confidence:.1%}) - {top_catalyst.description[:60]}...")
            
            if risks:
                top_risk = max(risks, key=lambda x: x.confidence)
                self._log("info", f"   ⚠️  Top Risk: {top_risk.type.title()} [{top_risk.severity.upper()}] ({top_risk.confidence:.1%}) - {top_risk.description[:60]}...")

        except Exception as e:
            error_message = str(e).lower()
            
            # Check if error is due to rate limiting or token limits
            is_rate_limit_error = any(keyword in error_message for keyword in [
                'rate limit',
                'rate_limit',
                'ratelimit',
                'too many tokens',
                'context length',
                'maximum context',
                'token limit',
                'tokens exceeded',
                'timeout',
                '413',  # Payload Too Large
                '429',  # Too Many Requests
            ])
            
            if is_rate_limit_error:
                self._log("warning", f"{indent}⚠️  Batch {batch_num} failed due to rate limit/token limit: {e}")
                
                # Intelligently split and retry
                if batch_size == 1:
                    # Check if article was already truncated to prevent infinite loop
                    if articles[0].get('already_truncated', False):
                        self._log("error", f"{indent}❌ Article was already truncated but still failed - giving up")
                        return [], [], []
                    
                    # Single article is too large - truncate it
                    self._log("warning", f"{indent}📄 Single article too large, truncating content...")
                    return self._analyze_truncated_article(articles[0], batch_num, depth)
                
                # Split batch in half and process recursively
                mid_point = batch_size // 2
                self._log("info", f"{indent}✂️  Splitting batch {batch_num} into 2 sub-batches: [{mid_point}] + [{batch_size - mid_point}] articles")
                
                # Process first half
                catalysts_1, risks_1, mitigations_1 = self._analyze_article_batch(
                    articles[:mid_point], 
                    f"{batch_num}a", 
                    depth + 1
                )
                
                # Process second half
                catalysts_2, risks_2, mitigations_2 = self._analyze_article_batch(
                    articles[mid_point:], 
                    f"{batch_num}b", 
                    depth + 1
                )
                
                # Combine results
                all_catalysts = catalysts_1 + catalysts_2
                all_risks = risks_1 + risks_2
                all_mitigations = mitigations_1 + mitigations_2
                
                self._log("info", f"{indent}✅ Batch {batch_num} complete (split after rate limit): {len(all_catalysts)}🚀 {len(all_risks)}⚠️ {len(all_mitigations)}🛡️")
                return all_catalysts, all_risks, all_mitigations
            else:
                # Non-rate-limit error - log and return empty results
                self._log("error", f"{indent}❌ Batch {batch_num} analysis failed with non-rate-limit error: {e}")
                return [], [], []

        return catalysts, risks, mitigations
    
    def _analyze_truncated_article(self, article: Dict, batch_num: int, depth: int = 0) -> Tuple[List[Catalyst], List[Risk], List[Mitigation]]:
        """
        Analyze a single article that's too large by truncating its content to fit token limits.
        
        Args:
            article: Article to analyze
            batch_num: Batch number for logging
            depth: Recursion depth for logging
        """
        indent = "  " * depth
        self._log("info", f"{indent}📝 Truncating article to fit token limit...")
        
        # Calculate available tokens for article content
        # Reserve tokens for: prompt overhead + article metadata + response
        available_tokens = self.max_tokens_per_request - self.prompt_overhead_tokens - 500  # 500 for metadata
        
        # Truncate article text to fit
        article_text = article['text']
        text_tokens = self.encoding.encode(article_text)
        
        if len(text_tokens) > available_tokens:
            # Truncate to available tokens
            truncated_tokens = text_tokens[:available_tokens]
            truncated_text = self.encoding.decode(truncated_tokens)
            
            original_words = len(article_text.split())
            truncated_words = len(truncated_text.split())
            
            self._log("warning", f"{indent}✂️  Truncated article from {original_words:,} to {truncated_words:,} words (~{len(text_tokens):,} → {available_tokens:,} tokens)")
            
            # Create truncated copy with flag to prevent re-truncation
            truncated_article = article.copy()
            truncated_article['text'] = truncated_text
            truncated_article['truncated'] = True
            truncated_article['original_word_count'] = original_words
            truncated_article['already_truncated'] = True  # Prevent infinite truncation loops
            
            # Analyze the truncated article - if this fails, we give up
            try:
                return self._analyze_article_batch([truncated_article], batch_num, depth)
            except Exception as e:
                self._log("error", f"{indent}❌ Truncated article still failed: {e}")
                self._log("error", f"{indent}⚠️  Giving up on this article to prevent infinite loop")
                return [], [], []
        else:
            # Article fits after all - shouldn't happen but handle gracefully
            return self._analyze_article_batch([article], batch_num, depth)

    # ============= END BATCH PROCESSING METHODS =============

    # ============= LLM-POWERED ANALYSIS METHODS =============
    
    def _display_intermediate_analysis_results(self, analysis_data: Dict, article_name: str):
        """Display user-friendly intermediate analysis results for real-time feedback."""
        try:
            # Get analysis summary if available
            summary = analysis_data.get("analysis_summary", {})
            sentiment = summary.get("overall_sentiment", "unknown")
            themes = summary.get("key_themes", [])
            
            # Count insights
            catalysts = analysis_data.get("catalysts", [])
            risks = analysis_data.get("risks", [])
            mitigations = analysis_data.get("mitigations", [])
            
            # Display article summary
            self._log("info", f"📄 [{article_name[:40]}...] Analysis Complete:")
            self._log("info", f"   📊 Sentiment: {sentiment.title()} | Insights: 🚀{len(catalysts)} catalyst ⚠️{len(risks)} risk 🛡️{len(mitigations)} mitigation")
            
            # Show key themes if available
            if themes:
                themes_str = ", ".join(themes[:5])  # Show top 5 themes
                self._log("info", f"   🎯 Key Themes: {themes_str}")
            
            # Show top catalyst if found
            if catalysts:
                top_catalyst = max(catalysts, key=lambda x: x.get("confidence", 0))
                catalyst_desc = top_catalyst.get("description", "")
                catalyst_conf = top_catalyst.get("confidence", 0)
                catalyst_type = top_catalyst.get("type", "unknown").title()
                self._log("info", f"   🚀 Top Catalyst: {catalyst_type} ({catalyst_conf:.1%}) - {catalyst_desc}...")
            
            # Show top risk if found
            if risks:
                top_risk = max(risks, key=lambda x: x.get("confidence", 0))
                risk_desc = top_risk.get("description", "")
                risk_conf = top_risk.get("confidence", 0)
                risk_severity = top_risk.get("severity", "unknown").upper()
                risk_type = top_risk.get("type", "unknown").title()
                self._log("info", f"   ⚠️  Top Risk: {risk_type} [{risk_severity}] ({risk_conf:.1%}) - {risk_desc}...")
            
            # Show top mitigation if found
            if mitigations:
                top_mitigation = mitigations[0]  # First mitigation
                mit_strategy = top_mitigation.get("strategy", "")
                mit_effectiveness = top_mitigation.get("effectiveness", "unknown").title()
                self._log("info", f"   🛡️  Mitigation: [{mit_effectiveness}] {mit_strategy}...")
            
            self._log("info", f"   ─────────────────────────────────────────────────")
            
        except Exception as e:
            self._log("warning", f"Could not display intermediate results for {article_name}: {e}")

    def _parse_llm_json_response(self, response_text: str, response_type: str) -> Dict:
        """Safely parse LLM JSON response with error handling."""
        try:
            # Clean the response text
            response_text = response_text.strip()
            
            # Extract JSON if wrapped in markdown code blocks
            if "```json" in response_text:
                start = response_text.find("```json") + 7
                end = response_text.find("```", start)
                response_text = response_text[start:end].strip()
            elif "```" in response_text:
                start = response_text.find("```") + 3
                end = response_text.find("```", start)
                response_text = response_text[start:end].strip()
            
            # Parse JSON
            parsed = json.loads(response_text)
            
            # For batch analysis, unified analysis, or deduplication, ensure all required keys exist
            if response_type == "batch_analysis":
                if "catalysts" not in parsed:
                    parsed["catalysts"] = []
                if "risks" not in parsed:
                    parsed["risks"] = []
                if "mitigations" not in parsed:
                    parsed["mitigations"] = []
                if "analysis_summary" not in parsed:
                    parsed["analysis_summary"] = {
                        "overall_sentiment": "neutral",
                        "key_themes": [],
                        "confidence_score": 0.5
                    }
            elif response_type == "deduplication_analysis":
                if "catalysts" not in parsed:
                    parsed["catalysts"] = []
                if "risks" not in parsed:
                    parsed["risks"] = []
                if "mitigations" not in parsed:
                    parsed["mitigations"] = []
                if "deduplication_summary" not in parsed:
                    parsed["deduplication_summary"] = {
                        "original_catalysts": 0,
                        "final_catalysts": 0,
                        "original_risks": 0,
                        "final_risks": 0,
                        "original_mitigations": 0,
                        "final_mitigations": 0,
                        "merge_operations": 0
                    }
            
            return parsed
            
        except json.JSONDecodeError as e:
            self._log("warning", f"Failed to parse LLM {response_type} response as JSON: {e}")
            self._log("warning", f"Raw response: {response_text[:200]}...")
            
            # Return appropriate empty structure based on response type
            if response_type == "batch_analysis":
                return {
                    "analysis_summary": {"overall_sentiment": "neutral", "key_themes": [], "confidence_score": 0.5},
                    "catalysts": [],
                    "risks": [],
                    "mitigations": []
                }
            elif response_type == "deduplication_analysis":
                return {
                    "deduplication_summary": {
                        "original_catalysts": 0, "final_catalysts": 0,
                        "original_risks": 0, "final_risks": 0,
                        "original_mitigations": 0, "final_mitigations": 0,
                        "merge_operations": 0
                    },
                    "catalysts": [],
                    "risks": [],
                    "mitigations": []
                }
            else:
                return {response_type: []}
                
        except Exception as e:
            self._log("warning", f"Error processing LLM {response_type} response: {e}")
            
            # Return appropriate empty structure based on response type
            if response_type == "batch_analysis":
                return {
                    "analysis_summary": {"overall_sentiment": "neutral", "key_themes": [], "confidence_score": 0.5},
                    "catalysts": [],
                    "risks": [],
                    "mitigations": []
                }
            elif response_type == "deduplication_analysis":
                return {
                    "deduplication_summary": {
                        "original_catalysts": 0, "final_catalysts": 0,
                        "original_risks": 0, "final_risks": 0,
                        "original_mitigations": 0, "final_mitigations": 0,
                        "merge_operations": 0
                    },
                    "catalysts": [],
                    "risks": [],
                    "mitigations": []
                }
            else:
                return {response_type: []}

    # ============= ARTICLE LOADING =============

    def load_articles_from_db(self, limit: int = 50) -> List[Dict]:
        """
        Load filtered articles from MongoDB database.
        
        This method retrieves articles that have already been filtered and scored,
        avoiding the need to re-scrape and re-filter articles.
        
        Args:
            min_score: Minimum LLM score threshold for articles
            limit: Maximum number of articles to load
            
        Returns:
            List of article dictionaries compatible with analyze_all_articles()
        """        
        try:
            self._log("info", f"📂 Loading articles from MongoDB for {self.ticker} limit: {limit}")
            
            # Get recent articles from database using vynn_core
            recent_articles = find_recent(limit=limit * 2, collection_name=self.ticker)

            self._log("info", f"✅ Found {len(recent_articles)} recent articles in database")

            # Filter by ticker and score, convert to screener format
            filtered_articles = []
            for article in recent_articles:
                # Convert database format to screener format
                screener_article = {
                    "file_path": None,  # Not from file
                    "file_name": f"db_article_{article.get('_id', 'unknown')}",
                    "title": article.get('title', 'Untitled'),
                    "source_url": article.get('url') or article.get('source_url', ''),
                    "publish_date": article.get('publish_date', ''),
                    "text": article.get('content', ''),
                    "word_count": article.get('word_count', 0),
                    "serpapi_snippet": article.get('serpapi_snippet', ''),
                    "serpapi_source": article.get('serpapi_source', ''),
                    "search_category": article.get('search_category', '')
                }
                filtered_articles.append(screener_article)
            
            # Limit to requested number
            result = filtered_articles[:limit]
            self._log("info", f"✅ Loaded {len(result)} articles from MongoDB (filtered from {len(recent_articles)} total)")
            
            return result
            
        except Exception as e:
            self._log("error", f"❌ Error loading articles from MongoDB: {e}")
            import traceback
            self._log("error", f"Full traceback: {traceback.format_exc()}")
            # Fallback to local file loading
            self._log("info", "⚠️  Falling back to local file loading")

    def analyze_all_articles(self, articles: List[Dict], batch_size: int = 10) -> Tuple[List[Catalyst], List[Risk], List[Mitigation], AnalysisSummary]:
        """
        Analyze all articles using batch processing to send multiple articles to LLM at once.
        Articles are processed in batches of the specified size (default 10) for efficiency.
        """
        all_catalysts = []
        all_risks = []
        all_mitigations = []

        # Calculate number of batches
        total_batches = (len(articles) + batch_size - 1) // batch_size
        
        self._log("info", f"🚀 Starting batch analysis for {len(articles)} articles")
        self._log("info", f"� Processing in {total_batches} batch(es) of up to {batch_size} articles each...")

        # Process articles in batches
        for batch_num in range(total_batches):
            start_idx = batch_num * batch_size
            end_idx = min(start_idx + batch_size, len(articles))
            batch_articles = articles[start_idx:end_idx]
            
            self._log("info", f"📦 Batch {batch_num + 1}/{total_batches}: Processing articles {start_idx + 1}-{end_idx}")
            
            # Analyze the batch (will auto-split if too large)
            batch_catalysts, batch_risks, batch_mitigations = self._analyze_article_batch(
                batch_articles, 
                batch_num + 1,
                depth=0
            )
            
            # Add to overall results
            all_catalysts.extend(batch_catalysts)
            all_risks.extend(batch_risks)
            all_mitigations.extend(batch_mitigations)
        
        self._log("info", f"🔄 Using LLM to intelligently deduplicate insights across {len(articles)} articles...")
        # Use LLM-powered deduplication instead of simple merging
        # merged_catalysts, merged_risks, merged_mitigations = self._llm_deduplicate_insights(all_catalysts, all_risks, all_mitigations)
        
        self._log("info", f"✅ Batch analysis complete! Raw insights: {len(all_catalysts)}🚀 {len(all_risks)}⚠️ {len(all_mitigations)}🛡️")
        # self._log("info", f"🔍 After LLM deduplication: {len(merged_catalysts)}🚀 {len(merged_risks)}⚠️ {len(merged_mitigations)}🛡️")
        self._log("info", f"💰 Total LLM cost: ${self.total_llm_cost:.4f} USD across {self.llm_call_count} calls")
        
        # Create overall analysis summary
        overall_summary = AnalysisSummary(
            overall_sentiment=self._determine_overall_sentiment(all_catalysts, all_risks),
            key_themes=self._extract_key_themes(all_catalysts, all_risks),
            confidence_score=self._calculate_overall_confidence(all_catalysts, all_risks, all_mitigations),
            articles_analyzed=len(articles),
            total_catalysts=len(all_catalysts),
            total_risks=len(all_risks),
            total_mitigations=len(all_mitigations)
        )

        return all_catalysts, all_risks, all_mitigations, overall_summary
    
    def _determine_overall_sentiment(self, catalysts: List[Catalyst], risks: List[Risk]) -> str:
        """Determine overall sentiment based on catalyst and risk balance."""
        if not catalysts and not risks:
            return "neutral"
        
        catalyst_score = sum(c.confidence for c in catalysts)
        risk_score = sum(r.confidence * ({"low": 1, "medium": 2, "high": 3, "critical": 4}.get(r.severity, 2)) for r in risks)
        
        if catalyst_score > risk_score * 1.5:
            return "bullish"
        elif risk_score > catalyst_score * 1.5:
            return "bearish"
        else:
            return "neutral"
    
    def _extract_key_themes(self, catalysts: List[Catalyst], risks: List[Risk]) -> List[str]:
        """Extract key themes from catalysts and risks."""
        themes = []
        
        # Catalyst themes
        catalyst_types = Counter(c.type for c in catalysts)
        for cat_type, count in catalyst_types.most_common(3):
            themes.append(f"{cat_type.title()} Growth ({count} catalysts)")
        
        # Risk themes
        risk_types = Counter(r.type for r in risks)
        for risk_type, count in risk_types.most_common(2):
            themes.append(f"{risk_type.title()} Risk ({count} risks)")

        return themes[:10]  # Limit to top 10 themes

    def _calculate_overall_confidence(self, catalysts: List[Catalyst], risks: List[Risk], mitigations: List[Mitigation]) -> float:
        """Calculate overall confidence score based on all insights."""
        if not any([catalysts, risks, mitigations]):
            return 0.5
        
        all_confidences = []
        all_confidences.extend(c.confidence for c in catalysts)
        all_confidences.extend(r.confidence for r in risks)
        all_confidences.extend(m.confidence for m in mitigations)
        
        return sum(all_confidences) / len(all_confidences) if all_confidences else 0.5

    def save_structured_data(self, catalysts: List[Catalyst], risks: List[Risk], 
                           mitigations: List[Mitigation], analysis_summary: AnalysisSummary, output_file: pathlib.Path):
        """Save structured data as JSON for further analysis."""
        data = {
            "timestamp": datetime.now().isoformat(),
            "ticker": self.ticker,
            "analysis_method": "batch_llm",
            "analysis_summary": asdict(analysis_summary),
            "catalysts": [asdict(c) for c in catalysts],
            "risks": [asdict(r) for r in risks],
            "mitigations": [asdict(m) for m in mitigations],
            "llm_stats": {
                "total_batch_calls": self.llm_call_count,
                "total_cost_usd": self.total_llm_cost,
                "articles_analyzed": analysis_summary.articles_analyzed,
                "efficiency_method": "Batch processing for optimal cost and speed"
            }
        }
        
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)


