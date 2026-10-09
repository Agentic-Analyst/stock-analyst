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

from src.currency import currency_symbol


def _num(v) -> Optional[float]:
    try:
        if v is None or isinstance(v, bool):
            return None
        f = float(v)
        return f if f == f else None      # drop NaN
    except (TypeError, ValueError):
        return None


def _symbol(ccy: Optional[str]) -> str:
    """
    The listing's own currency symbol, or nothing when the currency is unknown.

    This used to default to "$". Every tool that can know its currency now
    publishes it, so the default only ever fired when the currency was
    genuinely unknown, and a dollar sign there is not a default but a claim:
    a yen or rupee fair value streamed to the user as US dollars. A bare
    number says exactly what is known. lib/research/parse.ts on the web side
    applies the same rule to the same figures.
    """
    if not ccy:
        return ""
    return currency_symbol(ccy)


def _money(v, ccy: Optional[str] = None) -> Optional[str]:
    """
    Format a monetary finding in the currency it was actually measured in.

    The symbol used to be a hardcoded "$". A verified LVMH run produced a
    correct EUR report and then published the finding chip "$388.27" beside it —
    the same mislabelling that was fixed inside reports, still live on the chat
    surface the user watches while waiting.
    """
    n = _num(v)
    if n is None:
        return None
    sym = _symbol(ccy)
    if abs(n) >= 1_000_000_000_000:
        return f"{sym}{n/1_000_000_000_000:.2f}T"
    if abs(n) >= 1_000_000_000:
        return f"{sym}{n/1_000_000_000:.1f}B"
    if abs(n) >= 1_000_000:
        return f"{sym}{n/1_000_000:.1f}M"
    return f"{sym}{n:,.2f}"


def _pct(v, already_pct: bool = False) -> Optional[str]:
    n = _num(v)
    if n is None:
        return None
    if not already_pct:
        n *= 100
    return f"{n:+.1f}%"


def _ratio_pct(v) -> Optional[str]:
    """Unsigned two-decimal percent for small ratios such as fund fees."""
    n = _num(v)
    return f"{n * 100:.2f}%" if n is not None else None


def extract_findings(tool: str, result: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    Map one tool result to displayable findings.

    Returns a list of {kind, label, value, sub?} dicts — `kind` lets the UI
    pick an icon/tone, `label` is the caption, `value` is the headline fact.
    Empty list when the tool produced nothing worth interrupting for.
    """
    # "not_applicable" is a tool declining the job (build_model and
    # write_report on a company the method does not value): nothing was
    # produced. It used to fall through to "Report ready: Generated" while
    # the reports folder stayed empty.
    if not isinstance(result, dict) or result.get("status") in ("error", "not_applicable"):
        return []

    out: List[Dict[str, str]] = []
    # The listing's currency, when the tool reported one. Absent it, the
    # figure prints bare: an unknown unit is never rendered as dollars.
    ccy = result.get("currency")

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
        px = _money(result.get("latest_price"), ccy)
        chg = _pct(result.get("day_change_pct"), already_pct=True)
        if px:
            add("price", result.get("ticker") or "Price", px, chg)

    elif tool == "get_crypto":
        # GetCryptoTool returns "price_usd" (crypto_tools.py), not "price". This
        # read the wrong key, so _money() got None and the chip never rendered:
        # every crypto run silently lost its price finding. "price" is kept as a
        # fallback in case the tool's shape changes back.
        px = _money(result.get("price_usd") if result.get("price_usd") is not None
                    else result.get("price"), ccy)
        chg = _pct(result.get("change_24h_pct"), already_pct=True)
        if px:
            add("price", result.get("symbol") or result.get("asset") or "Price", px, chg)

    elif tool == "get_fund":
        operations = result.get("operations")
        expense = operations.get("expense_ratio") if isinstance(operations, dict) else None
        if isinstance(expense, dict):
            category_fee = _ratio_pct(expense.get("category"))
            add("metric", "Expense ratio", _ratio_pct(expense.get("fund")),
                f"category {category_fee}" if category_fee else None)
        performance = result.get("performance")
        returns = performance.get("returns") if isinstance(performance, dict) else None
        if isinstance(returns, dict):
            add("metric", "1-year return", _pct(returns.get("one_year")),
                "adjusted close")

    elif tool == "get_financials":
        # A company valued on its home listing but asked about by its US line
        # (listing_view): the card shows the line the user asked about.
        us = result.get("listing_view") if isinstance(result.get("listing_view"), dict) else {}
        if us.get("market_cap"):
            add("company", result.get("company_name") or "Company",
                _money(us.get("market_cap"), "USD"), f"market cap · {us.get('ticker')}")
        else:
            add("company", result.get("company_name") or "Company",
                _money(result.get("market_cap"), ccy), "market cap")
        pe = _num(result.get("trailing_pe"))
        if pe:
            add("metric", "Trailing P/E", f"{pe:.1f}x")

    elif tool == "build_model":
        us = result.get("listing_view") if isinstance(result.get("listing_view"), dict) else {}
        # A fair value the Street does not back is shown with its confidence.
        flag = " · low confidence" if result.get("confidence_alert") else ""
        if us.get("fair_value"):
            up = _pct(us.get("upside"))
            add("valuation", "Fair value", _money(us.get("fair_value"), "USD"),
                f"per {us.get('ticker')} share" + (f" · {up} vs market" if up else "") + flag)
        else:
            fv = _money(result.get("fair_value"), ccy)
            up = _pct(result.get("upside_vs_market"))
            method = result.get("valuation_method")
            add("valuation", "Fair value", fv,
                (f"{up} vs market" + flag) if up else (method or None))

    elif tool == "analyze_news":
        n = _num(result.get("articles_analyzed"))
        if n:
            add("news", "Articles screened", f"{int(n)}")
        # AnalyzeNewsTool returns "top_catalysts"/"top_risks" (analysis_tools.py:652).
        # These read the un-prefixed names, so the branch never fired and the
        # "Signals found" chip never appeared on any run.
        cats = result.get("top_catalysts")
        if cats is None:
            cats = result.get("catalysts")
        risks = result.get("top_risks")
        if risks is None:
            risks = result.get("risks")
        if isinstance(cats, list) and isinstance(risks, list) and (cats or risks):
            nc, nr = len(cats), len(risks)
            add("news", "Signals found",
                f"{nc} catalyst{'' if nc == 1 else 's'} · {nr} risk{'' if nr == 1 else 's'}")

    elif tool == "get_technicals":
        rsi = _num(result.get("rsi_14"))
        if rsi is not None:   # an RSI of 0 is a reading, not a missing value
            add("technical", "RSI (14)", f"{rsi:.0f}")

    elif tool == "get_global_news":
        heads = result.get("headlines")
        if isinstance(heads, list) and heads:
            top = heads[0]
            title = top.get("title") if isinstance(top, dict) else None
            add("news", "Latest headline", (title or "")[:90] or None)

    elif tool == "explain_price_move":
        episode = result.get("episode") if isinstance(result.get("episode"), dict) else {}
        move = _num(episode.get("change_pct"))
        if move is not None and episode.get("start_date") and episode.get("end_date"):
            # Half-up, as the answer's prose rounds it: -21.65 is "-21.7%".
            from decimal import ROUND_HALF_UP, Decimal
            shown = Decimal(str(move)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
            add("metric", "The move", f"{shown:+}%",
                f"{_short_date(episode['start_date'])} → {_short_date(episode['end_date'])}")
        headline = _key_headline(result.get("news"))
        if headline:
            add("news", "Key headline", headline[:90])

    elif tool == "write_report":
        us = result.get("listing_view") if isinstance(result.get("listing_view"), dict) else {}
        fv = (_money(us.get("fair_value"), "USD") if us.get("fair_value")
              else _money(result.get("fair_value"), ccy))
        add("report", "Report ready", fv, "full analyst report generated")
        if not fv:
            out.clear()
            add("report", "Report ready", "Generated", "full analyst report")

    elif tool == "compare_tickers":
        n = result.get("tickers")
        if isinstance(n, list) and n:
            add("compare", "Peers compared", ", ".join(str(x) for x in n[:5]))

    return out[:2]   # never flood the panel from a single tool


def _short_date(day: str) -> str:
    """2026-09-30 -> Sep 30."""
    try:
        from datetime import date
        d = date.fromisoformat(str(day)[:10])
        return f"{d:%b} {d.day}"
    except ValueError:
        return str(day)


def _key_headline(news) -> Optional[str]:
    """The top article on the first big-move session, else the first article."""
    sessions = (news or {}).get("by_session") if isinstance(news, dict) else None
    if not isinstance(sessions, list):
        return None
    ordered = [s for s in sessions if s.get("big_move_day")] + sessions
    for session in ordered:
        for article in session.get("articles") or []:
            if article.get("title"):
                return article["title"]
    return None
