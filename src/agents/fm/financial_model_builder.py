"""
Financial Model Builder - Entry Point

Main orchestrator that builds complete Excel DCF model from JSON data.
This is the ONLY entry point for building financial models.

Architecture:
- Loads JSON financial data
- Calls LLM to infer forward assumptions
- Coordinates 9 tab builders to create complete model
- Generates banker-grade Excel file with formulas

Usage:
    # Method 1: Convenience function
    from src.agents.fm import create_financial_model
    create_financial_model("NVDA", "data.json", "output.xlsx")
    
    # Method 2: Builder class (more control)
    from src.agents.fm import FinancialModelBuilder
    builder = FinancialModelBuilder("NVDA")
    builder.load_json_file("data.json")
    builder.build_model()
    builder.save("output.xlsx")
"""

from typing import Dict, Any, Optional
from pathlib import Path
from datetime import datetime
import json

import openpyxl
from openpyxl.workbook.workbook import Workbook


# =============================================================================
# Constants
# =============================================================================

# Tab names in order of creation
TAB_NAMES = [
    "Raw",
    "Keys_Map",
    "Assumptions",
    "LLM_Inferred",  # Hidden tab with LLM-inferred values
    "Historical",
    "Projections",
    "Valuation (DCF)",  # Perpetual Growth DCF
    "Valuation (Exit Multiple)",  # Exit Multiple DCF
    "Sensitivity",
    "Summary",
]


class ExcelFormats:
    """Standard Excel formatting for different data types"""
    
    CURRENCY = '#,##0'
    CURRENCY_DECIMAL = '#,##0.00'
    PERCENTAGE = '0.0%'
    PERCENTAGE_DECIMAL = '0.00%'
    NUMBER = '#,##0'
    NUMBER_DECIMAL = '#,##0.00'
    
    # Colors
    HEADER_COLOR = 'D3D3D3'  # Light gray
    CALCULATED_COLOR = 'F0F0F0'  # Very light gray
    INPUT_COLOR = 'FFFFCC'  # Light yellow
    IMPORTANT_COLOR = 'FFE6CC'  # Light orange


# =============================================================================
# Tab Builder Imports
# =============================================================================

# Import all tab builders
from .tabs.tab_raw import RawTabBuilder
from .tabs.tab_keys_map import KeysMapTabBuilder
from .tabs.tab_assumptions import AssumptionsTabBuilder, infer_assumptions_with_llm
from .tabs.tab_historical import HistoricalTabBuilder
from .tabs.tab_projections import ProjectionsTabBuilder
from .tabs.tab_valuation_perpetual_growth_dcf import ValuationPerpetualGrowthDCFBuilder
from .tabs.tab_valuation_exit_multiple_dcf import ValuationExitMultipleDCFBuilder
from .tabs.tab_sensitivity import SensitivityTabBuilder
from .tabs.tab_summary import SummaryTabBuilder
from .formula_evaluator import FormulaEvaluator


class FinancialModelBuilder:
    """
    Main builder for creating Excel-based DCF financial models.
    
    This class:
    1. Loads JSON financial data from financial_scraper.py
    2. Calls LLM to infer forward-looking assumptions
    3. Builds 9 Excel tabs with formulas:
       - Raw: Flat (Key, Year, Value) database
       - Keys_Map: SUMIFS lookup helper
       - Assumptions: Forward assumptions (LLM-inferred)
       - Historical: Last 5 years actuals
       - Projections: FY1-FY5 forecasts
       - Valuation (DCF): Perpetual Growth DCF
       - Valuation (Exit Multiple): Exit Multiple DCF
       - Sensitivity: 2-way sensitivity analysis
       - Summary: Executive dashboard with 34 metrics
    4. Saves complete model as .xlsx file
    
    All tabs use Excel formulas (no hardcoded values) for banker-grade quality.
    """
    
    def __init__(self, ticker: str):
        """
        Initialize the Financial Model Builder.
        
        Args:
            ticker: Stock ticker symbol (e.g., "NVDA", "AAPL")
        """
        self.ticker = ticker.upper()
        
        # Data
        self.json_data: Optional[Dict[str, Any]] = None
        self.llm_assumptions: Optional[Dict[str, Any]] = None
        
        # Workbook
        self.workbook: Optional[Workbook] = None
        self.build_timestamp: Optional[datetime] = None
        
        # Tab builders (initialized on demand)
        self.raw_builder = RawTabBuilder()
        self.keys_map_builder: Optional[KeysMapTabBuilder] = None
        self.assumptions_builder: Optional[AssumptionsTabBuilder] = None
        self.historical_builder: Optional[HistoricalTabBuilder] = None
        self.projections_builder: Optional[ProjectionsTabBuilder] = None
        self.perpetual_growth_dcf_builder: Optional[ValuationPerpetualGrowthDCFBuilder] = None
        self.exit_multiple_dcf_builder: Optional[ValuationExitMultipleDCFBuilder] = None
        self.sensitivity_builder: Optional[SensitivityTabBuilder] = None
        self.summary_builder: Optional[SummaryTabBuilder] = None
        
        # Formula evaluator (initialized after workbook is built)
        self.formula_evaluator: Optional[FormulaEvaluator] = None
    
    def load_json_file(self, json_path: Path | str) -> None:
        """
        Load financial data from JSON file.
        
        Args:
            json_path: Path to JSON file from financial_scraper.py
            
        Raises:
            FileNotFoundError: If JSON file doesn't exist
        """
        json_path = Path(json_path)
        
        if not json_path.exists():
            raise FileNotFoundError(f"JSON file not found: {json_path}")
        
        with open(json_path, 'r') as f:
            self.json_data = json.load(f)
        
        # Parse into Raw tab data
        self.raw_builder.add_data_from_json(self.json_data)
        
        # Get summary
        summary = self.raw_builder.get_data_summary()
        years_str = ', '.join(map(str, summary['years']))
        
        print(f"✅ Loaded financial data from {json_path.name}")
        print(f"   • Parsed {summary['total_rows']} data rows")
        print(f"   • Years available: {years_str}")
    
    def build_model(self) -> Workbook:
        """
        Build the complete financial model.
        
        This is the main workflow:
        1. Validate data is loaded
        2. Call LLM to infer forward assumptions
        3. Create Excel workbook
        4. Build all 9 tabs in sequence
        5. Set Summary tab as active
        
        Returns:
            The completed Excel workbook
            
        Raises:
            ValueError: If no data loaded
        """
        if self.json_data is None:
            raise ValueError("No data loaded. Call load_json_file() first.")
        
        self.build_timestamp = datetime.now()
        
        print("\n" + "="*70)
        print(f"Building Financial Model for {self.ticker}")
        print("="*70)
        
        # Step 1: Call LLM to infer forward assumptions
        print("\n[Step 1/2] Inferring forward assumptions with LLM...")
        print("-" * 70)
        self.llm_assumptions = infer_assumptions_with_llm(self.json_data)
        print(f"✅ Assumptions inferred:")
        print(f"   • WACC: {self.llm_assumptions.get('wacc', 0)*100:.2f}%")
        print(f"   • Terminal Growth: {self.llm_assumptions.get('terminal_growth_rate', 0)*100:.2f}%")
        print(f"   • Revenue Growth FY1-FY5: {[f'{r*100:.1f}%' for r in self.llm_assumptions.get('revenue_growth_rates', [])]}")
        
        # Step 2: Build all Excel tabs
        print("\n[Step 2/2] Building Excel tabs with formulas...")
        print("-" * 70)
        
        # Create workbook
        self.workbook = openpyxl.Workbook()
        if 'Sheet' in self.workbook.sheetnames:
            self.workbook.remove(self.workbook['Sheet'])
        
        # Initialize all builders
        self.keys_map_builder = KeysMapTabBuilder()
        self.assumptions_builder = AssumptionsTabBuilder(llm_assumptions=self.llm_assumptions)
        self.historical_builder = HistoricalTabBuilder()
        self.projections_builder = ProjectionsTabBuilder()
        self.perpetual_growth_dcf_builder = ValuationPerpetualGrowthDCFBuilder()
        self.exit_multiple_dcf_builder = ValuationExitMultipleDCFBuilder()
        self.sensitivity_builder = SensitivityTabBuilder()
        self.summary_builder = SummaryTabBuilder()
        
        # Build tabs in sequence
        print("[1/9] Building Raw tab...")
        self.raw_builder.create_tab(self.workbook)
        print(f"      ✅ Raw tab created ({len(self.raw_builder.data_rows)} rows)")
        
        print("[2/9] Building Keys_Map tab...")
        # Populate Keys_Map from Raw data
        self.keys_map_builder.build_from_raw_data(self.raw_builder.data_rows)
        self.keys_map_builder.create_tab(self.workbook)
        print(f"      ✅ Keys_Map tab created ({len(self.keys_map_builder.field_mappings)} fields)")
        
        print("[3/9] Building Assumptions tab...")
        self.assumptions_builder.create_tab(self.workbook)
        print("      ✅ Assumptions tab created (with LLM_Inferred hidden tab)")
        
        print("[4/9] Building Historical tab...")
        self.historical_builder.create_tab(self.workbook)
        print("      ✅ Historical tab created (5 years actuals)")
        
        print("[5/9] Building Projections tab...")
        self.projections_builder.create_tab(self.workbook)
        print("      ✅ Projections tab created (FY1-FY5 forecasts)")
        
        print("[6/9] Building Valuation (Perpetual Growth DCF) tab...")
        self.perpetual_growth_dcf_builder.create_tab(self.workbook)
        print("      ✅ Valuation (DCF) tab created")
        
        print("[7/9] Building Valuation (Exit Multiple DCF) tab...")
        self.exit_multiple_dcf_builder.create_tab(self.workbook)
        print("      ✅ Valuation (Exit Multiple) tab created")
        
        print("[8/9] Building Sensitivity tab...")
        self.sensitivity_builder.create_tab(self.workbook)
        print("      ✅ Sensitivity tab created (2-way analysis)")
        
        print("[9/9] Building Summary tab...")
        self.summary_builder.create_tab(self.workbook)
        print("      ✅ Summary tab created (34 metrics)")
        
        # Set Summary as active sheet
        self.workbook.active = self.workbook["Summary"]
        
        # Initialize formula evaluator
        self.formula_evaluator = FormulaEvaluator(self.workbook)
        
        print("\n" + "="*70)
        print("✅ Financial Model Build Complete!")
        print("="*70)
        
        return self.workbook
    
    def save(self, output_path: Path | str) -> None:
        """
        Save the workbook to an Excel file.
        
        Args:
            output_path: Path to save the .xlsx file
            
        Raises:
            ValueError: If model not built yet
        """
        if self.workbook is None:
            raise ValueError("No workbook to save. Call build_model() first.")
        
        output_path = Path(output_path)
        self.workbook.save(output_path)
        
        file_size = output_path.stat().st_size
        print(f"\n✅ Model saved to: {output_path}")
        print(f"   • File size: {file_size:,} bytes ({file_size/1024:.1f} KB)")
    
    def evaluate_and_save_json(self, json_output_path: Optional[Path | str] = None) -> Dict[str, Any]:
        """
        Evaluate all formulas and save computed values to JSON.
        
        This add-on feature:
        1. Evaluates all Excel formulas dynamically
        2. Computes concrete values for every cell
        3. Stores results in a structured JSON file
        
        Args:
            json_output_path: Optional path for JSON output. If None, derives from Excel path.
            
        Returns:
            Dictionary with all evaluated tab values
            
        Raises:
            ValueError: If model not built yet
        """
        if self.workbook is None:
            raise ValueError("No workbook to evaluate. Call build_model() first.")
        
        if self.formula_evaluator is None:
            # Initialize if not already done
            self.formula_evaluator = FormulaEvaluator(self.workbook)
        
        # Evaluate all tabs
        results = self.formula_evaluator.evaluate_all_tabs()
        
        # Save to JSON if path provided
        if json_output_path:
            self.formula_evaluator.save_to_json(results, json_output_path)
        
        return results


def create_financial_model(
    ticker: str,
    json_path: Path | str,
    output_path: Optional[Path | str] = None
) -> FinancialModelBuilder:
    """
    Convenience function to create a financial model in one call.
    
    This is the simplest way to build a model:
    >>> from src.agents.fm import create_financial_model
    >>> create_financial_model("NVDA", "data/NVDA/financials/latest.json")
    
    Args:
        ticker: Stock ticker symbol
        json_path: Path to JSON financial data file
        output_path: Optional output path (default: {ticker}_financial_model.xlsx)
        evaluate_formulas: If True, also generates JSON with computed values
        
    Returns:
        The FinancialModelBuilder instance (in case you need it)
    """
    # Create builder
    builder = FinancialModelBuilder(ticker=ticker)
    
    # Load data
    builder.load_json_file(json_path)
    
    # Build model (this calls LLM internally)
    builder.build_model()
    
    # Save
    if output_path is None:
        output_path = f"{ticker}_financial_model.xlsx"
    builder.save(output_path)
    
    # Evaluate formulas and save to JSON
    # Derive JSON path from Excel path
    excel_path = Path(output_path)
    json_output_path = excel_path.parent / f"{excel_path.stem}_computed_values.json"
    builder.evaluate_and_save_json(json_output_path)
    
    return builder
