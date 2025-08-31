#!/usr/bin/env python3
"""
screener.py - Unified LLM-powered stock screening and analysis of filtered articles.

This module uses a single comprehensive AI prompt to analyze news articles for investment
insights including growth catalysts, risks, and mitigation strategies in one efficient call.

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

# Conditionally import LLM functionality
try:
    from llms import gpt_4o_mini
    LLM_AVAILABLE = True
except ImportError:
    LLM_AVAILABLE = False
    def gpt_4o_mini(*args, **kwargs):
        raise ImportError("LLM functionality not available. Please check llms.py")

PROMPTS_ROOT = pathlib.Path("prompts")

def load_prompt(prompt_name: str) -> str:
    """Load a prompt template from the prompts directory."""
    prompt_file = PROMPTS_ROOT / f"{prompt_name}.md"
    if not prompt_file.exists():
        raise FileNotFoundError(f"Prompt file not found: {prompt_file}")
    return prompt_file.read_text(encoding="utf-8")

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
        self.filtered_dir = self.company_dir / "filtered"
        
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
    
    def _estimate_prompt_tokens(self, system_prompt: str, user_prompt_template: str) -> int:
        """Estimate total tokens for a prompt including system and user messages."""
        # Estimate with placeholder content
        sample_content = "Sample article content for token estimation"
        estimated_user = user_prompt_template.format(
            company_ticker=self.ticker,
            article_content=sample_content
        )
        return self._count_tokens(system_prompt) + self._count_tokens(estimated_user)
    
    def _chunk_article_content(self, article: Dict, target_chunk_size: int) -> List[Dict]:
        """
        Intelligently chunk long articles while preserving context.
        
        Args:
            article: Article dictionary with 'title', 'text', etc.
            target_chunk_size: Target tokens per chunk
            
        Returns:
            List of article chunks with metadata
        """
        title = article.get('title', '')
        content = article.get('text', '')
        
        # If content is short enough, return as single chunk
        total_tokens = self._count_tokens(f"Title: {title}\n\nContent: {content}")
        if total_tokens <= target_chunk_size:
            return [article]
        
        self._log("info", f"Article '{title[:50]}...' has {total_tokens} tokens, chunking into smaller pieces")
        
        # Split content into paragraphs first
        paragraphs = content.split('\n\n')
        
        chunks = []
        current_chunk = f"Title: {title}\n\n"
        current_tokens = self._count_tokens(current_chunk)
        chunk_num = 1
        
        for i, paragraph in enumerate(paragraphs):
            paragraph_tokens = self._count_tokens(paragraph + '\n\n')
            
            # If adding this paragraph would exceed limit, save current chunk
            if current_tokens + paragraph_tokens > target_chunk_size and current_chunk.strip():
                # Add context about chunking
                chunk_footer = f"\n\n[CHUNK {chunk_num} OF ARTICLE: {title[:50]}...]"
                
                chunk_article = article.copy()
                chunk_article.update({
                    'text': current_chunk + chunk_footer,
                    'chunk_number': chunk_num,
                    'total_chunks': 'TBD',  # Will be updated later
                    'is_chunked': True,
                    'original_title': title
                })
                chunks.append(chunk_article)
                
                chunk_num += 1
                current_chunk = f"Title: {title} (Chunk {chunk_num})\n\nPrevious context: [This is part {chunk_num} of a longer article]\n\n"
                current_tokens = self._count_tokens(current_chunk)
            
            # Add paragraph to current chunk
            current_chunk += paragraph + '\n\n'
            current_tokens += paragraph_tokens
        
        # Add final chunk if there's remaining content
        if current_chunk.strip():
            chunk_footer = f"\n\n[FINAL CHUNK {chunk_num} OF ARTICLE: {title[:50]}...]"
            
            chunk_article = article.copy()
            chunk_article.update({
                'text': current_chunk + chunk_footer,
                'chunk_number': chunk_num,
                'total_chunks': chunk_num,
                'is_chunked': True,
                'original_title': title
            })
            chunks.append(chunk_article)
        
        # Update total_chunks for all chunks
        for chunk in chunks:
            chunk['total_chunks'] = len(chunks)
        
        self._log("info", f"Split article into {len(chunks)} chunks")
        return chunks
    
    def _merge_chunk_results(self, chunk_results: List[Tuple[List[Catalyst], List[Risk], List[Mitigation]]], 
                           original_article: Dict) -> Tuple[List[Catalyst], List[Risk], List[Mitigation]]:
        """
        Merge results from multiple chunks of the same article.
        
        Args:
            chunk_results: List of (catalysts, risks, mitigations) tuples from each chunk
            original_article: Original article metadata
            
        Returns:
            Merged (catalysts, risks, mitigations) tuple
        """
        all_catalysts = []
        all_risks = []
        all_mitigations = []
        
        # Combine all results
        for catalysts, risks, mitigations in chunk_results:
            all_catalysts.extend(catalysts)
            all_risks.extend(risks)
            all_mitigations.extend(mitigations)
        
        # Update article references to use original filename
        original_filename = original_article.get('file_name', 'unknown')
        
        for catalyst in all_catalysts:
            catalyst.articles_mentioned = [original_filename]
        
        for risk in all_risks:
            risk.articles_mentioned = [original_filename]
            
        for mitigation in all_mitigations:
            mitigation.articles_mentioned = [original_filename]
        
        # Merge similar insights within the same article
        merged_catalysts = self._merge_similar_catalysts(all_catalysts)
        merged_risks = self._merge_similar_risks(all_risks)
        merged_mitigations = self._merge_similar_mitigations(all_mitigations)
        
        self._log("info", f"Merged chunk results: {len(merged_catalysts)} catalysts, {len(merged_risks)} risks, {len(merged_mitigations)} mitigations")
        
        return merged_catalysts, merged_risks, merged_mitigations

    # ============= LLM-POWERED ANALYSIS METHODS =============
    
    def _create_unified_analysis_prompt(self, article_content: str, company_ticker: str) -> List[Dict]:
        """Create unified prompt for comprehensive catalyst, risk, and mitigation analysis."""
        system_prompt = load_prompt("unified_analysis")
        user_prompt = load_prompt("unified_user").format(
            company_ticker=company_ticker,
            article_content=article_content
        )
        
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
    
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
                themes_str = ", ".join(themes[:2])  # Show top 2 themes
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
            
            # For unified analysis, ensure all required keys exist
            if response_type == "unified_analysis":
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
            
            return parsed
            
        except json.JSONDecodeError as e:
            self._log("warning", f"Failed to parse LLM {response_type} response as JSON: {e}")
            self._log("warning", f"Raw response: {response_text[:200]}...")
            
            # Return appropriate empty structure based on response type
            if response_type == "unified_analysis":
                return {
                    "analysis_summary": {"overall_sentiment": "neutral", "key_themes": [], "confidence_score": 0.5},
                    "catalysts": [],
                    "risks": [],
                    "mitigations": []
                }
            else:
                return {response_type: []}
                
        except Exception as e:
            self._log("warning", f"Error processing LLM {response_type} response: {e}")
            
            # Return appropriate empty structure based on response type
            if response_type == "unified_analysis":
                return {
                    "analysis_summary": {"overall_sentiment": "neutral", "key_themes": [], "confidence_score": 0.5},
                    "catalysts": [],
                    "risks": [],
                    "mitigations": []
                }
            else:
                return {response_type: []}

    def analyze_article_with_llm(self, article: Dict) -> Tuple[List[Catalyst], List[Risk], List[Mitigation]]:
        """
        Analyze a single article using LLM for comprehensive insights.
        Handles long articles by intelligently chunking them.
        """
        if not LLM_AVAILABLE:
            return [], [], []
        
        # Check if article needs chunking
        article_content = f"Title: {article['title']}\n\nContent: {article['text']}"
        
        # Estimate tokens needed for prompts
        unified_prompt_tokens = self._estimate_prompt_tokens(
            load_prompt("unified_analysis"),
            load_prompt("unified_user")
        )

        available_tokens = self.max_tokens_per_request - unified_prompt_tokens - self.prompt_overhead_tokens

        # Check if chunking is needed
        content_tokens = self._count_tokens(article_content)
        
        if content_tokens <= available_tokens:
            # Article fits in one request
            self._log("info", f"Article '{article['file_name'][:50]}...' ({content_tokens} tokens) fits in single request")
            return self._analyze_single_chunk(article)
        else:
            # Article needs chunking
            self._log("info", f"Article '{article['file_name'][:50]}...' ({content_tokens} tokens) requires chunking")
            return self._analyze_chunked_article(article, available_tokens)
    
    def _analyze_single_chunk(self, article: Dict) -> Tuple[List[Catalyst], List[Risk], List[Mitigation]]:
        """Analyze a single article chunk using unified LLM analysis."""
        article_content = f"Title: {article['title']}\n\nContent: {article['text']}"
        catalysts = []
        risks = []
        mitigations = []
        
        try:
            # Single unified LLM call for comprehensive analysis
            article_title = article.get('title', 'Unknown Title')[:50]
            self._log("info", f"🤖 Analyzing '{article_title}...' - Extracting catalysts, risks & mitigations...")
            
            unified_prompt = self._create_unified_analysis_prompt(article_content, self.ticker)
            response, cost = gpt_4o_mini(unified_prompt)
            self.total_llm_cost += cost
            self.llm_call_count += 1
            
            # Parse the unified response
            analysis_data = self._parse_llm_json_response(response, "unified_analysis")
            
            # Display intermediate results to user for real-time feedback
            self._display_intermediate_analysis_results(analysis_data, article['file_name'])
            
            # Extract catalysts
            for cat_data in analysis_data.get("catalysts", []):
                catalyst = Catalyst(
                    type=cat_data.get("type", "unknown").lower(),
                    description=cat_data.get("description", ""),
                    confidence=cat_data.get("confidence", 0.5),
                    supporting_evidence=cat_data.get("supporting_evidence", []),
                    articles_mentioned=[article['file_name']],
                    timeline=cat_data.get("timeline", "medium-term").lower().replace("_", "-"),
                    llm_reasoning=cat_data.get("reasoning", ""),
                    llm_confidence=cat_data.get("confidence", 0.5)
                )
                catalysts.append(catalyst)

            # Extract risks
            for risk_data in analysis_data.get("risks", []):
                risk = Risk(
                    type=risk_data.get("type", "unknown").lower(),
                    description=risk_data.get("description", ""),
                    severity=risk_data.get("severity", "medium").lower(),
                    confidence=risk_data.get("confidence", 0.5),
                    supporting_evidence=risk_data.get("supporting_evidence", []),
                    articles_mentioned=[article['file_name']],
                    potential_impact=risk_data.get("potential_impact", ""),
                    llm_reasoning=risk_data.get("reasoning", ""),
                    llm_confidence=risk_data.get("confidence", 0.5)
                )
                risks.append(risk)
            
            # Extract mitigations
            for mit_data in analysis_data.get("mitigations", []):
                mitigation = Mitigation(
                    risk_addressed=mit_data.get("risk_addressed", ""),
                    strategy=mit_data.get("strategy", ""),
                    confidence=mit_data.get("confidence", 0.5),
                    supporting_evidence=mit_data.get("supporting_evidence", []),
                    articles_mentioned=[article['file_name']],
                    effectiveness=mit_data.get("effectiveness", "medium").lower(),
                    company_action=mit_data.get("company_action", ""),
                    llm_reasoning=mit_data.get("reasoning", ""),
                    llm_confidence=mit_data.get("confidence", 0.5)
                )
                mitigations.append(mitigation)

            self._log("info", f"[llm] Analysis complete: {len(catalysts)} catalysts, {len(risks)} risks, {len(mitigations)} mitigations")
            
            # Show cost info
            self._log("info", f"💰 Article cost: ${cost:.4f} USD | Running total: ${self.total_llm_cost:.4f} USD")

        except Exception as e:
            self._log("error", f"Analysis failed for article {article['file_name']}: {e}")

        return catalysts, risks, mitigations
    
    def _analyze_chunked_article(self, article: Dict, available_tokens: int) -> Tuple[List[Catalyst], List[Risk], List[Mitigation]]:
        """
        Analyze a long article by splitting it into chunks and merging results.
        """
        # Split article into manageable chunks
        chunks = self._chunk_article_content(article, available_tokens)
        
        chunk_results = []
        for i, chunk in enumerate(chunks):
            self._log("info", f"Analyzing chunk {i+1}/{len(chunks)} of article '{article['file_name'][:30]}...'")
            
            # Analyze this chunk
            chunk_catalysts, chunk_risks, chunk_mitigations = self._analyze_single_chunk(chunk)
            chunk_results.append((chunk_catalysts, chunk_risks, chunk_mitigations))
        
        # Merge results from all chunks
        return self._merge_chunk_results(chunk_results, article)

    # ============= END LLM METHODS =============

    def load_filtered_articles(self) -> List[Dict]:
        """Load all filtered articles."""
        if not self.filtered_dir.exists():
            self._log("error", f"[error] Filtered directory {self.filtered_dir} does not exist")
            return []
        
        articles = []
        for md_file in self.filtered_dir.glob("filtered_*.md"):
            try:
                content = md_file.read_text(encoding="utf-8")
                
                # Parse frontmatter
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
                
                articles.append({
                    "file_path": md_file,
                    "file_name": md_file.name,
                    "title": frontmatter.get("title", ""),
                    "source_url": frontmatter.get("source_url", ""),
                    "publish_date": frontmatter.get("publish_date", ""),
                    "text": text_content,
                    "word_count": len(text_content.split()),
                })
            except Exception as e:
                self._log("warn", f"[warn] Could not load {md_file}: {e}")

        return articles

    def analyze_all_articles(self, articles: List[Dict]) -> Tuple[List[Catalyst], List[Risk], List[Mitigation], AnalysisSummary]:
        """
        Analyze all articles using unified LLM analysis and extract catalysts, risks, mitigations, and summary.
        This is the efficient method that uses single LLM calls per article instead of three separate calls.
        """
        if not LLM_AVAILABLE:
            self._log("error", "[error] LLM functionality required for analysis but not available")
            return [], [], [], AnalysisSummary("neutral", [], 0.5)
            
        all_catalysts = []
        all_risks = []
        all_mitigations = []

        self._log("info", f"[info] Performing LLM analysis for {len(articles)} articles (1 call per article)...")
        self._log("info", f"🔄 Starting article-by-article analysis with real-time progress...")

        for i, article in enumerate(articles, 1):
            self._log("info", f"📰 [{i}/{len(articles)}] Processing: {article['file_name'][:50]}...")
            llm_catalysts, llm_risks, llm_mitigations = self.analyze_article_with_llm(article)
            all_catalysts.extend(llm_catalysts)
            all_risks.extend(llm_risks)
            all_mitigations.extend(llm_mitigations)
        
        self._log("info", f"🔄 Merging similar insights across {len(articles)} articles...")
        # Merge similar insights to avoid duplicates
        merged_catalysts = self._merge_similar_catalysts(all_catalysts)
        merged_risks = self._merge_similar_risks(all_risks)
        merged_mitigations = self._merge_similar_mitigations(all_mitigations)
        
        self._log("info", f"✅ Analysis complete! Raw insights: {len(all_catalysts)}🚀 {len(all_risks)}⚠️ {len(all_mitigations)}🛡️")
        self._log("info", f"🔍 After deduplication: {len(merged_catalysts)}🚀 {len(merged_risks)}⚠️ {len(merged_mitigations)}🛡️")
        
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
        
        return themes[:5]  # Limit to top 5 themes
    
    def _calculate_overall_confidence(self, catalysts: List[Catalyst], risks: List[Risk], mitigations: List[Mitigation]) -> float:
        """Calculate overall confidence score based on all insights."""
        if not any([catalysts, risks, mitigations]):
            return 0.5
        
        all_confidences = []
        all_confidences.extend(c.confidence for c in catalysts)
        all_confidences.extend(r.confidence for r in risks)
        all_confidences.extend(m.confidence for m in mitigations)
        
        return sum(all_confidences) / len(all_confidences) if all_confidences else 0.5


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
            supporting_evidence=list(set(all_evidence))[:5],  # Unique evidence, max 5
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
            supporting_evidence=list(set(all_evidence))[:5],
            articles_mentioned=list(set(all_articles)),
            potential_impact=base_risk.potential_impact
        )

    def generate_screening_report(self, catalysts: List[Catalyst], risks: List[Risk], 
                                mitigations: List[Mitigation], analysis_summary: AnalysisSummary, output_file: pathlib.Path):
        """Generate comprehensive screening report with LLM insights and analysis summary."""
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(f"# {self.ticker} LLM Stock Screening Analysis\n\n")
            f.write(f"**Generated on:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"**Analysis Method:** LLM Analysis (3x more efficient)\n")
            f.write(f"**Articles Analyzed:** {analysis_summary.articles_analyzed}\n")
            f.write(f"**LLM Calls:** {self.llm_call_count} (reduced by ~66% vs. legacy method)\n\n")
            
            # Executive Summary with Analysis Summary
            f.write("## 📊 Executive Summary\n\n")
            f.write(f"**Overall Sentiment:** {analysis_summary.overall_sentiment.title()}\n")
            f.write(f"**Analysis Confidence:** {analysis_summary.confidence_score:.1%}\n")
            f.write(f"**Growth Catalysts Identified:** {len(catalysts)}\n")
            f.write(f"**Risks Identified:** {len(risks)}\n")
            f.write(f"**Mitigation Strategies:** {len(mitigations)}\n\n")
            
            if analysis_summary.key_themes:
                f.write("**Key Themes:**\n")
                for theme in analysis_summary.key_themes:
                    f.write(f"- {theme}\n")
                f.write("\n")
            
            # High-level insights
            if catalysts or risks:
                f.write("### Key Insights\n\n")
                
                # Top catalyst by confidence
                if catalysts:
                    top_catalyst = max(catalysts, key=lambda x: x.confidence)
                    f.write(f"**Strongest Growth Driver:** {top_catalyst.type.title()} - {top_catalyst.description[:100]}...\n")
                
                # Highest risk by severity/confidence
                if risks:
                    top_risk = max(risks, key=lambda x: (x.severity == 'critical', x.severity == 'high', x.confidence))
                    f.write(f"**Primary Risk Factor:** {top_risk.type.title()} - {top_risk.description[:100]}...\n")
                
                f.write("\n")
            
            # Growth Catalysts Section  
            f.write("## 🚀 Growth Catalysts\n\n")
            if catalysts:
                for i, catalyst in enumerate(sorted(catalysts, key=lambda x: x.confidence, reverse=True), 1):
                    f.write(f"### Catalyst {i}: {catalyst.type.title()} Opportunity\n\n")
                    f.write(f"**Confidence:** {catalyst.confidence:.1%}")
                    if catalyst.llm_confidence:
                        f.write(f" (LLM: {catalyst.llm_confidence:.1%})")
                    f.write(f"\n**Timeline:** {catalyst.timeline.title()}\n")
                    f.write(f"**Description:** {catalyst.description}\n\n")
                    
                    if catalyst.llm_reasoning:
                        f.write("**AI Analysis:**\n")
                        f.write(f"> {catalyst.llm_reasoning}\n\n")
                    
                    f.write("**Supporting Evidence:**\n")
                    for evidence in catalyst.supporting_evidence:
                        f.write(f"- {evidence}\n")
                    f.write("\n")
                    
                    f.write(f"**Source Articles:** {', '.join(catalyst.articles_mentioned)}\n\n")
                    f.write("---\n\n")
            else:
                f.write("No specific growth catalysts identified in the analyzed articles.\n\n")
            
            # Risks Section
            f.write("## ⚠️ Risk Analysis\n\n")
            if risks:
                for i, risk in enumerate(sorted(risks, key=lambda x: (x.severity == 'critical', x.severity == 'high', x.confidence), reverse=True), 1):
                    severity_emoji = {'critical': '🚨', 'high': '⚠️', 'medium': '⚡', 'low': '💭'}
                    f.write(f"### Risk {i}: {risk.type.title()} Risk {severity_emoji.get(risk.severity, '⚠️')}\n\n")
                    f.write(f"**Severity:** {risk.severity.title()}\n")
                    f.write(f"**Confidence:** {risk.confidence:.1%}")
                    if risk.llm_confidence:
                        f.write(f" (LLM: {risk.llm_confidence:.1%})")
                    f.write(f"\n**Description:** {risk.description}\n")
                    f.write(f"**Potential Impact:** {risk.potential_impact}\n\n")
                    
                    if risk.llm_reasoning:
                        f.write("**AI Analysis:**\n")
                        f.write(f"> {risk.llm_reasoning}\n\n")
                    
                    f.write("**Supporting Evidence:**\n")
                    for evidence in risk.supporting_evidence:
                        f.write(f"- {evidence}\n")
                    f.write("\n")
                    
                    f.write(f"**Source Articles:** {', '.join(risk.articles_mentioned)}\n\n")
                    f.write("---\n\n")
            else:
                f.write("No specific risks identified in the analyzed articles.\n\n")
            
            # Mitigation Strategies Section
            f.write("## 🛡️ Risk Mitigation & Company Response\n\n")
            if mitigations:
                for i, mitigation in enumerate(sorted(mitigations, key=lambda x: x.confidence, reverse=True), 1):
                    effectiveness_emoji = {'high': '✅', 'medium': '⚡', 'low': '❓'}
                    f.write(f"### Mitigation {i}: {effectiveness_emoji.get(mitigation.effectiveness, '⚡')} Strategy\n\n")
                    f.write(f"**Risk Addressed:** {mitigation.risk_addressed[:100]}...\n")
                    f.write(f"**Strategy:** {mitigation.strategy}\n")
                    f.write(f"**Effectiveness:** {mitigation.effectiveness.title()}\n")
                    f.write(f"**Confidence:** {mitigation.confidence:.1%}")
                    if mitigation.llm_confidence:
                        f.write(f" (LLM: {mitigation.llm_confidence:.1%})")
                    f.write("\n\n")
                    
                    if mitigation.company_action:
                        f.write(f"**Company Action:** {mitigation.company_action}\n\n")
                    
                    if mitigation.llm_reasoning:
                        f.write("**AI Analysis:**\n")
                        f.write(f"> {mitigation.llm_reasoning}\n\n")
                    
                    f.write("**Supporting Evidence:**\n")
                    for evidence in mitigation.supporting_evidence:
                        f.write(f"- {evidence}\n")
                    f.write("\n")
                    
                    f.write(f"**Source Articles:** {', '.join(mitigation.articles_mentioned)}\n\n")
                    f.write("---\n\n")
            else:
                f.write("No specific mitigation strategies identified in the analyzed articles.\n\n")
            
            # Investment Thesis Summary
            f.write("## 📈 Investment Thesis Summary\n\n")
            
            # Catalyst summary
            if catalysts:
                f.write("### Growth Potential\n")
                catalyst_types = {}
                for catalyst in catalysts:
                    if catalyst.type not in catalyst_types:
                        catalyst_types[catalyst.type] = []
                    catalyst_types[catalyst.type].append(catalyst)
                
                for cat_type, cat_list in catalyst_types.items():
                    avg_confidence = sum(c.confidence for c in cat_list) / len(cat_list)
                    f.write(f"- **{cat_type.title()} Catalysts:** {len(cat_list)} identified (avg confidence: {avg_confidence:.1%})\n")
                f.write("\n")
            
            # Risk summary
            if risks:
                f.write("### Risk Profile\n")
                risk_by_severity = {}
                for risk in risks:
                    if risk.severity not in risk_by_severity:
                        risk_by_severity[risk.severity] = []
                    risk_by_severity[risk.severity].append(risk)
                
                for severity in ['critical', 'high', 'medium', 'low']:
                    if severity in risk_by_severity:
                        f.write(f"- **{severity.title()} Risks:** {len(risk_by_severity[severity])}\n")
                f.write("\n")
            
            # Overall assessment
            if catalysts and risks:
                catalyst_score = sum(c.confidence for c in catalysts) / len(catalysts)
                risk_score = sum(r.confidence for r in risks) / len(risks)
                net_score = catalyst_score - (risk_score * 0.5)  # Weight risks lower
                
                f.write("### Overall Assessment\n")
                f.write(f"**Catalyst Strength:** {catalyst_score:.1%}\n")
                f.write(f"**Risk Level:** {risk_score:.1%}\n") 
                f.write(f"**Net Outlook Score:** {net_score:.1%}\n\n")
                
                if net_score > 0.6:
                    f.write("**Investment Outlook:** 🟢 Positive - Strong catalysts outweigh identified risks\n")
                elif net_score > 0.3:
                    f.write("**Investment Outlook:** 🟡 Cautiously Positive - Moderate opportunity with manageable risks\n")
                elif net_score > 0:
                    f.write("**Investment Outlook:** 🟡 Neutral - Balanced risk/reward profile\n")
                else:
                    f.write("**Investment Outlook:** 🔴 Cautious - Risks may outweigh near-term catalysts\n")
            
            # Add cost information from LLM usage
            if self.llm_call_count > 0:
                f.write(f"\n## 💰 LLM Analysis Cost Summary\n\n")
                f.write(f"**Total LLM Calls:** {self.llm_call_count}\n")
                f.write(f"**Total Cost:** ${self.total_llm_cost:.6f} USD\n")
                f.write(f"**Average Cost per Call:** ${self.total_llm_cost/self.llm_call_count:.6f} USD\n\n")
            
            f.write(f"\n---\n*Analysis completed using {len(catalysts + risks + mitigations)} insights from filtered articles.*")
            if self.llm_call_count > 0:
                f.write(f" LLM analysis cost: ${self.total_llm_cost:.6f} USD")
            f.write("\n")

    def save_structured_data(self, catalysts: List[Catalyst], risks: List[Risk], 
                           mitigations: List[Mitigation], analysis_summary: AnalysisSummary, output_file: pathlib.Path):
        """Save structured data as JSON for further analysis."""
        data = {
            "timestamp": datetime.now().isoformat(),
            "ticker": self.ticker,
            "analysis_method": "unified_llm",
            "analysis_summary": asdict(analysis_summary),
            "catalysts": [asdict(c) for c in catalysts],
            "risks": [asdict(r) for r in risks],
            "mitigations": [asdict(m) for m in mitigations],
            "llm_stats": {
                "total_calls": self.llm_call_count,
                "total_cost_usd": self.total_llm_cost,
                "efficiency_improvement": "~66% fewer LLM calls vs legacy 3-step analysis"
            }
        }
        
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

def main():
    parser = argparse.ArgumentParser(description="LLM-Powered Stock Screening: Analyze filtered articles for investment insights")
    parser.add_argument("--ticker", required=True, help="Stock ticker, e.g. NVDA")
    parser.add_argument("--min-confidence", type=float, default=0.5, help="Minimum confidence threshold (0.0-1.0)")
    # Report generation is now always enabled for production use
    parser.add_argument("--save-data", action="store_true", help="Save structured data as JSON")
    parser.add_argument("--detailed-analysis", action="store_true", help="Include detailed analysis in output")
    
    args = parser.parse_args()
    
    # Initialize screener
    screener = ArticleScreener(args.ticker)
    
    # Load filtered articles
    screener._log("info", f"Loading filtered articles for {args.ticker}")
    articles = screener.load_filtered_articles()
    
    if not articles:
        screener._log("warning", "No filtered articles found")
        return
    
    screener._log("info", f"Analyzing {len(articles)} filtered articles using LLM-Enhanced analysis")
    
    if not LLM_AVAILABLE:
        screener._log("error", "LLM functionality not available. Please check that llms.py is properly configured.")
        return
    screener._log("info", "🤖 LLM analysis enabled - this will provide deeper insights but take longer and cost API credits")
    screener._log("info", "🔍 Real-time progress tracking enabled - you'll see intermediate results as each article is analyzed")
    
    # Extract insights using efficient single-pass analysis
    screener._log("info", "Analyzing articles for catalysts, risks, and mitigations...")
    all_catalysts, all_risks, all_mitigations, analysis_summary = screener.analyze_all_articles(articles)
    
    # Filter by confidence threshold
    catalysts = [c for c in all_catalysts if c.confidence >= args.min_confidence]
    risks = [r for r in all_risks if r.confidence >= args.min_confidence]
    mitigations = [m for m in all_mitigations if m.confidence >= args.min_confidence]
    
    # Display summary
    screener._log("info", f"Analysis complete:")
    screener._log("info", f"  Overall Sentiment: {analysis_summary.overall_sentiment.title()}")
    screener._log("info", f"  Analysis Confidence: {analysis_summary.confidence_score:.1%}")
    screener._log("info", f"  Growth Catalysts: {len(catalysts)}")
    screener._log("info", f"  Risks Identified: {len(risks)}")
    screener._log("info", f"  Mitigation Strategies: {len(mitigations)}")
    if analysis_summary.key_themes:
        screener._log("info", f"  Key Themes: {', '.join(analysis_summary.key_themes)}")
    
    # Display LLM efficiency improvements
    if screener.llm_call_count > 0:
        screener._log("info", f"  LLM Calls Made: {screener.llm_call_count}")
        screener._log("info", f"  Total LLM Cost: ${screener.total_llm_cost:.6f} USD")
        screener._log("info", f"  Average Cost per Call: ${screener.total_llm_cost/screener.llm_call_count:.6f} USD")
    
    if args.detailed_analysis:
        screener._log("info", "Top Catalysts:")
        for i, catalyst in enumerate(sorted(catalysts, key=lambda x: x.confidence, reverse=True)[:3], 1):
            llm_note = f" (LLM: {catalyst.llm_confidence:.1%})" if catalyst.llm_confidence else ""
            screener._log("info", f"  {i}. [{catalyst.confidence:.1%}{llm_note}] {catalyst.type.title()}: {catalyst.description[:80]}...")
        
        screener._log("info", "Top Risks:")
        for i, risk in enumerate(sorted(risks, key=lambda x: x.confidence, reverse=True)[:3], 1):
            llm_note = f" (LLM: {risk.llm_confidence:.1%})" if risk.llm_confidence else ""
            screener._log("info", f"  {i}. [{risk.confidence:.1%}{llm_note}] {risk.type.title()}: {risk.description[:80]}...")
    
    # Always generate reports in production use
    report_file = screener.analysis_path / "screened" / "screening_report.md"
    screener.generate_screening_report(catalysts, risks, mitigations, analysis_summary, report_file)
    screener._log("info", f"Screening report saved: {report_file}")
    
    if args.save_data:
        data_file = screener.analysis_path / "screened" / "screening_data.json"
        screener.save_structured_data(catalysts, risks, mitigations, analysis_summary, data_file)
        screener._log("info", f"Structured data saved: {data_file}")
    
    # Quick investment outlook
    if catalysts or risks:
        screener._log("info", f"Quick Investment Outlook for {args.ticker}:")
        if catalysts:
            avg_catalyst_confidence = sum(c.confidence for c in catalysts) / len(catalysts)
            screener._log("info", f"  📈 Growth Potential: {avg_catalyst_confidence:.1%} (based on {len(catalysts)} catalysts)")
        
        if risks:
            avg_risk_confidence = sum(r.confidence for r in risks) / len(risks)
            high_severity_risks = len([r for r in risks if r.severity in ['high', 'critical']])
            screener._log("info", f"  ⚠️  Risk Level: {avg_risk_confidence:.1%} (including {high_severity_risks} high-severity risks)")
        
        if mitigations:
            screener._log("info", f"  🛡️  Risk Management: {len(mitigations)} mitigation strategies identified")
        
        # Simple net assessment
        if catalysts and risks:
            catalyst_score = sum(c.confidence for c in catalysts) / len(catalysts)
            risk_score = sum(r.confidence for r in risks) / len(risks)
            net_score = catalyst_score - (risk_score * 0.5)
            
            if net_score > 0.4:
                outlook = "🟢 POSITIVE"
            elif net_score > 0.1:
                outlook = "🟡 CAUTIOUS POSITIVE" 
            elif net_score > -0.1:
                outlook = "🟡 NEUTRAL"
            else:
                outlook = "🔴 CAUTIOUS"
            
            screener._log("info", f"  📊 Net Outlook: {outlook} (Score: {net_score:.2f})")

if __name__ == "__main__":
    main()
