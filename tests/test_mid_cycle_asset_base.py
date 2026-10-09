"""
A memory maker's D&A and capex follow its asset base, not the price cycle.

The engine scales both with projected revenue. For a memory maker in a boom
that revenue is price: Micron's trailing capex (28% of revenue that had
tripled) became $86B and $84B a year in the Street's covered years, more than
three times what it was spending, building plant no mid-cycle year earns on,
while D&A on the trend years stayed at the boom's 10% of revenue. Now both are
measured against trend revenue and grow with it, capex converging to the
engine's usual 1.1x D&A by FY5; and the exit multiple is held to what the
model's own terminal cash conversion justifies, because today's EV/EBITDA
prices the same cycle.

Run:  python -m pytest tests/test_mid_cycle_asset_base.py -q
"""

import os
import sys

import openpyxl
import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "src"))
sys.path.insert(0, os.path.join(_ROOT, "tests"))

from src.agents.fm import memory_cycle  # noqa: E402
from src.agents.fm.tabs.tab_projections import ProjectionsTabBuilder  # noqa: E402
from src.agents.fm.tabs.tab_valuation_exit_multiple_dcf import (  # noqa: E402
    ValuationExitMultipleDCFBuilder,
)
from src.reinvestment_sensitivity import build_reinvestment_sensitivity  # noqa: E402
from test_memory_mid_cycle import _grounded, _sandisk  # noqa: E402


def _revenue(grounded):
    revenue = [grounded["modeling_basis"]["revenue"]]
    for rate in grounded["revenue_growth_rates"]:
        revenue.append(revenue[-1] * (1 + rate))
    return revenue


def _sandisk_with_spend(da=0.0074 * 20.248e9, capex=-0.009 * 20.248e9):
    payload = _sandisk()
    payload["ttm_bridge"]["normalized"].update(
        {"depreciation_and_amortization": da, "capital_expenditure": capex})
    return payload


def test_da_and_capex_follow_trend_revenue_not_the_price(monkeypatch):
    monkeypatch.setenv("RISK_FREE_USD", "0.04")
    payload = _sandisk_with_spend()
    grounded, notes = _grounded(payload)
    basis = grounded["modeling_basis"]
    inputs = memory_cycle.mid_cycle_inputs(payload)
    period = grounded["mid_cycle"]["base_period_end"]
    revenue = _revenue(grounded)

    # The trailing twelve months' dollars, measured against the trend revenue
    # at the end of those twelve months instead of the boom revenue they were
    # reported on.
    trend_then = memory_cycle.trend_revenue(inputs, 0, "2026-06-30")
    da_share = 0.0074 * 20.248e9 / trend_then
    capex_share = -0.009 * 20.248e9 / trend_then
    asset = grounded["mid_cycle"]["asset_base"]
    assert asset["da_share_of_trend_revenue"] == pytest.approx(da_share)
    assert asset["capex_share_of_trend_revenue"] == pytest.approx(capex_share)
    assert asset["trailing_period_end"] == "2026-06-30"
    assert asset["da_share_held_at_maximum"] is False

    for i, progress in enumerate((0, 0, 1 / 3, 2 / 3, 1)):
        trend = memory_cycle.trend_revenue(inputs, i + 1, period)
        da = basis["da_to_revenue_by_year"][i] * revenue[i + 1]
        capex = basis["capex_to_revenue_by_year"][i] * revenue[i + 1]
        assert da == pytest.approx(da_share * trend)
        # Today's intensity through the covered years, then the engine's
        # glide to 1.1x D&A by FY5, on trend dollars.
        assert capex == pytest.approx(
            trend * (capex_share * (1 - progress) - 1.1 * da_share * progress))
        # EBITDA is EBIT plus the D&A actually projected that year.
        assert grounded["ebitda_margins"][i] == pytest.approx(
            grounded["operating_margins"][i] + basis["da_to_revenue_by_year"][i])
    assert capex == pytest.approx(-1.1 * da)
    assert any("D&A and capex on the asset base" in note
               and "twelve months to 2026-06-30" in note for note in notes)


def test_the_dollars_are_the_trailing_twelve_months_even_on_an_annual_base(monkeypatch):
    """Too few analysts for the rolling clock: the projections start from the
    last fiscal year, but the D&A and capex are still the trailing twelve
    months' dollars, not their ratio applied to annual revenue."""
    monkeypatch.setenv("RISK_FREE_USD", "0.04")
    payload = _sandisk_with_spend()
    payload["ttm_bridge"]["latest_period"] = "2026-09-30"
    for horizon in ("0y", "+1y"):
        payload["analyst_data"]["revenue_estimates"][horizon]["numberOfAnalysts"] = 3
        payload["analyst_data"]["earnings_estimates"][horizon]["numberOfAnalysts"] = 3
    grounded, _ = _grounded(payload)
    assert (grounded.get("modeling_basis") or {}).get("revenue") is None
    inputs = memory_cycle.mid_cycle_inputs(payload)
    asset = grounded["mid_cycle"]["asset_base"]
    trend_then = memory_cycle.trend_revenue(inputs, 0, "2026-09-30")
    assert asset["da_share_of_trend_revenue"] == pytest.approx(0.0074 * 20.248e9 / trend_then)
    period = grounded["mid_cycle"]["base_period_end"]
    assert asset["da"][0] == pytest.approx(
        0.0074 * 20.248e9 / trend_then * memory_cycle.trend_revenue(inputs, 1, period))


def test_without_a_current_trailing_twelve_months_the_engine_path_is_kept(monkeypatch):
    monkeypatch.setenv("RISK_FREE_USD", "0.04")
    payload = _sandisk()                          # no D&A or capex dollars
    grounded, notes = _grounded(payload)
    assert "da_to_revenue_by_year" not in (grounded.get("modeling_basis") or {})
    assert grounded["mid_cycle"]["asset_base"] is None
    assert any("no current trailing twelve months" in note for note in notes)


@pytest.mark.parametrize("da,capex", [(None, -1e8), (1e8, None), (-1e8, -1e8), (1e8, 5e7),
                                      (float("nan"), -1e8), (True, -1e8)])
def test_implausible_trailing_spend_leaves_the_engine_path(da, capex):
    inputs = memory_cycle.mid_cycle_inputs(_sandisk_with_spend(da, capex))
    assert memory_cycle.asset_base_path(inputs, inputs["base_period_end"], [20e9] * 5) is None


def test_capex_beyond_any_asset_base_is_a_data_problem():
    inputs = memory_cycle.mid_cycle_inputs(_sandisk())
    trend_then = memory_cycle.trend_revenue(inputs, 0, "2026-06-30")
    inputs = memory_cycle.mid_cycle_inputs(_sandisk_with_spend(1e8, -1.6 * trend_then))
    assert memory_cycle.asset_base_path(inputs, inputs["base_period_end"], [20e9] * 5) is None


def test_d_and_a_is_held_at_the_highest_share_observed_through_the_cycle():
    inputs = memory_cycle.mid_cycle_inputs(_sandisk())
    trend_then = memory_cycle.trend_revenue(inputs, 0, "2026-06-30")
    inputs = memory_cycle.mid_cycle_inputs(_sandisk_with_spend(0.45 * trend_then, -0.5 * trend_then))
    path = memory_cycle.asset_base_path(inputs, inputs["base_period_end"], [30e9] * 5)
    assert path["da_share_held_at_maximum"] is True
    assert path["da_share_of_trend_revenue"] == memory_cycle.MAX_DA_SHARE_OF_TREND
    assert path["trailing_da_share_of_trend_revenue"] == pytest.approx(0.45)
    base = inputs["base_period_end"]
    trend = [memory_cycle.trend_revenue(inputs, i + 1, base) for i in range(5)]
    # The Street's covered years add back the trailing D&A their EBIT was
    # earned on; the ceiling starts with the first mid-cycle year.
    assert path["da"][:2] == pytest.approx([0.45 * t for t in trend[:2]])
    assert path["da"][2:] == pytest.approx([0.30 * t for t in trend[2:]])
    assert path["capex"][4] == pytest.approx(-1.1 * 0.30 * trend[4])


def test_a_path_the_workbook_would_refuse_is_never_recorded():
    """A deep double dip: projected revenue far under trend makes D&A more
    than all of that year's revenue, which the workbook refuses; the rewrite
    must then keep the engine path rather than claim one it did not build."""
    inputs = memory_cycle.mid_cycle_inputs(_sandisk())
    trend_then = memory_cycle.trend_revenue(inputs, 0, "2026-06-30")
    inputs = memory_cycle.mid_cycle_inputs(_sandisk_with_spend(0.25 * trend_then, -0.3 * trend_then))
    assert memory_cycle.asset_base_path(
        inputs, inputs["base_period_end"], [0.2 * trend_then] * 5) is None


def _projections(basis):
    workbook = openpyxl.Workbook()
    ws = ProjectionsTabBuilder(modeling_basis=basis).create_tab(workbook)
    return [ws.cell(row=12, column=c).value for c in range(2, 7)], \
        [ws.cell(row=13, column=c).value for c in range(2, 7)]


def test_the_workbook_uses_one_ratio_per_year_when_both_are_given():
    by_year = {
        "da_to_revenue": 0.10, "capex_to_revenue": -0.28,
        "da_to_revenue_by_year": [0.04, 0.035, 0.1, 0.28, 0.28],
        "capex_to_revenue_by_year": [-0.12, -0.08, -0.19, -0.42, -0.31],
    }
    da, capex = _projections(by_year)
    assert da[0] == "=B3*0.040000000000" and da[3] == "=E3*0.280000000000"
    assert capex[0] == "=B3*-0.120000000000" and capex[4] == "=F3*-0.310000000000"

    # Both or neither: one list alone, a short list or an implausible value
    # keeps the engine's single-ratio path for both rows.
    for broken in ({"capex_to_revenue_by_year": None},
                   {"da_to_revenue_by_year": [0.04] * 4},
                   {"capex_to_revenue_by_year": [-0.12, 0.3, -0.19, -0.42, -0.31]}):
        da, capex = _projections({**by_year, **broken})
        assert da[0] == "=B3*0.100000000000"
        assert capex[0].startswith("=B3*(-0.280000000000*1.00")


def test_a_mid_cycle_exit_multiple_is_held_to_its_ceiling_from_a_steady_conversion():
    def multiple_formula(always_cap):
        workbook = openpyxl.Workbook()
        ws = ValuationExitMultipleDCFBuilder(
            exit_multiple=10.4, growth_cap=0.04, always_cap=always_cap,
        ).create_tab(workbook)
        return ws.cell(row=13, column=2).value

    gated = multiple_formula(False)
    assert "$K$7/$B$12>=0.30" in gated
    # Held from the conversion terminal_value.py calls steady (15%), not the
    # generic 30%: a memory maker's D&A is half its EBITDA.
    held = multiple_formula(True)
    assert "$K$7/$B$12>=0.30" not in held and "$K$7/$B$12>=0.15" in held
    assert "MIN($B$3,($K$7/$B$12)" in held


def test_the_run_rate_capex_case_does_not_apply_to_an_asset_base_path():
    result = build_reinvestment_sensitivity(
        {}, {}, modeling_basis={"capex_to_revenue": -0.28, "da_to_revenue": 0.1,
                                "capex_to_revenue_by_year": [-0.12] * 5})
    assert result["status"] == "unavailable"
    assert "asset base" in result["reason"]


# ── Micron's own workbook, built offline from its 9 October 2026 data ───────

def _build_micron():
    import pathlib
    from src.agents.fm.financial_model_builder import FinancialModelBuilder
    from src.agents.fm.formula_evaluator import model_integrity

    class Quiet:
        def __getattr__(self, _name):
            return lambda *args, **kwargs: None

    builder = FinancialModelBuilder("MU", Quiet())
    builder.load_json_file(pathlib.Path(__file__).parent / "fixtures"
                           / "mu_memory_boom_2026_10_09.json")
    builder.build_model()
    results = builder.formula_evaluator.evaluate_all_tabs()
    return builder, results, model_integrity(results)


def test_micron_builds_plant_for_its_trend_not_its_boom():
    builder, results, integrity = _build_micron()
    assert integrity["status"] == "ready", integrity.get("issues")
    basis = builder.llm_assumptions["modeling_basis"]
    projections = results["Projections"]["cells"]
    ttm_capex = -basis["capex_to_revenue"] * basis["revenue"]
    capex = [-projections[f"(13, {col})"] for col in range(2, 7)]
    # About what Micron spent over the last twelve months, never three times it.
    assert ttm_capex < capex[0] < 1.3 * ttm_capex
    assert capex[1] < 1.3 * ttm_capex
    # The boom path took net PP&E from $47B to $167B (3.5x) on capex scaled
    # with price; on the asset base it ends near $101B, the trailing build-out
    # gliding to maturity.
    assert projections["(46, 6)"] < 2.5 * projections["(43, 2)"]
    # D&A on the trend's asset base: about a quarter of FY5 revenue, not the
    # boom's 10%.
    assert projections["(12, 6)"] / projections["(3, 6)"] > 0.2
    assert projections["(13, 6)"] == pytest.approx(-1.1 * projections["(12, 6)"])


def test_micron_exit_leg_is_held_to_its_own_economics():
    _builder, results, _integrity = _build_micron()
    exit_tab = results["Valuation (Exit Multiple)"]["cells"]
    multiple, reference = exit_tab["(13, 2)"], exit_tab["(3, 2)"]
    # Its terminal conversion is under the 30% gate, legitimately; held to the
    # ceiling anyway, not today's multiple on boom EBITDA.
    assert multiple < reference
    perpetual = results["Valuation (DCF)"]["cells"]["(37, 2)"]
    exit_value = exit_tab["(25, 2)"] if isinstance(exit_tab.get("(25, 2)"), (int, float)) else None
    if exit_value is not None:
        assert abs(exit_value / perpetual - 1) < 0.05


def test_a_refused_asset_base_says_why(monkeypatch):
    monkeypatch.setenv("RISK_FREE_USD", "0.04")
    inputs = memory_cycle.mid_cycle_inputs(_sandisk())
    trend_then = memory_cycle.trend_revenue(inputs, 0, "2026-06-30")
    grounded, notes = _grounded(_sandisk_with_spend(1e8, -2.0 * trend_then))
    assert grounded["mid_cycle"]["asset_base"] is None
    assert any("do not form a plausible asset base" in note for note in notes)
