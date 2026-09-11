"""Aggregate, reproducible calibration checks for completed valuation runs.

This module does not decide that a healthy model must be bullish. It measures
signed bias, methodology coverage, analyst disagreement, and whether a cohort
is sufficiently versioned and complete to support a calibration claim.

The Mongo loader projects out user and artifact metadata. Pure functions accept
ordinary dictionaries so the benchmark is unit tested without a database and
can also run against a deliberately exported JSON fixture.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

LEGACY_VERSION = "unversioned"
EQUITY_QUOTE_TYPES = frozenset({"EQUITY"})
NON_EQUITY_QUOTE_TYPES = frozenset({
    "ETF", "MUTUALFUND", "MUTUAL FUND", "CRYPTO", "CRYPTOCURRENCY", "INDEX",
})


def _number(value: Any, *, positive: bool = False) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or (positive and number <= 0):
        return None
    return number


def _timestamp(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _document_time(doc: Dict[str, Any]) -> Optional[datetime]:
    for field in ("completed_at", "job_created_at", "recorded_at"):
        parsed = _timestamp(doc.get(field))
        if parsed is not None:
            return parsed
    return None


def _model_version(doc: Dict[str, Any]) -> str:
    value = doc.get("model_version")
    return value.strip() if isinstance(value, str) and value.strip() else LEGACY_VERSION


def _version_number(doc: Dict[str, Any]) -> int:
    try:
        return max(0, int(doc.get("version") or 0))
    except (TypeError, ValueError):
        return 0


def latest_by_ticker(documents: Iterable[Dict[str, Any]], *,
                     model_version: Optional[str] = None) -> List[Dict[str, Any]]:
    """Newest completed record per ticker, optionally within one model release."""
    wanted = model_version.strip() if isinstance(model_version, str) and model_version.strip() else None
    latest: Dict[str, Dict[str, Any]] = {}
    for raw in documents or ():
        if not isinstance(raw, dict):
            continue
        ticker = raw.get("ticker")
        ticker = ticker.strip().upper() if isinstance(ticker, str) else ""
        if not ticker or (wanted and _model_version(raw) != wanted):
            continue
        doc = {**raw, "ticker": ticker}
        previous = latest.get(ticker)
        current_key = (_document_time(doc) or datetime.min.replace(tzinfo=timezone.utc),
                       _version_number(doc))
        previous_key = (
            _document_time(previous) or datetime.min.replace(tzinfo=timezone.utc),
            _version_number(previous),
        ) if previous else None
        if previous_key is None or current_key > previous_key:
            latest[ticker] = doc
    return sorted(latest.values(), key=lambda doc: doc["ticker"])


def methodology_values(doc: Dict[str, Any]) -> Dict[str, Optional[float]]:
    """Recorded, old flat-leg, and current equal-method fair values."""
    valuation = doc.get("valuation") if isinstance(doc.get("valuation"), dict) else {}
    perpetual = _number(valuation.get("perpetual"), positive=True)
    exit_multiple = _number(valuation.get("exit_multiple"), positive=True)
    comps = _number(valuation.get("comps"), positive=True)
    dcf_legs = [value for value in (perpetual, exit_multiple) if value is not None]
    dcf_view = statistics.fmean(dcf_legs) if dcf_legs else None
    method_equal = (
        statistics.fmean((dcf_view, comps))
        if dcf_view is not None and comps is not None
        else dcf_view if dcf_view is not None else comps
    )
    flat_legs = [value for value in (perpetual, exit_multiple, comps) if value is not None]
    return {
        "recorded": _number(valuation.get("fair_value"), positive=True),
        "dcf_view": dcf_view,
        "comps": comps,
        "flat_three_leg": statistics.fmean(flat_legs) if flat_legs else None,
        "method_equal": method_equal,
    }


def formula_signature(doc: Dict[str, Any]) -> str:
    values = methodology_values(doc)
    recorded = values["recorded"]
    if recorded is None:
        return "unavailable"
    tolerance = max(0.05, abs(recorded) * 0.001)
    if values["method_equal"] is not None and abs(recorded - values["method_equal"]) <= tolerance:
        return "method_equal"
    if values["flat_three_leg"] is not None and abs(recorded - values["flat_three_leg"]) <= tolerance:
        return "flat_three_leg"
    return "other"


def _distribution(values: Sequence[float]) -> Dict[str, Any]:
    clean = [float(value) for value in values if math.isfinite(float(value))]
    if not clean:
        return {"n": 0, "mean": None, "median": None, "below_zero_share": None,
                "p10": None, "p90": None}
    ordered = sorted(clean)

    def percentile(fraction: float) -> float:
        if len(ordered) == 1:
            return ordered[0]
        position = fraction * (len(ordered) - 1)
        low, high = math.floor(position), math.ceil(position)
        if low == high:
            return ordered[low]
        return ordered[low] + (ordered[high] - ordered[low]) * (position - low)

    return {
        "n": len(clean),
        "mean": round(statistics.fmean(clean), 6),
        "median": round(statistics.median(clean), 6),
        "below_zero_share": round(sum(value < 0 for value in clean) / len(clean), 6),
        "p10": round(percentile(0.10), 6),
        "p90": round(percentile(0.90), 6),
    }


def _correlation(pairs: Sequence[Tuple[float, float]]) -> Optional[float]:
    if len(pairs) < 2:
        return None
    try:
        return round(statistics.correlation(
            [pair[0] for pair in pairs], [pair[1] for pair in pairs]), 6)
    except statistics.StatisticsError:
        return None


def _domain(quote_type: Any) -> str:
    value = str(quote_type or "").strip().upper()
    if value in EQUITY_QUOTE_TYPES:
        return "equity"
    if value in NON_EQUITY_QUOTE_TYPES:
        return "non_equity"
    return "unclassified"


def benchmark(documents: Sequence[Dict[str, Any]], universe_documents: Sequence[Dict[str, Any]] = (), *,
              model_version: Optional[str] = None, minimum_analysts: int = 5,
              now: Optional[datetime] = None) -> Dict[str, Any]:
    """Aggregate one latest-per-ticker valuation cohort without user metadata."""
    cohort = latest_by_ticker(documents, model_version=model_version)
    universe = {
        str(doc.get("symbol") or "").strip().upper(): doc
        for doc in universe_documents or () if isinstance(doc, dict) and doc.get("symbol")
    }
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    recorded_gaps: List[float] = []
    replay_gaps: List[float] = []
    current_model_gaps: List[float] = []
    analyst_gaps: List[float] = []
    model_vs_analyst: List[float] = []
    analyst_pairs: List[Tuple[float, float]] = []
    ratings: Counter[str] = Counter()
    signatures: Counter[str] = Counter()
    versions: Counter[str] = Counter()
    equity_versions: Counter[str] = Counter()
    domains: Counter[str] = Counter()
    completed: List[datetime] = []
    age_eligible_12m = 0
    with_comps = 0
    with_two_dcf = 0
    with_derived_capm = 0

    for doc in cohort:
        ticker = doc["ticker"]
        market = universe.get(ticker, {})
        domain = _domain(market.get("quote_type"))
        domains[domain] += 1
        versions[_model_version(doc)] += 1
        signatures[formula_signature(doc)] += 1
        if domain == "equity":
            equity_versions[_model_version(doc)] += 1
            rating = ((doc.get("verdict") or {}).get("rating")
                      if isinstance(doc.get("verdict"), dict) else None)
            ratings[str(rating or "MISSING").strip().upper()] += 1

        completed_at = _document_time(doc)
        if completed_at and domain == "equity":
            completed.append(completed_at)
            if (now - completed_at).total_seconds() >= 365.25 * 86400:
                age_eligible_12m += 1
        if domain == "equity" and doc.get("capm_derived") is True:
            with_derived_capm += 1

        values = methodology_values(doc)
        if domain == "equity" and values["comps"] is not None:
            with_comps += 1
        valuation = doc.get("valuation") if isinstance(doc.get("valuation"), dict) else {}
        if domain == "equity" and all(_number(valuation.get(field), positive=True) is not None
               for field in ("perpetual", "exit_multiple")):
            with_two_dcf += 1

        run_price = _number(valuation.get("current_price"), positive=True)
        if domain == "equity" and run_price and values["recorded"]:
            recorded_gaps.append(values["recorded"] / run_price - 1)
        if domain == "equity" and run_price and values["method_equal"]:
            replay_gaps.append(values["method_equal"] / run_price - 1)

        # Current cross-checks require a provider-confirmed equity and put the
        # model and analyst target over the SAME cached market-price denominator.
        current_price = _number(market.get("price_at_refresh"), positive=True)
        analyst_target = _number(market.get("analyst_target_mean"), positive=True)
        analyst_count = int(_number(market.get("analyst_count")) or 0)
        if domain != "equity" or current_price is None or values["method_equal"] is None:
            continue
        model_gap = values["method_equal"] / current_price - 1
        current_model_gaps.append(model_gap)
        if analyst_target is not None and analyst_count >= max(1, int(minimum_analysts)):
            analyst_gap = analyst_target / current_price - 1
            analyst_gaps.append(analyst_gap)
            model_vs_analyst.append(model_gap - analyst_gap)
            analyst_pairs.append((model_gap, analyst_gap))

    count = len(cohort)
    analyst_count = len(analyst_pairs)
    equity_count = domains["equity"]
    versioned_equities = equity_count - equity_versions.get(LEGACY_VERSION, 0)
    named_equity_versions = [version for version in equity_versions if version != LEGACY_VERSION]
    reasons: List[str] = []
    if equity_count < 20:
        reasons.append("fewer_than_20_provider_confirmed_equities")
    if equity_count and versioned_equities != equity_count:
        reasons.append("cohort_contains_unversioned_runs")
    if len(named_equity_versions) > 1:
        reasons.append("cohort_mixes_model_versions")
    if equity_count and with_derived_capm / equity_count < 0.80:
        reasons.append("derived_capm_coverage_below_80_percent")
    if equity_count and with_comps / equity_count < 0.60:
        reasons.append("comps_coverage_below_60_percent")
    if analyst_count < 15:
        reasons.append("fewer_than_15_analyst_comparisons")

    return {
        "corpus": {
            "documents_received": len(documents or ()),
            "unique_tickers_received": len({
                str(doc.get("ticker") or "").strip().upper()
                for doc in documents or () if isinstance(doc, dict) and doc.get("ticker")
            }),
            "cohort_tickers": count,
            "latest_per_ticker": True,
            "model_version_filter": model_version,
            "model_versions": dict(sorted(versions.items())),
            "completed_min": min(completed).isoformat() if completed else None,
            "completed_max": max(completed).isoformat() if completed else None,
        },
        "data_quality": {
            "domains": dict(sorted(domains.items())),
            "formula_signatures": dict(sorted(signatures.items())),
            "equities_with_positive_comps": with_comps,
            "equities_with_two_positive_dcf_legs": with_two_dcf,
            "equities_with_derived_capm": with_derived_capm,
            "analyst_comparable": analyst_count,
            "age_eligible_for_12m_backtest": age_eligible_12m,
        },
        "recorded_at_run": {
            "ratings": dict(sorted(ratings.items())),
            "fair_value_gap": _distribution(recorded_gaps),
        },
        "method_equal_replay_at_run": {
            "fair_value_gap": _distribution(replay_gaps),
            "note": "Reweights stored legs only; it cannot replay the newer ERP or assumptions.",
        },
        "current_analyst_cross_check": {
            "model_gap": _distribution(current_model_gaps),
            "analyst_gap": _distribution(analyst_gaps),
            "model_minus_analyst_gap": _distribution(model_vs_analyst),
            "direction_agreement_share": (
                round(sum((model >= 0) == (analyst >= 0) for model, analyst in analyst_pairs)
                      / analyst_count, 6) if analyst_count else None
            ),
            "gap_correlation": _correlation(analyst_pairs),
            "note": "Consensus is an external cross-check, not ground truth or an intrinsic-value input.",
        },
        "readiness": {
            "cross_sectional_calibration_ready": not reasons and count > 0,
            "cross_sectional_blockers": reasons,
            "forecast_backtest_ready": age_eligible_12m >= 20,
            "forecast_backtest_note": (
                "Needs at least 20 point-in-time predictions old enough for a 12-month outcome."
            ),
        },
    }


def _load_json(path: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(value, list):
        return value, []
    if not isinstance(value, dict) or not isinstance(value.get("theses"), list):
        raise ValueError("Input must be a thesis list or {theses: [...], universe: [...] }.")
    universe = value.get("universe") if isinstance(value.get("universe"), list) else []
    return value["theses"], universe


def _load_mongo() -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    try:
        from dotenv import load_dotenv
        load_dotenv(".env")
    except ImportError:
        pass
    uri, db_name = os.getenv("MONGO_URI"), os.getenv("MONGO_DB")
    if not uri or not db_name:
        raise RuntimeError("MONGO_URI and MONGO_DB are required for --mongo.")
    from pymongo import MongoClient
    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    database = client[db_name]
    try:
        # Use an allowlist so owner identity, report text, prompts, job metadata,
        # and artifact paths never leave Mongo for this aggregate benchmark.
        theses = list(database.theses.find({}, {
            "_id": 0,
            "ticker": 1,
            "version": 1,
            "model_version": 1,
            "completed_at": 1,
            "job_created_at": 1,
            "recorded_at": 1,
            "capm_derived": 1,
            "valuation.fair_value": 1,
            "valuation.perpetual": 1,
            "valuation.exit_multiple": 1,
            "valuation.comps": 1,
            "valuation.current_price": 1,
            "verdict.rating": 1,
        }))
        tickers = sorted({
            str(doc.get("ticker") or "").strip().upper()
            for doc in theses if doc.get("ticker")
        })
        universe = list(database.ticker_universe.find(
            {"symbol": {"$in": tickers}},
            {"_id": 0, "symbol": 1, "quote_type": 1, "price_at_refresh": 1,
             "fundamentals_at": 1, "analyst_target_mean": 1, "analyst_count": 1},
        ))
    finally:
        client.close()
    return theses, universe


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Aggregate valuation calibration benchmark")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", help="Sanitized JSON thesis corpus")
    source.add_argument("--mongo", action="store_true", help="Read configured thesis/universe collections")
    parser.add_argument("--model-version", help="Evaluate only this immutable model release")
    parser.add_argument("--minimum-analysts", type=int, default=5)
    parser.add_argument("--compact", action="store_true")
    args = parser.parse_args(argv)

    documents, universe = _load_mongo() if args.mongo else _load_json(args.input)
    result = benchmark(
        documents, universe,
        model_version=args.model_version,
        minimum_analysts=args.minimum_analysts,
    )
    print(json.dumps(result, indent=None if args.compact else 2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
