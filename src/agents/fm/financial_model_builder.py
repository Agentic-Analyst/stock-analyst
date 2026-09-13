"""
Financial Model Builder - Entry Point

Main orchestrator that builds complete Excel DCF model from JSON data.
This is the ONLY entry point for building financial models.

Architecture:
- Loads JSON financial data
- Builds reproducible numerical assumptions from observable inputs
- Coordinates 9 build stages to create a 10-sheet operating-company model
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
from openpyxl.styles import Alignment
from openpyxl.workbook.workbook import Workbook


# =============================================================================
# Constants
# =============================================================================

# Tab names in order of creation
TAB_NAMES = [
    "Raw",
    "Keys_Map",
    "Assumptions",
    "Model_Inputs",  # Visible audit tab with grounded numerical inputs
    "Historical",
    "Projections",
    "Valuation (DCF)",  # Perpetual Growth DCF
    "Valuation (Exit Multiple)",  # Exit Multiple DCF
    "Sensitivity",
    "Bank Valuation",  # Present only for balance-sheet financials
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
from .tabs.tab_assumptions import (
    AssumptionsTabBuilder,
    source_grounded_bank_assumption_seed,
    source_grounded_assumption_seed,
)
from .tabs.tab_historical import HistoricalTabBuilder
from .tabs.tab_projections import ProjectionsTabBuilder
from .tabs.tab_valuation_perpetual_growth_dcf import ValuationPerpetualGrowthDCFBuilder
from .tabs.tab_valuation_exit_multiple_dcf import ValuationExitMultipleDCFBuilder
from .tabs.tab_sensitivity import SensitivityTabBuilder
from .tabs.tab_summary import SummaryTabBuilder
from .tabs.tab_bank_valuation import BankValuationTabBuilder, apply_bank_summary
from .formula_evaluator import FormulaEvaluator, formula_integrity


class FinancialModelBuilder:
    """
    Main builder for creating Excel-based DCF financial models.
    
    This class:
    1. Loads JSON financial data from financial_scraper.py
    2. Grounds forward-looking numerical assumptions in source data
    3. Builds 10 visible operating-company sheets with formulas:
       - Raw: Flat (Key, Year, Value) database
       - Keys_Map: SUMIFS lookup helper
       - Assumptions: Source-grounded forward assumptions
       - Model_Inputs: Visible derivation and provenance audit
       - Historical: Last 5 years actuals
       - Projections: FY1-FY5 forecasts
       - Valuation (DCF): Perpetual Growth DCF
       - Valuation (Exit Multiple): Exit Multiple DCF
       - Sensitivity: 2-way sensitivity analysis
       - Summary: Executive dashboard and publication state
       Balance-sheet financials use a smaller, method-specific bank workbook.
    4. Saves complete model as .xlsx file
    
    All tabs use Excel formulas (no hardcoded values) for banker-grade quality.
    """
    
    def __init__(self, ticker: str, logger):
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
        self.bank_valuation_override: Optional[Dict[str, Any]] = None
        
        # Formula evaluator (initialized after workbook is built)
        self.formula_evaluator: Optional[FormulaEvaluator] = None
        
        # Logger - will be set by pipeline if available
        self.logger = logger
    
    def _log(self, level: str, message: str):
        """Log message using logger if available, otherwise print."""
        getattr(self.logger, level)(message)

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

        self._log("info", f"✅ Loaded financial data from {json_path.name}")
        self._log("info", f"   • Parsed {summary['total_rows']} data rows")
        self._log("info", f"   • Years available: {years_str}")

    def build_model(self) -> Workbook:
        """
        Build the complete financial model.
        
        This is the main workflow:
        1. Validate data is loaded
        2. Seed forward assumptions from observable source data
        3. Create Excel workbook
        4. Build the applicable operating-company or bank workbook
        5. Set Summary tab as active
        
        Returns:
            The completed Excel workbook
            
        Raises:
            ValueError: If no data loaded
        """
        if self.json_data is None:
            raise ValueError("No data loaded. Call load_json_file() first.")
        from src.valuation_methodology import assess_valuation_methodology
        suitability = assess_valuation_methodology(self.json_data)
        if suitability.get("specialized_service"):
            raise ValueError(
                suitability.get("reason")
                or "This instrument requires a specialized valuation service."
            )
        
        self.build_timestamp = datetime.now()
        
        self._log("info", "="*70)
        self._log("info", f"Building Financial Model for {self.ticker}")
        self._log("info", "="*70)

        is_bank_method = suitability.get("primary_method") == "justified_pb_roe"

        # Step 1: deterministic, source-grounded numerical seed. Generative
        # output is intentionally excluded from the valuation calculation.
        # A bank must be routed before industrial inputs are required: banks
        # often do not publish Operating Income, and that is not a missing
        # input for justified P/B.
        self._log("info", "[Step 1/2] Building source-grounded model inputs...")
        self._log("info", "-" * 70)
        self.llm_assumptions = (
            source_grounded_bank_assumption_seed(self.json_data)
            if is_bank_method else
            source_grounded_assumption_seed(self.json_data)
        )

        # Step 1b: deterministic grounding — CAPM WACC, terminal-growth clamp,
        # trailing-anchored margin paths, company-specific exit multiple. The
        # Numerical parameters a bank computes mechanically are computed
        # mechanically; qualified Street estimates anchor covered years.
        from .assumption_grounding import ground_assumptions
        self.llm_assumptions, grounding_notes = ground_assumptions(
            self.llm_assumptions, self.json_data
        )
        for note in grounding_notes:
            self._log("info", f"   ⚙️ {note}")

        # Select the sector-appropriate method before rendering the workbook,
        # not only after it has been saved.  The old path correctly repaired
        # chat/report state but left bank users downloading a visible $113
        # industrial DCF while the actual JPM method was $281–$297.
        from .bank_valuation import build_bank_valuation_override
        self.bank_valuation_override = build_bank_valuation_override(
            self.json_data,
            terminal_growth=self.llm_assumptions.get("terminal_growth_rate"),
            capm=self.llm_assumptions.get("capm"),
        )
        if (
            is_bank_method
            and not self.bank_valuation_override
        ):
            raise ValueError(
                "Bank valuation failed after method selection; refusing to build an "
                "industrial free-cash-flow DCF for a balance-sheet financial."
            )

        self._log("info", f"✅ Model inputs grounded:")
        self._log("info", f"   • WACC: {self.llm_assumptions.get('wacc', 0)*100:.2f}%")
        self._log("info", f"   • Terminal Growth: {self.llm_assumptions.get('terminal_growth_rate', 0)*100:.2f}%")
        forecast_basis = self.llm_assumptions.get("forecast_basis") or {}
        horizon_prefix = (
            "NTM" if forecast_basis.get("basis") == "rolling_twelve_months" else "FY"
        )
        self._log("info", f"   • Revenue Growth {horizon_prefix}1-{horizon_prefix}5: {[f'{r*100:.1f}%' for r in self.llm_assumptions.get('revenue_growth_rates', [])]}")

        # Step 2: Build all Excel tabs
        self._log("info", "[Step 2/2] Building Excel tabs with formulas...")
        self._log("info", "-" * 70)

        # Create workbook
        self.workbook = openpyxl.Workbook()
        if 'Sheet' in self.workbook.sheetnames:
            self.workbook.remove(self.workbook['Sheet'])
        
        # Initialize all builders
        self.keys_map_builder = KeysMapTabBuilder()
        self.assumptions_builder = AssumptionsTabBuilder(llm_assumptions=self.llm_assumptions)
        self.historical_builder = HistoricalTabBuilder()
        modeling_basis = self.llm_assumptions.get("modeling_basis") or {}
        self.projections_builder = ProjectionsTabBuilder(modeling_basis=modeling_basis)
        self.perpetual_growth_dcf_builder = ValuationPerpetualGrowthDCFBuilder(
            modeling_basis=modeling_basis
        )
        self.exit_multiple_dcf_builder = ValuationExitMultipleDCFBuilder(
            exit_multiple=self.llm_assumptions.get('exit_multiple', 20.0),
            growth_cap=self.llm_assumptions.get('sustainable_growth_cap', 0.04),
            available=self.llm_assumptions.get('exit_multiple_available'),
            modeling_basis=modeling_basis,
        )
        self.sensitivity_builder = SensitivityTabBuilder(modeling_basis=modeling_basis)
        self.summary_builder = SummaryTabBuilder(
            comps_ev_ebitda=self.llm_assumptions.get('comps_ev_ebitda', 0.0),
            comps_ps=self.llm_assumptions.get('comps_ps', 0.0),
            comps_source=self.llm_assumptions.get('comps_source'),
            comps_peer_count=self.llm_assumptions.get('comps_peer_count', 0),
            comps_included_in_blend=self.llm_assumptions.get(
                'comps_included_in_blended_value', True),
            comps_confidence=self.llm_assumptions.get('comps_confidence'),
            comps_role=self.llm_assumptions.get('comps_role'),
            exit_multiple_available=self.llm_assumptions.get(
                'exit_multiple_available'),
            analyst_target=self.llm_assumptions.get('analyst_target_mean', 0.0),
            analyst_target_low=self.llm_assumptions.get('analyst_target_low', 0.0),
            analyst_target_high=self.llm_assumptions.get('analyst_target_high', 0.0),
            analyst_count=self.llm_assumptions.get('analyst_count', 0),
            analyst_source=self.llm_assumptions.get('analyst_consensus_source'),
            analyst_as_of=self.llm_assumptions.get('analyst_consensus_as_of'),
            analyst_captured_at=self.llm_assumptions.get('analyst_consensus_captured_at'),
            analyst_rating=self.llm_assumptions.get('analyst_consensus_rating'),
            currency=(
                ((self.json_data.get("company_data") or {}).get("basic_info") or {})
                .get("currency")
            ),
            modeling_basis=modeling_basis,
        )
        
        # Build tabs in sequence
        self._log("info", "[1/9] Building Raw tab...")
        self.raw_builder.create_tab(self.workbook)
        self._log("info", f"      ✅ Raw tab created ({len(self.raw_builder.data_rows)} rows)")

        self._log("info", "[2/9] Building Keys_Map tab...")
        # Populate Keys_Map from Raw data
        self.keys_map_builder.build_from_raw_data(self.raw_builder.data_rows)
        self.keys_map_builder.create_tab(self.workbook)
        self._log("info", f"      ✅ Keys_Map tab created ({len(self.keys_map_builder.field_mappings)} fields)")

        self._log("info", "[3/9] Building Assumptions tab...")
        self.assumptions_builder.create_tab(self.workbook)
        self._log("info", "      ✅ Assumptions tab created (with visible Model_Inputs audit tab)")
        self._log("info", "[4/9] Building Historical tab...")
        self.historical_builder.create_tab(self.workbook)
        self._log("info", "      ✅ Historical tab created (5 years actuals)")

        if self.bank_valuation_override:
            # Do not build and then hide an industrial DCF. Besides confusing
            # users, its irrelevant formulas can fail and block an otherwise
            # valid bank artifact. The bank workbook gets a clean Summary plus
            # the method-specific tab only.
            self.workbook.create_sheet("Summary")
            BankValuationTabBuilder(
                self.bank_valuation_override, self.json_data
            ).create_tab(self.workbook)
            apply_bank_summary(self.workbook)
            self._log(
                "info",
                "      ✅ Bank Valuation tab created; inapplicable industrial "
                "DCF tabs were never built",
            )
        else:
            self._log("info", "[5/9] Building Projections tab...")
            self.projections_builder.create_tab(self.workbook)
            self._log(
                "info",
                f"      ✅ Projections tab created ({horizon_prefix}1-"
                f"{horizon_prefix}5 forecasts)",
            )

            self._log("info", "[6/9] Building Valuation (Perpetual Growth DCF) tab...")
            self.perpetual_growth_dcf_builder.create_tab(self.workbook)
            self._log("info", "      ✅ Valuation (DCF) tab created")

            self._log("info", "[7/9] Building Valuation (Exit Multiple DCF) tab...")
            self.exit_multiple_dcf_builder.create_tab(self.workbook)
            self._log("info", "      ✅ Valuation (Exit Multiple) tab created")

            self._log("info", "[8/9] Building Sensitivity tab...")
            self.sensitivity_builder.create_tab(self.workbook)
            self._log("info", "      ✅ Sensitivity tab created (2-way analysis)")

            self._log("info", "[9/9] Building Summary tab...")
            self.summary_builder.create_tab(self.workbook)
            self._log("info", "      ✅ Summary tab created (34 metrics)")

        # Set Summary as active sheet
        self.workbook.active = self.workbook["Summary"]
        
        # Initialize formula evaluator
        self.formula_evaluator = FormulaEvaluator(self.workbook)
        self.formula_evaluator.set_logger(self.logger)

        self._log("info", "="*70)
        self._log("info", "✅ Financial Model Build Complete!")
        self._log("info", "="*70)

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
        self._log("info", f"✅ Model saved to: {output_path}")
        self._log("info", f"   • File size: {file_size:,} bytes ({file_size/1024:.1f} KB)")

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
            self.formula_evaluator.set_logger(self.logger)

        # Evaluate all tabs
        results = self.formula_evaluator.evaluate_all_tabs()
        integrity = formula_integrity(results)
        from .formula_evaluator import model_integrity
        semantic_integrity = model_integrity(results)

        # A workbook keeps every scenario number for audit, but downstream
        # APIs also need the deterministic decision about whether that number
        # is safe to present as fair value. Reports carry the same decision in
        # prose; model-only runs do not, so persist it beside the evaluated
        # tabs and fail closed if the boundary itself cannot be computed.
        try:
            from src.valuation_publication_metadata import build_publication_metadata
            publication = build_publication_metadata(
                results,
                self.json_data or {},
                assumptions=self.llm_assumptions or {},
            )
        except Exception as error:
            from src.valuation_publication_metadata import fail_closed_publication_metadata
            publication = fail_closed_publication_metadata(error)
            self._log(
                "error",
                "Valuation publication metadata failed closed: "
                f"{type(error).__name__}",
            )
        if integrity["status"] != "ready" or semantic_integrity["status"] != "ready":
            from src.valuation_publication_metadata import fail_closed_publication_metadata
            publication = fail_closed_publication_metadata(
                RuntimeError(
                    f"{integrity['issue_count']} workbook formula(s) failed evaluation; "
                    f"{semantic_integrity['issue_count']} accounting or valuation "
                    "identity check(s) failed"
                )
            )
            self._log(
                "error",
                "Workbook integrity failed closed: "
                f"{integrity['issue_count']} formula error(s), "
                f"{semantic_integrity['issue_count']} semantic error(s)",
            )
        self._apply_publication_labels(publication)
        self._sync_publication_labels_into_results(results)
        revenue_source = (self.llm_assumptions or {}).get("revenue_growth_source")
        try:
            from src.reinvestment_sensitivity import build_reinvestment_sensitivity
            reinvestment = build_reinvestment_sensitivity(
                results,
                self.json_data or {},
                modeling_basis=(self.llm_assumptions or {}).get("modeling_basis") or {},
            )
        except Exception as error:
            # This diagnostic never grants publication permission and must not
            # block a fully reconciled workbook. Make its failure explicit
            # instead of silently omitting the uncertainty dimension.
            reinvestment = {
                "schema_version": 1,
                "status": "error",
                "included_in_intrinsic_value": False,
                "error_type": type(error).__name__,
                "reason": (
                    "The capex-cycle sensitivity could not be evaluated; no "
                    "normalized reinvestment case is available."
                ),
            }
        results["_vynn"] = {
            "valuation_publication": publication,
            "formula_integrity": integrity,
            "model_integrity": semantic_integrity,
            "reinvestment_sensitivity": reinvestment,
            "model_inputs": {
                "revenue_growth_source": revenue_source,
                "forecast_basis": (self.llm_assumptions or {}).get("forecast_basis"),
                "near_term_revenue_is_consensus_anchored": bool(
                    isinstance(revenue_source, str)
                    and revenue_source.startswith("yahoo_analyst_consensus")
                ),
            },
        }
        
        # Save to JSON if path provided
        if json_output_path:
            self.formula_evaluator.save_to_json(results, json_output_path)
        
        return results

    def _sync_publication_labels_into_results(
        self, results: Dict[str, Any],
    ) -> None:
        """Keep computed JSON aligned with post-evaluation workbook labels.

        Publication metadata depends on evaluated formulas, so the workbook
        labels necessarily change after the first evaluation. Copy only those
        presentation cells back into the already-evaluated payload; formula
        values are untouched.
        """
        if self.workbook is None or not isinstance(results, dict):
            return
        references = {
            "Summary": ("A24", "B24", "G24", "A25", "B25", "A26", "A27"),
            "Sensitivity": ("A34", "A36"),
            "Bank Valuation": ("A18", "B22", "B23"),
        }
        for sheet_name, coordinates in references.items():
            if sheet_name not in self.workbook.sheetnames:
                continue
            tab = results.get(sheet_name)
            cells = tab.get("cells") if isinstance(tab, dict) else None
            if not isinstance(cells, dict):
                continue
            sheet = self.workbook[sheet_name]
            for coordinate in coordinates:
                cell = sheet[coordinate]
                key = f"({cell.row}, {cell.column})"
                # Bank and corporate summaries intentionally have different
                # schemas. Do not manufacture null corporate cells inside a
                # bank sidecar merely because the synchronization list covers
                # both workbook shapes.
                if cell.value is not None or key in cells:
                    cells[key] = cell.value

    def _apply_publication_labels(self, publication: Dict[str, Any]) -> None:
        """Make the downloadable workbook honor the machine publication gate.

        Formula values remain intact for audit. Only their user-facing role is
        changed: a withheld midpoint cannot still be labelled ``Fair Value`` or
        its market gap labelled ordinary upside in the file a user downloads.
        """
        if self.workbook is None or "Summary" not in self.workbook.sheetnames:
            return
        metadata = publication if isinstance(publication, dict) else {}
        withheld = metadata.get("publication_allowed") is not True
        summary = self.workbook["Summary"]
        is_bank = "Bank Valuation" in self.workbook.sheetnames
        low = metadata.get("range_low")
        high = metadata.get("range_high")
        if is_bank:
            summary["A26"] = (
                "Bank valuation audit composite (not published)"
                if withheld else "Bank fair value per share"
            )
            summary["A27"] = (
                "Audit composite vs market (diagnostic)"
                if withheld else "Upside vs market"
            )
            bank = self.workbook["Bank Valuation"]
            bank["A18"] = (
                "Valuation audit composite (not published)"
                if withheld else "Fair value per share"
            )
            bank["B22"] = (
                "WITHHELD — scenario range only" if withheld else "PUBLISHABLE"
            )
            bank["B23"] = str(metadata.get("withheld_reason") or (
                "The deterministic bank-method publication checks passed."
            ))[:32000]
        else:
            summary["A24"] = "Publication status"
            one_visible_estimate = (
                isinstance(low, (int, float)) and not isinstance(low, bool)
                and isinstance(high, (int, float)) and not isinstance(high, bool)
                and round(low, 2) == round(high, 2)
            )
            summary["B24"] = (
                ("WITHHELD — scenario estimate only" if one_visible_estimate
                 else "WITHHELD — scenario range only")
                if withheld else "PUBLISHABLE"
            )
            summary["G24"] = str(metadata.get("withheld_reason") or (
                "The deterministic valuation publication checks passed."
            ))[:32000]
            summary["G24"].alignment = Alignment(wrap_text=True, vertical="top")
            if (isinstance(low, (int, float)) and not isinstance(low, bool)
                    and isinstance(high, (int, float)) and not isinstance(high, bool)
                    and low > 0 and high > 0):
                summary["A25"] = (
                    "Supported DCF scenario estimate"
                    if one_visible_estimate else "Supported scenario range"
                )
                summary["B25"] = (
                    f"{low:,.2f} {self.summary_builder.currency}/share"
                    if one_visible_estimate else
                    f"{low:,.2f} to {high:,.2f} {self.summary_builder.currency}/share"
                )
            summary["A26"] = (
                "DCF scenario midpoint (not published)"
                if withheld else
                ("Blended fair value per share"
                 if self.summary_builder.comps_included_in_blend
                 else "DCF fair value per share")
            )
            summary["A27"] = (
                "Audit midpoint vs market (diagnostic)"
                if withheld else "Upside vs market"
            )
            if "Sensitivity" in self.workbook.sheetnames:
                sensitivity = self.workbook["Sensitivity"]
                sensitivity["A34"] = (
                    "DCF scenario midpoint (not published)"
                    if withheld else "DCF scenario midpoint"
                )
                sensitivity["A36"] = (
                    "Audit midpoint vs market (diagnostic)"
                    if withheld else "Upside vs market"
                )


def create_financial_model(
    ticker: str,
    json_path: Path | str,
    logger,
    output_path: Optional[Path | str] = None
) -> FinancialModelBuilder:
    """
    Convenience function to create a financial model in one call.
    
    This is the simplest way to build a model:
    >>> from src.agents.fm import create_financial_model
    >>> create_financial_model("NVDA", "data/NVDA/financials/latest.json", logger)
    
    Args:
        ticker: Stock ticker symbol
        json_path: Path to JSON financial data file
        output_path: Optional output path (default: {ticker}_financial_model.xlsx)
        logger: Logger with an ``info`` method
        output_path: Optional XLSX path; its computed-values JSON is saved next to it
        
    Returns:
        The FinancialModelBuilder instance (in case you need it)
    """
    # Create builder
    builder = FinancialModelBuilder(ticker=ticker, logger=logger)
    
    # Load data
    builder.load_json_file(json_path)
    
    # Build the numerical model from deterministic, source-grounded inputs.
    builder.build_model()
    
    # Evaluate before saving so the deterministic publication decision can
    # relabel withheld midpoint rows in the downloadable workbook itself.
    if output_path is None:
        output_path = f"{ticker}_financial_model.xlsx"
    excel_path = Path(output_path)
    json_output_path = excel_path.parent / f"{excel_path.stem}_computed_values.json"
    evaluated = builder.evaluate_and_save_json(json_output_path)
    integrity = ((evaluated.get("_vynn") or {}).get("formula_integrity") or {})
    if integrity.get("status") != "ready":
        raise RuntimeError(
            f"Workbook formula integrity failed with {integrity.get('issue_count', 0)} error(s)"
        )
    semantic_integrity = ((evaluated.get("_vynn") or {}).get("model_integrity") or {})
    if semantic_integrity.get("status") != "ready":
        raise RuntimeError(
            "Workbook accounting/valuation identity integrity failed with "
            f"{semantic_integrity.get('issue_count', 0)} error(s)"
        )
    builder.save(output_path)
    
    return builder
