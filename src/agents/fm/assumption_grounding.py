"""
assumption_grounding.py — deterministic, observable-data guardrails over the
initial modeling inputs.

Generative models can help explain a story, but they are unreliable for
PARAMETERS a bank computes mechanically. Left alone, the former path guessed
WACC 11.14% for Alphabet (CAPM says ~8.7%), started
margin paths below what the company already achieves, and every model shipped
a hardcoded 20.0x exit multiple regardless of sector. Each bias compounds
into fair values 30-50% off.

This module grounds those parameters from observable data:

  * WACC        — CAPM: the 10Y government yield in the cash flows' own
                  currency less the sovereign's default spread (sovereign_rates,
                  country_risk), beta regressed on the home index and
                  Blume-adjusted (market_beta), a 5.5% mature-market ERP plus
                  Damodaran's country premium, blended with after-tax cost of
                  debt (government yield + spread) at actual D/E weights.
  * Terminal g  — clamped to [2.0%, 3.0%], then capped at the currency's
                  risk-free rate.
  * Margin paths— for companies with positive trailing operating profit, the
                  path is anchored to trailing actuals and the recent median.
                  Loss-making names keep an explicit scenario path because
                  convergence to profitability is the investment thesis.
  * Exit multiple— the company's observable current EV/EBITDA when it is a
                  finite positive multiple. There is no invented fallback.
                  The workbook can only reduce that reference multiple using
                  projected FY10 cash conversion and a sustainable-growth cap.

Every override is returned as a human-readable note and logged, so the
workbook's provenance stays auditable.
"""

from __future__ import annotations

import math
import os
import statistics
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

_ERP = 0.055                # mature-market equity risk premium; in the range
                            # Damodaran publishes for developed markets, and the
                            # figure a sell-side DCF on a euro large-cap would use
_DEBT_SPREAD = 0.015        # explicit fallback when issuer coverage is unavailable
_TAX_DEFAULT = 0.25         # mature-market average; overridden by the
                            # company's own effective rate when available
_BETA_MIN, _BETA_MAX = 0.5, 2.0
_WACC_MIN, _WACC_MAX = 0.06, 0.20   # disclosure band, not a clamp
_TG_MIN, _TG_MAX = 0.02, 0.03
_TERMINAL_GROWTH_BASE = 0.025
# Provider sanity boundary. The observed current multiple is not clamped into
# a preferred range: doing so silently lifts cheap/cyclical names and cuts
# expensive growth names. Sustainability is tested against projected FY10
# economics below; values outside this very broad provider-validity boundary
# make the method unavailable.
_EXIT_PROVIDER_MIN, _EXIT_PROVIDER_MAX = 0.1, 80.0
_CONSENSUS_FADE_FACTORS = (0.67, 0.40, 0.20)
# Exact, well-covered dollar forecasts can legitimately imply triple-digit
# growth for an early commercialization story. Keep a broad unit-error rail on
# those absolute forecasts, but do not apply the mature-company 100% ceiling
# that is still appropriate for a provider's unverified percentage field.
_ABSOLUTE_CONSENSUS_GROWTH_MAX = 10.0
# Beyond the two covered years, do not blindly extrapolate a 200%+ Street step.
# The uncovered tail is a scenario and is capped before fading toward terminal
# growth; publication remains withheld for companies without established FCF.
_POST_CONSENSUS_GROWTH_CAP = 1.0

# Damodaran, "Ratings, Interest Coverage Ratios and Default Spread",
# January 2026, large non-financial service firms.  The source defines the
# synthetic rating from EBIT / interest expense and adds the corresponding
# spread to the risk-free rate. Small-cap and financial-service tables have
# different breakpoints, so this table is used only above USD-equivalent $5B
# and never for a selected bank methodology.
_SYNTHETIC_RATING_SOURCE = (
    "Damodaran large non-financial synthetic-rating table (January 2026; "
    "https://pages.stern.nyu.edu/adamodar/New_Home_Page/datafile/ratings.html)"
)
_LARGE_FIRM_COVERAGE_TABLE = (
    (0.20, "D2/D", 0.1900),
    (0.65, "C2/C", 0.1600),
    (0.80, "Ca2/CC", 0.1261),
    (1.25, "Caa/CCC", 0.0885),
    (1.50, "B3/B-", 0.0509),
    (1.75, "B2/B", 0.0321),
    (2.00, "B1/B+", 0.0275),
    (2.25, "Ba2/BB", 0.0184),
    (2.50, "Ba1/BB+", 0.0138),
    (3.00, "Baa2/BBB", 0.0111),
    (4.25, "A3/A-", 0.0089),
    (5.50, "A2/A", 0.0078),
    (6.50, "A1/A+", 0.0070),
    (8.50, "Aa2/AA", 0.0055),
    (math.inf, "Aaa/AAA", 0.0040),
)


def _issuer_credit_spread(
    company_data: Dict[str, Any], json_data: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Return a normalized issuer spread or the explicit house fallback.

    A single noisy period is not enough to assign a synthetic rating. Use the
    median of at least two valid current/annual EBIT-to-interest observations.
    The published cutoff is denominated in US dollars and calibrated on US
    firms, so apply it only to USD-reporting subjects above $5B.
    """
    fallback = {
        "spread": _DEBT_SPREAD,
        "rating": None,
        "coverage": None,
        "coverage_observations": [],
        "source": "1.5% house credit-spread fallback; issuer coverage unavailable",
        "synthetic": False,
    }
    if not isinstance(json_data, dict):
        return fallback
    currency = str(
        (company_data.get("basic_info", {}) or {}).get("currency") or ""
    ).upper()
    if currency != "USD":
        return {**fallback, "source": (
            "1.5% house credit-spread fallback; the available synthetic-rating "
            "table is calibrated to USD-reporting US firms"
        )}
    market = company_data.get("market_data", {}) or {}
    equity = market.get("market_cap_financial") or market.get("market_cap")
    if (not isinstance(equity, (int, float)) or isinstance(equity, bool)
            or not math.isfinite(float(equity)) or float(equity) <= 5_000_000_000):
        return {**fallback, "source": (
            "1.5% house credit-spread fallback; the available market capitalization "
            "does not meet the source table's >$5B large-firm scope"
        )}

    observations = []

    def observe(label: str, row: Any) -> None:
        if not isinstance(row, dict):
            return
        ebit = _number(row, "Operating Income", "EBIT")
        interest = _number(row, "Interest Expense", "InterestExpense")
        if (ebit is None or interest is None or interest <= 0
                or not math.isfinite(ebit / interest)):
            return
        observations.append({"period": label, "interest_coverage": ebit / interest})

    bridge = json_data.get("ttm_bridge") or {}
    if bridge.get("status") == "current":
        observe(str(bridge.get("latest_period") or "TTM"), bridge.get("income_statement"))
    statements = (json_data.get("financial_statements") or {}).get(
        "income_statement") or {}
    for period, row in sorted(
        statements.items(), key=lambda pair: str(pair[0]), reverse=True,
    ):
        observe(str(period), row)
        if len(observations) >= 4:
            break
    if len(observations) < 2:
        return {**fallback, "coverage_observations": observations}

    coverage = statistics.median(
        row["interest_coverage"] for row in observations
    )
    upper, rating, spread = next(
        row for row in _LARGE_FIRM_COVERAGE_TABLE if coverage <= row[0]
    )
    return {
        "spread": spread,
        "rating": rating,
        "coverage": coverage,
        "coverage_observations": observations,
        "source": (
            f"{spread*100:.2f}% synthetic {rating} spread from normalized "
            f"EBIT/interest coverage {coverage:.2f}x; {_SYNTHETIC_RATING_SOURCE}"
        ),
        "synthetic": True,
    }


# The risk-free rate is built from two published inputs, both printed:
#
#     Rf(currency) = 10-year government yield in that currency
#                    - the sovereign's rating-based default spread
#
# The yield comes from a published feed per currency (sovereign_rates: the
# ECB, Japan's MOF and Yahoo's ^TNX daily, then TradingView's screen, then
# FRED's monthly series), with a dated snapshot as the offline fallback and a
# labelled US proxy only for currencies none of those cover.
# The subtraction is Damodaran's: a government bond rated below Aaa is not
# default-free, and the default risk it carries is what the country risk
# premium prices into the cost of equity — leaving it in the risk-free rate
# as well would charge it twice. For an Aaa sovereign (Germany, Switzerland,
# Singapore) the spread is zero and the yield is used as is.
#
# RISK_FREE_<CCY> (e.g. RISK_FREE_EUR=0.0324) overrides the final rate without
# a deploy; EQUITY_RISK_PREMIUM overrides the mature-market ERP.


def _mature_erp() -> float:
    """
    The mature-market equity risk premium.

    ORDER MATTERS, and it used to be wrong. This returned the _ERP house
    assumption of 5.5% while `load_table()` — already called a few lines from
    the only use site — carried Damodaran's PUBLISHED implied premium of about
    4.2%. The published figure was read solely to print in the provenance
    note, so every workbook said, in effect, "we used 5.5%; Damodaran says
    4.2%" and then valued the company off the higher number.

    That was not a small conservatism. It runs through the model twice: the
    inflated WACC discounts the perpetuity leg directly, AND it lowers the
    exit-multiple ceiling in `defensible_multiple`, because that ceiling is a
    function of WACC. Both DCF legs move together off this one input, which is
    why they agreed with each other and disagreed with the market. Measured
    over 49 stored theses, the median name came out 15.7% BELOW market and 69%
    were negative — a valuation engine that rated two thirds of large-cap
    America a sell.

    A published, dated, citable number is also the whole premise of the
    product. Preferring a house assumption over the source we already fetch is
    the one thing this page cannot afford to do.

    So: an explicit env override still wins (it is how a desk states a view),
    then Damodaran's published figure, then the embedded constant as a floor
    for when the fetch and the snapshot are both unavailable.
    """
    import os
    raw = os.getenv("EQUITY_RISK_PREMIUM")
    if raw:
        try:
            value = float(raw)
            if 0.03 <= value <= 0.09:
                return value
        except ValueError:
            pass
    try:
        # Imported here, not at module scope: country_risk reaches the network
        # on first use and this module is imported during model build.
        from .country_risk import load_table
        published = (load_table() or {}).get("mature_erp")
    except Exception:
        # A failed fetch must never break model generation; fall through to
        # the embedded snapshot value below.
        published = None
    # The band is a sanity gate, not a preference: a parse failure that yields
    # 0.4 or 0.0004 must not silently become the discount rate.
    if isinstance(published, (int, float)) and 0.03 <= float(published) <= 0.09:
        return float(published)
    return _ERP


def risk_free_details(currency: Optional[str] = "USD") -> Dict[str, Any]:
    """
    The risk-free rate for cash flows denominated in ``currency``, and its build.

    Returns ``rate`` (default-free), ``sovereign_yield`` (the government bond
    yield the rate was built from — what corporate debt is priced off),
    ``default_spread``, ``as_of``, ``source``, ``proxy`` and ``label``, the
    sentence the report prints so a reader can see whether the rate was live,
    dated or a proxy.
    """
    import os
    from .sovereign_rates import normalise_currency, sovereign_yield
    from .country_risk import sovereign_default_spread

    ccy = normalise_currency(currency)
    sy = sovereign_yield(ccy)
    bond = float(sy["rate"])
    proxy = bool(sy.get("proxy"))
    have_bond = not proxy and sy.get("source") != "fallback"
    instrument = str(sy.get("instrument") or "US 10Y Treasury")

    override = os.getenv(f"RISK_FREE_{ccy}")
    if override:
        try:
            rate = float(override)
        except ValueError:
            rate = None
        if rate is not None and 0.0 <= rate <= 0.25:
            # The operator sets the default-free rate. Corporate debt is still
            # priced off the government bond when there is one to price it off.
            label = f"{ccy} {rate*100:.2f}% (RISK_FREE_{ccy} override)"
            return {"currency": ccy, "rate": rate, "sovereign_yield": bond if have_bond else rate,
                    "instrument": instrument if have_bond else f"RISK_FREE_{ccy} override",
                    "default_spread": 0.0, "default_spread_label": "", "as_of": None,
                    "source": "override", "proxy": False,
                    "sovereign_label": str(sy["label"]) if have_bond else label, "label": label}

    if sy.get("source") == "proxy":
        # A US bond standing in for a currency we cannot source. It is still a
        # US bond, so the US default spread comes out — the currency's own
        # spread does not belong on it.
        spread, spread_label = sovereign_default_spread("USD")
        spread_label = f"US {spread_label}" if spread_label else ""
    elif proxy:
        spread, spread_label = 0.0, ""
    else:
        spread, spread_label = sovereign_default_spread(ccy)
    rate = max(0.0, bond - spread)
    label = str(sy["label"])
    if spread > 0.0:
        label += (f"; less {spread*100:.2f}% sovereign default spread "
                  f"({spread_label}) = {rate*100:.2f}%")
    return {"currency": ccy, "rate": rate, "sovereign_yield": bond, "instrument": instrument,
            "default_spread": spread, "default_spread_label": spread_label,
            "as_of": sy.get("as_of"), "source": sy.get("source"), "proxy": proxy,
            "sovereign_label": str(sy["label"]), "label": label}


def risk_free_rate(currency: Optional[str] = "USD") -> Tuple[float, str]:
    """``(rate, label)`` — see risk_free_details."""
    d = risk_free_details(currency)
    return d["rate"], d["label"]


def _live_risk_free() -> Tuple[float, str]:
    """Backwards-compatible USD entry point."""
    return risk_free_rate("USD")


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _country_risk_details(country: str, currency: str) -> Dict[str, Any]:
    """Resolve the issuer-country premium once with explicit fallback metadata."""
    from .country_risk import (
        country_entry,
        country_risk_premium,
        sovereign_for_currency,
    )

    name = (country or "").strip()
    crp, crp_source = country_risk_premium(name) if name else (0.0, "")
    unmatched = bool(name) and crp == 0.0 and (
        "no country premium on record" in crp_source
    )
    domicile = country_entry(name) if name and not unmatched else None
    assumed_country = None
    if not name or unmatched:
        assumed_country = sovereign_for_currency(currency)
        if assumed_country:
            crp, inner = country_risk_premium(assumed_country)
            why = (
                f"{name} is not in Damodaran's table"
                if name else "no country on record"
            )
            crp_source = (
                f"{why} — {assumed_country} assumed from {currency}: {inner}"
            )
            domicile = country_entry(assumed_country)
        elif not name:
            crp_source = (
                f"no country on record and no sovereign known for {currency} "
                "— no country premium applied"
            )
    return {
        "input_country": name or None,
        "assumed_country": assumed_country,
        "premium": float(crp),
        "source": crp_source,
        "domicile": dict(domicile) if isinstance(domicile, dict) else None,
    }


def collect_market_assumption_snapshot(
    company_data: Dict[str, Any],
) -> Dict[str, Any]:
    """Collect the dated exogenous inputs used by CAPM.

    This belongs to the data-collection layer, not model construction.  A
    financial artifact can then be rebuilt without silently re-querying a new
    sovereign yield, Damodaran table, or beta window.
    """
    from .country_risk import load_table
    from .market_beta import compute_beta
    from .sovereign_rates import normalise_currency

    company = company_data if isinstance(company_data, dict) else {}
    basic = company.get("basic_info") or {}
    currency = normalise_currency(basic.get("currency"))
    symbol = basic.get("symbol") or company.get("ticker")
    risk_free = risk_free_details(currency)
    table = load_table() or {}
    return {
        "schema_version": 1,
        "status": "ready",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "currency": currency,
        "symbol": symbol,
        "risk_free": risk_free,
        "beta_fit": compute_beta(symbol),
        "country_risk": _country_risk_details(
            str(basic.get("country") or ""), currency
        ),
        "mature_equity_risk_premium": _mature_erp(),
        "mature_equity_risk_premium_published": table.get("mature_erp"),
        "mature_equity_risk_premium_source": table.get("source"),
    }


def _saved_market_assumption_snapshot(
    json_data: Optional[Dict[str, Any]], currency: str,
) -> Optional[Dict[str, Any]]:
    """Validate a stored snapshot before it is allowed into a model."""
    value = (
        (json_data or {}).get("market_assumption_snapshot")
        if isinstance(json_data, dict) else None
    )
    if not isinstance(value, dict) or value.get("status") != "ready":
        return None
    if str(value.get("currency") or "").upper() != currency:
        return None
    risk_free = value.get("risk_free")
    country = value.get("country_risk")
    if not isinstance(risk_free, dict) or not isinstance(country, dict):
        return None
    rf = risk_free.get("rate")
    sovereign_yield = risk_free.get("sovereign_yield")
    sovereign_spread = risk_free.get("default_spread")
    erp = value.get("mature_equity_risk_premium")
    crp = country.get("premium")
    valid = (
        isinstance(rf, (int, float)) and not isinstance(rf, bool)
        and math.isfinite(float(rf)) and 0.0 <= float(rf) <= 0.25
        and isinstance(sovereign_yield, (int, float))
        and not isinstance(sovereign_yield, bool)
        and math.isfinite(float(sovereign_yield))
        and -0.01 <= float(sovereign_yield) <= 0.60
        and isinstance(sovereign_spread, (int, float))
        and not isinstance(sovereign_spread, bool)
        and math.isfinite(float(sovereign_spread))
        and 0.0 <= float(sovereign_spread) <= 0.50
        and isinstance(risk_free.get("label"), str)
        and bool(risk_free.get("label"))
        and isinstance(risk_free.get("source"), str)
        and isinstance(risk_free.get("proxy"), bool)
        and isinstance(erp, (int, float)) and not isinstance(erp, bool)
        and math.isfinite(float(erp)) and 0.03 <= float(erp) <= 0.09
        and isinstance(crp, (int, float)) and not isinstance(crp, bool)
        and math.isfinite(float(crp)) and 0.0 <= float(crp) <= 0.30
    )
    if not valid:
        return None
    domicile = country.get("domicile")
    if domicile is not None:
        if not isinstance(domicile, dict):
            return None
        spread = domicile.get("default_spread")
        if (
            not isinstance(domicile.get("name"), str)
            or not isinstance(domicile.get("rating"), str)
            or not isinstance(spread, (int, float))
            or isinstance(spread, bool)
            or not math.isfinite(float(spread))
            or not 0.0 <= float(spread) <= 0.50
        ):
            return None
    fit = value.get("beta_fit")
    if fit is not None:
        if not isinstance(fit, dict):
            return None
        numeric = ("raw", "blume", "r_squared", "observations")
        if any(
            not isinstance(fit.get(key), (int, float))
            or isinstance(fit.get(key), bool)
            or not math.isfinite(float(fit[key]))
            for key in numeric
        ):
            return None
        if not isinstance(fit.get("index"), str) or not isinstance(
            fit.get("window"), str
        ) or not isinstance(fit.get("weak_fit"), bool):
            return None
    return value


def capm_components(company_data: Dict[str, Any],
                    json_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    The full CAPM build, not just the answer.

    This function used to return only ``(wacc, note)`` and discard rf, beta, Ke,
    Kd and the capital-structure weights. That mattered more than it looked:
    the Excel model rebuilt its own cost of capital from hardcoded constants
    (Rf 4.5%, ERP 6.5%, beta 1.2) because the derived inputs were not available
    to write into the cells, so the workbook discounted every company on earth
    at ~11% while the report printed this function's number instead. LVMH was
    valued at EUR 269/share against a market price of EUR 452.

    Returning the components lets the workbook, the report and the recommendation
    all quote one derivation.
    """
    cs = company_data.get("capital_structure", {}) or {}
    md = company_data.get("market_data", {}) or {}
    bi = company_data.get("basic_info", {}) or {}

    from .sovereign_rates import normalise_currency
    currency = normalise_currency(bi.get("currency"))
    snapshot = _saved_market_assumption_snapshot(json_data, currency)
    rfd = dict(snapshot["risk_free"]) if snapshot else risk_free_details(currency)
    rf, rf_source = rfd["rate"], rfd["label"]

    # Beta against the listing's HOME index, computed from price history.
    # Yahoo's `beta` is measured against the S&P 500 for every listing on
    # earth, so every NSE name read 0.1-0.3 and was floored; see market_beta.
    symbol = bi.get("symbol") or (company_data.get("ticker") if isinstance(company_data, dict) else None)
    if snapshot:
        fit = snapshot.get("beta_fit")
    else:
        from .market_beta import compute_beta
        fit = compute_beta(symbol)
    beta_r2 = None
    beta_index = None
    if fit and fit["weak_fit"]:
        # R² below 0.10: the slope is mostly noise. Alnylam regressed at 0.36
        # with R² 0.01, which would hand a biotech an 8% cost of equity. When
        # the market explains little of the stock's movement, the regression
        # slope is not defensible.  But replacing it with 1.00 also discarded
        # a valid provider beta for US-listed names (KO was observed at 0.34,
        # yet valued at beta 1.00 and an overstated WACC).  Yahoo's beta is an
        # S&P 500 beta, so it is an appropriate fallback precisely when the
        # selected benchmark is the S&P 500.  It remains inappropriate for a
        # foreign home-index regression, where neutral beta is safer.
        raw_beta = cs.get("beta")
        try:
            observed_beta = float(raw_beta)
        except (TypeError, ValueError):
            observed_beta = float("nan")
        use_observed = (
            fit.get("index") == "^GSPC"
            and math.isfinite(observed_beta) and observed_beta > 0
        )
        if use_observed:
            beta = _clamp(0.67 * observed_beta + 0.33, _BETA_MIN, _BETA_MAX)
            fallback = (
                f"Yahoo S&P 500 beta {observed_beta:.2f}, Blume-adjusted to "
                f"{beta:.2f}, used instead"
            )
        else:
            beta = 1.0
            fallback = "neutral beta 1.00 used"
        beta_r2 = fit["r_squared"]
        beta_index = fit["index"]
        beta_source = (f"regression vs {fit['index']} is not informative "
                       f"(R²={fit['r_squared']:.2f}, slope {fit['raw']:.2f}); "
                       f"{fallback}")
    elif fit:
        # Blume adjustment: raw betas mean-revert toward 1.0, so every bank
        # shrinks them (2/3 raw + 1/3 market) before CAPM.
        beta = _clamp(fit["blume"], _BETA_MIN, _BETA_MAX)
        beta_r2 = fit["r_squared"]
        beta_index = fit["index"]
        beta_source = (f"{fit['raw']:.2f} vs {fit['index']} ({fit['window']}, "
                       f"n={fit['observations']}, R²={fit['r_squared']:.2f}), Blume-adjusted")
        if abs(beta - fit["blume"]) > 1e-9:
            beta_source += f", clamped to {beta:.2f}"
    else:
        raw_beta = cs.get("beta")
        if raw_beta:
            beta = _clamp(0.67 * float(raw_beta) + 0.33, _BETA_MIN, _BETA_MAX)
            beta_source = (f"Blume-adjusted from Yahoo's {float(raw_beta):.2f} — measured "
                           f"against the S&P 500, not the home index; price history was unavailable")
        else:
            beta = 1.0
            beta_source = "market beta 1.00 (no price history and no observed beta)"

    # Country risk premium on top of the mature-market ERP, Damodaran style:
    # Ke = Rf + beta x (ERP + CRP). Zero only for Aaa sovereigns.
    country = (bi.get("country") or "").strip()
    country_details = (
        dict(snapshot["country_risk"])
        if snapshot else _country_risk_details(country, currency)
    )
    crp = float(country_details["premium"])
    crp_source = str(country_details.get("source") or "")
    domicile = country_details.get("domicile")
    erp = (
        float(snapshot["mature_equity_risk_premium"])
        if snapshot else _mature_erp()
    )
    erp_total = erp + crp
    if snapshot:
        erp_published = snapshot.get("mature_equity_risk_premium_published")
    else:
        from .country_risk import load_table
        erp_published = (load_table() or {}).get("mature_erp")

    tax_details = _effective_tax_rate_details(company_data, json_data)
    tax = tax_details["rate"]
    ke = rf + beta * erp_total
    # Corporate debt is priced off the government bond in the same currency,
    # not off the default-free rate: an Indian issuer borrows above the G-Sec,
    # not above the G-Sec less India's default spread.
    # Kd = default-free rate + the ISSUER's sovereign default spread + a credit
    # spread. A company borrows above its own government, not above the
    # currency's benchmark: an Italian euro issuer sits over the BTP, not the
    # Bund. When domicile and currency sovereign coincide (a US company in
    # dollars, an Indian one in rupees) this is exactly "government yield +
    # spread"; the general form is what keeps Italy, or a UK major reporting
    # in dollars, from being lent to at the AAA rate.
    dom_spread = float(domicile.get("default_spread") or 0.0) if domicile else 0.0
    issuer_credit = _issuer_credit_spread(company_data, json_data)
    credit_spread = issuer_credit["spread"]
    kd_pre_tax = rf + dom_spread + credit_spread
    rf_word = (f"RISK_FREE_{currency} override" if rfd.get("source") == "override"
               else "US 10Y proxy, default-free" if rfd["proxy"] else "default-free")
    kd_parts = [f"risk-free {rf*100:.2f}% ({rf_word})"]
    if domicile and dom_spread > 0:
        kd_parts.append(f"{domicile['name']} sovereign spread {dom_spread*100:.2f}% (Moody's {domicile['rating']})")
    kd_parts.append(issuer_credit["source"])
    kd_source = " + ".join(kd_parts)
    kd_after_tax = kd_pre_tax * (1 - tax)

    equity = float(md.get("market_cap_financial") or 0)
    weights_note = "financial-currency market cap / (market cap + total debt)"
    if equity <= 0:
        raw_equity = md.get("market_cap")
        listing_currency = bi.get("listing_currency") or currency
        fx = md.get("fx_listing_to_financial")
        if (
            listing_currency != currency
            and isinstance(raw_equity, (int, float))
            and isinstance(fx, (int, float))
            and raw_equity > 0 and fx > 0
        ):
            equity = float(raw_equity) * float(fx)
            weights_note = (
                f"market cap converted {listing_currency}->{currency} / "
                "(market cap + total debt)"
            )
        elif listing_currency == currency:
            equity = float(raw_equity or 0)
            weights_note = "market cap / (market cap + total debt)"
        elif isinstance(raw_equity, (int, float)) and raw_equity > 0:
            # Unlike currencies cannot be weighted.  Treating a USD market cap
            # as CNY (or vice versa) is worse than an explicit all-equity
            # fallback and was the source of BABA's false 50% debt weight.
            equity = 0.0
            weights_note = (
                f"market cap is {listing_currency} while debt is {currency}; "
                "FX unavailable — all-equity weights used"
            )
    debt = float(cs.get("total_debt") or 0)
    if equity > 0:
        w_e = equity / (equity + debt)
    else:
        # No market cap on record (Yahoo returned none for Reliance on one
        # day). Treating that as zero equity priced the whole firm at the cost
        # of debt — a 3.8% WACC for India's largest company. Missing equity
        # means we cannot weight; use all-equity and say so.
        w_e = 1.0
        if "all-equity weights used" not in weights_note:
            weights_note = "market cap unavailable — all-equity weights used"
    w_d = 1.0 - w_e

    # The WACC is what the components produce. It is NOT clamped: the workbook
    # recomputes it from the same seeded cells, so altering the number here
    # would put two different rates in one model (13% in the summary, 20% in
    # the DCF tab for PC Jeweller). Out-of-band values are flagged instead.
    raw_wacc = w_e * ke + w_d * kd_after_tax
    wacc = raw_wacc
    # The 6% floor of the disclosure band is a dollar number. A yen or Swiss
    # franc WACC of 4-5% is what those rates produce, not a broken input, so
    # the floor follows the risk-free rate.
    wacc_min = min(_WACC_MIN, rf + 0.02)

    return {
        "currency": currency,
        "market_input_snapshot_status": (
            "saved_snapshot" if snapshot else "legacy_live_collection"
        ),
        "market_input_snapshot_captured_at": (
            snapshot.get("captured_at") if snapshot else None
        ),
        "risk_free_rate": rf,
        "risk_free_source": rf_source,
        "risk_free_as_of": rfd.get("as_of"),
        "risk_free_kind": rfd.get("source"),
        "sovereign_yield": rfd["sovereign_yield"],
        "sovereign_default_spread": rfd["default_spread"],
        "equity_risk_premium": erp,
        "mature_erp_published": erp_published,
        "country_risk_premium": crp,
        "crp_source": crp_source,
        "equity_risk_premium_total": erp_total,
        "beta": beta,
        "beta_source": beta_source,
        "beta_r_squared": beta_r2,
        "beta_index": beta_index,
        "cost_of_equity": ke,
        "pre_tax_cost_of_debt": kd_pre_tax,
        "kd_source": kd_source,
        "issuer_credit_spread": credit_spread,
        "issuer_synthetic_rating": issuer_credit["rating"],
        "issuer_interest_coverage": issuer_credit["coverage"],
        "issuer_interest_coverage_observations": issuer_credit[
            "coverage_observations"
        ],
        "issuer_credit_spread_source": issuer_credit["source"],
        "domicile_default_spread": dom_spread,
        "domicile": domicile["name"] if domicile else None,
        "tax_rate": tax,
        "tax_rate_source": tax_details["source"],
        "tax_rate_observations": tax_details["observations"],
        "after_tax_cost_of_debt": kd_after_tax,
        "equity_value": equity,
        "debt_value": debt,
        "equity_weight": w_e,
        "debt_weight": w_d,
        "weights_note": weights_note,
        "wacc": wacc,
        "wacc_unclamped": raw_wacc,
        # Kept as a flag, not an alteration: a WACC outside [6%, 20%] usually
        # means an input is broken, and the reader should see the number that
        # was actually used alongside the warning.
        "wacc_clamped": not (wacc_min <= wacc <= _WACC_MAX),
        "wacc_band": (wacc_min, _WACC_MAX),
    }


def compute_capm_wacc(company_data: Dict[str, Any],
                      components: Optional[Dict[str, Any]] = None) -> Tuple[float, str]:
    """Deterministic CAPM WACC from scraped beta, live rates, actual D/E."""
    c = components or capm_components(company_data)
    note = (
        f"CAPM WACC {c['wacc']*100:.2f}% (rf {c['risk_free_source']}, "
        f"beta {c['beta']:.2f} [{c['beta_source']}], "
        f"ERP {c['equity_risk_premium']*100:.1f}% + CRP {c['country_risk_premium']*100:.2f}%, "
        f"Ke {c['cost_of_equity']*100:.2f}%, D/(D+E) {c['debt_weight']*100:.0f}%)"
    )
    if c["wacc_clamped"]:
        lo, hi = c.get("wacc_band", (_WACC_MIN, _WACC_MAX))
        note += f" [OUTSIDE the {lo*100:.1f}-{hi*100:.0f}% band — check the inputs]"
    return c["wacc"], note


def _current_shares(md: Dict[str, Any]) -> Optional[float]:
    """
    The share count the per-share bridge should divide by.

    Order of trust:
      1. Yahoo's impliedSharesOutstanding — market cap / price, so it counts
         every share class. sharesOutstanding is Class A only for Alphabet
         (5.9B against 12.2B implied) and misses Samsung's preferreds; dividing
         by it doubled Alphabet's value per share.
      2. sharesOutstanding, but only when it reconciles to the market cap
         within 10% — the same check that exposed the cases above.
      3. None: the workbook falls back to the year-end balance-sheet count.
    """
    implied = md.get("shares_outstanding_implied")
    if isinstance(implied, (int, float)) and implied > 0:
        return float(implied)
    basic = md.get("shares_outstanding_basic")
    # Yahoo market cap follows the listing currency.  The model's
    # ``current_price`` is converted to the statements' currency, so using it
    # here would falsely reject an otherwise reconciling ADR share count.
    mcap = md.get("market_cap")
    px = md.get("current_price_listing") or md.get("current_price")
    if isinstance(basic, (int, float)) and basic > 0:
        if isinstance(mcap, (int, float)) and isinstance(px, (int, float)) and mcap > 0 and px > 0:
            if abs(basic * px / mcap - 1.0) <= 0.10:
                return float(basic)
            return None          # does not reconcile — do not seed a wrong count
        return float(basic)      # nothing to reconcile against; take it
    return None


def _tax_rate_observation(row: Dict[str, Any]) -> Optional[float]:
    """One usable statement-period cash-tax observation, provider field first."""
    calcs = _number(row if isinstance(row, dict) else {}, "Tax Rate For Calcs")
    if calcs is not None and 0.0 < calcs <= 0.5:
        return calcs
    provision = _number(row if isinstance(row, dict) else {}, "Tax Provision")
    pretax = _number(row if isinstance(row, dict) else {}, "Pretax Income")
    if pretax is not None and pretax > 0 and provision is not None:
        ratio = provision / pretax
        if 0.0 < ratio <= 0.5:
            return ratio
    return None


def _tax_rate_from_statements(json_data: Dict[str, Any]) -> Optional[float]:
    """
    The issuer's own effective tax rate, from its latest income statement.

    Mirrors the workbook's Assumptions!B20 formula, including the edge case its
    comment records: Tax Provision / Pretax Income goes NEGATIVE in a
    tax-credit year (PC Jeweller booked a -9.7M provision on 7.1B of pretax
    income), which would discount debt at an after-tax cost ABOVE its pre-tax
    cost. Yahoo's "Tax Rate For Calcs" is preferred when present; the ratio is
    the fallback; both are clamped to (0, 50%].
    """
    bridge = (json_data or {}).get("ttm_bridge") or {}
    if bridge.get("status") == "current":
        rate = _tax_rate_observation(bridge.get("income_statement") or {})
        if rate is not None:
            return rate

    statements = (json_data or {}).get("financial_statements", {}) or {}
    income = statements.get("income_statement", {}) or {}
    periods = sorted((p for p in income if isinstance(p, str)), reverse=True)
    for period in periods:
        row = income.get(period) or {}
        if not isinstance(row, dict):
            continue

        rate = _tax_rate_observation(row)
        if rate is not None:
            return rate
    return None


def _normalized_tax_rate_from_statements(
    json_data: Dict[str, Any],
) -> Tuple[Optional[float], List[float]]:
    """Median current/three-year effective rate for forward NOPAT and WACC.

    A DCF forecasts a normalized cash-tax burden, not one unusually low/high
    fiscal year's tax settlement.  The prior implementation also let Python
    WACC use a TTM ratio while the workbook used the latest annual rate, so one
    model contained two tax assumptions.  Keep up to one current TTM and three
    annual observations, prefer Yahoo's normalized calculation field within
    each period, and use their median.  Sparse companies still use the one
    valid observation rather than manufacturing history.
    """
    observations: List[float] = []
    bridge = (json_data or {}).get("ttm_bridge") or {}
    if bridge.get("status") == "current":
        rate = _tax_rate_observation(bridge.get("income_statement") or {})
        if rate is not None:
            observations.append(rate)
    statements = (json_data or {}).get("financial_statements", {}) or {}
    income = statements.get("income_statement", {}) or {}
    for period in sorted(
        (p for p in income if isinstance(p, str)), reverse=True
    ):
        rate = _tax_rate_observation(income.get(period) or {})
        if rate is not None:
            observations.append(rate)
        if len(observations) >= 4:
            break
    return (
        (float(statistics.median(observations)) if observations else None),
        observations,
    )


def _effective_tax_rate_details(
    company_data: Dict[str, Any],
    json_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Normalized tax rate plus visible provenance for the whole workbook."""
    gp = company_data.get("growth_profitability", {}) or {}
    for key in ("effective_tax_rate", "tax_rate"):
        value = gp.get(key)
        try:
            rate = float(value) if value is not None else None
        except (TypeError, ValueError):
            rate = None
        if rate is not None and 0.0 < rate < 0.6:
            return {
                "rate": rate,
                "source": f"company_data.growth_profitability.{key}",
                "observations": [rate],
            }
    rate, observations = _normalized_tax_rate_from_statements(json_data or {})
    if rate is not None:
        return {
            "rate": rate,
            "source": (
                "median of current TTM and up to three latest valid annual "
                "effective-tax observations"
            ),
            "observations": observations,
        }
    return {
        "rate": _TAX_DEFAULT,
        "source": "25% mature-market fallback; no usable issuer observation",
        "observations": [],
    }


def _effective_tax_rate(company_data: Dict[str, Any],
                        json_data: Optional[Dict[str, Any]] = None) -> float:
    """
    The rate that shields interest. Falls back to a mature-market average
    rather than the US statutory 21%, which is wrong for most of the world and
    was previously applied to every company regardless of domicile.

    THE BUG this fixes: the only source consulted was
    company_data["growth_profitability"], which the scraper NEVER populates
    with a tax rate — checked across all 43 real runs on disk, zero contain
    `effective_tax_rate` or `tax_rate`. So every company on earth was given the
    same hardcoded default while the report presented WACC as derived from that
    issuer's own figures. NVDA's real rate is 17.88%, not 25%: ~19bp of WACC,
    small in itself but a fabricated input on a page whose whole claim is that
    every input is real and sourced.
    """
    return _effective_tax_rate_details(company_data, json_data)["rate"]


def _anchor_path(path: List[float], trailing: float,
                 fy1_band: float = 0.03,
                 fy5_lo: float = 0.05, fy5_hi: float = 0.08) -> Tuple[List[float], bool]:
    """
    Clamp FY1/FY5 to bands around the trailing actual and re-glide linearly.
    Returns (new_path, changed). Only rebuilds the path when a clamp binds.
    """
    if not path or len(path) < 2:
        return path, False
    fy1 = _clamp(path[0], trailing - fy1_band, trailing + fy1_band)
    fy5 = _clamp(path[-1], trailing - fy5_lo, trailing + fy5_hi)
    if abs(fy1 - path[0]) < 1e-9 and abs(fy5 - path[-1]) < 1e-9:
        return path, False
    n = len(path)
    new = [fy1 + (fy5 - fy1) * i / (n - 1) for i in range(n)]
    return new, True


def _ordered_statement_rows(json_data: Dict[str, Any], statement: str) -> List[Dict[str, Any]]:
    rows = (((json_data or {}).get("financial_statements") or {}).get(statement) or {})
    if not isinstance(rows, dict):
        return []
    return [row for _, row in sorted(rows.items(), key=lambda pair: str(pair[0]), reverse=True)
            if isinstance(row, dict)]


def _number(row: Dict[str, Any], *keys: str) -> Optional[float]:
    for key in keys:
        value = row.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            value = float(value)
            if math.isfinite(value):
                return value
    return None


def _selected_number(
    row: Dict[str, Any], *keys: str,
) -> Tuple[Optional[str], Optional[float]]:
    """Return the provider field selected by the same precedence as `_number`.

    The field name matters for balance-sheet point-in-time comparisons. Yahoo
    can expose narrow trade receivables annually but a much broader
    ``Receivables`` bucket quarterly (and likewise for payables). Equal-looking
    numbers from different definitions are not a safe working-capital bridge.
    """
    for key in keys:
        value = _number(row, key)
        if value is not None:
            return key, value
    return None, None


def _current_working_capital_base(
    json_data: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Build a current NWC base only from definition-consistent line items.

    A rolling-twelve-month forecast needs a point-in-time NWC base at the same
    valuation date. It is safe to use the latest quarter only when AR,
    inventory and AP are all present and each resolves to the exact same Yahoo
    field used by the latest annual balance sheet. Otherwise the workbook keeps
    its annual FY0 base; manufacturing a bridge is worse than being stale.
    """
    bridge = (json_data or {}).get("ttm_bridge") or {}
    if bridge.get("status") != "current":
        return None
    current = bridge.get("balance_sheet") or {}
    balance = (((json_data or {}).get("financial_statements") or {}).get(
        "balance_sheet") or {})
    latest = next(
        ((period, row) for period, row in sorted(
            balance.items(), key=lambda pair: str(pair[0]), reverse=True,
        ) if isinstance(row, dict)),
        None,
    )
    if not isinstance(current, dict) or latest is None:
        return None
    annual_period, annual = latest
    definitions = {
        "accounts_receivable": ("Accounts Receivable", "Receivables"),
        "inventory": ("Inventory",),
        "accounts_payable": (
            "Accounts Payable", "Payables", "Payables And Accrued Expenses",
        ),
    }
    components: Dict[str, float] = {}
    fields: Dict[str, str] = {}
    for label, aliases in definitions.items():
        current_field, current_value = _selected_number(current, *aliases)
        annual_field, annual_value = _selected_number(annual, *aliases)
        if (
            current_field is None or annual_field is None
            or current_field != annual_field
            or current_value is None or annual_value is None
            or current_value < 0 or annual_value < 0
        ):
            return None
        components[label] = current_value
        fields[label] = current_field
    return {
        **components,
        "net_working_capital": (
            components["accounts_receivable"]
            + components["inventory"]
            - components["accounts_payable"]
        ),
        "period_end": bridge.get("latest_period"),
        "comparison_period": str(annual_period),
        "fields": fields,
        "method": "current balance sheet; exact annual field definitions",
    }


def _safe_count(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    try:
        number = int(value or 0)
    except (TypeError, ValueError, OverflowError):
        return 0
    return min(max(number, 0), 100_000)


def _positive_number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) and number > 0 else None


def _period_date(value: Any) -> Optional[date]:
    try:
        return datetime.fromisoformat(str(value or "")[:10]).date()
    except (TypeError, ValueError):
        return None


def _next_fiscal_anniversary(value: date) -> date:
    try:
        return value.replace(year=value.year + 1)
    except ValueError:  # February 29
        return value.replace(year=value.year + 1, day=28)


def _rolling_consensus_revenue_path(
    json_data: Dict[str, Any],
    qualified_revenue: Dict[str, Tuple[float, int]],
    terminal_growth: float,
) -> Optional[Dict[str, Any]]:
    """Align annual Street forecasts to a current TTM valuation date.

    Yahoo's 0y/+1y rows are fiscal-year totals. When the latest balance sheet
    is part-way through that fiscal year, treating all of 0y as a future FY1
    cash-flow period double counts elapsed operations. A rolling next-twelve-
    month target is the linear fiscal-progress blend of 0y and +1y. Later NTM
    periods apply the same blend to a deterministic post-consensus fade.
    """
    bridge = (json_data or {}).get("ttm_bridge") or {}
    if bridge.get("status") != "current":
        return None
    base_revenue = _positive_number((bridge.get("normalized") or {}).get("revenue"))
    period_end = _period_date(bridge.get("latest_period"))
    income = (((json_data or {}).get("financial_statements") or {}).get(
        "income_statement") or {})
    latest_annual_key = next(
        (key for key, row in sorted(income.items(), key=lambda pair: str(pair[0]), reverse=True)
         if isinstance(row, dict)),
        None,
    )
    latest_annual_end = _period_date(latest_annual_key)
    if (
        base_revenue is None or period_end is None or latest_annual_end is None
        or not all(key in qualified_revenue for key in ("0y", "+1y"))
    ):
        return None
    next_fiscal_end = _next_fiscal_anniversary(latest_annual_end)
    fiscal_days = (next_fiscal_end - latest_annual_end).days
    elapsed_days = (period_end - latest_annual_end).days
    if fiscal_days <= 0 or not 0 <= elapsed_days <= fiscal_days + 7:
        return None
    progress = min(1.0, max(0.0, elapsed_days / fiscal_days))

    current_fiscal, current_count = qualified_revenue["0y"]
    next_fiscal, next_count = qualified_revenue["+1y"]
    covered_growth = next_fiscal / current_fiscal - 1.0
    if not -0.50 <= covered_growth <= _ABSOLUTE_CONSENSUS_GROWTH_MAX:
        return None
    tail_start = min(covered_growth, _POST_CONSENSUS_GROWTH_CAP)
    annual_targets = [current_fiscal, next_fiscal]
    # The first three factors preserve the existing FY3-FY5 convergence when
    # progress is zero. The terminal factor supplies the extra endpoint needed
    # to blend a fifth rolling period when progress is non-zero.
    for factor in (*_CONSENSUS_FADE_FACTORS, 0.0):
        growth = terminal_growth + (tail_start - terminal_growth) * factor
        annual_targets.append(annual_targets[-1] * (1.0 + growth))

    rolling_targets = [
        annual_targets[index] * (1.0 - progress)
        + annual_targets[index + 1] * progress
        for index in range(5)
    ]
    growth_path = []
    previous = base_revenue
    for target in rolling_targets:
        growth = target / previous - 1.0
        if not -0.50 <= growth <= _ABSOLUTE_CONSENSUS_GROWTH_MAX:
            return None
        growth_path.append(growth)
        previous = target
    return {
        "basis": "rolling_twelve_months",
        "period_end": period_end.isoformat(),
        "latest_annual_end": latest_annual_end.isoformat(),
        "next_fiscal_end": next_fiscal_end.isoformat(),
        "fiscal_year_progress": progress,
        "base_revenue": base_revenue,
        "forecast_revenue": rolling_targets,
        "revenue_growth_rates": growth_path,
        "analyst_counts": {"0y": current_count, "+1y": next_count},
        "method": "fiscal-progress blend of 0y/+1y absolute consensus",
    }


def _historical_margin(json_data: Dict[str, Any], numerator: str) -> List[float]:
    values = []
    bridge = (json_data or {}).get("ttm_bridge") or {}
    if bridge.get("status") == "current":
        row = bridge.get("income_statement") or {}
        revenue = _number(row, "Total Revenue", "Operating Revenue")
        amount = _number(row, numerator)
        if numerator == "EBITDA" and amount is None:
            operating = _number(row, "Operating Income")
            da = _number(
                bridge.get("cash_flow") or {},
                "Depreciation And Amortization",
                "Depreciation Amortization Depletion",
                "Depreciation",
            )
            if operating is not None and da is not None:
                amount = operating + da
        if revenue and revenue > 0 and amount is not None:
            ratio = amount / revenue
            if -0.50 <= ratio <= 1.00:
                values.append(ratio)
    for row in _ordered_statement_rows(json_data, "income_statement"):
        revenue = _number(row, "Total Revenue", "Operating Revenue")
        amount = _number(row, numerator)
        if revenue and revenue > 0 and amount is not None:
            ratio = amount / revenue
            if -0.50 <= ratio <= 1.00:
                values.append(ratio)
        if len(values) >= 3:
            break
    return values


def _deterministic_margin_path(
    trailing: Optional[float], history: List[float], years: int = 5,
) -> Optional[List[float]]:
    observed = [float(value) for value in history if isinstance(value, (int, float))]
    start = float(trailing) if isinstance(trailing, (int, float)) else (observed[0] if observed else None)
    if start is None or not math.isfinite(start):
        return None
    target = statistics.median(observed) if observed else start
    # Historical normalization is bounded so a one-off accounting swing cannot
    # imply implausible multi-year margin movement.
    target = _clamp(target, start - 0.05, start + 0.05)
    if years <= 1:
        return [start]
    return [start + (target - start) * index / (years - 1) for index in range(years)]


def _working_capital_history(json_data: Dict[str, Any], metric: str) -> List[float]:
    statements = (json_data or {}).get("financial_statements") or {}
    income = statements.get("income_statement") or {}
    balance = statements.get("balance_sheet") or {}
    periods = sorted(set(income).intersection(balance), key=str, reverse=True)
    values = []
    # Keep the driver series and FY0 base on the same fiscal-period basis.
    # Quarterly Yahoo schemas often omit the narrow AR/AP rows or change their
    # scope (BABA's latest quarter exposed broad Receivables but only tax
    # Payables). Combining those with an annual FY0 base manufactured a CNY
    # 275B working-capital outflow. TTM remains the source for margins,
    # reinvestment and the equity bridge; working-capital days use consistent
    # annual fields until four-quarter canonical WC coverage is available.
    for period in periods:
        inc = income.get(period) or {}
        bal = balance.get(period) or {}
        revenue = _number(inc, "Total Revenue", "Operating Revenue")
        cogs = _number(inc, "Cost Of Revenue", "Reconciled Cost Of Revenue")
        if metric == "dso_days":
            # Prefer the narrow trade-working-capital lines. Broad Receivables
            # and Payables/Accrued Expenses can include tax, notes, payroll and
            # other balances that do not turn with revenue/COGS. J&J exposed
            # both: using broad payables for FY0 but a narrow DPO forecast
            # manufactured a $30.5B FY1 working-capital outflow.
            numerator = _number(bal, "Accounts Receivable", "Receivables")
            denominator = revenue
        elif metric == "dio_days":
            numerator = _number(bal, "Inventory")
            denominator = cogs
        else:
            numerator = _number(
                bal, "Accounts Payable", "Payables",
                "Payables And Accrued Expenses"
            )
            denominator = cogs
        if numerator is not None and denominator and denominator > 0:
            days = numerator / denominator * 365.0
            if 0 <= days <= 365:
                values.append(days)
        if len(values) >= 3:
            break
    return values


def _normalized_history_path(values: List[float], years: int = 5) -> Optional[List[float]]:
    if not values:
        return None
    start = float(values[0])
    target = statistics.median(values)
    target = _clamp(target, max(0.0, start - 30.0), start + 30.0)
    return [start + (target - start) * index / (years - 1) for index in range(years)]


def ground_assumptions(
    assumptions: Dict[str, Any],
    json_data: Dict[str, Any],
) -> Tuple[Dict[str, Any], List[str]]:
    """
    Apply deterministic grounding to the initial source-derived assumptions.
    Returns (adjusted_assumptions, notes) — notes describe every override.
    """
    a = dict(assumptions or {})
    notes: List[str] = []
    company_data = (json_data or {}).get("company_data", {}) or {}
    gp = company_data.get("growth_profitability", {}) or {}
    vm = company_data.get("valuation_metrics", {}) or {}
    bridge = (json_data or {}).get("ttm_bridge") or {}
    current_bridge = bridge if bridge.get("status") == "current" else {}

    # 1. WACC — always deterministic (the LLM's guess is discarded).
    llm_wacc = a.get("wacc")
    capm = capm_components(company_data, json_data)
    wacc, wacc_note = compute_capm_wacc(company_data, components=capm)
    a["wacc"] = wacc
    # Publish the derivation, not just the answer. The workbook writes these into
    # the Assumptions tab so its CAPM cells stop being hardcoded constants, and
    # the report prints them so the discount rate can be argued with.
    a["capm"] = capm
    # Current share count for the per-share bridge. The workbook otherwise
    # divides by last year's diluted AVERAGE, which lags issuance and buybacks.
    md = company_data.get("market_data", {}) or {}
    a["shares_outstanding_current"] = _current_shares(md)
    if llm_wacc is not None and abs(llm_wacc - wacc) > 0.005:
        notes.append(f"WACC {llm_wacc*100:.2f}% (LLM) -> {wacc_note}")
    else:
        notes.append(wacc_note)

    # 2. Terminal growth — a deterministic long-run base, capped at the
    #    currency's risk-free rate. Letting a prose model choose anywhere in a
    #    superficially safe 2-3% band still moved the most valuation-sensitive
    #    DCF input between identical runs. Company-specific uncertainty belongs
    #    in the sensitivity table, not in an unexplained point assumption.
    requested_tg = a.get("terminal_growth_rate")
    tg_c = _TERMINAL_GROWTH_BASE
    if isinstance(requested_tg, (int, float)) and not isinstance(requested_tg, bool):
        if math.isfinite(float(requested_tg)) and abs(float(requested_tg) - tg_c) > 1e-9:
            notes.append(
                f"Terminal growth {float(requested_tg)*100:.2f}% (model) -> "
                f"{tg_c*100:.2f}% deterministic long-run base"
            )
    # A company cannot outgrow its currency's economy forever, and the
    # risk-free rate is the market's estimate of that economy's long-run
    # nominal growth (Damodaran's cap). The 2-3% band is a dollar band:
    # once yen and yuan cash flows were discounted at their own rates, a
    # 2.5% perpetuity against a 2.3% JPY or 1.1% CNY risk-free rate put
    # Toyota at 2.5x its price and Alibaba at 1.5x — the terminal value,
    # not the business, was doing the valuing.
    rf_cap = capm.get("risk_free_rate")
    if isinstance(rf_cap, (int, float)) and tg_c > rf_cap:
        tg_c = max(0.0, float(rf_cap))
        terminal_note = (
            f"deterministic {_TERMINAL_GROWTH_BASE*100:.2f}% long-run base capped "
            f"at the {capm.get('currency')} risk-free rate {tg_c*100:.2f}% — "
            "a perpetuity cannot outgrow its currency's economy"
        )
        notes.append(f"Terminal growth {terminal_note}")
    else:
        terminal_note = (
            f"deterministic {_TERMINAL_GROWTH_BASE*100:.2f}% long-run nominal "
            "growth base"
        )
    a["terminal_growth_note"] = terminal_note
    a["terminal_growth_rate"] = tg_c

    # 3. Profitable-company margins are observable operating inputs, not creative
    #    writing.  Start at the current trailing margin and normalize to the
    #    median of the last three fiscal years.  This makes identical source
    #    data produce identical cash flows while retaining LLM judgment only
    #    for genuinely loss-making paths. The old 5% eligibility cutoff treated
    #    structurally low-margin but mature businesses as if they were pre-profit:
    #    Walmart's observed 4.2% margin was replaced by an ungrounded 25% path,
    #    inflating FY10 FCF from roughly $30B to $200B. Positive profitability,
    #    not a software-like margin threshold, is the correct boundary.
    bridge_income = current_bridge.get("income_statement") or {}
    bridge_cash = current_bridge.get("cash_flow") or {}
    bridge_revenue = _number(bridge_income, "Total Revenue", "Operating Revenue")
    bridge_operating = _number(bridge_income, "Operating Income")
    bridge_gross = _number(bridge_income, "Gross Profit")
    bridge_da = _number(
        bridge_cash, "Depreciation And Amortization",
        "Depreciation Amortization Depletion", "Depreciation",
    )
    t_om = (
        bridge_operating / bridge_revenue
        if bridge_revenue and bridge_operating is not None else gp.get("operating_margins")
    )
    t_em = (
        (bridge_operating + bridge_da) / bridge_revenue
        if bridge_revenue and bridge_operating is not None and bridge_da is not None
        else gp.get("ebitda_margins")
    )
    t_gm = (
        bridge_gross / bridge_revenue
        if bridge_revenue and bridge_gross is not None else gp.get("gross_margins")
    )
    operating_history = _historical_margin(json_data, "Operating Income")
    operating_anchor = (
        float(t_om) if isinstance(t_om, (int, float)) and not isinstance(t_om, bool)
        else (operating_history[0] if operating_history else None)
    )
    if operating_anchor is not None and operating_anchor > 0:
        for key, trailing, label, statement_field, history in (
            ("operating_margins", t_om, "operating", "Operating Income", operating_history),
            ("ebitda_margins", t_em, "EBITDA", "EBITDA", None),
            ("gross_margins", t_gm, "gross", "Gross Profit", None),
        ):
            new = _deterministic_margin_path(
                trailing, history if history is not None else _historical_margin(json_data, statement_field)
            )
            if new:
                a[key] = new
                notes.append(
                    f"{label} margin path grounded to observed results: "
                    f"FY1 trailing {new[0]*100:.1f}% -> FY5 normalized "
                    f"three-year median {new[-1]*100:.1f}%"
                )

        # Internal consistency: EBITDA >= operating and gross >= operating.
        # Gross profit does NOT have to exceed EBITDA when depreciation sits
        # in cost of revenue. TSM is the clearest case: adding foundry D&A back
        # to EBIT puts EBITDA above gross profit. The old ordering inflated
        # projected gross margin to the EBITDA margin and rewrote COGS.
        oms = a.get("operating_margins") or []
        ems = list(a.get("ebitda_margins") or [])
        gms = list(a.get("gross_margins") or [])
        for i in range(min(len(oms), len(ems))):
            ems[i] = max(ems[i], oms[i])
        for i in range(min(len(oms), len(gms))):
            gms[i] = max(gms[i], oms[i])
        if ems:
            a["ebitda_margins"] = ems
        if gms:
            a["gross_margins"] = gms

    # Working-capital days are likewise mechanical historical ratios.  Use the
    # latest year and glide to the three-year median instead of accepting a
    # different LLM guess on each run.
    grounded_working_capital = []
    for key, label in (("dso_days", "DSO"), ("dio_days", "DIO"), ("dpo_days", "DPO")):
        history = _working_capital_history(json_data, key)
        path = _normalized_history_path(history)
        if path:
            a[key] = path
            grounded_working_capital.append(
                f"{label} {path[0]:.1f}->{path[-1]:.1f} days"
            )
    if grounded_working_capital:
        a["working_capital_source"] = "latest_actual_to_three_year_median"
        notes.append("Working capital grounded to statements: " + ", ".join(grounded_working_capital))

    # Current quarterly balance sheet and TTM reinvestment intensities update
    # the places where an annual snapshot goes stale. Revenue is replaced below
    # by a rolling consensus bridge when the current TTM and both covered annual
    # endpoints are available.
    if current_bridge:
        normalized = current_bridge.get("normalized") or {}
        basis = {
            "basis": "ttm",
            "period_end": current_bridge.get("latest_period"),
            "quarter_periods": current_bridge.get("quarter_periods") or [],
        }
        for key in (
            "capex_to_revenue", "da_to_revenue", "cash",
            "short_term_investments", "non_operating_investments",
            "total_debt",
        ):
            value = normalized.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)):
                basis[key] = float(value)
        investment_source = normalized.get("non_operating_investments_source")
        if investment_source:
            basis["non_operating_investments_source"] = str(investment_source)
        current_working_capital = _current_working_capital_base(json_data)
        if current_working_capital and len(grounded_working_capital) == 3:
            basis["working_capital"] = current_working_capital
        a["modeling_basis"] = basis
        notes.append(
            f"TTM/current balance-sheet bridge used through {basis['period_end']} "
            "for reinvestment intensity and the equity bridge"
        )
        if current_working_capital and len(grounded_working_capital) == 3:
            notes.append(
                "Current working-capital base used through "
                f"{current_working_capital['period_end']} with definition-matched "
                "AR, inventory and AP fields"
            )

    # Near-term revenue is an observable consensus input, not something the
    # language model should replace with a generic mature-company curve. The
    # Yahoo estimate table maps 0y/+1y to the first two unreported fiscal
    # years. Once both anchors have real breadth, FY3-FY5 follow a deterministic
    # convergence curve toward terminal growth. Previously those years were
    # whatever JSON the LLM happened to return: two identical AAPL runs could
    # use 7/4.5/3% or 7.5/6/5% and publish different valuations.
    revenue_estimates = ((json_data or {}).get("analyst_data", {}) or {}).get(
        "revenue_estimates", {}) or {}
    growth_path = a.get("revenue_growth_rates")
    if isinstance(growth_path, list) and len(growth_path) >= 2:
        grounded_growth = [float(value) for value in growth_path]
        used = []
        try:
            minimum_analysts = max(5, int(os.getenv("ANALYST_CONSENSUS_MIN_ANALYSTS", "5") or 5))
        except ValueError:
            minimum_analysts = 5
        annual_rows = _ordered_statement_rows(json_data, "income_statement")
        latest_annual_revenue = (
            _positive_number(_number(
                annual_rows[0], "Total Revenue", "Operating Revenue"
            )) if annual_rows else None
        )
        qualified_revenue = {}
        for period in ("0y", "+1y"):
            estimate = revenue_estimates.get(period) or {}
            average = _positive_number(estimate.get("avg"))
            count = _safe_count(estimate.get("numberOfAnalysts"))
            if average is not None and count >= minimum_analysts:
                qualified_revenue[period] = (average, count)
        terminal = float(a.get("terminal_growth_rate") or _TG_MIN)
        rolling = _rolling_consensus_revenue_path(
            json_data, qualified_revenue, terminal
        )
        if rolling:
            grounded_growth = rolling["revenue_growth_rates"]
            a["forecast_basis"] = rolling
            if isinstance(a.get("modeling_basis"), dict):
                a["modeling_basis"]["forecast_basis"] = rolling
                a["modeling_basis"]["revenue"] = rolling["base_revenue"]
            used = [
                f"NTM{index + 1} {growth * 100:.1f}% "
                f"(rolling revenue {rolling['forecast_revenue'][index]:,.0f})"
                for index, growth in enumerate(grounded_growth)
            ]
            used.append(
                f"fiscal progress {rolling['fiscal_year_progress'] * 100:.1f}% "
                f"at {rolling['period_end']}; 0y/+1y consensus blended without "
                "counting elapsed fiscal operations as future cash flow"
            )
            a["revenue_growth_rates"] = grounded_growth
            a["revenue_growth_source"] = (
                "yahoo_analyst_consensus_rolling_twelve_months_with_deterministic_fade"
            )
            notes.append("Revenue growth anchored to consensus: " + ", ".join(used))
        else:
            for offset, period in enumerate(("0y", "+1y")):
                estimate = revenue_estimates.get(period) or {}
                count = _safe_count(estimate.get("numberOfAnalysts"))
                growth = None
                anchor_note = None
                # Absolute revenue estimates are the actual Street forecast.
                # Derive the workbook driver from those dollars so the model
                # reconciles exactly to the benchmark.
                if period == "0y" and latest_annual_revenue is not None and period in qualified_revenue:
                    average, count = qualified_revenue[period]
                    growth = average / latest_annual_revenue - 1.0
                    anchor_note = f"absolute revenue {average:,.0f}"
                elif period == "+1y" and all(
                    key in qualified_revenue for key in ("0y", "+1y")
                ):
                    previous, _ = qualified_revenue["0y"]
                    average, count = qualified_revenue[period]
                    growth = average / previous - 1.0
                    anchor_note = f"absolute revenue {average:,.0f}"
                else:
                    growth = estimate.get("growth")
                maximum_growth = (
                    _ABSOLUTE_CONSENSUS_GROWTH_MAX if anchor_note else 1.00
                )
                if (isinstance(growth, (int, float)) and not isinstance(growth, bool)
                        and math.isfinite(float(growth))
                        and -0.50 <= float(growth) <= maximum_growth
                        and isinstance(count, (int, float)) and count >= minimum_analysts):
                    grounded_growth[offset] = float(growth)
                    used.append(
                        f"FY{offset + 1} {float(growth) * 100:.1f}% "
                        f"({int(count)} analysts"
                        + (f"; {anchor_note}" if anchor_note else "")
                        + ")"
                    )
            if used:
                if len(used) == 2 and len(grounded_growth) >= 5:
                    fy2 = grounded_growth[1]
                    tail_start = min(fy2, _POST_CONSENSUS_GROWTH_CAP)
                    grounded_growth[2:5] = [
                        terminal + (tail_start - terminal) * factor
                        for factor in _CONSENSUS_FADE_FACTORS
                    ]
                    if fy2 > _POST_CONSENSUS_GROWTH_CAP:
                        a["post_consensus_growth_capped"] = True
                        used.append(
                            "uncovered tail capped at 100.0% before deterministic fade"
                        )
                    used.append(
                        "FY3-FY5 deterministic fade to terminal growth "
                        f"({grounded_growth[2]*100:.1f}%/{grounded_growth[3]*100:.1f}%/"
                        f"{grounded_growth[4]*100:.1f}%)"
                    )
                a["revenue_growth_rates"] = grounded_growth
                a["revenue_growth_source"] = (
                    "yahoo_analyst_consensus_absolute_revenue_with_deterministic_fade"
                    if len(qualified_revenue) == 2 and len(used) >= 3 else
                    "yahoo_analyst_consensus_with_deterministic_fade"
                    if len(used) == 3 else "yahoo_analyst_consensus_near_term"
                )
                notes.append("Revenue growth anchored to consensus: " + ", ".join(used))

    # 4. Exit multiple — company-specific, never one-size-fits-all.
    # Do not apply an unexplained blanket haircut. The former 0.8x rule asserted
    # exactly 20% multiple compression for every issuer, sector and cycle. Start
    # with the observable multiple and let the terminal cash-conversion and
    # sustainable-growth ceiling do the economically grounded compression.
    cur = vm.get("enterprise_to_ebitda")
    valid_current_multiple = (
        isinstance(cur, (int, float)) and not isinstance(cur, bool)
        and math.isfinite(float(cur))
        and _EXIT_PROVIDER_MIN <= float(cur) <= _EXIT_PROVIDER_MAX
    )
    if valid_current_multiple:
        exit_m = float(cur)
        notes.append(
            f"Exit-multiple reference {exit_m:.1f}x from current EV/EBITDA "
            f"{float(cur):.1f}x (no arbitrary de-rating or floor)"
        )
        a["exit_multiple_available"] = True
        a["exit_multiple_source"] = "current_ev_ebitda"
    else:
        exit_m = 0.0
        notes.append(
            "Exit-multiple DCF unavailable: current EV/EBITDA is missing, "
            "non-positive, non-finite, or outside the provider-validity boundary; "
            "no generic terminal multiple was invented"
        )
        a["exit_multiple_available"] = False
        a["exit_multiple_source"] = "unavailable"
    # Record the growth ceiling the WORKBOOK will use to cap the multiple.
    #
    # Everything above sources the exit multiple from what the company trades
    # at TODAY, which embeds today's growth expectations. It is then applied to
    # a terminal year in which growth has already decayed to perpetuity levels
    # — assuming no multiple compression despite growth collapsing.
    #
    # Replaying 34 production models showed how systematic that is: 28 assumed
    # an exit multiple implying perpetual growth ABOVE nominal GDP (one implied
    # 7.29% forever against a perpetuity assuming 2.5%), and only 2 were
    # internally consistent. That single unstated assumption is the bulk of the
    # gap between the two DCF legs — the thing the dispersion rail could only
    # report after the fact.
    #
    # The previous implementation applied the identity here with the latest
    # HISTORICAL FCF / EBITDA ratio. That is not terminal cash conversion. It
    # silently treated current growth investment as permanent: MSFT's 32%
    # historical conversion cut a 15.3x input to 6.4x even though the completed
    # projection normalized to 61%. The exit tab already has both projected
    # FY5 FCF and EBITDA, so that is the first point where a defensible cap can
    # be calculated. Keep the observable input intact until then.
    from src.agents.fm.terminal_value import sustainable_growth_cap
    g_cap = sustainable_growth_cap(capm.get("risk_free_rate"))
    a["sustainable_growth_cap"] = g_cap
    horizon = (
        "NTM10" if (a.get("forecast_basis") or {}).get("basis")
        == "rolling_twelve_months" else "FY10"
    )
    notes.append(
        f"Exit-multiple sustainability cap deferred to projected {horizon} cash "
        f"conversion (perpetual growth ceiling {g_cap*100:.2f}%)"
    )

    a["exit_multiple"] = exit_m

    # 5. Market-comps parameters. A qualified comparable set can become the
    # second methodology in the headline blend; a broad-sector fallback is
    # retained only as explicitly excluded context. Require at least three
    # actual peers. A company's own current multiple is not a comparable-company
    # method: applying it to its own forecast merely echoes today's market
    # pricing, so an unavailable provider leaves this leg absent.
    peer_comps = (((json_data or {}).get("industry_data") or {}).get("peer_comps") or {})
    peer_ev = peer_comps.get("median_ev_ebitda")
    peer_ps = peer_comps.get("median_price_sales")
    peer_ev_count = _safe_count(peer_comps.get("ev_ebitda_peer_count"))
    peer_ps_count = _safe_count(peer_comps.get("price_sales_peer_count"))
    ev_eb = vm.get("enterprise_to_ebitda")
    ps = vm.get("price_to_sales")
    ev_from_peers = bool(peer_ev and peer_ev > 0 and peer_ev_count >= 3)
    ps_from_peers = bool(peer_ps and peer_ps > 0 and peer_ps_count >= 3)
    if ev_from_peers:
        a["comps_ev_ebitda"] = _clamp(float(peer_ev), 4.0, 30.0)
    else:
        a["comps_ev_ebitda"] = 0.0
    if ps_from_peers:
        a["comps_ps"] = _clamp(float(peer_ps), 0.5, 40.0)
    else:
        a["comps_ps"] = 0.0
    real_peers = ev_from_peers or ps_from_peers
    a["comps_ev_source"] = "finnhub_peer_median" if ev_from_peers else "unavailable"
    a["comps_ps_source"] = "finnhub_peer_median" if ps_from_peers else "unavailable"
    a["comps_source"] = (
        a["comps_ev_source"] if a["comps_ev_source"] == a["comps_ps_source"]
        else "partial_finnhub_peer_median"
    )
    selected_method = (
        "ev_ebitda" if ev_from_peers else "price_sales" if ps_from_peers else None
    )
    a["comps_selected_method"] = selected_method
    a["comps_peer_count"] = (
        peer_ev_count if selected_method == "ev_ebitda" else
        peer_ps_count if selected_method == "price_sales" else 0
    )
    from src.valuation_methodology import normalize_peer_comps_policy
    comps_policy = normalize_peer_comps_policy(peer_comps)
    a["comps_confidence"] = comps_policy["confidence"]
    a["comps_role"] = comps_policy["role"]
    a["comps_included_in_blended_value"] = comps_policy["included_in_blended_value"]
    a["comps_horizon_years"] = 2
    # EV/EBITDA produces enterprise value and is discounted at WACC. P/S
    # produces equity value and must use the cost of equity instead.
    a["comps_enterprise_discount_rate"] = a.get("wacc")
    # cost_of_equity lives inside the capm block published at a["capm"], never
    # on `a` itself — unlike wacc on the line above, which IS a top-level key
    # (set at :531 beside a["capm"] at :535). Reading it off `a` made this
    # unconditionally None. Nothing consumes the key yet, so no valuation was
    # wrong; it was a trap set for the first reader who trusted the name.
    a["comps_equity_discount_rate"] = a.get("capm", {}).get("cost_of_equity")
    fg = company_data.get("forward_guidance", {}) or {}
    consensus = company_data.get("analyst_consensus", {}) or {}
    target_meta = consensus.get("price_target", {}) or {}
    recommendation_meta = consensus.get("recommendation", {}) or {}
    # The normalized source-owned block is authoritative where present. The
    # legacy guidance mirror is retained only for artifacts/providers which do
    # not yet carry that block.
    target_mean = _positive_number(
        target_meta.get("mean") if target_meta else fg.get("target_mean_price")
    )
    a["analyst_target_mean"] = target_mean or 0.0
    a["analyst_target_low"] = _positive_number(target_meta.get("low")) or 0.0
    a["analyst_target_high"] = _positive_number(target_meta.get("high")) or 0.0
    a["analyst_count"] = _safe_count(target_meta.get("analyst_count"))
    a["analyst_consensus_source"] = target_meta.get("source")
    a["analyst_consensus_as_of"] = target_meta.get("as_of")
    a["analyst_consensus_captured_at"] = consensus.get("captured_at")
    a["analyst_consensus_rating"] = recommendation_meta.get("label")
    a["analyst_consensus_rating_count"] = max(
        _safe_count(recommendation_meta.get("total")),
        _safe_count(recommendation_meta.get("unique_analyst_count")),
        _safe_count(recommendation_meta.get("analyst_count")),
    )
    a["analyst_consensus_rating_source"] = recommendation_meta.get("source")
    if a["comps_ev_ebitda"] or a["comps_ps"]:
        notes.append(
            f"Comps leg (EV/EBITDA {a['comps_ev_source']}; "
            f"P/S {a['comps_ps_source']}"
            + (f"; {a['comps_peer_count']} {selected_method or ''} peers" if real_peers else "")
            + f"): EV/EBITDA {a['comps_ev_ebitda']:.1f}x / "
            f"P/S {a['comps_ps']:.1f}x on FY2 projections"
            + ("; low-confidence broad-sector cross-check excluded from blended fair value"
               if real_peers and not a["comps_included_in_blended_value"] else "")
            + (f"; analyst mean target {a['analyst_target_mean']:.2f} "
               f"({a['analyst_count']} analysts, {a['analyst_consensus_source'] or 'source unavailable'})"
               if a["analyst_target_mean"] else "")
        )

    return a, notes
