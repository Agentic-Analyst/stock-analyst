#!/usr/bin/env python3
"""
evidence_extractor.py - Evidence Pack Builder

Extracts and structures evidence from screening data for LLM citation.
Each piece of evidence gets an ID, date, source, and relevance score.
"""

from typing import Dict, Any, List
from datetime import datetime


class EvidenceExtractor:
    """Extracts structured evidence from screening data for LLM citation."""
    
    def build_evidence_pack(
        self,
        screening_data: Dict[str, Any],
        max_catalysts: int = 6,
        max_risks: int = 5
    ) -> Dict[str, Any]:
        """
        Build evidence pack from screening data.
        
        Returns:
            Dictionary with 'evidence' list containing structured evidence items
        """
        evidence_list = []
        evidence_counter = 1
        
        # Extract catalyst evidence
        catalysts = screening_data.get('catalysts', [])
        sorted_catalysts = sorted(
            catalysts,
            key=lambda x: x.get('confidence', 0),
            reverse=True
        )[:max_catalysts]
        
        for cat in sorted_catalysts:
            # Primary catalyst evidence
            evidence_id = f"E{evidence_counter}"
            evidence_counter += 1
            
            # Extract source information
            source_articles = cat.get('source_articles', [])
            source_title = source_articles[0].get('title', 'Unknown') if source_articles else 'Screening Analysis'
            source_url = source_articles[0].get('url', '') if source_articles else ''
            
            # Extract quote if available
            quotes = cat.get('direct_quotes', [])
            snippet = quotes[0].get('quote', cat.get('description', '')) if quotes else cat.get('description', '')
            
            # Determine date - try to extract from article URL or use analysis date
            # NOTE: Ideally extract from article metadata; for now use analysis timestamp
            # TODO: Extract actual publish dates from scraped article data
            date_str = self._extract_date(screening_data.get('timestamp', ''))
            
            # Assess source quality (primary > tier-1 > tier-2 > syndication)
            source_quality = self._assess_source_quality(source_url, source_title)
            
            evidence_list.append({
                "id": evidence_id,
                "type": f"catalyst_{cat.get('type', 'other')}",
                "date": date_str,
                "source": source_title,
                "source_quality": source_quality,
                "title": cat.get('description', '')[:100],  # Truncate long descriptions
                "url": source_url,
                "snippet": snippet[:500],  # Limit snippet length
                "relevance": cat.get('confidence', 0.5),
                "stance": "positive",
                "timeline": cat.get('timeline', 'medium-term'),
                "reasoning": cat.get('reasoning', cat.get('llm_reasoning', ''))
            })
        
        # Extract risk evidence
        risks = screening_data.get('risks', [])
        sorted_risks = sorted(
            risks,
            key=lambda x: self._risk_priority(x),
            reverse=True
        )[:max_risks]
        
        for risk in sorted_risks:
            evidence_id = f"E{evidence_counter}"
            evidence_counter += 1
            
            # Extract source information
            source_articles = risk.get('source_articles', [])
            source_title = source_articles[0].get('title', 'Unknown') if source_articles else 'Risk Analysis'
            source_url = source_articles[0].get('url', '') if source_articles else ''
            
            # Extract quote if available
            quotes = risk.get('direct_quotes', [])
            snippet = quotes[0].get('quote', risk.get('description', '')) if quotes else risk.get('description', '')
            
            date_str = self._extract_date(screening_data.get('timestamp', ''))
            source_quality = self._assess_source_quality(source_url, source_title)
            
            evidence_list.append({
                "id": evidence_id,
                "type": f"risk_{risk.get('type', 'other')}",
                "date": date_str,
                "source": source_title,
                "source_quality": source_quality,
                "title": risk.get('description', '')[:100],
                "url": source_url,
                "snippet": snippet[:500],
                "relevance": risk.get('confidence', 0.5),
                "stance": "negative",
                "severity": risk.get('severity', 'medium'),
                "likelihood": risk.get('likelihood', 'possible'),
                "reasoning": risk.get('reasoning', risk.get('llm_reasoning', ''))
            })
        
        # Add summary evidence
        summary = screening_data.get('analysis_summary', {})
        if summary:
            evidence_id = f"E{evidence_counter}"
            evidence_counter += 1
            
            date_str = self._extract_date(screening_data.get('timestamp', ''))
            
            evidence_list.append({
                "id": evidence_id,
                "type": "market_analysis",
                "date": date_str,
                "source": "Comprehensive Market Analysis",
                "title": f"Overall Sentiment: {summary.get('overall_sentiment', 'neutral').upper()}",
                "url": "",
                "snippet": f"Analysis of {summary.get('articles_analyzed', 0)} articles. Key themes: {', '.join(summary.get('key_themes', [])[:3])}. Total catalysts: {summary.get('total_catalysts', 0)}, Total risks: {summary.get('total_risks', 0)}.",
                "relevance": summary.get('confidence_score', 0.5),
                "stance": summary.get('overall_sentiment', 'neutral'),
                "reasoning": f"Comprehensive analysis based on {summary.get('articles_analyzed', 0)} sources"
            })
        
        return {
            "evidence": evidence_list
        }
    
    def _extract_date(self, timestamp_str: str) -> str:
        """Extract date from timestamp string."""
        try:
            if timestamp_str:
                dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                return dt.strftime('%Y-%m-%d')
        except:
            pass
        
        # Default to today
        return datetime.now().strftime('%Y-%m-%d')
    
    def _assess_source_quality(self, url: str, title: str) -> str:
        """
        Assess source quality based on URL and title.
        
        Returns: 'primary', 'tier-1', 'tier-2', or 'syndication'
        """
        url_lower = url.lower()
        
        # Primary sources (company filings, official sources)
        primary_indicators = [
            'sec.gov', '10-q', '10-k', 'earnings', 'investor.apple.com',
            'apple.com/newsroom', 'doj.gov', 'ec.europa.eu', 'ftc.gov'
        ]
        if any(ind in url_lower or ind in title.lower() for ind in primary_indicators):
            return 'primary'
        
        # Tier-1 outlets (authoritative financial media)
        tier1_outlets = [
            'wsj.com', 'bloomberg.com', 'reuters.com', 'ft.com',
            'economist.com', 'apnews.com', 'nytimes.com/business'
        ]
        if any(outlet in url_lower for outlet in tier1_outlets):
            return 'tier-1'
        
        # Tier-2 outlets (reputable business media)
        tier2_outlets = [
            'cnbc.com', 'forbes.com', 'investopedia.com', 'seekingalpha.com',
            'marketwatch.com', 'barrons.com', 'businessinsider.com'
        ]
        if any(outlet in url_lower for outlet in tier2_outlets):
            return 'tier-2'
        
        # Syndication / aggregators (lower quality)
        syndication_indicators = [
            'financialcontent.com', 'tradingview.com/news', 'zacks.com',
            'invezz.com', 'yahoo.com/finance', 'benzinga.com'
        ]
        if any(ind in url_lower for ind in syndication_indicators):
            return 'syndication'
        
        # Default to tier-2 if unknown
        return 'tier-2'
    
    def _risk_priority(self, risk: Dict[str, Any]) -> float:
        """Calculate risk priority for sorting."""
        severity_map = {'low': 0.25, 'medium': 0.5, 'high': 0.75, 'very_high': 0.9}
        likelihood_map = {'unlikely': 0.2, 'possible': 0.4, 'likely': 0.6, 'very_likely': 0.8, 'high': 0.7, 'medium': 0.5}
        
        severity = risk.get('severity', 'medium')
        likelihood = risk.get('likelihood', 'possible')
        confidence = risk.get('confidence', 0.5)
        
        severity_val = severity_map.get(severity.lower() if isinstance(severity, str) else 'medium', 0.5)
        likelihood_val = likelihood_map.get(likelihood.lower() if isinstance(likelihood, str) else 'possible', 0.5)
        
        return severity_val * likelihood_val * confidence
    
    def format_catalyst_for_prompt(self, catalyst: Dict[str, Any], evidence_id: str) -> str:
        """Format catalyst with evidence ID for prompt."""
        desc = catalyst.get('description', '')
        timeline = catalyst.get('timeline', '')
        confidence = catalyst.get('confidence', 0) * 100
        
        return f"{desc} (Confidence: {confidence:.0f}%, Timeline: {timeline}) [{evidence_id}]"
    
    def format_risk_for_prompt(self, risk: Dict[str, Any], evidence_id: str) -> str:
        """Format risk with evidence ID for prompt."""
        desc = risk.get('description', '')
        severity = risk.get('severity', 'medium')
        likelihood = risk.get('likelihood', 'possible')
        
        return f"{desc} (Severity: {severity}, Likelihood: {likelihood}) [{evidence_id}]"
