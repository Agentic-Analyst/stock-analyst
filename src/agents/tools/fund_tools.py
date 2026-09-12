"""Fund-specific research for the generalist agent.

An ETF or mutual fund owns a portfolio; it is not an operating company. This
tool therefore exposes fees, holdings, allocation, portfolio characteristics
and adjusted-price performance, and deliberately has no earnings or DCF path.
"""

from __future__ import annotations

import math
import re
import statistics
from datetime import date, datetime, timezone, timedelta
from typing import Any, Dict, Optional

from .base import Tool, tool_error, tool_ok

_FUND_TYPES = {"ETF", "MUTUALFUND", "MUTUAL FUND"}
_SYMBOL = re.compile(r"^[A-Z0-9][A-Z0-9.:-]{0,31}$")


def _number(value: Any) -> Optional[float]:
    try:
        if value is None or value != value or isinstance(value, bool):
            return None
        out = float(value)
        return out if math.isfinite(out) else None
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> Optional[str]:
    try:
        if value is None or value != value:
            return None
    except (TypeError, ValueError):
        return None
    out = str(value).strip()
    return out or None


def _metric(frame: Any, label: str, symbol: str) -> Dict[str, Optional[float]]:
    try:
        row = frame.loc[label]
        return {"fund": _number(row.get(symbol)),
                "category": _number(row.get("Category Average"))}
    except Exception:
        return {"fund": None, "category": None}


def _weighted(values: Any) -> Dict[str, float]:
    if not isinstance(values, dict):
        return {}
    return {str(key): number for key, value in values.items()
            if (number := _number(value)) is not None and number >= 0}


def _fund_market_snapshot(info: Dict[str, Any]) -> Dict[str, Any]:
    market_price = _number(info.get("regularMarketPrice") or info.get("currentPrice"))
    nav = _number(info.get("navPrice"))
    inception = _number(info.get("fundInceptionDate"))
    return {
        "market_price": market_price,
        "nav": nav,
        "premium_discount_to_nav": (
            market_price / nav - 1.0 if market_price is not None and nav and nav > 0 else None
        ),
        "total_assets": _number(info.get("totalAssets")),
        "yield": _number(info.get("yield") or info.get("dividendYield")),
        "inception_date": (
            datetime.fromtimestamp(inception, tz=timezone.utc).date().isoformat()
            if inception is not None and inception > 0 else None
        ),
    }


def _top_holdings(frame: Any) -> list[dict]:
    if frame is None or getattr(frame, "empty", True):
        return []
    out = []
    for symbol, row in frame.head(25).iterrows():
        weight = _number(row.get("Holding Percent"))
        name = _text(row.get("Name"))
        if weight is None or weight < 0 or not name:
            continue
        out.append({"symbol": str(symbol).upper(), "name": name, "weight": weight})
    return out


def _performance(frame: Any) -> Dict[str, Any]:
    empty = {
        "as_of": None,
        "returns": {key: None for key in ("one_month", "three_month", "ytd",
                                            "one_year", "three_year", "five_year")},
        "annualized_volatility_one_year": None,
        "max_drawdown_one_year": None,
        "basis": "adjusted_close",
    }
    if frame is None or getattr(frame, "empty", True) or "Close" not in frame:
        return empty
    points = []
    for index, raw in frame["Close"].items():
        value = _number(raw)
        try:
            when = index.date() if hasattr(index, "date") else date.fromisoformat(str(index)[:10])
        except ValueError:
            continue
        if value is not None and value > 0:
            points.append((when, value))
    points = sorted(dict(points).items())
    if len(points) < 2:
        return empty

    end = points[-1][0]

    def since(start: date) -> Optional[float]:
        if points[0][0] > start + timedelta(days=10):
            return None
        first = next(((when, value) for when, value in points if when >= start), None)
        if first is None or first[0] > start + timedelta(days=10) or first[0] >= end:
            return None
        return points[-1][1] / first[1] - 1.0

    starts = {
        "one_month": end - timedelta(days=30),
        "three_month": end - timedelta(days=91),
        "ytd": date(end.year, 1, 1),
        "one_year": end - timedelta(days=365),
        "three_year": end - timedelta(days=365 * 3),
        "five_year": end - timedelta(days=365 * 5),
    }
    one_year = [(when, value) for when, value in points
                if when >= end - timedelta(days=365)]
    full_year = bool(one_year) and one_year[0][0] <= end - timedelta(days=355)
    daily = ([current / previous - 1.0
              for (_, previous), (_, current) in zip(one_year, one_year[1:])]
             if full_year else [])
    volatility = statistics.stdev(daily) * math.sqrt(252) if len(daily) >= 30 else None
    drawdown = None
    if full_year:
        peak = 0.0
        drawdown = 0.0
        for _, value in one_year:
            peak = max(peak, value)
            if peak:
                drawdown = min(drawdown, value / peak - 1.0)

    return {
        "as_of": end.isoformat(),
        "returns": {key: since(start) for key, start in starts.items()},
        "annualized_volatility_one_year": volatility,
        "max_drawdown_one_year": drawdown,
        "basis": "adjusted_close",
    }


class GetFundTool(Tool):
    name = "get_fund"
    description = (
        "Get fund-specific research for an ETF or mutual fund: category and family, "
        "expense ratio and turnover versus category, asset/sector allocation, top "
        "holdings, portfolio valuation characteristics, and adjusted-price returns "
        "and risk. Use this for VOO, SPY, QQQ and any fund question. A fund is not an "
        "operating company: never call get_financials, build_model, compare_tickers, "
        "or write_report for it, and never invent a benchmark from its category."
    )
    parameters = {
        "type": "object",
        "properties": {
            "ticker": {"type": "string", "description": "Fund ticker, e.g. VOO or QQQ."},
        },
        "required": ["ticker"],
    }

    async def execute(self, ticker: str) -> str:
        import asyncio

        symbol = str(ticker or "").strip().upper()
        if not _SYMBOL.fullmatch(symbol):
            return tool_error("Pass a valid ETF or mutual-fund ticker.", ticker=symbol)

        def snapshot() -> Dict[str, Any]:
            from .yf_resilience import fetch_history

            import yfinance as yf

            instrument = yf.Ticker(symbol)
            info = instrument.info or {}
            quote_type = str(info.get("quoteType") or "").strip().upper()
            if quote_type not in _FUND_TYPES:
                return {"wrong_type": quote_type or "unknown"}

            detail: Dict[str, Any] = {}
            try:
                fund = instrument.funds_data
                overview = fund.fund_overview or {}
                detail = {
                    "description": _text(fund.description),
                    "category": overview.get("categoryName"),
                    "family": overview.get("family"),
                    "legal_type": overview.get("legalType"),
                    "operations": {
                        "expense_ratio": _metric(fund.fund_operations,
                                                  "Annual Report Expense Ratio", symbol),
                        "turnover": _metric(fund.fund_operations,
                                            "Annual Holdings Turnover", symbol),
                        "total_net_assets": _metric(fund.fund_operations,
                                                    "Total Net Assets", symbol),
                    },
                    "asset_classes": _weighted(fund.asset_classes),
                    "top_holdings": _top_holdings(fund.top_holdings),
                    "holdings_provenance": {
                        "source": "yahoo_finance",
                        "as_of": None,
                        "note": "The upstream response does not expose a holdings as-of date.",
                    },
                    "sector_weightings": _weighted(fund.sector_weightings),
                    "bond_ratings": _weighted(fund.bond_ratings),
                    "equity_characteristics": {
                        key: _metric(fund.equity_holdings, label, symbol)
                        for key, label in {
                            "price_to_earnings": "Price/Earnings",
                            "price_to_book": "Price/Book",
                            "price_to_sales": "Price/Sales",
                            "price_to_cashflow": "Price/Cashflow",
                            "median_market_cap": "Median Market Cap",
                            "three_year_earnings_growth": "3 Year Earnings Growth",
                        }.items()
                    },
                    "bond_characteristics": {
                        key: _metric(fund.bond_holdings, label, symbol)
                        for key, label in {
                            "duration": "Duration", "maturity": "Maturity",
                            "credit_quality": "Credit Quality",
                        }.items()
                    },
                }
            except Exception as exc:
                detail = {"fund_data_error": str(exc)[:200]}

            history = fetch_history(symbol, "5y", attempts=2,
                                    auto_adjust=True, actions=False)
            detail["performance"] = _performance(history)
            return {
                "name": info.get("longName") or info.get("shortName"),
                "currency": info.get("currency"),
                "quote_type": quote_type,
                "market_snapshot": _fund_market_snapshot(info),
                **detail,
            }

        data = await asyncio.to_thread(snapshot)
        if data.get("wrong_type"):
            return tool_error(
                f"{symbol} is {data['wrong_type']}, not an ETF or mutual fund. "
                "Use the asset-specific tool for that instrument.",
                ticker=symbol, quote_type=data["wrong_type"],
            )
        return tool_ok(
            asset_class="fund",
            symbol=symbol,
            methodology={
                "ratios_weights_and_returns": "fractions",
                "performance_basis": "adjusted_close",
                "benchmark": None,
                "nav_premium_discount": "market_price_divided_by_nav_minus_one",
            },
            note=("Fund portfolio analytics; no issuer DCF applies. Holdings are the top "
                  "positions reported by the source. No benchmark, tracking error, or "
                  "relative return is claimed without a verified benchmark identity."),
            **data,
        )


def build_fund_tools():
    return [GetFundTool()]
