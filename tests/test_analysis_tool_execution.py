"""Execution-level contracts for the public analysis tools.

These tests intentionally call the tools.  Source-inspection assertions did not
catch a production-breaking wiring error where ``get_financials`` referenced a
report-only variable and ``write_report`` returned another undefined variable.
"""

import asyncio
import importlib
import json
from types import SimpleNamespace

from src.agents.supervisor.state import (
    FinancialData,
    FinancialModel,
    FinancialState,
    NewsAnalysis,
    Report,
)
from src.agents.tools.analysis_tools import GetFinancialsTool, WriteReportTool


def _state() -> FinancialState:
    return FinancialState(
        user_query="Analyze AAPL",
        ticker="AAPL",
        company_name="Apple Inc.",
        email="test@example.com",
        timestamp="20260912_120000",
    )


def _context(state: FinancialState):
    return SimpleNamespace(
        state=state,
        user_prompt=state.user_query,
        ensure_state_for_ticker=lambda ticker: state,
    )


def test_get_financials_executes_without_report_state(monkeypatch):
    """Collecting financials must not depend on a model, report, or gate."""
    state = _state()

    async def fake_financial_data_agent(incoming):
        incoming.financial_data = FinancialData(
            ticker="AAPL",
            company_name="Apple Inc.",
            key_metrics={
                "basic_info": {
                    "currency": "USD",
                    "sector": "Technology",
                    "industry": "Consumer Electronics",
                },
                "market_data": {
                    "current_price": 250.0,
                    "market_cap": 3.7e12,
                    "trailing_pe": 34.0,
                },
            },
        )
        return incoming

    module = importlib.import_module(
        "src.agents.supervisor.task_agents.financial_data_agent"
    )
    monkeypatch.setattr(module, "financial_data_agent", fake_financial_data_agent)

    payload = json.loads(asyncio.run(GetFinancialsTool(_context(state)).execute("AAPL")))

    assert payload["status"] == "ok"
    assert payload["ticker"] == "AAPL"
    assert payload["current_price"] == 250.0
    assert state.report is None
    assert state.financial_model is None


def test_write_report_executes_and_machine_gate_bounds_markdown(monkeypatch):
    """A stale SELL heading cannot escape when the model withholds publication."""
    state = _state()
    state.financial_data = FinancialData(
        ticker="AAPL",
        company_name="Apple Inc.",
        key_metrics={
            "basic_info": {"currency": "USD", "listing_currency": "USD"},
            "market_data": {"current_price": 250.0, "market_cap": 3.7e12},
        },
        raw_data={"external_expectations": {}},
    )
    state.financial_model = FinancialModel(
        ticker="AAPL",
        valuation_metrics={
            "valuation_method": "dcf",
            "fair_value": 100.0,
            "upside_vs_market": -0.60,
            "perpetual_price": 90.0,
            "exit_multiple_price": 110.0,
            "comps_included_in_blended_value": False,
            "point_estimate_withheld": True,
            "publication_withheld_reason": "Independent evidence conflicts with the DCF.",
        },
        assumptions={},
    )
    state.news_analysis = NewsAnalysis(
        ticker="AAPL",
        articles_count=1,
        overall_sentiment="bearish",
        freshness={"status": "fresh"},
    )
    state.report = Report(
        ticker="AAPL",
        report_path="/tmp/AAPL_Report.md",
        content=(
            "### Investment Rating: SELL\n\n"
            "**12-Month Price Target**: $180.00\n"
            "**Expected Return**: -28.0%\n"
        ),
    )

    async def fake_report_generator_agent(incoming):
        return incoming

    module = importlib.import_module(
        "src.agents.supervisor.task_agents.report_generator_agent"
    )
    monkeypatch.setattr(module, "report_generator_agent", fake_report_generator_agent)

    payload = json.loads(asyncio.run(WriteReportTool(_context(state)).execute("AAPL")))

    assert payload["status"] == "ok"
    assert payload["fair_value"] is None
    assert payload["fair_value_withheld"] is True
    assert payload["rating"] == "NOT RATED"
    assert "price_target_12m" not in payload
    assert "price_target_expected_return_pct" not in payload
