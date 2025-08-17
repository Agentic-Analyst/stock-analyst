#!/usr/bin/env python3
"""
financial_scraper.py - Financial statements scraper for stock analysis.

This module provides the FinancialScraper class for collecting and storing financial
statements data from Yahoo Finance API. Designed to extract precise numerical data
for financial modeling and analysis.

▶ Usage:
    python src/financial_scraper.py --ticker NVDA --statements all
    python src/financial_scraper.py --ticker AAPL --statements all --quarterly --save
"""

from __future__ import annotations
import os, json, argparse, pathlib, time
from datetime import datetime, date
from typing import Dict, List, Optional, Any, Union
import pandas as pd
import numpy as np

# Financial data libraries
try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False
    print("Warning: yfinance not installed. Install with: pip install yfinance")

# Use environment variable for data path, default to local development
DATA_ROOT = pathlib.Path(os.getenv('DATA_PATH', 'data'))

class FinancialScraper:
    """Financial statements scraper for collecting precise financial data."""
    
    def __init__(self, ticker: str):
        """
        Initialize the financial scraper for a specific stock.
        
        Args:
            ticker: Stock ticker symbol (e.g., 'NVDA')
        """
        self.ticker = ticker.upper()
        self.company_dir = DATA_ROOT / self.ticker
        self.financials_dir = self.company_dir / "financials"
        
        # Logger - will be set by pipeline if available
        self.logger = None
        
        # Statistics tracking
        self.scraped_statements = 0
        self.failed_statements = 0
        self.data_points_extracted = 0
        
        # Yahoo Finance ticker object
        if YFINANCE_AVAILABLE:
            self.yf_ticker = yf.Ticker(self.ticker)
        else:
            raise RuntimeError("yfinance is required but not installed. Install with: pip install yfinance")
    
    def set_logger(self, logger):
        """Set the logger instance."""
        self.logger = logger
    
    def _log(self, level: str, message: str):
        """Log message using logger if available, otherwise print."""
        if self.logger:
            getattr(self.logger, level)(message)
        else:
            print(f"[{level.upper()}] {message}")
    
    def _ensure_directories(self):
        """Create necessary directories."""
        self.company_dir.mkdir(parents=True, exist_ok=True)
        self.financials_dir.mkdir(parents=True, exist_ok=True)
    
    def _clean_financial_data(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Clean and structure financial data from pandas DataFrame.
        
        Args:
            df: Raw financial DataFrame from yfinance
            
        Returns:
            Cleaned dictionary with properly formatted financial data
        """
        if df is None or df.empty:
            return {}
        
        # Convert DataFrame to dictionary with date keys
        cleaned_data = {}
        available_periods = []
        
        for column in df.columns:
            # Convert pandas Timestamp to string for JSON serialization
            date_key = column.strftime('%Y-%m-%d') if hasattr(column, 'strftime') else str(column)
            available_periods.append(date_key)
            
            period_data = {}
            for index, value in df[column].items():
                # Handle different data types
                if pd.isna(value):
                    clean_value = None
                elif isinstance(value, (np.integer, int)):
                    clean_value = int(value)
                elif isinstance(value, (np.floating, float)):
                    clean_value = float(value)
                else:
                    clean_value = str(value)
                
                # Clean up the metric name
                metric_name = str(index).strip()
                period_data[metric_name] = clean_value
                
                if clean_value is not None:
                    self.data_points_extracted += 1
            
            cleaned_data[date_key] = period_data
        
        # Log available periods for user visibility
        if available_periods:
            periods_str = ", ".join(sorted(available_periods, reverse=True))
            self._log("info", f"   Available periods: {periods_str}")
        
        return cleaned_data
    
    def _find_metric_with_fallbacks(self, data: Dict[str, Any], primary_keys: List[str]) -> Optional[Any]:
        """
        Find a metric value using multiple potential key names.
        
        Args:
            data: Dictionary to search in
            primary_keys: List of potential key names to try
            
        Returns:
            The first matching value found, or None if not found
        """
        for key in primary_keys:
            if key in data and data[key] is not None:
                return data[key]
        return None
    
    def _extract_key_metrics(self, financials_data: Dict) -> Dict[str, Any]:
        """
        Extract key financial metrics for modeling with robust label matching.
        
        Args:
            financials_data: Complete financial statements data
            
        Returns:
            Dictionary of key metrics organized by category
        """
        key_metrics = {
            "revenue_metrics": {},
            "profitability_metrics": {},
            "balance_sheet_metrics": {},
            "cash_flow_metrics": {},
            "per_share_metrics": {},
            "growth_rates": {},
            "ratios": {}
        }
        
        try:
            # Get the latest period data for each statement type
            income_data = financials_data.get('income_statement', {})
            balance_data = financials_data.get('balance_sheet', {})
            cashflow_data = financials_data.get('cash_flow', {})
            
            if not income_data and not balance_data and not cashflow_data:
                return key_metrics
            
            # Get latest period data
            latest_income = {}
            latest_balance = {}
            latest_cashflow = {}
            
            if income_data:
                latest_date = max(income_data.keys())
                latest_income = income_data[latest_date]
                
            if balance_data:
                latest_date = max(balance_data.keys())
                latest_balance = balance_data[latest_date]
                
            if cashflow_data:
                latest_date = max(cashflow_data.keys())
                latest_cashflow = cashflow_data[latest_date]
            
            # Extract revenue metrics with fallback keys
            key_metrics["revenue_metrics"] = {
                "total_revenue": self._find_metric_with_fallbacks(
                    latest_income, ["Total Revenue", "TotalRevenues", "totalRevenue", "Revenue"]
                ),
                "cost_of_revenue": self._find_metric_with_fallbacks(
                    latest_income, ["Cost Of Revenue", "CostOfRevenue", "costOfRevenue", "Cost of Sales"]
                ),
                "gross_profit": self._find_metric_with_fallbacks(
                    latest_income, ["Gross Profit", "GrossProfit", "grossProfit"]
                ),
                "operating_revenue": self._find_metric_with_fallbacks(
                    latest_income, ["Operating Revenue", "OperatingRevenue", "operatingRevenue"]
                )
            }
            
            # Extract profitability metrics with fallback keys
            key_metrics["profitability_metrics"] = {
                "gross_profit": self._find_metric_with_fallbacks(
                    latest_income, ["Gross Profit", "GrossProfit", "grossProfit"]
                ),
                "operating_income": self._find_metric_with_fallbacks(
                    latest_income, ["Operating Income", "OperatingIncome", "operatingIncome", "EBIT"]
                ),
                "ebitda": self._find_metric_with_fallbacks(
                    latest_income, ["EBITDA", "Normalized EBITDA", "NormalizedEBITDA"]
                ),
                "net_income": self._find_metric_with_fallbacks(
                    latest_income, ["Net Income", "NetIncome", "netIncome", "Net Income Common Stockholders"]
                ),
                "pretax_income": self._find_metric_with_fallbacks(
                    latest_income, ["Pretax Income", "PretaxIncome", "pretaxIncome", "Income Before Tax", "Earnings Before Tax"]
                )
            }
            
            # Extract balance sheet metrics with fallback keys
            key_metrics["balance_sheet_metrics"] = {
                "total_assets": self._find_metric_with_fallbacks(
                    latest_balance, ["Total Assets", "TotalAssets", "totalAssets"]
                ),
                "total_liabilities": self._find_metric_with_fallbacks(
                    latest_balance, ["Total Liabilities Net Minority Interest", "Total Liabilities", "TotalLiabilities", "totalLiabilities"]
                ),
                "stockholders_equity": self._find_metric_with_fallbacks(
                    latest_balance, ["Stockholders Equity", "StockholdersEquity", "stockholdersEquity", "Total Equity", "Shareholders Equity"]
                ),
                "current_assets": self._find_metric_with_fallbacks(
                    latest_balance, ["Current Assets", "CurrentAssets", "currentAssets"]
                ),
                "current_liabilities": self._find_metric_with_fallbacks(
                    latest_balance, ["Current Liabilities", "CurrentLiabilities", "currentLiabilities"]
                ),
                "cash_and_equivalents": self._find_metric_with_fallbacks(
                    latest_balance, ["Cash And Cash Equivalents", "CashAndCashEquivalents", "cashAndCashEquivalents", "Cash", "Cash and Short Term Investments"]
                ),
                "total_debt": self._find_metric_with_fallbacks(
                    latest_balance, ["Total Debt", "TotalDebt", "totalDebt", "Long Term Debt", "Short Long Term Debt Total"]
                )
            }
            
            # Calculate Free Cash Flow properly: Operating Cash Flow + Capital Expenditure (capex is negative)
            operating_cf = self._find_metric_with_fallbacks(
                latest_cashflow, ["Operating Cash Flow", "OperatingCashFlow", "operatingCashFlow", "Cash Flow From Operating Activities"]
            )
            capex = self._find_metric_with_fallbacks(
                latest_cashflow, ["Capital Expenditure", "CapitalExpenditure", "capitalExpenditure", "Capital Expenditures", "Capex"]
            )
            
            # Calculate free cash flow if we have the components
            free_cash_flow = None
            if operating_cf is not None and capex is not None:
                # Capex is typically negative in cash flow statements, so we add it (which subtracts it)
                free_cash_flow = operating_cf + capex
            else:
                # Try to find it directly reported
                free_cash_flow = self._find_metric_with_fallbacks(
                    latest_cashflow, ["Free Cash Flow", "FreeCashFlow", "freeCashFlow"]
                )
            
            # Extract cash flow metrics
            key_metrics["cash_flow_metrics"] = {
                "operating_cash_flow": operating_cf,
                "investing_cash_flow": self._find_metric_with_fallbacks(
                    latest_cashflow, ["Investing Cash Flow", "InvestingCashFlow", "investingCashFlow", "Cash Flow From Investing Activities"]
                ),
                "financing_cash_flow": self._find_metric_with_fallbacks(
                    latest_cashflow, ["Financing Cash Flow", "FinancingCashFlow", "financingCashFlow", "Cash Flow From Financing Activities"]
                ),
                "free_cash_flow": free_cash_flow,
                "capex": capex
            }
            
            # Calculate basic ratios if data is available using fallback approach
            total_revenue = key_metrics["revenue_metrics"]["total_revenue"]
            net_income = key_metrics["profitability_metrics"]["net_income"]
            total_assets = key_metrics["balance_sheet_metrics"]["total_assets"]
            stockholders_equity = key_metrics["balance_sheet_metrics"]["stockholders_equity"]
            current_assets = key_metrics["balance_sheet_metrics"]["current_assets"]
            current_liabilities = key_metrics["balance_sheet_metrics"]["current_liabilities"]
            
            if total_revenue and net_income:
                key_metrics["ratios"]["net_profit_margin"] = net_income / total_revenue
            
            if net_income and total_assets:
                key_metrics["ratios"]["roa"] = net_income / total_assets
            
            if net_income and stockholders_equity:
                key_metrics["ratios"]["roe"] = net_income / stockholders_equity
            
            if current_assets and current_liabilities:
                key_metrics["ratios"]["current_ratio"] = current_assets / current_liabilities
            
        except Exception as e:
            self._log("warning", f"Error extracting key metrics: {e}")
        
        return key_metrics
    
    def scrape_income_statement(self, annual: bool = True) -> Dict[str, Any]:
        """
        Scrape income statement data.
        
        Args:
            annual: If True, get annual data; if False, get quarterly data
            
        Returns:
            Dictionary containing cleaned income statement data
        """
        self._log("info", f"Scraping {'annual' if annual else 'quarterly'} income statement for {self.ticker}")
        
        try:
            if annual:
                financials = self.yf_ticker.financials
            else:
                financials = self.yf_ticker.quarterly_financials
            
            cleaned_data = self._clean_financial_data(financials)
            
            if cleaned_data:
                self.scraped_statements += 1
                self._log("info", f"✅ Income statement: {len(cleaned_data)} periods extracted")
            else:
                self.failed_statements += 1
                self._log("warning", "❌ Income statement: No data found")
            
            return cleaned_data
            
        except Exception as e:
            self._log("error", f"Failed to scrape income statement: {e}")
            self.failed_statements += 1
            return {}
    
    def scrape_balance_sheet(self, annual: bool = True) -> Dict[str, Any]:
        """
        Scrape balance sheet data.
        
        Args:
            annual: If True, get annual data; if False, get quarterly data
            
        Returns:
            Dictionary containing cleaned balance sheet data
        """
        self._log("info", f"Scraping {'annual' if annual else 'quarterly'} balance sheet for {self.ticker}")
        
        try:
            if annual:
                balance_sheet = self.yf_ticker.balance_sheet
            else:
                balance_sheet = self.yf_ticker.quarterly_balance_sheet
            
            cleaned_data = self._clean_financial_data(balance_sheet)
            
            if cleaned_data:
                self.scraped_statements += 1
                self._log("info", f"✅ Balance sheet: {len(cleaned_data)} periods extracted")
            else:
                self.failed_statements += 1
                self._log("warning", "❌ Balance sheet: No data found")
            
            return cleaned_data
            
        except Exception as e:
            self._log("error", f"Failed to scrape balance sheet: {e}")
            self.failed_statements += 1
            return {}
    
    def scrape_cash_flow(self, annual: bool = True) -> Dict[str, Any]:
        """
        Scrape cash flow statement data.
        
        Args:
            annual: If True, get annual data; if False, get quarterly data
            
        Returns:
            Dictionary containing cleaned cash flow data
        """
        self._log("info", f"Scraping {'annual' if annual else 'quarterly'} cash flow for {self.ticker}")
        
        try:
            if annual:
                cash_flow = self.yf_ticker.cashflow
            else:
                cash_flow = self.yf_ticker.quarterly_cashflow
            
            cleaned_data = self._clean_financial_data(cash_flow)
            
            if cleaned_data:
                self.scraped_statements += 1
                self._log("info", f"✅ Cash flow: {len(cleaned_data)} periods extracted")
            else:
                self.failed_statements += 1
                self._log("warning", "❌ Cash flow: No data found")
            
            return cleaned_data
            
        except Exception as e:
            self._log("error", f"Failed to scrape cash flow: {e}")
            self.failed_statements += 1
            return {}
    
    def scrape_comprehensive_company_data(self) -> Dict[str, Any]:
        """
        Scrape comprehensive company data for financial modeling.
        
        Returns:
            Dictionary containing all company data needed for financial modeling
        """
        self._log("info", f"Scraping comprehensive company data for {self.ticker}")
        
        try:
            info = self.yf_ticker.info
            
            # 1. Basic Company Information
            company_data = {
                "basic_info": {
                    "symbol": info.get("symbol"),
                    "long_name": info.get("longName"),
                    "business_summary": info.get("longBusinessSummary"),
                    "sector": info.get("sector"),
                    "industry": info.get("industry"),
                    "website": info.get("website"),
                    "employees": info.get("fullTimeEmployees"),
                    "country": info.get("country"),
                    "exchange": info.get("exchange"),
                    "currency": info.get("currency")
                },
                
                # 2. Share/Market Data (Critical for modeling)
                "market_data": {
                    "shares_outstanding_basic": info.get("sharesOutstanding"),
                    "shares_outstanding_diluted": info.get("sharesOutstandingDiluted"),
                    "float_shares": info.get("floatShares"),
                    "current_price": info.get("currentPrice"),
                    "previous_close": info.get("previousClose"),
                    "market_cap": info.get("marketCap"),
                    "enterprise_value": info.get("enterpriseValue"),
                    "52_week_high": info.get("fiftyTwoWeekHigh"),
                    "52_week_low": info.get("fiftyTwoWeekLow"),
                    "dividend_yield": info.get("dividendYield"),
                    "ex_dividend_date": info.get("exDividendDate"),
                    "dividend_rate": info.get("dividendRate"),
                    "payout_ratio": info.get("payoutRatio")
                },
                
                # 3. Valuation Inputs & Multiples
                "valuation_metrics": {
                    "pe_ratio_trailing": info.get("trailingPE"),
                    "pe_ratio_forward": info.get("forwardPE"),
                    "peg_ratio": info.get("pegRatio"),
                    "price_to_book": info.get("priceToBook"),
                    "price_to_sales": info.get("priceToSalesTrailing12Months"),
                    "enterprise_to_revenue": info.get("enterpriseToRevenue"),
                    "enterprise_to_ebitda": info.get("enterpriseToEbitda"),
                    "book_value": info.get("bookValue"),
                    "price_to_book": info.get("priceToBook")
                },
                
                # 4. Capital Structure & Cost of Capital Data
                "capital_structure": {
                    "total_debt": info.get("totalDebt"),
                    "long_term_debt": info.get("longTermDebt"),
                    "short_term_debt": info.get("shortLongTermDebt"),
                    "total_cash": info.get("totalCash"),
                    "net_debt": (info.get("totalDebt", 0) - info.get("totalCash", 0)) if info.get("totalDebt") and info.get("totalCash") else None,
                    "debt_to_equity": info.get("debtToEquity"),
                    "current_ratio": info.get("currentRatio"),
                    "quick_ratio": info.get("quickRatio"),
                    "interest_coverage": info.get("interestCoverage"),
                    "beta": info.get("beta"),
                    "risk_free_rate": None,  # Will need external source
                    "equity_risk_premium": None  # Will need external source
                },
                
                # 5. Growth & Profitability Metrics
                "growth_profitability": {
                    "revenue_growth": info.get("revenueGrowth"),
                    "earnings_growth": info.get("earningsGrowth"),
                    "revenue_quarterly_growth": info.get("revenueQuarterlyGrowth"),
                    "earnings_quarterly_growth": info.get("earningsQuarterlyGrowth"),
                    "profit_margins": info.get("profitMargins"),
                    "gross_margins": info.get("grossMargins"),
                    "operating_margins": info.get("operatingMargins"),
                    "ebitda_margins": info.get("ebitdaMargins"),
                    "return_on_assets": info.get("returnOnAssets"),
                    "return_on_equity": info.get("returnOnEquity")
                },
                
                # 6. Operational/Non-Financial Metrics (Industry-specific)
                "operational_metrics": {
                    "employees": info.get("fullTimeEmployees"),
                    "revenue_per_employee": None,  # Will calculate
                    "asset_turnover": None,  # Will calculate
                    "inventory_turnover": None,  # Will calculate
                    "receivables_turnover": None,  # Will calculate
                    # Industry-specific KPIs will be added based on sector
                    "industry_kpis": {}
                },
                
                # 7. Management Guidance & Analyst Estimates
                "forward_guidance": {
                    "target_high_price": info.get("targetHighPrice"),
                    "target_low_price": info.get("targetLowPrice"),
                    "target_mean_price": info.get("targetMeanPrice"),
                    "target_median_price": info.get("targetMedianPrice"),
                    "recommendation_mean": info.get("recommendationMean"),
                    "recommendation_key": info.get("recommendationKey"),
                    "number_of_analyst_opinions": info.get("numberOfAnalystOpinions"),
                    "forward_eps": info.get("forwardEps"),
                    "trailing_eps": info.get("trailingEps")
                }
            }
            
            self._log("info", f"✅ Comprehensive company data: {info.get('longName', self.ticker)} extracted")
            return company_data
            
        except Exception as e:
            self._log("error", f"Failed to scrape comprehensive company data: {e}")
            return {}
    
    def scrape_company_info(self) -> Dict[str, Any]:
        """
        Scrape basic company information and stock metrics (legacy method).
        
        Returns:
            Dictionary containing company info and stock metrics
        """
        # For backward compatibility, call the comprehensive method and extract basic info
        comprehensive_data = self.scrape_comprehensive_company_data()
        if not comprehensive_data:
            return {}
            
        # Extract just the basic info for legacy compatibility
        basic_company_info = {
            "basic_info": comprehensive_data.get("basic_info", {}),
            "market_data": {
                "market_cap": comprehensive_data.get("market_data", {}).get("market_cap"),
                "shares_outstanding": comprehensive_data.get("market_data", {}).get("shares_outstanding_basic"),
                "float_shares": comprehensive_data.get("market_data", {}).get("float_shares"),
                "current_price": comprehensive_data.get("market_data", {}).get("current_price"),
                "previous_close": comprehensive_data.get("market_data", {}).get("previous_close"),
                "52_week_high": comprehensive_data.get("market_data", {}).get("52_week_high"),
                "52_week_low": comprehensive_data.get("market_data", {}).get("52_week_low")
            },
            "financial_highlights": {
                "total_revenue": comprehensive_data.get("market_data", {}).get("enterprise_value"),  # Placeholder
                "gross_profits": None,
                "ebitda": None,
                "total_cash": comprehensive_data.get("capital_structure", {}).get("total_cash"),
                "total_debt": comprehensive_data.get("capital_structure", {}).get("total_debt"),
                "revenue_growth": comprehensive_data.get("growth_profitability", {}).get("revenue_growth"),
                "earnings_growth": comprehensive_data.get("growth_profitability", {}).get("earnings_growth")
            },
            "valuation_metrics": {
                "pe_ratio": comprehensive_data.get("valuation_metrics", {}).get("pe_ratio_trailing"),
                "forward_pe": comprehensive_data.get("valuation_metrics", {}).get("pe_ratio_forward"),
                "peg_ratio": comprehensive_data.get("valuation_metrics", {}).get("peg_ratio"),
                "price_to_book": comprehensive_data.get("valuation_metrics", {}).get("price_to_book"),
                "price_to_sales": comprehensive_data.get("valuation_metrics", {}).get("price_to_sales"),
                "enterprise_value": comprehensive_data.get("market_data", {}).get("enterprise_value")
            }
        }
        
        return basic_company_info
    
    def scrape_historical_prices(self, period: str = "5y") -> Dict[str, Any]:
        """
        Scrape historical stock price data for volatility and beta calculations.
        
        Args:
            period: Time period ('1y', '2y', '5y', 'max')
            
        Returns:
            Dictionary containing historical price data
        """
        self._log("info", f"Scraping historical price data for {self.ticker} ({period})")
        
        try:
            hist = self.yf_ticker.history(period=period)
            if hist.empty:
                return {}
            
            # Convert to dictionary format
            price_data = {
                "period": period,
                "data_points": len(hist),
                "start_date": hist.index[0].strftime('%Y-%m-%d'),
                "end_date": hist.index[-1].strftime('%Y-%m-%d'),
                "prices": {}
            }
            
            for date, row in hist.iterrows():
                date_key = date.strftime('%Y-%m-%d')
                price_data["prices"][date_key] = {
                    "open": float(row['Open']) if pd.notna(row['Open']) else None,
                    "high": float(row['High']) if pd.notna(row['High']) else None,
                    "low": float(row['Low']) if pd.notna(row['Low']) else None,
                    "close": float(row['Close']) if pd.notna(row['Close']) else None,
                    "volume": int(row['Volume']) if pd.notna(row['Volume']) else None
                }
            
            self._log("info", f"✅ Historical prices: {len(hist)} data points extracted")
            return price_data
            
        except Exception as e:
            self._log("error", f"Failed to scrape historical prices: {e}")
            return {}
    
    def scrape_analyst_estimates(self) -> Dict[str, Any]:
        """
        Scrape analyst estimates and recommendations.
        
        Returns:
            Dictionary containing analyst data
        """
        self._log("info", f"Scraping analyst estimates for {self.ticker}")
        
        try:
            # Get analyst estimates
            recommendations = self.yf_ticker.recommendations
            analyst_data = {
                "recommendations": {},
                "earnings_estimates": {},
                "revenue_estimates": {}
            }
            
            if recommendations is not None and not recommendations.empty:
                # Process latest recommendations
                latest_recs = recommendations.tail(10)  # Last 10 recommendations
                for date, row in latest_recs.iterrows():
                    # Handle different date formats
                    if hasattr(date, 'strftime'):
                        date_key = date.strftime('%Y-%m-%d')
                    else:
                        date_key = str(date)
                    
                    analyst_data["recommendations"][date_key] = {
                        "firm": row.get('Firm', ''),
                        "to_grade": row.get('To Grade', ''),
                        "from_grade": row.get('From Grade', ''),
                        "action": row.get('Action', '')
                    }
            
            # Try to get earnings estimates
            try:
                calendar = self.yf_ticker.calendar
                if calendar is not None and not calendar.empty:
                    analyst_data["earnings_calendar"] = calendar.to_dict()
            except:
                pass
            
            self._log("info", f"✅ Analyst data: {len(analyst_data['recommendations'])} recommendations extracted")
            return analyst_data
            
        except Exception as e:
            self._log("error", f"Failed to scrape analyst estimates: {e}")
            return {}
    
    def scrape_financial_modeling_data(self, annual: bool = True, years: Optional[int] = None) -> Dict[str, Any]:
        """
        Scrape comprehensive data specifically for financial modeling.
        Combines all necessary data points for DCF, comparable analysis, etc.
        
        Args:
            annual: If True, get annual data; if False, get quarterly data
            years: Number of years of historical price data to fetch (1-10, default 5)
            
        Returns:
            Dictionary containing all financial modeling data
        """
        self._log("info", f"Starting comprehensive financial modeling data collection for {self.ticker}")
        
        # Reset statistics
        self.scraped_statements = 0
        self.failed_statements = 0
        self.data_points_extracted = 0
        
        modeling_data = {
            "ticker": self.ticker,
            "scraped_at": datetime.utcnow().isoformat(),
            "data_type": "annual" if annual else "quarterly",
            "data_purpose": "financial_modeling",
            
            # Core financial statements (3-5 years historical)
            "financial_statements": {
                "income_statement": {},
                "balance_sheet": {},
                "cash_flow": {}
            },
            
            # Comprehensive company data for modeling
            "company_data": {},
            
            # Historical price data for volatility/beta calculations
            "market_data": {},
            
            # Analyst estimates and guidance
            "analyst_data": {},
            
            # Calculated metrics for modeling
            "modeling_metrics": {},
            
            # Industry and peer data (placeholder for future enhancement)
            "industry_data": {},
            
            # Summary statistics
            "data_summary": {}
        }
        
        # 1. Scrape financial statements
        self._log("info", "Collecting historical financial statements...")
        modeling_data["financial_statements"]["income_statement"] = self.scrape_income_statement(annual)
        time.sleep(0.5)
        
        modeling_data["financial_statements"]["balance_sheet"] = self.scrape_balance_sheet(annual)
        time.sleep(0.5)
        
        modeling_data["financial_statements"]["cash_flow"] = self.scrape_cash_flow(annual)
        time.sleep(0.5)
        
        # 2. Scrape comprehensive company data
        self._log("info", "Collecting comprehensive company data...")
        modeling_data["company_data"] = self.scrape_comprehensive_company_data()
        time.sleep(0.5)
        
        # 3. Scrape historical price data
        self._log("info", "Collecting historical market data...")
        # Determine price data period based on years parameter
        if years:
            price_period = f"{min(max(years, 1), 10)}y"  # Clamp between 1-10 years
            self._log("info", f"  Using {years} years of price data as requested")
        else:
            price_period = "5y"  # Default to 5 years
        modeling_data["market_data"]["historical_prices"] = self.scrape_historical_prices(price_period)
        time.sleep(0.5)
        
        # 4. Scrape analyst data
        self._log("info", "Collecting analyst estimates...")
        modeling_data["analyst_data"] = self.scrape_analyst_estimates()
        time.sleep(0.5)
        
        # 5. Calculate advanced metrics for modeling
        self._log("info", "Calculating modeling metrics...")
        modeling_data["modeling_metrics"] = self._calculate_modeling_metrics(modeling_data)
        
        # 6. Generate data summary
        modeling_data["data_summary"] = self._generate_data_summary(modeling_data)
        
        self._log("info", f"Financial modeling data collection completed for {self.ticker}")
        return modeling_data
    
    def _calculate_modeling_metrics(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Calculate advanced metrics specifically needed for financial modeling.
        
        Args:
            data: Complete financial data
            
        Returns:
            Dictionary of calculated modeling metrics
        """
        metrics = {
            "historical_growth_rates": {},
            "financial_ratios": {},
            "working_capital_metrics": {},
            "leverage_metrics": {},
            "efficiency_metrics": {},
            "market_metrics": {}
        }
        
        try:
            # Extract financial statements data
            income_data = data.get("financial_statements", {}).get("income_statement", {})
            balance_data = data.get("financial_statements", {}).get("balance_sheet", {})
            cashflow_data = data.get("financial_statements", {}).get("cash_flow", {})
            
            if not income_data:
                return metrics
            
            # Calculate historical growth rates
            years = sorted(income_data.keys(), reverse=True)
            if len(years) >= 2:
                metrics["historical_growth_rates"] = self._calculate_growth_rates(income_data, balance_data, cashflow_data, years)
            
            # Calculate comprehensive financial ratios
            metrics["financial_ratios"] = self._calculate_comprehensive_ratios(income_data, balance_data, cashflow_data, years)
            
            # Calculate working capital components
            metrics["working_capital_metrics"] = self._calculate_working_capital_metrics(balance_data, income_data, years)
            
            # Calculate leverage and coverage ratios
            metrics["leverage_metrics"] = self._calculate_leverage_metrics(balance_data, income_data, cashflow_data, years)
            
        except Exception as e:
            self._log("warning", f"Error calculating modeling metrics: {e}")
        
        return metrics
    
    def _generate_data_summary(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Generate summary statistics for the collected data."""
        summary = {
            "collection_timestamp": datetime.utcnow().isoformat(),
            "data_completeness": {},
            "time_series_coverage": {},
            "key_statistics": {}
        }
        
        # Analyze data completeness
        statements = data.get("financial_statements", {})
        summary["data_completeness"] = {
            "income_statement_periods": len(statements.get("income_statement", {})),
            "balance_sheet_periods": len(statements.get("balance_sheet", {})),
            "cash_flow_periods": len(statements.get("cash_flow", {})),
            "company_data_available": bool(data.get("company_data")),
            "market_data_available": bool(data.get("market_data", {}).get("historical_prices")),
            "analyst_data_available": bool(data.get("analyst_data"))
        }
        
        return summary
    
    def _calculate_growth_rates(self, income_data: Dict, balance_data: Dict, cashflow_data: Dict, years: List[str]) -> Dict[str, Any]:
        """Calculate historical growth rates for key metrics."""
        growth_rates = {}
        
        try:
            # Revenue growth rates
            revenues = []
            for year in years:
                revenue = self._find_metric_with_fallbacks(
                    income_data.get(year, {}), 
                    ["Total Revenue", "TotalRevenues", "totalRevenue", "Revenue"]
                )
                if revenue:
                    revenues.append((year, revenue))
            
            if len(revenues) >= 2:
                growth_rates["revenue_growth"] = self._calculate_yoy_growth(revenues)
            
            # Net income growth rates
            net_incomes = []
            for year in years:
                net_income = self._find_metric_with_fallbacks(
                    income_data.get(year, {}),
                    ["Net Income", "NetIncome", "netIncome"]
                )
                if net_income:
                    net_incomes.append((year, net_income))
            
            if len(net_incomes) >= 2:
                growth_rates["net_income_growth"] = self._calculate_yoy_growth(net_incomes)
            
            # Cash flow growth rates
            cash_flows = []
            for year in years:
                if year in cashflow_data:
                    cf = self._find_metric_with_fallbacks(
                        cashflow_data.get(year, {}),
                        ["Operating Cash Flow", "OperatingCashFlow", "operatingCashFlow"]
                    )
                    if cf:
                        cash_flows.append((year, cf))
            
            if len(cash_flows) >= 2:
                growth_rates["operating_cf_growth"] = self._calculate_yoy_growth(cash_flows)
                
        except Exception as e:
            self._log("warning", f"Error calculating growth rates: {e}")
        
        return growth_rates
    
    def _calculate_yoy_growth(self, data_points: List[tuple]) -> Dict[str, Any]:
        """Calculate year-over-year growth rates."""
        if len(data_points) < 2:
            return {}
        
        # Sort by year
        data_points.sort(key=lambda x: x[0], reverse=True)
        
        growth_data = {
            "annual_growth_rates": [],
            "cagr_3y": None,
            "cagr_5y": None,
            "average_growth": None
        }
        
        # Calculate annual growth rates
        for i in range(len(data_points) - 1):
            current_year, current_value = data_points[i]
            previous_year, previous_value = data_points[i + 1]
            
            if previous_value and previous_value != 0:
                growth_rate = (current_value - previous_value) / abs(previous_value)
                growth_data["annual_growth_rates"].append({
                    "year": current_year,
                    "growth_rate": growth_rate
                })
        
        # Calculate CAGR if we have enough data
        if len(data_points) >= 3:
            first_value = data_points[-1][1]  # Oldest
            last_value = data_points[0][1]    # Most recent
            years_span = len(data_points) - 1
            
            if first_value and first_value > 0:
                cagr = (last_value / first_value) ** (1 / years_span) - 1
                if years_span >= 3:
                    growth_data["cagr_3y"] = cagr
                if years_span >= 5:
                    growth_data["cagr_5y"] = cagr
        
        # Calculate average growth
        if growth_data["annual_growth_rates"]:
            avg_growth = sum(item["growth_rate"] for item in growth_data["annual_growth_rates"]) / len(growth_data["annual_growth_rates"])
            growth_data["average_growth"] = avg_growth
        
        return growth_data
    
    def _calculate_comprehensive_ratios(self, income_data: Dict, balance_data: Dict, cashflow_data: Dict, years: List[str]) -> Dict[str, Any]:
        """Calculate comprehensive financial ratios for modeling."""
        ratios = {}
        
        try:
            latest_year = years[0] if years else None
            if not latest_year:
                return ratios
            
            latest_income = income_data.get(latest_year, {})
            latest_balance = balance_data.get(latest_year, {})
            latest_cashflow = cashflow_data.get(latest_year, {})
            
            # Profitability ratios
            total_revenue = self._find_metric_with_fallbacks(latest_income, ["Total Revenue", "TotalRevenues", "totalRevenue"])
            net_income = self._find_metric_with_fallbacks(latest_income, ["Net Income", "NetIncome", "netIncome"])
            gross_profit = self._find_metric_with_fallbacks(latest_income, ["Gross Profit", "GrossProfit", "grossProfit"])
            operating_income = self._find_metric_with_fallbacks(latest_income, ["Operating Income", "OperatingIncome", "EBIT"])
            
            ratios["profitability"] = {}
            if total_revenue:
                if gross_profit:
                    ratios["profitability"]["gross_margin"] = gross_profit / total_revenue
                if operating_income:
                    ratios["profitability"]["operating_margin"] = operating_income / total_revenue
                if net_income:
                    ratios["profitability"]["net_margin"] = net_income / total_revenue
            
            # Asset efficiency ratios
            total_assets = self._find_metric_with_fallbacks(latest_balance, ["Total Assets", "TotalAssets", "totalAssets"])
            
            ratios["efficiency"] = {}
            if total_assets and total_revenue:
                ratios["efficiency"]["asset_turnover"] = total_revenue / total_assets
            if total_assets and net_income:
                ratios["efficiency"]["roa"] = net_income / total_assets
            
            # Leverage ratios
            total_debt = self._find_metric_with_fallbacks(latest_balance, ["Total Debt", "TotalDebt", "totalDebt"])
            stockholders_equity = self._find_metric_with_fallbacks(latest_balance, ["Stockholders Equity", "StockholdersEquity", "Total Equity"])
            
            ratios["leverage"] = {}
            if total_debt and stockholders_equity:
                ratios["leverage"]["debt_to_equity"] = total_debt / stockholders_equity
            if total_debt and total_assets:
                ratios["leverage"]["debt_to_assets"] = total_debt / total_assets
            
        except Exception as e:
            self._log("warning", f"Error calculating comprehensive ratios: {e}")
        
        return ratios
    
    def _calculate_working_capital_metrics(self, balance_data: Dict, income_data: Dict, years: List[str]) -> Dict[str, Any]:
        """Calculate working capital components and efficiency metrics."""
        wc_metrics = {}
        
        try:
            latest_year = years[0] if years else None
            if not latest_year or latest_year not in balance_data:
                return wc_metrics
            
            latest_balance = balance_data[latest_year]
            latest_income = income_data.get(latest_year, {})
            
            # Working capital components
            current_assets = self._find_metric_with_fallbacks(latest_balance, ["Current Assets", "CurrentAssets", "currentAssets"])
            current_liabilities = self._find_metric_with_fallbacks(latest_balance, ["Current Liabilities", "CurrentLiabilities", "currentLiabilities"])
            
            if current_assets and current_liabilities:
                wc_metrics["working_capital"] = current_assets - current_liabilities
                wc_metrics["current_ratio"] = current_assets / current_liabilities
            
            # Calculate working capital as % of revenue
            total_revenue = self._find_metric_with_fallbacks(latest_income, ["Total Revenue", "TotalRevenues", "totalRevenue"])
            if wc_metrics.get("working_capital") and total_revenue:
                wc_metrics["wc_percent_of_revenue"] = wc_metrics["working_capital"] / total_revenue
            
        except Exception as e:
            self._log("warning", f"Error calculating working capital metrics: {e}")
        
        return wc_metrics
    
    def _calculate_leverage_metrics(self, balance_data: Dict, income_data: Dict, cashflow_data: Dict, years: List[str]) -> Dict[str, Any]:
        """Calculate leverage and coverage ratios."""
        leverage_metrics = {}
        
        try:
            latest_year = years[0] if years else None
            if not latest_year:
                return leverage_metrics
            
            latest_balance = balance_data.get(latest_year, {})
            latest_income = income_data.get(latest_year, {})
            latest_cashflow = cashflow_data.get(latest_year, {})
            
            # Debt metrics
            total_debt = self._find_metric_with_fallbacks(latest_balance, ["Total Debt", "TotalDebt", "totalDebt"])
            cash = self._find_metric_with_fallbacks(latest_balance, ["Cash And Cash Equivalents", "Cash", "CashAndCashEquivalents"])
            
            if total_debt:
                leverage_metrics["total_debt"] = total_debt
                if cash:
                    leverage_metrics["net_debt"] = total_debt - cash
            
            # Coverage ratios
            operating_income = self._find_metric_with_fallbacks(latest_income, ["Operating Income", "OperatingIncome", "EBIT"])
            interest_expense = self._find_metric_with_fallbacks(latest_income, ["Interest Expense", "InterestExpense", "interestExpense"])
            
            if operating_income and interest_expense and interest_expense > 0:
                leverage_metrics["interest_coverage_ratio"] = operating_income / interest_expense
            
        except Exception as e:
            self._log("warning", f"Error calculating leverage metrics: {e}")
        
        return leverage_metrics
    
    def scrape_all_statements(self, annual: bool = True) -> Dict[str, Any]:
        """
        Scrape all financial statements and company info.
        
        Args:
            annual: If True, get annual data; if False, get quarterly data
            
        Returns:
            Dictionary containing all financial data
        """
        self._log("info", f"Starting comprehensive financial data scraping for {self.ticker}")
        
        # Reset statistics
        self.scraped_statements = 0
        self.failed_statements = 0
        self.data_points_extracted = 0
        
        all_data = {
            "ticker": self.ticker,
            "scraped_at": datetime.utcnow().isoformat(),
            "data_type": "annual" if annual else "quarterly",
            "company_info": {},
            "income_statement": {},
            "balance_sheet": {},
            "cash_flow": {},
            "key_metrics": {}
        }
        
        # Scrape company information
        all_data["company_info"] = self.scrape_company_info()
        
        # Add small delays between API calls to be respectful
        time.sleep(0.5)
        
        # Scrape financial statements
        all_data["income_statement"] = self.scrape_income_statement(annual)
        time.sleep(0.5)
        
        all_data["balance_sheet"] = self.scrape_balance_sheet(annual)
        time.sleep(0.5)
        
        all_data["cash_flow"] = self.scrape_cash_flow(annual)
        time.sleep(0.5)
        
        # Extract key metrics for financial modeling
        all_data["key_metrics"] = self._extract_key_metrics(all_data)
        
        return all_data
    
    def save_financial_data(self, data: Dict[str, Any], annual: bool = True, statements_scraped: List[str] = None) -> pathlib.Path:
        """
        Save financial data to JSON file with clear naming for partial scrapes.
        
        Args:
            data: Financial data dictionary
            annual: Whether this is annual or quarterly data
            statements_scraped: List of statement types scraped (for filename clarity)
            
        Returns:
            Path to saved file
        """
        self._ensure_directories()
        
        # Generate filename with statement type info for clarity
        data_type = "annual" if annual else "quarterly"
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        
        # Add statement type to filename if partial scrape
        if statements_scraped and len(statements_scraped) == 1:
            statement_type = statements_scraped[0]
            filename = f"financials_{data_type}_{statement_type}_{timestamp}.json"
            latest_filename = f"financials_{data_type}_{statement_type}_latest.json"
        else:
            filename = f"financials_{data_type}_{timestamp}.json"
            latest_filename = f"financials_{data_type}_latest.json"
            
        file_path = self.financials_dir / filename
        
        # Save data
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)
        
        # Also save a "latest" version for easy access
        latest_path = self.financials_dir / latest_filename
        with open(latest_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)
        
        return file_path
    
    def get_scraping_results(self) -> Dict[str, Any]:
        """Get current scraping statistics."""
        return {
            "ticker": self.ticker,
            "statements_scraped": self.scraped_statements,
            "statements_failed": self.failed_statements,
            "data_points_extracted": self.data_points_extracted,
            "total_statements_attempted": self.scraped_statements + self.failed_statements,
            "success_rate": self.scraped_statements / max(1, self.scraped_statements + self.failed_statements)
        }
    
    def get_storage_info(self) -> Dict[str, Any]:
        """Get information about stored financial data."""
        financial_files = list(self.financials_dir.glob("*.json")) if self.financials_dir.exists() else []
        
        return {
            "company_dir": str(self.company_dir),
            "financials_dir": str(self.financials_dir),
            "total_files": len(financial_files),
            "files": [f.name for f in financial_files],
            "directories_exist": {
                "company_dir": self.company_dir.exists(),
                "financials_dir": self.financials_dir.exists()
            },
            "latest_files": {
                "annual": (self.financials_dir / "financials_annual_latest.json").exists(),
                "quarterly": (self.financials_dir / "financials_quarterly_latest.json").exists()
            }
        }

def main():
    """Command-line interface for the financial scraper."""
    parser = argparse.ArgumentParser(description="Scrape financial statements for stock analysis")
    parser.add_argument("--ticker", required=True, help="Stock ticker, e.g. NVDA")
    parser.add_argument("--statements", choices=["all", "income", "balance", "cashflow", "info", "modeling"], 
                       default="all", help="Which statements to scrape ('modeling' for comprehensive financial modeling data)")
    parser.add_argument("--quarterly", action="store_true", help="Get quarterly data instead of annual")
    parser.add_argument("--years", type=int, help="Number of years of historical price data (1-10, only affects 'modeling' mode)")
    # Data saving is now always enabled for production use
    parser.add_argument("--stats", action="store_true", help="Show current storage statistics")
    
    args = parser.parse_args()
    
    if not YFINANCE_AVAILABLE:
        print("Error: yfinance is required but not installed.")
        print("Install with: pip install yfinance pandas numpy")
        return 1
    
    try:
        # Initialize scraper
        scraper = FinancialScraper(args.ticker)
        
        # Show stats if requested
        if args.stats:
            storage_info = scraper.get_storage_info()
            scraper._log("info", f"Financial data storage for {args.ticker}:")
            scraper._log("info", f"  Financials directory: {storage_info['financials_dir']}")
            scraper._log("info", f"  Total files: {storage_info['total_files']}")
            scraper._log("info", f"  Latest files available: {storage_info['latest_files']}")
            if storage_info['files']:
                scraper._log("info", f"  Files: {', '.join(storage_info['files'])}")
            return 0
        
        # Determine data type
        annual = not args.quarterly
        data_type_str = "annual" if annual else "quarterly"
        
        # Scrape based on selection
        statements_scraped = []
        
        if args.statements == "all":
            scraper._log("info", f"Scraping all financial statements ({data_type_str}) for {args.ticker}")
            financial_data = scraper.scrape_all_statements(annual)
            statements_scraped = ["all"]
        elif args.statements == "income":
            statements_scraped = ["income"]
            financial_data = {
                "ticker": args.ticker,
                "scraped_at": datetime.utcnow().isoformat(),
                "data_type": data_type_str,
                "income_statement": scraper.scrape_income_statement(annual)
            }
        elif args.statements == "balance":
            statements_scraped = ["balance"]
            financial_data = {
                "ticker": args.ticker,
                "scraped_at": datetime.utcnow().isoformat(),
                "data_type": data_type_str,
                "balance_sheet": scraper.scrape_balance_sheet(annual)
            }
        elif args.statements == "cashflow":
            statements_scraped = ["cashflow"]
            financial_data = {
                "ticker": args.ticker,
                "scraped_at": datetime.utcnow().isoformat(),
                "data_type": data_type_str,
                "cash_flow": scraper.scrape_cash_flow(annual)
            }
        elif args.statements == "info":
            statements_scraped = ["info"]
            financial_data = {
                "ticker": args.ticker,
                "scraped_at": datetime.utcnow().isoformat(),
                "data_type": "company_info",
                "company_info": scraper.scrape_company_info()
            }
        elif args.statements == "modeling":
            scraper._log("info", f"Scraping comprehensive financial modeling data ({data_type_str}) for {args.ticker}")
            if args.years:
                scraper._log("info", f"  Using {args.years} years of historical price data")
            financial_data = scraper.scrape_financial_modeling_data(annual, args.years)
            statements_scraped = ["modeling"]
        
        # Save if requested
        if financial_data:  # Always save in production use
            file_path = scraper.save_financial_data(financial_data, annual, statements_scraped)
            scraper._log("info", f"Financial data saved to: {file_path}")
        
        # Display results
        results = scraper.get_scraping_results()
        scraper._log("info", f"Financial scraping completed for {results['ticker']}:")
        scraper._log("info", f"  Statements scraped: {results['statements_scraped']}")
        scraper._log("info", f"  Statements failed: {results['statements_failed']}")
        scraper._log("info", f"  Data points extracted: {results['data_points_extracted']}")
        scraper._log("info", f"  Success rate: {results['success_rate']:.1%}")
        
        # Display key metrics preview if available
        if args.statements == "all" and financial_data.get("key_metrics"):
            key_metrics = financial_data["key_metrics"]
            scraper._log("info", "Key Financial Metrics Preview:")
            
            # Revenue metrics
            revenue = key_metrics.get("revenue_metrics", {}).get("total_revenue")
            if revenue:
                scraper._log("info", f"  Total Revenue: ${revenue:,.0f}")
            
            # Profitability
            net_income = key_metrics.get("profitability_metrics", {}).get("net_income")
            if net_income:
                scraper._log("info", f"  Net Income: ${net_income:,.0f}")
            
            # Key ratios
            ratios = key_metrics.get("ratios", {})
            if ratios.get("net_profit_margin"):
                scraper._log("info", f"  Net Profit Margin: {ratios['net_profit_margin']:.1%}")
            if ratios.get("roe"):
                scraper._log("info", f"  Return on Equity: {ratios['roe']:.1%}")
        
    except Exception as e:
        if 'scraper' in locals():
            scraper._log("error", f"Financial scraping failed: {e}")
        else:
            print(f"[ERROR] Financial scraping failed: {e}")
        return 1
    
    return 0

if __name__ == "__main__":
    exit(main())
