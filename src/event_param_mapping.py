"""event_param_mapping.py

Deterministic mapping from qualitative screened events (catalysts / risks)
to per-parameter model deltas. This becomes the *primary* adjustment path
while the legacy scalar qualitative overlay becomes a residual backstop.

Design:
1. Each mapping entry defines an event_type with per-year deltas for one or
   more parameters (growth_pp, margin_bps, capex_rate_bps, wacc_bps).
2. Year indices are relative projection years (1 = first forecast year).
3. Caps enforced both per-event (local) and cumulatively across events.
4. Timeline weights (Immediate / Short-Term / Mid-Term / Long-Term) scale
   the base per-year deltas before capping.
5. Combination: additive, then clipped to global cumulative caps.

Current generator supports single-year growth override (first_year_growth),
uniform margin_uplift, capex_rate override, and override_wacc. Multi-year
patterns are collapsed into effective single deltas using weighted averages.
Future: extend strategies to accept explicit per-year growth / margin curve.

Units:
 - growth_pp: percentage points (e.g., +3.0 => +0.03).
 - margin_bps: basis points (e.g., +50 => +0.005).
 - capex_rate_bps: basis points of revenue (e.g., +40 => +0.004).
 - wacc_bps: basis points (e.g., -25 => -0.0025).

"""
from __future__ import annotations
from typing import Dict, Any, List, Tuple

# Base event templates (conservative). Additional patterns can be appended.
EVENT_PARAM_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "guidance_up": {
        "growth_pp": {1: 3.0, 2: 1.0},
        "caps": {"growth_pp": 5.0},
        "confidence_floor": 0.55,
    },
    "guidance_down": {
        "growth_pp": {1: -3.0, 2: -1.0},
        "caps": {"growth_pp": 5.0},
        "confidence_floor": 0.55,
    },
    "cost_cut": {
        "margin_bps": {1: 50, 2: 30},
        "caps": {"margin_bps": 150},
        "confidence_floor": 0.50,
    },
    "efficiency_initiative": {
        "margin_bps": {1: 40, 2: 40, 3: 20},
        "caps": {"margin_bps": 150},
        "confidence_floor": 0.50,
    },
    "supply_constraint": {
        "growth_pp": {1: -4.0, 2: 1.5},
        "caps": {"growth_pp": 5.0},
        "confidence_floor": 0.45,
    },
    "rate_cut": {
        "wacc_bps": {1: -25},  # treat as immediate; wacc override uses aggregate
        "caps": {"wacc_bps": 100},
        "confidence_floor": 0.50,
    },
    "rate_hike": {
        "wacc_bps": {1: 25},
        "caps": {"wacc_bps": 100},
        "confidence_floor": 0.50,
    },
    "capex_program": {
        "capex_rate_bps": {1: 40, 2: 40, 3: 20},
        "caps": {"capex_rate_bps": 100},
        "confidence_floor": 0.55,
    },
    # New broader demand & margin related patterns
    "ai_demand_surge": {
        "growth_pp": {1: 4.0, 2: 2.0, 3: 1.0},
        "margin_bps": {1: 20},  # modest operating leverage
        "caps": {"growth_pp": 6.0, "margin_bps": 120},
        "confidence_floor": 0.55,
    },
    "data_center_boom": {
        "growth_pp": {1: 3.5, 2: 2.5},
        "margin_bps": {1: 30, 2: 20},
        "caps": {"growth_pp": 6.0, "margin_bps": 140},
        "confidence_floor": 0.55,
    },
    "trade_tension_easing": {
        "growth_pp": {1: 2.0, 2: 1.0},
        "wacc_bps": {1: -15},
        "caps": {"growth_pp": 5.0, "wacc_bps": 60},
        "confidence_floor": 0.50,
    },
    "margin_expansion_record_fcf": {
        "margin_bps": {1: 60, 2: 40},
        "growth_pp": {1: 1.5},
        "caps": {"margin_bps": 160, "growth_pp": 5.0},
        "confidence_floor": 0.55,
    },
}

# Cumulative global caps (across all events for one ticker run)
GLOBAL_CUM_CAPS = {
    "growth_pp": 6.0,        # ±6 percentage points
    "margin_bps": 200,       # ±200 bps
    "capex_rate_bps": 120,   # ±120 bps
    "wacc_bps": 120,         # ±120 bps
}

# Timeline multipliers (reuse conceptually from price_adjustor TIMELINE_WEIGHTS
TIMELINE_MULTIPLIERS = {
    "immediate": 1.0,
    "short-term": 0.8,
    "short term": 0.8,
    "mid-term": 0.6,
    "mid term": 0.6,
    "medium-term": 0.6,
    "long-term": 0.4,
    "long term": 0.4,
}

# Simple keyword heuristic classification: (lowercased token) -> event_type
KEYWORD_EVENT_MAP: List[Tuple[str, str]] = [
    ("raise guidance", "guidance_up"),
    ("raised guidance", "guidance_up"),
    ("guidance up", "guidance_up"),
    ("higher guidance", "guidance_up"),
    ("lower guidance", "guidance_down"),
    ("cut guidance", "guidance_down"),
    ("reduce guidance", "guidance_down"),
    ("layoff", "cost_cut"),
    ("cost discipline", "cost_cut"),
    ("cost optimization", "cost_cut"),
    ("efficiency", "efficiency_initiative"),
    ("supply constraint", "supply_constraint"),
    ("supply bottleneck", "supply_constraint"),
    ("rate cut", "rate_cut"),
    ("lower rates", "rate_cut"),
    ("fed cut", "rate_cut"),
    ("rate hike", "rate_hike"),
    ("higher rates", "rate_hike"),
    ("capex program", "capex_program"),
    ("capital expenditure plan", "capex_program"),
    # Expanded demand & macro keywords
    ("surging demand for ai", "ai_demand_surge"),
    ("ai demand", "ai_demand_surge"),
    ("artificial intelligence is driving demand", "ai_demand_surge"),
    ("data center demand", "data_center_boom"),
    ("data-center compute", "data_center_boom"),
    ("data center boom", "data_center_boom"),
    ("easing trade tensions", "trade_tension_easing"),
    ("trade tensions easing", "trade_tension_easing"),
    ("easing of trade tensions", "trade_tension_easing"),
    ("record free cash flow", "margin_expansion_record_fcf"),
    ("record fcf", "margin_expansion_record_fcf"),
    ("margin expansion", "margin_expansion_record_fcf"),
]

def classify_event(title: str, description: str) -> str | None:
    text = f"{title or ''} {description or ''}".lower()
    for key, etype in KEYWORD_EVENT_MAP:
        if key in text:
            return etype
    return None

def aggregate_mapped_parameter_deltas(parsed_items, is_risk: bool = False) -> Dict[str, Any]:
    """Produce cumulative parameter deltas from parsed catalyst/risk items.

    Returns dict with raw per-event contributions and consolidated effective
    overrides (growth_delta_dec, margin_uplift_dec, capex_rate_delta_dec, wacc_delta_dec).
    Risk items invert the sign of growth_pp and margin_bps (penalizing), while
    wacc_bps for risks is additive (risks push WACC up) and capex_rate_bps is
    additive (higher capital intensity) unless template already negative.
    """
    contributions: List[Dict[str, Any]] = []
    accum = {"growth_pp": 0.0, "margin_bps": 0.0, "capex_rate_bps": 0.0, "wacc_bps": 0.0}
    for item in parsed_items:
        etype = item.get("event_type")
        if not etype: continue
        tmpl = EVENT_PARAM_TEMPLATES.get(etype)
        if not tmpl: continue
        conf = float(item.get("confidence", 0.0) or 0.0)
        if conf < tmpl.get("confidence_floor", 0.0):
            continue
        timeline = (item.get("timeline") or '').lower()
        t_mult = TIMELINE_MULTIPLIERS.get(timeline, 0.7)
        # For each parameter dimension present
        for dim in ["growth_pp", "margin_bps", "capex_rate_bps", "wacc_bps"]:
            series = tmpl.get(dim)
            if not series: continue
            dim_cap = tmpl.get("caps", {}).get(dim, GLOBAL_CUM_CAPS[dim])
            local_sum = 0.0
            for _, base_val in series.items():
                val = base_val * t_mult * conf
                local_sum += val
            # Apply local cap
            if local_sum > dim_cap: local_sum = dim_cap
            if local_sum < -dim_cap: local_sum = -dim_cap
            # Risk direction adjustments
            if is_risk and dim in ("growth_pp", "margin_bps"):
                local_sum = -abs(local_sum)
            if is_risk and dim == "wacc_bps":
                local_sum = abs(local_sum)  # increase WACC
            if is_risk and dim == "capex_rate_bps":
                local_sum = abs(local_sum)  # higher capex intensity
            prev = accum[dim]
            accum[dim] += local_sum
            # Enforce global cumulative cap
            cap_val = GLOBAL_CUM_CAPS[dim]
            if accum[dim] > cap_val: accum[dim] = cap_val
            if accum[dim] < -cap_val: accum[dim] = -cap_val
            applied = accum[dim] - prev
            if applied != 0:
                contributions.append({
                    "title": item.get("title"),
                    "event_type": etype,
                    "dimension": dim,
                    "applied": applied,
                    "confidence": conf,
                    "timeline": item.get("timeline"),
                })
    # Convert to model override units (decimals)
    effective = {
        "growth_delta_dec": accum["growth_pp"] / 100.0,
        "margin_uplift_dec": accum["margin_bps"] / 10000.0,
        "capex_rate_delta_dec": accum["capex_rate_bps"] / 10000.0,
        "wacc_delta_dec": accum["wacc_bps"] / 10000.0,
    }
    # Conversion audit log (raw -> decimal) for transparency & downstream reporting
    conversion_log = [
        {
            "dimension": "growth",
            "raw_pp": accum["growth_pp"],
            "converted_decimal": effective["growth_delta_dec"],
            "formula": "growth_pp / 100"
        },
        {
            "dimension": "margin",
            "raw_bps": accum["margin_bps"],
            "converted_decimal": effective["margin_uplift_dec"],
            "formula": "margin_bps / 10000"
        },
        {
            "dimension": "capex_rate",
            "raw_bps": accum["capex_rate_bps"],
            "converted_decimal": effective["capex_rate_delta_dec"],
            "formula": "capex_rate_bps / 10000"
        },
        {
            "dimension": "wacc",
            "raw_bps": accum["wacc_bps"],
            "converted_decimal": effective["wacc_delta_dec"],
            "formula": "wacc_bps / 10000"
        },
    ]
    return {"accumulated": accum, "effective": effective, "contributions": contributions, "conversion_log": conversion_log}

__all__ = [
    "EVENT_PARAM_TEMPLATES",
    "GLOBAL_CUM_CAPS",
    "classify_event",
    "aggregate_mapped_parameter_deltas",
]
