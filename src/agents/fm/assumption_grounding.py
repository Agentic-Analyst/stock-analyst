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

_ERP = 0.05                 # equity risk premium
_DEBT_SPREAD = 0.015        # cost of debt = rf + spread
_TAX = 0.21                 # statutory-ish rate for after-tax Kd
_RF_FALLBACK = 0.043
_BETA_MIN, _BETA_MAX = 0.6, 1.6
_WACC_MIN, _WACC_MAX = 0.07, 0.13
_TG_MIN, _TG_MAX = 0.02, 0.03
_EXIT_HAIRCUT = 0.8
# Terminal-year multiples above ~22x are rarely defensible in any sector.
_EXIT_MIN, _EXIT_MAX = 8.0, 22.0
_EXIT_FALLBACK = 15.0
_ESTABLISHED_OM = 0.05      # margin anchoring applies above this trailing OM


def _live_risk_free() -> Tuple[float, str]:
    """
    10Y treasury yield via ^TNX. The index is usually quoted as yield x10
    (42.5 = 4.25%) but some feeds return the plain percent — accept whichever
    scaling lands in a sane band. Clamped, with fallback.
    """
    try:
        import yfinance as yf
        h = yf.Ticker("^TNX").history(period="5d")
        if h is not None and not h.empty:
            close = float(h["Close"].iloc[-1])
            for scale in (1000.0, 100.0):
                rf = close / scale
                if 0.02 <= rf <= 0.07:
                    return rf, f"live 10Y {rf*100:.2f}%"
    except Exception:
        pass
    return _RF_FALLBACK, f"fallback {_RF_FALLBACK*100:.1f}%"


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def compute_capm_wacc(company_data: Dict[str, Any]) -> Tuple[float, str]:
    """Deterministic CAPM WACC from scraped beta, live rates, actual D/E."""
    cs = company_data.get("capital_structure", {}) or {}
    md = company_data.get("market_data", {}) or {}

    rf, rf_src = _live_risk_free()
    raw_beta = cs.get("beta")
    if raw_beta:
        # Blume adjustment: raw betas mean-revert toward 1.0, so every bank
        # shrinks them (2/3 raw + 1/3 market) before CAPM — a raw 1.8+ beta
        # would price the largest companies on earth at a 13%+ WACC.
        beta = _clamp(0.67 * float(raw_beta) + 0.33, _BETA_MIN, _BETA_MAX)
    else:
        beta = 1.0
    ke = rf + beta * _ERP
    kd_after_tax = (rf + _DEBT_SPREAD) * (1 - _TAX)

    equity = float(md.get("market_cap") or 0)
    debt = float(cs.get("total_debt") or 0)
    total = equity + debt
    w_e = equity / total if total > 0 else 1.0
    w_d = 1.0 - w_e

    wacc = _clamp(w_e * ke + w_d * kd_after_tax, _WACC_MIN, _WACC_MAX)
    note = (
        f"CAPM WACC {wacc*100:.2f}% (rf {rf_src}, beta {beta:.2f}, "
        f"Ke {ke*100:.2f}%, D/(D+E) {w_d*100:.0f}%)"
    )
    return wacc, note


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
    wacc, wacc_note = compute_capm_wacc(company_data)
    a["wacc"] = wacc
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
