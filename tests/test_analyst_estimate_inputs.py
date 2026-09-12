import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from financial_scraper import FinancialScraper, _frame_records


def test_frame_records_preserves_periods_and_is_json_safe():
    frame = pd.DataFrame(
        {
            "avg": [np.float64(10.5), np.float64(11.0)],
            "numberOfAnalysts": [np.int64(17), np.int64(16)],
            "growth": [np.float64(0.171), np.nan],
        },
        index=["0y", "+1y"],
    )

    records = _frame_records(frame)

    assert records["0y"] == {
        "avg": 10.5,
        "numberOfAnalysts": 17,
        "growth": pytest.approx(0.171),
    }
    assert "growth" not in records["+1y"]
    json.dumps(records)


def test_current_yahoo_estimate_schema_is_saved_in_separate_tables():
    class YahooTicker:
        recommendations = pd.DataFrame(
            {"strongBuy": [8], "buy": [20], "hold": [12], "sell": [2], "strongSell": [1]},
            index=["0m"],
        )
        earnings_estimate = pd.DataFrame(
            {"avg": [12.50], "numberOfAnalysts": [17], "growth": [0.20]},
            index=["0y"],
        )
        revenue_estimate = pd.DataFrame(
            {
                "avg": [7.5e10, 8.3e10],
                "numberOfAnalysts": [17, 16],
                "growth": [0.171, 0.112],
            },
            index=["0y", "+1y"],
        )
        growth_estimates = pd.DataFrame(
            {"stock": [0.20], "industry": [0.10]}, index=["+5y"])
        calendar = {"Earnings Date": pd.Timestamp("2026-10-28")}

    scraper = FinancialScraper.__new__(FinancialScraper)
    scraper.ticker = "CAT"
    scraper.yf_ticker = YahooTicker()
    scraper._log = lambda *_args, **_kwargs: None

    result = scraper.scrape_analyst_estimates()

    assert result["recommendations"]["0m"]["strongBuy"] == 8
    assert result["earnings_estimates"]["0y"]["growth"] == pytest.approx(0.20)
    assert result["revenue_estimates"]["0y"]["numberOfAnalysts"] == 17
    assert result["revenue_estimates"]["+1y"]["growth"] == pytest.approx(0.112)
    assert result["growth_estimates"]["+5y"]["industry"] == pytest.approx(0.10)
    assert result["earnings_calendar"]["calendar"]["Earnings Date"].startswith("2026-10-28")
    json.dumps(result)


def _grounding_data(*, analyst_count=17):
    return {
        "company_data": {
            "basic_info": {"currency": "USD", "country": "United States"},
            "capital_structure": {"beta": 1.0, "total_debt": 0},
            "market_data": {"market_cap": 1e9},
            "growth_profitability": {},
            "valuation_metrics": {},
        },
        "analyst_data": {
            "revenue_estimates": {
                "0y": {"growth": 0.171, "numberOfAnalysts": analyst_count},
                "+1y": {"growth": 0.112, "numberOfAnalysts": analyst_count},
            }
        },
    }


def test_revenue_consensus_anchors_near_term_and_fades_deterministically(monkeypatch):
    from src.agents.fm.assumption_grounding import ground_assumptions

    monkeypatch.setenv("RISK_FREE_USD", "0.04")
    assumptions = {
        "wacc": 0.09,
        "terminal_growth_rate": 0.025,
        "revenue_growth_rates": [0.043, 0.038, 0.033, 0.029, 0.025],
    }

    grounded, notes = ground_assumptions(assumptions, _grounding_data())

    assert grounded["revenue_growth_rates"] == pytest.approx(
        [0.171, 0.112, 0.08329, 0.0598, 0.0424])
    assert grounded["revenue_growth_source"] == "yahoo_analyst_consensus_with_deterministic_fade"
    assert any("FY1 17.1% (17 analysts)" in note for note in notes)


def test_different_llm_long_range_guesses_produce_the_same_grounded_curve(monkeypatch):
    from src.agents.fm.assumption_grounding import ground_assumptions

    monkeypatch.setenv("RISK_FREE_USD", "0.04")
    first, _ = ground_assumptions({
        "wacc": 0.09, "terminal_growth_rate": 0.025,
        "revenue_growth_rates": [0.04, 0.04, 0.20, 0.15, 0.10],
    }, _grounding_data())
    second, _ = ground_assumptions({
        "wacc": 0.12, "terminal_growth_rate": 0.025,
        "revenue_growth_rates": [0.01, 0.01, -0.10, -0.05, 0.00],
    }, _grounding_data())

    assert first["revenue_growth_rates"] == pytest.approx(second["revenue_growth_rates"])


def test_terminal_growth_is_deterministic_inside_the_old_llm_band(monkeypatch):
    from src.agents.fm.assumption_grounding import ground_assumptions

    monkeypatch.setenv("RISK_FREE_USD", "0.04")
    low, _ = ground_assumptions({
        "wacc": 0.09, "terminal_growth_rate": 0.02,
        "revenue_growth_rates": [0.04] * 5,
    }, _grounding_data())
    high, _ = ground_assumptions({
        "wacc": 0.09, "terminal_growth_rate": 0.03,
        "revenue_growth_rates": [0.04] * 5,
    }, _grounding_data())

    assert low["terminal_growth_rate"] == pytest.approx(0.025)
    assert high["terminal_growth_rate"] == pytest.approx(0.025)
    assert low["terminal_growth_note"].startswith("deterministic 2.50%")


def test_established_company_margins_and_working_capital_are_reproducible(monkeypatch):
    from src.agents.fm.assumption_grounding import ground_assumptions

    monkeypatch.setenv("RISK_FREE_USD", "0.04")
    data = _grounding_data()
    data["company_data"]["growth_profitability"] = {
        "operating_margins": 0.32,
        "ebitda_margins": 0.35,
        "gross_margins": 0.48,
    }
    data["financial_statements"] = {
        "income_statement": {
            "2025": {"Total Revenue": 1000, "Gross Profit": 470, "EBITDA": 340,
                     "Operating Income": 310, "Cost Of Revenue": 530},
            "2024": {"Total Revenue": 900, "Gross Profit": 414, "EBITDA": 297,
                     "Operating Income": 270, "Cost Of Revenue": 486},
            "2023": {"Total Revenue": 800, "Gross Profit": 352, "EBITDA": 256,
                     "Operating Income": 232, "Cost Of Revenue": 448},
        },
        "balance_sheet": {
            "2025": {"Accounts Receivable": 100, "Inventory": 53, "Accounts Payable": 80},
            "2024": {"Accounts Receivable": 81, "Inventory": 49, "Accounts Payable": 73},
            "2023": {"Accounts Receivable": 64, "Inventory": 45, "Accounts Payable": 67},
        },
    }
    base = {"wacc": 0.09, "terminal_growth_rate": 0.025,
            "revenue_growth_rates": [0.1] * 5}
    optimistic, _ = ground_assumptions({
        **base, "gross_margins": [0.60] * 5, "ebitda_margins": [0.50] * 5,
        "operating_margins": [0.45] * 5, "dso_days": [10] * 5,
        "dio_days": [5] * 5, "dpo_days": [200] * 5,
    }, data)
    pessimistic, _ = ground_assumptions({
        **base, "gross_margins": [0.35] * 5, "ebitda_margins": [0.20] * 5,
        "operating_margins": [0.10] * 5, "dso_days": [100] * 5,
        "dio_days": [80] * 5, "dpo_days": [10] * 5,
    }, data)

    for key in ("gross_margins", "ebitda_margins", "operating_margins",
                "dso_days", "dio_days", "dpo_days"):
        assert optimistic[key] == pytest.approx(pessimistic[key])
    assert optimistic["operating_margins"][0] == pytest.approx(0.32)
    assert optimistic["working_capital_source"] == "latest_actual_to_three_year_median"


def test_reported_margins_ground_a_mature_company_when_trailing_ratios_are_missing(monkeypatch):
    from src.agents.fm.assumption_grounding import ground_assumptions

    monkeypatch.setenv("RISK_FREE_USD", "0.04")
    data = _grounding_data()
    data["financial_statements"] = {
        "income_statement": {
            "2025": {"Total Revenue": 1000, "Gross Profit": 470, "EBITDA": 340,
                     "Operating Income": 310},
            "2024": {"Total Revenue": 900, "Gross Profit": 414, "EBITDA": 297,
                     "Operating Income": 270},
            "2023": {"Total Revenue": 800, "Gross Profit": 352, "EBITDA": 256,
                     "Operating Income": 232},
        },
    }
    grounded, _ = ground_assumptions({
        "wacc": 0.09, "terminal_growth_rate": 0.03,
        "revenue_growth_rates": [0.04] * 5,
        "gross_margins": [0.10] * 5,
        "ebitda_margins": [0.10] * 5,
        "operating_margins": [0.10] * 5,
    }, data)

    assert grounded["operating_margins"][0] == pytest.approx(0.31)
    assert grounded["ebitda_margins"][0] == pytest.approx(0.34)
    assert grounded["gross_margins"][0] == pytest.approx(0.47)


def test_thin_or_implausible_consensus_does_not_override_the_model(monkeypatch):
    from src.agents.fm.assumption_grounding import ground_assumptions

    monkeypatch.setenv("RISK_FREE_USD", "0.04")
    assumptions = {
        "wacc": 0.09,
        "terminal_growth_rate": 0.025,
        "revenue_growth_rates": [0.04, 0.035, 0.03, 0.027, 0.025],
    }
    data = _grounding_data(analyst_count=2)
    data["analyst_data"]["revenue_estimates"]["+1y"] = {
        "growth": 1.5, "numberOfAnalysts": 20}

    grounded, _ = ground_assumptions(assumptions, data)

    assert grounded["revenue_growth_rates"] == assumptions["revenue_growth_rates"]
    assert "revenue_growth_source" not in grounded
