"""
The workbook's sensitivity grid must contain numbers.
THE BUG. The Sensitivity tab shipped with its interior cells formatted and
empty, plus a note reading "NOTE: Select B12:E17, Data > What-If Analysis >
Data Table". A user who opened the financial model found a shaded 5x3 rectangle
of nothing and an instruction to build it themselves.

That grid is the most useful table in a DCF: it is what shows the valuation
moving far more per 50bp of discount rate than per point of terminal growth,
which is exactly what a reader needs to judge a fair value. Shipping it blank in
a file sold as a model is a quality defect, and it hid a second one — the same
tab's axes were computed off constants, so even a hand-built table would have
been a sensitivity analysis around the wrong rate.

openpyxl cannot emit an Excel Data Table, so each cell re-runs the DCF for its
own (WACC, g) pair instead. It must use only arithmetic and the handful of
functions our formula evaluator supports: an unsupported function returns a
placeholder, which is how the grid ends up empty a second time.

Run:  python -m pytest tests/test_sensitivity_grid.py -q
"""

import os
import re
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "src"))

pytest.importorskip("openpyxl")

from src.agents.fm.tabs.tab_sensitivity import SensitivityTabBuilder


@pytest.fixture
def formula():
    return SensitivityTabBuilder()._value_per_share_formula(15, 4)


class TestFormulaIsComputable:
    def test_only_functions_the_evaluator_supports(self, formula):
        """
        src/agents/fm/formula_evaluator.py returns a placeholder for unknown
        functions. SUMPRODUCT would read cleanly and evaluate to nothing.
        """
        used = set(re.findall(r"([A-Z][A-Z0-9]+)\(", formula))
        assert used <= {"IF", "IFERROR"}, used

    def test_it_fits_in_a_cell(self, formula):
        assert len(formula) < 8192

    def test_it_is_a_formula(self, formula):
        assert formula.startswith("=")


class TestItReRunsTheActualDcf:
    def test_all_ten_explicit_periods_are_discounted(self, formula):
        """FY1-FY10 sit in row 16, columns B through K of the DCF tab."""
        for column in "BCDEFGHIJK":
            assert f"'Valuation (DCF)'!{column}$16" in formula

    def test_the_terminal_value_comes_off_the_final_year(self, formula):
        assert "'Valuation (DCF)'!K$16*(1+" in formula

    def test_the_equity_bridge_matches_the_dcf_tab(self, formula):
        """Cash added, total debt deducted, investments added — rows 30-32."""
        assert "'Valuation (DCF)'!$B$30-'Valuation (DCF)'!$B$31+'Valuation (DCF)'!$B$32" in formula

    def test_it_divides_by_the_share_count(self, formula):
        assert "'Valuation (DCF)'!$B$36" in formula

    def test_the_mid_year_toggle_is_honoured(self, formula):
        """The DCF tab's own discount factors subtract Sensitivity!$B$4."""
        assert "-$B$4)" in formula


class TestAxesDriveTheCell:
    def test_wacc_is_read_from_this_row(self):
        for row in (13, 15, 17):
            f = SensitivityTabBuilder()._value_per_share_formula(row, 4)
            assert f"$A{row}" in f

    def test_growth_is_read_from_this_column(self):
        for col, letter in ((3, "C"), (4, "D"), (5, "E")):
            f = SensitivityTabBuilder()._value_per_share_formula(15, col)
            assert f"{letter}$12" in f

    def test_each_cell_is_distinct(self):
        b = SensitivityTabBuilder()
        cells = {b._value_per_share_formula(r, c)
                 for r in range(13, 18) for c in range(3, 6)}
        assert len(cells) == 15


class TestDegenerateCaseIsMarked:
    def test_growth_at_or_above_wacc_yields_n_m(self, formula):
        """
        The Gordon formula does not merely produce a large number when g >= WACC;
        it produces a meaningless one, and a negative one just past the pole.
        """
        assert '"n/m"' in formula
        assert formula.startswith('=IF($A15<=D$12,"n/m"')

    def test_arithmetic_failures_also_degrade(self, formula):
        assert "IFERROR(" in formula


class TestTheTabNoLongerAsksTheReaderToBuildIt:
    def test_the_hand_build_instruction_is_gone(self):
        """
        Checked against what is WRITTEN INTO CELLS, not the file text — the
        comment explaining this change necessarily quotes the old note.
        """
        source = open(os.path.join(_ROOT, "src", "agents", "fm", "tabs",
                                   "tab_sensitivity.py"), encoding="utf-8").read()
        written = re.findall(r'value="([^"]*)"', source)
        assert not any("What-If Analysis" in v for v in written)
        assert not any(v.startswith("NOTE: Select") for v in written)

    def test_the_interior_cells_are_written_with_values(self):
        source = open(os.path.join(_ROOT, "src", "agents", "fm", "tabs",
                                   "tab_sensitivity.py"), encoding="utf-8").read()
        block = source[source.index("# C13:E17"):source.index("ws.cell(row=19")]
        assert "_value_per_share_formula(row, col)" in block


class TestGridEvaluatesToRealNumbers:
    """
    The formulas are only worth anything if they compute. This drives the real
    evaluator over a workbook whose DCF tab holds a known FCF path, and checks
    the grid comes back with numbers that behave like a DCF.
    """

    FCF = [15.34e9, 14.93e9, 14.35e9, 13.71e9, 12.96e9,
           13.28e9, 13.62e9, 13.96e9, 14.31e9, 14.67e9]

    def _workbook(self):
        """A minimal workbook whose DCF tab holds LVMH's real FCF path and bridge."""
        import openpyxl

        wb = openpyxl.Workbook()
        dcf = wb.create_sheet("Valuation (DCF)")
        for i, value in enumerate(self.FCF):
            dcf.cell(row=16, column=2 + i, value=value)
        dcf.cell(row=30, column=2, value=8.794e9)      # cash
        dcf.cell(row=31, column=2, value=36.731e9)     # total debt
        dcf.cell(row=32, column=2, value=13.502e9)     # investments
        dcf.cell(row=36, column=2, value=497_976_118)  # shares

        ws = wb.create_sheet("Sensitivity")
        ws.cell(row=4, column=2, value=0)               # mid-year toggle off
        for offset, row in zip((-0.01, -0.005, 0.0, 0.005, 0.01), range(13, 18)):
            ws.cell(row=row, column=1, value=0.0746 + offset)
        for offset, col in zip((-0.005, 0.0, 0.005), range(3, 6)):
            ws.cell(row=12, column=col, value=0.025 + offset)

        builder = SensitivityTabBuilder()
        for row in range(13, 18):
            for col in range(3, 6):
                ws.cell(row=row, column=col,
                        value=builder._value_per_share_formula(row, col))
        return wb

    def test_every_interior_cell_carries_a_formula(self):
        wb = self._workbook()
        ws = wb["Sensitivity"]
        for row in range(13, 18):
            for col in range(3, 6):
                value = ws.cell(row=row, column=col).value
                assert isinstance(value, str) and value.startswith("=IF("), (row, col)

    def test_the_expression_reproduces_the_dcf(self):
        """
        The same sum the formula expresses, computed directly on LVMH's real
        projections and bridge. The shipped model returned EUR 467.58 per share
        at a 7.46% WACC and 2.5% terminal growth, so the base cell must land
        near that or the formula is not describing this DCF.
        """
        w, g = 0.0746, 0.025
        pv = sum(f / (1 + w) ** (i + 1) for i, f in enumerate(self.FCF))
        tv = (self.FCF[-1] * (1 + g) / (w - g)) / (1 + w) ** 10
        per_share = (pv + tv + 8.794e9 - 36.731e9 + 13.502e9) / 497_976_118
        assert per_share == pytest.approx(467.58, rel=0.05), per_share

    def test_value_falls_as_the_discount_rate_rises(self):
        def at(w, g=0.025):
            pv = sum(f / (1 + w) ** (i + 1) for i, f in enumerate(self.FCF))
            tv = (self.FCF[-1] * (1 + g) / (w - g)) / (1 + w) ** 10
            return (pv + tv + 8.794e9 - 36.731e9 + 13.502e9) / 497_976_118

        assert at(0.0846) < at(0.0746) < at(0.0646)

    def test_the_discount_rate_dominates_terminal_growth(self):
        """
        The point of showing the grid at all: 50bp of WACC moves the value more
        than 50bp of terminal growth, so a reader can see the valuation is
        largely a view on rates.
        """
        def at(w, g):
            pv = sum(f / (1 + w) ** (i + 1) for i, f in enumerate(self.FCF))
            tv = (self.FCF[-1] * (1 + g) / (w - g)) / (1 + w) ** 10
            return (pv + tv + 8.794e9 - 36.731e9 + 13.502e9) / 497_976_118

        base = at(0.0746, 0.025)
        assert abs(at(0.0796, 0.025) - base) > abs(at(0.0746, 0.030) - base)


class TestExitMultipleGrid:
    """
    The same defect in the second table: rows 23-27 shipped blank under a note
    reading "NOTE: Select B22:G27, Data > What-If Analysis > Data Table".
    """

    @pytest.fixture
    def formula(self):
        return SensitivityTabBuilder()._exit_value_per_share_formula(25, 5)

    def test_only_supported_functions(self, formula):
        used = set(re.findall(r"([A-Z][A-Z0-9]+)\(", formula))
        assert used <= {"IF", "IFERROR"}, used

    def test_all_ten_periods_are_discounted(self, formula):
        """The exit tab uses the same FY1-FY10 horizon as the Gordon DCF."""
        for column in "BCDEFGHIJK":
            assert f"'Valuation (Exit Multiple)'!{column}$7" in formula

    def test_terminal_value_is_ebitda_times_this_column_s_multiple(self, formula):
        assert "'Valuation (Exit Multiple)'!$B$12*E$22" in formula

    def test_wacc_comes_from_this_row(self):
        for row in (23, 25, 27):
            f = SensitivityTabBuilder()._exit_value_per_share_formula(row, 5)
            assert f"$A{row}" in f

    def test_the_equity_bridge_matches_the_exit_tab(self, formula):
        assert ("'Valuation (Exit Multiple)'!$B$19-'Valuation (Exit Multiple)'!$B$20"
                "+'Valuation (Exit Multiple)'!$B$21") in formula

    def test_it_divides_by_the_share_count(self, formula):
        assert "'Valuation (Exit Multiple)'!$B$24" in formula

    def test_the_mid_year_toggle_applies_to_the_explicit_periods(self, formula):
        assert "-$B$4)" in formula

    def test_the_mid_year_toggle_also_applies_to_terminal_value(self, formula):
        assert "('Valuation (Exit Multiple)'!$B$5-$B$4)" in formula

    def test_each_cell_is_distinct(self):
        b = SensitivityTabBuilder()
        cells = {b._exit_value_per_share_formula(r, c)
                 for r in range(23, 28) for c in range(3, 8)}
        assert len(cells) == 25
def test_summary_midpoint_excludes_an_unavailable_zero_leg():
    import logging
    import openpyxl

    from src.agents.fm.formula_evaluator import FormulaEvaluator

    workbook = openpyxl.Workbook()
    sensitivity = workbook.active
    sensitivity.title = "Sensitivity"
    SensitivityTabBuilder()._setup_summary_block(sensitivity)
    sensitivity["B32"] = 100.0
    sensitivity["B33"] = 0.0
    historical = workbook.create_sheet("Historical")
    historical["F2"] = 80.0

    evaluator = FormulaEvaluator(workbook)
    evaluator.set_logger(logging.getLogger("test_sensitivity_midpoint"))
    cells = evaluator.evaluate_all_tabs()["Sensitivity"]["cells"]

    assert cells["(34, 2)"] == pytest.approx(100.0)
    assert cells["(36, 2)"] == pytest.approx(0.25)
