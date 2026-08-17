"""
terminal_value.py — reconcile the two terminal-value assumptions.

THE PROBLEM THIS SOLVES

The model values a company twice and the answers disagree — median 1.85x across
39 real production runs, up to 54x. The two "methods" were then averaged, which
produced a precise-looking number no method supported.

They are not two independent methods. They are ONE discounted cash flow with
terminal value assumed twice:

    perpetuity      TV = FCF_n * (1 + g) / (WACC - g)
    exit multiple   TV = EBITDA_n * M

Terminal value dominates both, so those two assumptions imply each other. When
they disagree, the model contradicts itself, and averaging the contradiction is
the one response that cannot be right.

THE TEST THAT SETTLES IT

Given the terminal cash conversion r = FCF_n / EBITDA_n:

    M = r(1 + g) / (WACC - g)      solve for g

    g = (M * WACC - r) / (M + r)

That inverts an exit multiple into the perpetual growth rate it implicitly
assumes — and perpetual growth is a claim that can be checked against the
economy. Nothing can grow faster than nominal GDP forever; it would eventually
become the entire economy.

For the audited META run:

    exit multiple assumed            11.22x
    perpetual growth it implies       5.79%   <-- above nominal GDP
    perpetuity method assumes         2.50%
    defensible ceiling at g = 4%      8.22x

So the exit-multiple leg is the broken one, and the reason is structural rather
than arithmetic: the multiple is sourced from what comparable companies trade
at TODAY, which embeds today's growth expectations, and is then applied to a
terminal year in which growth has already decayed to perpetuity levels. Using a
current multiple as a terminal multiple assumes no multiple compression despite
growth collapsing — for META, that single unstated assumption is the entire gap
between $380.64 and $549.16 per share.
"""

from __future__ import annotations

from typing import Optional, Dict, Any

# Long-run nominal GDP: ~2% real + ~2% inflation. The ceiling on any perpetual
# growth rate, because a business compounding faster than the economy forever
# converges on being the whole economy. Deliberately generous — the point is to
# catch the indefensible, not to litigate 2.5% versus 3%.
MAX_SUSTAINABLE_GROWTH = 0.04

# Below this the two assumptions are close enough that the difference is noise
# rather than a contradiction worth reporting.
CONSISTENCY_TOLERANCE = 1.25


def implied_growth_from_multiple(
    exit_multiple: float, cash_conversion: float, wacc: float
) -> Optional[float]:
    """
    The perpetual growth rate an exit multiple implicitly assumes.

    g = (M * WACC - r) / (M + r)

    Returns None when the inputs cannot express a growth rate. A result at or
    above WACC is rejected: the perpetuity formula diverges there, so such a
    multiple encodes infinite value rather than a growth rate.
    """
    try:
        M, r, w = float(exit_multiple), float(cash_conversion), float(wacc)
    except (TypeError, ValueError):
        return None
    if M <= 0 or r <= 0 or w <= 0 or (M + r) == 0:
        return None
    g = (M * w - r) / (M + r)
    if g != g or g >= w:
        return None
    return g


def defensible_multiple(
    cash_conversion: float, wacc: float, growth: float = MAX_SUSTAINABLE_GROWTH
) -> Optional[float]:
    """The highest exit multiple justifiable at `growth` in perpetuity."""
    try:
        r, w, g = float(cash_conversion), float(wacc), float(growth)
    except (TypeError, ValueError):
        return None
    if r <= 0 or w <= g:
        return None
    m = r * (1 + g) / (w - g)
    return m if m > 0 else None


def reconcile(
    *,
    fcf_terminal: Optional[float],
    ebitda_terminal: Optional[float],
    wacc: Optional[float],
    terminal_growth: Optional[float],
    exit_multiple: Optional[float],
) -> Dict[str, Any]:
    """
    Compare the two terminal-value assumptions and name which one fails.

    Returns a dict that is always safe to read:
        ok               False when the inputs cannot support the test
        implied_multiple what the perpetuity implies (x)
        implied_growth   what the exit multiple implies (fraction)
        ceiling          highest defensible multiple at MAX_SUSTAINABLE_GROWTH
        verdict          consistent | exit_multiple_too_rich |
                         exit_multiple_too_cheap | growth_not_sustainable
        note             analyst-facing explanation, or None when consistent
    """
    out: Dict[str, Any] = {"ok": False, "verdict": None, "note": None}

    try:
        fcf = float(fcf_terminal)
        ebitda = float(ebitda_terminal)
        w = float(wacc)
        g = float(terminal_growth)
        M = float(exit_multiple)
    except (TypeError, ValueError):
        return out

    # A negative-FCF terminal year makes every quantity here meaningless: the
    # perpetuity is negative and the "multiple" it implies is not a multiple.
    if ebitda <= 0 or fcf <= 0 or w <= g or M <= 0:
        return out

    r = fcf / ebitda
    implied_multiple = defensible_multiple(r, w, g)      # what perpetuity implies
    implied_growth = implied_growth_from_multiple(M, r, w)  # what the multiple implies
    ceiling = defensible_multiple(r, w, MAX_SUSTAINABLE_GROWTH)

    if implied_multiple is None or implied_growth is None or ceiling is None:
        return out

    out.update(
        ok=True,
        cash_conversion=round(r, 4),
        implied_multiple=round(implied_multiple, 2),
        assumed_multiple=round(M, 2),
        implied_growth=round(implied_growth, 4),
        assumed_growth=round(g, 4),
        ceiling=round(ceiling, 2),
        multiple_gap=round(max(M, implied_multiple) / min(M, implied_multiple), 2),
    )

    # The strongest failure first: an exit multiple that cannot be justified at
    # ANY sustainable growth rate is wrong on its own terms, regardless of what
    # the perpetuity happens to assume.
    if implied_growth > MAX_SUSTAINABLE_GROWTH:
        out["verdict"] = "growth_not_sustainable"
        out["note"] = (
            f"EXIT MULTIPLE IS NOT A TERMINAL MULTIPLE: {M:.1f}x EV/EBITDA implies "
            f"{implied_growth * 100:.1f}% growth in perpetuity, above long-run nominal "
            f"GDP (~{MAX_SUSTAINABLE_GROWTH * 100:.0f}%). Nothing compounds faster than "
            f"the economy forever. The multiple is almost certainly taken from what "
            f"peers trade at TODAY, which embeds today's growth, and then applied to a "
            f"terminal year where growth has already decayed to "
            f"{g * 100:.1f}%. That single unstated assumption — no multiple compression "
            f"despite growth collapsing — is what separates the two valuation legs. "
            f"The highest defensible exit multiple here is about {ceiling:.1f}x "
            f"(vs {implied_multiple:.1f}x implied by the perpetuity's own "
            f"{g * 100:.1f}% growth). Treat the perpetuity leg as primary and present "
            f"the exit-multiple leg as an upper bound that assumes the market never "
            f"re-rates this business."
        )
        return out

    gap = out["multiple_gap"]
    if gap <= CONSISTENCY_TOLERANCE:
        out["verdict"] = "consistent"
        return out

    if M > implied_multiple:
        out["verdict"] = "exit_multiple_too_rich"
        out["note"] = (
            f"TERMINAL VALUE ASSUMED TWICE: the exit multiple ({M:.1f}x) is {gap:.1f}x "
            f"richer than the {implied_multiple:.1f}x the perpetuity implies at "
            f"{g * 100:.1f}% growth. It corresponds to {implied_growth * 100:.1f}% "
            f"perpetual growth, still under the ~{MAX_SUSTAINABLE_GROWTH * 100:.0f}% "
            f"ceiling but well above what the perpetuity assumes. The two legs differ "
            f"because of THIS, not because two methods reached different conclusions. "
            f"Reconcile the assumptions or present the exit leg as the optimistic case."
        )
    else:
        out["verdict"] = "exit_multiple_too_cheap"
        out["note"] = (
            f"TERMINAL VALUE ASSUMED TWICE: the exit multiple ({M:.1f}x) is {gap:.1f}x "
            f"CHEAPER than the {implied_multiple:.1f}x the perpetuity implies at "
            f"{g * 100:.1f}% growth, i.e. only {implied_growth * 100:.1f}% perpetual "
            f"growth. The exit leg is the conservative case here, not an independent "
            f"opinion. Reconcile the assumptions rather than averaging the two."
        )
    return out
