#!/usr/bin/env python3
"""Solve the equity risk premium implied by market prices under this engine.

Input: the output root of a model-canary run over a fixed sample of S&P 500
companies (``python -m src.valuation_model_canary <tickers> --output-root R``).
For each saved workbook this replays the perpetual-growth DCF exactly as the
workbook computes it (explicit NTM1-5 free cash flow, the NTM6-10 fade, the
Gordon terminal value and the equity bridge), checks the replay against the
workbook's own value, and then finds the uniform change in the mature-market
premium at which the median company is valued at its price.

Prints the CALIBRATION block for ``src/agents/fm/market_premium.py``.

Usage:
  calibrate_market_premium.py RUN_ROOT [--measured-on YYYY-MM-DD]
      [--published-erp 0.0409 --published-as-of 2026-09-01]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import statistics
import sys
from datetime import date
from typing import Any, Dict, List, Optional

_KEY = re.compile(r"\((\d+),\s*(\d+)\)")


def _cells(computed: Dict[str, Any], tab: str) -> Dict[tuple, Any]:
    body = computed.get(tab) or {}
    out = {}
    for key, value in (body.get("cells") or {}).items():
        match = _KEY.match(str(key))
        if match:
            out[(int(match.group(1)), int(match.group(2)))] = value
    return out


def _row(cells: Dict[tuple, Any], label: str) -> Dict[int, Any]:
    for (row, column), value in sorted(cells.items()):
        if column == 1 and str(value).strip().startswith(label):
            return {c: v for (r, c), v in cells.items() if r == row}
    return {}


def _num(value: Any) -> Optional[float]:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def extract(computed: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    projections = _cells(computed, "Projections")
    dcf = _cells(computed, "Valuation (DCF)")
    summary = _cells(computed, "Summary")
    sensitivity = _cells(computed, "Sensitivity")
    inputs = _cells(computed, "Model_Inputs")
    if not dcf:
        return None
    fcf = [_num(_row(projections, "Free Cash Flow").get(c)) for c in range(2, 7)]
    get = lambda label: _num(_row(dcf, label).get(2))
    data = {
        "fcf": fcf, "rf": get("Risk-Free"), "erp": get("Equity Risk"), "beta": get("Levered Beta"),
        "kd": get("Pre-Tax Cost of Debt"), "tax": get("Tax Rate"), "ew": get("Equity Weight"),
        "dw": get("Debt Weight"), "g": get("Terminal Growth Rate"), "cash": get("Add: Cash"),
        "debt": get("Less: Total Debt"), "investments": get("Add: Investments"),
        "shares": get("Shares Outstanding"), "workbook_value": get("Intrinsic Value per Share"),
        "price": _num(_row(summary, "Current Market Price").get(2)),
        "g5": _num(inputs.get((4, 6))),
        "mid_year": _num(sensitivity.get((4, 2))) or 0.0,
    }
    if None in fcf or any(data[k] is None for k in ("rf", "erp", "beta", "g", "shares", "price")):
        return None
    for k in ("kd", "tax", "dw", "cash", "debt", "investments"):
        data[k] = data[k] or 0.0
    data["ew"] = data["ew"] if data["ew"] is not None else 1.0
    return data


def value_per_share(d: Dict[str, Any], erp_shift: float = 0.0) -> Optional[float]:
    ke = d["rf"] + d["beta"] * (d["erp"] + erp_shift)
    wacc = d["ew"] * ke + d["dw"] * d["kd"] * (1 - d["tax"])
    g = d["g"]
    if wacc <= g:
        return None
    fcf = list(d["fcf"])
    positive = fcf[4] > 0
    seed = min(max(d["g5"] if d["g5"] is not None else 0.0, -0.2), 0.2)
    for j in range(1, 6):
        fcf.append(fcf[-1] * (1 + seed + (j / 5.0) * (g - seed)) if positive else 0.0)
    horizon = 10 if positive else 5
    myd = d["mid_year"]
    pv = sum(f / (1 + wacc) ** (t + 1 - myd) for t, f in enumerate(fcf[:horizon]))
    terminal = (fcf[9] if positive else fcf[4]) * (1 + g) / (wacc - g)
    pv += terminal / (1 + wacc) ** (horizon - myd)
    return (pv + d["cash"] - d["debt"] + d["investments"]) / d["shares"]


def calibrate(samples: List[Dict[str, Any]]) -> float:
    def median_at(shift: float) -> float:
        ratios = []
        for d in samples:
            v = value_per_share(d, shift)
            ratios.append(v / d["price"] if v is not None else float("-inf"))
        return statistics.median(ratios)
    low, high = -0.03, 0.03
    for _ in range(80):
        mid = (low + high) / 2
        if median_at(mid) > 1.0:
            low = mid
        else:
            high = mid
    return (low + high) / 2


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("root")
    parser.add_argument("--measured-on", default=date.today().isoformat())
    parser.add_argument("--published-erp", type=float)
    parser.add_argument("--published-as-of")
    args = parser.parse_args(argv)

    samples, skipped, mature = [], [], []
    for path in sorted(glob.glob(os.path.join(args.root, "*", "current", "models", "*_computed_values.json"))):
        ticker = path.split(os.sep)[-4]
        computed = json.load(open(path))
        d = extract(computed)
        if d is None:
            skipped.append((ticker, "not an industrial DCF workbook"))
            continue
        replay = value_per_share(d)
        if replay is None or not d["workbook_value"] or abs(replay / d["workbook_value"] - 1) > 0.001:
            skipped.append((ticker, "replay does not match the workbook"))
            continue
        cost = (computed.get("_vynn") or {}).get("cost_of_capital") or {}
        # The saved CAPM block names the mature-market premium "equity_risk_premium"
        # (the country premium is carried separately).
        if isinstance(cost.get("equity_risk_premium"), (int, float)):
            mature.append(float(cost["equity_risk_premium"]))
        samples.append(d)
    if len(samples) < 30 or not mature:
        print(f"too few usable workbooks ({len(samples)}) to calibrate", file=sys.stderr)
        return 2
    used = statistics.median(mature)
    shift = calibrate(samples)
    before = statistics.median(
        (value_per_share(d) or float("-inf")) / d["price"] for d in samples)
    calibration = {
        "mature_erp": round(used + shift, 4),
        "measured_on": args.measured_on,
        "sample_size": len(samples),
        "median_value_to_price_at_published": round(before, 3),
        "published_reference": (
            {"source": "Damodaran implied ERP (monthly)", "as_of": args.published_as_of,
             "value": args.published_erp}
            if args.published_erp is not None else None
        ),
    }
    print(f"workbooks used: {len(samples)}; skipped: {len(skipped)} {skipped}")
    print(f"mature premium in the run: {used:.4%}; median value/price: {before:.3f}")
    print(f"premium that centres the median: {used + shift:.4%} (shift {shift:+.4%})")
    print("CALIBRATION = " + json.dumps(calibration, indent=4))
    return 0


if __name__ == "__main__":
    sys.exit(main())
