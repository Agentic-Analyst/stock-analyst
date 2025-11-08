#!/usr/bin/env python3
"""
financial_summary_agent.py - Financial Model & Data Summary Generator

Generates a comprehensive summary of financial data and model results without
requiring a full report. This agent can be used standalone or as part of a
larger workflow.

Key Features:
1. Loads financial data and computed model values from JSON files
2. Extracts key metrics, valuation results, and projections
3. Uses LLM to generate professional narrative summary
4. Can be used by supervisor to provide quick financial insights

Data Sources:
- financial_json: financials_annual_modeling_latest.json (company info, historical data)
- computed_values_json: *_computed_values.json (evaluated financial model)

Output: Markdown-formatted financial summary
"""

from __future__ import annotations
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
import json

from llms.config import get_llm
from logger import StockAnalystLogger

def load_prompt(prompt_name: str) -> str:
    """Load a prompt template from the prompts folder."""
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


def format_number(num, decimals=2):
    """Format number with commas and appropriate unit suffix."""
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
        'current_price': market_data.get('current_price', 0),
        'market_cap': market_data.get('market_cap', 0),
        'enterprise_value': market_data.get('enterprise_value', 0),
        'pe_trailing': valuation_metrics.get('pe_ratio_trailing', 0),
        'pe_forward': valuation_metrics.get('pe_ratio_forward', 0),
        'price_to_book': valuation_metrics.get('price_to_book', 0),
        'ev_to_ebitda': valuation_metrics.get('enterprise_to_ebitda', 0),
        'debt_to_equity': capital_structure.get('debt_to_equity', 0),
        'gross_margin': growth_profitability.get('gross_margins', 0),
        'operating_margin': growth_profitability.get('operating_margins', 0),
        'ebitda_margin': growth_profitability.get('ebitda_margins', 0),
        'net_margin': growth_profitability.get('profit_margins', 0),
        'roe': growth_profitability.get('return_on_equity', 0),
        'revenue_growth': growth_profitability.get('revenue_growth', 0),
        'target_mean_price': forward_guidance.get('target_mean_price', 0),
    }


def extract_historical_financials(financial_data: Dict[str, Any]) -> Dict[str, Any]:
    """Extract 5-year historical financial statements."""
    statements = financial_data.get('financial_statements', {})
    income_statement = statements.get('income_statement', {})
    balance_sheet = statements.get('balance_sheet', {})
    cash_flow = statements.get('cash_flow', {})
    
    years = sorted(income_statement.keys())
    
    historical = {
        'years': years,
        'revenue': [],
        'gross_profit': [],
        'ebitda': [],
        'net_income': [],
        'fcf': [],
    }
    
    for year in years:
        is_data = income_statement.get(year, {})
        cf_data = cash_flow.get(year, {})
        
        historical['revenue'].append(is_data.get('Total Revenue', 0) or is_data.get('Operating Revenue', 0))
        historical['gross_profit'].append(is_data.get('Gross Profit', 0))
        historical['ebitda'].append(is_data.get('EBITDA', 0))
        historical['net_income'].append(is_data.get('Net Income', 0))
        historical['fcf'].append(cf_data.get('Free Cash Flow', 0))
    
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
        'ebitda_margins': [
            llm_inferred.get('(6, 2)', 0),
            llm_inferred.get('(6, 3)', 0),
            llm_inferred.get('(6, 4)', 0),
            llm_inferred.get('(6, 5)', 0),
            llm_inferred.get('(6, 6)', 0),
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
    """Extract valuation results from Summary tab."""
    summary = computed_values.get('Summary', {}).get('cells', {})
    
    return {
        'dcf_intrinsic': summary.get('(18, 2)', 0),
        'exit_intrinsic': summary.get('(22, 2)', 0),
        'average_intrinsic': summary.get('(26, 2)', 0),
        'upside': summary.get('(27, 2)', 0),
        'current_price': summary.get('(9, 2)', 0),
    }


def generate_financial_summary(
    financial_json_path: Path,
    computed_values_json_path: Path,
    logger: Optional[StockAnalystLogger] = None
) -> Tuple[str, float]:
    """
    Generate comprehensive financial model and data summary.
    
    Args:
        financial_json_path: Path to financials_annual_modeling_latest.json
        computed_values_json_path: Path to *_computed_values.json
        logger: Optional logger instance
        
    Returns:
        Tuple of (summary_markdown, llm_cost)
    """
    if logger:
        logger.info("="*70)
        logger.info("Generating Financial Model Summary")
        logger.info("="*70)
    
    # Load data
    if logger:
        logger.info("Loading financial data and model results...")
    
    financial_data = load_financial_json(financial_json_path)
    computed_values = load_computed_values_json(computed_values_json_path)
    
    # Extract structured data
    company = extract_company_overview(financial_data)
    historical = extract_historical_financials(financial_data)
    assumptions = extract_model_assumptions(computed_values)
    projections = extract_projections(computed_values)
    valuation = extract_valuation(computed_values)
    
    if logger:
        logger.info("✅ Data extracted successfully")
        logger.info(f"   Company: {company['company_name']} ({company['ticker']})")
        logger.info(f"   Current Price: {format_number(company['current_price'], 2)}")
        logger.info(f"   Model Fair Value: {format_number(valuation['average_intrinsic'], 2)}")
    
    # Build comprehensive data tables for LLM
    
    # Historical Performance Table
    years = historical['years']
    hist_table = "| Year | Revenue | EBITDA | Net Income | FCF |\n"
    hist_table += "|------|---------|--------|------------|-----|\n"
    for i, year in enumerate(years):
        hist_table += f"| {year} | {format_number(historical['revenue'][i])} | {format_number(historical['ebitda'][i])} | {format_number(historical['net_income'][i])} | {format_number(historical['fcf'][i])} |\n"
    
    # Calculate growth rates
    latest_revenue = historical['revenue'][-1]
    oldest_revenue = historical['revenue'][0]
    years_span = len(years) - 1
    revenue_cagr = ((latest_revenue / oldest_revenue) ** (1/years_span) - 1) if oldest_revenue and years_span > 0 else 0
    
    # Key Metrics Table
    metrics_table = "| Metric | Value |\n"
    metrics_table += "|--------|-------|\n"
    metrics_table += f"| Current Price | {format_number(company['current_price'], 2)} |\n"
    metrics_table += f"| Market Cap | {format_number(company['market_cap'])} |\n"
    metrics_table += f"| P/E Ratio (TTM) | {company['pe_trailing']:.2f}x |\n"
    metrics_table += f"| EV/EBITDA | {company['ev_to_ebitda']:.2f}x |\n"
    metrics_table += f"| Gross Margin | {format_percent(company['gross_margin'])} |\n"
    metrics_table += f"| EBITDA Margin | {format_percent(company['ebitda_margin'])} |\n"
    metrics_table += f"| Net Margin | {format_percent(company['net_margin'])} |\n"
    metrics_table += f"| ROE | {format_percent(company['roe'])} |\n"
    metrics_table += f"| Revenue CAGR ({years_span}Y) | {format_percent(revenue_cagr)} |\n"
    
    # Model Assumptions Table
    assumptions_table = "| Assumption | Value |\n"
    assumptions_table += "|------------|-------|\n"
    assumptions_table += f"| WACC | {format_percent(assumptions['wacc'])} |\n"
    assumptions_table += f"| Terminal Growth | {format_percent(assumptions['terminal_growth'])} |\n"
    assumptions_table += f"| Revenue Growth (FY1-FY5) | {format_percent(assumptions['revenue_growth_rates'][0])}, {format_percent(assumptions['revenue_growth_rates'][1])}, {format_percent(assumptions['revenue_growth_rates'][2])}, {format_percent(assumptions['revenue_growth_rates'][3])}, {format_percent(assumptions['revenue_growth_rates'][4])} |\n"
    assumptions_table += f"| EBITDA Margin (FY1-FY5) | {format_percent(assumptions['ebitda_margins'][0])}, {format_percent(assumptions['ebitda_margins'][1])}, {format_percent(assumptions['ebitda_margins'][2])}, {format_percent(assumptions['ebitda_margins'][3])}, {format_percent(assumptions['ebitda_margins'][4])} |\n"
    
    # Projections Table
    proj_table = "| FY | Revenue | EBITDA | FCF |\n"
    proj_table += "|----|---------|--------|-----|\n"
    for i in range(5):
        proj_table += f"| FY{i+1} | {format_number(projections['revenue'][i])} | {format_number(projections['ebitda'][i])} | {format_number(projections['fcf'][i])} |\n"
    
    # Valuation Summary Table
    val_table = "| Method | Intrinsic Value |\n"
    val_table += "|--------|----------------|\n"
    val_table += f"| DCF Perpetual Growth | {format_number(valuation['dcf_intrinsic'], 2)} |\n"
    val_table += f"| DCF Exit Multiple | {format_number(valuation['exit_intrinsic'], 2)} |\n"
    val_table += f"| **Average Fair Value** | **{format_number(valuation['average_intrinsic'], 2)}** |\n"
    val_table += f"| Current Price | {format_number(company['current_price'], 2)} |\n"
    val_table += f"| **Implied Upside/Downside** | **{format_percent(valuation['upside'])}** |\n"
    
    # Generate LLM summary
    if logger:
        logger.info("Generating narrative summary with LLM...")
    
    prompt = f"""You are a professional financial analyst. Generate a comprehensive but concise financial summary for {company['company_name']} ({company['ticker']}).

**Company Overview:**
- Sector: {company['sector']}
- Industry: {company['industry']}

**Historical Performance ({years[0]} - {years[-1]}):**
{hist_table}

**Current Valuation Metrics:**
{metrics_table}

**DCF Model Assumptions:**
{assumptions_table}

**5-Year Projections:**
{proj_table}

**Valuation Results:**
{val_table}

**Instructions:**
1. Start with a 2-sentence overview of the company's current financial position
2. Analyze historical performance trends (growth, margins, profitability)
3. Explain the DCF model assumptions and their reasonableness
4. Discuss the 5-year projections and growth trajectory
5. Present the valuation conclusion (fair value vs current price)
6. Highlight 3-5 key financial strengths or concerns

Be professional, data-driven, and balanced. Use the exact numbers from the tables above. Keep it under 500 words.

Format your response in clear sections with markdown headers (###).
"""
    
    llm = get_llm()
    messages = [{"role": "user", "content": prompt}]
    response, cost = llm(messages, temperature=0.5)
    
    if logger:
        logger.info(f"✅ Summary generated (cost: ${cost:.4f})")
    
    # Build final summary with both tables and narrative
    summary = f"""# Financial Model & Data Summary: {company['company_name']} ({company['ticker']})

**Generated:** {datetime.now().strftime('%B %d, %Y')}

---

## Quick Overview

| Metric | Value |
|--------|-------|
| Current Price | {format_number(company['current_price'], 2)} |
| Model Fair Value | {format_number(valuation['average_intrinsic'], 2)} |
| Implied Upside/Downside | {format_percent(valuation['upside'])} |
| Market Cap | {format_number(company['market_cap'])} |
| P/E Ratio | {company['pe_trailing']:.2f}x |

---

{response}

---

## Detailed Tables

### Historical Performance
{hist_table}

### Model Assumptions
{assumptions_table}

### 5-Year Projections
{proj_table}

### Valuation Summary
{val_table}

---

*This summary is based on financial data and DCF model results. For complete analysis including news and recommendation, see the full report.*
"""
    
    if logger:
        logger.info("="*70)
        logger.info("✅ FINANCIAL SUMMARY GENERATION COMPLETE")
        logger.info("="*70)
    
    return summary, cost


def generate_and_save_financial_summary(
    analysis_path: Path,
    ticker: str,
    logger: Optional[StockAnalystLogger] = None
) -> Tuple[str, Path, float]:
    """
    Main entry point: Generate and save financial summary.
    
    Args:
        analysis_path: Path to analysis folder (e.g., data/email/ticker/timestamp/)
        ticker: Stock ticker
        logger: Optional logger
        
    Returns:
        Tuple of (summary_content, summary_file_path, llm_cost)
    """
    # Define paths
    financials_path = analysis_path / "financials" / "financials_annual_modeling_latest.json"
    computed_values_path = analysis_path / "models" / f"{ticker}_financial_model_computed_values.json"
    summary_output_dir = analysis_path / "summaries"
    
    # Validate paths
    if not financials_path.exists():
        raise FileNotFoundError(f"Financial data not found: {financials_path}")
    if not computed_values_path.exists():
        raise FileNotFoundError(f"Computed values not found: {computed_values_path}")
    
    # Generate summary
    summary, cost = generate_financial_summary(
        financial_json_path=financials_path,
        computed_values_json_path=computed_values_path,
        logger=logger
    )
    
    # Save summary
    summary_output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = summary_output_dir / f"{ticker}_financial_summary.md"
    
    with open(summary_path, 'w') as f:
        f.write(summary)
    
    if logger:
        logger.info(f"✅ Summary saved to: {summary_path}")
        logger.info(f"   • File size: {summary_path.stat().st_size:,} bytes")
    
    return summary, summary_path, cost

