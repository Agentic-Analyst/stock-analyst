#!/usr/bin/env python3
"""Summarize one or two valuation-model-canary runs; fail on drift.

The canary (``python -m src.valuation_model_canary``) builds the deterministic
workbook and applies the publication boundary for each symbol with no LLM
call, and prints one JSON row per symbol. This script turns those rows into
the numbers that matter for release:

  * publish rate: how many equities received a point estimate and rating;
  * per name: both DCF legs, the comps leg, the Street target, the model's gap
    to market, and the first sentence of any withhold reason;
  * with a baseline file: the same table side by side, so a candidate engine
    can be compared before it is pinned.

Exit status is non-zero when the candidate publish rate is below
``--min-publish-rate`` or any symbol failed outright, so a nightly cron or a
release gate can block on it.

With ``--expect expectations.json`` every name is also compared with the
outcome it is expected to have (PUBLISHED, WITHHELD, refused), and any
difference is listed as UNEXPLAINED and fails the run. That is the
pre-deploy gate: a candidate engine ships with zero unexplained changes, or
the expectation file is updated in the same change with the reason. Prices
move between runs, so a name whose model sits near the 15% publication
boundary can flip legitimately; the nightly run therefore uses the rate
floor alone and the expectation diff is read by a person before a deploy.

Usage:
  valuation_canary_summary.py candidate.json [--baseline baseline.json]
                              [--min-publish-rate 0.30]
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


def _status(row: Dict[str, Any]) -> str:
    if row.get("status") == "failed":
        return "FAILED"
    if row.get("status") == "passed_specialized_refusal":
        return "refused"
    return "WITHHELD" if row.get("point_estimate_withheld") else "PUBLISHED"


def _equity_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        row for row in rows
        if row.get("status") not in {"failed", "passed_specialized_refusal"}
    ]


def summarize(rows: List[Dict[str, Any]], label: str) -> Dict[str, Any]:
    equities = _equity_rows(rows)
    published = [row for row in equities if not row.get("point_estimate_withheld")]
    failed = [row for row in rows if row.get("status") == "failed"]
    return {
        "label": label,
        "symbols": len(rows),
        "equities": len(equities),
        "published": len(published),
        "failed": [row.get("ticker") for row in failed],
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
    agreed outcome, so its result cannot be called explained.
    """
    problems = []
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
    return problems


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
        reason = str(row.get("withheld_reason") or "").split(". ")[0][:88]
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
            base_reason = str(base.get("withheld_reason") or "").split(". ")[0][:88]
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
    # 5 of the 16 basket names publish today (NVDA, GOOGL, MSFT, CRH, TEX);
    # the floor fails the gate if any one of them stops publishing.
    parser.add_argument("--min-publish-rate", type=float, default=0.30)
    parser.add_argument("--expect", type=Path, help="per-name expected outcomes (JSON)")
    args = parser.parse_args(argv)

    candidate = _rows(args.candidate)
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
            + (f"; FAILED: {', '.join(summary['failed'])}" if summary["failed"] else "")
        )
    result = summarize(candidate, "candidate")
    if result["failed"]:
        print(f"\nRESULT: FAIL ({len(result['failed'])} symbol(s) failed)")
        return 2
    if args.expect:
        problems = unexplained_changes(candidate, _expectations(args.expect))
        for problem in problems:
            print(problem)
        if problems:
            print(f"\nRESULT: FAIL ({len(problems)} unexplained outcome(s) against {args.expect})")
            return 3
        print(f"expectations: every name matches {args.expect}")
    if result["equities"] and result["publish_rate"] < args.min_publish_rate:
        print(f"\nRESULT: FAIL (publish rate {result['publish_rate']:.0%} below {args.min_publish_rate:.0%})")
        return 1
    print("\nRESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
