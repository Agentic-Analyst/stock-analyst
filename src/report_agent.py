#!/usr/bin/env python3
"""report_agent.py

LLM-assisted reporting utilities for price_adjustor.
Generates a professional markdown report that explains the step-by-step
price adjustment and provides analyst suggestions.
"""
from __future__ import annotations
from datetime import datetime
from pathlib import Path
import pathlib
from typing import Dict, Any, List
import json, time

from price_adjustor_config import ADJUSTOR_PROMPTS, ADJUSTOR_DEFAULTS

try:
    from llms import gpt_4o_mini as _llm_fn
except Exception:  # pragma: no cover
    _llm_fn = None


def _fmt_pct(x: float | None) -> str:
    try:
        return f"{x*100:+.1f}%" if x is not None else "n/a"
    except Exception:
        return "n/a"


def _list_lines(items: List[str]) -> str:
    return "\n".join(items) if items else "  - (none)"


def build_llm_explanation(ticker: str, output: Dict[str, Any], factors: Dict[str, Any], args) -> str | None:
    """Build LLM narrative using the explanation_report prompt.
    Returns markdown or None if LLM unavailable.
    """
    if _llm_fn is None:
        return None
    try:
        prompt_tmpl = Path(ADJUSTOR_PROMPTS.EXPLANATION_REPORT).read_text(encoding='utf-8')
        # Prepare inputs
        top_cats = []
        for i, c in enumerate(factors.get('catalysts', [])[:5], 1):
            conf = c.get('confidence'); tl = c.get('timeline')
            title = c.get('title') or c.get('description') or c.get('type') or 'untitled'
            top_cats.append(f"  - C{i}: {title} | conf={int((conf or 0)*100)}% | {tl}")
        top_risks = []
        for i, r in enumerate(factors.get('risks', [])[:5], 1):
            conf = r.get('confidence'); tl = r.get('timeline')
            title = r.get('title') or r.get('description') or r.get('type') or 'untitled'
            top_risks.append(f"  - R{i}: {title} | conf={int((conf or 0)*100)}% | {tl}")
        top_mits = []
        for i, m in enumerate(factors.get('mitigations', [])[:3], 1):
            title = m.get('title') or m.get('strategy') or m.get('risk_addressed') or 'untitled'
            top_mits.append(f"  - M{i}: {title} | eff={m.get('effectiveness','n/a')} | addr={m.get('risk_addressed','n/a')}")
        eff = (output.get('mapped_parameter_deltas') or {}).get('effective') or {}
        prompt = prompt_tmpl.format(
            ticker=ticker,
            model=args.model,
            years=args.years,
            term_growth=f"{args.term_growth:.3f}",
            wacc_override=(f"{args.wacc:.3f}" if args.wacc is not None else "n/a"),
            base_price=f"{(output.get('base_model_price') or 0):,.2f}",
            net_score=f"{(output.get('qualitative_inputs') or {}).get('net_score', 0):.3f}",
            raw_adjustment=f"{(output.get('qualitative_inputs') or {}).get('raw_adjustment', 0):.3f}",
            cap=f"{(output.get('qualitative_inputs') or {}).get('cap', 0):.3f}",
            scaling=f"{(output.get('qualitative_inputs') or {}).get('scaling', 0):.3f}",
            adjustment_pct=_fmt_pct(output.get('adjustment_pct')),
            qual_adjusted_price=f"{(output.get('adjusted_price') or 0):,.2f}",
            growth_pp=f"{eff.get('growth_delta_dec',0)*100:+.2f}",
            margin_pp=f"{eff.get('margin_uplift_dec',0)*100:+.2f}",
            capex_pp=f"{eff.get('capex_rate_delta_dec',0)*100:+.2f}",
            wacc_pp=f"{eff.get('wacc_delta_dec',0)*100:+.2f}",
            mapped_price=f"{(output.get('mapped_adjusted_price') or 0):,.2f}",
            mapped_total_pct=_fmt_pct((output.get('mapped_parameter_deltas') or {}).get('mapped_total_change_pct')),
            residual_overlay_pct=_fmt_pct(output.get('residual_overlay_pct') or output.get('residual_overlay_pct_llm')),
            final_price=f"{(output.get('final_price') or output.get('primary_adjusted_price') or 0):,.2f}",
            bull_price=f"{(output.get('bull_price') or 0):,.2f}",
            bear_price=f"{(output.get('bear_price') or 0):,.2f}",
            pw_price=f"{(output.get('probability_weighted_price') or 0):,.2f}",
            governance_flags=json.dumps(output.get('governance_flags') or []),
            top_catalysts=_list_lines(top_cats),
            top_risks=_list_lines(top_risks),
            top_mitigations=_list_lines(top_mits),
        )
        raw = _llm_fn([
            {"role": "system", "content": "You are a concise, rigorous sell-side analyst."},
            {"role": "user", "content": prompt}
        ], temperature=ADJUSTOR_DEFAULTS.DEFAULT_LLM_TEMPERATURE)
        if isinstance(raw, tuple):
            raw = raw[0]
        return str(raw).strip()
    except Exception:  # pragma: no cover
        return None


def save_explanation_reports(ticker: str, deterministic_md: str, llm_md: str, base_path: pathlib.Path) -> Dict[str, str]:
    """Save explanation reports with timestamped and latest versions."""
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    rdir = base_path / 'reports'
    rdir.mkdir(parents=True, exist_ok=True)
    final_report = deterministic_md + ("\n\n---\n\n" + llm_md if llm_md else "")
    report_path = rdir / f"price_adjustment_explanation_{ticker}_{timestamp}.md"
    report_latest = rdir / "price_adjustment_explanation_latest.md"
    report_path.write_text(final_report, encoding='utf-8')
    report_latest.write_text(final_report, encoding='utf-8')
    return {"path": str(report_path), "latest": str(report_latest)}


def build_deterministic_summary(ticker: str, output: Dict[str, Any], factors: Dict[str, Any], meta: Dict[str, Any] | None = None) -> str:
    """Build a concise deterministic markdown summary using computed outputs.
    meta may include keys like model, years, term_growth; all optional.
    """
    def _p(v):
        try:
            return f"{v*100:+.1f}%" if v is not None else "n/a"
        except Exception:
            return "n/a"
    def _top(items, n=5):
        out=[]
        for it in items[:n]:
            # Try multiple field names for title/description
            t = it.get('title') or it.get('description') or it.get('type') or '(untitled)'
            conf=it.get('confidence'); tl=it.get('timeline')
            try:
                conf_txt=f"{float(conf)*100:.0f}%" if conf is not None else "n/a"
            except Exception:
                conf_txt="n/a"
            out.append(f"- {t} (Confidence {conf_txt}, {tl})")
        return out
    ts_human = time.strftime('%Y-%m-%d %H:%M:%S')
    base_price = output.get('base_model_price')
    mapped_price = output.get('mapped_model_price') or output.get('mapped_adjusted_price')
    qual_adj_price = output.get('adjusted_price')
    final_price = output.get('final_price') or output.get('primary_adjusted_price') or output.get('adjusted_price')
    bull = output.get('bull_price'); bear = output.get('bear_price'); volb = output.get('vol_buffer')
    mapped_total_pct = None
    mr = output.get('mapped_result') or output.get('mapped_parameter_deltas')
    if isinstance(mr, dict):
        mapped_total_pct = mr.get('mapped_total_change_pct')
    qual_pct = output.get('adjustment_pct')
    residual_pct = output.get('residual_overlay_pct') or output.get('residual_overlay_pct_llm')
    llm_total_pct = output.get('llm_total_change_pct')
    lines=[f"# Qualitative Price Adjustment Summary — {ticker}", "", f"Generated on: {ts_human}", f"Method: {output.get('method','qual_overlay')}", "", "## Executive Snapshot"]
    if meta and meta.get('model'):
        years = meta.get('years', 'n/a'); tg = meta.get('term_growth', 'n/a')
        if isinstance(tg, (int,float)): tg = f"{tg:.3f}"
        lines.append(f"- Base implied price: {base_price:,.2f} (from {meta['model']} model, years={years}, g={tg})")
    else:
        lines.append(f"- Base implied price: {base_price:,.2f}")
    if mapped_price is not None:
        ch = mapped_total_pct if mapped_total_pct is not None else ((mapped_price / base_price) - 1 if base_price else None)
        lines.append(f"- Mapped-parameter price: {mapped_price:,.2f} ({_p(ch)} vs base)")
    if qual_adj_price is not None:
        lines.append(f"- Qualitative overlay price: {qual_adj_price:,.2f} ({_p(qual_pct)} vs base)")
    if output.get('llm_adjusted_price') is not None:
        lines.append(f"- LLM-adjusted price: {output['llm_adjusted_price']:,.2f} ({_p(llm_total_pct)} vs base)")
    if residual_pct is not None and final_price is not None and mapped_price is not None:
        lines.append(f"- Residual overlay applied: {_p(residual_pct)}")
    if final_price is not None:
        lines.append(f"- Final adjusted price: {final_price:,.2f}")
    if bull is not None and bear is not None and volb is not None:
        lines.append(f"- Range: Bear {bear:,.2f} / Bull {bull:,.2f} (volatility buffer ~{volb*100:.1f}%)")
    lines.append("")
    lines.append("## Key Catalysts"); lines.extend(_top(factors.get('catalysts',[]),5) or ["- (none)"])
    lines.append("")
    lines.append("## Key Risks"); lines.extend(_top(factors.get('risks',[]),5) or ["- (none)"])
    return "\n".join(lines)
