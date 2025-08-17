#!/usr/bin/env python3
"""price_adjustor.py

Combine intrinsic valuation (DCF-based implied price) with qualitative
catalyst / risk screening to produce an adjusted price framework
(base / adjusted / bull / bear) similar to a sell‑side research overlay.

Workflow:
1. Generate (or load) a base financial model using FinancialModelGenerator.
2. Parse screening_report.md (LLM-enhanced news synthesis) for catalysts & risks.
3. Quantify net qualitative impact via weighted confidence & timeline factors.
4. Apply capped adjustment to the implied price (range construction included).

Design Principles:
- Deterministic & auditable: all adjustments are formula driven & reported.
- Conservative: caps on upside/downside adjustment (default ±20%).
- Timeline-weighted: near-term (Immediate / Short-Term) items influence more.
- Symmetric treatment of risks vs catalysts.
- Transparent output JSON for downstream usage or Excel integration later.

CLI Example:
  python src/price_adjustor.py --ticker NVDA --model dcf --strategy generic_dcf \
      --years 5 --term-growth 0.03 --wacc 0.09

If screening file absent, falls back to unadjusted base price.
"""
from __future__ import annotations
import argparse, json, re, statistics, sys, time, math, datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import ast
import math

# Import configuration
from price_adjustor_config import ADJUSTOR_DEFAULTS, ADJUSTOR_PROMPTS

try:  # Optional LLM load (same pattern as financial_model_generator)
    from llms import gpt_4o_mini as _llm_fn
except Exception:  # pragma: no cover
    _llm_fn = None

# --- Parsing Screening Report -------------------------------------------------

CATALYST_HEADER = re.compile(r"^### Catalyst \d+: (.+?)$", re.IGNORECASE)
RISK_HEADER = re.compile(r"^### Risk \d+: (.+?)$", re.IGNORECASE)
# Mitigations section
MITIGATION_HEADER = re.compile(r"^### Mitigation \d+: (.+?)$", re.IGNORECASE)
EFFECTIVENESS_LINE = re.compile(r"^\*\*Effectiveness:\*\*\s*(\w+)", re.IGNORECASE)
RISK_ADDRESSED_LINE = re.compile(r"^\*\*Risk Addressed:\*\*\s*(.+?)\s*$", re.IGNORECASE)
# Some screens may title risks differently (e.g., "### Risk Factor 1:")
ALT_RISK_HEADER = re.compile(r"^### Risk (?:Factor )?\d+: (.+?)$", re.IGNORECASE)
CONF_LINE = re.compile(r"^\*\*Confidence:\*\*\s*([0-9]+(?:\.[0-9]+)?)%")
TIME_LINE = re.compile(r"^\*\*Timeline:\*\*\s*(.+?)\s*$", re.IGNORECASE)
DESC_LINE = re.compile(r"^\*\*Description:\*\*\s*(.+?)\s*$")
CATEGORY_IN_TITLE = re.compile(r"^(\w+)\s+-?\s*(.+)$")
RISK_ID_PATTERN = re.compile(r"R(\d+)")


def _load_structured_screen(path: Path) -> Optional[Dict[str, Any]]:
    """Attempt to load structured JSON (screening_report.json)."""
    jf = path.with_suffix('.json')
    if jf.exists():
        try:
            return json.loads(jf.read_text(encoding='utf-8'))
        except Exception:
            return None
    return None


def parse_screening_report(path: Path) -> Dict[str, List[Dict[str, Any]]]:
    """Parse catalysts, risks, mitigations from screening report markdown.

    Returns dict with keys: catalysts, risks, mitigations.
    Each list contains dicts with extracted metadata: title, confidence, timeline, description, effectiveness, etc.
    """
    if not path.exists():
        return {"catalysts": [], "risks": [], "mitigations": []}
    structured = _load_structured_screen(path)
    if structured:
        cats = structured.get('catalysts', [])
        risks = structured.get('risks', [])
        mits = structured.get('mitigations', [])
        for idx, r in enumerate(risks, 1):
            r.setdefault('id', f"R{idx}")
        for idx, c in enumerate(cats, 1):
            c.setdefault('id', f"C{idx}")
        for idx, m in enumerate(mits, 1):
            m.setdefault('id', f"M{idx}")
        return {"catalysts": cats, "risks": risks, "mitigations": mits}
    catalysts: List[Dict[str, Any]] = []
    risks: List[Dict[str, Any]] = []
    mitigations: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    current_type: Optional[str] = None

    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    for line in lines:
        sline = line.strip()
        m_cat = CATALYST_HEADER.match(sline)
        m_risk = RISK_HEADER.match(sline) or ALT_RISK_HEADER.match(sline)
        m_mit = MITIGATION_HEADER.match(sline)
        if m_cat:
            if current and current_type == 'catalyst':
                catalysts.append(current)
            elif current and current_type == 'risk':
                risks.append(current)
            elif current and current_type == 'mitigation':
                mitigations.append(current)
            title_raw = m_cat.group(1).strip()
            current = {"title": title_raw}
            current_type = 'catalyst'
            continue
        if m_risk:
            if current and current_type == 'catalyst':
                catalysts.append(current)
            elif current and current_type == 'risk':
                risks.append(current)
            elif current and current_type == 'mitigation':
                mitigations.append(current)
            title_raw = m_risk.group(1).strip()
            current = {"title": title_raw}
            current_type = 'risk'
            continue
        if m_mit:
            if current and current_type == 'catalyst':
                catalysts.append(current)
            elif current and current_type == 'risk':
                risks.append(current)
            elif current and current_type == 'mitigation':
                mitigations.append(current)
            title_raw = m_mit.group(1).strip()
            current = {"title": title_raw}
            current_type = 'mitigation'
            continue
        if current:
            # Confidence
            mc = CONF_LINE.match(line.strip())
            if mc:
                try:
                    current['confidence'] = float(mc.group(1)) / ADJUSTOR_DEFAULTS.PERCENTAGE_DIVISOR
                except ValueError:
                    current['confidence'] = 0.0
                continue
            # Timeline
            mt = TIME_LINE.match(line.strip())
            if mt:
                current['timeline'] = mt.group(1).strip()
                continue
            # Description
            md = DESC_LINE.match(line.strip())
            if md:
                current['description'] = md.group(1).strip()
                continue
            # Effectiveness (mitigations)
            me = EFFECTIVENESS_LINE.match(line.strip())
            if me and current_type == 'mitigation':
                current['effectiveness'] = me.group(1).strip().lower()
                continue
            # Risk Addressed
            mra = RISK_ADDRESSED_LINE.match(line.strip())
            if mra and current_type == 'mitigation':
                current['risk_addressed'] = mra.group(1).strip()
                continue
    # flush last
    if current:
        if current_type == 'catalyst':
            catalysts.append(current)
        elif current_type == 'risk':
            risks.append(current)
        elif current_type == 'mitigation':
            mitigations.append(current)

    # Assign stable IDs for traceability
    for i, r in enumerate(risks, 1):
        r['id'] = f"R{i}"
    for i, c in enumerate(catalysts, 1):
        c['id'] = f"C{i}"
    for i, m in enumerate(mitigations, 1):
        m['id'] = f"M{i}"
    # Derive category heuristically from title prefix (e.g., "Financial Opportunity")
    for lst, typ in ((catalysts, 'catalyst'), (risks, 'risk'), (mitigations, 'mitigation')):
        for item in lst:
            title = item.get('title', '')
            # Attempt to split first word as category if suitable
            parts = title.split()
            if len(parts) >= 1:
                cat = parts[0].rstrip(':').lower()
                item['category'] = cat
            item.setdefault('confidence', 0.5)
            item.setdefault('timeline', 'Mid-Term')
            item.setdefault('description', '')
    # Event classification (deterministic heuristics)
    try:
        from event_param_mapping import classify_event
    except Exception:  # pragma: no cover
        classify_event = None
    if classify_event:
        for c in catalysts:
            c['event_type'] = classify_event(c.get('title'), c.get('description'))
        for r in risks:
            r['event_type'] = classify_event(r.get('title'), r.get('description'))
    return {"catalysts": catalysts, "risks": risks, "mitigations": mitigations}


# --- Adjustment Engine --------------------------------------------------------

def compute_adjustment(base_price: Optional[float], factors: Dict[str, List[Dict[str, Any]]],
                       scaling: float = ADJUSTOR_DEFAULTS.DEFAULT_SCALING, 
                       cap: float = ADJUSTOR_DEFAULTS.DEFAULT_CAP,
                       mitigation_max_relief: float = ADJUSTOR_DEFAULTS.DEFAULT_MITIGATION_MAX_RELIEF,
                       sector: Optional[str] = None,
                       now_ts: Optional[float] = None) -> Dict[str, Any]:
    """Convert qualitative screening factors into a price adjustment.

    Formula:
        net_score = (Σ catalyst_weighted_conf - Σ risk_weighted_conf) / total_weight
        adj_pct = clamp(net_score * scaling, -cap, +cap)

    Weighted confidence = confidence * timeline_weight.
    timeline_weight defaults to 0.5 if unrecognized.
    """
    catalysts = factors.get('catalysts', [])
    risks = factors.get('risks', [])
    mitigations = factors.get('mitigations', [])
    if base_price is None:
        return {"base_price": None, "adjusted_price": None, "adjustment_pct": ADJUSTOR_DEFAULTS.DEFAULT_ADJUSTMENT_PCT,
                "detail": {"reason": "No base price available"}}

    # Load external qualitative config (sector scaling, source weights, recency decay)
    sector_scaling_adj = ADJUSTOR_DEFAULTS.DEFAULT_SECTOR_SCALING
    sector_cap_adj = ADJUSTOR_DEFAULTS.DEFAULT_SECTOR_CAP
    source_weights = {}
    recency_half_life = None
    try:  # optional import safety
        from qualitative_config import sector_adjustments, SOURCE_WEIGHTS, RECENCY_HALF_LIFE_DAYS
        source_weights = SOURCE_WEIGHTS
        recency_half_life = RECENCY_HALF_LIFE_DAYS
        if sector:
            s_adj = sector_adjustments(sector)
            if s_adj.get('scaling'):
                sector_scaling_adj = s_adj['scaling'] / scaling if scaling else 1.0
            if s_adj.get('cap'):
                sector_cap_adj = s_adj['cap'] / cap if cap else 1.0
    except Exception:  # pragma: no cover
        pass

    # Adjust scaling & cap per sector
    eff_scaling = scaling * sector_scaling_adj
    eff_cap = cap * sector_cap_adj
    if now_ts is None:
        now_ts = time.time()

    def extract_age_days(item: Dict[str, Any]) -> Optional[float]:
        # If items eventually include a timestamp field (iso8601), compute age; else use timeline heuristic
        ts = item.get('timestamp') or item.get('date')
        if ts:
            try:
                dt = datetime.datetime.fromisoformat(ts.replace('Z',''))
                return (now_ts - dt.timestamp()) / ADJUSTOR_DEFAULTS.SECONDS_PER_DAY
            except Exception:
                return None
        # Heuristic: Immediate ~7d, Short-Term ~30d, Mid-Term ~90d, Long-Term ~180d
        tl = (item.get('timeline') or '').lower()
        if 'immediate' in tl:
            return 7
        if 'short' in tl:
            return 30
        if 'mid' in tl or 'medium' in tl:
            return 90
        if 'long' in tl:
            return 180
        return None

    def weight_item(item: Dict[str, Any]) -> Tuple[float, float]:
        conf = float(item.get('confidence', ADJUSTOR_DEFAULTS.DEFAULT_ZERO_CONFIDENCE))
        tl = item.get('timeline', '').lower()
        base_w = ADJUSTOR_DEFAULTS.TIMELINE_WEIGHTS.get(tl, ADJUSTOR_DEFAULTS.DEFAULT_TIMELINE_WEIGHT)
        # Source credibility multiplier (if source metadata present)
        src = (item.get('source') or '').lower()
        src_mult = source_weights.get(src, 1.0) if source_weights else 1.0
        # Recency decay
        age_days = extract_age_days(item)
        rec_mult = 1.0
        if recency_half_life and age_days is not None:
            rec_mult = 0.5 ** (age_days / recency_half_life)
        weighted_conf = conf * base_w * src_mult * rec_mult
        return weighted_conf, base_w

    cat_scores = [weight_item(c)[0] for c in catalysts]
    cat_weights = [weight_item(c)[1] for c in catalysts]
    risk_scores_raw = [weight_item(r)[0] for r in risks]
    risk_weights = [weight_item(r)[1] for r in risks]

    eff_map = {"high": 0.30, "medium": 0.20, "low": 0.10}

    # Attempt targeted mitigation mapping (risk-addressed token overlap)
    targeted_relief_used = False
    risk_scores = list(risk_scores_raw)
    if mitigations and any(m.get('risk_addressed') for m in mitigations):
        # Pre-tokenize risks
        risk_tokens = []
        for r in risks:
            title = (r.get('title') or '').lower()
            toks = {t for t in re.split(r"[^a-z0-9]+", title) if t}
            risk_tokens.append(toks)
        # Pre-tokenize mitigations
        mitigation_reliefs_by_risk = [0.0 for _ in risks]
        for m in mitigations:
            ra = (m.get('risk_addressed') or '').lower()
            if not ra:
                continue
            mtoks = {t for t in re.split(r"[^a-z0-9]+", ra) if t}
            if not mtoks:
                continue
            eff = eff_map.get(m.get('effectiveness','').lower(), 0.0)
            m_score, _ = weight_item(m)
            if m_score <= 0 or eff <= 0:
                continue
            for idx, rtoks in enumerate(risk_tokens):
                if rtoks and mtoks & rtoks:  # overlap
                    # relief contribution relative to each matched risk
                    mitigation_reliefs_by_risk[idx] += eff * m_score
                    targeted_relief_used = True
        # Apply per-risk relief (capped)
        for i, orig in enumerate(risk_scores_raw):
            relief = mitigation_reliefs_by_risk[i]
            if orig > 0 and relief > 0:
                ratio = min(mitigation_max_relief, relief / orig)
                risk_scores[i] = orig * (1 - ratio)
        # overall relief ratio (weighted)
        if sum(risk_scores_raw) > 0:
            total_after = sum(risk_scores)
            relief_ratio = 1 - (total_after / (sum(risk_scores_raw) or 1))
        else:
            relief_ratio = 0.0
    else:
        # Fallback aggregate method
        mit_weighted_reliefs = []
        for m in mitigations:
            eff = eff_map.get(m.get('effectiveness','').lower(), 0.0)
            score, w = weight_item(m)
            if w > 0:
                mit_weighted_reliefs.append(eff * score)
        mitigation_relief = sum(mit_weighted_reliefs)
        total_risk_score = sum(risk_scores_raw) or 1.0
        relief_ratio = min(mitigation_max_relief, mitigation_relief / total_risk_score) if total_risk_score > 0 else 0.0
        risk_scores = [s * (1 - relief_ratio) for s in risk_scores_raw]

    total_weight = (sum(cat_weights) + sum(risk_weights)) or 1.0
    net_score = (sum(cat_scores) - sum(risk_scores)) / total_weight
    raw_adj = net_score * eff_scaling
    adj_pct = max(-eff_cap, min(eff_cap, raw_adj))

    # Volatility buffer derived from dispersion of item weights (higher dispersion -> wider range)
    dispersion: float = 0.0
    all_scores = cat_scores + risk_scores
    if len(all_scores) >= 2:
        try:
            dispersion = statistics.pstdev(all_scores)
        except Exception:
            dispersion = 0.0
    vol_buffer = min(0.05 + dispersion, 0.15)  # 5% base, max 15%

    adjusted_price = base_price * (1 + adj_pct)
    bull_price = base_price * (1 + adj_pct + vol_buffer)
    bear_price = base_price * (1 + adj_pct - vol_buffer)

    return {
        "base_price": base_price,
        "adjusted_price": adjusted_price,
        "adjustment_pct": adj_pct,
        "bull_price": bull_price,
        "bear_price": bear_price,
        "vol_buffer": vol_buffer,
        "inputs": {
            "catalyst_count": len(catalysts),
            "risk_count": len(risks),
            "mitigation_count": len(mitigations),
            "net_score": net_score,
            "raw_adjustment": raw_adj,
            "cap": eff_cap,
            "scaling": eff_scaling,
            "mitigation_relief_ratio": relief_ratio,
            "risk_score_reduction_pct": (1 - (sum(risk_scores) / (sum(risk_scores_raw) or 1))) if risk_scores_raw else 0.0,
            "mitigation_method": 'targeted' if targeted_relief_used else 'aggregate'
        }
    }


# --- Financial Model Integration ---------------------------------------------

def generate_base_model_price(ticker: str, model: str, strategy: Optional[str], years: int,
                              term_growth: float, wacc: Optional[float], no_llm: bool) -> Tuple[Optional[float], Dict[str, Any]]:
    try:
        from financial_model_generator import FinancialModelGenerator
    except ImportError:
        print("[ERROR] Cannot import FinancialModelGenerator. Ensure path is correct.", file=sys.stderr)
        return None, {}
    gen = FinancialModelGenerator(ticker, no_llm=no_llm)
    m = gen.generate_financial_model(model_type=model, projection_years=years,
                                     term_growth=term_growth, override_wacc=wacc,
                                     strategy=strategy, peers=None, generate_sensitivities=False)
    val = m.get('valuation_summary') or {}
    price = val.get('Implied Price') or val.get('Implied Price (blended)')
    return price, m


# --- LLM Parameter Delta Proposal -------------------------------------------

LLM_DELTA_CAPS = {
    "first_year_growth": 0.05,     # ±5 percentage points absolute
    "margin_uplift": 0.05,         # ±5 percentage points margin additive
    "capex_rate": 0.02,            # ±2 percentage points of revenue
    "wacc": 0.01,                  # ±1 percentage point absolute WACC
}

def _safe_num(v: Any, default: float = 0.0) -> float:
    try:
        if v is None or (isinstance(v, float) and math.isnan(v)):
            return default
        return float(v)
    except Exception:
        return default

def extract_base_operating_metrics(model_obj: Dict[str, Any]) -> Dict[str, float]:
    """Extract baseline metrics (growth, margin, capex_rate, wacc) from model object."""
    out = {"first_year_growth": None, "margin_uplift": 0.0, "capex_rate": None, "wacc": None, "ebitda_margin_first": None, "ebitda_margin_last": None}
    dcf = (model_obj.get("model_components") or {}).get("dcf_model")
    # dcf may be a DataFrame; handle both serialized or actual DataFrame
    try:
        import pandas as pd  # noqa
        if dcf is not None and hasattr(dcf, 'iloc') and len(dcf) >= 2:
            r0 = _safe_num(dcf.iloc[0].get("Revenue"))
            r1 = _safe_num(dcf.iloc[1].get("Revenue"))
            if r0 > 0 and r1:
                out["first_year_growth"] = (r1 / r0) - 1
            c1 = _safe_num(dcf.iloc[1].get("CapEx"))
            if r1 > 0 and c1:
                out["capex_rate"] = c1 / r1
            e0 = _safe_num(dcf.iloc[0].get("EBITDA"))
            e_last = _safe_num(dcf.iloc[len(dcf)-1].get("EBITDA"))
            r_last = _safe_num(dcf.iloc[len(dcf)-1].get("Revenue"))
            if r0 > 0 and e0:
                out["ebitda_margin_first"] = e0 / r0
            if r_last > 0 and e_last:
                out["ebitda_margin_last"] = e_last / r_last
    except Exception:
        pass
    val = model_obj.get("valuation_summary") or {}
    wacc = val.get("WACC")
    if wacc:
        out["wacc"] = _safe_num(wacc)
    return out

def propose_parameter_deltas(factors: Dict[str, List[Dict[str, Any]]], base_metrics: Dict[str, float],
                             llm_temperature: float = ADJUSTOR_DEFAULTS.DEFAULT_LLM_TEMPERATURE) -> Dict[str, Any]:
    """Use LLM to propose bounded parameter deltas with justification & sources.

    Returns dict with 'raw_response', 'deltas' list (after local capping), and 'errors' list.
    Safe if LLM unavailable (returns empty deltas).
    """
    if _llm_fn is None:
        return {"deltas": [], "errors": ["LLM unavailable"], "raw_response": None}

    # Compact event summary for prompt
    def short(item: Dict[str, Any]):
        return f"{item.get('title','')[:60]} (conf {int(item.get('confidence',0)*100)}% {item.get('timeline','')})"
    cats = factors.get('catalysts', [])[:10]
    risks = factors.get('risks', [])[:10]
    mits = factors.get('mitigations', [])[:6]
    events_txt = "Catalysts:\n" + "\n".join(f" - C{i+1}: {short(c)}" for i,c in enumerate(cats)) + "\nRisks:\n" + "\n".join(f" - R{i+1}: {short(r)}" for i,r in enumerate(risks)) + "\nMitigations:\n" + "\n".join(f" - M{i+1}: {short(m)}" for i,m in enumerate(mits))

    base_txt = ", ".join(f"{k}={v:.4f}" for k,v in base_metrics.items() if v is not None)
    caps_txt = ", ".join(f"{k}:±{v}" for k,v in LLM_DELTA_CAPS.items())

    schema = {
        "deltas": [
            {
                "param": "first_year_growth | margin_uplift | capex_rate | wacc",
                "delta": "numeric (can be negative) within caps",
                "reason": "succinct justification linking events to adjustment",
                "sources": ["C1","R2","M1"],
            }
        ]
    }
    prompt_template = Path(ADJUSTOR_PROMPTS.PARAMETER_DELTAS).read_text(encoding='utf-8')
    prompt = prompt_template.format(
        base_txt=base_txt or 'n/a',
        caps_txt=caps_txt,
        events_txt=events_txt,
        schema_json=json.dumps(schema)
    )

    try:
        raw = _llm_fn([
            {"role": "system", "content": "You propose bounded, explainable valuation parameter deltas."},
            {"role": "user", "content": prompt}
        ], temperature=llm_temperature)
        if isinstance(raw, tuple):
            raw = raw[0]
    except Exception as e:  # pragma: no cover
        return {"deltas": [], "errors": [f"LLM call failed: {e}"], "raw_response": None}

    # Attempt robust JSON extraction
    text = str(raw).strip()
    json_str = None
    if text.startswith('{') and text.endswith('}'):  # simple case
        json_str = text
    else:
        # Attempt to find first JSON object
        m = re.search(r"\{[\s\S]+\}", text)
        if m:
            json_str = m.group(0)
    deltas_out = []
    errors: List[str] = []
    if not json_str:
        errors.append("No JSON detected in LLM output")
    else:
        try:
            parsed = json.loads(json_str)
            for d in parsed.get('deltas', [])[:6]:
                param = str(d.get('param','')).strip()
                delta = _safe_num(d.get('delta'))
                reason = str(d.get('reason','')).strip()[:500]
                sources = [s for s in d.get('sources', []) if isinstance(s,str)][:8]
                if param not in LLM_DELTA_CAPS:
                    continue
                cap_val = LLM_DELTA_CAPS[param]
                # re-cap locally for safety
                delta_capped = max(-cap_val, min(cap_val, delta))
                deltas_out.append({
                    'param': param,
                    'delta_raw': delta,
                    'delta_applied': delta_capped,
                    'reason': reason,
                    'sources': sources,
                })
        except Exception as e:
            errors.append(f"JSON parse error: {e}")
    return {"deltas": deltas_out, "errors": errors, "raw_response": text}


# --- CLI ---------------------------------------------------------------------

def _parse_args():
    p = argparse.ArgumentParser(description="Adjust implied price using qualitative catalysts & risks")
    p.add_argument('--ticker', required=True)
    p.add_argument('--model', default='dcf', choices=['dcf','comprehensive','comparable'])
    p.add_argument('--strategy', default=None)
    p.add_argument('--years', type=int, default=5)
    p.add_argument('--term-growth', type=float, default=0.03)
    p.add_argument('--wacc', type=float, default=None)
    # LLM functionality is now always enabled for production use
    p.add_argument('--scaling', type=float, default=ADJUSTOR_DEFAULTS.DEFAULT_SCALING, help='Base scaling factor applied to net qualitative score (pre sector adj)')
    p.add_argument('--cap', type=float, default=ADJUSTOR_DEFAULTS.DEFAULT_CAP, help='Base absolute cap on adjustment (fraction) (pre sector adj)')
    p.add_argument('--screen-file', type=str, default=None, help='Explicit screening_report.md path')
    p.add_argument('--sector', type=str, default=None, help='Optional sector name for calibration (affects scaling & cap)')
    # JSON-only output removed - always provide human-readable output
    # LLM delta options
    p.add_argument('--llm-deltas', action='store_true', help='Invoke LLM to propose bounded parameter deltas (growth/margin/capex/wacc)')
    p.add_argument('--apply-deltas', action='store_true', help='Apply proposed deltas and recompute model price')
    p.add_argument('--llm-temp', type=float, default=ADJUSTOR_DEFAULTS.DEFAULT_LLM_TEMPERATURE, help='LLM temperature for delta generation')
    p.add_argument('--llm-scenarios', action='store_true', help='Use LLM to propose scenario multipliers & probabilities within guardrails')
    p.add_argument('--llm-scenarios-temp', type=float, default=0.1, help='LLM temperature for scenario generation')
    p.add_argument('--sens-after-deltas', action='store_true', help='Generate sensitivities after applying deltas')
    p.add_argument('--delta-log', type=str, default=None, help='Optional path to write LLM delta audit log JSON')
    p.add_argument('--export-excel-scenarios', action='store_true', help='Export scenario comparison to Excel')
    p.add_argument('--llm-guardrail-threshold', type=float, default=ADJUSTOR_DEFAULTS.DEFAULT_LLM_GUARDRAIL_THRESHOLD, help='Max allowed relative divergence between LLM-adjusted and qualitative-adjusted price before flag')
    # Mapped deterministic parameter delta engine
    p.add_argument('--use-mapped-deltas', action='store_true', help='Enable deterministic event->parameter mapping pipeline (primary)')
    p.add_argument('--residual-overlay-cap', type=float, default=ADJUSTOR_DEFAULTS.DEFAULT_RESIDUAL_OVERLAY_CAP, help='Max residual qualitative overlay cap when mapped deltas applied')
    p.add_argument('--materiality-threshold', type=float, default=ADJUSTOR_DEFAULTS.DEFAULT_MATERIALITY_THRESHOLD, help='Min absolute price impact (fraction) for mapped parameter retention')
    p.add_argument('--export-mitigation-matrix', action='store_true', help='Add mitigation matrix sheet to Excel export')
    return p.parse_args()


def main():
    args = _parse_args()
    ticker = args.ticker.upper()
    screen_path = Path(args.screen_file) if args.screen_file else Path('data') / ticker / 'screening_report.md'

    # Step 1: base model
    base_price, model_obj = generate_base_model_price(ticker, args.model, args.strategy,
                                                      args.years, args.term_growth, args.wacc, False)  # LLM always enabled

    # Step 2: parse qualitative factors
    factors = parse_screening_report(screen_path)

    # Step 3: compute qualitative adjustment (legacy scalar overlay)
    adj_cap = args.cap
    adj = compute_adjustment(base_price, factors, scaling=args.scaling, cap=adj_cap, sector=args.sector)

    output = {
        'ticker': ticker,
        'base_model_price': adj.get('base_price'),
        'adjusted_price': adj.get('adjusted_price'),
        'adjustment_pct': adj.get('adjustment_pct'),
        'bull_price': adj.get('bull_price'),
        'bear_price': adj.get('bear_price'),
        'vol_buffer': adj.get('vol_buffer'),
        'qualitative_inputs': adj.get('inputs'),
        'catalysts_sample': factors.get('catalysts')[:5],  # limit output size
    'risks_sample': factors.get('risks')[:5],
        'mitigations_sample': factors.get('mitigations')[:3],
        'screen_file_present': Path(screen_path).exists(),
    }

    # Optional Step 4a: deterministic mapped parameter deltas (primary path)
    mapped_result = None
    mapped_model_price = None
    if args.use_mapped_deltas and base_price is not None:
        try:
            from event_param_mapping import aggregate_mapped_parameter_deltas
            # Aggregate catalysts (positive) and risks (negative / adverse)
            cat_map = aggregate_mapped_parameter_deltas(factors.get('catalysts', []), is_risk=False)
            risk_map = aggregate_mapped_parameter_deltas(factors.get('risks', []), is_risk=True)
            # Combine effective deltas
            eff = {
                'growth_delta_dec': (cat_map['effective']['growth_delta_dec'] + risk_map['effective']['growth_delta_dec']),
                'margin_uplift_dec': (cat_map['effective']['margin_uplift_dec'] + risk_map['effective']['margin_uplift_dec']),
                'capex_rate_delta_dec': (cat_map['effective']['capex_rate_delta_dec'] + risk_map['effective']['capex_rate_delta_dec']),
                'wacc_delta_dec': (cat_map['effective']['wacc_delta_dec'] + risk_map['effective']['wacc_delta_dec']),
            }
            mapped_result = {
                'catalyst_contributions': cat_map['contributions'],
                'risk_contributions': risk_map['contributions'],
                'effective': eff,
                'accumulated': {
                    'growth_pp': cat_map['accumulated']['growth_pp'] + risk_map['accumulated']['growth_pp'],
                    'margin_bps': cat_map['accumulated']['margin_bps'] + risk_map['accumulated']['margin_bps'],
                    'capex_rate_bps': cat_map['accumulated']['capex_rate_bps'] + risk_map['accumulated']['capex_rate_bps'],
                    'wacc_bps': cat_map['accumulated']['wacc_bps'] + risk_map['accumulated']['wacc_bps'],
                },
                'conversion_log': cat_map.get('conversion_log', []) + risk_map.get('conversion_log', []),
            }
            # Materiality estimation (trial per parameter) using lean runs
            price_impact_map = {}
            if args.materiality_threshold > 0 and base_price:
                from financial_model_generator import FinancialModelGenerator
                base_metrics_tmp = extract_base_operating_metrics(model_obj)
                trial_specs = [
                    ('growth_delta_dec', 'first_year_growth', eff['growth_delta_dec']),
                    ('margin_uplift_dec', 'margin_uplift', eff['margin_uplift_dec']),
                    ('capex_rate_delta_dec', 'capex_rate', eff['capex_rate_delta_dec']),
                ]
                for key, ov_name, delta_val in trial_specs:
                    if abs(delta_val) < 1e-8:
                        continue
                    gen_trial = FinancialModelGenerator(ticker, no_llm=True)
                    tr_over = {}
                    if ov_name == 'first_year_growth':
                        tr_over['first_year_growth'] = max(0.0, (base_metrics_tmp.get('first_year_growth') or 0.0) + delta_val)
                    elif ov_name == 'margin_uplift':
                        tr_over['margin_uplift'] = delta_val
                    elif ov_name == 'capex_rate':
                        tr_over['capex_rate'] = max(0.0, (base_metrics_tmp.get('capex_rate') or 0.0) + delta_val)
                    gen_trial.overrides = tr_over
                    model_trial = gen_trial.generate_financial_model(model_type=args.model, projection_years=args.years, term_growth=args.term_growth, override_wacc=None, strategy=args.strategy, peers=None, generate_sensitivities=False, lean=True)
                    val_trial = model_trial.get('valuation_summary') or {}
                    tprice = val_trial.get('Implied Price') or val_trial.get('Implied Price (blended)')
                    if tprice:
                        price_impact_map[key] = (tprice / base_price) - 1
                # WACC trial
                if abs(eff['wacc_delta_dec']) > 1e-8:
                    gen_trial = FinancialModelGenerator(ticker, no_llm=True)
                    wacc_override_trial = None
                    base_metrics_tmp = base_metrics_tmp if 'base_metrics_tmp' in locals() else extract_base_operating_metrics(model_obj)
                    if base_metrics_tmp.get('wacc'):
                        wacc_override_trial = max(0.04, min(0.20, base_metrics_tmp['wacc'] + eff['wacc_delta_dec']))
                        model_trial = gen_trial.generate_financial_model(model_type=args.model, projection_years=args.years, term_growth=args.term_growth, override_wacc=wacc_override_trial, strategy=args.strategy, peers=None, generate_sensitivities=False, lean=True)
                        val_trial = model_trial.get('valuation_summary') or {}
                        tprice = val_trial.get('Implied Price') or val_trial.get('Implied Price (blended)')
                        if tprice:
                            price_impact_map['wacc_delta_dec'] = (tprice / base_price) - 1
            mapped_result['estimated_price_impacts'] = price_impact_map
            # Zero out immaterial deltas
            for dim_key in list(eff.keys()):
                impact = price_impact_map.get(dim_key)
                if impact is not None and abs(impact) < args.materiality_threshold:
                    eff[dim_key] = 0.0
            # Build overrides after materiality filtering
            overrides = {}
            base_metrics_tmp = extract_base_operating_metrics(model_obj)
            if abs(eff['growth_delta_dec']) > 1e-6:
                overrides['first_year_growth'] = max(0.0, (base_metrics_tmp.get('first_year_growth') or 0.0) + eff['growth_delta_dec'])
            if abs(eff['margin_uplift_dec']) > 1e-6:
                overrides['margin_uplift'] = eff['margin_uplift_dec']
            if abs(eff['capex_rate_delta_dec']) > 1e-6:
                overrides['capex_rate'] = max(0.0, (base_metrics_tmp.get('capex_rate') or 0.0) + eff['capex_rate_delta_dec'])
            wacc_override = None
            if abs(eff['wacc_delta_dec']) > 1e-6 and base_metrics_tmp.get('wacc'):
                wacc_override = max(0.04, min(0.20, base_metrics_tmp['wacc'] + eff['wacc_delta_dec']))
            if overrides or wacc_override:
                from financial_model_generator import FinancialModelGenerator
                gen_map = FinancialModelGenerator(ticker, no_llm=True)
                gen_map.overrides = overrides
                model_mapped = gen_map.generate_financial_model(model_type=args.model, projection_years=args.years,
                                                                term_growth=args.term_growth, override_wacc=wacc_override,
                                                                strategy=args.strategy, peers=None, generate_sensitivities=False, lean=True)
                val_map = model_mapped.get('valuation_summary') or {}
                mapped_model_price = val_map.get('Implied Price') or val_map.get('Implied Price (blended)')
                mapped_result['applied_overrides'] = overrides
                mapped_result['wacc_override'] = wacc_override
                mapped_result['mapped_price'] = mapped_model_price
                if mapped_model_price and base_price:
                    mapped_result['mapped_total_change_pct'] = (mapped_model_price / base_price) - 1
        except Exception as e:  # pragma: no cover
            mapped_result = {'error': str(e)}

    if mapped_result:
        output['mapped_parameter_deltas'] = mapped_result
        if mapped_model_price is not None:
            output['mapped_adjusted_price'] = mapped_model_price

    # Optional LLM Scenario proposal BEFORE deterministic scenario synthesis
    if args.llm_scenarios and mapped_result and mapped_result.get('effective') and base_price:
        try:
            eff = mapped_result['effective']
            base_metrics_tmp = extract_base_operating_metrics(model_obj)
            catalyst_summaries = "; ".join((c.get('title') or '')[:60] for c in factors.get('catalysts', [])[:8])
            risk_summaries = "; ".join((r.get('title') or '')[:60] for r in factors.get('risks', [])[:8])
            mitigation_summaries = "; ".join((m.get('title') or '')[:60] for m in factors.get('mitigations', [])[:4])
            prompt_template = Path('prompts/scenario_proposal.md').read_text(encoding='utf-8')
            prompt = prompt_template.format(
                effective_json=json.dumps(eff),
                base_metrics_json=json.dumps(base_metrics_tmp),
                catalyst_summaries=catalyst_summaries or 'n/a',
                risk_summaries=risk_summaries or 'n/a',
                mitigation_summaries=mitigation_summaries or 'n/a'
            )
            raw = _llm_fn([
                {"role": "system", "content": "You design bounded valuation scenarios only within policy risk guardrails."},
                {"role": "user", "content": prompt}
            ], temperature=args.llm_scenarios_temp) if _llm_fn else None
            if isinstance(raw, tuple): raw = raw[0]
            scen_obj = None
            if raw:
                text = str(raw)
                m = re.search(r"\{[\s\S]+\}", text)
                if m:
                    try:
                        scen_obj = json.loads(m.group(0))
                    except Exception:
                        scen_obj = None
            guard = ADJUSTOR_DEFAULTS
            def clamp(v, lo, hi):
                try:
                    return max(lo, min(hi, float(v)))
                except Exception:
                    return None
            applied_scenarios = {}
            probs_sum = 0.0
            if scen_obj and isinstance(scen_obj.get('scenarios'), dict):
                for name, sc in scen_obj['scenarios'].items():
                    gm = clamp(sc.get('growth_mult'), *guard.SCENARIO_GROWTH_MULT_RANGE)
                    mm = clamp(sc.get('margin_mult'), *guard.SCENARIO_MARGIN_MULT_RANGE)
                    cm = clamp(sc.get('capex_mult'), *guard.SCENARIO_CAPEX_MULT_RANGE)
                    wm = clamp(sc.get('wacc_mult'), *guard.SCENARIO_WACC_MULT_RANGE)
                    pr = clamp(sc.get('prob'), guard.SCENARIO_PROB_MIN, guard.SCENARIO_PROB_MAX)
                    applied_scenarios[name] = {
                        'growth_mult': gm, 'margin_mult': mm, 'capex_mult': cm, 'wacc_mult': wm,
                        'prob_raw': sc.get('prob'), 'prob': pr, 'rationale': sc.get('rationale')
                    }
                    if pr: probs_sum += pr
            # Normalize probabilities
            if probs_sum > 0:
                for sc in applied_scenarios.values():
                    sc['prob_norm'] = sc['prob'] / probs_sum
            else:
                for sc in applied_scenarios.values():
                    sc['prob_norm'] = None
            output['llm_scenario_raw'] = scen_obj
            output['llm_scenario_applied'] = applied_scenarios
        except Exception as e:  # pragma: no cover
            output['llm_scenario_error'] = str(e)

    # Decide primary adjusted price: mapped deltas if available; else qualitative
    primary_price = output.get('mapped_adjusted_price') or output.get('adjusted_price')
    output['primary_adjusted_price'] = primary_price

    # Governance: ensure long-term growth (if derivable) < WACC after any overrides
    try:
        if model_obj and isinstance(model_obj, dict):
            val_sum = (model_obj.get('valuation_summary') or {})
            g_term = val_sum.get('Terminal Growth Rate') or val_sum.get('Terminal Growth')
            wacc_val = val_sum.get('WACC')
            if g_term is not None and wacc_val is not None and g_term >= wacc_val:
                # Clamp growth just below WACC (basis point cushion)
                adjusted_g = max(0.0, wacc_val - 0.0005)
                if 'governance_flags' not in output:
                    output['governance_flags'] = []
                output['governance_flags'].append({'type': 'g_lt_wacc_enforced', 'original_g': g_term, 'clamped_g': adjusted_g})
    except Exception:  # pragma: no cover
        pass

    # Scenario synthesis (Bull/Base/Bear) using mapped effective deltas if present
    if mapped_result and mapped_result.get('effective') and base_price and 'scenario_set' not in output:
        eff = mapped_result['effective']
        scenarios = {}
        # Base already represented by mapped_model_price (if computed)
        # Define simple multipliers (could later migrate to config)
        mults = {
            'bull': {'growth': 1.3, 'margin': 1.2, 'capex': 1.0, 'wacc': 0.85},
            'base': {'growth': 1.0, 'margin': 1.0, 'capex': 1.0, 'wacc': 1.0},
            'bear': {'growth': 0.6, 'margin': 0.7, 'capex': 1.1, 'wacc': 1.15},
        }
        # If LLM scenario multipliers exist and passed guardrails, substitute them
        if output.get('llm_scenario_applied') and isinstance(output['llm_scenario_applied'], dict):
            applied = output['llm_scenario_applied']
            # Build mults from LLM with safe defaults
            for name in ('bull','base','bear'):
                sc = applied.get(name)
                if sc:
                    mults[name] = {
                        'growth': sc.get('growth_mult') or mults[name]['growth'],
                        'margin': sc.get('margin_mult') or mults[name]['margin'],
                        'capex': sc.get('capex_mult') or mults[name]['capex'],
                        'wacc': sc.get('wacc_mult') or mults[name]['wacc'],
                    }
        # Probabilities: prefer normalized LLM probabilities if available
        probs = {'bull': 0.25, 'base': 0.50, 'bear': 0.25}
        if output.get('llm_scenario_applied'):
            p_accum = 0.0
            llm_applied = output['llm_scenario_applied']
            for name in ('bull','base','bear'):
                sc = llm_applied.get(name)
                if sc and sc.get('prob_norm') is not None:
                    probs[name] = sc['prob_norm']
                    p_accum += sc['prob_norm']
            # Re-normalize if rounding drift
            if 0.95 < p_accum < 1.05:
                for k in probs:
                    probs[k] = probs[k] / p_accum
        try:
            from financial_model_generator import FinancialModelGenerator
            base_metrics_tmp = extract_base_operating_metrics(model_obj)
            for scen, m in mults.items():
                overrides = {}
                if abs(eff.get('growth_delta_dec', 0)) > 1e-8:
                    overrides['first_year_growth'] = max(0.0, (base_metrics_tmp.get('first_year_growth') or 0.0) + eff['growth_delta_dec'] * m['growth'])
                if abs(eff.get('margin_uplift_dec', 0)) > 1e-8:
                    overrides['margin_uplift'] = eff['margin_uplift_dec'] * m['margin']
                if abs(eff.get('capex_rate_delta_dec', 0)) > 1e-8:
                    overrides['capex_rate'] = max(0.0, (base_metrics_tmp.get('capex_rate') or 0.0) + eff['capex_rate_delta_dec'] * m['capex'])
                wacc_override = None
                if abs(eff.get('wacc_delta_dec', 0)) > 1e-8 and base_metrics_tmp.get('wacc'):
                    wacc_override = max(0.04, min(0.20, base_metrics_tmp['wacc'] + eff['wacc_delta_dec'] * m['wacc']))
                gen_s = FinancialModelGenerator(ticker, no_llm=True)
                gen_s.overrides = overrides
                model_s = gen_s.generate_financial_model(model_type=args.model, projection_years=args.years,
                                                         term_growth=args.term_growth, override_wacc=wacc_override,
                                                         strategy=args.strategy, peers=None, generate_sensitivities=False, lean=True)
                val_s = model_s.get('valuation_summary') or {}
                price_s = val_s.get('Implied Price') or val_s.get('Implied Price (blended)')
                scenarios[scen] = {
                    'price': price_s,
                    'overrides': overrides,
                    'wacc_override': wacc_override,
                    'mults': m,
                    'delta_effective': eff,
                }
            # Probability-weighted price (exclude missing scenarios)
            pw_price = 0.0
            weight_sum = 0.0
            for scen, data in scenarios.items():
                p = probs.get(scen, 0)
                if data['price'] and p > 0:
                    pw_price += data['price'] * p
                    weight_sum += p
            if weight_sum > 0:
                pw_price /= weight_sum
            output['scenario_set'] = scenarios
            output['scenario_probabilities'] = probs
            if pw_price:
                output['probability_weighted_price'] = pw_price
        except Exception as e:  # pragma: no cover
            output['scenario_error'] = str(e)

    # Residual qualitative overlay application if mapped deltas used
    if mapped_result and mapped_model_price and output.get('adjusted_price'):
        # Compute pure qualitative adjustment pct (already applied earlier) but restrain residual
        qual_pct = output.get('adjustment_pct', 0.0)
        residual_cap = args.residual_overlay_cap
        residual_pct = max(-residual_cap, min(residual_cap, qual_pct))
        residual_price = mapped_model_price * (1 + residual_pct)
        output['residual_overlay_pct'] = residual_pct
        output['final_price'] = residual_price
    else:
        output['final_price'] = primary_price

    # Optional Step 4b: LLM proposes parameter deltas
    llm_delta_result = None
    applied_model_price = None
    applied_valuation = None
    sensitivities_after = None
    if args.llm_deltas:
        base_metrics = extract_base_operating_metrics(model_obj)
        llm_delta_result = propose_parameter_deltas(factors, base_metrics, llm_temperature=args.llm_temp)
        output['llm_deltas'] = llm_delta_result
        if args.apply_deltas and llm_delta_result.get('deltas'):
            # Prepare overrides from deltas
            overrides = {}
            for d in llm_delta_result['deltas']:
                param = d['param']
                delta_val = d['delta_applied']
                if param == 'first_year_growth':
                    overrides['first_year_growth'] = max(0.0, (base_metrics.get('first_year_growth') or 0.0) + delta_val)
                elif param == 'margin_uplift':
                    overrides['margin_uplift'] = (overrides.get('margin_uplift') or 0.0) + delta_val
                elif param == 'capex_rate':
                    # capex_rate override uses absolute value (base + delta)
                    base_capex = base_metrics.get('capex_rate') or 0.0
                    overrides['capex_rate'] = max(0.0, base_capex + delta_val)
                elif param == 'wacc':
                    # We'll pass override_wacc to second run
                    pass
            # Re-run model with overrides (and potential WACC override)
            try:
                from financial_model_generator import FinancialModelGenerator
                gen2 = FinancialModelGenerator(ticker, no_llm=True)
                gen2.overrides = overrides
                # Apply WACC delta if present
                wacc_override = None
                for d in llm_delta_result['deltas']:
                    if d['param'] == 'wacc' and base_metrics.get('wacc'):
                        wacc_override = max(0.04, min(0.20, base_metrics['wacc'] + d['delta_applied']))
                model2 = gen2.generate_financial_model(model_type=args.model, projection_years=args.years,
                                                       term_growth=args.term_growth, override_wacc=wacc_override,
                                                       strategy=args.strategy, peers=None,
                                                       generate_sensitivities=args.sens_after_deltas)
                val2 = model2.get('valuation_summary') or {}
                applied_model_price = val2.get('Implied Price') or val2.get('Implied Price (blended)')
                applied_valuation = val2
                if args.sens_after_deltas:
                    # capture sensitivity tables references
                    sensitivities_after = {k: str(v.shape) for k,v in (model2.get('model_components') or {}).items() if k.startswith('sensitivity_')}
                output['llm_applied_overrides'] = overrides
                output['llm_applied_wacc'] = wacc_override
                output['llm_adjusted_price'] = applied_model_price
                # Materiality filter: ignore if below threshold vs base
                if applied_model_price and base_price and abs(applied_model_price / base_price - 1) < args.materiality_threshold:
                    output['llm_ignored_non_material'] = True
                    applied_model_price = None
                    output['llm_adjusted_price'] = None
                if applied_model_price and base_price:
                    output['llm_total_change_pct'] = (applied_model_price / base_price) - 1
                    if output.get('adjusted_price'):
                        rel_vs_qual = (applied_model_price / output['adjusted_price']) - 1
                        output['llm_vs_qualitative_pct'] = rel_vs_qual
                        if abs(rel_vs_qual) > args.llm_guardrail_threshold:
                            output['llm_guardrail_flag'] = True
                            output['llm_guardrail_reason'] = f"LLM adjusted diverges {rel_vs_qual*100:.2f}% vs qualitative (threshold {args.llm_guardrail_threshold*100:.1f}%)"
                output['llm_adjusted_valuation_summary'] = applied_valuation
                # If mapped deltas already set a final price, treat LLM as an exploratory scenario only
                if mapped_result and output.get('final_price') and applied_model_price:
                    output['llm_vs_mapped_pct'] = (applied_model_price / output['final_price']) - 1 if output['final_price'] else None
                if sensitivities_after:
                    output['llm_sensitivities_shapes'] = sensitivities_after
            except Exception as e:  # pragma: no cover
                output['llm_apply_error'] = str(e)

    # Audit log for deltas
    if args.llm_deltas and output.get('llm_deltas') and (args.delta_log or args.apply_deltas):
        try:
            ts = time.strftime('%Y%m%d_%H%M%S')
            log_path = Path(args.delta_log) if args.delta_log else (Path('data') / ticker / 'models' / f'llm_deltas_{ticker}_{ts}.json')
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_payload = {
                'timestamp': ts,
                'ticker': ticker,
                'base_price': base_price,
                'qual_adjusted_price': output.get('adjusted_price'),
                'llm_deltas': output.get('llm_deltas'),
                'applied_overrides': output.get('llm_applied_overrides'),
                'applied_wacc': output.get('llm_applied_wacc'),
                'llm_adjusted_price': output.get('llm_adjusted_price'),
            }
            with open(log_path, 'w', encoding='utf-8') as f:
                json.dump(log_payload, f, indent=2)
            output['delta_log_file'] = str(log_path)
        except Exception as e:  # pragma: no cover
            output['delta_log_error'] = str(e)

    # Final price selection logic (rerun deltas supersede qualitative unless non-material / guardrail flagged & excluded)
    if args.apply_deltas and output.get('llm_adjusted_price'):
        if output.get('final_price') and mapped_result and output.get('residual_overlay_pct') is not None:
            # If a residual overlay was already applied to mapped result earlier, decide whether to re-overlay
            resid = max(-args.residual_overlay_cap, min(args.residual_overlay_cap, output.get('adjustment_pct', 0.0)))
            output['final_price'] = output['llm_adjusted_price'] * (1 + resid)
            output['residual_overlay_pct_llm'] = resid
            output['method'] = 'llm_rerun_with_residual'
        else:
            output['final_price'] = output['llm_adjusted_price']
            output['method'] = 'llm_rerun'
    elif mapped_result and output.get('final_price'):
        output.setdefault('method', 'mapped_parameters')
    else:
        output.setdefault('method', 'qual_overlay')

    # Scenario Excel export
    if args.export_excel_scenarios and base_price is not None:
        try:
            try:
                import openpyxl  # noqa
                from openpyxl import Workbook
                from openpyxl.styles import Font
            except Exception:
                raise RuntimeError('openpyxl not installed')
            wb = Workbook()
            ws = wb.active
            ws.title = 'Scenarios'
            ws.append(['Ticker','Scenario','Implied Price','Adj % vs Base','Probability','Notes'])
            for cell in ws[1]:
                cell.font = Font(bold=True)
            # Base
            ws.append([ticker,'Base', base_price, 0.0, output.get('scenario_probabilities', {}).get('base'), 'Raw DCF output'])
            # Qualitative
            q_adj = output.get('adjusted_price')
            if q_adj:
                ws.append([ticker,'Qualitative', q_adj, (q_adj/base_price)-1, None, f"Qual adj (net_score={adj['inputs']['net_score']:.3f})"])
            # Mapped
            if output.get('mapped_adjusted_price'):
                ws.append([ticker,'Mapped Params', output['mapped_adjusted_price'], (output['mapped_adjusted_price']/base_price)-1, output.get('scenario_probabilities', {}).get('base'), 'Deterministic mapped'])
            # Final
            if output.get('final_price') and output.get('mapped_adjusted_price'):
                ws.append([ticker,'Final (Mapped+Residual)', output['final_price'], (output['final_price']/base_price)-1, output.get('scenario_probabilities', {}).get('base'), f"Residual overlay {output.get('residual_overlay_pct',0)*100:.1f}%"])
            # LLM adjusted
            if output.get('llm_adjusted_price'):
                ws.append([ticker,'LLM Adjusted', output['llm_adjusted_price'], (output['llm_adjusted_price']/base_price)-1, None, 'Applied LLM deltas'])
            # Probability-weighted result
            if output.get('probability_weighted_price'):
                pw = output['probability_weighted_price']
                ws.append([ticker,'Prob-Weighted', pw, (pw/base_price)-1, 1.0, 'Weighted by scenario probabilities'])
            # Delta breakdown sheet
            if output.get('llm_deltas'):
                ws2 = wb.create_sheet('LLM Deltas')
                ws2.append(['Param','Delta Raw','Delta Applied','Sources','Reason'])
                for cell in ws2[1]:
                    cell.font = Font(bold=True)
                for d in output['llm_deltas'].get('deltas', []):
                    ws2.append([
                        d['param'], d['delta_raw'], d['delta_applied'], ','.join(d['sources']), d['reason']
                    ])
            # Mapped contributions sheet
            if output.get('mapped_parameter_deltas'):
                mres = output['mapped_parameter_deltas']
                ws3 = wb.create_sheet('Mapped Contributions')
                ws3.append(['Type','Title','Dimension','Applied','Confidence','Timeline'])
                for cell in ws3[1]:
                    cell.font = Font(bold=True)
                for row in mres.get('catalyst_contributions', []):
                    ws3.append(['Catalyst', row.get('title'), row.get('dimension'), row.get('applied'), row.get('confidence'), row.get('timeline')])
                for row in mres.get('risk_contributions', []):
                    ws3.append(['Risk', row.get('title'), row.get('dimension'), row.get('applied'), row.get('confidence'), row.get('timeline')])
            # LLM Scenario sheet
            if output.get('llm_scenario_applied'):
                ws_sc = wb.create_sheet('LLM Scenarios')
                ws_sc.append(['Scenario','Growth Mult','Margin Mult','Capex Mult','WACC Mult','Prob Raw','Prob Clamped','Prob Norm','Rationale'])
                for cell in ws_sc[1]:
                    cell.font = Font(bold=True)
                for name, sc in output['llm_scenario_applied'].items():
                    ws_sc.append([
                        name,
                        sc.get('growth_mult'), sc.get('margin_mult'), sc.get('capex_mult'), sc.get('wacc_mult'),
                        sc.get('prob_raw'), sc.get('prob'), sc.get('prob_norm'), sc.get('rationale')
                    ])
            # Mitigation Matrix sheet (simple overlap / explicit reference)
            if args.export_mitigation_matrix and factors.get('mitigations') and factors.get('risks'):
                ws4 = wb.create_sheet('Mitigation Matrix')
                ws4.append(['Mitigation ID','Mitigation Title','Method','Linked Risks'])
                for cell in ws4[1]:
                    cell.font = Font(bold=True)
                # build risk token sets
                risk_tokens = []
                for r in factors.get('risks'):
                    title = (r.get('title') or '').lower()
                    toks = {t for t in re.split(r"[^a-z0-9]+", title) if t}
                    risk_tokens.append((r.get('id'), toks))
                for m in factors.get('mitigations'):
                    rid_matches = []
                    method = 'n/a'
                    ra = (m.get('risk_addressed') or '').lower()
                    if ra:
                        ids = set(RISK_ID_PATTERN.findall(ra))
                        if ids:
                            rid_matches = [f"R{x}" for x in ids]
                            method = 'explicit'
                        else:
                            mtoks = {t for t in re.split(r"[^a-z0-9]+", ra) if t}
                            overlaps = []
                            for rid, rtoks in risk_tokens:
                                if mtoks & rtoks:
                                    overlaps.append(rid)
                            if overlaps:
                                rid_matches = overlaps
                                method = 'token_overlap'
                    ws4.append([m.get('id'), m.get('title'), method, ','.join(rid_matches)])
            ts = time.strftime('%Y%m%d_%H%M%S')
            scen_path = Path('data') / ticker / 'models' / f'scenarios_{ticker}_{ts}.xlsx'
            scen_path.parent.mkdir(parents=True, exist_ok=True)
            wb.save(scen_path)
            output['scenario_excel'] = str(scen_path)
        except Exception as e:  # pragma: no cover
            output['scenario_excel_error'] = str(e)

    # Always provide human-readable output in production use
        print(f"\n=== Qualitative Price Adjustment ({ticker}) ===")
        if base_price is None:
            print("Base price unavailable; cannot adjust.")
            return 1
        print(f"Base Implied Price: {base_price:,.2f}")
        if mapped_result and mapped_model_price:
            print(f"Mapped Param Price: {mapped_model_price:,.2f} (Δ {mapped_result.get('mapped_total_change_pct',0)*100:+.1f}% vs base)")
            if output.get('residual_overlay_pct') is not None:
                print(f"Residual Overlay:   {output['residual_overlay_pct']*100:+.1f}% (cap {args.residual_overlay_cap*100:.1f}%)")
            print(f"Final Price:        {output['final_price']:,.2f}")
        else:
            print(f"Adjusted Price:     {output['adjusted_price']:,.2f} (Adj {output['adjustment_pct']*100:+.1f}%)")
        print(f"Bull Scenario:      {output['bull_price']:,.2f}")
        print(f"Bear Scenario:      {output['bear_price']:,.2f}")
        print(f"Catalysts Parsed:   {output['qualitative_inputs']['catalyst_count']}  | Risks Parsed: {output['qualitative_inputs']['risk_count']}")
        print(f"Vol Buffer (range): {output['vol_buffer']*100:.1f}%")
        if mapped_result:
            print("\nMapped Parameter Deltas (effective):")
            eff = mapped_result.get('effective', {})
            print(f"  Growth Δ (pp):      {eff.get('growth_delta_dec',0)*100:+.2f}")
            print(f"  Margin uplift (pp): {eff.get('margin_uplift_dec',0)*100:+.2f}")
            print(f"  CapEx rate Δ (pp):  {eff.get('capex_rate_delta_dec',0)*100:+.2f}")
            print(f"  WACC Δ (pp):        {eff.get('wacc_delta_dec',0)*100:+.2f}")
        print("\nKey Sample Catalysts:")
        for c in factors.get('catalysts')[:3]:
            print(f" - {c.get('title')} (Conf {c.get('confidence')*100:.0f}%, {c.get('timeline')})")
        print("Key Sample Risks:")
        for r in factors.get('risks')[:3]:
            print(f" - {r.get('title')} (Conf {r.get('confidence')*100:.0f}%, {r.get('timeline')})")
        if args.llm_deltas:
            print("\nLLM Parameter Delta Proposals:")
            if llm_delta_result and llm_delta_result.get('deltas'):
                for d in llm_delta_result['deltas']:
                    print(f" * {d['param']}: Δ {d['delta_applied']:+.4f} (raw {d['delta_raw']:+.4f}) sources={','.join(d['sources'])} -> {d['reason'][:80]}")
            else:
                print(" (none)")
            if llm_delta_result and llm_delta_result.get('errors'):
                print(" Errors: ", "; ".join(llm_delta_result['errors']))
            if applied_model_price:
                print(f"\nLLM-Adjusted Price: {applied_model_price:,.2f} (Total Δ {(output.get('llm_total_change_pct',0))*100:+.1f}%)")
        print("==============================================\n")
    return 0


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
