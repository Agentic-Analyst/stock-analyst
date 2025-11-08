#!/usr/bin/env python3
"""
news_summary_agent.py - News Analysis Summary Generator

Generates a comprehensive summary of news analysis results without requiring
a full report. This agent can be used standalone or as part of a larger workflow.

Key Features:
1. Loads news screening data from JSON file
2. Extracts catalysts, risks, and mitigations
3. Uses LLM to generate professional narrative summary
4. Can be used by supervisor to provide quick news insights

Data Sources:
- screening_json: screening_data.json (news catalysts, risks, mitigations)

Output: Markdown-formatted news analysis summary
"""

from __future__ import annotations
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
import json

from llms.config import get_llm
from logger import StockAnalystLogger


def load_screening_json(json_path: Path) -> Dict[str, Any]:
    """Load screening data JSON."""
    with open(json_path, 'r') as f:
        return json.load(f)


def extract_news_analysis(screening_data: Dict[str, Any]) -> Dict[str, Any]:
    """Extract news screening analysis."""
    return {
        'summary': screening_data.get('analysis_summary', {}),
        'catalysts': screening_data.get('catalysts', []),
        'risks': screening_data.get('risks', []),
        'mitigations': screening_data.get('mitigations', []),
        'screening_method': screening_data.get('analysis_method', 'LLM-based screening'),
    }


def generate_news_summary(
    screening_json_path: Path,
    ticker: str,
    company_name: str,
    logger: Optional[StockAnalystLogger] = None
) -> Tuple[str, float]:
    """
    Generate comprehensive news analysis summary.
    
    Args:
        screening_json_path: Path to screening_data.json
        ticker: Stock ticker symbol
        company_name: Company name
        logger: Optional logger instance
        
    Returns:
        Tuple of (summary_markdown, llm_cost)
    """
    if logger:
        logger.info("="*70)
        logger.info("Generating News Analysis Summary")
        logger.info("="*70)
    
    # Load data
    if logger:
        logger.info("Loading news screening data...")
    
    screening_data = load_screening_json(screening_json_path)
    news = extract_news_analysis(screening_data)
    
    if logger:
        logger.info("✅ Data loaded successfully")
        logger.info(f"   Articles Analyzed: {news['summary'].get('articles_analyzed', 0)}")
        logger.info(f"   Catalysts: {len(news['catalysts'])}")
        logger.info(f"   Risks: {len(news['risks'])}")
        logger.info(f"   Mitigations: {len(news['mitigations'])}")
    
    # Build structured tables for LLM
    
    # Catalysts Table
    catalysts_table = "| Type | Description | Confidence | Timeline | Impact |\n"
    catalysts_table += "|------|-------------|------------|----------|--------|\n"
    for c in news['catalysts']:
        impact = c.get('potential_impact', 'N/A')[:60]
        catalysts_table += f"| {c.get('type', 'N/A').title()} | {c.get('description', 'N/A')} | {c.get('confidence', 0):.0%} | {c.get('timeline', 'N/A').title()} | {impact}... |\n"
    
    # Risks Table
    risks_table = "| Type | Description | Severity | Likelihood | Impact |\n"
    risks_table += "|------|-------------|----------|------------|--------|\n"
    for r in news['risks']:
        impact = r.get('potential_impact', 'N/A')[:60]
        risks_table += f"| {r.get('type', 'N/A').title()} | {r.get('description', 'N/A')} | {r.get('severity', 'N/A').title()} | {r.get('likelihood', 'N/A').title()} | {impact}... |\n"
    
    # Mitigations Table
    mitigations_table = "| Risk Addressed | Strategy | Effectiveness | Confidence |\n"
    mitigations_table += "|----------------|----------|---------------|------------|\n"
    for m in news['mitigations']:
        risk = m.get('risk_addressed', 'N/A')[:40]
        strategy = m.get('strategy', 'N/A')[:50]
        mitigations_table += f"| {risk}... | {strategy}... | {m.get('effectiveness', 'N/A').title()} | {m.get('confidence', 0):.0%} |\n"
    
    # Generate LLM summary
    if logger:
        logger.info("Generating narrative summary with LLM...")
    
    prompt = f"""You are a professional financial analyst. Generate a comprehensive but concise news analysis summary for {company_name} ({ticker}).

**Analysis Overview:**
- Articles Analyzed: {news['summary'].get('articles_analyzed', 0)}
- Overall Sentiment: {news['summary'].get('overall_sentiment', 'neutral').upper()}
- Confidence Score: {news['summary'].get('confidence_score', 0):.0%}
- Key Themes: {', '.join(news['summary'].get('key_themes', []))}

**Catalysts Identified ({len(news['catalysts'])}):**
{catalysts_table}

**Risks Identified ({len(news['risks'])}):**
{risks_table}

**Risk Mitigations Identified ({len(news['mitigations'])}):**
{mitigations_table}

**Instructions:**
1. Start with a 2-sentence overview of the overall news sentiment and key themes
2. Summarize the most significant catalysts (top 3-5) and their potential impact
3. Discuss the major risks (top 3-5) and their severity/likelihood
4. Explain how the company is mitigating these risks
5. Provide a balanced conclusion on the news outlook (bullish/bearish/mixed)

Be professional, balanced, and data-driven. Reference specific catalysts and risks by their descriptions. Keep it under 500 words.

Format your response in clear sections with markdown headers (###).
"""
    
    llm = get_llm()
    messages = [{"role": "user", "content": prompt}]
    response, cost = llm(messages, temperature=0.5)
    
    if logger:
        logger.info(f"✅ Summary generated (cost: ${cost:.4f})")
    
    # Build detailed catalyst list with evidence
    detailed_catalysts = []
    for i, c in enumerate(news['catalysts'], 1):
        detail = f"**{i}. {c.get('description', 'N/A')}**\n"
        detail += f"- **Type:** {c.get('type', 'N/A').title()}\n"
        detail += f"- **Timeline:** {c.get('timeline', 'N/A').title()}\n"
        detail += f"- **Confidence:** {c.get('confidence', 0):.0%}\n"
        detail += f"- **Potential Impact:** {c.get('potential_impact', 'N/A')}\n"
        
        if c.get('supporting_evidence'):
            detail += f"- **Supporting Evidence:**\n"
            for evidence in c.get('supporting_evidence', [])[:3]:  # Top 3
                detail += f"  - {evidence}\n"
        
        detailed_catalysts.append(detail)
    
    # Build detailed risk list with evidence
    detailed_risks = []
    for i, r in enumerate(news['risks'], 1):
        detail = f"**{i}. {r.get('description', 'N/A')}**\n"
        detail += f"- **Type:** {r.get('type', 'N/A').title()}\n"
        detail += f"- **Severity:** {r.get('severity', 'N/A').title()}\n"
        detail += f"- **Likelihood:** {r.get('likelihood', 'N/A').title()}\n"
        detail += f"- **Confidence:** {r.get('confidence', 0):.0%}\n"
        detail += f"- **Potential Impact:** {r.get('potential_impact', 'N/A')}\n"
        
        if r.get('supporting_evidence'):
            detail += f"- **Supporting Evidence:**\n"
            for evidence in r.get('supporting_evidence', [])[:3]:
                detail += f"  - {evidence}\n"
        
        detailed_risks.append(detail)
    
    # Build detailed mitigation list
    detailed_mitigations = []
    for i, m in enumerate(news['mitigations'], 1):
        detail = f"**{i}. {m.get('strategy', 'N/A')}**\n"
        detail += f"- **Risk Addressed:** {m.get('risk_addressed', 'N/A')}\n"
        detail += f"- **Effectiveness:** {m.get('effectiveness', 'N/A').title()}\n"
        detail += f"- **Confidence:** {m.get('confidence', 0):.0%}\n"
        detail += f"- **Company Action:** {m.get('company_action', 'N/A')}\n"
        detail += f"- **Timeline:** {m.get('implementation_timeline', 'N/A')}\n"
        
        if m.get('supporting_evidence'):
            detail += f"- **Supporting Evidence:**\n"
            for evidence in m.get('supporting_evidence', [])[:3]:
                detail += f"  - {evidence}\n"
        
        detailed_mitigations.append(detail)
    
    # Build final summary with both narrative and detailed evidence
    summary = f"""# News Analysis Summary: {company_name} ({ticker})

**Generated:** {datetime.now().strftime('%B %d, %Y')}

---

## Quick Overview

| Metric | Value |
|--------|-------|
| Articles Analyzed | {news['summary'].get('articles_analyzed', 0)} |
| Overall Sentiment | {news['summary'].get('overall_sentiment', 'neutral').upper()} |
| Confidence Score | {news['summary'].get('confidence_score', 0):.0%} |
| Catalysts Identified | {len(news['catalysts'])} |
| Risks Identified | {len(news['risks'])} |
| Mitigations Identified | {len(news['mitigations'])} |

**Key Themes:** {', '.join(news['summary'].get('key_themes', []))}

---

{response}

---

## Detailed Evidence

### Catalysts - Full Details

{chr(10).join(detailed_catalysts) if detailed_catalysts else '*No catalysts identified.*'}

### Risks - Full Details

{chr(10).join(detailed_risks) if detailed_risks else '*No risks identified.*'}

### Risk Mitigations - Full Details

{chr(10).join(detailed_mitigations) if detailed_mitigations else '*No mitigations identified.*'}

---

## Summary Tables

### All Catalysts
{catalysts_table}

### All Risks
{risks_table}

### All Mitigations
{mitigations_table}

---

*This summary is based on news screening analysis. For complete investment analysis including financial model and recommendation, see the full report.*
"""
    
    if logger:
        logger.info("="*70)
        logger.info("✅ NEWS SUMMARY GENERATION COMPLETE")
        logger.info("="*70)
    
    return summary, cost


def generate_and_save_news_summary(
    analysis_path: Path,
    ticker: str,
    company_name: Optional[str] = None,
    logger: Optional[StockAnalystLogger] = None
) -> Tuple[str, Path, float]:
    """
    Main entry point: Generate and save news summary.
    
    Args:
        analysis_path: Path to analysis folder (e.g., data/email/ticker/timestamp/)
        ticker: Stock ticker
        company_name: Company name (optional, will load from financial data if not provided)
        logger: Optional logger
        
    Returns:
        Tuple of (summary_content, summary_file_path, llm_cost)
    """
    # Define paths
    screening_path = analysis_path / "screened" / "screening_data.json"
    summary_output_dir = analysis_path / "summaries"
    
    # Validate paths
    if not screening_path.exists():
        raise FileNotFoundError(f"Screening data not found: {screening_path}")
    
    # Get company name if not provided
    if not company_name:
        financials_path = analysis_path / "financials" / "financials_annual_modeling_latest.json"
        if financials_path.exists():
            with open(financials_path, 'r') as f:
                financial_data = json.load(f)
                company_name = financial_data.get('company_data', {}).get('basic_info', {}).get('long_name', ticker)
        else:
            company_name = ticker
    
    # Generate summary
    summary, cost = generate_news_summary(
        screening_json_path=screening_path,
        ticker=ticker,
        company_name=company_name,
        logger=logger
    )
    
    # Save summary
    summary_output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = summary_output_dir / f"{ticker}_news_summary.md"
    
    with open(summary_path, 'w') as f:
        f.write(summary)
    
    if logger:
        logger.info(f"✅ Summary saved to: {summary_path}")
        logger.info(f"   • File size: {summary_path.stat().st_size:,} bytes")
    
    return summary, summary_path, cost

