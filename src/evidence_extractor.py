#!/usr/bin/env python3
"""
evidence_extractor.py - Evidence Pack Builder

Extracts and structures evidence from screening data for LLM citation.
Each piece of evidence gets an ID, date, source, and relevance score.
"""

from typing import Dict, Any, List
from datetime import datetime
from urllib.parse import urlparse


class EvidenceExtractor:
    """Extracts structured evidence from screening data for LLM citation."""

    @staticmethod
    def _truncate_text(value: Any, limit: int) -> str:
        text = str(value or "").strip()
        if len(text) <= limit:
            return text
        shortened = text[:limit + 1].rsplit(" ", 1)[0].rstrip(" ,;:-")
        return (shortened or text[:limit].rstrip()) + "…"

    @staticmethod
    def _is_citable_url(value: Any) -> bool:
        """Require a real external source behind every citation identifier."""
        try:
            parsed = urlparse(str(value or "").strip())
        except ValueError:
            return False
        return parsed.scheme in {"http", "https"} and bool(parsed.hostname)
    
    def build_evidence_pack(
        self,
        screening_data: Dict[str, Any],
        max_catalysts: int = 8,
        max_risks: int = 8
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
            key=self._evidence_priority,
            reverse=True
        )[:max_catalysts]
        
        for cat in sorted_catalysts:
            # Extract source information
            source_articles = cat.get('source_articles', [])
            source_title = source_articles[0].get('title', 'Unknown') if source_articles else 'Screening Analysis'
            source_url = source_articles[0].get('url', '') if source_articles else ''
            source_snippet = source_articles[0].get('snippet', '') if source_articles else ''
            # A model-produced catalyst without a source URL is context, not
            # evidence. Giving it an E-number lets later prose cite one model
            # interpretation as proof of another.
            if not self._is_citable_url(source_url):
                continue
            evidence_id = f"E{evidence_counter}"
            evidence_counter += 1
            
            # Extract quote if available
            quotes = cat.get('direct_quotes', [])
            snippet = quotes[0].get('quote', '') if quotes else source_snippet
            
            # The evidence date is the source's publication date, never the
            # day on which our model happened to read it.
            date_str = self._extract_date(
                source_articles[0].get('publish_date', '') if source_articles else ''
            )
            
            # Assess source quality (primary > tier-1 > tier-2 > syndication)
            source_quality = self._assess_source_quality(source_url, source_title)
            
            evidence_list.append({
                "id": evidence_id,
                "type": f"catalyst_{cat.get('type', 'other')}",
                "date": date_str,
                "source": self._publication_name(source_url),
                "source_article_title": source_title,
                "source_quality": source_quality,
                "title": self._truncate_text(cat.get('description'), 240),
                "url": source_url,
                "snippet": self._truncate_text(snippet, 500),
                "relevance": cat.get('confidence', 0.5),
                "stance": "positive",
                "timeline": cat.get('timeline', 'medium-term'),
                # LLM reasoning is interpretation, not source evidence.  It is
                # intentionally excluded from the citation pack so a later
                # explainer cannot cite one model-generated sentence as proof
                # for another.
            })
        
        # Extract risk evidence
        risks = screening_data.get('risks', [])
        sorted_risks = sorted(
            risks,
            key=lambda x: self._risk_priority(x) + self._source_quality_weight(x),
            reverse=True
        )[:max_risks]
        
        for risk in sorted_risks:
            # Extract source information
            source_articles = risk.get('source_articles', [])
            source_title = source_articles[0].get('title', 'Unknown') if source_articles else 'Risk Analysis'
            source_url = source_articles[0].get('url', '') if source_articles else ''
            source_snippet = source_articles[0].get('snippet', '') if source_articles else ''
            if not self._is_citable_url(source_url):
                continue
            evidence_id = f"E{evidence_counter}"
            evidence_counter += 1
            
            # Extract quote if available
            quotes = risk.get('direct_quotes', [])
            snippet = quotes[0].get('quote', '') if quotes else source_snippet
            
            date_str = self._extract_date(
                source_articles[0].get('publish_date', '') if source_articles else ''
            )
            source_quality = self._assess_source_quality(source_url, source_title)
            
            evidence_list.append({
                "id": evidence_id,
                "type": f"risk_{risk.get('type', 'other')}",
                "date": date_str,
                "source": self._publication_name(source_url),
                "source_article_title": source_title,
                "source_quality": source_quality,
                "title": self._truncate_text(risk.get('description'), 240),
                "url": source_url,
                "snippet": self._truncate_text(snippet, 500),
                "relevance": risk.get('confidence', 0.5),
                "stance": "negative",
                "severity": risk.get('severity', 'medium'),
                "likelihood": risk.get('likelihood', 'possible'),
                # See catalyst evidence above: only the source excerpt is
                # admissible citation support.
            })
        
        # Aggregate sentiment remains report metadata. It deliberately has no
        # citation ID: it is computed from the source evidence above and is not
        # itself an independent publication that can substantiate a claim.
        return {
            "evidence": evidence_list
        }
    
    def _extract_date(self, timestamp_str: str) -> str:
        """Extract date from timestamp string."""
        try:
            if timestamp_str:
                dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                return dt.strftime('%Y-%m-%d')
        except (TypeError, ValueError, OverflowError):
            pass
        
        return "date unavailable"
    
    def _assess_source_quality(self, url: str, title: str) -> str:
        """
        Assess source quality based on URL and title.
        
        Returns: 'primary', 'tier-1', 'tier-2', or 'syndication'
        """
        url_lower = (url or '').lower()
        try:
            host = (urlparse(url_lower).hostname or '').removeprefix('www.')
        except ValueError:
            host = ''

        def on_domain(domain: str) -> bool:
            return host == domain or host.endswith('.' + domain)
        
        # Primary sources (company filings, official sources)
        primary_domains = {
            'sec.gov', 'investor.apple.com', 'apple.com', 'doj.gov',
            'ec.europa.eu', 'ftc.gov',
        }
        if any(on_domain(domain) for domain in primary_domains):
            return 'primary'
        
        # Tier-1 outlets (authoritative financial media)
        tier1_outlets = [
            'wsj.com', 'bloomberg.com', 'reuters.com', 'ft.com',
            'economist.com', 'apnews.com', 'nytimes.com'
        ]
        if any(on_domain(outlet) for outlet in tier1_outlets):
            return 'tier-1'
        
        # Tier-2 outlets (reputable business media)
        tier2_outlets = [
            'cnbc.com', 'forbes.com', 'investopedia.com', 'seekingalpha.com',
            'marketwatch.com', 'barrons.com', 'businessinsider.com'
        ]
        if any(on_domain(outlet) for outlet in tier2_outlets):
            return 'tier-2'
        
        # Syndication / aggregators (lower quality)
        syndication_indicators = [
            'financialcontent.com', 'tradingview.com/news', 'zacks.com',
            'invezz.com', 'finance.yahoo.com', 'yahoo.com', 'benzinga.com'
        ]
        if any(on_domain(ind.split('/')[0]) for ind in syndication_indicators):
            return 'syndication'
        
        return 'unrated'

    @staticmethod
    def _publication_name(url: str) -> str:
        try:
            host = (urlparse(str(url or "")).hostname or "").removeprefix("www.")
        except ValueError:
            host = ""
        return host or "publisher unavailable"

    def _source_quality_weight(self, insight: Dict[str, Any]) -> float:
        sources = insight.get('source_articles') or []
        first = sources[0] if sources and isinstance(sources[0], dict) else {}
        quality = self._assess_source_quality(
            first.get('url', ''), first.get('title', '')
        )
        return {
            'primary': 0.40, 'tier-1': 0.30, 'tier-2': 0.18,
            'syndication': 0.05, 'unrated': 0.0,
        }.get(quality, 0.0)

    def _evidence_priority(self, insight: Dict[str, Any]) -> float:
        return float(insight.get('confidence') or 0) + self._source_quality_weight(insight)
    
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
