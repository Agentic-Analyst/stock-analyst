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
    articles_mentioned: List[str]
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
    articles_mentioned: List[str]
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
    articles_mentioned: List[str]
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
    
    def _analyze_article_batch(self, articles: List[Dict], batch_num: int) -> Tuple[List[Catalyst], List[Risk], List[Mitigation]]:
        """
        Analyze a batch of articles using LLM for comprehensive insights.
        """
        batch_size = len(articles)
        self._log("info", f"🔍 Analyzing batch {batch_num} with {batch_size} articles...")
        
        # Format articles for batch analysis
        batch_content = self._format_articles_for_batch(articles)
        
        # Check token limits for batch
        total_tokens = self._count_tokens(batch_content)
        
        # If batch is too large, return empty results (no individual fallback)
        if total_tokens > self.max_tokens_per_request:
            self._log("warning", f"Batch {batch_num} exceeds token limit ({total_tokens} tokens), returning empty results")
            return self._fallback_individual_analysis(articles)
        
        catalysts = []
        risks = []
        mitigations = []
        
        try:
            # Create batch analysis prompt - no fallback to unified analysis
            batch_prompt = self._create_batch_analysis_prompt(batch_content, self.ticker, batch_size)
            
            # Make LLM call
            self._log("info", f"🤖 Processing batch {batch_num} - extracting insights across {batch_size} articles...")
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
                    articles_mentioned=[a['file_name'] for a in articles],  # Legacy field
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
                    articles_mentioned=[a['file_name'] for a in articles],  # Legacy field
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
                    articles_mentioned=[a['file_name'] for a in articles],  # Legacy field
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
            self._log("error", f"Batch {batch_num} analysis failed: {e}")
            # Return empty results if batch fails (no individual fallback)
            return self._fallback_individual_analysis(articles)

        return catalysts, risks, mitigations
    
    def _fallback_individual_analysis(self, articles: List[Dict]) -> Tuple[List[Catalyst], List[Risk], List[Mitigation]]:
        """
        Fallback method when batch processing fails.
        Now returns empty results instead of processing articles individually.
        """
        self._log("error", f"Batch processing failed for {len(articles)} articles - returning empty results")
        self._log("info", "Individual article fallback has been disabled. Only batch processing is supported.")
        
        # Return empty results instead of processing individually
        return [], [], []

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
            self._log("info", f"📂 Loading articles from MongoDB for {self.ticker} limit: {limit})")
            
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
            
            self._log("info", f"� Batch {batch_num + 1}/{total_batches}: Processing articles {start_idx + 1}-{end_idx}")
            
            # Analyze the batch
            batch_catalysts, batch_risks, batch_mitigations = self._analyze_article_batch(batch_articles, batch_num + 1)
            
            # Add to overall results
            all_catalysts.extend(batch_catalysts)
            all_risks.extend(batch_risks)
            all_mitigations.extend(batch_mitigations)
        
        self._log("info", f"🔄 Using LLM to intelligently deduplicate insights across {len(articles)} articles...")
        # Use LLM-powered deduplication instead of simple merging
        merged_catalysts, merged_risks, merged_mitigations = self._llm_deduplicate_insights(all_catalysts, all_risks, all_mitigations)
        
        self._log("info", f"✅ Batch analysis complete! Raw insights: {len(all_catalysts)}🚀 {len(all_risks)}⚠️ {len(all_mitigations)}🛡️")
        self._log("info", f"🔍 After LLM deduplication: {len(merged_catalysts)}🚀 {len(merged_risks)}⚠️ {len(merged_mitigations)}🛡️")
        self._log("info", f"💰 Total LLM cost: ${self.total_llm_cost:.4f} USD across {self.llm_call_count} calls")
        
        # Create overall analysis summary
        overall_summary = AnalysisSummary(
            overall_sentiment=self._determine_overall_sentiment(merged_catalysts, merged_risks),
            key_themes=self._extract_key_themes(merged_catalysts, merged_risks),
            confidence_score=self._calculate_overall_confidence(merged_catalysts, merged_risks, merged_mitigations),
            articles_analyzed=len(articles),
            total_catalysts=len(merged_catalysts),
            total_risks=len(merged_risks),
            total_mitigations=len(merged_mitigations)
        )
        
        return merged_catalysts, merged_risks, merged_mitigations, overall_summary

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

    # ============= LLM-POWERED DEDUPLICATION METHODS =============
    
    def _llm_deduplicate_insights(self, catalysts: List[Catalyst], risks: List[Risk], mitigations: List[Mitigation]) -> Tuple[List[Catalyst], List[Risk], List[Mitigation]]:
        """
        Use LLM to intelligently deduplicate and merge similar insights across all batches.
        This replaces simple string matching with semantic understanding.
        """        
        if not any([catalysts, risks, mitigations]):
            return [], [], []
        
        self._log("info", f"🔍 Using LLM to deduplicate {len(catalysts)} catalysts, {len(risks)} risks, {len(mitigations)} mitigations...")
        
        try:
            # Format insights for LLM analysis
            insights_content = self._format_insights_for_deduplication(catalysts, risks, mitigations)
            
            # Create deduplication prompt
            dedup_prompt = self._create_deduplication_prompt(insights_content)
            
            # Make LLM call for deduplication
            response, cost = get_llm()(dedup_prompt)
            self.total_llm_cost += cost
            self.llm_call_count += 1
            
            # Parse response
            dedup_data = self._parse_llm_json_response(response, "deduplication_analysis")
            
            # Extract deduplicated insights
            final_catalysts = self._parse_deduplicated_catalysts(dedup_data.get("catalysts", []))
            final_risks = self._parse_deduplicated_risks(dedup_data.get("risks", []))
            final_mitigations = self._parse_deduplicated_mitigations(dedup_data.get("mitigations", []))
            
            # Log deduplication results
            summary = dedup_data.get("deduplication_summary", {})
            original_total = summary.get("original_catalysts", 0) + summary.get("original_risks", 0) + summary.get("original_mitigations", 0)
            final_total = summary.get("final_catalysts", 0) + summary.get("final_risks", 0) + summary.get("final_mitigations", 0)
            merge_ops = summary.get("merge_operations", 0)
            
            self._log("info", f"✅ LLM deduplication complete: {original_total} → {final_total} insights ({merge_ops} merge operations)")
            self._log("info", f"   📊 Final: {len(final_catalysts)}🚀 {len(final_risks)}⚠️ {len(final_mitigations)}🛡️")
            self._log("info", f"💰 Deduplication cost: ${cost:.4f} USD | Running total: ${self.total_llm_cost:.4f} USD")
            
            return final_catalysts, final_risks, final_mitigations
            
        except Exception as e:
            self._log("error", f"LLM deduplication failed: {e}")
            self._log("warning", "Falling back to simple deduplication methods")
            return self._merge_similar_catalysts(catalysts), self._merge_similar_risks(risks), self._merge_similar_mitigations(mitigations)
    
    def _create_deduplication_prompt(self, insights_content: str) -> List[Dict]:
        """Create prompt for LLM-powered deduplication."""
        system_prompt = load_prompt("deduplication_analysis")
        user_prompt = load_prompt("deduplication_user").format(
            company_ticker=self.ticker,
            **insights_content
        )
        
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
    
    def _format_insights_for_deduplication(self, catalysts: List[Catalyst], risks: List[Risk], mitigations: List[Mitigation]) -> Dict[str, str]:
        """Format insights into a structured text for LLM analysis."""
        
        # Format catalysts
        catalysts_text = ""
        for i, catalyst in enumerate(catalysts, 1):
            catalysts_text += f"**Catalyst {i}:**\n"
            catalysts_text += f"- Type: {catalyst.type}\n"
            catalysts_text += f"- Description: {catalyst.description}\n"
            catalysts_text += f"- Confidence: {catalyst.confidence:.2f}\n"
            catalysts_text += f"- Timeline: {catalyst.timeline}\n"
            if catalyst.reasoning:
                catalysts_text += f"- Reasoning: {catalyst.reasoning}\n"
            if catalyst.supporting_evidence:
                catalysts_text += f"- Evidence: {'; '.join(catalyst.supporting_evidence)}\n"
            if catalyst.direct_quotes:
                quotes = [q.quote for q in catalyst.direct_quotes]
                catalysts_text += f"- Quotes: {'; '.join(quotes)}\n"
            # Format source articles properly
            if catalyst.source_articles:
                sources = [f"{ref.title} ({ref.url})" if ref.url else ref.title for ref in catalyst.source_articles]
                catalysts_text += f"- Sources: {', '.join(sources)}\n"
            elif catalyst.articles_mentioned:
                catalysts_text += f"- Sources: {', '.join(catalyst.articles_mentioned)}\n"
            catalysts_text += "\n"
        
        # Format risks
        risks_text = ""
        for i, risk in enumerate(risks, 1):
            risks_text += f"**Risk {i}:**\n"
            risks_text += f"- Type: {risk.type}\n"
            risks_text += f"- Description: {risk.description}\n"
            risks_text += f"- Severity: {risk.severity}\n"
            risks_text += f"- Confidence: {risk.confidence:.2f}\n"
            if risk.reasoning:
                risks_text += f"- Reasoning: {risk.reasoning}\n"
            if risk.supporting_evidence:
                risks_text += f"- Evidence: {'; '.join(risk.supporting_evidence)}\n"
            if risk.direct_quotes:
                quotes = [q.quote for q in risk.direct_quotes]
                risks_text += f"- Quotes: {'; '.join(quotes)}\n"
            # Format source articles properly
            if risk.source_articles:
                sources = [f"{ref.title} ({ref.url})" if ref.url else ref.title for ref in risk.source_articles]
                risks_text += f"- Sources: {', '.join(sources)}\n"
            elif risk.articles_mentioned:
                risks_text += f"- Sources: {', '.join(risk.articles_mentioned)}\n"
            risks_text += "\n"
        
        # Format mitigations
        mitigations_text = ""
        for i, mitigation in enumerate(mitigations, 1):
            mitigations_text += f"**Mitigation {i}:**\n"
            mitigations_text += f"- Risk Addressed: {mitigation.risk_addressed}\n"
            mitigations_text += f"- Strategy: {mitigation.strategy}\n"
            mitigations_text += f"- Effectiveness: {mitigation.effectiveness}\n"
            mitigations_text += f"- Confidence: {mitigation.confidence:.2f}\n"
            if mitigation.reasoning:
                mitigations_text += f"- Reasoning: {mitigation.reasoning}\n"
            if mitigation.supporting_evidence:
                mitigations_text += f"- Evidence: {'; '.join(mitigation.supporting_evidence)}\n"
            if mitigation.direct_quotes:
                quotes = [q.quote for q in mitigation.direct_quotes]
                mitigations_text += f"- Quotes: {'; '.join(quotes)}\n"
            # Format source articles properly
            if mitigation.source_articles:
                sources = [f"{ref.title} ({ref.url})" if ref.url else ref.title for ref in mitigation.source_articles]
                mitigations_text += f"- Sources: {', '.join(sources)}\n"
            elif mitigation.articles_mentioned:
                mitigations_text += f"- Sources: {', '.join(mitigation.articles_mentioned)}\n"
            mitigations_text += "\n"
        
        return {
            "catalyst_count": len(catalysts),
            "catalysts_data": catalysts_text or "None",
            "risk_count": len(risks),
            "risks_data": risks_text or "None",
            "mitigation_count": len(mitigations),
            "mitigations_data": mitigations_text or "None"
        }
    
    def _parse_deduplicated_catalysts(self, catalysts_data: List[Dict]) -> List[Catalyst]:
        """Parse deduplicated catalysts from LLM response."""
        catalysts = []
        for cat_data in catalysts_data:
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
                articles_mentioned=cat_data.get("source_articles", []) if isinstance(cat_data.get("source_articles", []), list) and all(isinstance(x, str) for x in cat_data.get("source_articles", [])) else [],
                timeline=cat_data.get("timeline", "medium-term").lower().replace("_", "-"),
                llm_reasoning=cat_data.get("reasoning", ""),
                llm_confidence=cat_data.get("confidence", 0.5),
                reasoning=cat_data.get("reasoning", ""),
                direct_quotes=direct_quotes,
                source_articles=source_articles,
                potential_impact=cat_data.get("potential_impact", "")
            )
            catalysts.append(catalyst)
        
        return catalysts
    
    def _parse_deduplicated_risks(self, risks_data: List[Dict]) -> List[Risk]:
        """Parse deduplicated risks from LLM response."""
        risks = []
        for risk_data in risks_data:
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
                articles_mentioned=risk_data.get("source_articles", []) if isinstance(risk_data.get("source_articles", []), list) and all(isinstance(x, str) for x in risk_data.get("source_articles", [])) else [],
                potential_impact=risk_data.get("potential_impact", ""),
                llm_reasoning=risk_data.get("reasoning", ""),
                llm_confidence=risk_data.get("confidence", 0.5),
                reasoning=risk_data.get("reasoning", ""),
                direct_quotes=direct_quotes,
                source_articles=source_articles,
                likelihood=risk_data.get("likelihood", "medium")
            )
            risks.append(risk)
        
        return risks
    
    def _parse_deduplicated_mitigations(self, mitigations_data: List[Dict]) -> List[Mitigation]:
        """Parse deduplicated mitigations from LLM response."""
        mitigations = []
        for mit_data in mitigations_data:
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
                articles_mentioned=mit_data.get("source_articles", []) if isinstance(mit_data.get("source_articles", []), list) and all(isinstance(x, str) for x in mit_data.get("source_articles", [])) else [],
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
        
        return mitigations

    # ============= END LLM DEDUPLICATION METHODS =============


    def _merge_similar_catalysts(self, catalysts: List[Catalyst]) -> List[Catalyst]:
        """Merge similar catalysts to avoid duplicates."""
        if not catalysts:
            return []
        
        merged = []
        used_indices = set()
        
        for i, catalyst in enumerate(catalysts):
            if i in used_indices:
                continue
                
            similar_catalysts = [catalyst]
            used_indices.add(i)
            
            # Find similar catalysts
            for j, other_catalyst in enumerate(catalysts[i+1:], i+1):
                if j in used_indices:
                    continue
                    
                if (catalyst.type == other_catalyst.type and 
                    self._are_descriptions_similar(catalyst.description, other_catalyst.description)):
                    similar_catalysts.append(other_catalyst)
                    used_indices.add(j)
            
            # Merge if multiple similar catalysts found
            if len(similar_catalysts) > 1:
                merged_catalyst = self._merge_catalyst_group(similar_catalysts)
                merged.append(merged_catalyst)
            else:
                merged.append(catalyst)
        
        return merged

    def _merge_similar_risks(self, risks: List[Risk]) -> List[Risk]:
        """Merge similar risks to avoid duplicates."""
        # Similar logic to catalyst merging
        if not risks:
            return []
        
        merged = []
        used_indices = set()
        
        for i, risk in enumerate(risks):
            if i in used_indices:
                continue
                
            similar_risks = [risk]
            used_indices.add(i)
            
            for j, other_risk in enumerate(risks[i+1:], i+1):
                if j in used_indices:
                    continue
                    
                if (risk.type == other_risk.type and 
                    self._are_descriptions_similar(risk.description, other_risk.description)):
                    similar_risks.append(other_risk)
                    used_indices.add(j)
            
            if len(similar_risks) > 1:
                merged_risk = self._merge_risk_group(similar_risks)
                merged.append(merged_risk)
            else:
                merged.append(risk)
        
        return merged

    def _merge_similar_mitigations(self, mitigations: List[Mitigation]) -> List[Mitigation]:
        """Merge similar mitigations."""
        # Similar merging logic
        return mitigations  # Simplified for now

    def _are_descriptions_similar(self, desc1: str, desc2: str, threshold: float = 0.6) -> bool:
        """Check if two descriptions are similar."""
        # Simple similarity check based on common words
        words1 = set(re.findall(r'\b\w+\b', desc1.lower()))
        words2 = set(re.findall(r'\b\w+\b', desc2.lower()))
        
        if not words1 or not words2:
            return False
        
        intersection = len(words1.intersection(words2))
        union = len(words1.union(words2))
        
        similarity = intersection / union if union > 0 else 0
        return similarity >= threshold

    def _merge_catalyst_group(self, catalysts: List[Catalyst]) -> Catalyst:
        """Merge a group of similar catalysts."""
        # Combine evidence and articles
        all_evidence = []
        all_articles = []
        total_confidence = 0
        
        for catalyst in catalysts:
            all_evidence.extend(catalyst.supporting_evidence)
            all_articles.extend(catalyst.articles_mentioned)
            total_confidence += catalyst.confidence
        
        # Create merged catalyst
        base_catalyst = catalysts[0]
        return Catalyst(
            type=base_catalyst.type,
            description=base_catalyst.description,
            confidence=min(1.0, total_confidence / len(catalysts) + 0.1),  # Boost merged confidence
            supporting_evidence=list(set(all_evidence)),
            articles_mentioned=list(set(all_articles)),
            timeline=base_catalyst.timeline
        )

    def _merge_risk_group(self, risks: List[Risk]) -> Risk:
        """Merge a group of similar risks."""
        all_evidence = []
        all_articles = []
        total_confidence = 0
        
        for risk in risks:
            all_evidence.extend(risk.supporting_evidence)
            all_articles.extend(risk.articles_mentioned)
            total_confidence += risk.confidence
        
        base_risk = risks[0]
        return Risk(
            type=base_risk.type,
            description=base_risk.description,
            severity=base_risk.severity,
            confidence=min(1.0, total_confidence / len(risks) + 0.1),
            supporting_evidence=list(set(all_evidence)),
            articles_mentioned=list(set(all_articles)),
            potential_impact=base_risk.potential_impact
        )

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


