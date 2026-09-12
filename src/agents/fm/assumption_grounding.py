"""
assumption_grounding.py — deterministic guardrails over LLM-inferred
modeling assumptions.

The LLM is good at the STORY (growth trajectory, margin convergence for a
hypergrowth name) and unreliable on PARAMETERS a bank computes mechanically.
Left alone it guessed WACC 11.14% for Alphabet (CAPM says ~8.7%), started
margin paths below what the company already achieves, and every model shipped
a hardcoded 20.0x exit multiple regardless of sector. Each bias compounds
into fair values 30-50% off.

This module grounds those parameters from observable data AFTER inference:

  * WACC        — CAPM: the 10Y government yield in the cash flows' own
                  currency less the sovereign's default spread (sovereign_rates,
                  country_risk), beta regressed on the home index and
                  Blume-adjusted (market_beta), a 5.5% mature-market ERP plus
                  Damodaran's country premium, blended with after-tax cost of
                  debt (government yield + spread) at actual D/E weights.
  * Terminal g  — clamped to [2.0%, 3.0%], then capped at the currency's
                  risk-free rate.
  * Margin paths— for companies with ESTABLISHED profitability (trailing
                  operating margin >= 5%), the path is anchored to trailing
                  actuals: FY1 within +/-3pts, FY5 within [-5, +8]pts, linear
                  glide between. Hypergrowth/loss-making names keep the LLM's
                  convergence path untouched — that path IS the story there.
  * Exit multiple— 0.8x the company's CURRENT EV/EBITDA (a 20% de-rating
                  over five years), clamped to [8x, 22x]; 15x fallback when
                  current EV/EBITDA is unavailable or negative. The workbook
                  can reduce it further from projected FY5 cash conversion.

Every override is returned as a human-readable note and logged, so the
workbook's provenance stays auditable.
"""

from __future__ import annotations

import math
import os
from typing import Any, Dict, List, Optional, Tuple

_ERP = 0.055                # mature-market equity risk premium; in the range
                            # Damodaran publishes for developed markets, and the
                            # figure a sell-side DCF on a euro large-cap would use
_DEBT_SPREAD = 0.015        # cost of debt = government yield + spread
_TAX_DEFAULT = 0.25         # mature-market average; overridden by the
                            # company's own effective rate when available
_BETA_MIN, _BETA_MAX = 0.5, 2.0
_WACC_MIN, _WACC_MAX = 0.06, 0.20   # disclosure band, not a clamp
_TG_MIN, _TG_MAX = 0.02, 0.03
_EXIT_HAIRCUT = 0.8
# Terminal-year multiples above ~22x are rarely defensible in any sector.
_EXIT_MIN, _EXIT_MAX = 8.0, 22.0
_EXIT_FALLBACK = 15.0
_ESTABLISHED_OM = 0.05      # margin anchoring applies above this trailing OM


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
    rfd = risk_free_details(currency)
    rf, rf_source = rfd["rate"], rfd["label"]

    # Beta against the listing's HOME index, computed from price history.
    # Yahoo's `beta` is measured against the S&P 500 for every listing on
    # earth, so every NSE name read 0.1-0.3 and was floored; see market_beta.
    from .market_beta import compute_beta
    from .country_risk import country_risk_premium, sovereign_for_currency, load_table, country_entry
    symbol = bi.get("symbol") or (company_data.get("ticker") if isinstance(company_data, dict) else None)
    fit = compute_beta(symbol)
    beta_r2 = None
    beta_index = None
    if fit and fit["weak_fit"]:
        # R² below 0.10: the slope is mostly noise. Alnylam regressed at 0.36
        # with R² 0.01, which would hand a biotech an 8% cost of equity. When
        # the market explains nothing of the stock's movement the defensible
        # beta is the market's own, and the reader is told why.
        beta = 1.0
        beta_r2 = fit["r_squared"]
        beta_index = fit["index"]
        beta_source = (f"regression vs {fit['index']} is not informative "
                       f"(R²={fit['r_squared']:.2f}, slope {fit['raw']:.2f}); market beta 1.00 used")
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
    crp, crp_source = country_risk_premium(country) if country else (0.0, "")
    unmatched = bool(country) and crp == 0.0 and "no country premium on record" in crp_source
    domicile = country_entry(country) if country and not unmatched else None
    if not country or unmatched:
        # No domicile on record, or a name the table does not carry ("Jersey"
        # before it was aliased). The risk-free build above has already taken
        # the currency's sovereign default spread out of Rf; pricing no
        # premium back in would leave that company cheaper than a neighbour
        # whose country string matched. Assume the currency's sovereign, and
        # say so.
        assumed = sovereign_for_currency(currency)
        if assumed:
            crp, inner = country_risk_premium(assumed)
            why = f"{country} is not in Damodaran's table" if country else "no country on record"
            crp_source = f"{why} — {assumed} assumed from {currency}: {inner}"
            domicile = country_entry(assumed)
        elif not country:
            crp_source = (f"no country on record and no sovereign known for {currency} "
                          f"— no country premium applied")
    erp = _mature_erp()
    erp_total = erp + crp
    erp_published = (load_table() or {}).get("mature_erp")

    tax = _effective_tax_rate(company_data, json_data)
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
    kd_pre_tax = rf + dom_spread + _DEBT_SPREAD
    rf_word = (f"RISK_FREE_{currency} override" if rfd.get("source") == "override"
               else "US 10Y proxy, default-free" if rfd["proxy"] else "default-free")
    kd_parts = [f"risk-free {rf*100:.2f}% ({rf_word})"]
    if domicile and dom_spread > 0:
        kd_parts.append(f"{domicile['name']} sovereign spread {dom_spread*100:.2f}% (Moody's {domicile['rating']})")
    kd_parts.append(f"{_DEBT_SPREAD*100:.1f}% credit spread")
    kd_source = " + ".join(kd_parts)
    kd_after_tax = kd_pre_tax * (1 - tax)

    equity = float(md.get("market_cap") or 0)
    debt = float(cs.get("total_debt") or 0)
    weights_note = "market cap / (market cap + total debt)"
    if equity > 0:
        w_e = equity / (equity + debt)
    else:
        # No market cap on record (Yahoo returned none for Reliance on one
        # day). Treating that as zero equity priced the whole firm at the cost
        # of debt — a 3.8% WACC for India's largest company. Missing equity
        # means we cannot weight; use all-equity and say so.
        w_e = 1.0
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
        "domicile_default_spread": dom_spread,
        "domicile": domicile["name"] if domicile else None,
        "tax_rate": tax,
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
    mcap, px = md.get("market_cap"), md.get("current_price")
    if isinstance(basic, (int, float)) and basic > 0:
        if isinstance(mcap, (int, float)) and isinstance(px, (int, float)) and mcap > 0 and px > 0:
            if abs(basic * px / mcap - 1.0) <= 0.10:
                return float(basic)
            return None          # does not reconcile — do not seed a wrong count
        return float(basic)      # nothing to reconcile against; take it
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
    statements = (json_data or {}).get("financial_statements", {}) or {}
    income = statements.get("income_statement", {}) or {}
    periods = sorted((p for p in income if isinstance(p, str)), reverse=True)
    for period in periods:
        row = income.get(period) or {}
        if not isinstance(row, dict):
            continue

        calcs = row.get("Tax Rate For Calcs")
        try:
            rate = float(calcs) if calcs is not None else None
        except (TypeError, ValueError):
            rate = None
        if rate is not None and 0.0 < rate <= 0.5:
            return rate

        try:
            provision = float(row.get("Tax Provision"))
            pretax = float(row.get("Pretax Income"))
        except (TypeError, ValueError):
            continue
        if pretax > 0:
            ratio = provision / pretax
            if 0.0 < ratio <= 0.5:
                return ratio
    return None


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
    gp = company_data.get("growth_profitability", {}) or {}
    for key in ("effective_tax_rate", "tax_rate"):
        value = gp.get(key)
        if value is not None:
            try:
                rate = float(value)
            except (TypeError, ValueError):
                continue
            if 0.0 < rate < 0.6:
                return rate

    from_statements = _tax_rate_from_statements(json_data or {})
    if from_statements is not None:
        return from_statements
    return _TAX_DEFAULT


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


def ground_assumptions(
    assumptions: Dict[str, Any],
    json_data: Dict[str, Any],
) -> Tuple[Dict[str, Any], List[str]]:
    """
    Apply deterministic grounding to LLM-inferred assumptions.
    Returns (adjusted_assumptions, notes) — notes describe every override.
    """
    a = dict(assumptions or {})
    notes: List[str] = []
    company_data = (json_data or {}).get("company_data", {}) or {}
    gp = company_data.get("growth_profitability", {}) or {}
    vm = company_data.get("valuation_metrics", {}) or {}

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

    # 2. Terminal growth — clamp, then cap at the currency's risk-free rate.
    tg = a.get("terminal_growth_rate")
    if tg is not None:
        tg_c = _clamp(float(tg), _TG_MIN, _TG_MAX)
        if abs(tg_c - tg) > 1e-9:
            notes.append(f"Terminal growth {tg*100:.2f}% -> {tg_c*100:.2f}% (clamped)")
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
            cap_note = (f"capped at the {capm.get('currency')} risk-free rate "
                        f"{tg_c*100:.2f}% — a perpetuity cannot outgrow its currency's economy")
            notes.append(f"Terminal growth {cap_note}")
            a["terminal_growth_note"] = cap_note
        elif abs(tg_c - tg) > 1e-9:
            a["terminal_growth_note"] = f"LLM {tg*100:.2f}% clamped to {tg_c*100:.2f}%"
        a["terminal_growth_rate"] = tg_c

    # 3. Margin anchoring — established-profitability companies only. For a
    #    loss-making hypergrowth name the LLM's convergence path is the
    #    valuation story and must not be dragged back to negative trailing.
    t_om = gp.get("operating_margins")
    t_em = gp.get("ebitda_margins")
    t_gm = gp.get("gross_margins")
    if t_om is not None and t_om >= _ESTABLISHED_OM:
        for key, trailing, label in (
            ("operating_margins", t_om, "operating"),
            ("ebitda_margins", t_em, "EBITDA"),
            ("gross_margins", t_gm, "gross"),
        ):
            if trailing is None or trailing <= 0:
                continue
            path = a.get(key)
            if not isinstance(path, list):
                continue
            new, changed = _anchor_path([float(x) for x in path], float(trailing))
            if changed:
                notes.append(
                    f"{label} margin path anchored to trailing {trailing*100:.1f}%: "
                    f"FY1 {path[0]*100:.1f}->{new[0]*100:.1f}%, "
                    f"FY5 {path[-1]*100:.1f}->{new[-1]*100:.1f}%"
                )
                a[key] = new

        # Internal consistency: gross >= EBITDA >= operating, year by year.
        oms = a.get("operating_margins") or []
        ems = list(a.get("ebitda_margins") or [])
        gms = list(a.get("gross_margins") or [])
        for i in range(min(len(oms), len(ems))):
            ems[i] = max(ems[i], oms[i])
        for i in range(min(len(ems), len(gms))):
            gms[i] = max(gms[i], ems[i])
        if ems:
            a["ebitda_margins"] = ems
        if gms:
            a["gross_margins"] = gms

    # Near-term revenue is an observable consensus input, not something the
    # language model should replace with a generic mature-company curve. The
    # Yahoo estimate table maps 0y/+1y to the first two unreported fiscal
    # years. Require real breadth and leave FY3-FY5 as explicit model
    # assumptions so consensus does not silently become the whole DCF.
    revenue_estimates = ((json_data or {}).get("analyst_data", {}) or {}).get(
        "revenue_estimates", {}) or {}
    growth_path = a.get("revenue_growth_rates")
    if isinstance(growth_path, list) and len(growth_path) >= 2:
        grounded_growth = [float(value) for value in growth_path]
        used = []
        try:
            minimum_analysts = max(3, int(os.getenv("ANALYST_CONSENSUS_MIN_ANALYSTS", "3") or 3))
        except ValueError:
            minimum_analysts = 3
        for offset, period in enumerate(("0y", "+1y")):
            estimate = revenue_estimates.get(period) or {}
            growth = estimate.get("growth")
            count = estimate.get("numberOfAnalysts")
            if (isinstance(growth, (int, float)) and not isinstance(growth, bool)
                    and math.isfinite(float(growth)) and -0.50 <= float(growth) <= 1.00
                    and isinstance(count, (int, float)) and count >= minimum_analysts):
                grounded_growth[offset] = float(growth)
                used.append(f"FY{offset + 1} {float(growth) * 100:.1f}% ({int(count)} analysts)")
        if used:
            a["revenue_growth_rates"] = grounded_growth
            a["revenue_growth_source"] = "yahoo_analyst_consensus_near_term"
            notes.append("Revenue growth anchored to consensus: " + ", ".join(used))

    # 4. Exit multiple — company-specific, never one-size-fits-all.
    cur = vm.get("enterprise_to_ebitda")
    if cur and cur > 0:
        exit_m = _clamp(_EXIT_HAIRCUT * float(cur), _EXIT_MIN, _EXIT_MAX)
        notes.append(
            f"Exit multiple {exit_m:.1f}x (0.8 x current EV/EBITDA {cur:.1f}x, "
            f"was hardcoded 20.0x)"
        )
    else:
        exit_m = _EXIT_FALLBACK
        notes.append(
            f"Exit multiple {exit_m:.1f}x fallback (current EV/EBITDA "
            f"unavailable/negative)"
        )
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
    notes.append(
        f"Exit-multiple sustainability cap deferred to projected FY5 cash "
        f"conversion (perpetual growth ceiling {g_cap*100:.2f}%)"
    )

    a["exit_multiple"] = exit_m

    # 5. Market-comps leg parameters (the second methodology in the headline
    # blend). Require a same-subindustry median backed by at least three actual
    # peers. A company's own current multiple is not a comparable-company
    # method: applying it to its own forecast merely echoes today's market
    # pricing, so an unavailable provider leaves this leg absent.
    peer_comps = (((json_data or {}).get("industry_data") or {}).get("peer_comps") or {})
    peer_ev = peer_comps.get("median_ev_ebitda")
    peer_ps = peer_comps.get("median_price_sales")
    peer_ev_count = int(peer_comps.get("ev_ebitda_peer_count") or 0)
    peer_ps_count = int(peer_comps.get("price_sales_peer_count") or 0)
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
    a["comps_peer_count"] = max(
        peer_ev_count if ev_from_peers else 0,
        peer_ps_count if ps_from_peers else 0,
    )
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
    tgt = fg.get("target_mean_price")
    a["analyst_target_mean"] = float(tgt) if tgt and tgt > 0 else 0.0
    consensus = company_data.get("analyst_consensus", {}) or {}
    target_meta = consensus.get("price_target", {}) or {}
    recommendation_meta = consensus.get("recommendation", {}) or {}
    a["analyst_target_low"] = float(target_meta.get("low") or 0.0)
    a["analyst_target_high"] = float(target_meta.get("high") or 0.0)
    a["analyst_count"] = int(target_meta.get("analyst_count") or 0)
    a["analyst_consensus_source"] = target_meta.get("source")
    a["analyst_consensus_as_of"] = target_meta.get("as_of") or consensus.get("captured_at")
    a["analyst_consensus_rating"] = recommendation_meta.get("label")
    if a["comps_ev_ebitda"] or a["comps_ps"]:
        notes.append(
            f"Comps leg (EV/EBITDA {a['comps_ev_source']}; "
            f"P/S {a['comps_ps_source']}"
            + (f"; up to {a['comps_peer_count']} peers" if real_peers else "")
            + f"): EV/EBITDA {a['comps_ev_ebitda']:.1f}x / "
            f"P/S {a['comps_ps']:.1f}x on FY2 projections"
            + (f"; analyst mean target {a['analyst_target_mean']:.2f} "
               f"({a['analyst_count']} analysts, {a['analyst_consensus_source'] or 'source unavailable'})"
               if a["analyst_target_mean"] else "")
        )

    return a, notes
