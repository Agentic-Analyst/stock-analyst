#!/usr/bin/env python3
"""report_agent.py

LLM-assisted reporting utilities for price_adjustor.
Generates a professional markdown report that explains the step-by-step
price adjustment and provides analyst suggestions.
"""
from __future__ import annotations
import time
from datetime import datetime
from pathlib import Path
import pathlib
from typing import Dict, Any, List
import json, time
from llms.config import get_llm


def generate_professional_analyst_report(ticker: str, company_name: str, 
                                        financial_model: Dict[str, Any],
                                        screening_results: Dict[str, Any],
                                        price_analysis: Dict[str, Any],
                                        company_data: Dict[str, Any] = None) -> str:
    """Generate a professional financial analyst report using LLM synthesis of all analysis components.
    
    Args:
        ticker: Stock ticker symbol
        company_name: Full company name
        financial_model: Complete financial model results with valuation
        screening_results: Article screening results (catalysts, risks, mitigations)
        price_analysis: Price adjustment analysis with LLM reasoning
        company_data: Optional company context data
    
    Returns:
        Professional analyst report in markdown format
    """
    
    # Extract key financial metrics for context
    valuation_summary = financial_model.get("valuation_summary", {})
    base_price = valuation_summary.get("Implied Price", 0)
    final_price = price_analysis.get("final_price") or price_analysis.get("adjusted_price", base_price)
    
    # Load prompt template from prompts folder

    prompt_path = Path(__file__).parent.parent / "prompts" / "professional_analyst_report.md"
    prompt_template = prompt_path.read_text(encoding='utf-8')
    # Format the prompt with actual data
    formatted_prompt = prompt_template.format(
        ticker=ticker,
        company_name=company_name,
        financial_model=json.dumps(financial_model, indent=2, default=str),
        screening_results=json.dumps(screening_results, indent=2, default=str),
        price_analysis=json.dumps(price_analysis, indent=2, default=str),
        company_data=json.dumps(company_data or {}, indent=2, default=str),
        base_price=base_price,
        final_price=final_price,
        num_catalysts=len(screening_results.get('catalysts', [])),
        num_risks=len(screening_results.get('risks', [])),
        num_mitigations=len(screening_results.get('mitigations', []))
    )
    
    # Prepare messages for LLM call
    messages = [
        {"role": "user", "content": formatted_prompt}
    ]
    
    # Generate professional report using LLM with correct signature
    response, cost = get_llm()(messages, temperature=0.3)
    
    return response.strip()


def save_explanation_reports(ticker: str, deterministic_md: str, base_path: pathlib.Path = None) -> Dict[str, str]:
    """Save technical analysis reports with timestamped and latest versions.
    
    Args:
        ticker: Stock ticker symbol
        deterministic_md: The comprehensive technical analysis report content
        base_path: Base path for saving reports
    
    Returns:
        Dictionary with saved file paths
    """
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    rdir = base_path / 'reports'
    rdir.mkdir(parents=True, exist_ok=True)
    
    # Save technical analysis report
    final_report = deterministic_md
    
    report_path = rdir / f"technical_analysis_{ticker}_{timestamp}.md"
    report_latest = rdir / "technical_analysis_latest.md"
    report_path.write_text(final_report, encoding='utf-8')
    report_latest.write_text(final_report, encoding='utf-8')
    return {"path": str(report_path), "latest": str(report_latest)}


def build_deterministic_summary(ticker: str, output: Dict[str, Any], factors: Dict[str, Any], meta: Dict[str, Any] | None = None) -> str:
    """Build a comprehensive deterministic markdown summary with LLM reasoning and detailed screening data.
    
    Args:
        ticker: Stock ticker symbol
        output: Price adjustment output with LLM reasoning
        factors: Screening factors (catalysts, risks, mitigations) with enhanced data
        meta: Optional metadata (model, years, term_growth, etc.)
    
    Returns:
        Comprehensive markdown report with executive summary, LLM reasoning, and detailed insights
    """
    def _p(v):
        try:
            return f"{v*100:+.1f}%" if v is not None else "n/a"
        except Exception:
            return "n/a"
    
    def _format_source_articles(source_articles):
        """Format source articles with proper titles and URLs."""
        if not source_articles:
            return ["- (no sources)"]
        
        sources = []
        for source in source_articles:
            if hasattr(source, 'title') and hasattr(source, 'url'):
                # ArticleReference object
                if source.url:
                    sources.append(f"- [{source.title}]({source.url})")
                else:
                    sources.append(f"- {source.title}")
            elif isinstance(source, dict):
                # Dictionary format
                title = source.get('title', 'Unknown Article')
                url = source.get('url', '')
                if url:
                    sources.append(f"- [{title}]({url})")
                else:
                    sources.append(f"- {title}")
            else:
                # Legacy string format
                sources.append(f"- {str(source)}")
        
        return sources
    
    def _format_quotes(direct_quotes):
        """Format direct quotes with proper attribution."""
        if not direct_quotes:
            return []
        
        quotes = []
        for quote in direct_quotes:
            if hasattr(quote, 'quote') and hasattr(quote, 'source_article'):
                # DirectQuote object
                quote_text = f'> "{quote.quote}"'
                if hasattr(quote, 'source_url') and quote.source_url:
                    quote_text += f" — [{quote.source_article}]({quote.source_url})"
                else:
                    quote_text += f" — {quote.source_article}"
                quotes.append(quote_text)
            elif isinstance(quote, dict):
                # Dictionary format
                quote_text = f'> "{quote.get("quote", "")}"'
                source = quote.get("source_article", "Unknown Source")
                url = quote.get("source_url", "")
                if url:
                    quote_text += f" — [{source}]({url})"
                else:
                    quote_text += f" — {source}"
                quotes.append(quote_text)
        
        return quotes
    
    # Initialize report
    ts_human = time.strftime('%Y-%m-%d %H:%M:%S')
    lines = [
        f"# Price Adjustment Analysis Report — {ticker}",
        "",
        f"**Generated:** {ts_human}",
        f"**Method:** {output.get('method', 'qual_overlay')}",
        "",
        "## Executive Summary"
    ]
    
    # Price analysis section
    base_price = output.get('base_model_price')
    mapped_price = output.get('mapped_model_price') or output.get('mapped_adjusted_price')
    qual_adj_price = output.get('adjusted_price')
    final_price = output.get('final_price') or output.get('primary_adjusted_price') or output.get('adjusted_price')
    bull = output.get('bull_price')
    bear = output.get('bear_price')
    volb = output.get('vol_buffer')
    
    # Extract percentage changes
    mapped_total_pct = None
    mr = output.get('mapped_result') or output.get('mapped_parameter_deltas')
    if isinstance(mr, dict):
        mapped_total_pct = mr.get('mapped_total_change_pct')
    
    qual_pct = output.get('adjustment_pct')
    residual_pct = output.get('residual_overlay_pct') or output.get('residual_overlay_pct_llm')
    llm_total_pct = output.get('llm_total_change_pct')
    
    # Base model information
    if meta and meta.get('model'):
        years = meta.get('years', 'n/a')
        tg = meta.get('term_growth', 'n/a')
        if isinstance(tg, (int, float)):
            tg = f"{tg:.3f}"
        lines.append(f"- **Base Model Price:** ${base_price:,.2f} ({meta['model']} model, {years} years, terminal growth={tg})")
    else:
        lines.append(f"- **Base Model Price:** ${base_price:,.2f}")
    
    # Price progression
    if mapped_price is not None:
        ch = mapped_total_pct if mapped_total_pct is not None else ((mapped_price / base_price) - 1 if base_price else None)
        lines.append(f"- **Mapped Parameter Price:** ${mapped_price:,.2f} ({_p(ch)} vs base)")
    
    if qual_adj_price is not None:
        lines.append(f"- **Qualitative Overlay Price:** ${qual_adj_price:,.2f} ({_p(qual_pct)} vs base)")
    
    if output.get('llm_adjusted_price') is not None:
        lines.append(f"- **LLM-Adjusted Price:** ${output['llm_adjusted_price']:,.2f} ({_p(llm_total_pct)} vs base)")
    
    if residual_pct is not None and final_price is not None and mapped_price is not None:
        lines.append(f"- **Residual Overlay:** {_p(residual_pct)}")
    
    if final_price is not None:
        lines.append(f"- **Final Target Price:** ${final_price:,.2f}")
    
    # Price range
    if bull is not None and bear is not None and volb is not None:
        lines.append(f"- **Price Range:** ${bear:,.2f} (Bear) — ${bull:,.2f} (Bull) | Buffer: {volb*100:.1f}%")
    
    # Extract LLM deltas and reasoning
    llm_deltas = output.get('llm_deltas', [])
    if llm_deltas:
        lines.append("**AI Parameter Adjustments with Reasoning:**")
        lines.append("")
        for delta in llm_deltas:
            param = delta.get('param', 'Unknown')
            delta_val = delta.get('delta_applied', 0)
            reason = delta.get('reason', 'No reasoning provided')
            sources = delta.get('sources', [])
            
            # Format parameter change
            if 'growth' in param.lower():
                delta_str = f"{delta_val*100:+.1f} percentage points"
            elif 'wacc' in param.lower():
                delta_str = f"{delta_val*100:+.1f} basis points"  
            elif 'margin' in param.lower():
                delta_str = f"{delta_val*100:+.1f} percentage points"
            else:
                delta_str = f"{delta_val:+.4f}"
            
            lines.append(f"**{param.replace('_', ' ').title()}:** {delta_str}")
            lines.append(f"- **Reasoning:** {reason}")
            if sources:
                source_list = ', '.join(sources)
                lines.append(f"- **Sources:** {source_list}")
            lines.append("")
    else:
        lines.append("*No LLM parameter adjustments were applied.*")
        lines.append("")
    
    # Detailed Analysis Sections
    lines.extend(["", "---", "", "## Detailed Investment Analysis", ""])
    
    # Growth Catalysts Section
    catalysts = factors.get('catalysts', [])
    lines.append("### 🚀 Growth Catalysts")
    lines.append("")
    
    if catalysts:
        for i, catalyst in enumerate(catalysts[:10], 1):  # Limit to top 10
            # Basic information
            title = catalyst.get('description') or catalyst.get('type') or f'Catalyst {i}'
            conf = catalyst.get('confidence', 0)
            timeline = catalyst.get('timeline', 'n/a')
            potential_impact = catalyst.get('potential_impact', '')
            
            lines.append(f"#### Catalyst {i}: {title}")
            lines.append(f"**Confidence:** {conf*100:.0f}% | **Timeline:** {timeline.title()}\n")
            
            # AI Analysis/Reasoning
            reasoning = catalyst.get('llm_reasoning') or catalyst.get('reasoning')
            if reasoning:
                lines.append(f"**AI Analysis:**\n {reasoning}\n")
            
            # Potential Impact
            if potential_impact:
                lines.append(f"**Potential Impact:**\n {potential_impact}\n")
            
            # Supporting Evidence
            evidence = catalyst.get('supporting_evidence', [])
            if evidence:
                lines.append("**Supporting Evidence:**\n")
                for ev in evidence:
                    lines.append(f"- {ev}")
                lines.append("\n")
            
            # Direct Quotes
            quotes = _format_quotes(catalyst.get('direct_quotes', []))
            if quotes:
                lines.append("**Key Quotes:**\n")
                lines.extend(quotes)
            
    else:
        lines.append("*No growth catalysts identified.*")
        lines.append("")
    
    # Investment Risks Section  
    risks = factors.get('risks', [])
    lines.append("### ⚠️ Investment Risks")
    lines.append("")
    
    if risks:
        for i, risk in enumerate(risks[:10], 1):  # Limit to top 10
            # Basic information
            title = risk.get('description') or risk.get('type') or f'Risk {i}'
            conf = risk.get('confidence', 0)
            severity = risk.get('severity', 'medium')
            potential_impact = risk.get('potential_impact', '')
            likelihood = risk.get('likelihood', 'n/a')
            
            severity_emoji = {'critical': '🚨', 'high': '⚠️', 'medium': '⚡', 'low': '💭'}
            risk_emoji = severity_emoji.get(severity.lower(), '⚠️')
            
            lines.append(f"#### Risk {i}: {title} {risk_emoji}")
            lines.append(f"**Confidence:** {conf*100:.0f}% | **Severity:** {severity.title()} | **Likelihood:** {likelihood.title()}")
            
            # AI Analysis/Reasoning
            reasoning = risk.get('llm_reasoning') or risk.get('reasoning')
            if reasoning:
                lines.append(f"**AI Analysis:** {reasoning}")
            
            # Potential Impact
            if potential_impact:
                lines.append(f"**Potential Impact:** {potential_impact}")
            
            # Supporting Evidence
            evidence = risk.get('supporting_evidence', [])
            if evidence:
                lines.append("**Supporting Evidence:**")
                for ev in evidence:
                    lines.append(f"- {ev}")
            
            # Direct Quotes
            quotes = _format_quotes(risk.get('direct_quotes', []))
            if quotes:
                lines.append("**Key Quotes:**")
                lines.extend(quotes)
            
            # Source Articles
            sources = _format_source_articles(risk.get('source_articles', []))
            lines.append("**Source Articles:**")
            lines.extend(sources)
            lines.append("")
    else:
        lines.append("*No investment risks identified.*")
        lines.append("")
    
    # Risk Mitigation Section
    mitigations = factors.get('mitigations', [])
    lines.append("### 🛡️ Risk Mitigation Strategies")
    lines.append("")
    
    if mitigations:
        for i, mitigation in enumerate(mitigations[:10], 1):  # Limit to top 10
            # Basic information
            strategy = mitigation.get('strategy', f'Mitigation {i}')
            risk_addressed = mitigation.get('risk_addressed', 'Various risks')
            conf = mitigation.get('confidence', 0)
            effectiveness = mitigation.get('effectiveness', 'medium')
            company_action = mitigation.get('company_action', '')
            timeline = mitigation.get('implementation_timeline', 'n/a')
            
            effectiveness_emoji = {'high': '✅', 'medium': '⚡', 'low': '❓'}
            mit_emoji = effectiveness_emoji.get(effectiveness.lower(), '⚡')
            
            lines.append(f"#### Mitigation {i}: {strategy} {mit_emoji}")
            lines.append(f"**Confidence:** {conf*100:.0f}% | **Effectiveness:** {effectiveness.title()}")
            lines.append(f"**Addresses:** {risk_addressed}")
            
            if timeline != 'n/a':
                lines.append(f"**Timeline:** {timeline}")
            
            # AI Analysis/Reasoning
            reasoning = mitigation.get('llm_reasoning') or mitigation.get('reasoning')
            if reasoning:
                lines.append(f"**AI Analysis:** {reasoning}")
            
            # Company Action
            if company_action:
                lines.append(f"**Company Action:** {company_action}")
            
            # Supporting Evidence
            evidence = mitigation.get('supporting_evidence', [])
            if evidence:
                lines.append("**Supporting Evidence:**")
                for ev in evidence:
                    lines.append(f"- {ev}")
            
            # Direct Quotes
            quotes = _format_quotes(mitigation.get('direct_quotes', []))
            if quotes:
                lines.append("**Key Quotes:**")
                lines.extend(quotes)
            
            # Source Articles
            sources = _format_source_articles(mitigation.get('source_articles', []))
            lines.append("**Source Articles:**")
            lines.extend(sources)
            lines.append("")
    else:
        lines.append("*No risk mitigation strategies identified.*")
        lines.append("")
    
    # Summary Statistics
    lines.extend([
        "---",
        "",
        "## Analysis Summary",
        "",
        f"**Total Insights Analyzed:** {len(catalysts)} catalysts, {len(risks)} risks, {len(mitigations)} mitigations",
    ])
    
    if catalysts:
        avg_catalyst_conf = sum(c.get('confidence', 0) for c in catalysts) / len(catalysts)
        lines.append(f"**Average Catalyst Confidence:** {avg_catalyst_conf*100:.0f}%")
    
    if risks:
        avg_risk_conf = sum(r.get('confidence', 0) for r in risks) / len(risks)
        lines.append(f"**Average Risk Confidence:** {avg_risk_conf*100:.0f}%")
        
        # Risk severity distribution
        severity_counts = {}
        for risk in risks:
            sev = risk.get('severity', 'medium').lower()
            severity_counts[sev] = severity_counts.get(sev, 0) + 1
        
        if severity_counts:
            sev_text = ', '.join(f"{count} {sev}" for sev, count in severity_counts.items())
            lines.append(f"**Risk Distribution:** {sev_text}")
    
    if mitigations:
        avg_mit_conf = sum(m.get('confidence', 0) for m in mitigations) / len(mitigations)
        lines.append(f"**Average Mitigation Confidence:** {avg_mit_conf*100:.0f}%")
    
    lines.extend([
        "",
        "*This report combines quantitative financial modeling with AI-powered qualitative analysis*",
        "*for comprehensive investment decision support.*"
    ])
    
    return "\n".join(lines)
