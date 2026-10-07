"""
Sandisk was valued at about 2x its price (+109%; the Street +26%) with a
STRONG BUY. Two things let that through:

1. It makes only NAND. A memory maker was recognised by "DRAM" and "NAND"
   both appearing in the business description, so Sandisk was not routed to
   the memory cycle and published a point value. Memory makers are scenarios
   until a mid-cycle margin exists (Micron is).
2. The Street EPS case lifted its operating margin to the ten-point cap,
   71.6%, and gross margin was then raised only to the operating margin:
   71.6% gross, 71.6% operating, R&D and SG&A at 0% of revenue against $2B a
   year actually spent. Gross margin now keeps room for operating costs at
   the lowest share of revenue the company has actually run.

Run:  python -m pytest tests/test_memory_cycle_and_operating_costs.py -q
"""

import copy
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "src"))
sys.path.insert(0, os.path.join(_ROOT, "tests"))

from src.valuation_methodology import is_memory_maker  # noqa: E402
from src.agents.fm import assumption_grounding  # noqa: E402
from src.agents.fm.assumption_grounding import ground_assumptions  # noqa: E402
from test_valuation_runway_and_corroboration import (  # noqa: E402
    _base_assumptions, _tesla_like_payload,
)


# ── 1. who is a memory maker (Yahoo's own industry and description) ─────────

@pytest.mark.parametrize("ticker, industry, summary, expected", [
    ("SNDK", "Computer Hardware",
     "Sandisk Corporation develops, manufactures, and sells data storage devices and "
     "solutions using NAND flash technology in the Americas, Europe, the Middle East, "
     "Africa, Asia, and internationally.", True),
    ("MU", "Semiconductors",
     "Micron Technology, Inc. designs, develops, manufactures, and sells memory and "
     "storage products. The company provides memory products, including DRAM "
     "components and modules, and NAND flash.", True),
    # Designs controllers for NAND; sells into the cycle, is not priced by it.
    ("SIMO", "Semiconductors",
     "Silicon Motion Technology Corporation, together with its subsidiaries, designs, "
     "develops, and markets NAND flash controllers for solid-state storage devices. "
     "It markets and sells its products to NAND flash makers, module makers, "
     "hyperscalers, and OEMs.", False),
    # Tests DRAM; filed under equipment.
    ("TER", "Semiconductor Equipment & Materials",
     "Teradyne designs, develops, manufactures, and sells automated test systems, "
     "including the Magnum platform that tests memory devices, such as flash memory "
     "and DRAM.", False),
    # Embedded flash in microcontrollers; neither NAND nor DRAM.
    ("MCHP", "Semiconductors",
     "Microchip Technology manufactures microcontrollers and offers memory products "
     "consisting of serial flash memories and parallel flash memories.", False),
    ("NVDA", "Semiconductors",
     "NVIDIA provides graphics and compute platforms; its GPUs use high-bandwidth "
     "DRAM supplied by memory makers.", False),
    ("DELL", "Computer Hardware",
     "Dell Technologies designs, develops, manufactures, markets, sells, and supports "
     "servers and all-flash storage solutions.", False),
])
def test_memory_makers_are_recognised_by_what_they_make(ticker, industry, summary, expected):
    assert is_memory_maker(industry, summary) is expected, ticker


def test_sandisk_is_a_scenario_like_micron():
    from test_valuation_methodology import _operating_company
    from src.valuation_methodology import assess_valuation_methodology
    data = _operating_company()
    data["company_data"]["basic_info"].update({
        "industry": "Computer Hardware",
        "business_summary": "Sandisk Corporation develops, manufactures, and sells data "
                            "storage devices and solutions using NAND flash technology.",
    })
    result = assess_valuation_methodology(data)
    assert result["primary_method"] == "scenario_only_pending_cycle_normalization"
    assert result["publication_allowed"] is False


# ── 2. operating costs never projected to zero ──────────────────────────────

def _sandisk_like_payload():
    """Sandisk's statements (FY ends June) with Street EPS above the cap."""
    payload = _tesla_like_payload()
    statements = {
        "2026-06-30": {"Total Revenue": 20.248e9, "Operating Income": 12.468e9,
                       "EBITDA": 12.617e9, "Gross Profit": 14.472e9,
                       "Pretax Income": 12.0e9, "Tax Provision": 1.0e9},
        "2025-06-30": {"Total Revenue": 7.355e9, "Operating Income": 0.507e9,
                       "EBITDA": 0.670e9, "Gross Profit": 2.212e9,
                       "Pretax Income": 0.4e9, "Tax Provision": 0.1e9},
        "2024-06-30": {"Total Revenue": 6.663e9, "Operating Income": -0.444e9,
                       "EBITDA": -0.220e9, "Gross Profit": 1.072e9,
                       "Pretax Income": -0.6e9, "Tax Provision": 0.07e9},
    }
    payload["financial_statements"] = {"income_statement": statements}
    payload["company_data"]["market_data"].update({
        "market_cap": 250e9, "current_price": 1725.77,
        "shares_outstanding_basic": 145_000_000, "shares_outstanding_implied": 145_000_000,
    })
    payload["company_data"]["growth_profitability"] = {
        "operating_margins": 0.616, "ebitda_margins": 0.623, "gross_margins": 0.715,
    }
    payload["ttm_bridge"] = {
        "status": "current", "latest_period": "2026-06-30",
        "normalized": {"revenue": 20.248e9, "da_to_revenue": 0.0074,
                       "capex_to_revenue": -0.009},
        "income_statement": {"Total Revenue": 20.248e9, "Operating Income": 12.468e9,
                             "Gross Profit": 14.472e9, "Interest Expense": 0.05e9,
                             "Interest Income": 0.1e9},
        "cash_flow": {"Depreciation And Amortization": 0.149e9},
    }
    payload["analyst_data"] = {
        "revenue_estimates": {
            "0y": {"avg": 49.06e9, "growth": 1.42, "numberOfAnalysts": 20, "currency": "USD"},
            "+1y": {"avg": 58.28e9, "growth": .19, "numberOfAnalysts": 18, "currency": "USD"},
        },
        "earnings_estimates": {
            "0y": {"avg": 230.0, "growth": 2.0, "numberOfAnalysts": 20, "currency": "USD"},
            "+1y": {"avg": 280.0, "growth": .2, "numberOfAnalysts": 18, "currency": "USD"},
        },
    }
    return payload


def _base_like(oms, gms):
    base = _base_assumptions()
    base.update(operating_margins=[oms] * 5, gross_margins=[gms] * 5,
                ebitda_margins=[oms + 0.007] * 5)
    return base


def test_a_street_margin_at_the_cap_keeps_room_for_operating_costs(monkeypatch):
    monkeypatch.setenv("RISK_FREE_USD", "0.04")
    grounded, _ = ground_assumptions(_base_like(0.616, 0.715), _sandisk_like_payload())

    oms, gms = grounded["operating_margins"], grounded["gross_margins"]
    assert grounded["margin_anchor"]["clamped"] is True
    assert oms[0] == pytest.approx(12.468 / 20.248 + 0.10)
    # FY2026 is the leanest year on record: (14.472 - 12.468) / 20.248.
    floor = (14.472 - 12.468) / 20.248
    for operating, gross in zip(oms, gms):
        assert gross - operating >= floor - 1e-9


def test_the_floor_is_the_leanest_year_not_the_latest(monkeypatch):
    # Tesla's TTM operating costs are 14.2% of revenue; its leanest year
    # (2023) was 9.1%. The Street lifts the operating margin from 4.6% to
    # ~7.5% and the gross path leaves ~11 points: nothing to raise.
    monkeypatch.setenv("RISK_FREE_USD", "0.04")
    floor = assumption_grounding._operating_cost_ratio_floor(_tesla_like_payload())
    assert floor == pytest.approx((17.7e9 - 8.9e9) / 96.8e9)


def test_tesla_comes_out_exactly_as_before(monkeypatch):
    """The floor binds only where the projection had no room for costs."""
    monkeypatch.setenv("RISK_FREE_USD", "0.04")
    now, _ = ground_assumptions(_base_assumptions(), _tesla_like_payload())
    monkeypatch.setattr(assumption_grounding, "_operating_cost_ratio_floor", lambda _: 0.0)
    before, _ = ground_assumptions(_base_assumptions(), _tesla_like_payload())
    assert now["gross_margins"] == pytest.approx(before["gross_margins"])
    assert now["operating_margins"] == pytest.approx(before["operating_margins"])


def test_without_both_lines_the_floor_is_zero():
    payload = copy.deepcopy(_tesla_like_payload())
    for row in payload["financial_statements"]["income_statement"].values():
        row.pop("Gross Profit")
    payload["ttm_bridge"]["income_statement"].pop("Gross Profit")
    # Booking Holdings reports no cost of revenue: behaviour as before.
    assert assumption_grounding._operating_cost_ratio_floor(payload) == 0.0


def test_a_path_that_already_leaves_room_is_never_touched(monkeypatch):
    """
    Only a gross path that fell below the operating margin is raised. Applied
    to every year, the floor moved AMD +5.6% and Amazon -1.3% through
    cost-of-revenue working capital (their leanest cost ratios, ~40%, carry
    acquisition amortization), with nothing wrong in either.
    """
    monkeypatch.setenv("RISK_FREE_USD", "0.04")
    monkeypatch.setattr(assumption_grounding, "_operating_cost_ratio_floor", lambda _: 0.30)
    wide, _ = ground_assumptions(_base_assumptions(), _tesla_like_payload())
    monkeypatch.setattr(assumption_grounding, "_operating_cost_ratio_floor", lambda _: 0.0)
    before, _ = ground_assumptions(_base_assumptions(), _tesla_like_payload())
    assert wide["gross_margins"] == pytest.approx(before["gross_margins"])
