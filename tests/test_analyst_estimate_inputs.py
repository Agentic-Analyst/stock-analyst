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


def test_near_term_revenue_consensus_anchors_only_first_two_years(monkeypatch):
    from src.agents.fm.assumption_grounding import ground_assumptions

    monkeypatch.setenv("RISK_FREE_USD", "0.04")
    assumptions = {
        "wacc": 0.09,
        "terminal_growth_rate": 0.025,
        "revenue_growth_rates": [0.043, 0.038, 0.033, 0.029, 0.025],
    }

    grounded, notes = ground_assumptions(assumptions, _grounding_data())

    assert grounded["revenue_growth_rates"] == pytest.approx(
        [0.171, 0.112, 0.033, 0.029, 0.025])
    assert grounded["revenue_growth_source"] == "yahoo_analyst_consensus_near_term"
    assert any("FY1 17.1% (17 analysts)" in note for note in notes)


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
