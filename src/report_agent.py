#!/usr/bin/env python3
"""
report_agent.py - Professional Financial Report Generator (V2)

Generates comprehensive, institutional-quality financial analyst reports by:
1. Loading data from JSON files (no more open_excel dependency)
2. Extracting company data, financial model results, and news analysis
3. Using LLM to synthesize all data into a professional markdown report

Data Sources:
- financial_json: financials_annual_modeling_latest.json (company info, historical data)
- computed_values_json: *_computed_values.json (evaluated financial model)
- screening_json: screening_data.json (news catalysts, risks, mitigations)

Output: Professional analyst report in markdown format
"""

from __future__ import annotations
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
import json

from llms.config import get_llm
from logger import StockAnalystLogger
from recommendation_engine import RecommendationEngine


def load_prompt(prompt_name: str) -> str:
    """Load a prompt template from the prompts folder.
    
    Args:
        prompt_name: Name of the prompt file (without .md extension)
        
    Returns:
        Prompt template string
    """
    prompt_path = Path(__file__).parent.parent / "prompts" / f"{prompt_name}.md"
    with open(prompt_path, 'r') as f:
        return f.read()


def load_financial_json(json_path: Path) -> Dict[str, Any]:
    """Load financial data JSON."""
    with open(json_path, 'r') as f:
        return json.load(f)


def load_computed_values_json(json_path: Path) -> Dict[str, Any]:
    """Load computed values JSON from formula_evaluator."""
    with open(json_path, 'r') as f:
        return json.load(f)


def load_screening_json(json_path: Path) -> Dict[str, Any]:
    """Load screening data JSON."""
    with open(json_path, 'r') as f:
        return json.load(f)


def extract_company_overview(financial_data: Dict[str, Any]) -> Dict[str, Any]:
    """Extract company overview from financial JSON."""
    company_data = financial_data.get('company_data', {})
    basic_info = company_data.get('basic_info', {})
    market_data = company_data.get('market_data', {})
    valuation_metrics = company_data.get('valuation_metrics', {})
    capital_structure = company_data.get('capital_structure', {})
    growth_profitability = company_data.get('growth_profitability', {})
    forward_guidance = company_data.get('forward_guidance', {})
    
    return {
        'ticker': financial_data.get('ticker', 'N/A'),
        'company_name': basic_info.get('long_name', 'Unknown Company'),
        'sector': basic_info.get('sector', 'N/A'),
        'industry': basic_info.get('industry', 'N/A'),
        'description': basic_info.get('business_summary', ''),
        'website': basic_info.get('website', ''),
        'employees': basic_info.get('employees', 0),
        'country': basic_info.get('country', 'N/A'),
        'exchange': basic_info.get('exchange', 'N/A'),
        'current_price': market_data.get('current_price', 0),
        'market_cap': market_data.get('market_cap', 0),
        'enterprise_value': market_data.get('enterprise_value', 0),
        'shares_outstanding': market_data.get('shares_outstanding_basic', 0),
        'week_52_high': market_data.get('52_week_high', 0),
        'week_52_low': market_data.get('52_week_low', 0),
        'pe_trailing': valuation_metrics.get('pe_ratio_trailing', 0),
        'pe_forward': valuation_metrics.get('pe_ratio_forward', 0),
        'price_to_book': valuation_metrics.get('price_to_book', 0),
        'price_to_sales': valuation_metrics.get('price_to_sales', 0),
        'ev_to_revenue': valuation_metrics.get('enterprise_to_revenue', 0),
        'ev_to_ebitda': valuation_metrics.get('enterprise_to_ebitda', 0),
        'total_debt': capital_structure.get('total_debt', 0),
        'total_cash': capital_structure.get('total_cash', 0),
        'net_debt': capital_structure.get('net_debt', 0),
        'debt_to_equity': capital_structure.get('debt_to_equity', 0),
        'current_ratio': capital_structure.get('current_ratio', 0),
        'quick_ratio': capital_structure.get('quick_ratio', 0),
        'beta': capital_structure.get('beta', 0),
        'gross_margin': growth_profitability.get('gross_margins', 0),
        'operating_margin': growth_profitability.get('operating_margins', 0),
        'ebitda_margin': growth_profitability.get('ebitda_margins', 0),
        'net_margin': growth_profitability.get('profit_margins', 0),
        'roe': growth_profitability.get('return_on_equity', 0),
        'roa': growth_profitability.get('return_on_assets', 0),
        'revenue_growth': growth_profitability.get('revenue_growth', 0),
        'earnings_growth': growth_profitability.get('earnings_growth', 0),
        'dividend_yield': market_data.get('dividend_yield', 0),
        'target_mean_price': forward_guidance.get('target_mean_price', 0),
        'target_high_price': forward_guidance.get('target_high_price', 0),
        'target_low_price': forward_guidance.get('target_low_price', 0),
        'recommendation': forward_guidance.get('recommendation_key', 'N/A'),
        'num_analysts': forward_guidance.get('number_of_analyst_opinions', 0),
    }


def extract_historical_financials(financial_data: Dict[str, Any]) -> Dict[str, Any]:
    """Extract 5-year historical financial statements."""
    statements = financial_data.get('financial_statements', {})
    income_statement = statements.get('income_statement', {})
    balance_sheet = statements.get('balance_sheet', {})
    cash_flow = statements.get('cash_flow', {})
    
    # Get years (sorted from oldest to newest)
    years = sorted(income_statement.keys())
    
    historical = {
        'years': years,
        'revenue': [],
        'gross_profit': [],
        'operating_income': [],
        'ebitda': [],
        'net_income': [],
        'operating_cf': [],
        'capex': [],
        'fcf': [],
        'total_assets': [],
        'total_equity': [],
        'cash': [],
        'debt': [],
    }
    
    for year in years:
        is_data = income_statement.get(year, {})
        bs_data = balance_sheet.get(year, {})
        cf_data = cash_flow.get(year, {})
        
        historical['revenue'].append(is_data.get('Total Revenue', 0) or is_data.get('Operating Revenue', 0))
        historical['gross_profit'].append(is_data.get('Gross Profit', 0))
        historical['operating_income'].append(is_data.get('Operating Income', 0))
        historical['ebitda'].append(is_data.get('EBITDA', 0))
        historical['net_income'].append(is_data.get('Net Income', 0))
        historical['operating_cf'].append(cf_data.get('Operating Cash Flow', 0))
        historical['capex'].append(cf_data.get('Capital Expenditure', 0))
        historical['fcf'].append(cf_data.get('Free Cash Flow', 0))
        historical['total_assets'].append(bs_data.get('Total Assets', 0))
        historical['total_equity'].append(bs_data.get('Stockholders Equity', 0))
        historical['cash'].append(bs_data.get('Cash And Cash Equivalents', 0))
        historical['debt'].append(bs_data.get('Total Debt', 0))
    
    return historical


def extract_model_assumptions(computed_values: Dict[str, Any]) -> Dict[str, Any]:
    """Extract model assumptions from LLM_Inferred tab."""
    llm_inferred = computed_values.get('LLM_Inferred', {}).get('cells', {})
    
    return {
        'wacc': llm_inferred.get('(2, 2)', 0.09),
        'terminal_growth': llm_inferred.get('(3, 2)', 0.025),
        'revenue_growth_rates': [
            llm_inferred.get('(4, 2)', 0),
            llm_inferred.get('(4, 3)', 0),
            llm_inferred.get('(4, 4)', 0),
            llm_inferred.get('(4, 5)', 0),
            llm_inferred.get('(4, 6)', 0),
        ],
        'gross_margins': [
            llm_inferred.get('(5, 2)', 0),
            llm_inferred.get('(5, 3)', 0),
            llm_inferred.get('(5, 4)', 0),
            llm_inferred.get('(5, 5)', 0),
            llm_inferred.get('(5, 6)', 0),
        ],
        'ebitda_margins': [
            llm_inferred.get('(6, 2)', 0),
            llm_inferred.get('(6, 3)', 0),
            llm_inferred.get('(6, 4)', 0),
            llm_inferred.get('(6, 5)', 0),
            llm_inferred.get('(6, 6)', 0),
        ],
        'operating_margins': [
            llm_inferred.get('(7, 2)', 0),
            llm_inferred.get('(7, 3)', 0),
            llm_inferred.get('(7, 4)', 0),
            llm_inferred.get('(7, 5)', 0),
            llm_inferred.get('(7, 6)', 0),
        ],
    }


def extract_projections(computed_values: Dict[str, Any]) -> Dict[str, Any]:
    """Extract 5-year projections from Projections tab."""
    projections = computed_values.get('Projections', {}).get('cells', {})
    
    return {
        'revenue': [
            projections.get('(3, 2)', 0),
            projections.get('(3, 3)', 0),
            projections.get('(3, 4)', 0),
            projections.get('(3, 5)', 0),
            projections.get('(3, 6)', 0),
        ],
        'gross_profit': [
            projections.get('(4, 2)', 0),
            projections.get('(4, 3)', 0),
            projections.get('(4, 4)', 0),
            projections.get('(4, 5)', 0),
            projections.get('(4, 6)', 0),
        ],
        'ebitda': [
            projections.get('(21, 2)', 0),
            projections.get('(21, 3)', 0),
            projections.get('(21, 4)', 0),
            projections.get('(21, 5)', 0),
            projections.get('(21, 6)', 0),
        ],
        'fcf': [
            projections.get('(19, 2)', 0),
            projections.get('(19, 3)', 0),
            projections.get('(19, 4)', 0),
            projections.get('(19, 5)', 0),
            projections.get('(19, 6)', 0),
        ],
    }


def extract_valuation(computed_values: Dict[str, Any]) -> Dict[str, Any]:
    """Extract valuation results from Summary and Valuation tabs."""
    summary = computed_values.get('Summary', {}).get('cells', {})
    dcf_tab = computed_values.get('Valuation (DCF)', {}).get('cells', {})
    exit_tab = computed_values.get('Valuation (Exit Multiple)', {}).get('cells', {})
    
    return {
        'dcf_perpetual': {
            'pv_fcfs': dcf_tab.get('(19, 2)', 0),  # Sum of PV of FCFs
            'terminal_value': dcf_tab.get('(26, 2)', 0),  # PV of Terminal Value (not row 20!)
            'enterprise_value': dcf_tab.get('(27, 2)', 0),  # Enterprise Value (EV)
            'equity_value': summary.get('(13, 2)', 0),  # Equity Value (Perpetual DCF) from Summary
            'intrinsic_value_per_share': summary.get('(18, 2)', 0),  # Value per Share (Perpetual DCF) from Summary
        },
        'dcf_exit': {
            'terminal_ev': exit_tab.get('(14, 2)', 0),  # Terminal Value (Un-discounted)
            'enterprise_value': exit_tab.get('(17, 2)', 0),  # Enterprise Value (EV) - row 17, not 18!
            'equity_value': exit_tab.get('(22, 2)', 0),  # Equity Value (Firm Value)
            'intrinsic_value_per_share': exit_tab.get('(25, 2)', 0),  # Intrinsic Value per Share - row 25, not 24!
            'exit_multiple': exit_tab.get('(3, 2)', 0),  # Terminal EV/EBITDA Multiple
        },
        'summary': {
            'dcf_intrinsic': summary.get('(18, 2)', 0),
            'exit_intrinsic': summary.get('(22, 2)', 0),
            'average_intrinsic': summary.get('(26, 2)', 0),
            'upside': summary.get('(27, 2)', 0),
            'shares_outstanding': summary.get('(8, 2)', 0),
            'cash': summary.get('(14, 2)', 0),
            'debt': summary.get('(15, 2)', 0),
            'net_debt': summary.get('(16, 2)', 0),
        }
    }


def extract_news_analysis(screening_data: Dict[str, Any]) -> Dict[str, Any]:
    """Extract news screening analysis."""
    return {
        'summary': screening_data.get('analysis_summary', {}),
        'catalysts': screening_data.get('catalysts', []),
        'risks': screening_data.get('risks', []),
        'mitigations': screening_data.get('mitigations', []),
        'screening_method': screening_data.get('analysis_method', 'LLM-based screening'),
    }


def format_number(num, decimals=2):
    """Format number with commas and decimals."""
    if num is None:
        return "N/A"
    try:
        num = float(num)
        if abs(num) >= 1e9:
            return f"${num/1e9:.{decimals}f}B"
        elif abs(num) >= 1e6:
            return f"${num/1e6:.{decimals}f}M"
        elif abs(num) >= 1e3:
            return f"${num/1e3:.{decimals}f}K"
        else:
            return f"${num:.{decimals}f}"
    except:
        return str(num)


def format_percent(num, decimals=1):
    """Format number as percentage."""
    if num is None:
        return "N/A"
    try:
        return f"{float(num)*100:.{decimals}f}%"
    except:
        return str(num)


def generate_section_company_overview(data: Dict[str, Any], llm) -> Tuple[str, float]:
    """Generate Company Overview section."""
    company = data['company_overview']
    
    # Load prompt template and fill in variables
    prompt_template = load_prompt("report_company_overview")
    prompt = prompt_template.format(
        company_name=company['company_name'],
        ticker=company['ticker'],
        sector=company['sector'],
        industry=company['industry'],
        description=company['description'][:500] + "...",
        employees=f"{company['employees']:,}",
        market_cap=format_number(company['market_cap']),
        current_price=format_number(company['current_price'], 2),
        week_52_low=format_number(company['week_52_low'], 2),
        week_52_high=format_number(company['week_52_high'], 2)
    )

    messages = [{"role": "user", "content": prompt}]
    response, cost = llm(messages, temperature=0.5)
    return response, cost


def generate_section_financial_performance(data: Dict[str, Any], llm) -> Tuple[str, float]:
    """Generate Financial Performance Analysis section with pre-built tables."""
    historical = data['historical']
    company = data['company_overview']
    
    # Build revenue table from actual JSON data
    years = historical['years']
    revenue_table = "| Year | Revenue | Gross Profit | EBITDA | Net Income | Operating CF | Free Cash Flow |\n"
    revenue_table += "|------|---------|--------------|--------|------------|--------------|----------------|\n"
    for i, year in enumerate(years):
        revenue_table += f"| {year} | {format_number(historical['revenue'][i])} | {format_number(historical['gross_profit'][i])} | {format_number(historical['ebitda'][i])} | {format_number(historical['net_income'][i])} | {format_number(historical['operating_cf'][i])} | {format_number(historical['fcf'][i])} |\n"
    
    # Calculate YoY growth rates
    growth_table = "| Year | Revenue Growth | Gross Profit Growth | EBITDA Growth | Net Income Growth | Operating CF Growth | FCF Growth |\n"
    growth_table += "|------|----------------|---------------------|---------------|-------------------|---------------------|------------|\n"
    for i in range(1, len(years)):
        rev_growth = ((historical['revenue'][i] / historical['revenue'][i-1]) - 1) if historical['revenue'][i-1] else 0
        gp_growth = ((historical['gross_profit'][i] / historical['gross_profit'][i-1]) - 1) if historical['gross_profit'][i-1] else 0
        ebitda_growth = ((historical['ebitda'][i] / historical['ebitda'][i-1]) - 1) if historical['ebitda'][i-1] else 0
        ni_growth = ((historical['net_income'][i] / historical['net_income'][i-1]) - 1) if historical['net_income'][i-1] else 0
        ocf_growth = ((historical['operating_cf'][i] / historical['operating_cf'][i-1]) - 1) if historical['operating_cf'][i-1] else 0
        fcf_growth = ((historical['fcf'][i] / historical['fcf'][i-1]) - 1) if historical['fcf'][i-1] else 0
        
        growth_table += f"| {years[i-1]}-{years[i]} | {rev_growth:.2%} | {gp_growth:.2%} | {ebitda_growth:.2%} | {ni_growth:.2%} | {ocf_growth:.2%} | {fcf_growth:.2%} |\n"
    
    # Margins table
    margins_table = "| Metric | Current Value |\n"
    margins_table += "|--------|---------------|\n"
    margins_table += f"| Gross Margin | {format_percent(company['gross_margin'])} |\n"
    margins_table += f"| Operating Margin | {format_percent(company['operating_margin'])} |\n"
    margins_table += f"| EBITDA Margin | {format_percent(company['ebitda_margin'])} |\n"
    margins_table += f"| Net Margin | {format_percent(company['net_margin'])} |\n"
    margins_table += f"| ROE | {format_percent(company['roe'])} |\n"
    margins_table += f"| ROA | {format_percent(company['roa'])} |\n"
    
    # Load prompt template and fill in variables
    prompt_template = load_prompt("report_financial_performance")
    prompt = prompt_template.format(
        company_name=company['company_name'],
        num_years=len(years),
        revenue_table=revenue_table,
        growth_table=growth_table,
        margins_table=margins_table
    )

    messages = [{"role": "user", "content": prompt}]
    response, cost = llm(messages, temperature=0.5)
    return response, cost


def generate_section_valuation(data: Dict[str, Any], llm) -> Tuple[str, float]:
    """Generate Financial Model & Valuation section with pre-built tables."""
    assumptions = data['assumptions']
    projections = data['projections']
    valuation = data['valuation']
    company = data['company_overview']
    
    # Model assumptions table
    assumptions_table = "| Assumption | Value |\n"
    assumptions_table += "|------------|-------|\n"
    assumptions_table += f"| WACC | {format_percent(assumptions['wacc'])} |\n"
    assumptions_table += f"| Terminal Growth Rate | {format_percent(assumptions['terminal_growth'])} |\n"
    assumptions_table += f"| Revenue Growth (FY1) | {format_percent(assumptions['revenue_growth_rates'][0])} |\n"
    assumptions_table += f"| Revenue Growth (FY2) | {format_percent(assumptions['revenue_growth_rates'][1])} |\n"
    assumptions_table += f"| Revenue Growth (FY3) | {format_percent(assumptions['revenue_growth_rates'][2])} |\n"
    assumptions_table += f"| Revenue Growth (FY4) | {format_percent(assumptions['revenue_growth_rates'][3])} |\n"
    assumptions_table += f"| Revenue Growth (FY5) | {format_percent(assumptions['revenue_growth_rates'][4])} |\n"
    assumptions_table += f"| EBITDA Margin (FY1) | {format_percent(assumptions['ebitda_margins'][0])} |\n"
    assumptions_table += f"| EBITDA Margin (FY2) | {format_percent(assumptions['ebitda_margins'][1])} |\n"
    assumptions_table += f"| EBITDA Margin (FY3) | {format_percent(assumptions['ebitda_margins'][2])} |\n"
    assumptions_table += f"| EBITDA Margin (FY4) | {format_percent(assumptions['ebitda_margins'][3])} |\n"
    assumptions_table += f"| EBITDA Margin (FY5) | {format_percent(assumptions['ebitda_margins'][4])} |\n"
    
    # 5-year projections table
    projections_table = "| Fiscal Year | Revenue | EBITDA | Free Cash Flow |\n"
    projections_table += "|-------------|---------|--------|----------------|\n"
    for i in range(5):
        projections_table += f"| FY{i+1} | {format_number(projections['revenue'][i])} | {format_number(projections['ebitda'][i])} | {format_number(projections['fcf'][i])} |\n"
    
    # DCF Perpetual Growth results
    dcf_perp_table = "| Metric | Value |\n"
    dcf_perp_table += "|--------|-------|\n"
    dcf_perp_table += f"| PV of Free Cash Flows | {format_number(valuation['dcf_perpetual']['pv_fcfs'])} |\n"
    dcf_perp_table += f"| Terminal Value | {format_number(valuation['dcf_perpetual']['terminal_value'])} |\n"
    dcf_perp_table += f"| Enterprise Value | {format_number(valuation['dcf_perpetual']['enterprise_value'])} |\n"
    dcf_perp_table += f"| Equity Value | {format_number(valuation['dcf_perpetual']['equity_value'])} |\n"
    dcf_perp_table += f"| Intrinsic Value per Share | {format_number(valuation['dcf_perpetual']['intrinsic_value_per_share'], 2)} |\n"
    
    # DCF Exit Multiple results
    dcf_exit_table = "| Metric | Value |\n"
    dcf_exit_table += "|--------|-------|\n"
    dcf_exit_table += f"| Exit Multiple (EV/EBITDA) | {valuation['dcf_exit']['exit_multiple']:.1f}x |\n"
    dcf_exit_table += f"| Terminal Enterprise Value | {format_number(valuation['dcf_exit']['terminal_ev'])} |\n"
    dcf_exit_table += f"| Enterprise Value | {format_number(valuation['dcf_exit']['enterprise_value'])} |\n"
    dcf_exit_table += f"| Equity Value | {format_number(valuation['dcf_exit']['equity_value'])} |\n"
    dcf_exit_table += f"| Intrinsic Value per Share | {format_number(valuation['dcf_exit']['intrinsic_value_per_share'], 2)} |\n"
    
    # Summary
    summary_table = "| Metric | Value |\n"
    summary_table += "|--------|-------|\n"
    summary_table += f"| DCF Perpetual Intrinsic Value | {format_number(valuation['dcf_perpetual']['intrinsic_value_per_share'], 2)} |\n"
    summary_table += f"| DCF Exit Multiple Intrinsic Value | {format_number(valuation['dcf_exit']['intrinsic_value_per_share'], 2)} |\n"
    summary_table += f"| **Average Intrinsic Value** | **{format_number(valuation['summary']['average_intrinsic'], 2)}** |\n"
    summary_table += f"| Current Market Price | {format_number(company['current_price'], 2)} |\n"
    summary_table += f"| **Implied Upside** | **{format_percent(valuation['summary']['upside'])}** |\n"
    
    # Load prompt template and fill in variables
    prompt_template = load_prompt("report_valuation")
    prompt = prompt_template.format(
        company_name=company['company_name'],
        assumptions_table=assumptions_table,
        projections_table=projections_table,
        dcf_perp_table=dcf_perp_table,
        dcf_exit_table=dcf_exit_table,
        summary_table=summary_table
    )

    messages = [{"role": "user", "content": prompt}]
    response, cost = llm(messages, temperature=0.5)
    return response, cost


def generate_section_news_analysis(data: Dict[str, Any], llm) -> Tuple[str, float]:
    """Generate News & Market Analysis section with pre-built tables."""
    news = data['news']
    company = data['company_overview']
    
    # Build catalysts table from actual JSON data (no LLM hallucination)
    catalysts_table = "| Type | Description | Confidence | Timeline | Supporting Evidence |\n"
    catalysts_table += "|------|-------------|------------|----------|---------------------|\n"
    for c in news['catalysts']:
        evidence = "; ".join(c.get('supporting_evidence', [])[:2])  # First 2 pieces
        catalysts_table += f"| {c.get('type', 'N/A').title()} | {c.get('description', 'N/A')} | {c.get('confidence', 0):.0%} | {c.get('timeline', 'N/A').title()} | {evidence[:100]}... |\n"
    
    # Build risks table from actual JSON data
    risks_table = "| Type | Description | Severity | Likelihood | Confidence | Potential Impact |\n"
    risks_table += "|------|-------------|----------|------------|------------|------------------|\n"
    for r in news['risks']:
        impact = r.get('potential_impact', 'N/A')[:80]
        risks_table += f"| {r.get('type', 'N/A').title()} | {r.get('description', 'N/A')} | {r.get('severity', 'N/A').title()} | {r.get('likelihood', 'N/A').title()} | {r.get('confidence', 0):.0%} | {impact}... |\n"
    
    # Build mitigations table from actual JSON data
    mitigations_table = "| Risk Addressed | Mitigation Strategy | Effectiveness | Confidence | Company Action |\n"
    mitigations_table += "|----------------|---------------------|---------------|------------|----------------|\n"
    for m in news['mitigations']:
        risk = m.get('risk_addressed', 'N/A')[:50]
        strategy = m.get('strategy', 'N/A')[:60]
        action = m.get('company_action', 'N/A')[:60]
        mitigations_table += f"| {risk}... | {strategy}... | {m.get('effectiveness', 'N/A').title()} | {m.get('confidence', 0):.0%} | {action}... |\n"
    
    # Load prompt template and fill in variables
    prompt_template = load_prompt("report_news_analysis")
    prompt = prompt_template.format(
        company_name=company['company_name'],
        articles_analyzed=news['summary'].get('articles_analyzed', 0),
        overall_sentiment=news['summary'].get('overall_sentiment', 'neutral').upper(),
        confidence_score=f"{news['summary'].get('confidence_score', 0):.0%}",
        key_themes=', '.join(news['summary'].get('key_themes', [])),
        num_catalysts=len(news['catalysts']),
        catalysts_table=catalysts_table,
        num_risks=len(news['risks']),
        risks_table=risks_table,
        num_mitigations=len(news['mitigations']),
        mitigations_table=mitigations_table
    )

    messages = [{"role": "user", "content": prompt}]
    response, cost = llm(messages, temperature=0.5)
    return response, cost


def generate_section_investment_thesis(data: Dict[str, Any], llm) -> Tuple[str, float]:
    """Generate Investment Thesis section."""
    company = data['company_overview']
    valuation = data['valuation']
    news = data['news']
    
    # Load prompt template and fill in variables
    prompt_template = load_prompt("report_investment_thesis")
    prompt = prompt_template.format(
        company_name=company['company_name'],
        current_price=format_number(company['current_price'], 2),
        intrinsic_value=format_number(valuation['summary']['average_intrinsic'], 2),
        upside=format_percent(valuation['summary']['upside']),
        sentiment=news['summary'].get('overall_sentiment', 'neutral').upper(),
        num_catalysts=len(news['catalysts']),
        num_risks=len(news['risks'])
    )

    messages = [{"role": "user", "content": prompt}]
    response, cost = llm(messages, temperature=0.6)
    return response, cost


def generate_section_recommendation(data: Dict[str, Any], llm) -> Tuple[str, float]:
    """
    Generate Recommendation & Price Target section using LLM with quantitative foundation.
    
    Process:
    1. Calculate all quantitative metrics (valuation gap, catalyst scores, risk scores, momentum)
    2. Format structured input for LLM with all calculations shown
    3. LLM generates investment rating, multi-horizon targets, and detailed justification
    4. Return professional recommendation with transparent reasoning
    
    This approach provides:
    - Auditable calculations that analysts can verify
    - LLM reasoning and synthesis for professional judgment
    - Transparent justification linking decisions to data
    """
    company = data['company_overview']
    valuation = data['valuation']
    news = data['news']
    
    # Initialize recommendation engine with sector-specific parameters
    sector = company.get('sector', 'default')
    engine = RecommendationEngine(sector=sector)
    
    # Generate LLM-based recommendation with quantitative foundation
    recommendation_text, cost = engine.generate_recommendation(
        company_data=company,
        valuation_data=valuation,
        news_data=news,
        llm=llm
    )
    
    # Return recommendation and LLM cost
    return recommendation_text, cost


def generate_executive_summary(sections: Dict[str, str], data: Dict[str, Any], llm) -> Tuple[str, float]:
    """Generate Executive Summary based on all other sections."""
    company = data['company_overview']
    valuation = data['valuation']
    
    # Extract key points from recommendation section
    recommendation_preview = sections['recommendation'][:1000]
    
    # Load prompt template and fill in variables
    prompt_template = load_prompt("report_executive_summary")
    prompt = prompt_template.format(
        company_name=company['company_name'],
        intrinsic_value=format_number(valuation['summary']['average_intrinsic'], 2),
        current_price=format_number(company['current_price'], 2),
        upside=format_percent(valuation['summary']['upside']),
        recommendation_preview=recommendation_preview
    )

    messages = [{"role": "user", "content": prompt}]
    response, cost = llm(messages, temperature=0.5)
    return response, cost


def integrate_report_sections(sections: Dict[str, str], data: Dict[str, Any]) -> str:
    """Integrate all sections into final report with header/footer.
    
    This is a simple assembly function - no LLM call needed since sections
    are already comprehensive and well-formatted.
    """
    company = data['company_overview']
    report_date = datetime.now().strftime('%B %d, %Y')
    
    # Build complete report
    report_parts = []
    
    # Header
    report_parts.append(f"""# {company['company_name']} ({company['ticker']})
## Professional Investment Analysis Report

**Report Date**: {report_date}  
**Sector**: {company['sector']} | **Industry**: {company['industry']}  
**Exchange**: {company['exchange']}

---
""")
    
    # Table of Contents
    report_parts.append("""## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Company Overview](#company-overview)
3. [Financial Performance Analysis](#financial-performance-analysis)
4. [Financial Model & Valuation](#financial-model--valuation)
5. [News & Market Analysis](#news--market-analysis)
6. [Investment Thesis](#investment-thesis)
7. [Recommendation & Price Target](#recommendation--price-target)
8. [Appendix](#appendix)

---
""")
    
    # Executive Summary
    report_parts.append(f"""## Executive Summary

{sections['executive_summary']}

---
""")
    
    # Company Overview
    report_parts.append(f"""## Company Overview

{sections['company_overview']}

---
""")
    
    # Financial Performance
    report_parts.append(f"""## Financial Performance Analysis

{sections['financial_performance']}

---
""")
    
    # Valuation
    report_parts.append(f"""## Financial Model & Valuation

{sections['valuation']}

---
""")
    
    # News Analysis
    report_parts.append(f"""## News & Market Analysis

{sections['news_analysis']}

---
""")
    
    # Investment Thesis
    report_parts.append(f"""## Investment Thesis

{sections['investment_thesis']}

---
""")
    
    # Recommendation
    report_parts.append(f"""## Recommendation & Price Target

{sections['recommendation']}

---
""")
    
    # Appendix
    assumptions = data['assumptions']
    news = data['news']
    
    # Build detailed news appendix
    news_appendix = []
    
    # Catalysts with evidence
    news_appendix.append("### A. Detailed News Analysis\n")
    news_appendix.append(f"**Analysis Method**: {data.get('screening_method', 'LLM-based screening')}")
    news_appendix.append(f"**Articles Analyzed**: {news['summary'].get('articles_analyzed', 0)}")
    news_appendix.append(f"**Overall Sentiment**: {news['summary'].get('overall_sentiment', 'neutral').upper()} (Confidence: {news['summary'].get('confidence_score', 0):.0%})\n")
    
    news_appendix.append("#### Catalysts - Detailed Evidence\n")
    for i, catalyst in enumerate(news['catalysts'], 1):
        news_appendix.append(f"**{i}. {catalyst.get('description', 'N/A')}**")
        news_appendix.append(f"- **Type**: {catalyst.get('type', 'N/A').title()}")
        news_appendix.append(f"- **Timeline**: {catalyst.get('timeline', 'N/A').title()}")
        news_appendix.append(f"- **Confidence**: {catalyst.get('confidence', 0):.0%}")
        news_appendix.append(f"- **LLM Reasoning**: {catalyst.get('llm_reasoning', 'N/A')}")
        news_appendix.append(f"- **Potential Impact**: {catalyst.get('potential_impact', 'N/A')}")
        
        news_appendix.append(f"- **Supporting Evidence**:")
        for evidence in catalyst.get('supporting_evidence', []):
            news_appendix.append(f"  - {evidence}")
        
        if catalyst.get('direct_quotes'):
            news_appendix.append(f"- **Direct Quotes**:")
            for quote_obj in catalyst.get('direct_quotes', [])[:2]:  # First 2 quotes
                news_appendix.append(f"  - \"{quote_obj.get('quote', '')}\"")
                news_appendix.append(f"    - Source: [{quote_obj.get('source_article', 'N/A')}]({quote_obj.get('source_url', '#')})")
        
        news_appendix.append("")
    
    # Risks with evidence
    news_appendix.append("#### Risks - Detailed Evidence\n")
    for i, risk in enumerate(news['risks'], 1):
        news_appendix.append(f"**{i}. {risk.get('description', 'N/A')}**")
        news_appendix.append(f"- **Type**: {risk.get('type', 'N/A').title()}")
        news_appendix.append(f"- **Severity**: {risk.get('severity', 'N/A').title()}")
        news_appendix.append(f"- **Likelihood**: {risk.get('likelihood', 'N/A').title()}")
        news_appendix.append(f"- **Confidence**: {risk.get('confidence', 0):.0%}")
        news_appendix.append(f"- **LLM Reasoning**: {risk.get('llm_reasoning', 'N/A')}")
        news_appendix.append(f"- **Potential Impact**: {risk.get('potential_impact', 'N/A')}")
        
        news_appendix.append(f"- **Supporting Evidence**:")
        for evidence in risk.get('supporting_evidence', []):
            news_appendix.append(f"  - {evidence}")
        
        if risk.get('direct_quotes'):
            news_appendix.append(f"- **Direct Quotes**:")
            for quote_obj in risk.get('direct_quotes', [])[:2]:
                news_appendix.append(f"  - \"{quote_obj.get('quote', '')}\"")
                news_appendix.append(f"    - Source: [{quote_obj.get('source_article', 'N/A')}]({quote_obj.get('source_url', '#')})")
        
        news_appendix.append("")
    
    # Mitigations with evidence
    news_appendix.append("#### Risk Mitigations - Detailed Evidence\n")
    for i, mitigation in enumerate(news['mitigations'], 1):
        news_appendix.append(f"**{i}. {mitigation.get('strategy', 'N/A')}**")
        news_appendix.append(f"- **Risk Addressed**: {mitigation.get('risk_addressed', 'N/A')}")
        news_appendix.append(f"- **Effectiveness**: {mitigation.get('effectiveness', 'N/A').title()}")
        news_appendix.append(f"- **Confidence**: {mitigation.get('confidence', 0):.0%}")
        news_appendix.append(f"- **Company Action**: {mitigation.get('company_action', 'N/A')}")
        news_appendix.append(f"- **LLM Reasoning**: {mitigation.get('llm_reasoning', 'N/A')}")
        news_appendix.append(f"- **Implementation Timeline**: {mitigation.get('implementation_timeline', 'N/A')}")
        
        news_appendix.append(f"- **Supporting Evidence**:")
        for evidence in mitigation.get('supporting_evidence', []):
            news_appendix.append(f"  - {evidence}")
        
        if mitigation.get('direct_quotes'):
            news_appendix.append(f"- **Direct Quotes**:")
            for quote_obj in mitigation.get('direct_quotes', [])[:2]:
                news_appendix.append(f"  - \"{quote_obj.get('quote', '')}\"")
                news_appendix.append(f"    - Source: [{quote_obj.get('source_article', 'N/A')}]({quote_obj.get('source_url', '#')})")
        
        news_appendix.append("")
    
    report_parts.append(f"""## Appendix

{chr(10).join(news_appendix)}

### B. Key Model Assumptions

| Assumption | Value |
|-----------|-------|
| WACC | {format_percent(assumptions['wacc'])} |
| Terminal Growth Rate | {format_percent(assumptions['terminal_growth'])} |
| Revenue Growth (FY1) | {format_percent(assumptions['revenue_growth_rates'][0])} |
| Revenue Growth (FY2) | {format_percent(assumptions['revenue_growth_rates'][1])} |
| Revenue Growth (FY3) | {format_percent(assumptions['revenue_growth_rates'][2])} |
| Revenue Growth (FY4) | {format_percent(assumptions['revenue_growth_rates'][3])} |
| Revenue Growth (FY5) | {format_percent(assumptions['revenue_growth_rates'][4])} |
| EBITDA Margin (FY1) | {format_percent(assumptions['ebitda_margins'][0])} |
| EBITDA Margin (FY2) | {format_percent(assumptions['ebitda_margins'][1])} |
| EBITDA Margin (FY3) | {format_percent(assumptions['ebitda_margins'][2])} |
| EBITDA Margin (FY4) | {format_percent(assumptions['ebitda_margins'][3])} |
| EBITDA Margin (FY5) | {format_percent(assumptions['ebitda_margins'][4])} |

### C. Disclaimers

This report is for informational purposes only and should not be considered as investment advice. 
The analysis is based on publicly available information and proprietary financial modeling. Past 
performance does not guarantee future results. Investors should conduct their own due diligence 
and consult with financial advisors before making investment decisions.

**Data Sources**: Financial data from yfinance, news analysis from article screening ({news['summary'].get('articles_analyzed', 0)} articles), 
valuation based on DCF modeling with LLM-inferred assumptions.

---

*Report generated on {report_date}*
""")
    
    return "\n".join(report_parts)


def generate_professional_report(
    financial_json_path: Path,
    computed_values_json_path: Path,
    screening_json_path: Path,
    logger: Optional[StockAnalystLogger] = None
) -> str:
    """Generate comprehensive professional report using LLM.
    
    Args:
        financial_json_path: Path to financials_annual_modeling_latest.json
        computed_values_json_path: Path to *_computed_values.json
        screening_json_path: Path to screening_data.json
        logger: Optional logger instance
        
    Returns:
        Complete markdown report
    """
    if logger:
        logger.info("="*70)
        logger.info("Generating Professional Financial Report")
        logger.info("="*70)
    
    # Step 1: Load all data
    if logger:
        logger.info("Loading data files...")
    
    financial_data = load_financial_json(financial_json_path)
    computed_values = load_computed_values_json(computed_values_json_path)
    screening_data = load_screening_json(screening_json_path)
    
    if logger:
        logger.info("✅ Loaded all data files")
    
    # Step 2: Extract structured data
    if logger:
        logger.info("Extracting structured data...")
    
    data = {
        'company_overview': extract_company_overview(financial_data),
        'historical': extract_historical_financials(financial_data),
        'assumptions': extract_model_assumptions(computed_values),
        'projections': extract_projections(computed_values),
        'valuation': extract_valuation(computed_values),
        'news': extract_news_analysis(screening_data),
    }
    
    if logger:
        logger.info("✅ Extracted structured data")
    
    # Step 3: Get LLM instance
    llm = get_llm()
    total_cost = 0.0
    sections = {}
    
    # Step 4: Generate sections iteratively
    if logger:
        logger.info("Generating report sections...")
    
    # Section 1: Company Overview
    if logger:
        logger.info("  1/7 Generating Company Overview...")
    section, cost = generate_section_company_overview(data, llm)
    sections['company_overview'] = section
    total_cost += cost
    if logger:
        logger.info(f"     ✅ Complete (cost: ${cost:.4f})")
    
    # Section 2: Financial Performance
    if logger:
        logger.info("  2/7 Generating Financial Performance Analysis...")
    section, cost = generate_section_financial_performance(data, llm)
    sections['financial_performance'] = section
    total_cost += cost
    if logger:
        logger.info(f"     ✅ Complete (cost: ${cost:.4f})")
    
    # Section 3: Valuation
    if logger:
        logger.info("  3/7 Generating Financial Model & Valuation...")
    section, cost = generate_section_valuation(data, llm)
    sections['valuation'] = section
    total_cost += cost
    if logger:
        logger.info(f"     ✅ Complete (cost: ${cost:.4f})")
    
    # Section 4: News Analysis
    if logger:
        logger.info("  4/7 Generating News & Market Analysis...")
    section, cost = generate_section_news_analysis(data, llm)
    sections['news_analysis'] = section
    total_cost += cost
    if logger:
        logger.info(f"     ✅ Complete (cost: ${cost:.4f})")
    
    # Section 5: Investment Thesis
    if logger:
        logger.info("  5/7 Generating Investment Thesis...")
    section, cost = generate_section_investment_thesis(data, llm)
    sections['investment_thesis'] = section
    total_cost += cost
    if logger:
        logger.info(f"     ✅ Complete (cost: ${cost:.4f})")
    
    # Section 6: Recommendation
    if logger:
        logger.info("  6/7 Generating Recommendation & Price Target...")
    section, cost = generate_section_recommendation(data, llm)
    sections['recommendation'] = section
    total_cost += cost
    if logger:
        logger.info(f"     ✅ Complete (cost: ${cost:.4f})")
    
    # Section 7: Executive Summary (generated last, needs other sections)
    if logger:
        logger.info("  7/7 Generating Executive Summary...")
    section, cost = generate_executive_summary(sections, data, llm)
    sections['executive_summary'] = section
    total_cost += cost
    if logger:
        logger.info(f"     ✅ Complete (cost: ${cost:.4f})")
    
    # Step 5: Integrate all sections
    if logger:
        logger.info("Integrating all sections into final report...")
    
    final_report = integrate_report_sections(sections, data)
    
    if logger:
        logger.info(f"✅ Report integrated (total cost: ${total_cost:.4f})")
    
    return final_report


def save_professional_report(
    report: str,
    output_dir: Path,
    ticker: str,
    logger: Optional[StockAnalystLogger] = None
) -> Path:
    """Save report to markdown file.
    
    Args:
        report: Generated report content
        output_dir: Directory to save report
        ticker: Stock ticker
        logger: Optional logger
        
    Returns:
        Path to saved report
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{ticker}_Professional_Analysis_Report.md"
    report_path = output_dir / filename
    
    with open(report_path, 'w') as f:
        f.write(report)
    
    if logger:
        logger.info(f"✅ Report saved to: {report_path}")
        logger.info(f"   • File size: {report_path.stat().st_size:,} bytes")
    
    return report_path


def generate_and_save_professional_report(
    analysis_path: Path,
    ticker: str,
    logger: Optional[StockAnalystLogger] = None
) -> Tuple[str, Path]:
    """Main entry point: Generate and save professional report.
    
    Args:
        analysis_path: Path to analysis folder (e.g., data/email/ticker/timestamp/)
        ticker: Stock ticker
        logger: Optional logger
        
    Returns:
        Tuple of (report_content, report_file_path)
    """
    # Define paths
    financials_path = analysis_path / "financials" / "financials_annual_modeling_latest.json"
    computed_values_path = analysis_path / "models" / f"{ticker}_financial_model_computed_values.json"
    screening_path = analysis_path / "screened" / "screening_data.json"
    report_output_dir = analysis_path / "reports"
    
    # Validate paths
    if not financials_path.exists():
        raise FileNotFoundError(f"Financial data not found: {financials_path}")
    if not computed_values_path.exists():
        raise FileNotFoundError(f"Computed values not found: {computed_values_path}")
    if not screening_path.exists():
        raise FileNotFoundError(f"Screening data not found: {screening_path}")
    
    # Generate report
    report = generate_professional_report(
        financial_json_path=financials_path,
        computed_values_json_path=computed_values_path,
        screening_json_path=screening_path,
        logger=logger
    )
    
    # Save report
    report_path = save_professional_report(
        report=report,
        output_dir=report_output_dir,
        ticker=ticker,
        logger=logger
    )
    
    if logger:
        logger.info("="*70)
        logger.info("✅ PROFESSIONAL REPORT GENERATION COMPLETE")
        logger.info("="*70)
    
    return report, report_path


def main():
    """Main function for standalone execution."""
    import argparse

    parser = argparse.ArgumentParser(description="Generate Professional Financial Report")
    parser.add_argument("--analysis_path", type=str, required=True, help="Path to analysis folder")
    parser.add_argument("--ticker", type=str, required=True, help="Stock ticker symbol")
    args = parser.parse_args()

    # logger = StockAnalystLogger()
    generate_and_save_professional_report(
        analysis_path=Path(args.analysis_path),
        ticker=args.ticker,
    )

if __name__ == "__main__":
    main()
