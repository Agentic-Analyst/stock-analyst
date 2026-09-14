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
# Yahoo emits this as an overlapping exposure: government bonds are already
# represented inside the letter-grade distribution.  It must not be added to
# that mutually exclusive distribution (BND otherwise totals 151.83%).
_BOND_RATING_OVERLAYS = frozenset({"us_government"})


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


def _portfolio_multiple(frame: Any, label: str, symbol: str) -> Dict[str, Optional[float]]:
    """Normalize Yahoo fund valuation fields from yields to multiples.

    Yahoo's ``topHoldings.equityHoldings`` fields are named priceToEarnings,
    priceToBook, etc., but the observed raw values are the reciprocal portfolio
    yields (VOO P/E arrives as 0.03974, i.e. 1 / 25.16). Presenting that raw
    number as 0.04x is economically wrong. Zero is not invertible and remains
    unavailable (common for bond funds).
    """
    raw = _metric(frame, label, symbol)

    def invert(value: Optional[float]) -> Optional[float]:
        if value is None or value <= 0:
            return None
        multiple = 1.0 / value
        return multiple if 0.1 <= multiple <= 500 else None

    return {"fund": invert(raw["fund"]), "category": invert(raw["category"])}


def _bond_characteristics(frame: Any, symbol: str) -> Dict[str, Dict[str, Any]]:
    out = {
        key: _metric(frame, label, symbol)
        for key, label in {
            "duration": "Duration", "maturity": "Maturity",
            "credit_quality": "Credit Quality",
        }.items()
    }
    for key in ("duration", "maturity"):
        out[key].update({"unit": "years", "source_unit": "years"})
    out["credit_quality"].update({
        "unit": "source_reported", "source_unit": "source_reported",
    })
    return out


def _net_assets_metric(frame: Any, symbol: str) -> Dict[str, Any]:
    """Normalize but fail closed on Yahoo's anomalous fund-operations AUM row.

    Live Yahoo responses frequently repeat the fund value *exactly* in the
    ``Category Average`` column and disagree materially with quote-level total
    assets. That is not a defensible category statistic or reconciled share-class
    AUM, so it is suppressed rather than presented as authoritative.
    """
    raw = _metric(frame, "Total Net Assets", symbol)
    fund = raw["fund"] * 1_000_000 if raw["fund"] is not None and raw["fund"] > 0 else None
    category = (raw["category"] * 1_000_000
                if raw["category"] is not None and raw["category"] > 0 else None)
    duplicated = (fund is not None and category is not None and
                  math.isclose(fund, category, rel_tol=1e-12, abs_tol=1.0))
    return {
        "fund": None if duplicated else fund,
        "category": None if duplicated else category,
        "unit": "currency_absolute",
        "source_unit": "currency_millions",
        "status": ("suppressed_provider_scope_anomaly" if duplicated else
                   "reported_scope_unverified" if fund is not None else "unavailable"),
    }


def _weighted(values: Any, *, include_zero: bool = True) -> Dict[str, float]:
    if not isinstance(values, dict):
        return {}
    # Yahoo exposes portfolio weights as fractions. Values above one are not
    # silently interpreted as percentages because that would mix units.
    minimum = 0 if include_zero else 0.0
    return {str(key): number for key, value in values.items()
            if (number := _number(value)) is not None and minimum <= number <= 1
            and (include_zero or number > 0)}


def _provider_epoch(value: Any, *, date_only: bool = False) -> Optional[str]:
    """Normalize a plausible provider epoch without letting bad data abort."""
    stamp = _number(value)
    if stamp is None or stamp <= 0:
        return None
    # Yahoo currently emits seconds. Accept milliseconds defensively, while
    # rejecting ancient sentinels and dates beyond the end of 2100.
    seconds = stamp / 1000.0 if stamp > 100_000_000_000 else stamp
    if not 0 < seconds <= 4_133_980_800:
        return None
    try:
        parsed = datetime.fromtimestamp(seconds, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None
    return parsed.date().isoformat() if date_only else parsed.isoformat()


def _fund_market_snapshot(info: Dict[str, Any]) -> Dict[str, Any]:
    market_price = _number(info.get("regularMarketPrice") or info.get("currentPrice"))
    nav = _number(info.get("navPrice"))
    inception = _number(info.get("fundInceptionDate"))
    market_time = _number(info.get("regularMarketTime"))
    return {
        "market_price": market_price,
        "market_price_as_of": _provider_epoch(market_time),
        "nav": nav,
        "nav_as_of": None,
        # Yahoo exposes no NAV timestamp on this surface. Dividing a live or
        # prior-close market price by an undated NAV created implausible ETF
        # premiums in live testing, so the derived value must fail closed.
        "premium_discount_to_nav": None,
        "premium_discount_status": "unavailable_without_aligned_as_of",
        # Kept for compatibility, but the adjacent scope/status is mandatory
        # context: Yahoo does not identify whether this is the ETF share class,
        # all classes of a pooled fund, or another aggregation.
        "total_assets": _number(info.get("totalAssets")),
        "total_assets_scope": "provider_reported_scope_unspecified",
        "total_assets_status": "unreconciled",
        "yield": _number(info.get("yield") or info.get("dividendYield")),
        "inception_date": _provider_epoch(inception, date_only=True),
    }


def _top_holdings(frame: Any) -> list[dict]:
    if frame is None or getattr(frame, "empty", True):
        return []
    out = []
    for symbol, row in frame.head(25).iterrows():
        weight = _number(row.get("Holding Percent"))
        name = _text(row.get("Name"))
        if weight is None or not 0 <= weight <= 1 or not name:
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
            partial_reasons = []
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
                        "total_net_assets": _net_assets_metric(
                            fund.fund_operations, symbol),
                    },
                    "asset_classes": _weighted(fund.asset_classes),
                    "top_holdings": _top_holdings(fund.top_holdings),
                    "holdings_provenance": {
                        "source": "yahoo_finance",
                        "as_of": None,
                        "note": "The upstream response does not expose a holdings as-of date.",
                    },
                    "sector_weightings": _weighted(
                        fund.sector_weightings, include_zero=False),
                    "bond_ratings": {
                        key: value for key, value in _weighted(
                            fund.bond_ratings, include_zero=False
                        ).items() if key not in _BOND_RATING_OVERLAYS
                    },
                    "bond_exposures": {
                        key: value for key, value in _weighted(
                            fund.bond_ratings, include_zero=False
                        ).items() if key in _BOND_RATING_OVERLAYS
                    },
                    "equity_characteristics": {
                        key: _portfolio_multiple(fund.equity_holdings, label, symbol)
                        for key, label in {
                            "price_to_earnings": "Price/Earnings",
                            "price_to_book": "Price/Book",
                            "price_to_sales": "Price/Sales",
                            "price_to_cashflow": "Price/Cashflow",
                        }.items()
                    } | {
                        "median_market_cap": _metric(
                            fund.equity_holdings, "Median Market Cap", symbol),
                        "three_year_earnings_growth": _metric(
                            fund.equity_holdings, "3 Year Earnings Growth", symbol),
                    },
                    "bond_characteristics": _bond_characteristics(
                        fund.bond_holdings, symbol
                    ),
                }
                if not detail.get("top_holdings"):
                    partial_reasons.append("top_holdings_unavailable")
            except Exception:
                # A provider detail failure must not leak implementation text or
                # masquerade as a complete fund profile. Performance may still
                # be independently usable.
                partial_reasons.append("portfolio_detail_unavailable")

            history = fetch_history(symbol, "5y", attempts=2,
                                    auto_adjust=True, actions=False)
            detail["performance"] = _performance(history)
            if detail["performance"]["as_of"] is None:
                partial_reasons.append("performance_history_unavailable")
            return {
                "name": info.get("longName") or info.get("shortName"),
                "currency": info.get("currency"),
                "quote_type": quote_type,
                "market_snapshot": _fund_market_snapshot(info),
                "data_status": "partial" if partial_reasons else "complete",
                "partial_reasons": partial_reasons,
                **detail,
            }

        try:
            data = await asyncio.to_thread(snapshot)
        except Exception:
            # Vendor metadata is needed to verify that the symbol is actually a
            # fund.  Never guess the asset type after an upstream failure, and
            # never let a yfinance exception tear down the agent loop.
            return tool_error(
                "Fund data is unavailable right now. Try again later.",
                ticker=symbol,
            )
        if data.get("wrong_type"):
            return tool_error(
                f"{symbol} is {data['wrong_type']}, not an ETF or mutual fund. "
                "Use the asset-specific tool for that instrument.",
                ticker=symbol, quote_type=data["wrong_type"],
            )
        return tool_ok(
            asset_class="fund",
            symbol=symbol,
            provider="yahoo_finance",
            capabilities={
                "portfolio_holdings": "when_available",
                "fund_operations": "when_available",
                "adjusted_price_performance": True,
                "verified_benchmark": False,
                "tracking_error": False,
                "issuer_dcf": False,
            },
            methodology={
                "ratios_weights_and_returns": "fractions",
                "equity_valuation_fields": (
                    "reciprocal_of_yahoo_portfolio_yields"
                ),
                "fund_operations_total_net_assets": "source_millions_normalized_to_absolute",
                "total_assets_scope": (
                    "provider_unspecified; fund-operations duplicates/conflicts fail closed"
                ),
                "performance_basis": "adjusted_close",
                "bond_ratings": (
                    "mutually_exclusive_credit_distribution; overlapping government "
                    "exposure is reported separately in bond_exposures"
                ),
                "bond_characteristic_units": {
                    "duration": "years", "maturity": "years",
                    "credit_quality": "source_reported",
                },
                "benchmark": None,
                "nav_premium_discount": "unavailable_without_aligned_price_and_nav_as_of",
            },
            note=("Fund portfolio analytics; no issuer DCF applies. Holdings are the top "
                  "positions reported by the source. No benchmark, tracking error, or "
                  "relative return is claimed without a verified benchmark identity. "
                  "Provider-reported total assets have unspecified share-class scope."),
            **data,
        )


def build_fund_tools():
    return [GetFundTool()]
