"""
bank_valuation.py — sector-appropriate valuation for financials.

A standard FCF DCF is structurally unfit for banks and other balance-sheet
businesses: deposit/loan flows swamp "free cash flow", so the model produces
negative or absurd fair values (FBP and JPM both shipped "valuation not
meaningful" to real users). The finance-standard alternative is a Gordon-style
justified P/B on book value:

    justified P/B = (ROE - g) / (r - g)
    fair value    = justified P/B x book value per share

with r = cost of equity (CAPM: risk-free + beta x equity risk premium) and
g = terminal growth. The audit range separates normalized historical ROE, a
fresh and well-covered forward-EPS-implied ROE scenario, and a period-matched
same-subindustry peer P/B cross-check.

Kept as its own module so both model_generation_agent and the chat tools can
import it without cycles.
"""

from __future__ import annotations

import math
import statistics
from datetime import datetime, timezone
from typing import Any, Dict, Optional

# CAPM parameters: ~10y risk-free plus a standard equity risk premium. The
# cost of equity is clamped to a sane band so a broken beta can't produce a
# silly discount rate.
_RISK_FREE = 0.043
_EQUITY_RISK_PREMIUM = 0.05
_COST_OF_EQUITY_MIN = 0.08
_COST_OF_EQUITY_MAX = 0.14

# Justified P/B clamp: bounds the damage from distorted ROE (one-offs,
# negative equity) and from roe < g edge cases.
_PB_MIN = 0.4
_PB_MAX = 3.0
_FORWARD_ROE_MIN_ANALYSTS = 5
_FORWARD_ROE_MAX_CAPTURE_AGE_DAYS = 30

# Book value is the right anchor for a BALANCE-SHEET business — banks and
# insurers, whose assets are financial and marked. It is the wrong anchor for
# payments, fintech, exchanges and asset managers, whose value is in intangibles
# and fee streams. "credit services" and the bare word "financial" pulled PayPal
# into a justified P/B x ROE valuation ($61.01) while its report ran a DCF
# ($87.11), and the chat told the user a DCF "was not used".
_FINANCIAL_INDUSTRY_HINTS = (
    "bank", "insurance", "capital markets", "credit services", "financial",
)
_NON_BALANCE_SHEET_FINANCIAL_HINTS = (
    "insurance broker", "asset management", "financial data", "stock exchange",
    "payment", "transaction processor",
)
# Interest income at or above this share of revenue marks a balance-sheet
# lender. Measured: Capital One 1.22, Synchrony 2.28, Ally 1.71, Bajaj Finance
# 1.56, banks >= 1.0, Amex 0.36, Schwab 0.60 — against PayPal 0.02, Visa -0.01,
# Mastercard -0.02, Coinbase -0.01.
_LENDER_INTEREST_SHARE = 0.30


def _finite(value: Any, *, positive: bool = False) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or (positive and number <= 0):
        return None
    return number


def _latest_reported_common_bvps(financial_data: Dict[str, Any]) -> Optional[dict]:
    """Derive the freshest auditable common book value per share."""
    statement_sets = (
        ("quarterly", financial_data.get("quarterly_financial_statements") or {}),
        ("annual", financial_data.get("financial_statements") or {}),
    )
    for frequency, statements in statement_sets:
        balance = statements.get("balance_sheet") or {}
        for period in sorted(balance, reverse=True):
            row = balance.get(period) or {}
            equity = _finite(row.get("Common Stock Equity"), positive=True)
            shares = _finite(row.get("Ordinary Shares Number"), positive=True)
            if equity is not None and shares is not None:
                return {
                    "value": equity / shares,
                    "period": str(period),
                    "source": (
                        "reported common equity / ordinary shares "
                        f"({period} {frequency})"
                    ),
                }
    return None


def _normalized_historical_common_roe(
    financial_data: Dict[str, Any], *, max_periods: int = 3
) -> Optional[dict]:
    """Median recent common ROE using average common equity.

    A point-in-time provider ROE can be distorted by one quarter or an unusual
    item.  For a residual-income/PB valuation, the sustainable ROE assumption
    is the most important input, so derive it from audited annual statements
    whenever at least two periods can be paired.
    """
    statements = financial_data.get("financial_statements") or {}
    income = statements.get("income_statement") or {}
    balance = statements.get("balance_sheet") or {}
    periods = sorted(set(income) & set(balance), reverse=True)
    all_balance_periods = sorted(balance, reverse=True)
    observations = []
    for period in periods:
        try:
            balance_index = all_balance_periods.index(period)
            prior_period = all_balance_periods[balance_index + 1]
        except (ValueError, IndexError):
            continue
        current_equity = _finite(
            (balance.get(period) or {}).get("Common Stock Equity"), positive=True
        )
        prior_equity = _finite(
            (balance.get(prior_period) or {}).get("Common Stock Equity"), positive=True
        )
        income_row = income.get(period) or {}
        common_income = None
        for key in (
            "Diluted NI Availto Com Stockholders",
            "Net Income Common Stockholders",
            "Net Income From Continuing Operation Net Minority Interest",
        ):
            common_income = _finite(income_row.get(key))
            if common_income is not None:
                break
        if current_equity is None or prior_equity is None or common_income is None:
            continue
        roe = common_income / ((current_equity + prior_equity) / 2.0)
        if math.isfinite(roe) and -1.0 < roe < 1.5:
            observations.append({"period": str(period), "roe": roe})
        if len(observations) >= max_periods:
            break
    if len(observations) < 2:
        return None
    selected = statistics.median(row["roe"] for row in observations)
    return {
        "value": selected,
        "source": f"median historical common ROE ({len(observations)} periods)",
        "observations": observations,
    }


def _forward_consensus_common_roe(
    expectations: Dict[str, Any],
    *,
    book_value_per_share: Any,
    reporting_currency: Any = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Derive an explicitly labelled near-term ROE scenario from Street EPS.

    EPS divided by current common BVPS is an approximation to forward common
    ROE, not an accounting identity: the exact denominator would be average
    forward common equity.  It is nevertheless a far better matched forecast
    cross-check than comparing a subject bank's three-year ROE with peers'
    trailing ROE.  Require two well-covered horizons and a fresh collection
    timestamp so one stale or thin estimate cannot become a valuation input.
    """
    result: Dict[str, Any] = {
        "status": "unavailable",
        "value": None,
        "source": None,
        "observations": [],
        "reason": None,
    }
    if not isinstance(expectations, dict):
        result["reason"] = "external expectations are unavailable"
        return result
    bvps = _finite(book_value_per_share, positive=True)
    if bvps is None:
        result["reason"] = "current common book value per share is unavailable"
        return result

    expected_currency = str(reporting_currency or "").strip().upper()
    estimate_currency = str(expectations.get("currency") or "").strip().upper()
    if expected_currency and estimate_currency and expected_currency != estimate_currency:
        result["reason"] = (
            f"EPS estimate currency {estimate_currency} does not match "
            f"book-value currency {expected_currency}"
        )
        return result

    captured_raw = expectations.get("captured_at")
    captured = None
    if isinstance(captured_raw, datetime):
        captured = captured_raw
    elif isinstance(captured_raw, str) and captured_raw.strip():
        try:
            captured = datetime.fromisoformat(
                captured_raw.strip().replace("Z", "+00:00")
            )
        except ValueError:
            captured = None
    if captured is None:
        result["reason"] = "forward-estimate collection time is unavailable"
        return result
    if captured.tzinfo is None:
        captured = captured.replace(tzinfo=timezone.utc)
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    age_days = (reference - captured.astimezone(timezone.utc)).total_seconds() / 86400.0
    if age_days < -2 or age_days > _FORWARD_ROE_MAX_CAPTURE_AGE_DAYS:
        result["reason"] = (
            "forward estimates are future-dated or older than "
            f"{_FORWARD_ROE_MAX_CAPTURE_AGE_DAYS} days"
        )
        return result

    observations = []
    for row in (expectations.get("forward_estimates") or [])[:2]:
        if not isinstance(row, dict):
            continue
        eps = _finite(row.get("eps"), positive=True)
        try:
            analyst_count = int(row.get("eps_analyst_count") or 0)
        except (TypeError, ValueError, OverflowError):
            analyst_count = 0
        implied_roe = eps / bvps if eps is not None else None
        if (
            eps is None
            or analyst_count < _FORWARD_ROE_MIN_ANALYSTS
            or implied_roe is None
            or not 0.01 <= implied_roe <= 0.50
        ):
            continue
        observations.append({
            "period": str(row.get("period") or "unknown")[:20],
            "eps": eps,
            "eps_analyst_count": analyst_count,
            "implied_common_roe": implied_roe,
        })
    if len(observations) < 2:
        result["reason"] = (
            "two fresh forward EPS horizons with at least five analysts each "
            "are required"
        )
        result["observations"] = observations
        return result

    result.update({
        "status": "ready",
        "value": statistics.median(
            row["implied_common_roe"] for row in observations
        ),
        "source": (
            "median of two fresh, well-covered Street EPS / current common BVPS "
            "scenarios (approximate forward ROE)"
        ),
        "observations": observations,
        "captured_at": captured.astimezone(timezone.utc).isoformat(),
        "age_days": round(age_days, 3),
        "reason": None,
    })
    return result


def assess_bank_publication(
    *,
    fair_value: Any,
    intrinsic_fair_value: Any,
    peer_fair_value: Any,
    current_price: Any,
    forward_consensus_fair_value: Any = None,
    bank_inputs: Optional[Dict[str, Any]] = None,
    analyst_target: Any = None,
    analyst_count: Any = 0,
    analyst_target_corroboration_qualified: bool = True,
    analyst_target_contradiction_qualified: bool = True,
    analyst_target_evidence: Optional[Dict[str, Any]] = None,
    analyst_rating: Any = None,
    analyst_rating_count: Any = 0,
    analyst_rating_evidence: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """One deterministic publication boundary for every bank call path."""
    inputs = bank_inputs if isinstance(bank_inputs, dict) else {}
    intrinsic = _finite(intrinsic_fair_value, positive=True)
    peer = _finite(peer_fair_value, positive=True)
    value = _finite(fair_value, positive=True)
    price = _finite(current_price, positive=True)
    legs = {
        "justified_pb_roe": intrinsic,
        "forward_consensus_roe_scenario": _finite(
            forward_consensus_fair_value, positive=True
        ),
        "roe_adjusted_peer_pb": peer,
    }
    positive = [number for number in legs.values() if number is not None]
    ratio = max(positive) / min(positive) if len(positive) >= 2 else None
    if ratio is None:
        band = "single-method"
        warning = (
            "The bank valuation currently has one usable scenario. A fresh, "
            "well-covered forward-EPS ROE scenario and/or at least three "
            "screened same-subindustry bank peers were unavailable."
        )
    elif ratio < 1.3:
        band, warning = "tight", None
    elif ratio < 1.8:
        band = "moderate"
        warning = "The bank valuation scenarios form a material range."
    elif ratio < 2.5:
        band = "wide"
        warning = "The bank valuation scenarios span more than 1.8x."
    else:
        band = "unreliable"
        warning = "The bank valuation scenarios contradict each other."

    withheld = bool(value is None or price is None or band in {"wide", "unreliable"})
    reason = None
    if value is None or price is None:
        reason = "The bank valuation or current market price is unavailable."
    elif band in {"wide", "unreliable"}:
        reason = (
            "The bank valuation scenarios do not "
            "converge enough to support a point estimate."
        )

    if inputs.get("input_boundary_triggered"):
        withheld = True
        triggered = []
        if inputs.get("cost_of_equity_clamped"):
            triggered.append("the CAPM cost of equity hit its model boundary")
        if inputs.get("price_to_book_clamped"):
            triggered.append("the justified P/B multiple hit its model boundary")
        if inputs.get("book_value_cross_check_failed"):
            triggered.append("reported and provider book value per share differ by over 15%")
        boundary_reason = (
            "The bank valuation is an audit scenario, not a publishable point "
            "estimate, because " + "; ".join(triggered or [
                "a core bank-model input hit a safety boundary"
            ]) + "."
        )
        reason = f"{reason} {boundary_reason}" if reason else boundary_reason

    def count(value_to_parse: Any) -> int:
        if isinstance(value_to_parse, bool):
            return 0
        try:
            return min(max(int(value_to_parse or 0), 0), 100_000)
        except (TypeError, ValueError, OverflowError):
            return 0

    model_gap = value / price - 1.0 if value is not None and price is not None else None
    bullish = {"strong_buy", "strong buy", "buy", "outperform", "overweight"}
    bearish = {"strong_sell", "strong sell", "sell", "underperform", "underweight"}

    target_rows = []
    if isinstance(analyst_target_evidence, dict) and analyst_target_evidence:
        for source, row in analyst_target_evidence.items():
            if not isinstance(row, dict):
                continue
            target_value = _finite(row.get("mean") or row.get("target"), positive=True)
            target_count = count(row.get("analyst_count"))
            if target_value is None or target_count < 5 or price is None:
                continue
            target_rows.append({
                "source": str(source)[:50],
                "count": target_count,
                "gap": target_value / price - 1.0,
                "contradiction_qualified": bool(
                    row.get("qualified_for_contradiction", row.get("qualified", True))
                ),
                "corroboration_qualified": bool(
                    row.get("qualified_for_corroboration", row.get("qualified", True))
                ),
            })
    else:
        target = _finite(analyst_target, positive=True)
        target_n = count(analyst_count)
        if target is not None and target_n >= 5 and price is not None:
            target_rows.append({
                "source": "active consensus",
                "count": target_n,
                "gap": target / price - 1.0,
                "contradiction_qualified": analyst_target_contradiction_qualified,
                "corroboration_qualified": analyst_target_corroboration_qualified,
            })

    rating_rows = []
    if isinstance(analyst_rating_evidence, dict) and analyst_rating_evidence:
        for source, row in analyst_rating_evidence.items():
            if not isinstance(row, dict) or row.get("qualified") is False:
                continue
            label = str(row.get("label") or "").strip().lower()
            rating_count = count(
                row.get("analyst_count") or row.get("total")
                or row.get("unique_analyst_count")
            )
            if rating_count >= 5 and label:
                rating_rows.append({
                    "source": str(source)[:50], "count": rating_count, "label": label,
                })
    else:
        rating_n = count(analyst_rating_count)
        rating_label = str(analyst_rating or "").strip().lower()
        if rating_n >= 5 and rating_label:
            rating_rows.append({
                "source": "active consensus", "count": rating_n,
                "label": rating_label,
            })

    target_conflict = bool(
        model_gap is not None and abs(model_gap) >= .15 and any(
            row["contradiction_qualified"]
            and ((model_gap < 0 and row["gap"] > -.05)
                 or (model_gap > 0 and row["gap"] < .05))
            for row in target_rows
        )
    )

    def rating_direction(label: str) -> Optional[int]:
        if label in bullish:
            return 1
        if label in bearish:
            return -1
        if label in {"hold", "neutral", "market_perform", "equal_weight"}:
            return 0
        return None

    model_direction = 1 if model_gap is not None and model_gap > 0 else -1
    rating_conflict = bool(
        model_gap is not None and abs(model_gap) >= .15 and any(
            (direction := rating_direction(row["label"])) is not None
            and direction != model_direction
            for row in rating_rows
        )
    )
    target_corroborates = bool(
        model_gap is not None and any(
            row["corroboration_qualified"]
            and model_gap * row["gap"] > 0
            and abs(row["gap"]) >= max(.08, abs(model_gap) * .50)
            for row in target_rows
        )
    )
    unsupported_single_method = bool(
        model_gap is not None and band == "single-method" and abs(model_gap) >= .15
        # A BUY/SELL label can challenge direction, but it does not support the
        # magnitude of a precise single-method target. Require a numeric target
        # pointing the same way, just as the corporate DCF boundary does.
        and not target_corroborates
    )
    if target_conflict or rating_conflict or unsupported_single_method:
        withheld = True
        benchmark_parts = []
        for row in target_rows[:3]:
            benchmark_parts.append(
                f"{row['source']} {row['count']}-analyst target benchmark is "
                f"{row['gap']:+.0%}"
            )
        for row in rating_rows[:3]:
            benchmark_parts.append(
                f"{row['source']} rates it "
                f"{row['label'].replace('_', ' ').upper()} "
                f"({row['count']} ratings)"
            )
        benchmark_note = (
            " External benchmarks: " + "; ".join(benchmark_parts) + "."
            if benchmark_parts else ""
        )
        analyst_reason = (
            f"The bank valuation is {model_gap:+.0%} from the market"
            + (" and rests on one intrinsic method" if band == "single-method" else "")
            + ". Well-covered external analyst evidence does not corroborate "
            "a directional call at that gap."
            + benchmark_note
            + " Publish the bank methods as scenarios and withhold a rating."
        )
        reason = f"{reason} {analyst_reason}" if reason else analyst_reason

    return {
        "dispersion_ratio": ratio,
        "dispersion_band": band,
        "valuation_warning": warning,
        "point_estimate_withheld": withheld,
        "publication_withheld_reason": reason,
        "reliability_legs": legs,
    }


def is_financial_sector(sector: Optional[str], industry: Optional[str] = None,
                        interest_income_to_revenue: Optional[float] = None) -> bool:
    """
    True for a balance-sheet financial, where a justified P/B x ROE valuation
    is meaningful.

    Yahoo files lenders and payment processors in the same "Credit Services"
    industry, so the taxonomy alone cannot decide: PayPal ($61.01 on P/B x ROE
    against an $87.11 DCF) was the cost of trusting it. When the income
    statement is available the interest-income share decides. When it is not,
    the industry hints decide, exactly as before — narrowing them was itself a
    regression that would have sent Capital One, Synchrony, Ally and Bajaj
    Finance through an FCF DCF.
    """
    financial = (sector or "").strip().lower() == "financial services"
    ind = (industry or "").strip().lower()
    hinted = financial or any(h in ind for h in _FINANCIAL_INDUSTRY_HINTS)
    if not hinted:
        return False
    if any(h in ind for h in _NON_BALANCE_SHEET_FINANCIAL_HINTS):
        return False
    interest_share = _finite(interest_income_to_revenue)
    if interest_share is not None:
        return interest_share >= _LENDER_INTEREST_SHARE
    return True


def is_balance_sheet_financial(financial_data: Dict[str, Any]) -> bool:
    """Classify method applicability independently from input completeness.

    A bank with a missing BVPS or ROE is still a bank.  Tying classification to
    whether ``build_bank_valuation_override`` happens to return a value lets an
    incomplete bank fall through to an industrial FCFF DCF, which is the exact
    methodology error this module exists to prevent.
    """
    if not isinstance(financial_data, dict):
        return False
    company_data = financial_data.get("company_data") or {}
    basic_info = company_data.get("basic_info") or {}
    financial_profile = (
        (((financial_data.get("modeling_metrics") or {}).get("financial_ratios") or {})
         .get("financial_profile") or {})
    )
    interest_share = _finite(financial_profile.get("interest_income_to_revenue"))

    # The final modeling payload normally carries the calculated profile.  Also
    # derive it directly from the freshest statement so classification remains
    # stable in earlier collection phases and when replaying older artifacts.
    if interest_share is None:
        statements = financial_data.get("financial_statements") or {}
        income = statements.get("income_statement") or {}
        if isinstance(income, dict):
            for period in sorted(income, key=str, reverse=True):
                row = income.get(period) or {}
                if not isinstance(row, dict):
                    continue
                revenue = next((
                    _finite(row.get(key), positive=True)
                    for key in ("Total Revenue", "TotalRevenues", "totalRevenue", "Revenue")
                    if _finite(row.get(key), positive=True) is not None
                ), None)
                interest = next((
                    _finite(row.get(key))
                    for key in (
                        "Interest Income", "Total Interest Income", "InterestIncome",
                        "Net Interest Income", "NetInterestIncome",
                    )
                    if _finite(row.get(key)) is not None
                ), None)
                if revenue is not None and interest is not None:
                    interest_share = interest / revenue
                    break

    return is_financial_sector(
        basic_info.get("sector"), basic_info.get("industry"), interest_share
    )


def compute_bank_fair_value(
    company_data: dict,
    terminal_growth: Optional[float] = None,
    capm: Optional[dict] = None,
    *,
    book_value_per_share: Optional[float] = None,
    sustainable_roe: Optional[float] = None,
    input_context: Optional[Dict[str, Any]] = None,
) -> Optional[dict]:
    """
    Justified P/B x ROE fair value from the scraped company_data block.

    Returns a dict with fair_value, upside_vs_market (FRACTION — downstream
    multiplies by 100), method label, and the inputs used — or None when the
    required fields are missing/unusable. A caller that has already classified
    the issuer as a balance-sheet financial must fail closed, never fall back
    to an industrial DCF.
    """
    if not isinstance(company_data, dict):
        return None
    vm = company_data.get("valuation_metrics", {}) or {}
    gp = company_data.get("growth_profitability", {}) or {}
    md = company_data.get("market_data", {}) or {}
    cs = company_data.get("capital_structure", {}) or {}

    provider_bvps = _finite(vm.get("book_value"), positive=True)
    provider_roe = _finite(gp.get("return_on_equity"))
    bvps = _finite(book_value_per_share, positive=True) or provider_bvps
    roe = _finite(sustainable_roe)
    if roe is None:
        roe = provider_roe
    price = _finite(md.get("current_price"), positive=True)
    beta = _finite(cs.get("beta"), positive=True) or 1.0

    if bvps is None or roe is None or not -1.0 < roe < 1.5:
        return None

    requested_growth = _finite(terminal_growth)
    if requested_growth is None:
        requested_growth = 0.025
    g = max(0.0, min(requested_growth, 0.03))
    # One cost of capital per run: when the CAPM build is available the
    # bank's cost of equity is its risk-free rate, its home-index beta and
    # its premium — the same numbers the report's Cost of Capital table
    # prints — rather than a 4.3% + beta x 5% shortcut nothing else uses.
    rf, erp = _RISK_FREE, _EQUITY_RISK_PREMIUM
    source = "4.3% + beta x 5% (no CAPM build available)"
    if isinstance(capm, dict):
        capm_rf = _finite(capm.get("risk_free_rate"))
        capm_erp = _finite(capm.get("equity_risk_premium_total"), positive=True)
        capm_beta = _finite(capm.get("beta"), positive=True)
        if capm_rf is not None and capm_erp is not None:
            rf, erp = capm_rf, capm_erp
            if capm_beta is not None:
                beta = capm_beta
            source = f"Rf {rf*100:.2f}% + beta {beta:.2f} x ERP {erp*100:.2f}% (CAPM build)"
    raw_cost_of_equity = rf + beta * erp
    r = max(
        _COST_OF_EQUITY_MIN,
        min(_COST_OF_EQUITY_MAX, raw_cost_of_equity),
    )
    cost_of_equity_clamped = not math.isclose(
        r, raw_cost_of_equity, rel_tol=0.0, abs_tol=1e-12
    )
    if r <= g:
        return None

    raw_justified_pb = (float(roe) - g) / (r - g)
    if not math.isfinite(raw_justified_pb) or raw_justified_pb <= 0:
        return None
    justified_pb = max(_PB_MIN, min(_PB_MAX, raw_justified_pb))
    price_to_book_clamped = not math.isclose(
        justified_pb, raw_justified_pb, rel_tol=0.0, abs_tol=1e-12
    )

    fair_value = round(justified_pb * float(bvps), 2)
    upside = (fair_value / price - 1.0) if price else None

    context = dict(input_context or {})
    context.update({
        "provider_book_value_per_share": provider_bvps,
        "provider_return_on_equity": provider_roe,
        "raw_cost_of_equity": raw_cost_of_equity,
        "cost_of_equity_clamped": cost_of_equity_clamped,
        "raw_justified_pb": raw_justified_pb,
        "price_to_book_clamped": price_to_book_clamped,
        "input_boundary_triggered": bool(
            cost_of_equity_clamped or price_to_book_clamped
            or not math.isclose(g, requested_growth, rel_tol=0.0, abs_tol=1e-12)
        ),
    })

    return {
        "fair_value": fair_value,
        "upside_vs_market": upside,
        "method": "justified_pb_roe",
        "inputs": {
            "bvps": float(bvps),
            "roe": float(roe),
            "beta": beta,
            "cost_of_equity": r,
            "cost_of_equity_source": source,
            "terminal_growth": g,
            "justified_pb": justified_pb,
            **context,
        },
    }


def build_bank_valuation_override(
    financial_data: Dict[str, Any],
    terminal_growth: Optional[float] = None,
    capm: Optional[dict] = None,
) -> Optional[Dict[str, Any]]:
    """Build the report override for a provider-confirmed balance-sheet financial.

    The worker has two model-generation routes. The chat route carries its
    valuation in ``FinancialState``; the default comprehensive route reads the
    modeling JSON directly. Keeping classification and payload construction
    here prevents those routes from publishing different answers.
    """
    if not isinstance(financial_data, dict):
        return None
    company_data = financial_data.get("company_data") or {}
    if not is_balance_sheet_financial(financial_data):
        return None

    reported_bvps = _latest_reported_common_bvps(financial_data)
    historical_roe = _normalized_historical_common_roe(financial_data)
    provider_bvps = _finite(
        (company_data.get("valuation_metrics") or {}).get("book_value"),
        positive=True,
    )
    provider_roe = _finite(
        (company_data.get("growth_profitability") or {}).get("return_on_equity")
    )
    selected_bvps = (reported_bvps or {}).get("value") or provider_bvps
    selected_roe = (historical_roe or {}).get("value")
    if selected_roe is None:
        selected_roe = provider_roe
    from src.external_expectations import build_external_expectations
    expectations = (
        financial_data.get("external_expectations")
        or build_external_expectations(financial_data)
    )
    basic_info = company_data.get("basic_info") or {}
    forward_roe = _forward_consensus_common_roe(
        expectations,
        book_value_per_share=selected_bvps,
        reporting_currency=basic_info.get("currency"),
    )
    bvps_gap = (
        selected_bvps / provider_bvps - 1.0
        if selected_bvps and provider_bvps else None
    )
    input_context = {
        "book_value_per_share_source": (
            (reported_bvps or {}).get("source") or "provider current book value per share"
        ),
        "book_value_per_share_period": (reported_bvps or {}).get("period"),
        "book_value_provider_gap": bvps_gap,
        "return_on_equity_source": (
            (historical_roe or {}).get("source") or "provider trailing return on equity"
        ),
        "return_on_equity_observations": (
            (historical_roe or {}).get("observations") or []
        ),
    }
    bank = compute_bank_fair_value(
        company_data,
        terminal_growth=terminal_growth,
        capm=capm,
        book_value_per_share=selected_bvps,
        sustainable_roe=selected_roe,
        input_context=input_context,
    )
    if not bank:
        return None
    if bvps_gap is not None and abs(bvps_gap) > 0.15:
        bank["inputs"]["input_boundary_triggered"] = True
        bank["inputs"]["book_value_cross_check_failed"] = True
    else:
        bank["inputs"]["book_value_cross_check_failed"] = False

    forward_fair_value = None
    forward_scenario = None
    if forward_roe.get("status") == "ready":
        forward_scenario = compute_bank_fair_value(
            company_data,
            terminal_growth=terminal_growth,
            capm=capm,
            book_value_per_share=selected_bvps,
            sustainable_roe=forward_roe.get("value"),
            input_context={
                "return_on_equity_source": forward_roe.get("source"),
                "return_on_equity_observations": forward_roe.get("observations"),
            },
        )
        # An external scenario that itself hits a P/B safety clamp is not a
        # usable valuation leg. Preserve the diagnostic but do not let it
        # distort the historical intrinsic scenario or the publication range.
        if forward_scenario and not forward_scenario["inputs"].get(
            "input_boundary_triggered"
        ):
            forward_fair_value = forward_scenario["fair_value"]
        else:
            forward_roe["status"] = "excluded"
            forward_roe["reason"] = "forward-ROE scenario hit a valuation safety boundary"

    # A raw peer P/B comparison structurally penalizes a high-ROE bank.  Use
    # the same-subindustry peers' P/B divided by excess ROE (ROE - g), then
    # apply the median relationship to the subject's period-matched TTM ROE. This is
    # still a market cross-check—not an intrinsic-value input disguised as
    # consensus—and requires at least three screened peers.
    peer = ((financial_data.get("industry_data") or {}).get("peer_comps") or {})
    peer_fair_value = None
    peer_implied_pb = None
    peer_count = 0
    if (
        peer.get("status") == "ready"
        and peer.get("included_in_blended_value") is True
        and peer.get("selected_method") == "price_to_book"
    ):
        g = bank["inputs"]["terminal_growth"]
        excess_roe_multiples = []
        for observation in peer.get("observations") or []:
            if not isinstance(observation, dict):
                continue
            pb = _finite(observation.get("price_to_book"), positive=True)
            peer_roe_pct = _finite(observation.get("return_on_equity_ttm_pct"))
            if pb is None or peer_roe_pct is None:
                continue
            peer_excess_roe = peer_roe_pct / 100.0 - g
            if peer_excess_roe > 0.01:
                excess_roe_multiples.append(pb / peer_excess_roe)
        peer_count = len(excess_roe_multiples)
        # Peer ROE is provider trailing ROE, so compare it with the subject's
        # provider trailing ROE. The old implementation applied the subject's
        # three-year historical median against peers' TTM values, which
        # systematically depressed improving banks (most visibly GS and C).
        peer_subject_roe = (
            provider_roe
            if provider_roe is not None and -1.0 < provider_roe < 1.5
            else bank["inputs"]["roe"]
        )
        subject_excess_roe = peer_subject_roe - g
        if peer_count >= 3 and subject_excess_roe > 0.01:
            peer_implied_pb = statistics.median(excess_roe_multiples) * subject_excess_roe
            if math.isfinite(peer_implied_pb) and 0.2 <= peer_implied_pb <= 6.0:
                peer_fair_value = round(peer_implied_pb * bank["inputs"]["bvps"], 2)

    intrinsic_fair_value = bank["fair_value"]
    valuation_scenarios = [intrinsic_fair_value]
    if forward_fair_value is not None:
        valuation_scenarios.append(forward_fair_value)
    if peer_fair_value is not None:
        valuation_scenarios.append(peer_fair_value)
    fair_value = round(sum(valuation_scenarios) / len(valuation_scenarios), 2)
    bank["inputs"].update({
        "intrinsic_fair_value": intrinsic_fair_value,
        "forward_consensus_fair_value": forward_fair_value,
        "forward_consensus_roe": forward_roe.get("value"),
        "forward_consensus_roe_status": forward_roe.get("status"),
        "forward_consensus_roe_source": forward_roe.get("source"),
        "forward_consensus_roe_observations": forward_roe.get("observations") or [],
        "forward_consensus_roe_reason": forward_roe.get("reason"),
        "forward_consensus_justified_pb": (
            (forward_scenario or {}).get("inputs", {}).get("justified_pb")
        ),
        "peer_fair_value": peer_fair_value,
        "peer_implied_price_to_book": peer_implied_pb,
        "peer_observation_count": peer_count,
        "peer_subject_return_on_equity": (
            provider_roe
            if provider_roe is not None and -1.0 < provider_roe < 1.5
            else bank["inputs"]["roe"]
        ),
        "peer_subject_return_on_equity_source": (
            "provider trailing ROE (period-matched to peer observations)"
            if provider_roe is not None and -1.0 < provider_roe < 1.5
            else bank["inputs"].get("return_on_equity_source")
        ),
        "peer_method": "ROE-adjusted same-subindustry P/B" if peer_fair_value else None,
    })
    current_price = (company_data.get("market_data") or {}).get("current_price")
    recommendation = (company_data.get("analyst_consensus") or {}).get("recommendation") or {}
    guidance = company_data.get("forward_guidance") or {}
    rating_count = 0
    if isinstance(recommendation, dict):
        for candidate in (
            recommendation.get("total"),
            recommendation.get("unique_analyst_count"),
            recommendation.get("analyst_count"),
        ):
            try:
                rating_count = max(rating_count, int(candidate or 0))
            except (TypeError, ValueError, OverflowError):
                continue
    target_benchmark = (expectations.get("price_target") or {})
    recommendation_benchmark = (expectations.get("recommendations") or {})
    publication = assess_bank_publication(
        fair_value=fair_value,
        intrinsic_fair_value=intrinsic_fair_value,
        peer_fair_value=peer_fair_value,
        current_price=current_price,
        forward_consensus_fair_value=forward_fair_value,
        bank_inputs=bank["inputs"],
        analyst_target=(
            target_benchmark.get("mean") or guidance.get("target_mean_price")
        ),
        analyst_count=(
            target_benchmark.get("analyst_count")
            or guidance.get("number_of_analyst_opinions")
        ),
        analyst_target_corroboration_qualified=bool(
            target_benchmark.get("qualified_for_corroboration")
        ),
        analyst_target_contradiction_qualified=bool(
            target_benchmark.get("qualified_for_contradiction")
        ),
        analyst_target_evidence=target_benchmark.get("source_evidence") or {},
        analyst_rating=recommendation.get("label"),
        analyst_rating_count=(
            rating_count if recommendation_benchmark.get("active_qualified", True)
            else 0
        ),
        analyst_rating_evidence=(
            recommendation_benchmark.get("source_evidence") or {}
        ),
    )
    return {
        "valuation_method": "justified_pb_roe",
        "fair_value": fair_value,
        "current_price": current_price,
        "upside_vs_market": (
            fair_value / float(current_price) - 1.0 if current_price else None
        ),
        "intrinsic_fair_value": intrinsic_fair_value,
        "forward_consensus_fair_value": forward_fair_value,
        "peer_fair_value": peer_fair_value,
        "bank_inputs": bank["inputs"],
        **publication,
    }
