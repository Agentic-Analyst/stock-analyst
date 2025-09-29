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
from llms.config import get_llm
from event_param_mapping import classify_event
from qualitative_config import sector_adjustments, SOURCE_WEIGHTS, RECENCY_HALF_LIFE_DAYS
from financial_model_generator import FinancialModelGenerator

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

    source_weights = SOURCE_WEIGHTS
    recency_half_life = RECENCY_HALF_LIFE_DAYS
    if sector:
        s_adj = sector_adjustments(sector)
        if s_adj.get('scaling'):
            sector_scaling_adj = s_adj['scaling'] / scaling if scaling else 1.0
        if s_adj.get('cap'):
            sector_cap_adj = s_adj['cap'] / cap if cap else 1.0

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
                              term_growth: float, wacc: Optional[float]) -> Tuple[Optional[float], Dict[str, Any]]:
    gen = FinancialModelGenerator(ticker)
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
                "reason": "comprehensive justification linking events to adjustment",
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
        raw = get_llm()([
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


