"""Regression tests for the 2026-09-26 valuation fix.

Since the 2026-09-15 engine, 9 of 11 production runs were NOT RATED, including
every full analysis a real user asked for (NVDA, TSLA twice, META). Four
mechanical defects made corroboration impossible and one modeling choice made
the DCF absurd for growth names:

  1. an exit-multiple leg that never ran (observed EV/EBITDA above the 80x
     provider boundary: TSLA 134x, AMD 83x) was recorded as a *failed* method
     and blocked publication on its own;
  2. the peer collector chose sector leaders for every USD mega-cap and the
     publication policy rejected them, so no mega-cap ever received a comps
     vote (0 of 10 runs). A candidate that let a size/margin/growth-screened
     sector-leader roster vote was tried and rejected at the gate: the
     "screened" roster for META and GOOGL was T, VZ and TMUS (median 8.2x
     EV/EBITDA) and for TSLA and AMZN it was HD, SBUX and TJX. Sector leaders
     stay a cross-check; a mega-cap publishes on its DCF with Street
     corroboration (item 3) instead;
  3. the boundary required a "provider-dated" analyst target, Finnhub's dated
     endpoint is paid, and Yahoo's live target carries no date, so no
     free-tier target could ever corroborate (NVDA at +29% with the Street at
     +50% was withheld);
  4. the post-consensus growth fade collapsed to terminal by year five, so an
     11% grower was valued as a no-growth business ($15 for TSLA);
  5. margins extrapolated the trailing trough while the Street's EPS case,
     which the boundary used to challenge the model, was never used to build it.

Each test here reintroduces one defect's input and asserts the new behavior.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from src.agents.fm.assumption_grounding import (  # noqa: E402
    _POST_CONSENSUS_GROWTH_CAP,
    _post_consensus_growth_path,
    ground_assumptions,
)
from src.agents.tools.analysis_tools import valuation_publication_boundary  # noqa: E402
from src.external_expectations import build_external_expectations  # noqa: E402
from src.peer_comps import collect_peer_comps  # noqa: E402
from src.report_agent import enforce_valuation_publication_boundary  # noqa: E402
from src.valuation_methodology import normalize_peer_comps_policy  # noqa: E402


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------

def _financials(period="2026-06-30"):
    prior = f"{int(period[:4]) - 1}{period[4:]}"
    return {
        "company_data": {
            "basic_info": {
                "quote_type": "EQUITY", "currency": "USD", "listing_currency": "USD",
            },
        },
        "financial_statements": {
            "income_statement": {
                period: {"Total Revenue": 100},
                prior: {"Total Revenue": 90},
            },
            "balance_sheet": {
                period: {"Total Assets": 200},
                prior: {"Total Assets": 180},
            },
            "cash_flow": {
                period: {"Operating Cash Flow": 20, "Free Cash Flow": 15},
                prior: {"Operating Cash Flow": 18, "Free Cash Flow": 13},
            },
        },
    }


def _report_data(*, exit_value, exit_multiple, model_inputs=None):
    data = {
        "company_overview": {
            "company_name": "Tesla, Inc.",
            "current_price": 372.11,
            "market_cap": 1_470_000_000_000,
            "currency": "USD",
            "listing_currency": "USD",
            "target_mean_price": 396.62,
            "num_analysts": 38,
        },
        "valuation": {
            "dcf_perpetual": {"intrinsic_value_per_share": 14.92},
            "dcf_exit": {
                "intrinsic_value_per_share": exit_value,
                "exit_multiple": exit_multiple,
            },
            "summary": {"average_intrinsic": 14.92, "comps_intrinsic": 0.0, "upside": -0.96},
        },
    }
    if model_inputs is not None:
        data["model_inputs"] = model_inputs
    return data


# --------------------------------------------------------------------------
# 1. an exit leg that never ran is absent, not broken
# --------------------------------------------------------------------------

def test_unavailable_exit_leg_is_omitted_not_reported_as_failed():
    data = _report_data(
        exit_value=0.0, exit_multiple=0,
        model_inputs={"exit_multiple_available": False},
    )
    reliability = enforce_valuation_publication_boundary(data, _financials())[
        "valuation"]["reliability"]

    assert "exit_multiple_dcf" not in reliability["legs"]
    assert reliability["failed_legs"] == {}
    assert "failed with a non-positive value" not in reliability["withheld_reason"]
    # Still withheld, for the right reason: a DCF-only mega-cap gap of -96%
    # with nothing to corroborate it.
    assert reliability["point_estimate_withheld"] is True
    assert "DCF-only estimate" in reliability["withheld_reason"]


def test_workbook_zero_multiple_alone_marks_the_exit_leg_unavailable():
    """Artifacts saved before the flag was persisted carry only the workbook's
    own signal: a zero terminal multiple with a zero per-share value."""
    data = _report_data(exit_value=0.0, exit_multiple=0)
    reliability = enforce_valuation_publication_boundary(data, _financials())[
        "valuation"]["reliability"]

    assert "exit_multiple_dcf" not in reliability["legs"]
    assert reliability["failed_legs"] == {}


def test_a_genuinely_failed_exit_leg_is_still_reported():
    """A positive admitted multiple that produced a non-positive value is a
    real method failure and must keep blocking a point estimate."""
    data = _report_data(exit_value=-5.0, exit_multiple=12.0)
    reliability = enforce_valuation_publication_boundary(data, _financials())[
        "valuation"]["reliability"]

    assert reliability["failed_legs"] == {"exit_multiple_dcf": -5.0}
    assert "failed with a non-positive value" in reliability["withheld_reason"]


# --------------------------------------------------------------------------
# 3. an undated live target captured this week corroborates
# --------------------------------------------------------------------------

def _nvda_like(captured_at: str):
    return {
        "company_data": {
            "basic_info": {"currency": "USD"},
            "market_data": {
                "current_price": 219.34,
                "shares_outstanding_basic": 24_147_000_000,
            },
            "analyst_consensus": {
                "captured_at": captured_at,
                "price_target": {
                    "mean": 328.49, "median": 330, "low": 200, "high": 400,
                    "analyst_count": 58, "currency": "USD",
                    "source": "yahoo_finance", "as_of": None,
                },
                "recommendation": {"label": "strong_buy", "source": "finnhub"},
                "source_snapshots": {
                    "yahoo_finance": {
                        "captured_at": captured_at,
                        "price_target": {
                            "mean": 328.49, "analyst_count": 58,
                            "currency": "USD", "as_of": None,
                        },
                    },
                    "finnhub": {"recommendation": {
                        "label": "strong_buy", "total": 53, "period": "2026-09-01",
                    }},
                },
            },
        },
        "analyst_data": {"revenue_estimates": {}, "earnings_estimates": {}},
    }


def _iso(days_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def test_undated_live_target_captured_this_week_corroborates_a_dcf_only_claim():
    expectations = build_external_expectations(_nvda_like(_iso(0.2)))
    evidence = expectations["price_target"]["source_evidence"]["yahoo_finance"]

    assert evidence["temporal_quality"]["status"] == "unknown"
    assert evidence["temporal_quality"]["capture_current"] is True
    assert evidence["qualified_for_corroboration"] is True
    assert any("accepted as current for corroboration" in w for w in expectations["warnings"])

    withheld, reason = valuation_publication_boundary(
        band="single-method",
        legs={"perpetual_dcf": 271.53, "exit_multiple_dcf": 294.85},
        fair_value=283.19,
        current_price=219.34,
        is_mega_cap=True,
        analyst_target=328.49,
        analyst_count=58,
        analyst_target_evidence=expectations["price_target"]["source_evidence"],
    )
    # +29% model, +50% Street, same direction and more than half the move.
    assert withheld is False, reason


def test_a_month_old_capture_of_an_undated_target_does_not_corroborate():
    expectations = build_external_expectations(_nvda_like(_iso(30)))
    evidence = expectations["price_target"]["source_evidence"]["yahoo_finance"]

    assert evidence["temporal_quality"]["capture_current"] is False
    assert evidence["qualified_for_corroboration"] is False
    assert evidence["qualified_for_contradiction"] is True

    withheld, reason = valuation_publication_boundary(
        band="single-method",
        legs={"perpetual_dcf": 271.53, "exit_multiple_dcf": 294.85},
        fair_value=283.19,
        current_price=219.34,
        is_mega_cap=True,
        analyst_target=328.49,
        analyst_count=58,
        analyst_target_evidence=expectations["price_target"]["source_evidence"],
    )
    assert withheld is True
    assert "no provider-dated current analyst target qualified" in reason
    assert "capture-dated" not in reason


# --------------------------------------------------------------------------
# 2. sector leaders never vote, even when they pass the comparability bands
# --------------------------------------------------------------------------

class _MegaCapClient:
    """Sub-industry peers are tiny; three sector leaders sit inside the bands."""

    def peers(self, _ticker):
        return ["SMALL1", "SMALL2"]

    def metrics(self, ticker):
        rows = {
            "SMALL1": (18.0, 9_000, 30.0, 25.0),
            "SMALL2": (16.0, 7_000, 28.0, 22.0),
            "LEAD1": (24.0, 1_800_000, 48.0, 41.0),
            "LEAD2": (21.0, 1_500_000, 55.0, 44.0),
            "LEAD3": (27.0, 2_600_000, 50.0, 46.0),
            "FAR": (30.0, 3_000_000, 20.0, 5.0),
        }
        multiple, cap, margin, growth = rows[ticker]
        return {
            "evEbitdaTTM": multiple,
            "marketCapitalization": cap,
            "operatingMarginTTM": margin,
            "revenueGrowthTTMYoy": growth,
        }


def test_sector_leaders_inside_the_bands_are_still_only_a_cross_check(monkeypatch):
    """Passing the margin and growth bands does not make a telco a META peer.

    The gate run that motivated this test admitted T, VZ and TMUS as META's
    "screened" comparables because their margins sat within 20 points and
    their growth within 30 points of the subject. Similar ratios are not a
    similar business, so a sector-leader roster keeps its low-confidence,
    context-only role no matter how many names survive the screens.
    """
    monkeypatch.setenv("PEER_COMPS_MIN_SIZE_RATIO", "0.05")
    out = collect_peer_comps(
        "NVDA", client=_MegaCapClient(), max_peers=6,
        subject_market_cap=5_300_000_000_000, sector="Technology",
        subject_operating_margin=.62, subject_revenue_growth=.60,
        fallback_symbols=["LEAD1", "LEAD2", "LEAD3", "FAR"],
    )

    assert out["status"] == "ready"
    assert out["grouping"] == "sector_leaders"
    assert out["selected_peer_symbols"] == ["LEAD1", "LEAD2", "LEAD3"]
    assert out["fundamental_excluded_symbols"] == ["FAR"]
    assert out["confidence"] == "low"
    assert out["role"] == "broad_sector_cross_check"
    assert out["included_in_blended_value"] is False
    assert normalize_peer_comps_policy(out)["included_in_blended_value"] is False


def test_legacy_sector_leader_artifact_without_the_contract_stays_excluded():
    policy = normalize_peer_comps_policy({
        "grouping": "sector_leaders",
        "peer_universe_source": "yahoo_sector_leaders",
        "median_ev_ebitda": 22.9,
        "ev_ebitda_peer_count": 4,
    })
    assert policy["included_in_blended_value"] is False


# --------------------------------------------------------------------------
# 4. the post-consensus fade keeps a moderate grower's runway
# --------------------------------------------------------------------------

def test_fade_is_linear_over_eight_years_and_capped_at_thirty_percent():
    # An 11.7% grower: 11.7% - (9.2% / 8) * k.
    path = _post_consensus_growth_path(0.117, 0.025, 8)
    step = (0.117 - 0.025) / 8
    assert path == pytest.approx([0.117 - step * k for k in range(1, 9)])
    assert path[-1] == pytest.approx(0.025)
    # NVIDIA's +66% Street step starts the fade at the cap, not at 66%.
    capped = _post_consensus_growth_path(0.66, 0.025, 3)
    assert capped[0] == pytest.approx(_POST_CONSENSUS_GROWTH_CAP - (_POST_CONSENSUS_GROWTH_CAP - 0.025) / 8)
    assert capped[0] < 0.30
    # A decliner recovers along the line and never snaps above terminal.
    recovering = _post_consensus_growth_path(-0.05, 0.025, 8)
    assert recovering[0] > -0.05 and recovering[0] < 0.025
    assert all(a < b for a, b in zip(recovering, recovering[1:]))
    assert recovering[-1] == pytest.approx(0.025)


# --------------------------------------------------------------------------
# 5. the Street's EPS case anchors the covered years' margins
# --------------------------------------------------------------------------

def _tesla_like_payload(*, eps_0y=1.765, eps_1y=2.173):
    statements = {
        "2025-12-31": {"Total Revenue": 97.7e9, "Operating Income": 4.0e9,
                       "EBITDA": 10.5e9, "Gross Profit": 17.5e9,
                       "Pretax Income": 6.0e9, "Tax Provision": 1.4e9},
        "2024-12-31": {"Total Revenue": 97.7e9, "Operating Income": 7.1e9,
                       "EBITDA": 13.6e9, "Gross Profit": 17.5e9,
                       "Pretax Income": 8.0e9, "Tax Provision": 1.8e9},
        "2023-12-31": {"Total Revenue": 96.8e9, "Operating Income": 8.9e9,
                       "EBITDA": 14.8e9, "Gross Profit": 17.7e9,
                       "Pretax Income": 9.9e9, "Tax Provision": -5.0e9},
    }
    return {
        "company_data": {
            "basic_info": {"currency": "USD", "listing_currency": "USD",
                           "country": "United States"},
            "capital_structure": {"beta": 1.5, "total_debt": 16.1e9},
            "market_data": {
                "market_cap": 1.47e12, "current_price": 372.11,
                "shares_outstanding_basic": 3_949_547_394,
                "shares_outstanding_implied": 3_949_547_394,
            },
            "growth_profitability": {
                "operating_margins": 0.046, "ebitda_margins": 0.109,
                "gross_margins": 0.19,
            },
            "valuation_metrics": {},
        },
        "financial_statements": {"income_statement": statements},
        "ttm_bridge": {
            "status": "current",
            "latest_period": "2026-06-30",
            "normalized": {
                "revenue": 103.6e9, "da_to_revenue": 0.0625,
                "capex_to_revenue": -0.125,
            },
            "income_statement": {
                "Total Revenue": 103.6e9, "Operating Income": 4.77e9,
                "Gross Profit": 19.5e9, "Interest Expense": 0.33e9,
                "Interest Income": 1.6e9,
            },
            "cash_flow": {"Depreciation And Amortization": 6.48e9},
        },
        "analyst_data": {
            "revenue_estimates": {
                "0y": {"avg": 106.27e9, "growth": .12, "numberOfAnalysts": 42, "currency": "USD"},
                "+1y": {"avg": 120.79e9, "growth": .137, "numberOfAnalysts": 42, "currency": "USD"},
            },
            "earnings_estimates": {
                "0y": {"avg": eps_0y, "growth": .06, "numberOfAnalysts": 33, "currency": "USD"},
                "+1y": {"avg": eps_1y, "growth": .23, "numberOfAnalysts": 31, "currency": "USD"},
            },
        },
    }


def _base_assumptions():
    return {
        "wacc": 0.116,
        "terminal_growth_rate": 0.025,
        "operating_margins": [0.046] * 5,
        "ebitda_margins": [0.109] * 5,
        "gross_margins": [0.19] * 5,
        "revenue_growth_rates": [0.05] * 5,
    }


def test_street_eps_case_lifts_a_trough_margin_and_never_decays_below_it(monkeypatch):
    monkeypatch.setenv("RISK_FREE_USD", "0.04")
    grounded, notes = ground_assumptions(_base_assumptions(), _tesla_like_payload())

    oms = grounded["operating_margins"]
    assert grounded["operating_margin_source"] == "yahoo_analyst_consensus_eps_bridge"
    # ~6.6% Street net margin at ~24% tax, less ~1.2% net interest income,
    # is a 7-8% operating margin against a 4.6% trailing print.
    assert 0.06 < oms[0] < 0.10
    assert oms[0] <= 0.046 + 0.10
    # The covered case is a floor for the later years, not a peak.
    assert all(a <= b + 1e-12 for a, b in zip(oms[1:], oms[2:]))
    # EBITDA stays operating margin plus the TTM D&A intensity.
    assert grounded["ebitda_margins"] == pytest.approx([m + 0.0625 for m in oms])
    assert grounded["margin_anchor"]["clamped"] is False
    assert any("anchored to the Street EPS case" in note for note in notes)


def test_an_implausible_street_margin_is_bounded_and_flagged(monkeypatch):
    monkeypatch.setenv("RISK_FREE_USD", "0.04")
    # EPS of $12 on 3.95B shares implies a ~45% net margin: a unit or
    # definition problem, not an operating forecast.
    payload = _tesla_like_payload(eps_0y=12.0, eps_1y=13.0)
    grounded, _ = ground_assumptions(_base_assumptions(), payload)

    # The bound is ten points above the TTM operating margin the path starts
    # from (4.77B / 103.6B), not the rounded profile figure.
    trailing = 4.77e9 / 103.6e9
    assert grounded["margin_anchor"]["trailing_operating_margin"] == pytest.approx(trailing)
    assert grounded["operating_margins"][0] == pytest.approx(trailing + 0.10)
    assert grounded["margin_anchor"]["clamped"] is True


def test_margins_are_left_alone_when_street_coverage_is_thin(monkeypatch):
    monkeypatch.setenv("RISK_FREE_USD", "0.04")
    payload = _tesla_like_payload()
    payload["analyst_data"]["earnings_estimates"]["0y"]["numberOfAnalysts"] = 3
    payload["analyst_data"]["earnings_estimates"]["+1y"]["numberOfAnalysts"] = 3

    grounded, _ = ground_assumptions(_base_assumptions(), payload)

    assert "operating_margin_source" not in grounded
    assert "margin_anchor" not in grounded


# --------------------------------------------------------------------------
# 6. the Street EPS bridge reconciles to the model's own NOPAT
# --------------------------------------------------------------------------

from src.agents.fm.assumption_grounding import (  # noqa: E402
    _street_margin_anchor,
    _year_ago_bridge_calibration,
)


def _bridge_payload(*, fy0_revenue, fy0_ebit, fy0_eps, fy0_shares, year_ago_eps,
                    fy0_unusual=0.0, quarters=None, eps_0y, eps_1y,
                    rev_0y, rev_1y, analysts=40):
    """A company with one reported year, two covered years and a provider basis."""
    statements = {
        "2025-12-31": {
            "Total Revenue": fy0_revenue, "Operating Income": fy0_ebit,
            "Diluted EPS": fy0_eps, "Diluted Average Shares": fy0_shares,
            "Net Income": fy0_eps * fy0_shares, "Total Unusual Items": fy0_unusual,
        },
    }
    return {
        "company_data": {
            "basic_info": {"currency": "USD", "listing_currency": "USD"},
            "market_data": {"shares_outstanding_basic": fy0_shares},
        },
        "financial_statements": {"income_statement": statements},
        "quarterly_financial_statements": {"income_statement": quarters or {}},
        "analyst_data": {
            "revenue_estimates": {
                "0y": {"avg": rev_0y, "numberOfAnalysts": analysts, "currency": "USD"},
                "+1y": {"avg": rev_1y, "numberOfAnalysts": analysts, "currency": "USD"},
            },
            "earnings_estimates": {
                "0y": {"avg": eps_0y, "numberOfAnalysts": analysts, "currency": "USD",
                       "yearAgoEps": year_ago_eps},
                "+1y": {"avg": eps_1y, "numberOfAnalysts": analysts, "currency": "USD"},
            },
        },
    }


def test_bridge_grosses_up_at_the_model_tax_rate_not_a_flat_25_percent():
    """NVIDIA-like: 55% Street net margin at a 14% tax is a ~64% EBIT margin.

    The old bridge grossed up at 25% (73%) and the model then taxed that EBIT
    at 14%, so its NOPAT margin (63%) exceeded the Street's own net margin.
    """
    payload = _bridge_payload(
        fy0_revenue=200e9, fy0_ebit=128e9, fy0_eps=4.50, fy0_shares=24.5e9,
        year_ago_eps=4.50, eps_0y=9.0, eps_1y=15.0,
        rev_0y=400e9, rev_1y=660e9,
    )
    anchor = _street_margin_anchor(payload, None, 0.14, 5)
    rows = anchor["rows"]
    street_net_margin = rows[1]["street_net_margin"]
    model_nopat_margin = rows[1]["implied_operating_margin"] * (1 - 0.14)
    # NOPAT margin must sit at or below the Street net margin (the wedge is
    # net non-operating income), never nine points above it.
    assert model_nopat_margin <= street_net_margin + 1e-9
    assert anchor["bridge"]["tax_rate"] == pytest.approx(0.14)


def test_reported_basis_gains_are_not_read_as_operating_margin():
    """Alphabet-like: a reported-basis 0y EPS carries this year's equity gains."""
    quarters = {
        "2026-03-31": {"Total Unusual Items": 60e9},
        "2026-06-30": {"Total Unusual Items": 70e9},
        "2025-09-30": {"Total Unusual Items": 10e9},  # prior fiscal year: ignored
    }
    tax = 0.166
    # FY2025: 400B revenue, 32% EBIT margin, 24B of unusual gains, 3B interest.
    fy0_ni = (128e9 + 24e9 + 3e9) * (1 - tax)
    shares = 12.2e9
    payload = _bridge_payload(
        fy0_revenue=400e9, fy0_ebit=128e9, fy0_eps=fy0_ni / shares, fy0_shares=shares,
        year_ago_eps=fy0_ni / shares, fy0_unusual=24e9, quarters=quarters,
        # FY2026 Street: 34% operating margin plus 130B of reported gains.
        eps_0y=((0.34 * 500e9) + 3.5e9 + 130e9) * (1 - tax) / shares,
        eps_1y=((0.35 * 600e9) + 4e9) * (1 - tax) / shares,
        rev_0y=500e9, rev_1y=600e9,
    )
    payload["financial_statements"]["income_statement"]["2025-12-31"][
        "Net Non Operating Interest Income Expense"] = 3e9
    calibration = _year_ago_bridge_calibration(payload, tax, 1.0)
    assert calibration["basis"] == "reported"
    assert calibration["wedge"] == pytest.approx(3e9 / 400e9)
    assert calibration["current_year_reported_unusual"] == pytest.approx(130e9)

    anchor = _street_margin_anchor(payload, None, tax, 5)
    first, second = (row["implied_operating_margin"] for row in anchor["rows"])
    # Without the fix the 0y row read ~60%: gains priced as operating profit.
    assert first == pytest.approx(0.34, abs=0.005)
    assert second == pytest.approx(0.35, abs=0.005)


def test_adjusted_basis_eps_is_reconciled_to_reported_operating_margin():
    """Tesla-like: the provider's EPS excludes stock compensation.

    Year-ago provider EPS 1.66 against 1.08 reported means the Street case
    carries ~2B a year of expense the reported income statement charges. The
    bridge must return the reported-basis margin, the one the cash flows use.
    """
    tax = 0.237
    payload = _bridge_payload(
        fy0_revenue=94.8e9, fy0_ebit=4.84e9, fy0_eps=1.08, fy0_shares=3.53e9,
        year_ago_eps=1.66, eps_0y=1.77, eps_1y=2.17,
        rev_0y=106.3e9, rev_1y=120.8e9,
    )
    calibration = _year_ago_bridge_calibration(payload, tax, 1.0)
    assert calibration["basis"] == "adjusted"
    # Feeding the year-ago EPS back through the bridge returns the reported
    # FY0 operating margin exactly: that is the calibration identity.
    year_ago_margin = 1.66 * 3.53e9 / 94.8e9
    assert year_ago_margin / (1 - tax) - calibration["wedge"] == pytest.approx(4.84e9 / 94.8e9)

    anchor = _street_margin_anchor(payload, None, tax, 5)
    naive = [row["street_net_margin"] / (1 - tax) for row in anchor["rows"]]
    anchored = [row["implied_operating_margin"] for row in anchor["rows"]]
    assert all(a < n - 0.02 for a, n in zip(anchored, naive))


def test_rolling_clock_uses_the_plus_one_year_estimate_for_year_two():
    tax = 0.2
    payload = _bridge_payload(
        fy0_revenue=100e9, fy0_ebit=10e9, fy0_eps=2.0, fy0_shares=4e9,
        year_ago_eps=2.0, eps_0y=2.4, eps_1y=3.6,
        rev_0y=110e9, rev_1y=125e9,
    )
    basis = {
        "basis": "rolling_twelve_months", "fiscal_year_progress": 0.5,
        "base_revenue": 105e9, "period_end": "2026-06-30",
    }
    anchor = _street_margin_anchor(payload, basis, tax, 5)
    assert len(anchor["rows"]) == 2
    assert anchor["rows"][1]["horizon"].startswith("NTM2")
    # The second year carries the +1y margin, above the blended first year.
    assert anchor["rows"][1]["implied_operating_margin"] > anchor["rows"][0]["implied_operating_margin"]


def test_bridge_falls_back_to_interest_when_the_year_ago_eps_is_missing():
    payload = _bridge_payload(
        fy0_revenue=100e9, fy0_ebit=10e9, fy0_eps=2.0, fy0_shares=4e9,
        year_ago_eps=None, eps_0y=2.4, eps_1y=2.8,
        rev_0y=110e9, rev_1y=120e9,
    )
    assert _year_ago_bridge_calibration(payload, 0.2, 1.0) is None
    anchor = _street_margin_anchor(payload, None, 0.2, 5)
    assert anchor["bridge"]["calibration"] is None
    assert "net non-operating interest" in anchor["bridge"]["basis"]


def test_grounding_passes_the_nopat_tax_rate_into_the_bridge(monkeypatch):
    """The caller used to pass a key that is never set, so every bridge ran at 25%."""
    monkeypatch.setenv("RISK_FREE_USD", "0.04")
    grounded, _ = ground_assumptions(_base_assumptions(), _tesla_like_payload())
    assert grounded["margin_anchor"]["bridge"]["tax_rate"] == pytest.approx(
        grounded["capm"]["tax_rate"]
    )


# --------------------------------------------------------------------------
# 7. what the price requires, in revenue growth
# --------------------------------------------------------------------------

from src.external_expectations import (  # noqa: E402
    implied_revenue_growth_for_enterprise_value,
)


def _tesla_like_path():
    base = 103.6e9
    revenues = [113.5e9, 128.1e9, 142.9e9, 157.4e9, 171.2e9]
    nopat = [r * 0.059 for r in revenues]
    fcf = [-2.1e9, 1.0e9, 3.1e9, 5.7e9, 8.7e9]
    return dict(base_revenue=base, revenue_path=revenues, nopat_path=nopat,
                fcf_path=fcf, wacc=0.116, terminal_growth=0.025)


def _franchise_path():
    """A 20% NOPAT-margin grower whose new capital earns ~4x its cost."""
    base = 100e9
    revenues = [110e9, 120e9, 130e9, 139e9, 147e9]
    previous = [base] + revenues[:-1]
    nopat = [r * 0.20 for r in revenues]
    fcf = [n - (r - p) / 2.0 for n, r, p in zip(nopat, revenues, previous)]
    return dict(base_revenue=base, revenue_path=revenues, nopat_path=nopat,
                fcf_path=fcf, wacc=0.09, terminal_growth=0.025)


def test_at_the_models_own_value_the_price_and_the_model_need_the_same_growth():
    """The reviewer's counterexample: a CAGR comparison contradicted the model.

    On one measure the two numbers must order exactly as the valuations do:
    equal at the model's value, above it for a richer price, below it for a
    cheaper one.
    """
    kwargs = _franchise_path()
    model_ev = 400e9
    at_fair = implied_revenue_growth_for_enterprise_value(
        model_ev, model_enterprise_value=model_ev, **kwargs)
    assert at_fair["required_growth"] == pytest.approx(at_fair["model_equivalent_growth"], abs=1e-9)
    rich = implied_revenue_growth_for_enterprise_value(
        1.3 * model_ev, model_enterprise_value=model_ev, **kwargs)
    cheap = implied_revenue_growth_for_enterprise_value(
        0.7 * model_ev, model_enterprise_value=model_ev, **kwargs)
    assert rich["required_growth"] > rich["model_equivalent_growth"]
    assert cheap["required_growth"] < cheap["model_equivalent_growth"]


def test_fragile_modeled_margin_falls_back_to_the_best_reported_margin():
    """Tesla-like: new capital earns ~1.3x WACC, so the modeled-margin number is
    too sensitive to state; the best-margin requirement (13% NOPAT) is not."""
    out = implied_revenue_growth_for_enterprise_value(
        1.44e12, **_tesla_like_path(), best_operating_margin=0.168,
        tax_rate=0.237, model_revenue_year10=218.4e9, model_enterprise_value=73e9)
    assert out["available"] is True
    assert "required_growth" not in out
    assert out["model_margin_note"] == "new_capital_return_below_stability_threshold"
    assert out["required_growth_at_best_margin"] > 0.30
    assert out["model_revenue_growth"] == pytest.approx((218.4e9 / 103.6e9) ** 0.1 - 1)


def test_growth_that_releases_cash_carries_no_reinvestment_charge():
    """A distributor whose model years grow with FCF above NOPAT."""
    kwargs = _franchise_path()
    kwargs["fcf_path"] = [n * 1.05 for n in kwargs["nopat_path"]]
    out = implied_revenue_growth_for_enterprise_value(350e9, **kwargs)
    assert out["sales_to_capital"] is None
    assert out["available"] is True and out["required_growth"] is not None


def test_required_growth_reports_a_bound_instead_of_a_number():
    out = implied_revenue_growth_for_enterprise_value(1e17, **_franchise_path())
    assert out["required_growth"] is None
    assert out["required_growth_beyond_bound"] == "above"


def test_required_growth_is_unavailable_without_a_positive_margin():
    kwargs = _tesla_like_path()
    kwargs["nopat_path"] = [-1e9] * 5
    assert implied_revenue_growth_for_enterprise_value(1e12, **kwargs) == {"available": False}


from src.summary_evidence import model_view_summary, required_growth_sentence  # noqa: E402


def _required(**overrides):
    base = {
        "available": True, "years": 10, "required_growth": 0.30,
        "required_growth_beyond_bound": None, "model_equivalent_growth": 0.12,
        "model_revenue_growth": 0.08, "best_operating_margin": 0.35,
        "required_growth_at_best_margin": 0.22,
        "required_growth_at_best_margin_beyond_bound": None,
        "revenue_source": "yahoo_analyst_consensus_rolling_twelve_months_with_deterministic_fade",
    }
    base.update(overrides)
    return {key: value for key, value in base.items() if value is not ...}


def test_sentence_sets_the_price_against_the_same_measure_at_the_models_value():
    assert required_growth_sentence(_required()) == (
        "At this price, revenue would have to grow about 30% a year for 10 years "
        "at the modeled margins; on the same measure, the model's analyst-based "
        "forecasts come to about 12% a year. Even at the company's best reported "
        "operating margin of 35%, the price would need about 22% a year."
    )


def test_sentence_never_claims_analyst_provenance_for_a_trend_path():
    text = required_growth_sentence(_required(revenue_source="historical_trend"))
    assert "analyst" not in text and "the model's revenue forecasts" in text


def test_best_margin_clause_only_when_it_still_exceeds_the_model():
    # Price below the model's value: no "even at" clause at all.
    cheap = required_growth_sentence(_required(required_growth=0.05))
    assert "Even at" not in cheap
    # Identical rounded numbers are not a finding either.
    same = required_growth_sentence(_required(required_growth_at_best_margin=0.302))
    assert "Even at" not in same


def test_sentence_falls_back_to_the_best_margin_when_the_modeled_margin_is_fragile():
    text = required_growth_sentence(_required(
        required_growth=..., model_equivalent_growth=..., best_operating_margin=0.17,
        required_growth_at_best_margin=0.40, model_revenue_growth=0.077,
    ))
    assert text == (
        "At this price, even at the company's best reported operating margin of "
        "17%, revenue would have to grow about 40% a year for 10 years; the "
        "model's analyst-based forecasts average about 8% a year."
    )


def test_sentence_handles_shrinking_and_unreachable_prices():
    shrinking = required_growth_sentence(_required(
        required_growth=-0.052, model_equivalent_growth=0.031,
        best_operating_margin=None, required_growth_at_best_margin=None,
    ))
    assert shrinking.startswith(
        "At this price, the market is pricing revenue shrinking about 5% a year"
    )
    unreachable = required_growth_sentence(_required(
        required_growth=None, required_growth_beyond_bound="above",
    ))
    assert "no revenue growth up to 150% a year for 10 years reaches the valuation" in unreachable
    assert required_growth_sentence({"available": False}) is None


def test_model_view_prefers_required_growth_over_the_cash_flow_multiple():
    view = model_view_summary(
        span={"low": 25.67, "high": 25.67}, current_price=372.11,
        street_target=396.62, street_count=38, market_implied_path=18.68,
        currency="USD", required_growth=_required(),
    )
    assert view["price_assumes"].startswith("At this price, revenue would have to grow about 30%")
    assert view["price_implied_multiple"] == pytest.approx(19.68)
    fallback = model_view_summary(
        span={"low": 25.67, "high": 25.67}, current_price=372.11,
        market_implied_path=18.68, currency="USD",
    )
    assert fallback["price_assumes"].startswith("The market price assumes about 19.7")


def test_withheld_chat_answer_carries_the_required_growth_sentence():
    from types import SimpleNamespace
    from src.agents.supervisor import supervisor_agent

    runner = supervisor_agent.SupervisorWorkflowRunner.__new__(
        supervisor_agent.SupervisorWorkflowRunner)
    runner.ticker = "TSLA"
    runner.state = SimpleNamespace(
        financial_data=SimpleNamespace(
            key_metrics={"basic_info": {"currency": "USD"}}, raw_data={}
        ),
        news_analysis=None,
        financial_model=SimpleNamespace(
            assumptions={},
            valuation_metrics={
                "perpetual_price": 25.67, "current_price": 372.11,
                "point_estimate_withheld": True,
                "publication_withheld_reason": "model and Street disagree",
                "market_implied_fcf_path_vs_model": 18.68,
                "market_required_revenue_growth": _required(),
            },
        ),
    )
    answer = runner._safe_withheld_valuation_answer()
    assert "revenue would have to grow about 30% a year for 10 years" in answer
    assert "Rating: NOT RATED" in answer


def test_reported_basis_wedge_ignores_a_one_off_tax_charge():
    """Meta-like: a 2025 deferred-tax charge depresses net income, not operations."""
    shares = 2.574e9
    payload = _bridge_payload(
        fy0_revenue=201e9, fy0_ebit=83.3e9, fy0_eps=23.49, fy0_shares=shares,
        year_ago_eps=23.49, eps_0y=30.0, eps_1y=32.0,
        rev_0y=240e9, rev_1y=280e9,
    )
    statement = payload["financial_statements"]["income_statement"]["2025-12-31"]
    statement["Pretax Income"] = 85.6e9
    statement["Net Non Operating Interest Income Expense"] = 0.56e9
    calibration = _year_ago_bridge_calibration(payload, 0.20, 1.0)
    assert calibration["basis"] == "reported"
    # Net interest over revenue: neither the -4% a net-income solve produces
    # nor any untagged investment gain sitting between EBIT and pretax.
    assert calibration["wedge"] == pytest.approx(0.56e9 / 201e9)


def test_a_large_but_real_stock_compensation_wedge_is_accepted():
    """ServiceNow-like: adjusted EPS 2.1x reported is a basis, not an error."""
    payload = _bridge_payload(
        fy0_revenue=13.28e9, fy0_ebit=1.824e9, fy0_eps=1.67, fy0_shares=1.047e9,
        year_ago_eps=3.51, eps_0y=4.1, eps_1y=4.9,
        rev_0y=15.5e9, rev_1y=18.3e9,
    )
    calibration = _year_ago_bridge_calibration(payload, 0.2185, 1.0)
    assert calibration["basis"] == "adjusted"
    assert 0.20 < calibration["wedge"] < 0.35


def test_a_split_sized_eps_mismatch_is_rejected_as_a_data_error():
    payload = _bridge_payload(
        fy0_revenue=100e9, fy0_ebit=20e9, fy0_eps=10.0, fy0_shares=1e9,
        year_ago_eps=1.0, eps_0y=1.2, eps_1y=1.4,
        rev_0y=110e9, rev_1y=120e9,
    )
    assert _year_ago_bridge_calibration(payload, 0.2, 1.0) is None


def test_no_growth_requirement_is_stated_when_growth_destroys_value():
    """Low margin, capital-hungry growth: each new dollar earns below WACC."""
    kwargs = _tesla_like_path()
    revenues = kwargs["revenue_path"]
    previous = [kwargs["base_revenue"]] + revenues[:-1]
    kwargs["nopat_path"] = [r * 0.02 for r in revenues]
    # One dollar of capital per dollar of new revenue at a 2% margin: the
    # incremental return is 2%, far below the 11.6% cost of capital.
    kwargs["fcf_path"] = [r * 0.02 - (r - p) for r, p in zip(revenues, previous)]
    out = implied_revenue_growth_for_enterprise_value(0.5e12, **kwargs)
    assert out["available"] is False
    assert out["model_margin_note"] == "new_capital_return_below_stability_threshold"
    assert required_growth_sentence(out) is None



def test_reported_basis_ignores_untagged_investment_gains():
    """NVIDIA-like: $9B of gains sit between EBIT and pretax with no unusual tag."""
    shares = 24.5e9
    payload = _bridge_payload(
        fy0_revenue=216e9, fy0_ebit=130e9, fy0_eps=4.90, fy0_shares=shares,
        year_ago_eps=4.90, eps_0y=9.3, eps_1y=15.7,
        rev_0y=410e9, rev_1y=680e9,
    )
    statement = payload["financial_statements"]["income_statement"]["2025-12-31"]
    statement["Pretax Income"] = 130e9 + 9e9 + 1.8e9
    statement["Net Non Operating Interest Income Expense"] = 1.8e9
    calibration = _year_ago_bridge_calibration(payload, 0.14, 1.0)
    assert calibration["wedge"] == pytest.approx(1.8e9 / 216e9)


def test_misaligned_fiscal_year_is_not_calibrated():
    """Costco-like: estimates rolled to FY27 while statements still end at FY25."""
    payload = _bridge_payload(
        fy0_revenue=275.2e9, fy0_ebit=10.4e9, fy0_eps=18.2, fy0_shares=0.444e9,
        year_ago_eps=20.76, eps_0y=22.9, eps_1y=25.2,
        rev_0y=330e9, rev_1y=355e9,
    )
    payload["analyst_data"]["revenue_estimates"]["0y"]["yearAgoRevenue"] = 303.15e9
    assert _year_ago_bridge_calibration(payload, 0.25, 1.0) is None


def test_revenue_estimates_on_another_unit_are_rejected_not_clamped():
    """Infosys-like: INR revenue estimates against USD statements and EPS."""
    payload = _bridge_payload(
        fy0_revenue=19.3e9, fy0_ebit=4.0e9, fy0_eps=0.78, fy0_shares=4.15e9,
        year_ago_eps=0.78, eps_0y=0.84, eps_1y=0.92,
        rev_0y=1.95e12, rev_1y=2.10e12,
    )
    assert _street_margin_anchor(payload, None, 0.25, 5) is None


def test_fixed_intangible_amortization_shrinks_as_revenue_grows():
    """Broadcom-like: $8.2B of amortization is 13% of FY0 revenue, ~4% later."""
    shares = 4.85e9
    payload = _bridge_payload(
        fy0_revenue=63.9e9, fy0_ebit=26.1e9, fy0_eps=4.77, fy0_shares=shares,
        year_ago_eps=6.82, eps_0y=10.5, eps_1y=14.0,
        rev_0y=150e9, rev_1y=200e9,
    )
    payload["financial_statements"]["cash_flow"] = {
        "2025-12-31": {"Amortization Of Intangibles": 8.2e9},
    }
    with_fixed = _street_margin_anchor(payload, None, 0.20, 5)
    del payload["financial_statements"]["cash_flow"]
    as_percent = _street_margin_anchor(payload, None, 0.20, 5)
    fixed_margin = with_fixed["rows"][1]["implied_operating_margin"]
    percent_margin = as_percent["rows"][1]["implied_operating_margin"]
    # 8.2/63.9 - 8.2/200 = 8.7 points of margin the percent wedge wrongly charged.
    assert fixed_margin - percent_margin == pytest.approx(8.2 / 63.9 - 8.2 / 200, abs=1e-9)



def test_model_view_states_no_direction_when_the_method_was_ruled_out():
    from src.summary_evidence import unsuitable_method_note
    suitability = {
        "publication_allowed": False,
        "primary_method": "scenario_only_pending_operating_finance_sotp",
        "reason": ("The DCF may be shown as an auditable scenario, but no point "
                   "estimate or directional rating should be published because a "
                   "disclosed captive-finance segment is consolidated with the "
                   "operating business."),
    }
    note = unsuitable_method_note(suitability)
    assert note.startswith("a disclosed captive-finance segment")
    view = model_view_summary(
        span={"low": 40.0, "high": 65.5}, current_price=82.6,
        street_target=104.0, street_count=20, currency="USD", method_note=note,
    )
    assert view["direction"] is None
    assert "states no direction" in view["headline"]
    assert "below the market" not in view["headline"] + view["evidence"]
    # Evidence disagreement (the boundary, not the method) keeps its model view.
    assert unsuitable_method_note({"publication_allowed": True}) is None
    assert unsuitable_method_note({"publication_allowed": False,
                                   "primary_method": "dcf_only"}) is None


def test_converted_year_ago_eps_tolerates_currency_drift():
    """TSMC-like: a 4% FX drift must not flip a reported basis to adjusted."""
    payload = _bridge_payload(
        fy0_revenue=100e9, fy0_ebit=45e9, fy0_eps=10.0, fy0_shares=5e9,
        year_ago_eps=10.4, eps_0y=12.0, eps_1y=14.0,
        rev_0y=120e9, rev_1y=140e9,
    )
    # 3.9% apart after conversion: within the converted band, outside the
    # same-currency band.
    converted = _year_ago_bridge_calibration(payload, 0.15, 0.999)
    assert converted["basis"] == "reported"
    same_currency = _year_ago_bridge_calibration(payload, 0.15, 1.0)
    assert same_currency["basis"] == "adjusted"


def test_current_year_gains_cannot_lift_the_margin_above_trailing_and_next_year(monkeypatch):
    """Amazon-like: a sparse quarterly row leaves this year's gains in the 0y EPS."""
    monkeypatch.setenv("RISK_FREE_USD", "0.04")
    payload = _tesla_like_payload(eps_0y=3.3, eps_1y=2.2)
    fy0 = payload["financial_statements"]["income_statement"]["2025-12-31"]
    fy0.update({"Diluted EPS": 1.0, "Diluted Average Shares": 3.95e9})
    payload["analyst_data"]["earnings_estimates"]["0y"]["yearAgoEps"] = 1.0
    payload["quarterly_financial_statements"] = {"income_statement": {
        "2026-03-31": {"Diluted EPS": 1.1},  # no revenue, no unusual items
    }}
    grounded, _ = ground_assumptions(_base_assumptions(), payload)
    anchor = grounded["margin_anchor"]
    assert anchor["bridge"]["calibration"]["basis"] == "reported"
    assert anchor["bridge"]["calibration"]["current_year_unusual_complete"] is False
    first, second = grounded["operating_margins"][:2]
    trailing = anchor["trailing_operating_margin"]
    assert first <= max(trailing, second) + 0.02 + 1e-12



def _minimal_workbook(year10_label):
    cells = lambda mapping: {"cells": mapping}
    projections = {}
    for column, (revenue, nopat, fcf) in enumerate(
            [(110e9, 22e9, 17e9), (120e9, 24e9, 19e9), (130e9, 26e9, 21e9),
             (139e9, 27.8e9, 23.3e9), (147e9, 29.4e9, 25.4e9)], start=2):
        projections[f"(3, {column})"] = revenue
        projections[f"(11, {column})"] = nopat
        projections[f"(19, {column})"] = fcf
    return {
        "Projections": cells(projections),
        "Valuation (DCF)": cells({"(12, 2)": 0.09, "(23, 2)": 0.025, "(27, 2)": 400e9}),
        "Summary": cells({"(51, 2)": 450e9, "(33, 1)": year10_label, "(33, 2)": 190e9}),
        "Assumptions": cells({"(7, 3)": 0.10}),
        "Model_Inputs": cells({"(11, 2)": 0.20}),
    }


def test_model_growth_only_from_a_year_ten_revenue_cell():
    """Workbooks saved before 2026-09-13 carry FY5 revenue in Summary (33, 2)."""
    from src.external_expectations import required_revenue_growth_from_workbook
    current = required_revenue_growth_from_workbook(_minimal_workbook("Revenue (NTM10)"))
    assert current["model_revenue_growth"] == pytest.approx((190e9 / 100e9) ** 0.1 - 1)
    legacy = required_revenue_growth_from_workbook(_minimal_workbook("Revenue (FY5)"))
    assert "model_revenue_growth" not in legacy
    assert legacy["available"] is True
