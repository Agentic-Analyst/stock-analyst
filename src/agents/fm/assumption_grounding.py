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

  * WACC        — CAPM: live 10Y treasury (^TNX, cached fallback 4.3%),
                  scraped beta (clamped), 5% equity risk premium, blended
                  with after-tax cost of debt at actual D/E weights.
  * Terminal g  — clamped to [2.0%, 3.0%].
  * Margin paths— for companies with ESTABLISHED profitability (trailing
                  operating margin >= 5%), the path is anchored to trailing
                  actuals: FY1 within +/-3pts, FY5 within [-5, +8]pts, linear
                  glide between. Hypergrowth/loss-making names keep the LLM's
                  convergence path untouched — that path IS the story there.
  * Exit multiple— 0.8x the company's CURRENT EV/EBITDA (a 20% de-rating
                  over five years), clamped to [8x, 30x]; 15x fallback when
                  current EV/EBITDA is unavailable or negative.

Every override is returned as a human-readable note and logged, so the
workbook's provenance stays auditable.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

_ERP = 0.055                # mature-market equity risk premium; in the range
                            # Damodaran publishes for developed markets, and the
                            # figure a sell-side DCF on a euro large-cap would use
_DEBT_SPREAD = 0.015        # cost of debt = rf + spread
_TAX_DEFAULT = 0.25         # mature-market average; overridden by the
                            # company's own effective rate when available
_RF_FALLBACK = 0.043
_BETA_MIN, _BETA_MAX = 0.6, 1.6
_WACC_MIN, _WACC_MAX = 0.07, 0.13
_TG_MIN, _TG_MAX = 0.02, 0.03
_EXIT_HAIRCUT = 0.8
# Terminal-year multiples above ~22x are rarely defensible in any sector.
_EXIT_MIN, _EXIT_MAX = 8.0, 22.0
_EXIT_FALLBACK = 15.0
_ESTABLISHED_OM = 0.05      # margin anchoring applies above this trailing OM


# 10-year sovereign yields for currencies yfinance does not carry. Verified:
# ^TNX (US 10Y) is the ONLY sovereign yield symbol that returns data — ^GDBR10,
# DE10Y-DE, GB10YT=RR, JP10Y-JP and every other variant 404. There is no live
# feed to use, and no FRED key configured, so non-USD rates come from this table
# with an explicit as-of date that is printed alongside the number. A stale rate
# a reader can see is worth more than a live US rate silently applied to a euro
# company, which is what the model did before: LVMH was discounted on a US
# Treasury yield, contributing to a EUR 269 fair value against a EUR 452 price.
#
# Override any entry without a deploy by setting RISK_FREE_<CCY>, e.g.
# RISK_FREE_EUR=0.0324.
_RF_AS_OF = "2026-08-21"
_RF_STATIC = {
    # currency: (rate, instrument)
    "EUR": (0.0324, "10Y German Bund"),
}


def _live_us_10y() -> Optional[Tuple[float, str]]:
    """
    US 10Y via ^TNX. Usually quoted as yield x10 (47.0 = 4.70%) but some feeds
    return plain percent — accept whichever scaling lands in a sane band.
    """
    try:
        import yfinance as yf
        h = yf.Ticker("^TNX").history(period="5d")
        if h is not None and not h.empty:
            close = float(h["Close"].iloc[-1])
            for scale in (1000.0, 100.0):
                rf = close / scale
                if 0.02 <= rf <= 0.07:
                    return rf, f"live US 10Y {rf*100:.2f}%"
    except Exception:
        pass
    return None


def risk_free_rate(currency: Optional[str] = "USD") -> Tuple[float, str]:
    """
    The risk-free rate for cash flows denominated in ``currency``.

    Discounting a euro cash-flow stream at a US Treasury yield is a currency
    mismatch in the cost of capital — the same class of error as quoting a EUR
    company in dollars. Returns ``(rate, source_label)``; the label is printed in
    the report so the reader can see whether the rate was live, dated or a proxy.
    """
    import os

    ccy = (currency or "USD").upper()

    override = os.getenv(f"RISK_FREE_{ccy}")
    if override:
        try:
            rate = float(override)
            if 0.0 <= rate <= 0.25:
                return rate, f"{ccy} {rate*100:.2f}% (RISK_FREE_{ccy} override)"
        except ValueError:
            pass

    if ccy == "USD":
        live = _live_us_10y()
        if live:
            return live
        return _RF_FALLBACK, f"US 10Y fallback {_RF_FALLBACK*100:.2f}%"

    if ccy in _RF_STATIC:
        rate, instrument = _RF_STATIC[ccy]
        return rate, f"{instrument} {rate*100:.2f}% (as of {_RF_AS_OF})"

    # No feed and no table entry. Say so rather than pretending the US rate is
    # this currency's risk-free.
    live = _live_us_10y()
    if live:
        rate, _ = live
        return rate, (f"US 10Y {rate*100:.2f}% used as a proxy — no {ccy} "
                      f"sovereign yield source available")
    return _RF_FALLBACK, (f"fallback {_RF_FALLBACK*100:.2f}% — no {ccy} "
                          f"sovereign yield source available")


def _live_risk_free() -> Tuple[float, str]:
    """Backwards-compatible USD entry point."""
    return risk_free_rate("USD")


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def capm_components(company_data: Dict[str, Any]) -> Dict[str, Any]:
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

    currency = (bi.get("currency") or "USD").upper()
    rf, rf_source = risk_free_rate(currency)

    raw_beta = cs.get("beta")
    if raw_beta:
        # Blume adjustment: raw betas mean-revert toward 1.0, so every bank
        # shrinks them (2/3 raw + 1/3 market) before CAPM — a raw 1.8+ beta
        # would price the largest companies on earth at a 13%+ WACC.
        beta = _clamp(0.67 * float(raw_beta) + 0.33, _BETA_MIN, _BETA_MAX)
        beta_source = f"Blume-adjusted from observed {float(raw_beta):.2f}"
    else:
        beta = 1.0
        beta_source = "market beta 1.00 (no observed beta available)"

    tax = _effective_tax_rate(company_data)
    ke = rf + beta * _ERP
    kd_pre_tax = rf + _DEBT_SPREAD
    kd_after_tax = kd_pre_tax * (1 - tax)

    equity = float(md.get("market_cap") or 0)
    debt = float(cs.get("total_debt") or 0)
    total = equity + debt
    w_e = equity / total if total > 0 else 1.0
    w_d = 1.0 - w_e

    raw_wacc = w_e * ke + w_d * kd_after_tax
    wacc = _clamp(raw_wacc, _WACC_MIN, _WACC_MAX)

    return {
        "currency": currency,
        "risk_free_rate": rf,
        "risk_free_source": rf_source,
        "equity_risk_premium": _ERP,
        "beta": beta,
        "beta_source": beta_source,
        "cost_of_equity": ke,
        "pre_tax_cost_of_debt": kd_pre_tax,
        "tax_rate": tax,
        "after_tax_cost_of_debt": kd_after_tax,
        "equity_value": equity,
        "debt_value": debt,
        "equity_weight": w_e,
        "debt_weight": w_d,
        "wacc": wacc,
        "wacc_unclamped": raw_wacc,
        "wacc_clamped": abs(raw_wacc - wacc) > 1e-9,
    }


def compute_capm_wacc(company_data: Dict[str, Any]) -> Tuple[float, str]:
    """Deterministic CAPM WACC from scraped beta, live rates, actual D/E."""
    c = capm_components(company_data)
    note = (
        f"CAPM WACC {c['wacc']*100:.2f}% (rf {c['risk_free_source']}, "
        f"beta {c['beta']:.2f}, Ke {c['cost_of_equity']*100:.2f}%, "
        f"D/(D+E) {c['debt_weight']*100:.0f}%)"
    )
    if c["wacc_clamped"]:
        note += f" [clamped from {c['wacc_unclamped']*100:.2f}%]"
    return c["wacc"], note


def _effective_tax_rate(company_data: Dict[str, Any]) -> float:
    """
    The rate that shields interest. Falls back to a mature-market average
    rather than the US statutory 21%, which is wrong for most of the world and
    was previously applied to every company regardless of domicile.
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


def _terminal_cash_conversion(json_data: Dict[str, Any]) -> Optional[float]:
    """
    FCF / EBITDA from the most recent reported year.

    This is the `r` the terminal-value identity needs. It is a proxy — the true
    figure is the TERMINAL year's conversion, which does not exist until the
    projection is built — but a mature company's conversion is stable enough
    that using the latest actual is far better than leaving the exit multiple
    unchecked entirely.

    Returns None when either line is missing or non-positive; the caller must
    then leave the multiple alone rather than cap it on a guess.
    """
    try:
        fs = (json_data or {}).get("financial_statements", {}) or {}
        cf = fs.get("cash_flow", {}) or {}
        inc = fs.get("income_statement", {}) or {}
        if not cf or not inc:
            return None
        year = sorted(cf.keys(), reverse=True)[0]
        fcf = (cf.get(year) or {}).get("Free Cash Flow")
        ebitda = (inc.get(year) or {}).get("EBITDA") or (inc.get(year) or {}).get("Normalized EBITDA")
        if ebitda is None:
            ebitda = (cf.get(year) or {}).get("EBITDA")
        fcf, ebitda = float(fcf), float(ebitda)
        if ebitda <= 0 or fcf <= 0:
            return None
        r = fcf / ebitda
        # Outside this band the inputs are almost certainly mislabelled rather
        # than describing a real business.
        return r if 0.05 <= r <= 1.5 else None
    except (TypeError, ValueError, IndexError, KeyError):
        return None


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
    capm = capm_components(company_data)
    wacc, wacc_note = compute_capm_wacc(company_data)
    a["wacc"] = wacc
    # Publish the derivation, not just the answer. The workbook writes these into
    # the Assumptions tab so its CAPM cells stop being hardcoded constants, and
    # the report prints them so the discount rate can be argued with.
    a["capm"] = capm
    if llm_wacc is not None and abs(llm_wacc - wacc) > 0.005:
        notes.append(f"WACC {llm_wacc*100:.2f}% (LLM) -> {wacc_note}")
    else:
        notes.append(wacc_note)

    # 2. Terminal growth — clamp.
    tg = a.get("terminal_growth_rate")
    if tg is not None:
        tg_c = _clamp(float(tg), _TG_MIN, _TG_MAX)
        if abs(tg_c - tg) > 1e-9:
            notes.append(f"Terminal growth {tg*100:.2f}% -> {tg_c*100:.2f}% (clamped)")
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
    # CAP THE MULTIPLE AT WHAT SUSTAINABLE GROWTH CAN JUSTIFY.
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
    # Inverting the terminal-value identity gives the highest multiple a
    # defensible perpetual growth rate supports; anything above it is a claim
    # that the company outgrows the economy forever. Capping here makes the
    # model internally consistent BY CONSTRUCTION instead of contradicting
    # itself and being flagged afterwards.
    r_conv = _terminal_cash_conversion(json_data)
    if r_conv is not None:
        try:
            from src.agents.fm.terminal_value import defensible_multiple, MAX_SUSTAINABLE_GROWTH
            ceiling = defensible_multiple(r_conv, a["wacc"], MAX_SUSTAINABLE_GROWTH)
            if ceiling and ceiling > 0 and exit_m > ceiling:
                notes.append(
                    f"Exit multiple {exit_m:.1f}x -> {ceiling:.1f}x (capped: above "
                    f"{ceiling:.1f}x the multiple implies perpetual growth over "
                    f"{MAX_SUSTAINABLE_GROWTH*100:.1f}%, i.e. faster than the economy "
                    f"forever; cash conversion {r_conv:.2f}, WACC {a['wacc']*100:.2f}%)"
                )
                exit_m = ceiling
        except Exception as _cap_err:
            # A grounding refinement must never break model generation.
            notes.append(f"Exit-multiple cap skipped ({_cap_err})")

    a["exit_multiple"] = exit_m

    # 5. Market-comps leg parameters (the third method on the football
    #    field): the company's own forward-looking multiples, mildly
    #    de-rated, applied to FY2 projections. P/S covers pre-EBITDA names.
    ev_eb = vm.get("enterprise_to_ebitda")
    a["comps_ev_ebitda"] = (
        _clamp(0.9 * float(ev_eb), 6.0, 25.0) if ev_eb and ev_eb > 0 else 0.0
    )
    ps = vm.get("price_to_sales")
    a["comps_ps"] = _clamp(0.9 * float(ps), 0.5, 40.0) if ps and ps > 0 else 0.0
    fg = company_data.get("forward_guidance", {}) or {}
    tgt = fg.get("target_mean_price")
    a["analyst_target_mean"] = float(tgt) if tgt and tgt > 0 else 0.0
    if a["comps_ev_ebitda"] or a["comps_ps"]:
        notes.append(
            f"Comps leg: EV/EBITDA {a['comps_ev_ebitda']:.1f}x / "
            f"P/S {a['comps_ps']:.1f}x on FY2 projections"
            + (f"; analyst mean target ${a['analyst_target_mean']:.2f}"
               if a["analyst_target_mean"] else "")
        )

    return a, notes
