"""
Financial Model Agent

This package contains the infrastructure for building Excel-based DCF financial models
from Yahoo Finance JSON data. The model follows a structured 9-tab approach with
explicit formulas for each cell.

Tabs:
    0. Raw - Flat database of (Key, Year, Value) tuples
    1. Keys_Map - Helper lookup table with SUMIFS formulas
    2. Assumptions - Modeling drivers and parameters
    3. LLM_Inferred - Hidden tab with LLM-inferred assumptions
    4. Historical - Last 5 years of actual financials
    5. Projections - 5-year forward projections
    6. Valuation (DCF) - Perpetual Growth DCF valuation
    7. Valuation (Exit Multiple) - Exit Multiple DCF valuation
    8. Sensitivity - 2-way sensitivity analysis
    9. Summary - Clean output dashboard

Usage:
    from src.agents.fm import FinancialModelBuilder
    
    # Build from JSON file
    builder = FinancialModelBuilder(ticker="NVDA")
    builder.load_json_file("path/to/financials.json")
    builder.build_model()
    builder.save("NVDA_model.xlsx")
    
    # Or use the convenience function
    from src.agents.fm import create_financial_model
    create_financial_model("NVDA", "financials.json", "output.xlsx")
"""

from .financial_model_builder import (
    FinancialModelBuilder,
    create_financial_model,
    TAB_NAMES,
    ExcelFormats,
)

__all__ = [
    'FinancialModelBuilder',
    'create_financial_model',
    'TAB_NAMES',
    'ExcelFormats',
]

__version__ = '1.0.0'
