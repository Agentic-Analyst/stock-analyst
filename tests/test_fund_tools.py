import asyncio
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

pd = pytest.importorskip("pandas")

from agents.tools.analysis_tools import CompareTickersTool
from agents.tools.fund_tools import GetFundTool, _performance
from agents.supervisor.state import AnalysisObjective, FinancialState, PipelineStage


def history(days=400):
    start = datetime(2025, 1, 1)
    index = [start + timedelta(days=i) for i in range(days)]
    return pd.DataFrame({"Close": [100 + i / 10 for i in range(days)]}, index=index)


class Funds:
    description = "Tracks a broad US equity index."
    fund_overview = {
        "categoryName": "Large Blend", "family": "Vanguard",
        "legalType": "Exchange Traded Fund",
    }
    fund_operations = pd.DataFrame({
        "VOO": [0.0003, 0.025, 1.2e12],
        "Category Average": [0.0075, 0.21, 8e9],
    }, index=["Annual Report Expense Ratio", "Annual Holdings Turnover",
              "Total Net Assets"])
    asset_classes = {"stockPosition": 0.998, "cashPosition": 0.002}
    top_holdings = pd.DataFrame({
        "Name": ["Apple Inc.", "Microsoft Corp."],
        "Holding Percent": [0.071, 0.062],
    }, index=["AAPL", "MSFT"])
    sector_weightings = {"technology": 0.31}
    bond_ratings = {}
    equity_holdings = pd.DataFrame({
        "VOO": [27.2, 5.1], "Category Average": [25.1, 4.8],
    }, index=["Price/Earnings", "Price/Book"])
    bond_holdings = pd.DataFrame()


class Ticker:
    info = {"quoteType": "ETF", "longName": "Vanguard S&P 500 ETF",
            "currency": "USD"}
    funds_data = Funds()


def test_get_fund_returns_portfolio_data_and_never_a_company_valuation(monkeypatch):
    import yfinance as yf
    from agents.tools import yf_resilience

    monkeypatch.setattr(yf, "Ticker", lambda _symbol: Ticker())
    monkeypatch.setattr(yf_resilience, "fetch_history", lambda *args, **kwargs: history())
    result = json.loads(asyncio.run(GetFundTool().execute("voo")))
    assert result["status"] == "ok" and result["asset_class"] == "fund"
    assert result["operations"]["expense_ratio"] == {
        "fund": 0.0003, "category": 0.0075,
    }
    assert result["top_holdings"][0] == {
        "symbol": "AAPL", "name": "Apple Inc.", "weight": 0.071,
    }
    assert result["performance"]["returns"]["one_year"] is not None
    assert result["methodology"]["benchmark"] is None
    assert "no issuer DCF" in result["note"]


def test_get_fund_rejects_an_equity_instead_of_falling_into_a_dcf(monkeypatch):
    import yfinance as yf

    class Equity:
        info = {"quoteType": "EQUITY"}

    monkeypatch.setattr(yf, "Ticker", lambda _symbol: Equity())
    result = json.loads(asyncio.run(GetFundTool().execute("AAPL")))
    assert result["status"] == "error" and result["quote_type"] == "EQUITY"


def test_fund_risk_is_absent_when_history_does_not_cover_a_year():
    result = _performance(history(20))
    assert result["returns"]["one_year"] is None
    assert result["annualized_volatility_one_year"] is None
    assert result["max_drawdown_one_year"] is None

    sparse = pd.DataFrame({"Close": [90, 100, 110]}, index=[
        datetime(2024, 1, 1), datetime(2025, 8, 1), datetime(2026, 1, 1),
    ])
    assert _performance(sparse)["returns"]["one_year"] is None


def test_invalid_fund_symbol_is_rejected_before_vendor_code(monkeypatch):
    result = json.loads(asyncio.run(GetFundTool().execute("../VOO")))
    assert result["status"] == "error"


def test_company_financial_pipeline_hard_rejects_a_fund(monkeypatch, tmp_path):
    import importlib

    module = importlib.import_module(
        "agents.supervisor.task_agents.financial_data_agent"
    )

    class FundScraper:
        def __init__(self, _ticker, _path):
            self.yf_ticker = type("FundTicker", (), {
                "info": {"quoteType": "ETF"},
            })()

    monkeypatch.setattr(module, "FinancialScraper", FundScraper)
    state = FinancialState(
        user_query="analyze VOO", ticker="VOO", company_name="VOO",
        email="test@example.com", timestamp="2026-09-10",
        objective=AnalysisObjective.COMPREHENSIVE, analysis_path=str(tmp_path),
    )
    result = asyncio.run(module.financial_data_agent(state))
    assert result.current_stage == PipelineStage.FAILED
    assert result.financial_data is None
    assert "issuer financials and DCF are disabled" in (result.last_error or "")


def test_company_comparison_rejects_funds_instead_of_showing_fake_fundamentals(monkeypatch):
    import yfinance as yf

    class Instrument:
        def __init__(self, symbol):
            self.info = ({"quoteType": "ETF", "regularMarketPrice": 500}
                         if symbol == "VOO" else
                         {"quoteType": "EQUITY", "regularMarketPrice": 200,
                          "longName": "Apple Inc."})

    monkeypatch.setattr(yf, "Ticker", Instrument)
    result = json.loads(asyncio.run(
        CompareTickersTool(None).execute(["VOO", "AAPL"])
    ))
    fund = next(row for row in result["comparison"] if row["ticker"] == "VOO")
    assert "not an operating company" in fund["error"]
    assert "trailing_pe" not in fund
