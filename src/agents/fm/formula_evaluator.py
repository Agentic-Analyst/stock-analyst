"""
Formula Evaluator - Compute Excel formulas without opening Excel

This module evaluates Excel formulas dynamically and generates a JSON file
containing all computed values for every tab and cell in the financial model.

Architecture:
- Respects tab dependency order (Raw → Keys_Map → ... → Summary)
- Evaluates formulas recursively using previously computed tab values
- Handles cell references, arithmetic operations, and Excel functions
- Outputs structured JSON with all computed values

Usage:
    from src.agents.fm.formula_evaluator import FormulaEvaluator
    
    evaluator = FormulaEvaluator(workbook)
    results = evaluator.evaluate_all_tabs()
    evaluator.save_to_json(results, "output_path.json")
"""
import ast
import json
import math
import re
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional, Union
from openpyxl.workbook.workbook import Workbook
from openpyxl.utils import get_column_letter, column_index_from_string


def formula_integrity(results: Dict[str, Any]) -> Dict[str, Any]:
    """Return a bounded manifest of formula failures in an evaluated model."""
    issues = []
    for tab_name, tab in (results or {}).items():
        if tab_name == "_vynn" or not isinstance(tab, dict):
            continue
        cells = tab.get("cells") or {}
        if not isinstance(cells, dict):
            issues.append({
                "tab": str(tab_name), "cell": None,
                "error": "tab cells payload is not an object",
            })
            continue
        for cell, value in cells.items():
            if isinstance(value, dict) and value.get("error"):
                issues.append({
                    "tab": str(tab_name),
                    "cell": str(cell),
                    "error": str(value.get("error"))[:500],
                    "formula": str(value.get("formula") or "")[:500] or None,
                })
    return {
        "status": "ready" if not issues else "error",
        "issue_count": len(issues),
        "issues": issues[:50],
        "issues_truncated": len(issues) > 50,
    }


def model_integrity(results: Dict[str, Any]) -> Dict[str, Any]:
    """Validate accounting and valuation identities after formula evaluation.

    A formula can evaluate perfectly and still point at the wrong cell.  That
    class of defect survived the old manifest: PP&E began from historical free
    cash flow, and an incomplete SG&A disclosure made visible EBIT differ from
    reported operating income by more than $100B.  These checks validate the
    *meaning* of the evaluated workbook, not merely its Excel syntax.
    """
    results = results if isinstance(results, dict) else {}
    issues: List[Dict[str, Any]] = []

    def cell(tab: str, row: int, col: int):
        payload = results.get(tab) or {}
        cells = payload.get("cells") if isinstance(payload, dict) else None
        return cells.get(f"({row}, {col})") if isinstance(cells, dict) else None

    def number(value: Any) -> Optional[float]:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        value = float(value)
        return value if math.isfinite(value) else None

    def add_issue(check: str, tab: str, col: Optional[int], **detail: Any):
        item = {"check": check, "tab": tab, "column": col}
        item.update({key: value for key, value in detail.items() if value is not None})
        issues.append(item)

    def identity(check: str, tab: str, col: int, actual: Any, expected: Any):
        actual_n, expected_n = number(actual), number(expected)
        if actual_n is None or expected_n is None:
            add_issue(
                check, tab, col, error="identity input is not a finite number",
                actual=actual, expected=expected,
            )
            return
        tolerance = max(0.01, 1e-6 * max(abs(actual_n), abs(expected_n), 1.0))
        delta = actual_n - expected_n
        if abs(delta) > tolerance:
            add_issue(
                check, tab, col, actual=actual_n, expected=expected_n,
                delta=delta, tolerance=tolerance,
            )

    is_bank_model = "Bank Valuation" in results and "Projections" not in results
    required_tabs = (
        ("Bank Valuation", "Summary") if is_bank_model else
        ("Historical", "Projections", "Valuation (DCF)",
         "Valuation (Exit Multiple)", "Summary")
    )
    for tab in required_tabs:
        if tab not in results:
            add_issue("required_tab", tab, None, error="required model tab is missing")
    if issues:
        return {
            "status": "error", "issue_count": len(issues),
            "issues": issues[:100], "issues_truncated": len(issues) > 100,
        }

    # Historical accounting presentation and provider/recalculation tie-outs.
    active_history = [
        col for col in range(2, 7) if number(cell("Historical", 1, col)) is not None
    ]
    if not active_history and not is_bank_model:
        add_issue("historical_periods", "Historical", None,
                  error="no complete historical period is available")
    for col in active_history:
        identity("historical_gross_profit", "Historical", col,
                 cell("Historical", 5, col),
                 (number(cell("Historical", 3, col)) or 0.0)
                 - (number(cell("Historical", 4, col)) or 0.0))
        identity("historical_ebit_tieout", "Historical", col,
                 cell("Historical", 44, col), cell("Historical", 8, col))
        identity("historical_ebitda", "Historical", col,
                 cell("Historical", 19, col),
                 (number(cell("Historical", 8, col)) or 0.0)
                 + (number(cell("Historical", 18, col)) or 0.0))
        identity("historical_fcf", "Historical", col,
                 cell("Historical", 26, col),
                 (number(cell("Historical", 23, col)) or 0.0)
                 + (number(cell("Historical", 24, col)) or 0.0))
        identity("historical_fcf_source_tieout", "Historical", col,
                 cell("Historical", 25, col), cell("Historical", 26, col))
        identity("historical_net_debt", "Historical", col,
                 cell("Historical", 37, col),
                 (number(cell("Historical", 35, col)) or 0.0)
                 - (number(cell("Historical", 30, col)) or 0.0)
                 - (number(cell("Historical", 31, col)) or 0.0))

    if is_bank_model:
        bank = "Bank Valuation"
        bvps = number(cell(bank, 5, 2))
        roe = number(cell(bank, 6, 2))
        cost = number(cell(bank, 7, 2))
        growth = number(cell(bank, 8, 2))
        raw_pb = number(cell(bank, 10, 2))
        bounded_pb = number(cell(bank, 11, 2))
        peer_pb = number(cell(bank, 14, 2))
        for name, value, positive in (
            ("bank_book_value_per_share", bvps, True),
            ("bank_roe", roe, False),
            ("bank_cost_of_equity", cost, True),
            ("bank_long_run_growth", growth, False),
        ):
            if value is None or (positive and value <= 0):
                add_issue(name, bank, 2, error="required bank input is invalid",
                          actual=value)
        if cost is not None and growth is not None and cost <= growth:
            add_issue("bank_cost_of_equity_above_growth", bank, 2,
                      actual=cost, expected=f"> {growth}")
        if None not in (roe, growth, cost) and cost != growth:
            identity("bank_raw_justified_pb", bank, 2, raw_pb,
                     (roe - growth) / (cost - growth))
        if raw_pb is not None:
            identity("bank_bounded_justified_pb", bank, 2, bounded_pb,
                     min(3.0, max(0.4, raw_pb)))
        if bvps is not None and bounded_pb is not None:
            identity("bank_intrinsic_value", bank, 2, cell(bank, 12, 2),
                     bvps * bounded_pb)
        if bvps is not None and peer_pb is not None:
            identity("bank_peer_value", bank, 2, cell(bank, 15, 2),
                     bvps * peer_pb)
        intrinsic = number(cell(bank, 12, 2))
        peer_value = number(cell(bank, 15, 2))
        forward_value = number(cell(bank, 17, 2))
        forward_pb = number(cell(bank, 27, 5))
        if forward_value is not None and forward_pb is not None and bvps is not None:
            identity("bank_forward_consensus_value", bank, 2, forward_value,
                     bvps * forward_pb)
        supported = [value for value in (intrinsic, forward_value, peer_value)
                     if value is not None and value > 0]
        if supported:
            identity("bank_audit_midpoint", bank, 2, cell(bank, 18, 2),
                     sum(supported) / len(supported))
            identity("bank_range_low", bank, 2, cell(bank, 19, 2), min(supported))
            identity("bank_range_high", bank, 2, cell(bank, 20, 2), max(supported))
        summary = "Summary"
        identity("bank_summary_cost_of_equity", summary, 2,
                 cell(summary, 4, 2), cost)
        identity("bank_summary_growth", summary, 2,
                 cell(summary, 5, 2), growth)
        identity("bank_summary_roe", summary, 2,
                 cell(summary, 6, 2), roe)
        identity("bank_summary_justified_pb", summary, 2,
                 cell(summary, 7, 2), bounded_pb)
        identity("bank_summary_intrinsic", summary, 2,
                 cell(summary, 18, 2), intrinsic)
        if forward_value is not None and forward_value > 0:
            identity("bank_summary_forward_consensus", summary, 2,
                     cell(summary, 19, 2), forward_value)
        elif cell(summary, 19, 2) not in (None, "", 0, 0.0):
            add_issue(
                "bank_summary_forward_consensus_absent", summary, 2,
                error=(
                    "summary publishes a forward-consensus value without an "
                    "eligible forward-ROE scenario"
                ),
                actual=cell(summary, 19, 2),
            )
        # A missing peer method is a supported one-leg bank valuation.  The
        # workbook's cross-sheet reference evaluates the blank peer cell as
        # zero, while the semantic source value remains ``None``.  Only tie
        # the summary peer line when an eligible peer value actually exists;
        # otherwise require the rendered placeholder to stay blank/zero.
        if peer_value is not None and peer_value > 0:
            identity("bank_summary_peer", summary, 2,
                     cell(summary, 22, 2), peer_value)
        elif cell(summary, 22, 2) not in (None, "", 0, 0.0):
            add_issue(
                "bank_summary_peer_absent", summary, 2,
                error="summary publishes a peer value without an eligible peer method",
                actual=cell(summary, 22, 2),
            )
        if supported:
            identity("bank_summary_midpoint", summary, 2,
                     cell(summary, 26, 2), sum(supported) / len(supported))
        return {
            "status": "ready" if not issues else "error",
            "issue_count": len(issues),
            "issues": issues[:100],
            "issues_truncated": len(issues) > 100,
        }

    # Explicit forecast identities and PP&E continuity.
    normalized_tax = number(cell("Model_Inputs", 11, 2))
    if normalized_tax is None or not (0.0 < normalized_tax <= 0.5):
        add_issue(
            "normalized_tax_rate", "Model_Inputs", 2,
            error="normalized cash-tax rate must be finite and in (0%, 50%]",
            actual=cell("Model_Inputs", 11, 2),
        )
    else:
        identity("tax_assumption_cross_tab", "Assumptions", 2,
                 cell("Assumptions", 20, 2), normalized_tax)
        identity("tax_dcf_cross_tab", "Valuation (DCF)", 2,
                 cell("Valuation (DCF)", 8, 2), normalized_tax)
        identity("tax_exit_cross_tab", "Valuation (Exit Multiple)", 2,
                 cell("Valuation (Exit Multiple)", 4, 2), normalized_tax)
    for col in range(2, 7):
        revenue = number(cell("Projections", 3, col))
        if revenue is None or revenue <= 0:
            add_issue("projection_revenue", "Projections", col,
                      error="projected revenue must be finite and positive",
                      actual=cell("Projections", 3, col))
            continue
        identity("projection_gross_profit", "Projections", col,
                 cell("Projections", 5, col),
                 revenue - (number(cell("Projections", 4, col)) or 0.0))
        identity("projection_ebit", "Projections", col,
                 cell("Projections", 9, col),
                 (number(cell("Projections", 5, col)) or 0.0)
                 - (number(cell("Projections", 7, col)) or 0.0)
                 - (number(cell("Projections", 8, col)) or 0.0))
        identity("projection_cash_tax", "Projections", col,
                 cell("Projections", 10, col),
                 max(0.0, number(cell("Projections", 9, col)) or 0.0)
                 * (normalized_tax or 0.0))
        identity("projection_nopat", "Projections", col,
                 cell("Projections", 11, col),
                 (number(cell("Projections", 9, col)) or 0.0)
                 - (number(cell("Projections", 10, col)) or 0.0))
        identity("projection_nwc", "Projections", col,
                 cell("Projections", 17, col),
                 (number(cell("Projections", 14, col)) or 0.0)
                 + (number(cell("Projections", 15, col)) or 0.0)
                 - (number(cell("Projections", 16, col)) or 0.0))
        identity("projection_fcf", "Projections", col,
                 cell("Projections", 19, col),
                 (number(cell("Projections", 11, col)) or 0.0)
                 + (number(cell("Projections", 12, col)) or 0.0)
                 + (number(cell("Projections", 13, col)) or 0.0)
                 - (number(cell("Projections", 18, col)) or 0.0))
        beginning_expected = (
            abs(number(cell("Historical", 38, 6)) or 0.0) if col == 2
            else cell("Projections", 46, col - 1)
        )
        identity("ppe_beginning_balance", "Projections", col,
                 cell("Projections", 43, col), beginning_expected)
        identity("ppe_capex_sign", "Projections", col,
                 cell("Projections", 44, col),
                 -(number(cell("Projections", 13, col)) or 0.0))
        identity("ppe_depreciation_sign", "Projections", col,
                 cell("Projections", 45, col),
                 -(number(cell("Projections", 12, col)) or 0.0))
        identity("ppe_ending_balance", "Projections", col,
                 cell("Projections", 46, col),
                 (number(cell("Projections", 43, col)) or 0.0)
                 + (number(cell("Projections", 44, col)) or 0.0)
                 + (number(cell("Projections", 45, col)) or 0.0))

    # Perpetuity DCF identities.
    dcf = "Valuation (DCF)"
    identity("wacc", dcf, 2, cell(dcf, 12, 2),
             (number(cell(dcf, 6, 2)) or 0.0) * (number(cell(dcf, 10, 2)) or 0.0)
             + (number(cell(dcf, 9, 2)) or 0.0) * (number(cell(dcf, 11, 2)) or 0.0))
    for col in range(2, 12):
        identity("dcf_pv_fcf", dcf, col, cell(dcf, 18, col),
                 (number(cell(dcf, 16, col)) or 0.0)
                 * (number(cell(dcf, 17, col)) or 0.0))
    identity("dcf_explicit_pv_sum", dcf, 2, cell(dcf, 19, 2),
             sum(number(cell(dcf, 18, col)) or 0.0 for col in range(2, 12)))
    identity("dcf_enterprise_value", dcf, 2, cell(dcf, 27, 2),
             (number(cell(dcf, 19, 2)) or 0.0) + (number(cell(dcf, 26, 2)) or 0.0))
    identity("dcf_equity_bridge", dcf, 2, cell(dcf, 33, 2),
             (number(cell(dcf, 27, 2)) or 0.0)
             + (number(cell(dcf, 30, 2)) or 0.0)
             - (number(cell(dcf, 31, 2)) or 0.0)
             + (number(cell(dcf, 32, 2)) or 0.0))
    shares = number(cell(dcf, 36, 2))
    if shares is None or shares <= 0:
        add_issue("shares_outstanding", dcf, 2,
                  error="diluted shares must be finite and positive",
                  actual=cell(dcf, 36, 2))
    else:
        identity("dcf_value_per_share", dcf, 2, cell(dcf, 37, 2),
                 (number(cell(dcf, 33, 2)) or 0.0) / shares)

    # Exit-multiple method must use the identical explicit FCF stream/discounts.
    exit_tab = "Valuation (Exit Multiple)"
    for col in range(2, 12):
        identity("exit_fcf_cross_method", exit_tab, col,
                 cell(exit_tab, 7, col), cell(dcf, 16, col))
        identity("exit_discount_cross_method", exit_tab, col,
                 cell(exit_tab, 8, col), cell(dcf, 17, col))
        identity("exit_pv_fcf", exit_tab, col, cell(exit_tab, 9, col),
                 (number(cell(exit_tab, 7, col)) or 0.0)
                 * (number(cell(exit_tab, 8, col)) or 0.0))
    identity("exit_explicit_pv_sum", exit_tab, 2, cell(exit_tab, 10, 2),
             sum(number(cell(exit_tab, 9, col)) or 0.0 for col in range(2, 12)))
    identity("exit_terminal_value", exit_tab, 2, cell(exit_tab, 14, 2),
             (number(cell(exit_tab, 12, 2)) or 0.0)
             * (number(cell(exit_tab, 13, 2)) or 0.0))
    identity("exit_enterprise_value", exit_tab, 2, cell(exit_tab, 17, 2),
             (number(cell(exit_tab, 10, 2)) or 0.0)
             + (number(cell(exit_tab, 15, 2)) or 0.0))
    identity("exit_equity_bridge", exit_tab, 2, cell(exit_tab, 22, 2),
             (number(cell(exit_tab, 17, 2)) or 0.0)
             + (number(cell(exit_tab, 19, 2)) or 0.0)
             - (number(cell(exit_tab, 20, 2)) or 0.0)
             + (number(cell(exit_tab, 21, 2)) or 0.0))
    exit_multiple = number(cell(exit_tab, 3, 2))
    exit_shares = number(cell(exit_tab, 24, 2))
    if exit_multiple is not None and exit_multiple > 0 and exit_shares and exit_shares > 0:
        identity("exit_value_per_share", exit_tab, 2, cell(exit_tab, 25, 2),
                 (number(cell(exit_tab, 22, 2)) or 0.0) / exit_shares)

    # Summary is a second, user-visible copy of the key bridges and outputs.
    summary = "Summary"
    identity("summary_perpetual_enterprise_value", summary, 2,
             cell(summary, 17, 2),
             (number(cell(summary, 13, 2)) or 0.0)
             - (number(cell(summary, 14, 2)) or 0.0)
             + (number(cell(summary, 15, 2)) or 0.0)
             - (number(cell(summary, 16, 2)) or 0.0))
    identity("summary_perpetual_value_per_share", summary, 2,
             cell(summary, 18, 2), cell(dcf, 37, 2))
    identity("summary_exit_enterprise_value", summary, 2,
             cell(summary, 20, 2), cell(exit_tab, 17, 2))
    identity("summary_exit_equity_value", summary, 2,
             cell(summary, 21, 2), cell(exit_tab, 22, 2))
    identity("summary_exit_value_per_share", summary, 2,
             cell(summary, 22, 2), cell(exit_tab, 25, 2))
    price = number(cell(summary, 9, 2))
    headline = number(cell(summary, 26, 2))
    if price and price > 0 and headline is not None:
        identity("summary_upside", summary, 2, cell(summary, 27, 2),
                 headline / price - 1.0)
    identity("summary_market_enterprise_value", summary, 2,
             cell(summary, 29, 2),
             (number(cell(summary, 10, 2)) or 0.0)
             - (number(cell(summary, 14, 2)) or 0.0)
             + (number(cell(summary, 15, 2)) or 0.0)
             - (number(cell(summary, 16, 2)) or 0.0))
    for row in range(41, 47):
        if cell(summary, row, 2) is not True:
            add_issue("summary_qa_flag", summary, 2, row=row,
                      actual=cell(summary, row, 2), expected=True)

    return {
        "status": "ready" if not issues else "error",
        "issue_count": len(issues),
        "issues": issues[:100],
        "issues_truncated": len(issues) > 100,
    }


def _safe_arithmetic_eval(expression: str) -> Any:
    """Evaluate the small arithmetic subset emitted by workbook builders.

    Raw provider values can be referenced by formulas.  Python ``eval`` made a
    malicious or merely malformed string cell executable after reference
    substitution.  An explicit AST interpreter both closes that boundary and
    makes unsupported syntax fail formula integrity instead of running it.
    """
    tree = ast.parse(expression, mode="eval")
    nodes = list(ast.walk(tree))
    if len(nodes) > 500:
        raise ValueError("Arithmetic expression is too complex")

    binary = {
        ast.Add: lambda left, right: left + right,
        ast.Sub: lambda left, right: left - right,
        ast.Mult: lambda left, right: left * right,
        ast.Div: lambda left, right: left / right,
        ast.Pow: lambda left, right: left ** right,
    }
    unary = {
        ast.UAdd: lambda value: +value,
        ast.USub: lambda value: -value,
    }
    comparisons = {
        ast.Eq: lambda left, right: left == right,
        ast.NotEq: lambda left, right: left != right,
        ast.Lt: lambda left, right: left < right,
        ast.LtE: lambda left, right: left <= right,
        ast.Gt: lambda left, right: left > right,
        ast.GtE: lambda left, right: left >= right,
    }

    def visit(node):
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool):
                return node.value
            if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
                return node.value
            raise TypeError("Only numeric and boolean constants are allowed")
        if isinstance(node, ast.BinOp) and type(node.op) in binary:
            left, right = visit(node.left), visit(node.right)
            if isinstance(node.op, ast.Pow) and (
                isinstance(right, bool) or not isinstance(right, (int, float))
                or abs(float(right)) > 100
            ):
                raise ValueError("Exponent is outside the supported range")
            return binary[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and type(node.op) in unary:
            return unary[type(node.op)](visit(node.operand))
        if (
            isinstance(node, ast.Compare)
            and len(node.ops) == 1
            and len(node.comparators) == 1
            and type(node.ops[0]) in comparisons
        ):
            return comparisons[type(node.ops[0])](
                visit(node.left), visit(node.comparators[0])
            )
        raise ValueError(f"Unsupported arithmetic syntax: {type(node).__name__}")

    return visit(tree)


class FormulaEvaluator:
    """
    Evaluates all Excel formulas in a financial model workbook.
    
    This class:
    1. Processes tabs in dependency order
    2. Evaluates formulas using previously computed values
    3. Handles cell references, ranges, and Excel functions
    4. Stores all computed values in JSON format
    """
    
    # Tab processing order (must match dependency chain)
    TAB_ORDER = [
        "Raw",
        "Keys_Map",
        "Assumptions",
        "Model_Inputs",
        "Historical",
        "Projections",
        "Valuation (DCF)",
        "Valuation (Exit Multiple)",
        "Sensitivity",
        "Bank Valuation",
        "Summary",
    ]
    
    def __init__(self, workbook: Workbook):
        """
        Initialize the Formula Evaluator.
        
        Args:
            workbook: The openpyxl Workbook to evaluate
        """
        self.workbook = workbook
        
        # Storage for computed values
        # Structure: {tab_name: {(row, col): value}}
        self.computed_values: Dict[str, Dict[Tuple[int, int], Any]] = {}
        
        # Cache for formula evaluation to avoid re-computing
        self.eval_cache: Dict[str, Any] = {}
        
        # Logger - will be set by pipeline if available
        self.logger = None

    def set_logger(self, logger):
        """Set the logger instance."""
        self.logger = logger
    
    def _log(self, level: str, message: str):
        """Log message using logger if available, otherwise print."""
        if self.logger is not None and hasattr(self.logger, level):
            getattr(self.logger, level)(message)
    
    def evaluate_all_tabs(self) -> Dict[str, Dict[str, Any]]:
        """
        Evaluate all tabs in dependency order.
        
        Returns:
            Dictionary with structure:
            {
                "tab_name": {
                    "cells": {
                        "(row, col)": value,
                        ...
                    },
                    "metadata": {
                        "total_cells": int,
                        "formula_cells": int,
                        "value_cells": int
                    }
                }
            }
        """
        self._log("info", "="*70)
        self._log("info", "Starting Formula Evaluation")
        self._log("info", "="*70)

        results = {}
        
        for tab_name in self.TAB_ORDER:
            if tab_name not in self.workbook.sheetnames:
                self._log("warning", f"Skipping {tab_name} (not found in workbook)")
                continue

            self._log("info", f"[{self.TAB_ORDER.index(tab_name) + 1}/{len(self.TAB_ORDER)}] Evaluating {tab_name}...")

            tab_results = self._evaluate_tab(tab_name)
            results[tab_name] = tab_results
            
            # Store computed values for next tabs to reference
            self.computed_values[tab_name] = tab_results["cells"]

            self._log("info", f"      ✅ {tab_results['metadata']['total_cells']} cells evaluated")
            self._log("info", f"         • Formulas: {tab_results['metadata']['formula_cells']}")
            self._log("info", f"         • Values: {tab_results['metadata']['value_cells']}")

        self._log("info", "="*70)
        self._log("info", "✅ Formula Evaluation Complete!")
        self._log("info", "="*70)

        return results
    
    def _evaluate_tab(self, tab_name: str) -> Dict[str, Any]:
        """
        Evaluate all cells in a single tab.
        
        Args:
            tab_name: Name of the tab to evaluate
            
        Returns:
            Dictionary with cells and metadata
        """
        ws = self.workbook[tab_name]
        
        cells = {}
        formula_count = 0
        value_count = 0
        
        # Initialize computed_values for this tab if not exists
        if tab_name not in self.computed_values:
            self.computed_values[tab_name] = {}
        
        # Iterate through all cells with data
        for row in ws.iter_rows():
            for cell in row:
                if cell.value is None:
                    continue
                
                row_idx = cell.row
                col_idx = cell.column
                key = f"({row_idx}, {col_idx})"
                
                # Check if it's a formula
                if isinstance(cell.value, str) and cell.value.startswith('='):
                    # Evaluate the formula
                    try:
                        evaluated_value = self._evaluate_formula(
                            cell.value[1:],  # Remove '=' prefix
                            tab_name,
                            row_idx,
                            col_idx
                        )
                        cells[key] = evaluated_value
                        # Store immediately in computed_values so subsequent formulas can reference it
                        self.computed_values[tab_name][key] = evaluated_value
                        formula_count += 1
                    except Exception as e:
                        # If formula evaluation fails, store error info
                        error_value = {
                            "error": str(e),
                            "formula": cell.value
                        }
                        cells[key] = error_value
                        self.computed_values[tab_name][key] = error_value
                        formula_count += 1
                else:
                    # It's a direct value
                    serialized_value = self._serialize_value(cell.value)
                    cells[key] = serialized_value
                    # Store immediately in computed_values so formulas can reference it
                    self.computed_values[tab_name][key] = serialized_value
                    value_count += 1
        
        return {
            "cells": cells,
            "metadata": {
                "total_cells": len(cells),
                "formula_cells": formula_count,
                "value_cells": value_count,
                "tab_name": tab_name
            }
        }
    
    def _evaluate_formula(
        self,
        formula: str,
        current_tab: str,
        current_row: int,
        current_col: int
    ) -> Any:
        """
        Recursively evaluate an Excel formula.
        
        Args:
            formula: The formula string (without '=' prefix)
            current_tab: The tab containing this formula
            current_row: Row of the cell with this formula
            current_col: Column of the cell with this formula
            
        Returns:
            The evaluated result
        """
        # Create cache key
        cache_key = f"{current_tab}!{get_column_letter(current_col)}{current_row}:{formula}"
        if cache_key in self.eval_cache:
            return self.eval_cache[cache_key]
        
        try:
            result = self._eval_expression(formula, current_tab, current_row, current_col)
            self.eval_cache[cache_key] = result
            return result
        except Exception as e:
            # Return error information
            return {
                "error": f"Evaluation error: {str(e)}",
                "formula": formula
            }
    
    def _eval_expression(
        self,
        expr: str,
        current_tab: str,
        current_row: int,
        current_col: int
    ) -> Any:
        """
        Evaluate a formula expression.
        
        Handles:
        - Cell references (A1, 'Tab'!B2, $A$1)
        - Arithmetic operations (+, -, *, /, ^)
        - Excel functions (SUM, IF, IFERROR, SUMIFS, etc.)
        - Ranges (A1:A10)
        """
        expr = expr.strip()
        
        # Handle comparison operators (must come before function check)
        # But only if the operator is at the top level, not inside parentheses
        has_top_level_comparison = False
        paren_depth = 0
        in_quotes = False
        
        for i, char in enumerate(expr):
            if char == '"':
                in_quotes = not in_quotes
            elif not in_quotes:
                if char == '(':
                    paren_depth += 1
                elif char == ')':
                    paren_depth -= 1
                elif paren_depth == 0:
                    # Check for comparison operators at this position
                    for op in ['<>', '>=', '<=', '>', '<', '=']:
                        if expr[i:i+len(op)] == op:
                            has_top_level_comparison = True
                            break
            if has_top_level_comparison:
                break
        
        if has_top_level_comparison:
            return self._evaluate_comparison(expr, current_tab, current_row, current_col)
        
        # Handle Excel functions
        if self._is_function_call(expr):
            return self._evaluate_function(expr, current_tab, current_row, current_col)
        
        # Handle cell references
        if self._is_cell_reference(expr):
            return self._get_cell_value(expr, current_tab)
        
        # Handle arithmetic expressions
        if any(op in expr for op in ['+', '-', '*', '/', '^', '(', ')', '&']):
            return self._evaluate_arithmetic(expr, current_tab, current_row, current_col)
        
        # Handle numeric literals
        try:
            # Try to parse as number
            if '.' in expr or 'E' in expr.upper():
                return float(expr)
            return int(expr)
        except ValueError:
            pass
        
        # Handle string literals
        if expr.startswith('"') and expr.endswith('"'):
            return expr[1:-1]
        
        # Handle boolean literals
        if expr.upper() == 'TRUE':
            return True
        if expr.upper() == 'FALSE':
            return False
        
        # A formula which is neither a literal, reference, arithmetic
        # expression nor a supported function is not a valid string result.
        # Returning the source text here silently turned misspelled functions
        # and unsupported syntax into apparently successful cells.
        raise ValueError(f"Unsupported formula expression: {expr}")
    
    def _is_function_call(self, expr: str) -> bool:
        """
        Check if expression is a PURE function call (not a composite expression).
        
        Examples:
        - SUM(A1:A10) -> True
        - IF(A1>0,1,0) -> True
        - MAX(0,B9)*Assumptions!$B$20 -> False (contains arithmetic after function)
        - A1+SUM(B1:B10) -> False (contains arithmetic before function)
        """
        if '(' not in expr:
            return False
        
        func_name = expr.split('(')[0].strip()
        if not func_name.replace('_', '').isalpha():
            return False
        
        # Check if there are any operators outside the function call
        # Find the matching closing parenthesis for the function
        paren_count = 0
        start_idx = expr.find('(')
        for i in range(start_idx, len(expr)):
            if expr[i] == '(':
                paren_count += 1
            elif expr[i] == ')':
                paren_count -= 1
                if paren_count == 0:
                    # Check if there's anything after the closing parenthesis
                    remaining = expr[i+1:].strip()
                    if remaining and remaining not in ['', ')']:
                        # There's content after the function call
                        return False
                    break
        
        return True
    
    def _is_cell_reference(self, expr: str) -> bool:
        """Check if expression is a cell reference"""
        # Remove $ signs first
        cleaned_expr = expr.replace('$', '').strip()
        
        # Pattern: [Tab!]A1 or [Tab!]A1:B5 (single cell or range)
        # Handle both with and without quotes around tab name
        # Tab name can be: 'Tab Name'! or TabName! or no tab
        # Changed [^!]+! to [A-Za-z0-9_ ]+! to only match valid tab name characters
        pattern = r"^(?:'[^']+'!|[A-Za-z0-9_ ]+!)?[A-Z]+\d+(?::[A-Z]+\d+)?$"
        return bool(re.match(pattern, cleaned_expr))
    
    def _get_cell_value(self, cell_ref: str, current_tab: str) -> Any:
        """
        Get the value of a cell reference.
        
        Args:
            cell_ref: Cell reference (e.g., "A1", "'Tab'!B2", "$A$1")
            current_tab: The current tab (used for relative references)
            
        Returns:
            The cell's computed value
        """
        # Remove $ signs (absolute references)
        cell_ref = cell_ref.replace('$', '')
        
        # Parse tab and cell
        if '!' in cell_ref:
            # Cross-tab reference
            parts = cell_ref.split('!')
            tab_name = parts[0].strip("'")
            cell_addr = parts[1]
        else:
            # Same-tab reference
            tab_name = current_tab
            cell_addr = cell_ref
        
        # Parse cell address
        match = re.match(r'([A-Z]+)(\d+)', cell_addr)
        if not match:
            raise ValueError(f"Invalid cell reference: {cell_ref}")
        
        col_letter = match.group(1)
        row_num = int(match.group(2))
        col_num = column_index_from_string(col_letter)
        
        # Look up in computed values
        if tab_name in self.computed_values:
            key = f"({row_num}, {col_num})"
            if key in self.computed_values[tab_name]:
                return self.computed_values[tab_name][key]
        
        # If not found in computed values, try to get from workbook
        if tab_name in self.workbook.sheetnames:
            ws = self.workbook[tab_name]
            cell = ws.cell(row=row_num, column=col_num)
            
            if cell.value is None:
                return 0  # Empty cell = 0 in Excel
            
            if isinstance(cell.value, str) and cell.value.startswith('='):
                # It's a formula - evaluate it recursively
                return self._evaluate_formula(
                    cell.value[1:],
                    tab_name,
                    row_num,
                    col_num
                )
            
            return cell.value
        
        raise ValueError(f"Formula references unknown worksheet: {tab_name}")
    
    def _evaluate_arithmetic(
        self,
        expr: str,
        current_tab: str,
        current_row: int,
        current_col: int
    ) -> float:
        """
        Evaluate arithmetic expressions with cell references.
        
        Strategy:
        1. Replace all function calls with their results
        2. Replace all cell references with their values
        3. Handle string concatenation (&)
        4. Evaluate the resulting arithmetic expression
        """
        # Check if there's a & operator at the top level (not inside parentheses)
        # This handles string concatenation
        has_top_level_concat = False
        paren_depth = 0
        in_quotes = False
        for char in expr:
            if char == '"':
                in_quotes = not in_quotes
            elif not in_quotes:
                if char == '(':
                    paren_depth += 1
                elif char == ')':
                    paren_depth -= 1
                elif char == '&' and paren_depth == 0:
                    has_top_level_concat = True
                    break
        
        if has_top_level_concat:
            return self._evaluate_concatenation(expr, current_tab, current_row, current_col)
        
        # First, find and evaluate any function calls
        # Pattern to match function calls: FUNCTION_NAME(...)
        func_pattern = r'([A-Z_]+)\('
        matches = list(re.finditer(func_pattern, expr))
        
        # Process function calls from right to left to avoid index issues
        for match in reversed(matches):
            func_name = match.group(1)
            start_pos = match.start()
            
            # Find the matching closing parenthesis
            paren_count = 1
            pos = match.end()
            while pos < len(expr) and paren_count > 0:
                if expr[pos] == '(':
                    paren_count += 1
                elif expr[pos] == ')':
                    paren_count -= 1
                pos += 1
            
            if paren_count == 0:
                # Found complete function call
                func_call = expr[start_pos:pos]
                try:
                    # Evaluate the function
                    result = self._evaluate_function(func_call, current_tab, current_row, current_col)
                    # Replace function call with its result in the expression
                    expr = expr[:start_pos] + f'({result})' + expr[pos:]
                except Exception as error:
                    raise ValueError(
                        f"Could not evaluate nested function {func_call}: {error}"
                    ) from error
        
        # Find all cell references in the expression
        # Pattern must handle: Tab!A1, 'Tab'!A1, $A$1, Tab!$A$1, 'Tab Name'!A1
        # Use a more specific pattern that captures the entire reference including tab name
        pattern = r"(?:'[^']+'!|[A-Za-z_][A-Za-z0-9_]*!)?\$?[A-Z]+\$?\d+"
        
        def replace_cell_ref(match):
            cell_ref = match.group(0)
            try:
                value = self._get_cell_value(cell_ref, current_tab)
                # Handle errors and non-numeric values
                if isinstance(value, dict) and 'error' in value:
                    raise ValueError(
                        f"Referenced formula failed at {cell_ref}: {value.get('error')}"
                    )
                if value is None or value == '':
                    return '0'
                # Convert boolean to int
                if isinstance(value, bool):
                    return '1' if value else '0'
                # Wrap in parentheses to maintain operator precedence
                return f'({value})'
            except Exception as error:
                raise ValueError(
                    f"Could not resolve cell reference {cell_ref}: {error}"
                ) from error
        
        # Replace all cell references with their values
        evaluated_expr = re.sub(pattern, replace_cell_ref, expr)
        
        # Replace Excel's ^ with Python's **
        evaluated_expr = evaluated_expr.replace('^', '**')
        
        try:
            result = _safe_arithmetic_eval(evaluated_expr)
            return float(result) if isinstance(result, (int, float)) else result
        except ZeroDivisionError as error:
            # Excel produces #DIV/0!, not zero.  Raising lets an enclosing
            # IFERROR select its explicit fallback and makes an unguarded
            # valuation failure visible to the formula-integrity gate.
            raise ZeroDivisionError(
                f"Division by zero in formula: {expr}"
            ) from error
        except Exception as e:
            raise ValueError(f"Cannot evaluate arithmetic: {expr} -> {evaluated_expr}: {e}")
    
    def _evaluate_concatenation(
        self,
        expr: str,
        current_tab: str,
        current_row: int,
        current_col: int
    ) -> str:
        """
        Evaluate string concatenation expressions (Excel's & operator).
        
        Example: C$1&"*" where C$1 is 2024 -> "2024*"
        """
        # Split by & but preserve quoted strings
        parts = []
        current_part = []
        in_quotes = False
        
        for char in expr:
            if char == '"':
                in_quotes = not in_quotes
                current_part.append(char)
            elif char == '&' and not in_quotes:
                parts.append(''.join(current_part).strip())
                current_part = []
            else:
                current_part.append(char)
        
        if current_part:
            parts.append(''.join(current_part).strip())
        
        # Evaluate each part
        result_parts = []
        for part in parts:
            # Remove quotes if it's a string literal
            if part.startswith('"') and part.endswith('"'):
                result_parts.append(part[1:-1])
            else:
                # It's a cell reference or expression
                value = self._eval_expression(part, current_tab, current_row, current_col)
                # Format numbers without unnecessary decimal points
                # Excel's & operator converts 2024.0 to "2024", not "2024.0"
                if isinstance(value, float) and value == int(value):
                    result_parts.append(str(int(value)))
                else:
                    result_parts.append(str(value))
        
        return ''.join(result_parts)
    
    def _evaluate_function(
        self,
        func_expr: str,
        current_tab: str,
        current_row: int,
        current_col: int
    ) -> Any:
        """
        Evaluate Excel functions.
        
        Supported functions:
        - SUM, AVERAGE, MIN, MAX, COUNT
        - IF, IFERROR, IFNA
        - SUMIFS, COUNTIFS, AVERAGEIFS
        - INDEX, MATCH
        - AND, OR, NOT
        - ROUND, ABS, SQRT
        - LEFT, RIGHT, MID, LEN
        - VALUE, TEXT
        - COLUMNS, ROWS
        """
        # Parse function name and arguments
        match = re.match(r'([A-Z_]+)\((.*)\)$', func_expr.strip(), re.IGNORECASE)
        if not match:
            raise ValueError(f"Invalid function: {func_expr}")
        
        func_name = match.group(1).upper()
        args_str = match.group(2)
        
        # Parse arguments (respecting nested parentheses and commas)
        args = self._parse_function_args(args_str)
        
        # Dispatch to appropriate handler
        if func_name == 'SUM':
            return self._func_sum(args, current_tab, current_row, current_col)
        elif func_name == 'AVERAGE' or func_name == 'AVG':
            return self._func_average(args, current_tab, current_row, current_col)
        elif func_name == 'MIN':
            return self._func_min(args, current_tab, current_row, current_col)
        elif func_name == 'MAX':
            return self._func_max(args, current_tab, current_row, current_col)
        elif func_name == 'COUNT':
            return self._func_count(args, current_tab, current_row, current_col)
        elif func_name == 'IF':
            return self._func_if(args, current_tab, current_row, current_col)
        elif func_name == 'IFERROR':
            return self._func_iferror(args, current_tab, current_row, current_col)
        elif func_name == 'SUMIFS':
            return self._func_sumifs(args, current_tab, current_row, current_col)
        elif func_name == 'INDEX':
            return self._func_index(args, current_tab, current_row, current_col)
        elif func_name == 'MATCH':
            return self._func_match(args, current_tab, current_row, current_col)
        elif func_name == 'AND':
            return self._func_and(args, current_tab, current_row, current_col)
        elif func_name == 'OR':
            return self._func_or(args, current_tab, current_row, current_col)
        elif func_name == 'NOT':
            return self._func_not(args, current_tab, current_row, current_col)
        elif func_name == 'ABS':
            return self._func_abs(args, current_tab, current_row, current_col)
        elif func_name == 'MAX':
            return self._func_max(args, current_tab, current_row, current_col)
        elif func_name == 'MIN':
            return self._func_min(args, current_tab, current_row, current_col)
        elif func_name == 'ROUND':
            return self._func_round(args, current_tab, current_row, current_col)
        elif func_name == 'LEFT':
            return self._func_left(args, current_tab, current_row, current_col)
        elif func_name == 'VALUE':
            return self._func_value(args, current_tab, current_row, current_col)
        elif func_name == 'COLUMNS':
            return self._func_columns(args, current_tab, current_row, current_col)
        elif func_name == 'ROWS':
            return self._func_rows(args, current_tab, current_row, current_col)
        else:
            raise NotImplementedError(f"Unsupported Excel function: {func_name}")
    
    def _parse_function_args(self, args_str: str) -> List[str]:
        """
        Parse function arguments, respecting nested parentheses and quoted strings.
        
        Example:
            "A1, SUM(B1:B5), 'Text, with comma'" 
            -> ["A1", "SUM(B1:B5)", "'Text, with comma'"]
        """
        args = []
        current_arg = []
        paren_depth = 0
        in_quotes = False
        quote_char = None
        
        for char in args_str:
            if char in ('"', "'") and (not in_quotes or char == quote_char):
                in_quotes = not in_quotes
                quote_char = char if in_quotes else None
                current_arg.append(char)
            elif char == '(' and not in_quotes:
                paren_depth += 1
                current_arg.append(char)
            elif char == ')' and not in_quotes:
                paren_depth -= 1
                current_arg.append(char)
            elif char == ',' and paren_depth == 0 and not in_quotes:
                # End of argument
                args.append(''.join(current_arg).strip())
                current_arg = []
            else:
                current_arg.append(char)
        
        # Add last argument
        if current_arg:
            args.append(''.join(current_arg).strip())
        
        return args
    
    def _parse_range(self, range_ref: str, current_tab: str) -> List[Tuple[str, int, int]]:
        """
        Parse a range reference into list of (tab, row, col) tuples.
        
        Example: "A1:A5" -> [(tab, 1, 1), (tab, 2, 1), ..., (tab, 5, 1)]
        Example: "D:D" -> all cells in column D
        """
        # Remove $ signs and normalize both Excel spellings of a cross-sheet
        # range. Some saved workbooks repeat the sheet on the second endpoint:
        # ``'Tab'!B1:'Tab'!F1`` rather than ``'Tab'!B1:F1``.
        range_ref = range_ref.replace('$', '').strip()

        def endpoint(value: str) -> Tuple[Optional[str], str]:
            value = value.strip()
            if '!' not in value:
                return None, value
            sheet, cell = value.rsplit('!', 1)
            return sheet.strip().strip("'"), cell.strip()

        if ':' in range_ref:
            left_raw, right_raw = range_ref.split(':', 1)
            left_tab, left_cell = endpoint(left_raw)
            right_tab, right_cell = endpoint(right_raw)
            if left_tab and right_tab and left_tab != right_tab:
                raise ValueError(f"A range cannot span two worksheets: {range_ref}")
            tab_name = left_tab or right_tab or current_tab
            range_part = f"{left_cell}:{right_cell}"
        else:
            tab_name, range_part = endpoint(range_ref)
            tab_name = tab_name or current_tab

        if tab_name not in self.workbook.sheetnames:
            raise ValueError(f"Range references unknown worksheet: {tab_name}")
        
        # Parse range
        if ':' in range_part:
            start_cell, end_cell = range_part.split(':')
            
            # Check for full column reference (e.g., "D:D")
            if re.match(r'^[A-Z]+$', start_cell) and re.match(r'^[A-Z]+$', end_cell):
                # Full column reference - get all non-empty cells in these columns
                start_col = column_index_from_string(start_cell)
                end_col = column_index_from_string(end_cell)
                
                cells = []
                if tab_name in self.computed_values:
                    # Scan all cells in this tab for matching columns
                    for cell_key, cell_value in self.computed_values[tab_name].items():
                        if cell_key.startswith('(') and cell_key.endswith(')'):
                            # Parse cell key like "(3, 4)"
                            try:
                                parts = cell_key[1:-1].split(',')
                                row = int(parts[0].strip())
                                col = int(parts[1].strip())
                                if start_col <= col <= end_col:
                                    cells.append((tab_name, row, col))
                            except (TypeError, ValueError, IndexError):
                                continue
                return cells
            
            # Check for full row reference (e.g., "1:5")
            elif re.match(r'^\d+$', start_cell) and re.match(r'^\d+$', end_cell):
                # Full row reference
                start_row = int(start_cell)
                end_row = int(end_cell)
                
                cells = []
                if tab_name in self.computed_values:
                    for cell_key, cell_value in self.computed_values[tab_name].items():
                        if cell_key.startswith('(') and cell_key.endswith(')'):
                            try:
                                parts = cell_key[1:-1].split(',')
                                row = int(parts[0].strip())
                                col = int(parts[1].strip())
                                if start_row <= row <= end_row:
                                    cells.append((tab_name, row, col))
                            except (TypeError, ValueError, IndexError):
                                continue
                return cells
            
            # Regular cell range (e.g., "A1:B5")
            match_start = re.match(r'([A-Z]+)(\d+)', start_cell)
            if not match_start:
                raise ValueError(f"Invalid range start: {range_ref}")
            start_col = column_index_from_string(match_start.group(1))
            start_row = int(match_start.group(2))
            
            match_end = re.match(r'([A-Z]+)(\d+)', end_cell)
            if not match_end:
                raise ValueError(f"Invalid range end: {range_ref}")
            end_col = column_index_from_string(match_end.group(1))
            end_row = int(match_end.group(2))
            
            # Generate all cells in range
            cells = []
            for row in range(start_row, end_row + 1):
                for col in range(start_col, end_col + 1):
                    cells.append((tab_name, row, col))
            
            return cells
        else:
            # Single cell
            match = re.match(r'([A-Z]+)(\d+)', range_part)
            if not match:
                raise ValueError(f"Invalid cell or range reference: {range_ref}")
            col = column_index_from_string(match.group(1))
            row = int(match.group(2))
            return [(tab_name, row, col)]
    
    def _get_range_values(self, range_ref: str, current_tab: str) -> List[Any]:
        """Get all values from a range"""
        cells = self._parse_range(range_ref, current_tab)
        values = []
        
        for tab, row, col in cells:
            key = f"({row}, {col})"
            if tab in self.computed_values and key in self.computed_values[tab]:
                val = self.computed_values[tab][key]
                if isinstance(val, dict) and 'error' in val:
                    raise ValueError(
                        f"Range {range_ref} contains a failed formula at {tab}!{key}: "
                        f"{val.get('error')}"
                    )
                values.append(val)
        
        return values
    
    # =============================================================================
    # Excel Function Implementations
    # =============================================================================
    
    def _func_sum(self, args: List[str], tab: str, row: int, col: int) -> float:
        """SUM function"""
        total = 0
        for arg in args:
            if ':' in arg and not self._is_function_call(arg):
                # Range
                values = self._get_range_values(arg, tab)
                total += sum(float(v) for v in values if isinstance(v, (int, float)))
            else:
                # Single value
                val = self._eval_expression(arg, tab, row, col)
                if isinstance(val, (int, float)):
                    total += val
        return total
    
    def _func_average(self, args: List[str], tab: str, row: int, col: int) -> float:
        """AVERAGE function"""
        values = []
        for arg in args:
            if ':' in arg and not self._is_function_call(arg):
                # A bare range like Raw!$D:$D. A function CALL that merely
                # contains a range — SUMIFS(Raw!$D:$D, ...) — has a paren, and
                # must be evaluated, not read as a range. Treating it as one
                # returned nothing, so MIN(0.5, SUMIFS(...)) evaluated to 0.5
                # and the workbook's tax rate to 0 on every forecast year.
                values.extend(self._get_range_values(arg, tab))
            else:
                val = self._eval_expression(arg, tab, row, col)
                values.append(val)
        
        numeric_values = [v for v in values if isinstance(v, (int, float))]
        return sum(numeric_values) / len(numeric_values) if numeric_values else 0
    
    def _func_count(self, args: List[str], tab: str, row: int, col: int) -> int:
        """COUNT function"""
        count = 0
        for arg in args:
            if ':' in arg and not self._is_function_call(arg):
                values = self._get_range_values(arg, tab)
                count += sum(1 for v in values if isinstance(v, (int, float)))
            else:
                val = self._eval_expression(arg, tab, row, col)
                if isinstance(val, (int, float)):
                    count += 1
        return count
    
    def _func_if(self, args: List[str], tab: str, row: int, col: int) -> Any:
        """IF function"""
        if len(args) < 2:
            raise ValueError("IF requires at least two arguments")
        
        # Evaluate condition
        condition = self._eval_expression(args[0], tab, row, col)
        
        # Handle comparison operators
        if isinstance(condition, str):
            condition = self._evaluate_comparison(condition, tab, row, col)
        
        # Return appropriate branch
        if condition:
            return self._eval_expression(args[1], tab, row, col) if len(args) > 1 else True
        else:
            return self._eval_expression(args[2], tab, row, col) if len(args) > 2 else False
    
    def _evaluate_comparison(self, expr: str, tab: str, row: int, col: int) -> bool:
        """Evaluate comparison expressions like 'A1 > 5' or 'IFERROR(A1,"")<>""'"""
        # First, check if this is a complex expression with functions
        # We need to evaluate sub-expressions first
        
        # Check for comparison operators
        for op in ['<>', '>=', '<=', '>', '<', '=']:
            if op in expr:
                # Find the operator position (avoid matching inside function calls)
                # Split carefully to handle nested functions
                parts = self._split_by_operator(expr, op)
                
                if len(parts) == 2:
                    left = self._eval_expression(parts[0].strip(), tab, row, col)
                    right = self._eval_expression(parts[1].strip(), tab, row, col)
                    
                    # Perform comparison
                    if op == '>=':
                        return left >= right
                    elif op == '<=':
                        return left <= right
                    elif op == '<>':
                        return left != right
                    elif op == '>':
                        return left > right
                    elif op == '<':
                        return left < right
                    elif op == '=':
                        return left == right
        
        # If no comparison operator, treat as boolean
        return bool(expr)
    
    def _split_by_operator(self, expr: str, operator: str) -> List[str]:
        """
        Split expression by operator, respecting parentheses and quoted strings.
        
        Example: 'IFERROR(A1,"")<>""' with '<>' -> ['IFERROR(A1,"")', '""']
        """
        parts = []
        current_part = []
        paren_depth = 0
        in_quotes = False
        i = 0
        
        while i < len(expr):
            char = expr[i]
            
            if char == '"':
                in_quotes = not in_quotes
                current_part.append(char)
                i += 1
            elif char == '(' and not in_quotes:
                paren_depth += 1
                current_part.append(char)
                i += 1
            elif char == ')' and not in_quotes:
                paren_depth -= 1
                current_part.append(char)
                i += 1
            elif paren_depth == 0 and not in_quotes:
                # Check if we're at the operator
                if expr[i:i+len(operator)] == operator:
                    # Found the operator at top level
                    parts.append(''.join(current_part))
                    current_part = []
                    i += len(operator)
                    
                    # Add remaining as second part
                    parts.append(expr[i:])
                    return parts
                else:
                    current_part.append(char)
                    i += 1
            else:
                current_part.append(char)
                i += 1
        
        # If we didn't find the operator at top level, return the whole expression
        return [''.join(current_part)]
    
    def _func_iferror(self, args: List[str], tab: str, row: int, col: int) -> Any:
        """IFERROR function"""
        if len(args) < 1:
            raise ValueError("IFERROR requires at least one argument")
        
        try:
            result = self._eval_expression(args[0], tab, row, col)
            # Check if result is an error
            if isinstance(result, dict) and 'error' in result:
                return self._eval_expression(args[1], tab, row, col) if len(args) > 1 else ""
            return result
        except Exception:
            return self._eval_expression(args[1], tab, row, col) if len(args) > 1 else ""
    
    def _func_sumifs(self, args: List[str], tab: str, row: int, col: int) -> float:
        """
        SUMIFS function
        
        Syntax: SUMIFS(sum_range, criteria_range1, criteria1, ...)
        """
        if len(args) < 3:
            raise ValueError("SUMIFS requires a sum range and at least one criteria pair")
        
        # Get sum range
        sum_range = self._get_range_values(args[0], tab)
        sum_cells = self._parse_range(args[0], tab)
        
        # Process criteria pairs
        matching_indices = set(range(len(sum_range)))
        
        for i in range(1, len(args), 2):
            if i + 1 >= len(args):
                break
            
            criteria_range = self._parse_range(args[i], tab)
            
            # Evaluate the criteria (may contain expressions like C$1&"*")
            criteria_arg = args[i + 1]
            if criteria_arg.startswith('"') and criteria_arg.endswith('"'):
                # Already a string literal
                criteria_str = criteria_arg.strip('"')
            else:
                # May be an expression - evaluate it
                criteria_val = self._eval_expression(criteria_arg, tab, row, col)
                criteria_str = str(criteria_val)
            
            # Support wildcards (e.g., "2024*")
            if '*' in criteria_str:
                pattern = criteria_str.replace('*', '.*')
                for idx, (ctab, crow, ccol) in enumerate(criteria_range):
                    if idx not in matching_indices:
                        continue
                    
                    key = f"({crow}, {ccol})"
                    if ctab in self.computed_values and key in self.computed_values[ctab]:
                        val = str(self.computed_values[ctab][key])
                        if not re.match(pattern, val):
                            matching_indices.discard(idx)
            else:
                # Exact match
                for idx, (ctab, crow, ccol) in enumerate(criteria_range):
                    if idx not in matching_indices:
                        continue
                    
                    key = f"({crow}, {ccol})"
                    if ctab in self.computed_values and key in self.computed_values[ctab]:
                        val = str(self.computed_values[ctab][key])
                        if val != criteria_str:
                            matching_indices.discard(idx)
        
        # Sum matching values
        total = 0
        for idx in matching_indices:
            if idx < len(sum_range) and isinstance(sum_range[idx], (int, float)):
                total += sum_range[idx]
        
        return total
    
    def _func_index(self, args: List[str], tab: str, row: int, col: int) -> Any:
        """INDEX function"""
        if len(args) < 2:
            raise ValueError("INDEX requires a range and row index")

        range_values = self._get_range_values(args[0], tab)
        row_idx_val = self._eval_expression(args[1], tab, row, col)
        if isinstance(row_idx_val, bool) or not isinstance(row_idx_val, (int, float)):
            raise TypeError("INDEX row index must be numeric")
        row_idx = int(row_idx_val) - 1
        if not 0 <= row_idx < len(range_values):
            raise IndexError(
                f"INDEX row {row_idx + 1} is outside a {len(range_values)}-value range"
            )
        return range_values[row_idx]
    
    def _func_match(self, args: List[str], tab: str, row: int, col: int) -> int:
        """MATCH function"""
        if len(args) < 2:
            raise ValueError("MATCH requires a lookup value and lookup range")

        lookup_val = self._eval_expression(args[0], tab, row, col)
        range_values = self._get_range_values(args[1], tab)
        match_type = 0
        if len(args) > 2:
            match_type = int(self._eval_expression(args[2], tab, row, col))
        if match_type != 0:
            raise NotImplementedError(
                f"MATCH type {match_type} is not supported; use exact match type 0"
            )
        try:
            return range_values.index(lookup_val) + 1
        except ValueError:
            lookup_str = str(lookup_val)
            for i, value in enumerate(range_values):
                if str(value) == lookup_str:
                    return i + 1
        raise LookupError(f"MATCH could not find {lookup_val!r}")
    
    def _func_and(self, args: List[str], tab: str, row: int, col: int) -> bool:
        """AND function"""
        for arg in args:
            val = self._eval_expression(arg, tab, row, col)
            if not val:
                return False
        return True
    
    def _func_or(self, args: List[str], tab: str, row: int, col: int) -> bool:
        """OR function"""
        for arg in args:
            val = self._eval_expression(arg, tab, row, col)
            if val:
                return True
        return False
    
    def _func_not(self, args: List[str], tab: str, row: int, col: int) -> bool:
        """NOT function"""
        if len(args) < 1:
            return True
        val = self._eval_expression(args[0], tab, row, col)
        return not val
    
    def _func_abs(self, args: List[str], tab: str, row: int, col: int) -> float:
        """ABS function"""
        if len(args) < 1:
            raise ValueError("ABS requires one argument")
        val = self._eval_expression(args[0], tab, row, col)
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            raise TypeError("ABS argument must be numeric")
        return abs(val)
    
    def _func_max(self, args: List[str], tab: str, row: int, col: int) -> float:
        """MAX function"""
        if len(args) < 1:
            return 0
        
        values = []
        for arg in args:
            if ':' in arg and not self._is_function_call(arg):
                # A bare range like Raw!$D:$D. A function CALL that merely
                # contains a range — SUMIFS(Raw!$D:$D, ...) — has a paren and
                # must be evaluated, not read as a range. Read as one it
                # contributed nothing, so MIN(0.5, SUMIFS(...)) returned 0.5 and
                # the workbook's tax rate evaluated to 0 on every forecast year.
                range_vals = self._get_range_values(arg, tab)
                values.extend([v for v in range_vals if isinstance(v, (int, float))])
            else:
                # Single value
                val = self._eval_expression(arg, tab, row, col)
                if isinstance(val, (int, float)):
                    values.append(val)
        
        return max(values) if values else 0
    
    def _func_min(self, args: List[str], tab: str, row: int, col: int) -> float:
        """MIN function"""
        if len(args) < 1:
            return 0
        
        values = []
        for arg in args:
            if ':' in arg and not self._is_function_call(arg):
                # A bare range like Raw!$D:$D. A function CALL that merely
                # contains a range — SUMIFS(Raw!$D:$D, ...) — has a paren and
                # must be evaluated, not read as a range. Read as one it
                # contributed nothing, so MIN(0.5, SUMIFS(...)) returned 0.5 and
                # the workbook's tax rate evaluated to 0 on every forecast year.
                range_vals = self._get_range_values(arg, tab)
                values.extend([v for v in range_vals if isinstance(v, (int, float))])
            else:
                # Single value
                val = self._eval_expression(arg, tab, row, col)
                if isinstance(val, (int, float)):
                    values.append(val)
        
        return min(values) if values else 0
    
    def _func_round(self, args: List[str], tab: str, row: int, col: int) -> float:
        """ROUND function"""
        if len(args) < 1:
            raise ValueError("ROUND requires one argument")
        val = self._eval_expression(args[0], tab, row, col)
        decimals = int(self._eval_expression(args[1], tab, row, col)) if len(args) > 1 else 0
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            raise TypeError("ROUND value must be numeric")
        return round(val, decimals)
    
    def _func_left(self, args: List[str], tab: str, row: int, col: int) -> str:
        """LEFT function"""
        if len(args) < 1:
            raise ValueError("LEFT requires one argument")
        text = str(self._eval_expression(args[0], tab, row, col))
        num_chars = int(self._eval_expression(args[1], tab, row, col)) if len(args) > 1 else 1
        return text[:num_chars]
    
    def _func_value(self, args: List[str], tab: str, row: int, col: int) -> float:
        """VALUE function"""
        if len(args) < 1:
            raise ValueError("VALUE requires one argument")
        text = str(self._eval_expression(args[0], tab, row, col))
        text = text.replace(',', '').replace('$', '').strip()
        return float(text)
    
    def _func_columns(self, args: List[str], tab: str, row: int, col: int) -> int:
        """COLUMNS function"""
        if len(args) < 1:
            return 0
        
        # Parse range
        cells = self._parse_range(args[0], tab)
        
        # Count unique columns
        unique_cols = set(col for _, _, col in cells)
        return len(unique_cols)
    
    def _func_rows(self, args: List[str], tab: str, row: int, col: int) -> int:
        """ROWS function"""
        if len(args) < 1:
            return 0
        
        # Parse range
        cells = self._parse_range(args[0], tab)
        
        # Count unique rows
        unique_rows = set(row for _, row, _ in cells)
        return len(unique_rows)
    
    def _serialize_value(self, value: Any) -> Any:
        """Convert value to JSON-serializable format"""
        if isinstance(value, (int, float, str, bool, type(None))):
            return value
        elif isinstance(value, (list, tuple)):
            return [self._serialize_value(v) for v in value]
        elif isinstance(value, dict):
            return {k: self._serialize_value(v) for k, v in value.items()}
        else:
            return str(value)
    
    def save_to_json(self, results: Dict[str, Any], output_path: Union[str, Path]) -> None:
        """
        Save evaluation results to JSON file.
        
        Args:
            results: The results from evaluate_all_tabs()
            output_path: Path to save the JSON file
        """
        output_path = Path(output_path)
        
        # Ensure parent directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Convert all values to JSON-serializable format
        serializable_results = {}
        for tab_name, tab_data in results.items():
            if isinstance(tab_data, dict) and isinstance(tab_data.get("cells"), dict):
                serializable_results[tab_name] = {
                    "cells": {
                        k: self._serialize_value(v)
                        for k, v in tab_data["cells"].items()
                    },
                    "metadata": tab_data["metadata"],
                }
            else:
                # Names beginning with '_' are bounded application metadata,
                # not workbook tabs. Existing tab readers ignore them.
                serializable_results[tab_name] = self._serialize_value(tab_data)
        
        # Write to file
        with open(output_path, 'w') as f:
            json.dump(serializable_results, f, indent=2)
        
        file_size = output_path.stat().st_size
        print(f"\n✅ Evaluation results saved to: {output_path}")
        print(f"   • File size: {file_size:,} bytes ({file_size/1024:.1f} KB)")
        print(f"   • Tabs evaluated: {len(serializable_results)}")
        
        total_cells = sum(
            tab["metadata"]["total_cells"]
            for tab in serializable_results.values()
            if isinstance(tab, dict) and isinstance(tab.get("metadata"), dict)
        )
        print(f"   • Total cells: {total_cells}")
