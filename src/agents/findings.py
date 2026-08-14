"""
findings.py — turn a tool's JSON result into the one or two FACTS worth
showing the user while they wait.

A chat run takes 45-120 seconds (minutes for a full report). The pipeline
already knows real things long before the answer is written — the ticker it
resolved, the live quote, how many articles it screened, the fair value the
model produced — but until now those numbers lived only in the LLM's context
and the user stared at a spinner.

Each finding is emitted as a `[FINDING] {json}` marker line on the same
channel as `[CHART_DIRECTIVE]`: api-runner lifts it out of the log stream and
forwards it as a `finding` SSE event, and the chat renders it as a card the
moment it lands.

HARD RULE: findings are RETRIEVED FACTS, never conclusions. "Fair value
$184.44" is a fact about the model's output; "BUY" is a verdict, and a
partial verdict the final answer might contradict is worse than showing
nothing. Ratings, recommendations and sentiment verdicts are deliberately
excluded here.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def _num(v) -> Optional[float]:
    try:
        if v is None or isinstance(v, bool):
            return None
        f = float(v)
        return f if f == f else None      # drop NaN
    except (TypeError, ValueError):
        return None


def _money(v) -> Optional[str]:
    n = _num(v)
    if n is None:
        return None
    if abs(n) >= 1_000_000_000_000:
        return f"${n/1_000_000_000_000:.2f}T"
    if abs(n) >= 1_000_000_000:
        return f"${n/1_000_000_000:.1f}B"
    if abs(n) >= 1_000_000:
        return f"${n/1_000_000:.1f}M"
    return f"${n:,.2f}"


def _pct(v, already_pct: bool = False) -> Optional[str]:
    n = _num(v)
    if n is None:
        return None
    if not already_pct:
        n *= 100
    return f"{n:+.1f}%"


def extract_findings(tool: str, result: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    Map one tool result to displayable findings.

    Returns a list of {kind, label, value, sub?} dicts — `kind` lets the UI
    pick an icon/tone, `label` is the caption, `value` is the headline fact.
    Empty list when the tool produced nothing worth interrupting for.
    """
    if not isinstance(result, dict) or result.get("status") == "error":
        return []

    out: List[Dict[str, str]] = []

    def add(kind: str, label: str, value: Optional[str], sub: Optional[str] = None):
        if value:
            item = {"kind": kind, "label": label, "value": str(value)}
            if sub:
                item["sub"] = str(sub)
            out.append(item)

    if tool == "resolve_symbol":
        sym = result.get("best_guess") or result.get("ticker")
        name = result.get("company_name") or result.get("name")
        add("identity", "Resolved", sym, name)

    elif tool == "get_prices":
        px = _money(result.get("latest_price"))
        chg = _pct(result.get("day_change_pct"), already_pct=True)
        if px:
            add("price", result.get("ticker") or "Price", px, chg)

    elif tool == "get_crypto":
        px = _money(result.get("price"))
        chg = _pct(result.get("change_24h_pct"), already_pct=True)
        if px:
            add("price", result.get("symbol") or result.get("asset") or "Price", px, chg)

    elif tool == "get_financials":
        add("company", result.get("company_name") or "Company",
            _money(result.get("market_cap")), "market cap")
        pe = _num(result.get("trailing_pe"))
        if pe:
            add("metric", "Trailing P/E", f"{pe:.1f}x")

    elif tool == "build_model":
        fv = _money(result.get("fair_value"))
        up = _pct(result.get("upside_vs_market"))
        method = result.get("valuation_method")
        add("valuation", "Fair value", fv,
            f"{up} vs market" if up else (method or None))

    elif tool == "analyze_news":
        n = _num(result.get("articles_analyzed"))
        if n:
            add("news", "Articles screened", f"{int(n)}")
        cats = result.get("catalysts")
        risks = result.get("risks")
        if isinstance(cats, list) and isinstance(risks, list) and (cats or risks):
            add("news", "Signals found", f"{len(cats)} catalysts · {len(risks)} risks")

    elif tool == "get_technicals":
        rsi = _num(result.get("rsi_14"))
        if rsi:
            add("technical", "RSI (14)", f"{rsi:.0f}")

    elif tool == "get_global_news":
        heads = result.get("headlines")
        if isinstance(heads, list) and heads:
            top = heads[0]
            title = top.get("title") if isinstance(top, dict) else None
            add("news", "Latest headline", (title or "")[:90] or None)

    elif tool == "write_report":
        fv = _money(result.get("fair_value"))
        add("report", "Report ready", fv, "full analyst report generated")
        if not fv:
            out.clear()
            add("report", "Report ready", "Generated", "full analyst report")

    elif tool == "compare_tickers":
        n = result.get("tickers")
        if isinstance(n, list) and n:
            add("compare", "Peers compared", ", ".join(str(x) for x in n[:5]))

    return out[:2]   # never flood the panel from a single tool
