"""
Tab 3: Assumptions Tab Builder with Excel Formulas

This module creates the Assumptions tab with embedded Excel formulas that
reference the Raw tab for calculations. Forward numerical inputs are seeded
from financial statements and qualified analyst estimates, then passed through
the deterministic grounding layer.

Key Design:
- FY0 values use formulas referencing Raw tab
- FY1-FY5 values use formulas referencing the visible Model_Inputs audit tab
"""

from typing import Dict, Optional, Any
import math
import openpyxl
from openpyxl.worksheet.worksheet import Worksheet
from openpyxl.styles import Font, PatternFill, Alignment
from pathlib import Path
import sys

# Add parent directories to path for imports
current_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(current_dir.parent.parent.parent))  # Add 'src' to path

from ..financial_metrics import (
    depreciation_and_amortization,
    depreciation_excel_formula,
)


class AssumptionsTabBuilder:
    """
    Builds the Assumptions tab with Excel formulas referencing Raw tab.
    
    Layout:
    - Column A: Labels
    - Column B: FY0 (latest actual, calculated from Raw using formulas)
    - Columns C-G: FY1-FY5 (formulas referencing Model_Inputs tab)
    """
    
    def __init__(self, llm_assumptions: Optional[Dict[str, Any]] = None):
        """Initialize with source-grounded model assumptions."""
        self.llm_assumptions = llm_assumptions or {}
    
    def create_tab(self, workbook: openpyxl.Workbook) -> Worksheet:
        """Create and format the Assumptions tab with Excel formulas."""
        # Remove existing tabs if they exist
        if "Assumptions" in workbook.sheetnames:
            ws = workbook["Assumptions"]
            workbook.remove(ws)
        if "Model_Inputs" in workbook.sheetnames:
            ws = workbook["Model_Inputs"]
            workbook.remove(ws)

        # Create the visible input/provenance tab first.
        self._create_model_inputs_tab(workbook)

        # Create Assumptions tab
        ws = workbook.create_sheet("Assumptions", 2)

        self._setup_headers(ws)
        self._setup_fy0_year(ws)
        self._setup_valuation_params(ws)
        self._setup_revenue_growth(ws)
        self._setup_operating_margins(ws)
        self._setup_working_capital(ws)
        self._setup_capital_structure(ws)
        self._setup_dcf_parameters(ws)
        self._format_sheet(ws)
        
        return ws
    
    def _create_model_inputs_tab(self, workbook: openpyxl.Workbook) -> None:
        """Create the visible tab containing grounded numerical inputs."""
        ws = workbook.create_sheet("Model_Inputs", 3)
        
        # Headers
        ws.cell(row=1, column=1, value="Metric").font = Font(bold=True)
        forecast_basis = self.llm_assumptions.get("forecast_basis") or {}
        horizon_prefix = (
            "NTM" if forecast_basis.get("basis") == "rolling_twelve_months"
            else "FY"
        )
        for i in range(5):
            ws.cell(
                row=1, column=2 + i, value=f"{horizon_prefix}{i+1}"
            ).font = Font(bold=True)
        
        # WACC and Terminal Growth (same for all years, but we'll put in B column)
        ws.cell(row=2, column=1, value="WACC")
        ws.cell(row=2, column=2, value=self.llm_assumptions.get('wacc'))
        
        ws.cell(row=3, column=1, value="Terminal Growth Rate")
        ws.cell(row=3, column=2, value=self.llm_assumptions.get('terminal_growth_rate'))
        
        # Revenue Growth Rates (FY1-FY5)
        ws.cell(row=4, column=1, value="Revenue Growth Rate")
        rates = self.llm_assumptions.get('revenue_growth_rates', [None] * 5)
        for i, rate in enumerate(rates):
            ws.cell(row=4, column=2 + i, value=rate)
        
        # Gross Margins (FY1-FY5)
        ws.cell(row=5, column=1, value="Gross Margin")
        margins = self.llm_assumptions.get('gross_margins', [None] * 5)
        for i, margin in enumerate(margins):
            ws.cell(row=5, column=2 + i, value=margin)
        
        # EBITDA Margins (FY1-FY5)
        ws.cell(row=6, column=1, value="EBITDA Margin")
        ebitda = self.llm_assumptions.get('ebitda_margins', [None] * 5)
        for i, margin in enumerate(ebitda):
            ws.cell(row=6, column=2 + i, value=margin)
        
        # Operating Margins (FY1-FY5)
        ws.cell(row=7, column=1, value="Operating Margin")
        operating = self.llm_assumptions.get('operating_margins', [None] * 5)
        for i, margin in enumerate(operating):
            ws.cell(row=7, column=2 + i, value=margin)
        
        # DSO Days (FY1-FY5)
        ws.cell(row=8, column=1, value="DSO Days")
        dso = self.llm_assumptions.get('dso_days', [None] * 5)
        for i, days in enumerate(dso):
            ws.cell(row=8, column=2 + i, value=days)
        
        # DIO Days (FY1-FY5)
        ws.cell(row=9, column=1, value="DIO Days")
        dio = self.llm_assumptions.get('dio_days', [None] * 5)
        for i, days in enumerate(dio):
            ws.cell(row=9, column=2 + i, value=days)
        
        # DPO Days (FY1-FY5)
        ws.cell(row=10, column=1, value="DPO Days")
        dpo = self.llm_assumptions.get('dpo_days', [None] * 5)
        for i, days in enumerate(dpo):
            ws.cell(row=10, column=2 + i, value=days)

        # One normalized forward tax rate feeds both NOPAT and after-tax debt
        # cost.  Previously WACC used TTM tax while this workbook independently
        # recomputed the latest annual rate, creating two answers in one model.
        capm = self.llm_assumptions.get("capm") or {}
        ws.cell(row=11, column=1, value="Normalized Cash Tax Rate")
        ws.cell(row=11, column=2, value=capm.get("tax_rate", 0.25))
        ws.cell(row=11, column=2).number_format = '0.00%'
        ws.cell(row=11, column=3, value=capm.get("tax_rate_source"))

        # Make the change in forecast clock visible. A user should not have to
        # inspect a literal formula in Projections!B3 to discover that FY0 is a
        # current TTM base and 0y/+1y consensus has been blended into NTM1.
        if forecast_basis.get("basis") == "rolling_twelve_months":
            ws.cell(row=12, column=1, value="Forecast Basis")
            ws.cell(row=12, column=2, value="Rolling twelve months")
            ws.cell(row=12, column=3, value=forecast_basis.get("method"))
            ws.cell(row=13, column=1, value="Forecast Base Period End")
            ws.cell(row=13, column=2, value=forecast_basis.get("period_end"))
            ws.cell(row=14, column=1, value="TTM Revenue Base")
            ws.cell(row=14, column=2, value=forecast_basis.get("base_revenue"))
            ws.cell(row=14, column=2).number_format = '#,##0'
            ws.cell(row=15, column=1, value="Fiscal Year Elapsed")
            ws.cell(
                row=15, column=2,
                value=forecast_basis.get("fiscal_year_progress"),
            ).number_format = '0.0%'

        # This tab intentionally stays visible so every model input is auditable.

    def _setup_headers(self, ws: Worksheet) -> None:
        """Set up column headers."""
        ws.cell(row=1, column=1, value="Metric").font = Font(bold=True)
        ws.cell(row=1, column=2, value="Latest FY Actual").font = Font(bold=True)
        forecast_basis = self.llm_assumptions.get("forecast_basis") or {}
        horizon_prefix = (
            "NTM" if forecast_basis.get("basis") == "rolling_twelve_months"
            else "FY"
        )
        for i in range(5):
            col = 3 + i
            ws.cell(
                row=1, column=col, value=f"{horizon_prefix}{i+1}"
            ).font = Font(bold=True)
    
    def _setup_fy0_year(self, ws: Worksheet) -> None:
        """Set up FY0 year extraction using simpler approach."""
        ws.cell(row=2, column=1, value="Latest Fiscal Year (FY0)").font = Font(bold=True, italic=True)
        # Use INDEX/MATCH to find the latest year from Raw tab
        # Simpler formula: just show latest year as a number
        ws.cell(row=2, column=2, value='=VALUE(LEFT(INDEX(Raw!$C:$C,MATCH("Total Revenue",Raw!$B:$B,0)),4))').number_format = '0'
    
    def _setup_valuation_params(self, ws: Worksheet) -> None:
        """Set up valuation parameters."""
        ws.cell(row=3, column=1, value="VALUATION PARAMETERS").font = Font(bold=True, size=11)
        
        # WACC
        ws.cell(row=4, column=1, value="WACC").font = Font(bold=True)
        ws.cell(row=4, column=2, value='=Model_Inputs!B2').number_format = '0.00%'
        ws.cell(row=4, column=3, value="[Derived CAPM / observed capital structure]").font = Font(italic=True, size=9)
        
        # Terminal Growth Rate
        ws.cell(row=5, column=1, value="Terminal Growth Rate (g)").font = Font(bold=True)
        ws.cell(row=5, column=2, value='=Model_Inputs!B3').number_format = '0.00%'
        ws.cell(row=5, column=3, value="[Grounded to long-run band and currency risk-free cap]").font = Font(italic=True, size=9)
    
    def _setup_revenue_growth(self, ws: Worksheet) -> None:
        """Set up revenue growth with formulas."""
        ws.cell(row=6, column=1, value="REVENUE GROWTH ASSUMPTIONS").font = Font(bold=True, size=11)
        
        ws.cell(row=7, column=1, value="Revenue Growth (YoY)").font = Font(bold=True)
        
        # FY0: Calculate from Raw tab - use INDIRECT to avoid complex date matching
        # Simplified: Use helper cells or direct reference
        # For now, use a simpler SUMIFS approach
        formula_fy0 = (
            '=IFERROR('
            'SUMIFS(Raw!$D:$D,Raw!$B:$B,"Total Revenue",Raw!$C:$C,$B$2&"*")/'
            'SUMIFS(Raw!$D:$D,Raw!$B:$B,"Total Revenue",Raw!$C:$C,($B$2-1)&"*")-1,'
            '"")'
        )
        ws.cell(row=7, column=2, value=formula_fy0).number_format = '0.00%'
        
        # FY1-FY5: Reference Model_Inputs tab (columns B-F)
        for i in range(5):
            col_letter = chr(66 + i)  # B, C, D, E, F in Model_Inputs
            # Use simple IFERROR for compatibility with all Excel versions
            if i == 0:
                # FY1: fallback to FY0 (B7) if blank
                formula = f'=IF(IFERROR(Model_Inputs!{col_letter}4,"")<>"",Model_Inputs!{col_letter}4,B7)'
            else:
                # FY2-FY5: fallback to previous FY
                prev_col = chr(66 + i)  # C, D, E, F (previous column in Assumptions tab)
                formula = f'=IF(IFERROR(Model_Inputs!{col_letter}4,"")<>"",Model_Inputs!{col_letter}4,{prev_col}7)'
            ws.cell(row=7, column=3 + i, value=formula).number_format = '0.00%'
    
    def _setup_operating_margins(self, ws: Worksheet) -> None:
        """Set up operating margins with formulas."""
        ws.cell(row=8, column=1, value="OPERATING MARGIN ASSUMPTIONS").font = Font(bold=True, size=11)
        
        # Gross Margin
        ws.cell(row=9, column=1, value="Gross Margin").font = Font(bold=True)
        formula_fy0 = (
            '=IFERROR('
            'SUMIFS(Raw!$D:$D,Raw!$B:$B,"Gross Profit",Raw!$C:$C,$B$2&"*")/'
            'SUMIFS(Raw!$D:$D,Raw!$B:$B,"Total Revenue",Raw!$C:$C,$B$2&"*"),'
            '"")'
        )
        ws.cell(row=9, column=2, value=formula_fy0).number_format = '0.00%'
        
        # FY1-FY5: Reference Model_Inputs (columns B-F)
        for i in range(5):
            col_letter = chr(66 + i)  # B, C, D, E, F
            if i == 0:
                formula = f'=IF(IFERROR(Model_Inputs!{col_letter}5,"")<>"",Model_Inputs!{col_letter}5,B9)'
            else:
                prev_col = chr(66 + i)  # C, D, E, F
                formula = f'=IF(IFERROR(Model_Inputs!{col_letter}5,"")<>"",Model_Inputs!{col_letter}5,{prev_col}9)'
            ws.cell(row=9, column=3 + i, value=formula).number_format = '0.00%'
        
        # EBITDA Margin
        ws.cell(row=10, column=1, value="EBITDA Margin").font = Font(bold=True)
        formula_fy0 = (
            '=IFERROR('
            '(SUMIFS(Raw!$D:$D,Raw!$B:$B,"Operating Income",Raw!$C:$C,$B$2&"*")+'
            f'{depreciation_excel_formula("$B$2")})/'
            'SUMIFS(Raw!$D:$D,Raw!$B:$B,"Total Revenue",Raw!$C:$C,$B$2&"*"),'
            '"")'
        )
        ws.cell(row=10, column=2, value=formula_fy0).number_format = '0.00%'
        
        # FY1-FY5: Reference Model_Inputs (columns B-F)
        for i in range(5):
            col_letter = chr(66 + i)  # B, C, D, E, F
            if i == 0:
                formula = f'=IF(IFERROR(Model_Inputs!{col_letter}6,"")<>"",Model_Inputs!{col_letter}6,B10)'
            else:
                prev_col = chr(66 + i)  # C, D, E, F
                formula = f'=IF(IFERROR(Model_Inputs!{col_letter}6,"")<>"",Model_Inputs!{col_letter}6,{prev_col}10)'
            ws.cell(row=10, column=3 + i, value=formula).number_format = '0.00%'
        
        # Operating Margin
        ws.cell(row=11, column=1, value="Operating Margin").font = Font(bold=True)
        formula_fy0 = (
            '=IFERROR('
            'SUMIFS(Raw!$D:$D,Raw!$B:$B,"Operating Income",Raw!$C:$C,$B$2&"*")/'
            'SUMIFS(Raw!$D:$D,Raw!$B:$B,"Total Revenue",Raw!$C:$C,$B$2&"*"),'
            '"")'
        )
        ws.cell(row=11, column=2, value=formula_fy0).number_format = '0.00%'
        
        # FY1-FY5: Reference Model_Inputs (columns B-F)
        for i in range(5):
            col_letter = chr(66 + i)  # B, C, D, E, F
            if i == 0:
                formula = f'=IF(IFERROR(Model_Inputs!{col_letter}7,"")<>"",Model_Inputs!{col_letter}7,B11)'
            else:
                prev_col = chr(66 + i)  # C, D, E, F
                formula = f'=IF(IFERROR(Model_Inputs!{col_letter}7,"")<>"",Model_Inputs!{col_letter}7,{prev_col}11)'
            ws.cell(row=11, column=3 + i, value=formula).number_format = '0.00%'
    
    def _setup_working_capital(self, ws: Worksheet) -> None:
        """Set up working capital with formulas."""
        ws.cell(row=12, column=1, value="WORKING CAPITAL ASSUMPTIONS").font = Font(bold=True, size=11)
        
        # DSO
        ws.cell(row=13, column=1, value="DSO (Days)").font = Font(bold=True)
        formula_fy0 = (
            '=IFERROR('
            'SUMIFS(Raw!$D:$D,Raw!$B:$B,"Accounts Receivable",Raw!$C:$C,$B$2&"*")/'
            '(SUMIFS(Raw!$D:$D,Raw!$B:$B,"Total Revenue",Raw!$C:$C,$B$2&"*")/365),'
            '"")'
        )
        ws.cell(row=13, column=2, value=formula_fy0).number_format = '0.0'
        
        # FY1-FY5: Reference Model_Inputs (columns B-F)
        for i in range(5):
            col_letter = chr(66 + i)  # B, C, D, E, F
            if i == 0:
                formula = f'=IF(IFERROR(Model_Inputs!{col_letter}8,"")<>"",Model_Inputs!{col_letter}8,B13)'
            else:
                prev_col = chr(66 + i)  # C, D, E, F
                formula = f'=IF(IFERROR(Model_Inputs!{col_letter}8,"")<>"",Model_Inputs!{col_letter}8,{prev_col}13)'
            ws.cell(row=13, column=3 + i, value=formula).number_format = '0.0'
        
        # DIO
        ws.cell(row=14, column=1, value="DIO (Days)").font = Font(bold=True)
        formula_fy0 = (
            '=IFERROR('
            'SUMIFS(Raw!$D:$D,Raw!$B:$B,"Inventory",Raw!$C:$C,$B$2&"*")/'
            '(SUMIFS(Raw!$D:$D,Raw!$B:$B,"Cost Of Revenue",Raw!$C:$C,$B$2&"*")/365),'
            '"")'
        )
        ws.cell(row=14, column=2, value=formula_fy0).number_format = '0.0'
        
        # FY1-FY5: Reference Model_Inputs (columns B-F)
        for i in range(5):
            col_letter = chr(66 + i)  # B, C, D, E, F
            if i == 0:
                formula = f'=IF(IFERROR(Model_Inputs!{col_letter}9,"")<>"",Model_Inputs!{col_letter}9,B14)'
            else:
                prev_col = chr(66 + i)  # C, D, E, F
                formula = f'=IF(IFERROR(Model_Inputs!{col_letter}9,"")<>"",Model_Inputs!{col_letter}9,{prev_col}14)'
            ws.cell(row=14, column=3 + i, value=formula).number_format = '0.0'
        
        # DPO
        ws.cell(row=15, column=1, value="DPO (Days)").font = Font(bold=True)
        formula_fy0 = (
            '=IFERROR('
            'SUMIFS(Raw!$D:$D,Raw!$B:$B,"Accounts Payable",Raw!$C:$C,$B$2&"*")/'
            '(SUMIFS(Raw!$D:$D,Raw!$B:$B,"Cost Of Revenue",Raw!$C:$C,$B$2&"*")/365),'
            '"")'
        )
        ws.cell(row=15, column=2, value=formula_fy0).number_format = '0.0'
        
        # FY1-FY5: Reference Model_Inputs (columns B-F)
        for i in range(5):
            col_letter = chr(66 + i)  # B, C, D, E, F
            if i == 0:
                formula = f'=IF(IFERROR(Model_Inputs!{col_letter}10,"")<>"",Model_Inputs!{col_letter}10,B15)'
            else:
                prev_col = chr(66 + i)  # C, D, E, F
                formula = f'=IF(IFERROR(Model_Inputs!{col_letter}10,"")<>"",Model_Inputs!{col_letter}10,{prev_col}15)'
            ws.cell(row=15, column=3 + i, value=formula).number_format = '0.0'
        
        # CCC - ALL columns use formulas
        ws.cell(row=16, column=1, value="Cash Conversion Cycle (Days)").font = Font(bold=True)
        ws.cell(row=16, column=2, value='=IFERROR(B13+B14-B15,"")').number_format = '0.0'
        
        for i in range(5):
            col_letter = chr(67 + i)
            ws.cell(row=16, column=3 + i, value=f'=IFERROR({col_letter}13+{col_letter}14-{col_letter}15,"")').number_format = '0.0'
    
    def _setup_capital_structure(self, ws: Worksheet) -> None:
        """Set up capital structure."""
        ws.cell(row=17, column=1, value="CAPITAL STRUCTURE").font = Font(bold=True, size=11)
        
        # Shares Outstanding
        ws.cell(row=18, column=1, value="Shares Outstanding (latest)").font = Font(bold=True)
        # Value per share divides by THIS cell. "Diluted Average Shares" is a
        # period average and lags any issuance: PC Jeweller's was 8.61B against
        # 9.75B actually outstanding (value overstated 13%); PayPal's 968M
        # against 855M after buybacks (understated 13%). Prefer the live count
        # the scraper captured; fall back to the year-end balance-sheet count,
        # then the average.
        live_shares = self.llm_assumptions.get("shares_outstanding_current")
        if isinstance(live_shares, (int, float)) and live_shares > 0:
            ws.cell(row=18, column=2, value=float(live_shares)).number_format = '#,##0'
        else:
            ws.cell(row=18, column=2, value=(
                '=IFERROR(IF(SUMIFS(Raw!$D:$D,Raw!$B:$B,"Ordinary Shares Number",Raw!$C:$C,$B$2&"*")>0,'
                'SUMIFS(Raw!$D:$D,Raw!$B:$B,"Ordinary Shares Number",Raw!$C:$C,$B$2&"*"),'
                'SUMIFS(Raw!$D:$D,Raw!$B:$B,"Diluted Average Shares",Raw!$C:$C,$B$2&"*")),'
                'SUMIFS(Raw!$D:$D,Raw!$B:$B,"Diluted Average Shares",Raw!$C:$C,$B$2&"*"))'
            )).number_format = '#,##0'
        ws.cell(row=18, column=3, value=(
            "[Live shares outstanding]" if isinstance(live_shares, (int, float)) and live_shares > 0
            else "[Year-end shares, else diluted average]"
        )).font = Font(italic=True, size=9)
        
        # Net Debt
        ws.cell(row=19, column=1, value="Net Debt (latest)").font = Font(bold=True)
        formula = (
            '=SUMIFS(Raw!$D:$D,Raw!$B:$B,"Total Debt",Raw!$C:$C,$B$2&"*")-'
            'SUMIFS(Raw!$D:$D,Raw!$B:$B,"Cash And Cash Equivalents",Raw!$C:$C,$B$2&"*")'
        )
        ws.cell(row=19, column=2, value=formula).number_format = '#,##0'
        ws.cell(row=19, column=3, value="[From JSON]").font = Font(italic=True, size=9)
        
        # Normalized Cash Tax Rate. It is a forward modeling assumption, not a
        # claim that the latest accounting-period effective rate repeats.
        ws.cell(row=20, column=1, value="Normalized Cash Tax Rate").font = Font(bold=True)
        ws.cell(row=20, column=2, value='=Model_Inputs!B11').number_format = '0.00%'
        ws.cell(row=20, column=3, value=(
            "[Same normalized issuer rate used in NOPAT and after-tax debt cost]"
        )).font = Font(italic=True, size=9)
    
    def _setup_dcf_parameters(self, ws: Worksheet) -> None:
        """Set up DCF valuation parameters (rows 21-36)."""
        # Section header
        ws.cell(row=21, column=1, value="DCF VALUATION PARAMETERS").font = Font(bold=True, size=11)
        
        # Subsection: Cost of Equity Inputs
        ws.cell(row=22, column=1, value="Cost of Equity Inputs:")
        ws.cell(row=22, column=1).font = Font(bold=True, italic=True, size=10)
        
        # Every cell below used to be a literal — Rf 4.5%, ERP 6.5%, beta 1.2,
        # Kd 5.5%, equity weight 85% — for every company on earth, whatever its
        # actual beta, domicile or currency. The DCF tab reads these cells, so
        # the workbook discounted LVMH (observed beta 0.84, euro issuer) at
        # 11.01% and returned EUR 269/share against a EUR 452 market price,
        # while the report printed a different, CAPM-derived rate that nothing
        # used. They are now seeded from that same CAPM derivation.
        #
        # They remain plain values, not formulas: the point of shipping a
        # workbook is that a reader can change the discount rate and watch the
        # valuation move.
        capm = self.llm_assumptions.get("capm") or {}

        def _seed(row: int, label: str, key: str, default, fmt: str, note: str):
            value = capm.get(key, default)
            ws.cell(row=row, column=1, value=label).font = Font(bold=True)
            ws.cell(row=row, column=2, value=value).number_format = fmt
            ws.cell(row=row, column=3, value=note).font = Font(italic=True, size=9)

        _seed(23, "Risk-Free Rate (Rf)", "risk_free_rate", 0.045, '0.00%',
              f"[{capm.get('risk_free_source', '10Y government bond')}]")
        # The cell carries the mature-market ERP PLUS the country premium so
        # the tab's Ke = Rf + beta x B24 reproduces the CAPM's own cost of
        # equity. The note says what was added.
        _crp = capm.get("country_risk_premium") or 0.0
        _erp_source = capm.get("mature_erp_selected_source") or "source unavailable"
        _erp_as_of = capm.get("mature_erp_as_of")
        _erp_date = f", as of {_erp_as_of}" if _erp_as_of else ""
        _base = (
            f"Mature-market ERP "
            f"{capm.get('equity_risk_premium', 0.055)*100:.2f}% "
            f"({_erp_source}{_erp_date})"
        )
        _seed(24, "Equity Risk Premium (ERP + country premium)", "equity_risk_premium_total", 0.055, '0.00%',
              f"[{_base} + country premium {_crp*100:.2f}%: {capm.get('crp_source', 'none')}]"
              if capm else "[Mature-market ERP]")
        _seed(25, "Levered Beta (β)", "beta", 1.0, '0.00',
              f"[{capm.get('beta_source', 'observed beta')}]")

        # Subsection: Cost of Debt Inputs
        ws.cell(row=26, column=1, value="Cost of Debt Inputs:").font = Font(bold=True, italic=True, size=10)

        _seed(27, "Pre-Tax Cost of Debt (Kd)", "pre_tax_cost_of_debt", 0.055, '0.00%',
              f"[{capm.get('kd_source', 'Risk-free + credit spread')}]")

        # Subsection: Capital Structure
        ws.cell(row=28, column=1, value="Capital Structure Weights:").font = Font(bold=True, italic=True, size=10)

        _seed(29, "Equity Weight (E/V)", "equity_weight", 0.85, '0.00%',
              f"[{capm.get('weights_note', 'Market cap / (market cap + total debt)')}]")
        
        # Terminal Growth Rate (row 35 in markdown, row 30 here)
        ws.cell(row=30, column=1, value="Terminal Growth Rate (g)").font = Font(bold=True)
        ws.cell(row=30, column=2, value='=Model_Inputs!B3').number_format = '0.00%'
        _tg_note = self.llm_assumptions.get("terminal_growth_note")
        ws.cell(row=30, column=3, value=(
            f"[{_tg_note}]" if _tg_note
            else "[Grounded to long-run band and currency risk-free cap]"
        )).font = Font(italic=True, size=9)
        
        # Shares Outstanding (row 36 in markdown, row 31 here)
        ws.cell(row=31, column=1, value="Shares Outstanding (for valuation)").font = Font(bold=True)
        ws.cell(row=31, column=2, value='=B18').number_format = '#,##0'  # Reference row 18
        ws.cell(row=31, column=3, value="[From row 18]").font = Font(italic=True, size=9)

    
    def _format_sheet(self, ws: Worksheet) -> None:
        """Apply formatting."""
        ws.column_dimensions['A'].width = 35
        ws.column_dimensions['B'].width = 18
        # Column C carries the provenance notes — where the risk-free rate,
        # the premium and the beta came from — which run to a sentence.
        ws.column_dimensions['C'].width = 70
        for col in ['D', 'E', 'F', 'G', 'H']:
            ws.column_dimensions[col].width = 12
        ws.freeze_panes = ws['A2']
    
    def get_summary(self) -> Dict[str, Any]:
        """Get summary."""
        return {
            'wacc': self.llm_assumptions.get('wacc'),
            'terminal_growth_rate': self.llm_assumptions.get('terminal_growth_rate'),
            'projection_years': 5
        }


def _finite_number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _statement_value(row: Dict[str, Any], *keys: str) -> Optional[float]:
    for key in keys:
        value = _finite_number(row.get(key))
        if value is not None:
            return value
    return None


def source_grounded_assumption_seed(json_data: Dict[str, Any]) -> Dict[str, Any]:
    """Build a deterministic starting point from observable source data.

    This is deliberately not a valuation opinion.  The grounding layer later
    replaces WACC, terminal growth, covered revenue years, normalized margins,
    working capital, and terminal multiples with their authoritative methods.
    The seed exists so a model is reproducible and an LLM/network outage cannot
    either abort a run or inject generic software-company margins.
    """
    statements = (json_data.get("financial_statements") or {})
    income = statements.get("income_statement") or {}
    balance = statements.get("balance_sheet") or {}
    periods = sorted(
        (period for period, row in income.items() if isinstance(row, dict)),
        key=str,
        reverse=True,
    )
    if not periods:
        raise ValueError("Cannot build model inputs: no annual income statements")
    latest_period = periods[0]
    latest_income = income[latest_period]
    latest_balance = balance.get(latest_period) or {}
    latest_revenue = _statement_value(latest_income, "Total Revenue", "Operating Revenue")
    latest_operating = _statement_value(latest_income, "Operating Income")
    if latest_revenue is None or latest_revenue <= 0 or latest_operating is None:
        raise ValueError(
            "Cannot build model inputs: latest annual revenue and operating income "
            "must be present and finite"
        )

    # Prefer a qualified historical CAGR, then the latest annual change.  This
    # is only the uncovered-year seed; qualified Street revenue dollars replace
    # FY1/FY2 and the grounding layer creates the deterministic fade thereafter.
    history = (((json_data.get("modeling_metrics") or {})
                .get("historical_growth_rates") or {})
               .get("revenue_growth") or {})
    growth = _finite_number(history.get("cagr_3y"))
    growth_source = "three_year_revenue_cagr"
    if growth is None and len(periods) > 1:
        prior_revenue = _statement_value(
            income[periods[1]], "Total Revenue", "Operating Revenue"
        )
        if prior_revenue and prior_revenue > 0:
            growth = latest_revenue / prior_revenue - 1.0
            growth_source = "latest_annual_revenue_growth"
    if growth is None:
        growth = 0.0
        growth_source = "zero_growth_when_history_unavailable"
    # This is a provider/unit sanity rail, not a mature-company forecast.  A
    # qualified absolute analyst forecast can still exceed it downstream.
    growth = max(-0.50, min(1.00, growth))
    terminal = 0.025
    growth_path = [
        terminal + (growth - terminal) * factor
        for factor in (1.0, 0.80, 0.60, 0.40, 0.20)
    ]

    bridge = json_data.get("ttm_bridge") or {}
    current_income = (
        bridge.get("income_statement") or {}
        if bridge.get("status") == "current" else latest_income
    )
    current_cash = (
        bridge.get("cash_flow") or {}
        if bridge.get("status") == "current" else {}
    )
    current_revenue = _statement_value(
        current_income, "Total Revenue", "Operating Revenue"
    ) or latest_revenue
    current_operating = _statement_value(current_income, "Operating Income")
    if current_operating is None:
        current_operating = latest_operating
    gross_profit = _statement_value(current_income, "Gross Profit")
    if gross_profit is None:
        gross_profit = _statement_value(latest_income, "Gross Profit")
    ebitda = _statement_value(current_income, "EBITDA")
    if ebitda is None:
        da = _statement_value(
            current_cash,
            "Depreciation And Amortization",
            "Depreciation Amortization Depletion",
            "Depreciation",
        )
        if da is None:
            da = depreciation_and_amortization(statements, latest_period)
        # Operating income is EBIT.  If D&A is unavailable, using EBIT as the
        # EBITDA seed is conservative and transparent; no margin is invented.
        ebitda = current_operating + (float(da) if da is not None else 0.0)

    def margin_path(amount: Optional[float]) -> list:
        margin = amount / current_revenue if amount is not None and current_revenue else None
        return [margin] * 5

    cogs = _statement_value(
        latest_income, "Cost Of Revenue", "Reconciled Cost Of Revenue"
    )

    def days(numerator: Optional[float], denominator: Optional[float]) -> list:
        value = (
            numerator / denominator * 365.0
            if numerator is not None and denominator and denominator > 0 else None
        )
        return [value] * 5

    assumptions = {
        "wacc": None,
        "terminal_growth_rate": terminal,
        "revenue_growth_rates": growth_path,
        "gross_margins": margin_path(gross_profit),
        "ebitda_margins": margin_path(ebitda),
        "operating_margins": margin_path(current_operating),
        "dso_days": days(
            _statement_value(latest_balance, "Accounts Receivable", "Receivables"),
            latest_revenue,
        ),
        "dio_days": days(_statement_value(latest_balance, "Inventory"), cogs),
        "dpo_days": days(
            _statement_value(
                latest_balance, "Accounts Payable", "Payables",
                "Payables And Accrued Expenses",
            ),
            cogs,
        ),
        "assumption_seed_source": growth_source,
        "assumption_seed_period": latest_period,
    }
    return assumptions


def source_grounded_bank_assumption_seed(
    json_data: Dict[str, Any],
) -> Dict[str, Any]:
    """Seed only the shared discount-rate inputs for a bank workbook.

    Banks commonly do not report ``Operating Income`` because interest income,
    funding costs, provisions, and equity capital are the relevant economics.
    Requiring that industrial line before selecting justified P/B prevented a
    valid JPM model from being built at all.  Blank industrial drivers are
    intentional here: :func:`ground_assumptions` will populate CAPM and the
    long-run rate, while the bank model derives book value and normalized ROE
    independently.  No fabricated operating margin is introduced merely to
    satisfy an inapplicable DCF schema.
    """
    statements = (json_data.get("financial_statements") or {})
    income = statements.get("income_statement") or {}
    periods = sorted(
        (period for period, row in income.items() if isinstance(row, dict)),
        key=str,
        reverse=True,
    )
    return {
        "wacc": None,
        "terminal_growth_rate": 0.025,
        "revenue_growth_rates": [],
        "gross_margins": [],
        "ebitda_margins": [],
        "operating_margins": [],
        "dso_days": [],
        "dio_days": [],
        "dpo_days": [],
        "assumption_seed_source": "not_applicable_to_bank_valuation",
        "assumption_seed_period": periods[0] if periods else None,
    }


def infer_assumptions_with_llm(json_data: Dict[str, Any]) -> Dict[str, Any]:
    """Deprecated compatibility alias for the old public entry point.

    Numerical valuation assumptions must not depend on generative output.  Keep
    the name temporarily so external callers do not break, but return exactly
    the same deterministic source-grounded seed as the model builder.
    """
    return source_grounded_assumption_seed(json_data)
