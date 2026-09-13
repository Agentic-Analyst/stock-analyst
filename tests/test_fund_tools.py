import asyncio
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

pd = pytest.importorskip("pandas")

from agents.tools.analysis_tools import CompareTickersTool
from agents.tools.fund_tools import (
    GetFundTool, _fund_market_snapshot, _performance, _weighted,
)
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
        "VOO": [0.0003, 0.025, 1.2e6],
        "Category Average": [0.0075, 0.21, 8e3],
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
        "VOO": [1 / 27.2, 1 / 5.1],
        "Category Average": [1 / 25.1, 1 / 4.8],
    }, index=["Price/Earnings", "Price/Book"])
    bond_holdings = pd.DataFrame()


class BondFunds(Funds):
    top_holdings = pd.DataFrame()
    bond_ratings = {
        "aa": 0.72, "a": 0.16, "bbb": 0.12,
        "bb": 0.0, "us_government": 0.52,
    }
    bond_holdings = pd.DataFrame({
        "BND": [6.1, 9.325, None],
        "Category Average": [5.8, None, None],
    }, index=["Duration", "Maturity", "Credit Quality"])


class Ticker:
    info = {"quoteType": "ETF", "longName": "Vanguard S&P 500 ETF",
            "currency": "USD", "regularMarketPrice": 505.0, "navPrice": 500.0,
            "regularMarketTime": 1789131600,
            "totalAssets": 1.2e12, "yield": 0.012,
            "fundInceptionDate": 1285804800}
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
    assert result["operations"]["total_net_assets"] == {
        "fund": 1.2e12, "category": 8e9,
        "unit": "currency_absolute", "source_unit": "currency_millions",
        "status": "reported_scope_unverified",
    }
    assert result["equity_characteristics"]["price_to_earnings"]["fund"] == pytest.approx(27.2)
    assert result["top_holdings"][0] == {
        "symbol": "AAPL", "name": "Apple Inc.", "weight": 0.071,
    }
    assert result["performance"]["returns"]["one_year"] is not None
    assert result["market_snapshot"]["premium_discount_to_nav"] is None
    assert result["market_snapshot"]["nav_as_of"] is None
    assert result["market_snapshot"]["premium_discount_status"] == (
        "unavailable_without_aligned_as_of"
    )
    assert result["market_snapshot"]["market_price_as_of"] is not None
    assert result["market_snapshot"]["total_assets"] == 1.2e12
    assert result["market_snapshot"]["total_assets_scope"] == (
        "provider_reported_scope_unspecified"
    )
    assert result["holdings_provenance"]["as_of"] is None
    assert result["methodology"]["benchmark"] is None
    assert result["data_status"] == "complete"
    assert result["capabilities"]["verified_benchmark"] is False
    assert "no issuer DCF" in result["note"]


def test_zero_fund_assets_are_missing_not_a_real_zero_aum():
    class ZeroAssets(Funds):
        fund_operations = pd.DataFrame({
            "VOO": [0.0003, 0.025, 0.0],
            "Category Average": [0.0075, 0.21, 0.0],
        }, index=["Annual Report Expense Ratio", "Annual Holdings Turnover",
                  "Total Net Assets"])

    class ZeroTicker(Ticker):
        funds_data = ZeroAssets()

    from agents.tools.fund_tools import _net_assets_metric

    assert _net_assets_metric(ZeroTicker.funds_data.fund_operations, "VOO") == {
        "fund": None,
        "category": None,
        "unit": "currency_absolute",
        "source_unit": "currency_millions",
        "status": "unavailable",
    }


def test_duplicated_fund_and_category_assets_are_suppressed():
    from agents.tools.fund_tools import _net_assets_metric

    frame = pd.DataFrame({"VOO": [496754.28],
                          "Category Average": [496754.28]},
                         index=["Total Net Assets"])
    assert _net_assets_metric(frame, "VOO") == {
        "fund": None,
        "category": None,
        "unit": "currency_absolute",
        "source_unit": "currency_millions",
        "status": "suppressed_provider_scope_anomaly",
    }


def test_missing_top_holdings_is_an_explicit_partial_profile(monkeypatch):
    import yfinance as yf
    from agents.tools import yf_resilience

    class NoHoldings(Funds):
        top_holdings = pd.DataFrame()

    class NoHoldingsTicker(Ticker):
        funds_data = NoHoldings()

    monkeypatch.setattr(yf, "Ticker", lambda _symbol: NoHoldingsTicker())
    monkeypatch.setattr(yf_resilience, "fetch_history", lambda *args, **kwargs: history())

    result = json.loads(asyncio.run(GetFundTool().execute("BND")))

    assert result["data_status"] == "partial"
    assert result["partial_reasons"] == ["top_holdings_unavailable"]


def test_bond_rating_overlay_is_separate_and_characteristic_units_are_explicit(
        monkeypatch):
    import yfinance as yf
    from agents.tools import yf_resilience

    class BondTicker(Ticker):
        info = {**Ticker.info, "longName": "Vanguard Total Bond Market ETF"}
        funds_data = BondFunds()

    monkeypatch.setattr(yf, "Ticker", lambda _symbol: BondTicker())
    monkeypatch.setattr(yf_resilience, "fetch_history", lambda *args, **kwargs: history())

    result = json.loads(asyncio.run(GetFundTool().execute("BND")))

    assert sum(result["bond_ratings"].values()) == pytest.approx(1.0)
    assert result["bond_exposures"] == {"us_government": 0.52}
    assert result["bond_characteristics"]["duration"] == {
        "fund": 6.1, "category": 5.8, "unit": "years", "source_unit": "years",
    }
    assert result["bond_characteristics"]["maturity"]["unit"] == "years"


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


def test_invalid_fractional_weights_are_dropped_instead_of_mixing_units():
    assert _weighted({"valid": 0.4, "percent_unit": 40, "negative": -0.1}) == {
        "valid": 0.4,
    }
    assert _weighted({"zero": 0, "real": 0.4}, include_zero=False) == {
        "real": 0.4,
    }


def test_malformed_provider_epochs_do_not_abort_or_create_impossible_dates():
    snapshot = _fund_market_snapshot({
        "regularMarketPrice": 100,
        "regularMarketTime": 10**40,
        "fundInceptionDate": -1,
    })
    assert snapshot["market_price"] == 100
    assert snapshot["market_price_as_of"] is None
    assert snapshot["inception_date"] is None


def test_fund_detail_failure_is_explicit_partial_without_raw_vendor_error(monkeypatch):
    import yfinance as yf
    from agents.tools import yf_resilience

    class PartialTicker:
        info = Ticker.info

        @property
        def funds_data(self):
            raise RuntimeError("secret vendor implementation detail")

    monkeypatch.setattr(yf, "Ticker", lambda _symbol: PartialTicker())
    monkeypatch.setattr(yf_resilience, "fetch_history", lambda *args, **kwargs: history())
    result = json.loads(asyncio.run(GetFundTool().execute("VOO")))
    assert result["status"] == "ok" and result["data_status"] == "partial"
    assert result["partial_reasons"] == ["portfolio_detail_unavailable"]
    assert "fund_data_error" not in result
    assert "secret vendor" not in json.dumps(result)


def test_fund_metadata_failure_returns_a_safe_tool_error(monkeypatch):
    import yfinance as yf

    class BrokenTicker:
        @property
        def info(self):
            raise RuntimeError("secret Yahoo cookie detail")

    monkeypatch.setattr(yf, "Ticker", lambda _symbol: BrokenTicker())

    result = json.loads(asyncio.run(GetFundTool().execute("VOO")))

    assert result["status"] == "error"
    assert result["ticker"] == "VOO"
    assert "unavailable" in result["error"]
    assert "secret Yahoo" not in json.dumps(result)


@pytest.mark.parametrize("quote_type", ["ETF", "CRYPTOCURRENCY"])
def test_company_financial_pipeline_hard_rejects_a_non_equity(
        monkeypatch, tmp_path, quote_type):
    import importlib

    module = importlib.import_module(
        "agents.supervisor.task_agents.financial_data_agent"
    )

    class FundScraper:
        def __init__(self, _ticker, _path):
            self.yf_ticker = type("FundTicker", (), {
                "info": {"quoteType": quote_type},
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
