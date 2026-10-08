"""
A memory maker is valued on mid-cycle economics, not on one point of the cycle.

Sandisk's DCF held the Street's 71.6% operating margin, on revenue that had
nearly tripled in a year, through the terminal value: about 2x the price.
Micron's did the same at 76%. Now the Street's two covered years are kept,
then revenue reverts to the company's trend and the margin to the industry's
through-cycle level (NAND 18%, DRAM 21%, from SEC 10-K histories), and the
value is published with what the price pays for: the years of peak-cycle cash
flow before mid-cycle.

Run:  python -m pytest tests/test_memory_mid_cycle.py -q
"""

import copy
import math
import os
import sys
from types import SimpleNamespace

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "src"))
sys.path.insert(0, os.path.join(_ROOT, "tests"))

from src.agents.fm import memory_cycle  # noqa: E402
from src.agents.fm.assumption_grounding import ground_assumptions  # noqa: E402
from test_memory_cycle_and_operating_costs import _base_like, _sandisk_like_payload  # noqa: E402

SANDISK = ("Sandisk Corporation develops, manufactures, and sells data storage devices and "
           "solutions using NAND flash technology.")
MICRON = ("Micron designs, develops, manufactures and sells memory and storage products, "
          "including DRAM, NAND and NOR memory.")


def _sandisk():
    payload = _sandisk_like_payload()
    payload["company_data"]["basic_info"].update(
        {"industry": "Computer Hardware", "business_summary": SANDISK})
    return payload


# ── who, and with what history ───────────────────────────────────────────────

def test_kind_follows_what_the_company_makes():
    assert memory_cycle.memory_kind("Computer Hardware", SANDISK) == "nand"
    assert memory_cycle.memory_kind("Semiconductors", MICRON) == "dram"
    assert memory_cycle.memory_kind("Semiconductors", "NVIDIA designs GPUs.") is None


def test_inputs_place_the_trend_from_the_reported_years():
    inputs = memory_cycle.mid_cycle_inputs(_sandisk())
    assert inputs["kind"] == "nand"
    assert inputs["operating_margin"] == 0.18
    assert len(inputs["history"]) == 3
    # The geometric mean of FY2024-FY2026 revenue (a trend is log-linear; the
    # arithmetic mean let one boom year move MU's FY4 trend by 76%).
    assert inputs["trend_revenue_mean"] == pytest.approx((6.663e9 * 7.355e9 * 20.248e9) ** (1 / 3))
    assert inputs["base_period_end"] == "2026-06-30"


def test_no_mid_cycle_without_three_reported_years_or_for_a_non_memory_maker():
    short = _sandisk()
    statements = short["financial_statements"]["income_statement"]
    statements.pop(min(statements))
    assert memory_cycle.mid_cycle_inputs(short) is None
    other = _sandisk()
    other["company_data"]["basic_info"]["business_summary"] = "Designs GPUs."
    assert memory_cycle.mid_cycle_inputs(other) is None


# ── the rewrite, through ground_assumptions ─────────────────────────────────

def _grounded(payload):
    return ground_assumptions(_base_like(0.616, 0.715), payload)


def test_covered_years_stay_the_street_case_then_revert(monkeypatch):
    monkeypatch.setenv("RISK_FREE_USD", "0.04")
    street, _ = _grounded(_sandisk_like_payload())        # no description: as before
    grounded, notes = _grounded(_sandisk())
    g, m = grounded["revenue_growth_rates"], grounded["operating_margins"]

    assert g[:2] == pytest.approx(street["revenue_growth_rates"][:2])
    assert m[:2] == pytest.approx(street["operating_margins"][:2])
    assert m[2] == pytest.approx((m[1] + 0.18) / 2)
    assert m[3:] == pytest.approx([0.18, 0.18])
    assert g[4] == pytest.approx(0.09)                     # FY5 grows at the trend

    base = grounded["modeling_basis"]["revenue"]
    revenue = [base]
    for rate in g:
        revenue.append(revenue[-1] * (1 + rate))
    inputs = memory_cycle.mid_cycle_inputs(_sandisk())
    assert revenue[4] == pytest.approx(memory_cycle.trend_revenue(inputs, 4))
    assert revenue[3] == pytest.approx(math.sqrt(revenue[2] * revenue[4]))

    # Operating costs follow trend revenue: 15% of trend dollars every year,
    # so a smaller share of FY3's still-elevated revenue, never a spike.
    for i in (2, 3, 4):
        costs = (grounded["gross_margins"][i] - m[i]) * revenue[i + 1]
        assert costs == pytest.approx(0.15 * memory_cycle.trend_revenue(inputs, i + 1))
    assert grounded["comps_included_in_blended_value"] is False
    assert grounded["mid_cycle"]["kind"] == "nand"
    assert grounded["revenue_growth_source"].startswith(street["revenue_growth_source"])
    assert any(note.startswith("Mid-cycle (NAND maker)") for note in notes)


def test_a_company_that_is_not_a_memory_maker_is_untouched(monkeypatch):
    monkeypatch.setenv("RISK_FREE_USD", "0.04")
    payload = _sandisk()
    payload["company_data"]["basic_info"]["business_summary"] = "Designs GPUs."
    before, _ = _grounded(_sandisk_like_payload())
    after, _ = _grounded(payload)
    assert after["revenue_growth_rates"] == pytest.approx(before["revenue_growth_rates"])
    assert after["operating_margins"] == pytest.approx(before["operating_margins"])
    assert "mid_cycle" not in after


# ── what the price pays for ──────────────────────────────────────────────────

_FCF = [19.6, 32.2, 18.2, 6.1, 2.5, 2.7, 2.8, 3.0, 3.1, 3.2]


def _ev(n, street_growth=0.188, trend=0.09, wacc=0.12, g=0.025):
    peak = _FCF[:2] + [_FCF[1] * (1 + street_growth) ** k for k in range(1, n - 1)]
    tail = [f * (1 + trend) ** (n - 2) for f in _FCF[2:]]
    return memory_cycle._enterprise_value(peak + tail, wacc, g, 0.0)


def test_peak_years_recovers_a_known_answer():
    result = memory_cycle.peak_years_implied(
        _FCF, wacc=0.12, terminal_growth=0.025, enterprise_value=_ev(7),
        street_growth=0.188, trend_growth=0.09)
    assert result["peak_years"] == pytest.approx(7.0, abs=0.05)
    sentence = memory_cycle.peak_years_sentence(result)
    assert "about 7 years of the Street's peak-cycle cash flow, extended at its FY2 growth" in sentence
    # Micron above its through-cycle 21%: FY2017-FY2019 and FY2021-FY2022.
    assert "two to three years (FY2017-FY2019, FY2021-FY2022)" in sentence


def test_a_price_below_the_mid_cycle_value_and_one_beyond_reach():
    low = memory_cycle.peak_years_implied(
        _FCF, wacc=0.12, terminal_growth=0.025, enterprise_value=_ev(2) * 0.8,
        street_growth=0.188, trend_growth=0.09)
    assert low["below_mid_cycle"] is True
    assert "pays less than" in memory_cycle.peak_years_sentence(low)
    high = memory_cycle.peak_years_implied(
        _FCF, wacc=0.12, terminal_growth=0.025, enterprise_value=_ev(2) * 1000,
        street_growth=0.188, trend_growth=0.09)
    assert high["beyond_bound"] == 25


def test_the_workbook_benchmark_is_peak_years_for_a_mid_cycle_model():
    from src.external_expectations import required_revenue_growth_from_workbook
    from src.summary_evidence import required_growth_sentence
    dcf = {f"(16, {column})": value for column, value in zip(range(2, 12), _FCF)}
    dcf.update({"(12, 2)": 0.12, "(23, 2)": 0.025})
    computed = {
        "Valuation (DCF)": {"cells": dcf},
        "Summary": {"cells": {"(51, 2)": _ev(6)}},
        "Model_Inputs": {"cells": {"(4, 3)": 0.188}},
        "Sensitivity": {"cells": {"(4, 2)": 0}},
        "_vynn": {"model_inputs": {"mid_cycle": {"revenue_trend_growth": 0.09}}},
    }
    required = required_revenue_growth_from_workbook(computed)
    assert required["kind"] == "mid_cycle_peak_years"
    assert required["peak_years"] == pytest.approx(6.0, abs=0.05)
    assert required_growth_sentence(required).startswith("At this price, the market pays for about 6 years")


# ── publication ──────────────────────────────────────────────────────────────

def _memory_financials():
    from test_valuation_runway_and_corroboration import _financials
    data = _financials()
    data["company_data"]["basic_info"].update(
        {"industry": "Computer Hardware", "business_summary": SANDISK})
    for statement, row in (("income_statement", {"Total Revenue": 80}),
                           ("balance_sheet", {"Total Assets": 160}),
                           ("cash_flow", {"Operating Cash Flow": 16, "Free Cash Flow": 11})):
        data["financial_statements"][statement]["2024-06-30"] = row
    return data


def test_a_mid_cycle_method_needs_a_mid_cycle_workbook():
    from src.report_agent import enforce_valuation_publication_boundary
    from test_valuation_runway_and_corroboration import _report_data
    unbuilt = enforce_valuation_publication_boundary(
        _report_data(exit_value=15.0, exit_multiple=10.0, model_inputs={}),
        _memory_financials())["valuation"]["reliability"]
    assert unbuilt["point_estimate_withheld"] is True
    assert "not built on mid-cycle revenue and margins" in unbuilt["withheld_reason"]

    built = enforce_valuation_publication_boundary(
        _report_data(exit_value=15.0, exit_multiple=10.0,
                     model_inputs={"mid_cycle": {"kind": "nand"}}),
        _memory_financials())["valuation"]["reliability"]
    assert "mid-cycle" not in str(built.get("withheld_reason") or "")
    assert built["method_suitability"]["primary_method"] == "dcf_mid_cycle"


def test_the_published_answer_says_how_and_what_the_price_pays_for():
    from src.agents.supervisor import supervisor_agent
    runner = supervisor_agent.SupervisorWorkflowRunner.__new__(
        supervisor_agent.SupervisorWorkflowRunner)
    runner.ticker = "SNDK"
    runner.state = SimpleNamespace(
        financial_data=SimpleNamespace(key_metrics={"basic_info": {"currency": "USD"}}, raw_data={}),
        news_analysis=None,
        financial_model=SimpleNamespace(assumptions={}, valuation_metrics={
            "fair_value": 587.36, "current_price": 1692.42,
            "method_suitability": {"primary_method": "dcf_mid_cycle",
                                   "mid_cycle": {"kind": "nand", "operating_margin": 0.18}},
            "market_required_revenue_growth": {"available": True, "kind": "mid_cycle_peak_years",
                                               "peak_years": 7.4, "below_mid_cycle": False},
        }),
    )
    answer = runner._safe_published_valuation_answer({"rating": "STRONG SELL"})
    assert "model fair value $587.36 USD" in answer
    assert "mid-cycle economics" in answer and "18% operating margin" in answer
    assert "NAND industry's through-cycle level" in answer
    assert "about 7 years of the Street's peak-cycle cash flow" in answer


def test_the_dashboard_sentence_says_how_and_is_not_a_scenario_note():
    from src.market_expectations import build_market_expectations
    dcf = {f"(16, {column})": value for column, value in zip(range(2, 12), _FCF)}
    dcf.update({"(12, 2)": 0.12, "(23, 2)": 0.025})
    computed = {
        "Valuation (DCF)": {"cells": dcf},
        "Summary": {"cells": {"(51, 2)": _ev(6), "(9, 2)": 1692.42}},
        "Model_Inputs": {"cells": {"(4, 3)": 0.188}},
        "Sensitivity": {"cells": {"(4, 2)": 0}},
        "_vynn": {"model_inputs": {"mid_cycle": {"revenue_trend_growth": 0.09}}},
    }
    payload = build_market_expectations(
        computed, _memory_financials(), {"point_estimate_withheld": False})
    assert payload["sentence"].startswith("VYNN values a memory maker on mid-cycle economics")
    assert "about 6 years of the Street's peak-cycle cash flow" in payload["sentence"]
    # api-runner maps method_note to "scenario only": a published value has none.
    assert payload["method_note"] is None
    assert payload["required_growth"]["kind"] == "mid_cycle_peak_years"



def test_no_peak_years_outside_a_boom():
    # A trough: the covered years earn less than the mid-cycle path.
    trough = [-1.0, 1.5, 2.0, 3.0, 3.2, 3.4, 3.6, 3.8, 4.0, 4.2]
    result = memory_cycle.peak_years_implied(
        trough, wacc=0.12, terminal_growth=0.025, enterprise_value=100.0,
        street_growth=0.4, trend_growth=0.09)
    assert result["available"] is False and result["not_a_boom"] is True
    assert memory_cycle.peak_years_sentence(result) is None


def _peers_qualify(monkeypatch):
    import src.valuation_methodology as methodology
    real = methodology.normalize_peer_comps_policy
    def qualifying(peer_comps):
        policy = dict(real(peer_comps))
        policy.update(included_in_blended_value=True, usable=True)
        return policy
    monkeypatch.setattr(methodology, "normalize_peer_comps_policy", qualifying)


def test_peers_never_enter_a_mid_cycle_value(monkeypatch):
    """With production's peer setting, a peak-cycle multiple must not blend back in."""
    from src.report_agent import enforce_valuation_publication_boundary
    from test_valuation_runway_and_corroboration import _financials, _report_data
    _peers_qualify(monkeypatch)
    data = _report_data(exit_value=15.0, exit_multiple=10.0,
                        model_inputs={"mid_cycle": {"kind": "nand"}})
    data["valuation"]["summary"]["comps_intrinsic"] = 300.0
    reliability = enforce_valuation_publication_boundary(
        copy.deepcopy(data), _memory_financials())["valuation"]["reliability"]
    assert "market_comps" not in {k for k, v in reliability["legs"].items() if v}
    alert = reliability.get("confidence_alert") or {}
    assert "no independent market-comps valuation qualified" not in str(alert.get("detail"))
    # The same peers still blend for an ordinary company.
    ordinary = enforce_valuation_publication_boundary(
        copy.deepcopy(data), _financials())["valuation"]["reliability"]
    assert ordinary["legs"].get("market_comps") == 300.0


def test_the_dashboard_follows_the_workbook_not_the_policy():
    """A memory maker's workbook built without the rewrite reads as a scenario."""
    from src.market_expectations import build_market_expectations
    computed = {"Summary": {"cells": {"(51, 2)": 100.0, "(9, 2)": 1692.42}},
                "_vynn": {"model_inputs": {}}}
    payload = build_market_expectations(
        computed, _memory_financials(), {"point_estimate_withheld": True,
                                         "range_low": 3000.0, "range_high": 3500.0})
    assert payload["method_note"] and "not built on mid-cycle" in payload["method_note"]
    assert not str(payload["sentence"] or "").startswith("VYNN values a memory maker")


def test_the_trend_is_counted_from_the_projections_own_base(monkeypatch):
    """Too few analysts for the rolling clock: the projections start from the
    last fiscal year, and FY4's trend is counted from that year too."""
    monkeypatch.setenv("RISK_FREE_USD", "0.04")
    payload = _sandisk()
    # A quarter past the fiscal year end: the TTM date and the annual base differ.
    payload["ttm_bridge"]["latest_period"] = "2026-09-30"
    for horizon in ("0y", "+1y"):
        payload["analyst_data"]["revenue_estimates"][horizon]["numberOfAnalysts"] = 3
        payload["analyst_data"]["earnings_estimates"][horizon]["numberOfAnalysts"] = 3
    grounded, _ = _grounded(payload)
    basis = grounded.get("modeling_basis") or {}
    inputs = memory_cycle.mid_cycle_inputs(payload)
    if isinstance(basis.get("revenue"), (int, float)) and basis["revenue"] > 0:
        base, period = basis["revenue"], (grounded.get("forecast_basis") or {}).get(
            "period_end") or inputs["base_period_end"]
    else:
        base, period = inputs["history"][-1]["revenue"], inputs["history"][-1]["period_end"]
    assert basis.get("revenue") is None                   # the fiscal-year fallback
    assert period == "2026-06-30"
    assert grounded["mid_cycle"]["base_period_end"] == period
    revenue = [base]
    for rate in grounded["revenue_growth_rates"]:
        revenue.append(revenue[-1] * (1 + rate))
    assert revenue[4] == pytest.approx(memory_cycle.trend_revenue(inputs, 4, period))
