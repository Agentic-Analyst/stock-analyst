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
import os, csv, argparse, pathlib, re, json, asyncio, math
from datetime import datetime
from typing import Dict, List, Tuple, Set, Optional
from dataclasses import dataclass, asdict
from collections import defaultdict, Counter
import yaml
from urllib.parse import urlsplit, urlunsplit

# Import centralized configuration
from config import (
    MIN_CONFIDENCE,
    NEWS_CANDIDATE_LIMIT,
    NEWS_MAX_AGE_DAYS,
    NEWS_MIN_FRESH_ARTICLES,
)
from news_freshness import filter_fresh_articles
from article_relevance import filter_subject_articles
import tiktoken
from llms.config import get_llm
from vynn_core import find_recent, get_article_by_url
from recommendation_validator import RecommendationValidator

PROMPTS_ROOT = pathlib.Path(__file__).resolve().parent.parent / "prompts"


def _mongo_configured() -> bool:
    return bool(
        (os.getenv("MONGO_URI") or "").strip()
        and (os.getenv("MONGO_DB") or "").strip()
    )

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
    publish_date: Optional[str] = None
    snippet: Optional[str] = None

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
    confidence_basis: Optional[str] = None  # Deterministic evidence calibration
    
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
    confidence_basis: Optional[str] = None  # Deterministic evidence calibration
    
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
    confidence_basis: Optional[str] = None  # Deterministic evidence calibration
    
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
    def __init__(self, ticker: str, base_path: pathlib.Path,
                 company_name: Optional[str] = None):
        self.ticker = ticker.upper()
        self.company_name = company_name
        self.company_dir = base_path
        
        # Logger - will be set by pipeline if available
        self.logger = None
        
        # Load configuration
        self.min_confidence = MIN_CONFIDENCE
        
        # Cost tracking for LLM usage
        self.total_llm_cost = 0.0
        self.llm_call_count = 0
        self.last_freshness: Dict[str, object] = {}
        
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
            batch_content += f"<UNTRUSTED_ARTICLE index=\"{i}\">\n"
            batch_content += f"### ARTICLE {i}: {article['file_name']}\n"
            batch_content += f"**Title:** {article['title']}\n"
            batch_content += f"**Source:** {article.get('source_url', 'N/A')}\n"
            batch_content += f"**Date:** {article.get('publish_date', 'N/A')}\n\n"
            batch_content += f"**Content:**\n{article['text']}\n\n"
            batch_content += "</UNTRUSTED_ARTICLE>\n\n"
        
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
            
            # Parse response into structured insights (shared by sync + async paths)
            analysis_data = self._parse_llm_json_response(response, "batch_analysis")
            catalysts, risks, mitigations = self._parse_batch_analysis_data(analysis_data)
            catalysts, risks, mitigations = self._ground_insights(
                catalysts, risks, mitigations, articles
            )

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

            return catalysts, risks, mitigations

        except Exception as e:
            return self._handle_batch_error(e, articles, batch_num, depth)

    def _parse_batch_analysis_data(
        self, analysis_data: Dict
    ) -> Tuple[List[Catalyst], List[Risk], List[Mitigation]]:
        """
        Convert parsed batch-analysis JSON into Catalyst/Risk/Mitigation objects.

        Pure/deterministic — no LLM, no I/O — so it is safely reused by both the
        synchronous ``_analyze_article_batch`` and the async fan-out variant.
        """
        catalysts: List[Catalyst] = []
        risks: List[Risk] = []
        mitigations: List[Mitigation] = []

        if analysis_data:
            # Extract catalysts with enhanced information
            for cat_data in analysis_data.get("catalysts", []):
                if not isinstance(cat_data, dict):
                    continue
                # Parse direct quotes
                direct_quotes = []
                for quote_data in cat_data.get("direct_quotes", []):
                    if not isinstance(quote_data, dict):
                        continue
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
                    confidence=self._bounded_confidence(cat_data.get("confidence")),
                    supporting_evidence=self._string_list(
                        cat_data.get("supporting_evidence")),
                    timeline=self._enum_value(
                        cat_data.get("timeline"),
                        {"immediate", "short-term", "medium-term", "long-term"},
                        "medium-term",
                    ),
                    llm_reasoning=cat_data.get("reasoning", ""),
                    llm_confidence=self._bounded_confidence(cat_data.get("confidence")),
                    reasoning=cat_data.get("reasoning", ""),
                    direct_quotes=direct_quotes,
                    source_articles=source_articles,
                    potential_impact=cat_data.get("potential_impact", "")
                )
                catalysts.append(catalyst)

            # Extract risks with enhanced information
            for risk_data in analysis_data.get("risks", []):
                if not isinstance(risk_data, dict):
                    continue
                # Parse direct quotes
                direct_quotes = []
                for quote_data in risk_data.get("direct_quotes", []):
                    if not isinstance(quote_data, dict):
                        continue
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
                    severity=self._enum_value(
                        risk_data.get("severity"),
                        {"low", "medium", "high", "critical"}, "medium"),
                    confidence=self._bounded_confidence(risk_data.get("confidence")),
                    supporting_evidence=self._string_list(
                        risk_data.get("supporting_evidence")),
                    potential_impact=risk_data.get("potential_impact", ""),
                    llm_reasoning=risk_data.get("reasoning", ""),
                    llm_confidence=self._bounded_confidence(risk_data.get("confidence")),
                    reasoning=risk_data.get("reasoning", ""),
                    direct_quotes=direct_quotes,
                    source_articles=source_articles,
                    likelihood=self._enum_value(
                        risk_data.get("likelihood"),
                        {"low", "medium", "high"}, "medium")
                )
                risks.append(risk)
            
            # Extract mitigations with enhanced information
            for mit_data in analysis_data.get("mitigations", []):
                if not isinstance(mit_data, dict):
                    continue
                # Parse direct quotes
                direct_quotes = []
                for quote_data in mit_data.get("direct_quotes", []):
                    if not isinstance(quote_data, dict):
                        continue
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
                    confidence=self._bounded_confidence(mit_data.get("confidence")),
                    supporting_evidence=self._string_list(
                        mit_data.get("supporting_evidence")),
                    effectiveness=self._enum_value(
                        mit_data.get("effectiveness"),
                        {"low", "medium", "high"}, "medium"),
                    company_action=mit_data.get("company_action", ""),
                    llm_reasoning=mit_data.get("reasoning", ""),
                    llm_confidence=self._bounded_confidence(mit_data.get("confidence")),
                    reasoning=mit_data.get("reasoning", ""),
                    direct_quotes=direct_quotes,
                    source_articles=source_articles,
                    implementation_timeline=mit_data.get("implementation_timeline", "")
                )
                mitigations.append(mitigation)

        return catalysts, risks, mitigations

    @staticmethod
    def _bounded_confidence(value: object, default: float = 0.5) -> float:
        """Normalize an untrusted model score to the documented 0..1 range."""
        if isinstance(value, bool):
            return default
        try:
            number = float(value)
        except (TypeError, ValueError):
            return default
        if not math.isfinite(number):
            return default
        return min(max(number, 0.0), 1.0)

    @staticmethod
    def _string_list(value: object) -> List[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()][:20]

    @staticmethod
    def _enum_value(value: object, allowed: Set[str], default: str) -> str:
        normalized = str(value or "").strip().lower().replace("_", "-")
        return normalized if normalized in allowed else default

    @staticmethod
    def _canonical_url(value: str) -> str:
        try:
            parsed = urlsplit(str(value or "").strip())
        except ValueError:
            return ""
        if not parsed.netloc:
            return ""
        host = parsed.netloc.casefold().removeprefix("www.")
        path = parsed.path.rstrip("/") or "/"
        return urlunsplit((parsed.scheme.casefold() or "https", host, path, "", ""))

    @staticmethod
    def _normalized_source_text(value: str) -> str:
        return " ".join(
            str(value or "").replace("’", "'").replace("“", '"').replace("”", '"')
            .casefold().split()
        )

    @classmethod
    def _claim_supported(cls, claim: str, source_text: str) -> bool:
        claim_numbers = RecommendationValidator._support_numbers(claim)
        source_numbers = RecommendationValidator._support_numbers(source_text)
        if claim_numbers and not claim_numbers.issubset(source_numbers):
            return False
        overlap = RecommendationValidator._support_tokens(claim).intersection(
            RecommendationValidator._support_tokens(source_text)
        )
        return len(overlap) >= 2 or any(len(token) >= 7 for token in overlap)

    @staticmethod
    def _quote_excerpt(value: str, max_words: int = 25, max_chars: int = 240) -> str:
        """Keep a short verbatim excerpt instead of reproducing article prose."""
        text = " ".join(str(value or "").split())
        words = text.split()
        clipped = len(words) > max_words or len(text) > max_chars
        candidate = " ".join(words[:max_words])
        if len(candidate) > max_chars:
            candidate = candidate[:max_chars + 1].rsplit(" ", 1)[0].rstrip()
        return candidate + ("…" if clipped and candidate else "")

    @classmethod
    def _calibrate_evidence_confidence(cls, insight) -> None:
        """Cap model confidence by the corroboration actually retained.

        The score is extraction confidence, not the probability a stock outcome
        occurs. One opinion article cannot become 99%-certain merely because the
        language model sounded confident. Independent publishers raise the cap;
        a verified primary/regulatory source can support a high single-source
        score for a factual event.
        """
        references = getattr(insight, "source_articles", None) or []
        canonical_urls = {
            cls._canonical_url(getattr(reference, "url", ""))
            for reference in references
        }
        canonical_urls.discard("")
        hosts = {
            (urlsplit(url).hostname or "").casefold().removeprefix("www.")
            for url in canonical_urls
        }
        primary = any(
            host == "sec.gov" or host.endswith(".sec.gov")
            or host.endswith(".gov") or host == "ec.europa.eu"
            for host in hosts
        )
        if len(hosts) >= 3:
            cap, basis = 0.95, "three_or_more_independent_publishers"
        elif len(hosts) >= 2:
            cap, basis = 0.90, "two_independent_publishers"
        elif len(canonical_urls) >= 2:
            cap, basis = 0.85, "multiple_articles_one_publisher"
        elif primary:
            cap, basis = 0.90, "verified_primary_or_regulatory_source"
        elif getattr(insight, "direct_quotes", None):
            cap, basis = 0.80, "single_source_with_verified_excerpt"
        else:
            cap, basis = 0.70, "single_source_without_verified_excerpt"
        raw = cls._bounded_confidence(
            getattr(insight, "llm_confidence", None),
            default=cls._bounded_confidence(getattr(insight, "confidence", None)),
        )
        insight.llm_confidence = raw
        insight.confidence = min(raw, cap)
        insight.confidence_basis = (
            f"model_extraction_score={raw:.2f}; evidence_cap={cap:.2f}; {basis}"
        )

    def _ground_insights(
        self, catalysts: List[Catalyst], risks: List[Risk], mitigations: List[Mitigation],
        articles: List[Dict],
    ) -> Tuple[List[Catalyst], List[Risk], List[Mitigation]]:
        """Keep only insights whose references and claims map to input articles."""
        by_url = {}
        by_title = {}
        for article in articles:
            url = self._canonical_url(article.get("source_url") or article.get("url") or "")
            title_key = self._normalized_source_text(article.get("title") or "")
            if url:
                by_url[url] = article
            if title_key:
                by_title[title_key] = article

        def resolve(title: str, url: str) -> Optional[Dict]:
            return (
                by_url.get(self._canonical_url(url))
                or by_title.get(self._normalized_source_text(title))
            )

        dropped = 0

        def ground(rows):
            nonlocal dropped
            kept = []
            for insight in rows:
                matched = []
                seen_urls = set()
                for reference in insight.source_articles:
                    article = resolve(reference.title, reference.url)
                    if not article:
                        continue
                    actual_url = str(article.get("source_url") or article.get("url") or "")
                    canonical = self._canonical_url(actual_url)
                    if canonical in seen_urls:
                        continue
                    seen_urls.add(canonical)
                    matched.append((article, ArticleReference(
                        title=str(article.get("title") or "Untitled"),
                        url=actual_url,
                        publish_date=(
                            article.get("_publication_datetime")
                            or article.get("publish_date")
                        ),
                        snippet=str(
                            article.get("serpapi_snippet")
                            or article.get("snippet")
                            or article.get("text")
                            or article.get("content")
                            or ""
                        )[:1000],
                    )))

                # A quote can recover a missing source_articles entry only when
                # its own source title/URL exactly maps to this input batch.
                for quote in insight.direct_quotes:
                    article = resolve(quote.source_article, quote.source_url)
                    if not article:
                        continue
                    actual_url = str(article.get("source_url") or article.get("url") or "")
                    canonical = self._canonical_url(actual_url)
                    if canonical in seen_urls:
                        continue
                    seen_urls.add(canonical)
                    matched.append((article, ArticleReference(
                        title=str(article.get("title") or "Untitled"),
                        url=actual_url,
                        publish_date=article.get("_publication_datetime") or article.get("publish_date"),
                        snippet=str(article.get("serpapi_snippet") or article.get("text") or "")[:1000],
                    )))

                claim = (
                    insight.description if hasattr(insight, "description")
                    else f"{insight.risk_addressed} {insight.strategy}"
                )
                # One actual source must support the whole claim on its own.
                # Concatenating several unrelated articles allowed token/number
                # fragments from different sources to manufacture apparent
                # support for a combined claim that none of them made.
                supported_matched = []
                for article, reference in matched:
                    individual_text = " ".join(
                        str(article.get(key) or "") for key in (
                            "title", "serpapi_snippet", "snippet", "text", "content",
                        )
                    )
                    if self._claim_supported(claim, individual_text):
                        supported_matched.append((article, reference))
                if not supported_matched:
                    dropped += 1
                    continue

                matched = supported_matched
                source_text = " ".join(
                    " ".join(str(article.get(key) or "") for key in (
                        "title", "serpapi_snippet", "snippet", "text", "content",
                    ))
                    for article, _ in matched
                )

                insight.source_articles = [reference for _, reference in matched]
                valid_quotes = []
                for quote in insight.direct_quotes:
                    article = resolve(quote.source_article, quote.source_url)
                    if not article or len(str(quote.quote or "").strip()) < 12:
                        continue
                    article_text = self._normalized_source_text(
                        article.get("text") or article.get("content") or ""
                    )
                    if self._normalized_source_text(quote.quote) not in article_text:
                        continue
                    quote.source_article = str(article.get("title") or "Untitled")
                    quote.source_url = str(article.get("source_url") or article.get("url") or "")
                    quote.quote = self._quote_excerpt(quote.quote)
                    valid_quotes.append(quote)
                insight.direct_quotes = valid_quotes
                insight.supporting_evidence = [
                    item for item in insight.supporting_evidence
                    if self._claim_supported(str(item), source_text)
                ]
                self._calibrate_evidence_confidence(insight)
                kept.append(insight)
            return kept

        grounded = ground(catalysts), ground(risks), ground(mitigations)
        if dropped:
            self._log(
                "warning",
                f"Evidence provenance gate dropped {dropped} ungrounded insight(s) "
                "with unknown sources or unsupported claims",
            )
        return grounded

    @staticmethod
    def _dedup_tokens(value: str) -> List[str]:
        stop = {
            "a", "an", "and", "are", "as", "at", "be", "by", "can",
            "company", "could", "for", "from", "has", "have", "if", "in",
            "into", "is", "it", "its", "may", "new", "of", "on", "or",
            "that", "the", "their", "this", "to", "under", "when", "which",
            "while", "with",
        }
        words = re.findall(r"[a-z0-9]+", str(value or "").casefold())
        return [
            word[:-1] if word.endswith("s") and len(word) > 4 else word
            for word in words
            if (len(word) > 2 or word == "ai") and word not in stop
        ]

    @classmethod
    def _insights_are_duplicates(cls, left, right) -> bool:
        type_aliases = {"technological": "technology", "finance": "financial"}
        left_raw = str(getattr(left, "type", "") or "").casefold()
        right_raw = str(getattr(right, "type", "") or "").casefold()
        left_type = type_aliases.get(left_raw, left_raw)
        right_type = type_aliases.get(right_raw, right_raw)
        if left_type and right_type and left_type != right_type:
            return False

        def text(row):
            if hasattr(row, "description"):
                return row.description
            return f"{getattr(row, 'risk_addressed', '')} {getattr(row, 'strategy', '')}"

        left_tokens = cls._dedup_tokens(text(left))
        right_tokens = cls._dedup_tokens(text(right))
        if not left_tokens or not right_tokens:
            return False
        left_set, right_set = set(left_tokens), set(right_tokens)
        overlap = len(left_set & right_set) / min(len(left_set), len(right_set))
        left_bigrams = set(zip(left_tokens, left_tokens[1:]))
        right_bigrams = set(zip(right_tokens, right_tokens[1:]))
        return overlap >= 0.50 or (
            overlap >= 0.25 and bool(left_bigrams & right_bigrams)
        )

    @classmethod
    def _deduplicate_insights(cls, rows: list) -> list:
        """Keep the strongest repeated theme without another model call.

        Do not union evidence from the discarded phrasing into the retained
        claim. Each original source passed grounding against its own wording;
        it has not necessarily established every detail in the surviving row.
        """
        ordered = sorted(
            rows or [], key=lambda row: float(getattr(row, "confidence", 0.0)),
            reverse=True,
        )
        kept = []
        for row in ordered:
            duplicate = next(
                (item for item in kept if cls._insights_are_duplicates(item, row)),
                None,
            )
            if duplicate is None:
                kept.append(row)
                continue
            duplicate.confidence = max(duplicate.confidence, row.confidence)
            duplicate.llm_confidence = max(
                float(duplicate.llm_confidence or duplicate.confidence),
                float(row.llm_confidence or row.confidence),
            )
            if hasattr(duplicate, "severity"):
                ranks = {"low": 0, "medium": 1, "high": 2, "critical": 3}
                if ranks.get(row.severity, 1) > ranks.get(duplicate.severity, 1):
                    duplicate.severity = row.severity
        return kept

    def _is_rate_limit_error(self, error_message: str) -> bool:
        """True if an error string looks like a rate-limit / token-limit failure."""
        error_message = error_message.lower()
        return any(keyword in error_message for keyword in [
            'rate limit', 'rate_limit', 'ratelimit',
            'too many tokens', 'context length', 'maximum context',
            'token limit', 'tokens exceeded', 'timeout',
            '413',  # Payload Too Large
            '429',  # Too Many Requests
        ])

    def _handle_batch_error(
        self, e: Exception, articles: List[Dict], batch_num, depth: int
    ) -> Tuple[List[Catalyst], List[Risk], List[Mitigation]]:
        """
        Shared error handler for the SYNC batch path: on a rate/token-limit error,
        recursively split the batch (or truncate a lone oversized article) and
        retry synchronously; otherwise log and return empty. The async path has its
        own analogue (``_handle_batch_error_async``) so it can await sub-batches.
        """
        batch_size = len(articles)
        indent = "  " * depth
        if self._is_rate_limit_error(str(e)):
            self._log("warning", f"{indent}⚠️  Batch {batch_num} failed due to rate limit/token limit: {e}")

            if batch_size == 1:
                if articles[0].get('already_truncated', False):
                    self._log("error", f"{indent}❌ Article was already truncated but still failed - giving up")
                    return [], [], []
                self._log("warning", f"{indent}📄 Single article too large, truncating content...")
                return self._analyze_truncated_article(articles[0], batch_num, depth)

            mid_point = batch_size // 2
            self._log("info", f"{indent}✂️  Splitting batch {batch_num} into 2 sub-batches: [{mid_point}] + [{batch_size - mid_point}] articles")
            catalysts_1, risks_1, mitigations_1 = self._analyze_article_batch(articles[:mid_point], f"{batch_num}a", depth + 1)
            catalysts_2, risks_2, mitigations_2 = self._analyze_article_batch(articles[mid_point:], f"{batch_num}b", depth + 1)
            all_catalysts = catalysts_1 + catalysts_2
            all_risks = risks_1 + risks_2
            all_mitigations = mitigations_1 + mitigations_2
            self._log("info", f"{indent}✅ Batch {batch_num} complete (split after rate limit): {len(all_catalysts)}🚀 {len(all_risks)}⚠️ {len(all_mitigations)}🛡️")
            return all_catalysts, all_risks, all_mitigations

        self._log("error", f"{indent}❌ Batch {batch_num} analysis failed with non-rate-limit error: {e}")
        return [], [], []

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
        if not _mongo_configured():
            self._log(
                "info",
                "MongoDB persistence is not configured; using current-run local articles",
            )
            self.last_freshness = {
                "status": "unavailable",
                "fresh_articles": 0,
                "reason": "mongodb_not_configured",
            }
            return []

        try:
            self._log("info", f"📂 Loading articles from MongoDB for {self.ticker} limit: {limit}")
            
            # Get recent articles from database using vynn_core
            recent_articles = find_recent(
                limit=max(limit * 2, NEWS_CANDIDATE_LIMIT),
                collection_name=self.ticker,
            )

            self._log("info", f"✅ Found {len(recent_articles)} recent articles in database")

            recent_articles, irrelevant_count = filter_subject_articles(
                recent_articles, self.ticker, self.company_name
            )
            if irrelevant_count:
                self._log(
                    "warning",
                    f"Deterministic subject gate excluded {irrelevant_count} unrelated "
                    f"database article(s) from {self.ticker} coverage",
                )

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
                    "published_at": article.get('published_at'),
                    "scraped_at": article.get('scraped_at'),
                    "createdAt": article.get('createdAt'),
                    "created_at": article.get('created_at'),
                    "text": article.get('content', ''),
                    "word_count": article.get('word_count', 0),
                    "serpapi_snippet": article.get('serpapi_snippet', ''),
                    "serpapi_source": article.get('serpapi_source', ''),
                    "search_category": article.get('search_category', '')
                }
                filtered_articles.append(screener_article)
            
            # Only a source publication date can establish recency.  Ingestion
            # time is not a substitute: old articles are frequently backfilled.
            result, freshness = filter_fresh_articles(
                filtered_articles,
                max_age_days=NEWS_MAX_AGE_DAYS,
                minimum_articles=NEWS_MIN_FRESH_ARTICLES,
                limit=limit,
            )
            freshness["irrelevant_articles_excluded"] = irrelevant_count
            self.last_freshness = freshness
            self._log(
                "info",
                f"✅ Loaded {len(result)} fresh articles from MongoDB "
                f"({freshness['stale_articles_excluded']} stale and "
                f"{freshness['unknown_date_articles_excluded']} undated excluded)",
            )
            
            return result
            
        except Exception as e:
            self._log(
                "warning",
                "MongoDB article lookup failed; using current-run local articles "
                f"({type(e).__name__})",
            )
            # Fallback to local file loading
            self._log("info", "⚠️  Falling back to local file loading")
            self.last_freshness = {
                "status": "unavailable",
                "fresh_articles": 0,
                "error_type": type(e).__name__,
            }
            return []

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
        
        raw_counts = (len(all_catalysts), len(all_risks), len(all_mitigations))
        all_catalysts = self._deduplicate_insights(all_catalysts)
        all_risks = self._deduplicate_insights(all_risks)
        all_mitigations = self._deduplicate_insights(all_mitigations)
        self._log(
            "info",
            f"✅ Batch analysis complete: {raw_counts[0]}/{raw_counts[1]}/{raw_counts[2]} "
            f"raw catalyst/risk/mitigation insights → "
            f"{len(all_catalysts)}/{len(all_risks)}/{len(all_mitigations)} unique themes",
        )
        self._log("info", f"💰 Total LLM cost: ${self.total_llm_cost:.4f} USD across {self.llm_call_count} calls")

        overall_summary = self._build_analysis_summary(
            all_catalysts, all_risks, all_mitigations, len(articles)
        )
        return all_catalysts, all_risks, all_mitigations, overall_summary

    def _build_analysis_summary(
        self,
        all_catalysts: List[Catalyst],
        all_risks: List[Risk],
        all_mitigations: List[Mitigation],
        articles_analyzed: int,
    ) -> AnalysisSummary:
        """Build the aggregate AnalysisSummary. Shared by sync + async orchestrators."""
        return AnalysisSummary(
            overall_sentiment=self._determine_overall_sentiment(all_catalysts, all_risks),
            key_themes=self._extract_key_themes(all_catalysts, all_risks),
            confidence_score=self._calculate_overall_confidence(all_catalysts, all_risks, all_mitigations),
            articles_analyzed=articles_analyzed,
            total_catalysts=len(all_catalysts),
            total_risks=len(all_risks),
            total_mitigations=len(all_mitigations),
        )

    # ============= ASYNC (PARALLEL) BATCH PROCESSING =============

    async def analyze_all_articles_async(
        self,
        articles: List[Dict],
        batch_size: int = 10,
        max_concurrency: int = 5,
    ) -> Tuple[List[Catalyst], List[Risk], List[Mitigation], AnalysisSummary]:
        """
        Parallel counterpart to ``analyze_all_articles``.

        Splits the articles into the same batches, but dispatches them
        concurrently with ``asyncio.gather`` under a semaphore (``max_concurrency``)
        so wall-clock time collapses to roughly the slowest batch instead of the
        sum of all batches. Batch results are independent and simply concatenated,
        exactly as in the sync path, so output is equivalent (ordering across
        batches aside, which does not matter — everything is re-sorted downstream).

        Falls back to identical semantics: same cost tracking, same
        recursive rate-limit splitting (awaited), same summary building.
        """
        all_catalysts: List[Catalyst] = []
        all_risks: List[Risk] = []
        all_mitigations: List[Mitigation] = []

        total_batches = (len(articles) + batch_size - 1) // batch_size
        self._log("info", f"🚀 Starting PARALLEL batch analysis for {len(articles)} articles")
        self._log(
            "info",
            f"⚡ Dispatching {total_batches} batch(es) of up to {batch_size} "
            f"articles, concurrency={max_concurrency}...",
        )

        semaphore = asyncio.Semaphore(max_concurrency)

        async def run_batch(batch_num: int):
            start_idx = batch_num * batch_size
            end_idx = min(start_idx + batch_size, len(articles))
            batch_articles = articles[start_idx:end_idx]
            async with semaphore:
                self._log(
                    "info",
                    f"📦 Batch {batch_num + 1}/{total_batches}: articles {start_idx + 1}-{end_idx}",
                )
                return await self._analyze_article_batch_async(
                    batch_articles, batch_num + 1, depth=0
                )

        # Fan out. return_exceptions=True so one failed batch can't sink the rest;
        # a failure degrades to empty insights for that batch (same as sync).
        results = await asyncio.gather(
            *(run_batch(i) for i in range(total_batches)), return_exceptions=True
        )

        for i, res in enumerate(results):
            if isinstance(res, Exception):
                self._log("error", f"❌ Batch {i + 1} raised and was skipped: {res}")
                continue
            batch_catalysts, batch_risks, batch_mitigations = res
            all_catalysts.extend(batch_catalysts)
            all_risks.extend(batch_risks)
            all_mitigations.extend(batch_mitigations)

        raw_counts = (len(all_catalysts), len(all_risks), len(all_mitigations))
        all_catalysts = self._deduplicate_insights(all_catalysts)
        all_risks = self._deduplicate_insights(all_risks)
        all_mitigations = self._deduplicate_insights(all_mitigations)

        self._log(
            "info",
            f"✅ Parallel batch analysis complete: "
            f"{raw_counts[0]}/{raw_counts[1]}/{raw_counts[2]} raw themes → "
            f"{len(all_catalysts)}/{len(all_risks)}/{len(all_mitigations)} unique themes",
        )
        self._log(
            "info",
            f"💰 Total LLM cost: ${self.total_llm_cost:.4f} USD across "
            f"{self.llm_call_count} calls",
        )

        overall_summary = self._build_analysis_summary(
            all_catalysts, all_risks, all_mitigations, len(articles)
        )
        return all_catalysts, all_risks, all_mitigations, overall_summary

    async def _analyze_article_batch_async(
        self, articles: List[Dict], batch_num, depth: int = 0
    ) -> Tuple[List[Catalyst], List[Risk], List[Mitigation]]:
        """
        Async mirror of ``_analyze_article_batch``: one awaited LLM call, shared
        parsing, and recursive rate-limit splitting (awaited). Cost/parse logic is
        identical to the sync path — only the LLM call and the sub-batch recursion
        are awaited.
        """
        from llms.async_client import get_async_llm

        batch_size = len(articles)
        indent = "  " * depth
        self._log("info", f"{indent}🔍 Analyzing batch {batch_num} with {batch_size} article(s)...")

        batch_content = self._format_articles_for_batch(articles)
        total_tokens = self._count_tokens(batch_content)
        self._log("info", f"{indent}📊 Batch {batch_num} size: {total_tokens:,} tokens")

        try:
            batch_prompt = self._create_batch_analysis_prompt(batch_content, self.ticker, batch_size)
            self._log("info", f"{indent}🤖 Processing batch {batch_num} - extracting insights across {batch_size} article(s)...")
            response, cost = await get_async_llm()(batch_prompt)
            self.total_llm_cost += cost
            self.llm_call_count += 1

            analysis_data = self._parse_llm_json_response(response, "batch_analysis")
            catalysts, risks, mitigations = self._parse_batch_analysis_data(analysis_data)
            catalysts, risks, mitigations = self._ground_insights(
                catalysts, risks, mitigations, articles
            )

            self._log("info", f"{indent}✅ Batch {batch_num} complete: {len(catalysts)}🚀 {len(risks)}⚠️ {len(mitigations)}🛡️")
            self._log("info", f"{indent}💰 Batch cost: ${cost:.4f} USD | Running total: ${self.total_llm_cost:.4f} USD")
            if catalysts:
                top = max(catalysts, key=lambda x: x.confidence)
                self._log("info", f"   🚀 Top Catalyst: {top.type.title()} ({top.confidence:.1%}) - {top.description[:60]}...")
            return catalysts, risks, mitigations

        except Exception as e:
            return await self._handle_batch_error_async(e, articles, batch_num, depth)

    async def _handle_batch_error_async(
        self, e: Exception, articles: List[Dict], batch_num, depth: int
    ) -> Tuple[List[Catalyst], List[Risk], List[Mitigation]]:
        """Async analogue of ``_handle_batch_error`` — awaits sub-batch retries."""
        batch_size = len(articles)
        indent = "  " * depth
        if self._is_rate_limit_error(str(e)):
            self._log("warning", f"{indent}⚠️  Batch {batch_num} failed due to rate limit/token limit: {e}")
            if batch_size == 1:
                if articles[0].get('already_truncated', False):
                    self._log("error", f"{indent}❌ Article was already truncated but still failed - giving up")
                    return [], [], []
                # Truncation path reuses the (sync, CPU-only) truncator, then re-runs async.
                self._log("warning", f"{indent}📄 Single article too large, truncating content...")
                article = articles[0]
                truncated = self._truncate_article_for_retry(article)
                if truncated is None:
                    return [], [], []
                return await self._analyze_article_batch_async([truncated], batch_num, depth)

            mid_point = batch_size // 2
            self._log("info", f"{indent}✂️  Splitting batch {batch_num} into 2 sub-batches: [{mid_point}] + [{batch_size - mid_point}] articles")
            # Sub-batches are independent → run them concurrently too.
            res1, res2 = await asyncio.gather(
                self._analyze_article_batch_async(articles[:mid_point], f"{batch_num}a", depth + 1),
                self._analyze_article_batch_async(articles[mid_point:], f"{batch_num}b", depth + 1),
            )
            all_catalysts = res1[0] + res2[0]
            all_risks = res1[1] + res2[1]
            all_mitigations = res1[2] + res2[2]
            self._log("info", f"{indent}✅ Batch {batch_num} complete (split after rate limit): {len(all_catalysts)}🚀 {len(all_risks)}⚠️ {len(all_mitigations)}🛡️")
            return all_catalysts, all_risks, all_mitigations

        self._log("error", f"{indent}❌ Batch {batch_num} analysis failed with non-rate-limit error: {e}")
        return [], [], []

    def _truncate_article_for_retry(self, article: Dict) -> Optional[Dict]:
        """
        Return a token-truncated copy of an oversized article (flagged to prevent
        re-truncation), or None if it cannot be salvaged. Pure/CPU-only so it is
        shared by the sync (`_analyze_truncated_article`) and async retry paths.
        """
        available_tokens = self.max_tokens_per_request - self.prompt_overhead_tokens - 500
        text_tokens = self.encoding.encode(article['text'])
        if len(text_tokens) <= available_tokens:
            return article  # Fits after all.
        truncated_text = self.encoding.decode(text_tokens[:available_tokens])
        out = article.copy()
        out['text'] = truncated_text
        out['truncated'] = True
        out['original_word_count'] = len(article['text'].split())
        out['already_truncated'] = True
        self._log("warning", f"✂️  Truncated oversized article to ~{available_tokens:,} tokens for retry")
        return out

    def _determine_overall_sentiment(self, catalysts: List[Catalyst], risks: List[Risk]) -> str:
        """Determine sentiment from unique-theme intensity, not raw item count.

        Parallel batches can emit different counts of otherwise similar items.
        Averages prevent article volume from becoming sentiment, while a modest
        severity adjustment preserves genuinely serious risks. A 15% dead band
        avoids a false directional label on mixed evidence.
        """
        if not catalysts and not risks:
            return "neutral"
        if catalysts and not risks:
            return "bullish"
        if risks and not catalysts:
            return "bearish"

        catalyst_score = sum(c.confidence for c in catalysts) / len(catalysts)
        severity_weights = {
            "low": 0.75, "medium": 1.0, "high": 1.25, "critical": 1.5,
        }
        risk_score = sum(
            r.confidence * severity_weights.get(r.severity, 1.0) for r in risks
        ) / len(risks)

        if catalyst_score > risk_score * 1.15:
            return "bullish"
        if risk_score > catalyst_score * 1.15:
            return "bearish"
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
            return 0.0
        
        all_confidences = []
        all_confidences.extend(c.confidence for c in catalysts)
        all_confidences.extend(r.confidence for r in risks)
        all_confidences.extend(m.confidence for m in mitigations)
        
        return sum(all_confidences) / len(all_confidences) if all_confidences else 0.5

    def save_structured_data(self, catalysts: List[Catalyst], risks: List[Risk], 
                           mitigations: List[Mitigation], analysis_summary: AnalysisSummary,
                           output_file: pathlib.Path,
                           freshness: Optional[Dict[str, object]] = None):
        """Save structured data as JSON for further analysis."""
        data = {
            "timestamp": datetime.now().isoformat(),
            "ticker": self.ticker,
            "analysis_method": "batch_llm",
            "analysis_summary": asdict(analysis_summary),
            "freshness": freshness if freshness is not None else self.last_freshness,
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
