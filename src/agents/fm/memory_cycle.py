"""
Mid-cycle normalisation for memory-chip makers.

Memory chips are priced like a commodity: DRAM and NAND contract prices set
both revenue and margins, which swing from deep losses to 60-80% within two
years. A run-rate DCF capitalises whichever point of the cycle the covered
years sit on: Sandisk's Street case (71.6% operating margin on revenue that
had nearly tripled in a year) held through the terminal value valued it at
about 2x its price. So a memory maker is valued on the Street's two covered
years as forecast, then on mid-cycle economics: revenue reverts to the
company's long-run trend and the operating margin to the industry's pooled
through-cycle level, and the cycle's windfall is the covered years' cash.

The mid-cycle levels come from SEC XBRL annual filings (10-K), read
2026-10-07:

- DRAM (Micron, FY2009-FY2025): operating income over revenue pooled across
  complete cycles is 22.6% (trough to trough FY2009-FY2022), 21.6% over the
  last ten years, 18.7% over all seventeen; revenue's log-linear trend is
  10.6% a year.
- NAND (SanDisk Corp FY2008-FY2015, Sandisk FY2023-FY2026): pooled 14.6-17.5%
  over SanDisk's history (ex impairments; royalty income flatters it), 21%
  excluding the 2008 crisis year; revenue's peak-to-peak trend about 9% a
  year. NAND has more suppliers than DRAM and structurally lower returns.
- Operating costs (gross profit less operating income) ran 15% of revenue for
  Micron, pooled FY2009-FY2025, growing with trend revenue, not the cycle.
- Depreciation and capital spending follow the fabs, not the price: Micron's
  capex was $8.9B in the FY2018 boom (29% of revenue) and $9.8B in the FY2019
  bust (42%), $12.1B in FY2022 and $7.7B in FY2023. Scaled with a tripled,
  price-driven revenue they would build plants no mid-cycle year earns on.

No memory maker in that history ever reported a full year above about 61%.
"""

from __future__ import annotations

import math
import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional

# A maker of one kind of memory is as cyclical as one that makes both.
_MEMORY_CYCLE_SUMMARY_HINTS = ("dram", "nand")
_MEMORY_CYCLE_INDUSTRY_HINTS = ("semiconductor", "computer hardware")
_SINGLE_MEMORY_PRODUCT = re.compile(r"\b(?:nand|dram)\b")
# Kioxia, Sandisk's manufacturing partner, says "flash memory, SSDs", never
# "NAND". With drives beside it: Microchip's serial flash comes without them.
_FLASH_MEMORY = re.compile(r"\bflash memory\b")
_SOLID_STATE_DRIVES = re.compile(r"\bssds?\b|\bsolid[- ]state drives?\b")
# The company's own making: "manufactures", "manufacturing", "a manufacturer
# of", never its customers ("sells to module manufacturers").
_MAKES = re.compile(r"\bmanufactur(?:e|es|ed|ing|er)\b")
_MEMORY_CONTROLLER_VENDOR = re.compile(
    r"\b(?:nand\s+flash|flash|nand|memory)\s+controllers?\b"
    r"|\bcontrollers?\s+for\s+(?:nand|flash)\b"
)
_DRAM = re.compile(r"\bdram\b|\bdynamic random[- ]access memory\b")

MID_CYCLE = {
    "dram": {
        "operating_margin": 0.21,
        "revenue_trend_growth": 0.106,
        "source": (
            "Micron FY2009-FY2025 10-K (SEC XBRL): operating income over revenue "
            "pooled across complete cycles 22.6%, last ten years 21.6%; revenue "
            "trend 10.6% a year"
        ),
    },
    "nand": {
        "operating_margin": 0.18,
        "revenue_trend_growth": 0.09,
        "source": (
            "SanDisk FY2008-FY2015 and Sandisk FY2023-FY2026 10-K (SEC XBRL): "
            "operating income over revenue pooled 15-21% through the cycle; "
            "revenue trend about 9% a year"
        ),
    },
}
# Gross profit less operating income, as a share of trend revenue.
MID_CYCLE_OPERATING_COSTS = 0.15
# The engine's maturity convention (tab_projections): capex converges to 1.1x
# D&A by FY5, which the terminal value inherits.
CAPEX_TO_DA_AT_MATURITY = 1.1
# D&A against trend revenue (a log-linear fit of each 10-K history): Micron
# FY2009-FY2025 17.8%-29.2%, pooled 24.4%; old SanDisk FY2010-FY2015, whose
# fabs sit in the Kioxia joint venture, 3.0%-7.5%. A trailing share above the
# highest observed is held there: the through-cycle operating margin was
# earned on that much depreciation, and more would leave the terminal year
# converting too little of its EBITDA to be steady (terminal_value.py).
MAX_DA_SHARE_OF_TREND = 0.30
# Capex beyond 1.5x trend revenue is a data problem (a one-off acquisition
# booked as capex), not an asset base. Micron's highest was 50%; its trailing
# 78% is a real build-out, which the glide below winds down.
_MAX_CAPEX_SHARE_OF_TREND = 1.5
# Capex keeps today's intensity through the Street's covered years, the way
# Micron's rose into the FY2018 boom and its first bust year, then converges.
_CAPEX_GLIDE = (0.0, 0.0, 1 / 3, 2 / 3, 1.0)
# Annual periods needed to place the company's revenue trend.
MIN_ANNUAL_PERIODS = 3
# Why a memory maker's workbook built without the mid-cycle rewrite is only a
# scenario: it holds the covered years' margins through the terminal value.
MID_CYCLE_SCENARIO_REASON = (
    "The DCF may be shown as an auditable scenario, but no point estimate or "
    "directional rating should be published because memory-chip margins follow "
    "DRAM and NAND contract prices, and this workbook was not built on mid-cycle "
    "revenue and margins."
)


def is_memory_maker(industry: str, business_summary: str) -> bool:
    """A maker of DRAM or NAND chips, read from Yahoo's industry and description."""
    industry_key = (industry or "").casefold()
    summary = (business_summary or "").casefold()
    if not any(hint in industry_key for hint in _MEMORY_CYCLE_INDUSTRY_HINTS):
        return False
    if all(hint in summary for hint in _MEMORY_CYCLE_SUMMARY_HINTS):
        return True
    if ("equipment" in industry_key or _MAKES.search(summary) is None
            or _MEMORY_CONTROLLER_VENDOR.search(summary) is not None):
        return False
    if _SINGLE_MEMORY_PRODUCT.search(summary) is not None:
        return True
    return (_FLASH_MEMORY.search(summary) is not None
            and _SOLID_STATE_DRIVES.search(summary) is not None)


def memory_kind(industry: str, business_summary: str) -> Optional[str]:
    """'dram' for a DRAM maker (with or without NAND), 'nand' for flash only."""
    if not is_memory_maker(industry, business_summary):
        return None
    return "dram" if _DRAM.search((business_summary or "").casefold()) else "nand"


def _number(row: Any, *keys: str) -> Optional[float]:
    if not isinstance(row, dict):
        return None
    for key in keys:
        value = row.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
            return float(value)
    return None


def _as_date(value: Any) -> Optional[date]:
    text = str(value or "")[:10]
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def _years_between(start: date, end: date) -> float:
    return (end - start).days / 365.25


def mid_cycle_inputs(financial_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    What a mid-cycle valuation needs for this company, or None when it is not a
    memory maker or its reported history cannot place a revenue trend (then
    the model stays a scenario, as before).
    """
    data = financial_data if isinstance(financial_data, dict) else {}
    basic = ((data.get("company_data") or {}).get("basic_info") or {})
    summary = str(basic.get("business_summary") or basic.get("long_business_summary") or "")
    kind = memory_kind(str(basic.get("industry") or ""), summary)
    if kind is None:
        return None

    statements = ((data.get("financial_statements") or {}).get("income_statement") or {})
    history: List[Dict[str, Any]] = []
    if isinstance(statements, dict):
        for period, row in statements.items():
            when, revenue = _as_date(period), _number(row, "Total Revenue", "Operating Revenue")
            if when is not None and revenue is not None and revenue > 0:
                history.append({"period_end": when.isoformat(), "revenue": revenue})
    history.sort(key=lambda r: r["period_end"])
    if len(history) < MIN_ANNUAL_PERIODS:
        return None

    bridge = data.get("ttm_bridge") or {}
    base = (_as_date(bridge.get("latest_period")) if bridge.get("status") == "current" else None) \
        or _as_date(history[-1]["period_end"])
    centre = date.fromordinal(round(sum(
        _as_date(r["period_end"]).toordinal() for r in history) / len(history)))
    params = MID_CYCLE[kind]
    return {
        "kind": kind,
        "operating_margin": params["operating_margin"],
        "revenue_trend_growth": params["revenue_trend_growth"],
        "operating_costs": MID_CYCLE_OPERATING_COSTS,
        "source": params["source"],
        "history": history,
        # The company's reported years average out its own swings: their
        # geometric mean (a trend is log-linear, and one boom year must not
        # dominate it), at their mean date, grown at the industry trend.
        "trend_revenue_mean": math.exp(sum(math.log(r["revenue"]) for r in history) / len(history)),
        "trend_centre": centre.isoformat(),
        "base_period_end": base.isoformat() if base else None,
        # The trailing twelve months' D&A and capex in dollars, for the asset
        # base (asset_base_path); only from a current bridge.
        **_trailing_asset_spend(bridge),
    }


def _trailing_asset_spend(bridge: Any) -> Dict[str, Any]:
    if not isinstance(bridge, dict) or bridge.get("status") != "current":
        return {}
    normalized = bridge.get("normalized") or {}
    period = _as_date(bridge.get("latest_period"))
    return {
        "ttm_depreciation": _number(normalized, "depreciation_and_amortization"),
        "ttm_capex": _number(normalized, "capital_expenditure"),
        "ttm_period_end": period.isoformat() if period else None,
    }


def trend_revenue(inputs: Dict[str, Any], years_after_base: float,
                  base_period_end: Optional[str] = None) -> float:
    """The company's trend revenue at the end of forecast year `years_after_base`,
    counted from the projection's base period (the TTM quarter by default)."""
    centre = _as_date(inputs["trend_centre"])
    base = _as_date(base_period_end or inputs["base_period_end"])
    span = _years_between(centre, base) + years_after_base
    return inputs["trend_revenue_mean"] * (1 + inputs["revenue_trend_growth"]) ** span


def asset_base_path(
    inputs: Dict[str, Any], base_period: Optional[str], revenue: List[float],
) -> Optional[Dict[str, Any]]:
    """
    D&A and capex on the company's asset base: trend revenue, not the price.

    The engine scales both with projected revenue (tab_projections), which for
    a memory maker in a boom is price: Micron's trailing capex, 28% of revenue
    that had tripled, became $86B and $84B a year in the Street's two covered
    years, building plant no mid-cycle year earns on, while D&A on the trend
    years stayed at the boom's 10% of revenue ($5B a year on $100B+ of plant).

    Here the trailing twelve months' D&A and capex dollars are measured
    against the TREND revenue at the end of those twelve months, which
    removes the price, and grow with trend revenue. D&A keeps that share (at
    most MAX_DA_SHARE_OF_TREND); capex keeps today's intensity through the
    covered years, then converges to the engine's usual 1.1x D&A by FY5, so the
    terminal year is no more and no less mature than any other company's.
    Returns the per-year ratios to projected revenue, or None (the engine's
    path is kept) without a current trailing twelve months, with implausible
    shares, or with ratios the workbook would refuse.
    """
    from src.agents.fm.tabs.tab_projections import YEAR_RATIO_BOUNDS

    da_ttm, capex_ttm = inputs.get("ttm_depreciation"), inputs.get("ttm_capex")
    ttm_end = inputs.get("ttm_period_end")
    if (not ttm_end or len(revenue) < 5
            or not all(isinstance(v, (int, float)) and not isinstance(v, bool)
                       and math.isfinite(v) for v in (da_ttm, capex_ttm))):
        return None
    trend_then = trend_revenue(inputs, 0, ttm_end)
    if not trend_then > 0 or da_ttm < 0 or capex_ttm > 0:
        return None
    da_share = float(da_ttm) / trend_then
    capex_share = float(capex_ttm) / trend_then
    if capex_share < -_MAX_CAPEX_SHARE_OF_TREND:
        return None
    da_held = da_share > MAX_DA_SHARE_OF_TREND
    da_share = min(da_share, MAX_DA_SHARE_OF_TREND)
    da, capex = [], []
    for i, progress in enumerate(_CAPEX_GLIDE):
        trend_i = trend_revenue(inputs, i + 1, base_period)
        da.append(da_share * trend_i)
        capex.append(trend_i * (capex_share * (1 - progress)
                                - CAPEX_TO_DA_AT_MATURITY * da_share * progress))
    da_ratios = [d / r for d, r in zip(da, revenue[:5])]
    capex_ratios = [c / r for c, r in zip(capex, revenue[:5])]
    # The workbook takes the per-year ratios only inside these bounds; a path
    # it would refuse must not be recorded as the one it built.
    if not (all(YEAR_RATIO_BOUNDS["da"][0] <= v <= YEAR_RATIO_BOUNDS["da"][1] for v in da_ratios)
            and all(YEAR_RATIO_BOUNDS["capex"][0] <= v <= YEAR_RATIO_BOUNDS["capex"][1]
                    for v in capex_ratios)):
        return None
    return {
        "da_share_of_trend_revenue": da_share,
        "da_share_held_at_maximum": da_held,
        "capex_share_of_trend_revenue": capex_share,
        "trailing_period_end": ttm_end,
        "da": da,
        "capex": capex,
        "da_to_revenue_by_year": da_ratios,
        "capex_to_revenue_by_year": capex_ratios,
    }


def apply_mid_cycle(a: Dict[str, Any], inputs: Dict[str, Any]) -> Optional[str]:
    """
    Rewrite FY3-FY5 of the grounded assumptions to mid-cycle economics, in place.

    FY1-FY2 stay the Street's case (revenue and margin), which the publication
    boundary checks against the Street. FY3 is halfway to mid-cycle; FY4 is on
    the trend line at the mid-cycle margin; FY5 grows at the trend rate, so the
    DCF's years six to ten (FY5 growth fading to terminal) continue the trend
    rather than the reversion. Returns the note, or None when the grounded
    assumptions lack what the rewrite needs.
    """
    growth = list(a.get("revenue_growth_rates") or [])
    margins = list(a.get("operating_margins") or [])
    basis = a.get("modeling_basis") or {}
    base_revenue = basis.get("revenue")
    # The projections' own base: the rolling TTM revenue when the model has
    # one, else the last fiscal year (tab_projections). The trend is counted
    # from the same period, or FY4 lands up to a year off the trend line.
    if isinstance(base_revenue, (int, float)) and base_revenue > 0:
        base_period = ((a.get("forecast_basis") or {}).get("period_end")
                       or inputs["base_period_end"])
    else:
        base_revenue = inputs["history"][-1]["revenue"]
        base_period = inputs["history"][-1]["period_end"]
    if (len(growth) < 5 or len(margins) < 5
            or not isinstance(base_revenue, (int, float)) or base_revenue <= 0):
        return None

    revenue = [float(base_revenue)]
    for g in growth[:2]:
        revenue.append(revenue[-1] * (1 + float(g)))
    fy2, fy4 = revenue[2], trend_revenue(inputs, 4, base_period)
    fy3 = math.sqrt(fy2 * fy4)
    new_growth = [float(growth[0]), float(growth[1]), fy3 / fy2 - 1, fy4 / fy3 - 1,
                  inputs["revenue_trend_growth"]]

    mid = inputs["operating_margin"]
    om2 = float(margins[1])
    new_margins = [float(margins[0]), om2, (om2 + mid) / 2, mid, mid]

    gross = list(a.get("gross_margins") or [None] * 5)
    da_ratio = basis.get("da_to_revenue")
    da_ratio = float(da_ratio) if isinstance(da_ratio, (int, float)) else 0.0
    projected = [float(base_revenue)]
    for g in new_growth:
        projected.append(projected[-1] * (1 + g))
    asset_base = (asset_base_path(inputs, base_period, projected[1:])
                  if isinstance(a.get("modeling_basis"), dict) else None)
    # Operating costs follow trend revenue, not the cycle: in FY3 the same
    # dollars are a smaller share of still-elevated revenue.
    year_revenue = {2: fy3, 3: fy4, 4: fy4 * (1 + inputs["revenue_trend_growth"])}
    for i in range(2, 5):
        trend_i = trend_revenue(inputs, i + 1, base_period)
        gross[i] = new_margins[i] + inputs["operating_costs"] * trend_i / year_revenue[i]
    a["revenue_growth_rates"] = new_growth
    a["operating_margins"] = new_margins
    a["gross_margins"] = gross
    if asset_base:
        basis["da_to_revenue_by_year"] = asset_base["da_to_revenue_by_year"]
        basis["capex_to_revenue_by_year"] = asset_base["capex_to_revenue_by_year"]
        a["ebitda_margins"] = [m + d for m, d in zip(new_margins, asset_base["da_to_revenue_by_year"])]
    else:
        a["ebitda_margins"] = [m + da_ratio for m in new_margins]
    # Peak-cycle peers on peak-cycle earnings would put the cycle back in.
    a["comps_included_in_blended_value"] = False
    a["mid_cycle"] = {
        "kind": inputs["kind"],
        "operating_margin": mid,
        "revenue_trend_growth": inputs["revenue_trend_growth"],
        "trend_revenue_fy4": fy4,
        "base_period_end": base_period,
        "street_revenue_fy2": fy2,
        "source": inputs["source"],
        "history": inputs["history"],
        "asset_base": ({k: asset_base[k] for k in (
            "da_share_of_trend_revenue", "da_share_held_at_maximum",
            "capex_share_of_trend_revenue", "trailing_period_end", "da", "capex")}
            if asset_base else None),
    }
    a["operating_margin_source"] = "mid_cycle_after_street_covered_years"
    # FY1-FY2 are still the consensus case: keep the source's prefix, which
    # the model records as near-term revenue anchored to the Street.
    a["revenue_growth_source"] = f"{a.get('revenue_growth_source') or 'model'}_then_mid_cycle_trend"
    label = "DRAM" if inputs["kind"] == "dram" else "NAND"
    if asset_base:
        held = (" (held at the highest observed through the cycle)"
                if asset_base["da_share_held_at_maximum"] else "")
        assets = (
            f"; D&A and capex on the asset base, not the price: "
            f"{asset_base['da_share_of_trend_revenue'] * 100:.1f}%{held} and "
            f"{-asset_base['capex_share_of_trend_revenue'] * 100:.1f}% of trend revenue over the "
            f"twelve months to {asset_base['trailing_period_end']}, capex at that intensity "
            f"through FY2 and converging to {CAPEX_TO_DA_AT_MATURITY:.1f}x D&A by FY5"
        )
    else:
        assets = ("; D&A and capex at the trailing share of projected revenue "
                  "(no current trailing twelve months)")
    return (
        f"Mid-cycle ({label} maker): FY1-FY2 on the Street case; revenue from "
        f"{fy2 / 1e9:,.1f}B (FY2) to its trend {fy4 / 1e9:,.1f}B by FY4, then "
        f"{inputs['revenue_trend_growth'] * 100:.1f}% a year; operating margin "
        f"{om2 * 100:.1f}% to {mid * 100:.0f}% ({inputs['source']}){assets}"
    )


# How long memory booms have lasted: Micron's operating margin stood above
# its through-cycle 21% in FY2017-FY2019 and FY2021-FY2022, and again from
# FY2025 (SEC XBRL, FY2009-FY2025); FY2010 and FY2014 peaked below it.
BOOM_YEARS_OBSERVED = "two to three years (FY2017-FY2019, FY2021-FY2022)"
_MAX_PEAK_YEARS = 25


def _enterprise_value(fcf: List[float], wacc: float, growth: float, timing: float) -> float:
    pv = sum(f / (1 + wacc) ** (t + 1 - timing) for t, f in enumerate(fcf))
    terminal = fcf[-1] * (1 + growth) / (wacc - growth)
    return pv + terminal / (1 + wacc) ** (len(fcf) - timing)


def peak_years_implied(
    fcf: List[float], *, wacc: float, terminal_growth: float, enterprise_value: float,
    street_growth: float, trend_growth: float, mid_year: float = 0.0,
) -> Dict[str, Any]:
    """
    How many years of the Street's peak-cycle cash flow a market price pays
    for, before the model's mid-cycle path. Benchmark only.

    `fcf` is the workbook's ten years: FY1-FY2 on the Street's case, FY3-FY10
    the mid-cycle path. With N peak years, FY2's cash flow continues at the
    Street's FY2 growth through year N, then the mid-cycle path follows, each
    year grown by the trend over the N-2 years it was postponed. The workbook's
    own discounting (WACC, terminal growth, timing) values each path; N is
    interpolated between whole years.
    """
    if (len(fcf) < 3 or not all(isinstance(f, (int, float)) for f in fcf)
            or wacc <= terminal_growth or not enterprise_value or enterprise_value <= 0):
        return {"available": False}
    # Only a boom has peak-cycle years to count: the covered years' cash flow
    # above the mid-cycle path's. In a trough the question has no answer.
    if fcf[1] <= 0 or fcf[1] <= max(fcf[3:]):
        return {"available": False, "not_a_boom": True}
    timing = 0.5 if mid_year else 0.0

    def value(n: int) -> float:
        peak = list(fcf[:2]) + [fcf[1] * (1 + street_growth) ** k for k in range(1, n - 1)]
        tail = [f * (1 + trend_growth) ** (n - 2) for f in fcf[2:]]
        return _enterprise_value(peak + tail, wacc, terminal_growth, timing)

    previous = value(2)
    if previous >= enterprise_value:
        return {"available": True, "peak_years": None, "below_mid_cycle": True}
    for n in range(3, _MAX_PEAK_YEARS + 1):
        current = value(n)
        if current >= enterprise_value:
            years = (n - 1) + (enterprise_value - previous) / (current - previous)
            return {"available": True, "peak_years": round(years, 1), "below_mid_cycle": False}
        previous = current
    return {"available": True, "peak_years": None, "beyond_bound": _MAX_PEAK_YEARS}


def peak_years_sentence(result: Any) -> Optional[str]:
    """The benchmark in one sentence, or None."""
    if not isinstance(result, dict) or not result.get("available"):
        return None
    if result.get("below_mid_cycle"):
        return ("At this price, the market pays less than the Street's two covered "
                "years followed by mid-cycle revenue and margins are worth.")
    if result.get("beyond_bound"):
        return (f"At this price, the market pays for more than {result['beyond_bound']} "
                "years of the Street's peak-cycle cash flow before mid-cycle economics.")
    years = result.get("peak_years")
    if not isinstance(years, (int, float)):
        return None
    return (f"At this price, the market pays for about {years:.0f} years of the Street's "
            f"peak-cycle cash flow, extended at its FY2 growth, before mid-cycle revenue and "
            f"margins; Micron's booms above its through-cycle margin have lasted "
            f"{BOOM_YEARS_OBSERVED}.")
