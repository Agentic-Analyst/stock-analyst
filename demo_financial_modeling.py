#!/usr/bin/env python3
"""
Financial Modeling Data Demo
Shows how to use the comprehensive financial data for actual financial modeling
"""

import json
import pandas as pd
from pathlib import Path

def load_modeling_data(ticker: str) -> dict:
    """Load the comprehensive financial modeling data for a ticker."""
    data_path = Path(f"data/{ticker}/financials/financials_annual_modeling_latest.json")
    
    if not data_path.exists():
        print(f"❌ No modeling data found for {ticker}")
        print(f"Run: python src/financial_scraper.py --ticker {ticker} --statements modeling --save")
        return {}
    
    with open(data_path, 'r') as f:
        return json.load(f)

def demonstrate_dcf_inputs(ticker: str):
    """Demonstrate how to extract DCF model inputs from scraped data."""
    print(f"🏗️ DCF Model Inputs for {ticker}")
    print("=" * 50)
    
    data = load_modeling_data(ticker)
    if not data:
        return
    
    # Extract company information
    company_name = data['company_data']['basic_info']['long_name']
    industry = data['company_data']['basic_info']['industry']
    print(f"📊 Company: {company_name} ({industry})")
    
    # 1. Historical Revenue and Growth
    income_statements = data['financial_statements']['income_statement']
    years = sorted(income_statements.keys(), reverse=True)
    
    print("\n💰 Historical Revenue Analysis:")
    revenues = []
    for year in years:
        # Use the robust fallback system
        revenue_keys = ["Total Revenue", "TotalRevenues", "totalRevenue", "Revenue"]
        revenue = None
        for key in revenue_keys:
            if key in income_statements[year] and income_statements[year][key]:
                revenue = income_statements[year][key]
                break
        
        if revenue:
            revenues.append((year, revenue))
            print(f"  {year}: ${revenue/1e9:.1f}B")
    
    # Calculate revenue growth rates
    growth_rates = data['modeling_metrics']['historical_growth_rates'].get('revenue_growth', {})
    avg_growth = growth_rates.get('average_growth')
    if avg_growth:
        print(f"  📈 Average Growth Rate: {avg_growth:.1%}")
    
    # 2. Free Cash Flow Analysis
    print("\n💵 Free Cash Flow Analysis:")
    cash_flows = data['financial_statements']['cash_flow']
    fcf_data = []
    
    for year in years:
        if year in cash_flows:
            # Get operating cash flow and capex
            ocf_keys = ["Operating Cash Flow", "OperatingCashFlow", "operatingCashFlow"]
            capex_keys = ["Capital Expenditure", "CapitalExpenditure", "capitalExpenditure"]
            
            ocf = None
            capex = None
            
            for key in ocf_keys:
                if key in cash_flows[year] and cash_flows[year][key]:
                    ocf = cash_flows[year][key]
                    break
            
            for key in capex_keys:
                if key in cash_flows[year] and cash_flows[year][key]:
                    capex = cash_flows[year][key]
                    break
            
            # Calculate FCF
            if ocf and capex:
                fcf = ocf + capex  # capex is negative
                fcf_data.append((year, fcf))
                print(f"  {year}: ${fcf/1e9:.1f}B (OCF: ${ocf/1e9:.1f}B, CapEx: ${capex/1e9:.1f}B)")
    
    # 3. Margin Analysis
    print("\n📊 Profitability Margins:")
    ratios = data['modeling_metrics']['financial_ratios']['profitability']
    for margin_type, value in ratios.items():
        if value:
            print(f"  {margin_type.replace('_', ' ').title()}: {value:.1%}")
    
    # 4. Working Capital Analysis
    print("\n💼 Working Capital Analysis:")
    wc_metrics = data['modeling_metrics']['working_capital_metrics']
    for metric, value in wc_metrics.items():
        if value:
            if 'percent' in metric:
                print(f"  {metric.replace('_', ' ').title()}: {value:.1%}")
            elif 'ratio' in metric:
                print(f"  {metric.replace('_', ' ').title()}: {value:.2f}x")
            else:
                print(f"  {metric.replace('_', ' ').title()}: ${value/1e9:.1f}B")
    
    # 5. Capital Structure for WACC
    print("\n🏛️ Capital Structure (for WACC calculation):")
    capital_structure = data['company_data']['capital_structure']
    market_data = data['company_data']['market_data']
    
    market_cap = market_data.get('market_cap')
    total_debt = capital_structure.get('total_debt')
    beta = capital_structure.get('beta')
    
    if market_cap:
        print(f"  Market Cap: ${market_cap/1e9:.1f}B")
    if total_debt:
        print(f"  Total Debt: ${total_debt/1e9:.1f}B")
    if beta:
        print(f"  Beta: {beta:.2f}")
    
    # 6. Valuation Multiples for Sanity Check
    print("\n🎯 Valuation Multiples (for sanity check):")
    valuation = data['company_data']['valuation_metrics']
    multiples = ['pe_ratio_trailing', 'pe_ratio_forward', 'price_to_book', 'price_to_sales']
    
    for multiple in multiples:
        value = valuation.get(multiple)
        if value:
            print(f"  {multiple.replace('_', ' ').title()}: {value:.1f}x")
    
    print(f"\n✅ DCF model inputs ready for {ticker}!")
    print("💡 Next steps: Build forecast assumptions and calculate terminal value")

def demonstrate_comparable_analysis(tickers: list):
    """Demonstrate comparable company analysis using multiple tickers."""
    print("🔍 Comparable Company Analysis")
    print("=" * 40)
    
    comparison_data = []
    
    for ticker in tickers:
        data = load_modeling_data(ticker)
        if not data:
            continue
        
        # Extract key metrics for comparison
        company_name = data['company_data']['basic_info']['long_name']
        industry = data['company_data']['basic_info']['industry']
        
        # Financial ratios
        ratios = data['modeling_metrics']['financial_ratios']
        profitability = ratios.get('profitability', {})
        efficiency = ratios.get('efficiency', {})
        
        # Growth rates
        growth = data['modeling_metrics']['historical_growth_rates']
        revenue_growth = growth.get('revenue_growth', {}).get('average_growth')
        
        # Valuation multiples
        valuation = data['company_data']['valuation_metrics']
        
        comparison_data.append({
            'Ticker': ticker,
            'Company': company_name,
            'Industry': industry,
            'Revenue Growth': f"{revenue_growth:.1%}" if revenue_growth else "N/A",
            'Gross Margin': f"{profitability.get('gross_margin', 0):.1%}",
            'Operating Margin': f"{profitability.get('operating_margin', 0):.1%}",
            'Net Margin': f"{profitability.get('net_margin', 0):.1%}",
            'ROA': f"{efficiency.get('roa', 0):.1%}",
            'P/E Ratio': f"{valuation.get('pe_ratio_trailing', 0):.1f}x" if valuation.get('pe_ratio_trailing') else "N/A",
            'P/B Ratio': f"{valuation.get('price_to_book', 0):.1f}x" if valuation.get('price_to_book') else "N/A"
        })
    
    if comparison_data:
        # Create DataFrame for nice formatting
        df = pd.DataFrame(comparison_data)
        print(df.to_string(index=False))
        print(f"\n✅ Comparable analysis ready for {len(tickers)} companies!")

def main():
    """Demonstrate comprehensive financial modeling data usage."""
    print("🎯 Financial Modeling Data Demonstration")
    print("=" * 60)
    
    # Single company DCF analysis
    demonstrate_dcf_inputs("NVDA")
    
    print("\n" + "=" * 60)
    
    # Comparable company analysis
    tickers = ["NVDA", "AAPL"]  # Add more tickers as needed
    demonstrate_comparable_analysis(tickers)
    
    print("\n🚀 Financial modeling dataset is production-ready!")
    print("💡 Use this data for:")
    print("  • DCF (Discounted Cash Flow) models")
    print("  • LBO (Leveraged Buyout) analysis") 
    print("  • Comparable company analysis")
    print("  • Sum-of-the-parts valuation")
    print("  • Scenario and sensitivity analysis")

if __name__ == "__main__":
    main()
