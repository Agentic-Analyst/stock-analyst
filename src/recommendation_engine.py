#!/usr/bin/env python3
"""
recommendation_engine.py - LLM-Based Investment Recommendation Engine

Extracts and organizes investment data, then lets LLM perform complete analysis.
LLM has full flexibility to weight factors, reason about catalysts/risks, and generate recommendations.

Design Philosophy:
- Provide comprehensive, structured data to LLM
- LLM decides how to analyze and weight all factors
- LLM generates investment rating, price targets (3M/6M/12M), and justification
- All decisions traceable to source data
"""

from typing import Dict, Any, List, Tuple
import os


def _format_label(value: Any) -> str:
    """Safely format a label that may be string or numeric.

    - If string: title-case it.
    - If numeric between 0 and 1: format as percentage (e.g. 0.75 -> '75%').
    - Otherwise convert to str.
    """
    if value is None:
        return None
    # Strings: title-case
    if isinstance(value, str):
        return value.title()
    # Numbers: treat 0-1 as probabilities, else raw
    try:
        if isinstance(value, (int, float)):
            if 0 <= value <= 1:
                return f"{value:.0%}"
            return str(value)
    except Exception:
        pass
    return str(value)


class RecommendationEngine:
    """
    Data preparation engine for LLM-based investment recommendations.
    
    Extracts and formats all relevant data:
    - Company fundamentals and market data
    - DCF valuation results
    - News-driven catalysts and risks
    - Historical performance metrics
    
    Then passes everything to LLM for complete analysis and recommendation.
    """
    
    def __init__(self, sector: str = None):
        """
        Initialize engine.
        
        Args:
            sector: Company sector (optional, for LLM context)
        """
        self.sector = sector
    
    def generate_recommendation(
        self,
        company_data: Dict[str, Any],
        valuation_data: Dict[str, Any],
        news_data: Dict[str, Any],
        llm  # LLM callable
    ) -> Tuple[str, float]:
        """
        Generate LLM-based investment recommendation.
        
        Process:
        1. Extract all relevant data from company, valuation, and news
        2. Format into structured, clear input for LLM
        3. Load prompt template that guides LLM analysis
        4. LLM analyzes data and generates comprehensive recommendation
        
        Args:
            company_data: Company overview (name, ticker, price, sector, etc.)
            valuation_data: DCF valuation results (perpetual, exit multiple)
            news_data: News analysis (catalysts, risks, sentiment)
            llm: LLM callable (messages -> response, cost)
        
        Returns:
            (recommendation_text, llm_cost)
        """
        # Step 1: Extract and organize all data
        structured_data = self._prepare_investment_data(
            company_data, valuation_data, news_data
        )
        
        # Step 2: Format for LLM
        formatted_input = self._format_for_llm(structured_data)
        
        # Step 3: Load prompt template
        prompt_template = self._load_prompt_template()
        
        # Step 4: Generate final prompt
        prompt = prompt_template.replace('{input_data}', formatted_input)
        
        # Step 5: Call LLM (LLM does all analysis, weighting, and decision-making)
        messages = [{"role": "user", "content": prompt}]
        response, cost = llm(messages, temperature=0.7)
        
        return response, cost
    
    def _prepare_investment_data(
        self,
        company_data: Dict[str, Any],
        valuation_data: Dict[str, Any],
        news_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Extract and organize all investment-relevant data.
        
        Returns:
            Dictionary with all data organized by category
        """
        # Company fundamentals
        company_info = {
            'name': company_data.get('name', 'N/A'),
            'ticker': company_data.get('ticker', 'N/A'),
            'sector': company_data.get('sector', self.sector or 'N/A'),
            'industry': company_data.get('industry', 'N/A'),
            'market_cap': company_data.get('market_cap', 'N/A'),
            'description': company_data.get('description', 'N/A'),
        }
        
        # Market data
        market_data = {
            'current_price': company_data.get('current_price'),
            'week_52_high': company_data.get('week_52_high'),
            'week_52_low': company_data.get('week_52_low'),
            'average_volume': company_data.get('average_volume'),
            'beta': company_data.get('beta'),
        }
        
        # Financial metrics
        financial_metrics = {
            'revenue': company_data.get('revenue'),
            'revenue_growth': company_data.get('revenue_growth'),
            'net_income': company_data.get('net_income'),
            'net_margin': company_data.get('net_margin'),
            'operating_margin': company_data.get('operating_margin'),
            'roe': company_data.get('roe'),
            'roic': company_data.get('roic'),
            'debt_to_equity': company_data.get('debt_to_equity'),
            'current_ratio': company_data.get('current_ratio'),
            'free_cash_flow': company_data.get('free_cash_flow'),
        }
        
        # Valuation metrics
        valuation_metrics = {
            'dcf_perpetual_value': valuation_data.get('dcf_perpetual', {}).get('intrinsic_value_per_share'),
            'dcf_exit_value': valuation_data.get('dcf_exit', {}).get('intrinsic_value_per_share'),
            'dcf_perpetual_assumptions': valuation_data.get('dcf_perpetual', {}).get('assumptions', {}),
            'dcf_exit_assumptions': valuation_data.get('dcf_exit', {}).get('assumptions', {}),
            'pe_ratio': company_data.get('pe_ratio'),
            'forward_pe': company_data.get('forward_pe'),
            'peg_ratio': company_data.get('peg_ratio'),
            'price_to_book': company_data.get('price_to_book'),
            'ev_to_ebitda': company_data.get('ev_to_ebitda'),
        }
        
        # News-driven catalysts
        catalysts = news_data.get('catalysts', [])
        
        # News-driven risks
        risks = news_data.get('risks', [])
        
        # News summary and sentiment
        news_summary = news_data.get('summary', {})
        
        return {
            'company_info': company_info,
            'market_data': market_data,
            'financial_metrics': financial_metrics,
            'valuation_metrics': valuation_metrics,
            'catalysts': catalysts,
            'risks': risks,
            'news_summary': news_summary,
        }
    
    def _format_for_llm(self, data: Dict[str, Any]) -> str:
        """
        Format investment data into clear, structured text for LLM.
        
        Args:
            data: Organized investment data
        
        Returns:
            Formatted markdown string
        """
        lines = []
        
        # ===== COMPANY INFORMATION =====
        lines.append("# INVESTMENT DATA PACKAGE\n")
        lines.append("## 1. COMPANY INFORMATION\n")
        
        company = data['company_info']
        lines.append(f"**Company Name**: {company['name']}")
        lines.append(f"**Ticker**: {company['ticker']}")
        lines.append(f"**Sector**: {company['sector']}")
        lines.append(f"**Industry**: {company['industry']}")
        if company.get('market_cap'):
            lines.append(f"**Market Cap**: {company['market_cap']}")
        if company.get('description'):
            lines.append(f"\n**Company Description**: {company['description']}\n")
        
        # ===== MARKET DATA =====
        lines.append("## 2. MARKET DATA\n")
        
        market = data['market_data']
        if market.get('current_price'):
            lines.append(f"**Current Price**: ${market['current_price']:.2f}")
        if market.get('week_52_high') and market.get('week_52_low'):
            lines.append(f"**52-Week Range**: ${market['week_52_low']:.2f} - ${market['week_52_high']:.2f}")
            # Calculate position in range
            if market['current_price']:
                range_span = market['week_52_high'] - market['week_52_low']
                if range_span > 0:
                    position = (market['current_price'] - market['week_52_low']) / range_span
                    lines.append(f"**Price Position in Range**: {position:.1%}")
        if market.get('average_volume'):
            lines.append(f"**Average Volume**: {market['average_volume']:,.0f}")
        if market.get('beta'):
            lines.append(f"**Beta**: {market['beta']:.2f}\n")
        
        # ===== FINANCIAL METRICS =====
        lines.append("## 3. FINANCIAL METRICS\n")
        
        financials = data['financial_metrics']
        if financials.get('revenue'):
            lines.append(f"**Revenue**: ${financials['revenue']:,.0f}")
        if financials.get('revenue_growth') is not None:
            lines.append(f"**Revenue Growth**: {financials['revenue_growth']:.1%}")
        if financials.get('net_income'):
            lines.append(f"**Net Income**: ${financials['net_income']:,.0f}")
        if financials.get('net_margin') is not None:
            lines.append(f"**Net Margin**: {financials['net_margin']:.1%}")
        if financials.get('operating_margin') is not None:
            lines.append(f"**Operating Margin**: {financials['operating_margin']:.1%}")
        if financials.get('roe') is not None:
            lines.append(f"**Return on Equity (ROE)**: {financials['roe']:.1%}")
        if financials.get('roic') is not None:
            lines.append(f"**Return on Invested Capital (ROIC)**: {financials['roic']:.1%}")
        if financials.get('debt_to_equity') is not None:
            lines.append(f"**Debt-to-Equity**: {financials['debt_to_equity']:.2f}")
        if financials.get('current_ratio') is not None:
            lines.append(f"**Current Ratio**: {financials['current_ratio']:.2f}")
        if financials.get('free_cash_flow'):
            lines.append(f"**Free Cash Flow**: ${financials['free_cash_flow']:,.0f}\n")
        
        # ===== VALUATION ANALYSIS =====
        lines.append("## 4. VALUATION ANALYSIS\n")
        
        valuation = data['valuation_metrics']
        
        lines.append("### DCF Valuation Results\n")
        if valuation.get('dcf_perpetual_value'):
            lines.append(f"**DCF Perpetual Growth Method**: ${valuation['dcf_perpetual_value']:.2f} per share")
            if valuation.get('dcf_perpetual_assumptions'):
                assumptions = valuation['dcf_perpetual_assumptions']
                lines.append("  - Key Assumptions:")
                for key, value in assumptions.items():
                    if isinstance(value, (int, float)):
                        if 'rate' in key.lower() or 'growth' in key.lower():
                            lines.append(f"    - {key}: {value:.1%}")
                        else:
                            lines.append(f"    - {key}: {value}")
                    else:
                        lines.append(f"    - {key}: {value}")
        
        if valuation.get('dcf_exit_value'):
            lines.append(f"\n**DCF Exit Multiple Method**: ${valuation['dcf_exit_value']:.2f} per share")
            if valuation.get('dcf_exit_assumptions'):
                assumptions = valuation['dcf_exit_assumptions']
                lines.append("  - Key Assumptions:")
                for key, value in assumptions.items():
                    if isinstance(value, (int, float)):
                        if 'rate' in key.lower() or 'growth' in key.lower():
                            lines.append(f"    - {key}: {value:.1%}")
                        else:
                            lines.append(f"    - {key}: {value}")
                    else:
                        lines.append(f"    - {key}: {value}")
        
        # Calculate valuation gap if data available
        if valuation.get('dcf_perpetual_value') and valuation.get('dcf_exit_value') and market.get('current_price'):
            avg_intrinsic = (valuation['dcf_perpetual_value'] + valuation['dcf_exit_value']) / 2
            gap = ((avg_intrinsic - market['current_price']) / market['current_price']) * 100
            lines.append(f"\n**Average DCF Intrinsic Value**: ${avg_intrinsic:.2f}")
            lines.append(f"**Current Market Price**: ${market['current_price']:.2f}")
            lines.append(f"**Valuation Gap**: {gap:+.1f}%")
        
        lines.append("\n### Market Multiples\n")
        if valuation.get('pe_ratio'):
            lines.append(f"**P/E Ratio**: {valuation['pe_ratio']:.1f}")
        if valuation.get('forward_pe'):
            lines.append(f"**Forward P/E**: {valuation['forward_pe']:.1f}")
        if valuation.get('peg_ratio'):
            lines.append(f"**PEG Ratio**: {valuation['peg_ratio']:.2f}")
        if valuation.get('price_to_book'):
            lines.append(f"**Price-to-Book**: {valuation['price_to_book']:.2f}")
        if valuation.get('ev_to_ebitda'):
            lines.append(f"**EV/EBITDA**: {valuation['ev_to_ebitda']:.1f}\n")
        
        # ===== POSITIVE CATALYSTS =====
        lines.append("## 5. POSITIVE CATALYSTS\n")
        
        catalysts = data['catalysts']
        if catalysts:
            for i, catalyst in enumerate(catalysts, 1):
                lines.append(f"### Catalyst #{i}: {catalyst.get('type', 'Catalyst')}\n")
                lines.append(f"**Description**: {catalyst.get('description', 'N/A')}\n")
                if catalyst.get('confidence') is not None:
                    lines.append(f"**Confidence Level**: {_format_label(catalyst['confidence'])}")
                if catalyst.get('timeframe'):
                    lines.append(f"**Expected Timeframe**: {catalyst['timeframe']}")
                if catalyst.get('impact'):
                    lines.append(f"**Expected Impact**: {catalyst['impact']}")
                if catalyst.get('source'):
                    lines.append(f"**Source**: {catalyst['source']}")
                lines.append("")
        else:
            lines.append("*No specific catalysts identified from news analysis.*\n")
        
        # ===== KEY RISKS =====
        lines.append("## 6. KEY RISKS\n")
        
        risks = data['risks']
        if risks:
            for i, risk in enumerate(risks, 1):
                lines.append(f"### Risk #{i}: {risk.get('type', 'Risk')}\n")
                lines.append(f"**Description**: {risk.get('description', 'N/A')}\n")
                if risk.get('likelihood') is not None:
                    lines.append(f"**Likelihood**: {_format_label(risk['likelihood'])}")
                if risk.get('severity') is not None:
                    lines.append(f"**Severity**: {_format_label(risk['severity'])}")
                if risk.get('timeframe'):
                    lines.append(f"**Timeframe**: {risk['timeframe']}")
                if risk.get('mitigation'):
                    lines.append(f"**Potential Mitigation**: {risk['mitigation']}")
                lines.append("")
        else:
            lines.append("*No specific risks identified from news analysis.*\n")
        
        # ===== NEWS SUMMARY =====
        lines.append("## 7. NEWS SUMMARY & SENTIMENT\n")
        
        news_summary = data['news_summary']
        if news_summary:
            if news_summary.get('overall_sentiment') is not None:
                lines.append(f"**Overall Sentiment**: {_format_label(news_summary['overall_sentiment'])}")
            if news_summary.get('key_themes'):
                lines.append(f"**Key Themes**: {', '.join(news_summary['key_themes'])}")
            if news_summary.get('recent_developments'):
                lines.append(f"\n**Recent Developments**:")
                for dev in news_summary['recent_developments']:
                    lines.append(f"- {dev}")
            if news_summary.get('analyst_consensus'):
                lines.append(f"\n**Analyst Consensus**: {news_summary['analyst_consensus']}")
        else:
            lines.append("*No news summary available.*")
        
        lines.append("\n")
        lines.append("=" * 80)
        lines.append("\nAbove is all the available investment data. Please analyze this comprehensively and generate your investment recommendation.")
        
        return "\n".join(lines)
    
    def _load_prompt_template(self) -> str:
        """Load investment recommendation prompt template."""
        prompt_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'prompts',
            'investment_recommendation.md'
        )
        
        with open(prompt_path, 'r', encoding='utf-8') as f:
            return f.read()


def load_prompt(prompt_name: str) -> str:
    """
    Load a prompt template from the prompts folder.
    
    Args:
        prompt_name: Name of the prompt file (without .md extension)
    
    Returns:
        Prompt template content
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    prompt_path = os.path.join(project_root, 'prompts', f'{prompt_name}.md')
    
    with open(prompt_path, 'r', encoding='utf-8') as f:
        return f.read()
