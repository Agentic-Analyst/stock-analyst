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
import argparse, json, re, statistics, sys, time
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import ast
import math

try:  # Optional LLM load (same pattern as financial_model_generator)
    from llms import gpt_4o_mini as _llm_fn
except Exception:  # pragma: no cover
    _llm_fn = None

# --- Parsing Screening Report -------------------------------------------------
TIMELINE_WEIGHTS = {
    "immediate": 1.00,
    "short-term": 0.80,
    "short term": 0.80,
    "mid-term": 0.50,
    "mid term": 0.50,
    "medium-term": 0.50,
    "long-term": 0.30,
    "long term": 0.30,
}

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


def parse_screening_report(path: Path) -> Dict[str, List[Dict[str, Any]]]:
    """Parse catalysts, risks, mitigations from screening report markdown.

    Returns dict with keys: catalysts, risks, mitigations.
    Each list contains dicts with extracted metadata: title, confidence, timeline, description, effectiveness, etc.
    """
    if not path.exists():
        return {"catalysts": [], "risks": [], "mitigations": []}
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
                    current['confidence'] = float(mc.group(1)) / 100.0
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
    return {"catalysts": catalysts, "risks": risks, "mitigations": mitigations}


# --- Adjustment Engine --------------------------------------------------------

def compute_adjustment(base_price: Optional[float], factors: Dict[str, List[Dict[str, Any]]],
                       scaling: float = 0.25, cap: float = 0.20,
                       mitigation_max_relief: float = 0.35) -> Dict[str, Any]:
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
        return {"base_price": None, "adjusted_price": None, "adjustment_pct": 0.0,
                "detail": {"reason": "No base price available"}}

    def weight_item(item: Dict[str, Any]) -> Tuple[float, float]:
        conf = float(item.get('confidence', 0.0))
        tl = item.get('timeline', '').lower()
        w = TIMELINE_WEIGHTS.get(tl, 0.5)
        return conf * w, w

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
    raw_adj = net_score * scaling
    adj_pct = max(-cap, min(cap, raw_adj))

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
            "cap": cap,
            "scaling": scaling,
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
                             llm_temperature: float = 0.15) -> Dict[str, Any]:
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
    prompt = f"""You are an equity valuation assistant. Based ONLY on the events below, propose parameter deltas to refine a DCF model.\n\nBase Metrics: {base_txt or 'n/a'}\nContext: first_year_growth impacts year 1 revenue; margin_uplift is an additive EBITDA margin shift applied across projection years (keep small, only if efficiency / operating leverage is CLEARLY implied by catalysts or mitigations); capex_rate adjusts capital intensity; wacc reflects perceived risk (only reduce if broad de-risking + mitigations).\nAllowed Parameters (caps applied AFTER your response): {caps_txt}.\nReturn ONLY valid JSON per schema. Do not invent sources. Reference catalysts as C#, risks as R#, mitigations as M#. Provide 1-4 high-confidence deltas max. If insufficient evidence, return {{\"deltas\": []}}.\n\nEvents:\n{events_txt}\n\nJSON Schema Example: {json.dumps(schema)}\nReturn JSON now:"""

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
    p.add_argument('--no-llm', action='store_true')
    p.add_argument('--scaling', type=float, default=0.25, help='Scaling factor applied to net qualitative score')
    p.add_argument('--cap', type=float, default=0.20, help='Absolute cap on adjustment (fraction)')
    p.add_argument('--json', action='store_true', help='Output JSON only')
    p.add_argument('--screen-file', type=str, default=None, help='Explicit screening_report.md path')
    # LLM delta options
    p.add_argument('--llm-deltas', action='store_true', help='Invoke LLM to propose bounded parameter deltas (growth/margin/capex/wacc)')
    p.add_argument('--apply-deltas', action='store_true', help='Apply proposed deltas and recompute model price')
    p.add_argument('--llm-temp', type=float, default=0.15, help='LLM temperature for delta generation')
    p.add_argument('--sens-after-deltas', action='store_true', help='Generate sensitivities after applying deltas')
    p.add_argument('--delta-log', type=str, default=None, help='Optional path to write LLM delta audit log JSON')
    p.add_argument('--export-excel-scenarios', action='store_true', help='Export scenario comparison to Excel')
    p.add_argument('--llm-guardrail-threshold', type=float, default=0.07, help='Max allowed relative divergence between LLM-adjusted and qualitative-adjusted price before flag')
    return p.parse_args()


def main():
    args = _parse_args()
    ticker = args.ticker.upper()
    screen_path = Path(args.screen_file) if args.screen_file else Path('data') / ticker / 'screening_report.md'

    # Step 1: base model
    base_price, model_obj = generate_base_model_price(ticker, args.model, args.strategy,
                                                      args.years, args.term_growth, args.wacc, args.no_llm)

    # Step 2: parse qualitative factors
    factors = parse_screening_report(screen_path)

    # Step 3: compute qualitative adjustment (catalyst vs risk weighting)
    adj = compute_adjustment(base_price, factors, scaling=args.scaling, cap=args.cap)

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

    # Optional Step 4: LLM proposes parameter deltas
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
                if applied_model_price and base_price:
                    output['llm_total_change_pct'] = (applied_model_price / base_price) - 1
                    if output.get('adjusted_price'):
                        rel_vs_qual = (applied_model_price / output['adjusted_price']) - 1
                        output['llm_vs_qualitative_pct'] = rel_vs_qual
                        if abs(rel_vs_qual) > args.llm_guardrail_threshold:
                            output['llm_guardrail_flag'] = True
                            output['llm_guardrail_reason'] = f"LLM adjusted diverges {rel_vs_qual*100:.2f}% vs qualitative (threshold {args.llm_guardrail_threshold*100:.1f}%)"
                output['llm_adjusted_valuation_summary'] = applied_valuation
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
            ws.append(['Ticker','Scenario','Implied Price','Adj % vs Base','Notes'])
            for cell in ws[1]:
                cell.font = Font(bold=True)
            # Base
            ws.append([ticker,'Base', base_price, 0.0, 'Raw DCF output'])
            # Qualitative
            q_adj = output.get('adjusted_price')
            if q_adj:
                ws.append([ticker,'Qualitative', q_adj, (q_adj/base_price)-1, f"Qual adj (net_score={adj['inputs']['net_score']:.3f})"])
            # LLM adjusted
            if output.get('llm_adjusted_price'):
                ws.append([ticker,'LLM Adjusted', output['llm_adjusted_price'], (output['llm_adjusted_price']/base_price)-1, 'Applied LLM deltas'])
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
            ts = time.strftime('%Y%m%d_%H%M%S')
            scen_path = Path('data') / ticker / 'models' / f'scenarios_{ticker}_{ts}.xlsx'
            scen_path.parent.mkdir(parents=True, exist_ok=True)
            wb.save(scen_path)
            output['scenario_excel'] = str(scen_path)
        except Exception as e:  # pragma: no cover
            output['scenario_excel_error'] = str(e)

    if args.json:
        print(json.dumps(output, indent=2))
    else:
        print(f"\n=== Qualitative Price Adjustment ({ticker}) ===")
        if base_price is None:
            print("Base price unavailable; cannot adjust.")
            return 1
        print(f"Base Implied Price: {base_price:,.2f}")
        print(f"Adjusted Price:     {output['adjusted_price']:,.2f} (Adj {output['adjustment_pct']*100:+.1f}%)")
        print(f"Bull Scenario:      {output['bull_price']:,.2f}")
        print(f"Bear Scenario:      {output['bear_price']:,.2f}")
        print(f"Catalysts Parsed:   {output['qualitative_inputs']['catalyst_count']}  | Risks Parsed: {output['qualitative_inputs']['risk_count']}")
        print(f"Vol Buffer (range): {output['vol_buffer']*100:.1f}%")
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
