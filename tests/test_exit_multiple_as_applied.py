"""
Report and workbook show the exit multiple the valuation applied.

The exit leg starts from today's EV/EBITDA and holds it to what a sustainable
growth rate justifies (tab_valuation_exit_multiple_dcf row 13). The report
printed today's reference beside a value computed at the applied multiple
(Apple "29.7x" against 17.5x, Micron 10.4x against 5.0x), and the workbook's
sensitivity grid was centred on the reference, so its base cell disagreed
with the anchor beside it.

Run:  python -m pytest tests/test_exit_multiple_as_applied.py -q
"""

import os
import pathlib
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "src"))

from src.report_agent import exit_multiple_text, extract_valuation  # noqa: E402

_FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "mu_memory_boom_2026_10_09.json"


def _build():
    from src.agents.fm.financial_model_builder import FinancialModelBuilder

    class Quiet:
        def __getattr__(self, _name):
            return lambda *args, **kwargs: None

    builder = FinancialModelBuilder("MU", Quiet())
    builder.load_json_file(_FIXTURE)
    builder.build_model()
    return builder.formula_evaluator.evaluate_all_tabs()


@pytest.fixture(scope="module")
def micron():
    return _build()


def test_the_grid_is_centred_on_the_applied_multiple(micron):
    exit_tab = micron["Valuation (Exit Multiple)"]["cells"]
    grid = micron["Sensitivity"]["cells"]
    applied, reference = exit_tab["(13, 2)"], exit_tab["(3, 2)"]
    assert applied < reference                       # the ceiling held it
    assert grid["(8, 2)"] == pytest.approx(applied)
    assert grid["(22, 5)"] == pytest.approx(applied)
    # The base cell (base WACC, base multiple) is the exit leg's own value.
    assert grid["(25, 5)"] == pytest.approx(grid["(22, 2)"], rel=1e-6)
    assert grid["(22, 2)"] == pytest.approx(exit_tab["(25, 2)"])


def test_the_report_prints_the_applied_multiple_and_says_where_it_came_from(micron):
    valuation = extract_valuation(micron)
    exit_tab = micron["Valuation (Exit Multiple)"]["cells"]
    assert valuation["dcf_exit"]["exit_multiple"] == pytest.approx(exit_tab["(13, 2)"])
    assert valuation["dcf_exit"]["exit_multiple_reference"] == pytest.approx(exit_tab["(3, 2)"])
    assert exit_multiple_text(valuation["dcf_exit"]) == (
        f"{exit_tab['(13, 2)']:.1f}x (today's {exit_tab['(3, 2)']:.1f}x, held to what "
        "a sustainable growth rate justifies)")


def test_an_unheld_multiple_prints_alone_and_a_missing_one_is_na():
    assert exit_multiple_text({"exit_multiple": 11.9, "exit_multiple_reference": 11.9}) == "11.9x"
    assert exit_multiple_text({"exit_multiple": 0, "exit_multiple_reference": 0}) == "N/A"
    assert exit_multiple_text({"exit_multiple": None}) == "N/A"


def test_a_ceiling_within_rounding_prints_one_number():
    assert exit_multiple_text({"exit_multiple": 10.36, "exit_multiple_reference": 10.41}) == "10.4x"


def test_the_exit_tab_names_the_reference_and_the_applied_multiple(micron):
    exit_tab = micron["Valuation (Exit Multiple)"]["cells"]
    assert exit_tab["(3, 1)"] == "Current EV/EBITDA (reference)"
    assert exit_tab["(13, 1)"] == "Exit Multiple applied (EV/EBITDA)"
