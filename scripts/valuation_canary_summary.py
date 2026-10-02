#!/usr/bin/env python3
"""Summarize one or two valuation-model-canary runs; fail on drift.

The canary (``python -m src.valuation_model_canary``) builds the deterministic
workbook and applies the publication boundary for each symbol with no LLM
call, and prints one JSON row per symbol. This script turns those rows into
the numbers that matter for release:

  * publish rate: how many equities received a point estimate and rating,
    and how many of those are FLAGGED (published with a confidence alert
    because well-covered analysts do not back the model's conclusion);
  * per name: both DCF legs, the comps leg, the Street target, the model's gap
    to market, and the first sentence of any range-only reason or the alert;
  * with a baseline file: the same table side by side, so a candidate engine
    can be compared before it is pinned.

Exit status is non-zero when the candidate publish rate is below
``--min-publish-rate`` or any symbol failed outright, so a nightly cron or a
release gate can block on it.

With ``--expect expectations.json`` every name is also compared with the
outcome it is expected to have (PUBLISHED, FLAGGED, WITHHELD, refused), and
any difference is listed as UNEXPLAINED and fails the run. WITHHELD is this
tool's word for a range-only result (no single value exists); a user never
reads it. PUBLISHED and FLAGGED are different outcomes: a corroborated name
that becomes flagged, or the reverse, is a change someone must explain. That is the
pre-deploy gate: a candidate engine ships with zero unexplained changes, or
the expectation file is updated in the same change with the reason. Prices
move between runs, so a name whose model sits near the 15% publication
boundary can flip legitimately; the nightly run therefore uses the rate
floor alone and the expectation diff is read by a person before a deploy.

Usage:
  valuation_canary_summary.py candidate.json [--baseline baseline.json]
                              [--min-publish-rate 0.30] [--max-refused N]
                              [--expect scripts/valuation_canary_expectations.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


def _rows(path: Path) -> List[Dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    # The canary prints its JSON after any library chatter; take the last
    # top-level array in the file.
    start = text.rfind("\n[")
    payload = text[start + 1:] if start >= 0 else text
    rows = json.loads(payload)
    return rows if isinstance(rows, list) else []


def _num(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _fmt(value: Any, width: int = 9, digits: int = 2, pct: bool = False) -> str:
    number = _num(value)
    if number is None:
        return f"{'-':>{width}}"
    if pct:
        return f"{number * 100:>{width - 1}.0f}%"
    return f"{number:>{width},.{digits}f}"


def _comps(row: Dict[str, Any], width: int = 9) -> str:
    """The comps leg, starred when the artifact reports it as context only."""
    value = _num(row.get("peer_value"))
    if not value:
        # A zero comps cell means no comps leg was produced, not a value of 0.
        return _fmt(None, width) + " "
    context_only = row.get("peer_value_included") is False
    return _fmt(value, width) + ("*" if context_only else " ")


def _growth(row: Dict[str, Any], width: int = 8) -> str:
    """Revenue growth the market price requires (10y), or the bound it passed."""
    bound = row.get("market_required_revenue_growth_bound")
    if bound == "above":
        return f"{'>150%':>{width}}"
    if bound == "below":
        return f"{'<-20%':>{width}}"
    return _fmt(row.get("market_required_revenue_growth_10y"), width, pct=True)


def _alert(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The confidence alert on a published row, if the canary reported one."""
    alert = row.get("confidence_alert")
    if row.get("point_estimate_withheld") or not isinstance(alert, dict):
        return None
    return alert


def _status(row: Dict[str, Any]) -> str:
    if row.get("status") == "failed":
        return "FAILED"
    if row.get("status") == "passed_specialized_refusal":
        return "refused"
    if row.get("point_estimate_withheld"):
        return "WITHHELD"
    return "FLAGGED" if _alert(row) else "PUBLISHED"


def _reason(row: Dict[str, Any], width: int = 88) -> str:
    """Why a row is range-only, or how the Street stands against a flagged one."""
    alert = _alert(row)
    if alert is None:
        return str(row.get("withheld_reason") or "").split(". ")[0][:width]
    parts = [f"alert: {alert.get('relation') or 'unconfirmed'}"]
    gap, count = _num(alert.get("benchmark_gap")), _num(alert.get("analyst_count"))
    if gap is not None:
        parts.append(f"Street target {gap * 100:+.0f}%" + (f" ({count:.0f} analysts)" if count else ""))
    if alert.get("analyst_rating"):
        parts.append(f"rated {alert['analyst_rating']}")
    return ", ".join(parts)[:width]


def _equity_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        row for row in rows
        if row.get("status") not in {"failed", "passed_specialized_refusal"}
    ]


def summarize(rows: List[Dict[str, Any]], label: str) -> Dict[str, Any]:
    equities = _equity_rows(rows)
    published = [row for row in equities if not row.get("point_estimate_withheld")]
    failed = [row for row in rows if row.get("status") == "failed"]
    refused = [row for row in rows if row.get("status") == "passed_specialized_refusal"]
    return {
        "label": label,
        "symbols": len(rows),
        "equities": len(equities),
        "published": len(published),
        "flagged": sum(1 for row in published if _alert(row)),
        "failed": [row.get("ticker") for row in failed],
        "refused": [row.get("ticker") for row in refused],
        "publish_rate": (len(published) / len(equities)) if equities else 0.0,
    }


def _expectations(path: Path) -> Dict[str, Dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {
        str(ticker).upper(): (entry if isinstance(entry, dict) else {"status": entry})
        for ticker, entry in raw.items()
        if not str(ticker).startswith("_")
    }


def unexplained_changes(
    rows: List[Dict[str, Any]], expectations: Dict[str, Dict[str, Any]],
) -> List[str]:
    """Names whose outcome differs from the expectation file.

    A name the file does not list is reported too: an unlisted name has no
    agreed outcome, so its result cannot be called explained. So is a listed
    name missing from the run: a partial run must not pass as the full gate.
    """
    problems = []
    seen = {str(row.get("ticker") or "?").upper() for row in rows}
    for row in rows:
        ticker = str(row.get("ticker") or "?").upper()
        actual = _status(row)
        expected = expectations.get(ticker)
        if expected is None:
            problems.append(f"UNLISTED: {ticker} is {actual} but has no expectation")
            continue
        # A list accepts several outcomes. It exists for a name that must
        # build but sits on a publication boundary market noise can cross
        # (Booking: methods span right at the 1.8x limit).
        status = expected.get("status")
        wanted = [
            str(value or "").upper()
            for value in (status if isinstance(status, list) else [status])
        ]
        if actual.upper() not in wanted:
            want = " or ".join(wanted)
            reason = str(row.get("withheld_reason") or row.get("error") or "").split(". ")[0][:120]
            problems.append(
                f"UNEXPLAINED: {ticker} expected {want} but is {actual}"
                + (f" ({reason})" if reason else "")
            )
    for ticker in expectations:
        if ticker not in seen:
            problems.append(f"MISSING: {ticker} is expected but was not in this run")
    return problems


def warnings(rows: List[Dict[str, Any]]) -> List[str]:
    """Audit warnings, which pass but must be read (a stale artifact, say)."""
    out = []
    for row in rows:
        for check in row.get("checks") or []:
            if str(check).startswith("WARN"):
                out.append(f"WARN {row.get('ticker')}: {str(check)[5:].strip()}")
    return out


def print_table(candidate: List[Dict[str, Any]], baseline: Optional[List[Dict[str, Any]]]) -> None:
    base_by_ticker = {row.get("ticker"): row for row in (baseline or [])}
    header = (
        f"{'ticker':<14}{'status':<10}{'price':>9}{'perpDCF':>10}{'exitDCF':>10}"
        f"{'comps':>9} {'street':>9}{'gap':>7}{'model g':>8}{'price g':>8} {'band':<15} reason"
    )
    print(header)
    print("-" * len(header))
    for row in candidate:
        ticker = str(row.get("ticker") or "?")
        reason = _reason(row)
        print(
            f"{ticker:<14}{_status(row):<10}{_fmt(row.get('current_price'))}"
            f"{_fmt(row.get('dcf_perpetual'), 10)}{_fmt(row.get('dcf_exit'), 10)}"
            f"{_comps(row)}{_fmt(row.get('street_target'))}"
            f"{_fmt(row.get('dcf_gap_vs_market'), 7, pct=True)}"
            f"{_fmt(row.get('model_equivalent_revenue_growth_10y'), 8, pct=True)}"
            f"{_growth(row)} {str(row.get('reliability_band') or '-')[:14]:<15} {reason}"
        )
        base = base_by_ticker.get(ticker)
        if base is not None:
            base_reason = _reason(base)
            print(
                f"{'  baseline':<14}{_status(base):<10}{_fmt(base.get('current_price'))}"
                f"{_fmt(base.get('dcf_perpetual'), 10)}{_fmt(base.get('dcf_exit'), 10)}"
                f"{_comps(base)}{_fmt(base.get('street_target'))}"
                f"{_fmt(base.get('dcf_gap_vs_market'), 7, pct=True)}"
                f"{_fmt(base.get('model_equivalent_revenue_growth_10y'), 8, pct=True)}"
                f"{_growth(base)} {str(base.get('reliability_band') or '-')[:14]:<15} {base_reason}"
            )


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--baseline", type=Path)
    # The nightly basket publishes 10 to 12 of 16: five the Street
    # corroborates (NVDA, GOOGL, MSFT, CRH, TEX), five published with a
    # confidence alert (META, TSLA, AMD, AAPL, PYPL), Amazon with an alert
    # once the provider's statements for it are current, and Booking when it
    # clears its boundary. At 0.55 the floor fails once fewer than 9 of 16
    # judged equities publish: it catches a collapse, not a single flip, which
    # is the --expect check's job before a deploy. (Before 2026-10-02 a name
    # the Street did not back was withheld, 5 of 16 published, and the floor
    # was 0.30.)
    parser.add_argument("--min-publish-rate", type=float, default=0.55)
    parser.add_argument("--expect", type=Path, help="per-name expected outcomes (JSON)")
    # A refused equity leaves the rate's denominator, so a classification
    # regression that refused every name would otherwise raise the rate.
    parser.add_argument("--max-refused", type=int, default=None,
                        help="fail when more symbols than this are refused")
    args = parser.parse_args(argv)

    try:
        candidate = _rows(args.candidate)
    except (OSError, ValueError) as error:
        # The canary container failed before printing its rows (docker
        # could not start, the image is missing, the run was killed).
        print(f"RESULT: FAIL (no readable canary rows in {args.candidate}: {error})")
        return 1
    baseline = _rows(args.baseline) if args.baseline else None
    print_table(candidate, baseline)
    print("* comps reported for context only; not in the blended value")
    print()
    for rows, label in ((baseline, "baseline"), (candidate, "candidate")):
        if rows is None:
            continue
        summary = summarize(rows, label)
        print(
            f"{label:<10} published {summary['published']}/{summary['equities']} equities "
            f"({summary['publish_rate']:.0%})"
            + (f", {summary['flagged']} with a confidence alert" if summary["flagged"] else "")
            + (f"; FAILED: {', '.join(summary['failed'])}" if summary["failed"] else "")
        )
    for line in warnings(candidate):
        print(line)
    result = summarize(candidate, "candidate")
    if result["failed"]:
        print(f"\nRESULT: FAIL ({len(result['failed'])} symbol(s) failed)")
        return 2
    if args.max_refused is not None and len(result["refused"]) > args.max_refused:
        print(f"\nRESULT: FAIL ({len(result['refused'])} symbol(s) refused: "
              f"{', '.join(map(str, result['refused']))}; at most {args.max_refused} allowed)")
        return 1
    if args.expect:
        problems = unexplained_changes(candidate, _expectations(args.expect))
        for problem in problems:
            print(problem)
        if problems:
            print(f"\nRESULT: FAIL ({len(problems)} unexplained outcome(s) against {args.expect})")
            return 3
        print(f"expectations: every name matches {args.expect}")
    if not result["equities"]:
        print("\nRESULT: FAIL (no equity rows to judge)")
        return 1
    if result["publish_rate"] < args.min_publish_rate:
        print(f"\nRESULT: FAIL (publish rate {result['publish_rate']:.0%} below {args.min_publish_rate:.0%})")
        return 1
    print("\nRESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
