"""Read-only live-data canary for valuation launch review.

This exercises the same financial/analyst/peer collection path as a worker but
does not invoke an LLM, build a workbook, save an artifact, or write a database.
Output is deliberately compact and contains no credentials.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

# The production entry point exposes both the repository root (for ``src.*``)
# and ``src`` itself (for legacy top-level imports). Release utilities must be
# runnable with ``python -m src...`` too, otherwise the documented/read-only
# preflight can fail before it tests anything.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from financial_scraper import FinancialScraper


class _QuietLogger:
    def __getattr__(self, _name):
        return lambda *_args, **_kwargs: None


def _summary(data: Dict[str, Any], *, elapsed: float, failed: int) -> Dict[str, Any]:
    company = data.get("company_data") or {}
    basic = company.get("basic_info") or {}
    market = company.get("market_data") or {}
    consensus = company.get("analyst_consensus") or {}
    target = consensus.get("price_target") or {}
    recommendation = consensus.get("recommendation") or {}
    peers = (data.get("industry_data") or {}).get("peer_comps") or {}
    peer_configuration = (data.get("industry_data") or {}).get("peer_comps_status") or {}
    external = data.get("external_expectations") or {}
    analyst_observations = external.get("analyst_observations") or {}
    methodology = data.get("valuation_methodology") or {}
    warnings = []
    is_equity = str(basic.get("quote_type") or "").upper() == "EQUITY"
    if failed and is_equity:
        warnings.append(f"{failed} financial statement surfaces failed")
    if not is_equity:
        warnings.append("not an equity; corporate valuation must not run")
    if is_equity and external.get("coverage") == "limited":
        warnings.append("Street benchmark coverage limited")
    if is_equity and target.get("mean") is None:
        warnings.append("analyst mean target unavailable")
    expects_corporate_peers = bool(
        is_equity and methodology.get("specialized_service") not in {
            "reit", "insurance", "commodity_cycle",
        }
    )
    if expects_corporate_peers and peer_configuration and not peer_configuration.get("ready"):
        warnings.append(
            "peer cross-check not configured: "
            + "; ".join(peer_configuration.get("blockers") or ["unknown reason"])
        )
    elif peers and peers.get("status") == "not_applicable":
        warnings.append(peers.get("reason") or "peer cross-check is not applicable")
    elif peers and peers.get("status") not in (None, "ready"):
        warnings.append(f"peer cross-check unavailable: {peers.get('status')}")
    elif peers and peers.get("confidence") == "low":
        warnings.append("broad peer cross-check is low confidence and excluded from blend")
    freshness = data.get("financial_freshness") or {}
    ttm = data.get("ttm_bridge") or {}
    estimates = [{
        key: row.get(key) for key in (
            "period", "revenue_growth", "revenue_analyst_count", "eps",
            "eps_analyst_count", "implied_net_margin",
        )
    } for row in external.get("forward_estimates") or []]
    provider_status = consensus.get("provider_status") or {}
    compact_providers = {
        name: {
            key: row.get(key) for key in (
                "configured", "attempted", "usable", "coverage_count",
                "meets_minimum_coverage", "eligible_primary",
                "price_target_coverage_count", "price_target_eligible",
                "recommendation_coverage_count", "recommendation_eligible",
                "analyst_observations_usable", "analyst_observation_count",
                "query_window",
                "partial_errors",
            )
        }
        for name, row in provider_status.items() if isinstance(row, dict)
    }
    return {
        "ticker": data.get("ticker"),
        "elapsed_seconds": round(elapsed, 2),
        "quote_type": basic.get("quote_type"),
        "sector": basic.get("sector"),
        "industry": basic.get("industry"),
        "currency": basic.get("currency"),
        "financial_currency": basic.get("currency"),
        "listing_currency": basic.get("listing_currency"),
        "current_price": market.get("current_price"),
        "current_price_listing": market.get("current_price_listing"),
        "fx_listing_to_financial": market.get("fx_listing_to_financial"),
        "financial_freshness": {
            key: freshness.get(key)
            for key in ("status", "basis", "latest_period", "age_days", "reason")
        },
        "ttm_status": {
            key: ttm.get(key)
            for key in ("status", "latest_period", "age_days", "reason")
        },
        "valuation_methodology": {
            key: methodology.get(key) for key in (
                "primary_method", "quality", "publication_allowed", "reason",
                "specialized_service",
            )
        },
        "street": {
            "coverage": external.get("coverage"),
            "target_mean": target.get("mean"),
            "target_count": target.get("analyst_count"),
            "target_coverage_unit": target.get("coverage_unit"),
            "target_source": target.get("source"),
            "rating": recommendation.get("label"),
            "rating_source": recommendation.get("source"),
            "provider_status": compact_providers,
            "forward_estimates": estimates,
            "analyst_observations": {
                key: analyst_observations.get(key) for key in (
                    "source", "observation_count", "as_of",
                    "oldest_observation_as_of", "excluded_observation_count",
                    "included_in_intrinsic_value",
                )
            },
        },
        "peers": {
            key: peers.get(key) for key in (
                "status", "error_type", "grouping", "peer_universe_source", "selected_method",
                "selected_peer_symbols", "selected_peer_count", "confidence",
                "role", "included_in_blended_value", "median_ev_ebitda",
                "median_price_sales", "ev_ebitda_peer_count",
                "price_sales_peer_count", "failed_symbols", "size_excluded_symbols",
                "fundamental_excluded_symbols", "subindustry_requested_peers",
                "screening_stages",
                "size_screen_applied", "fundamental_screen_applied",
                "comparability_thresholds", "minimum_subject_size_ratio", "reason",
            )
        } if peers else None,
        "peer_configuration": {
            key: peer_configuration.get(key)
            for key in ("mode", "enabled", "ready", "provider_key_configured", "blockers")
        },
        "warnings": warnings,
    }


def run(tickers: Sequence[str]) -> list[Dict[str, Any]]:
    results = []
    with tempfile.TemporaryDirectory(prefix="vynn-valuation-canary-") as temp:
        for ticker in tickers:
            started = time.monotonic()
            scraper = FinancialScraper(ticker, Path(temp) / ticker.upper())
            scraper.set_logger(_QuietLogger())
            try:
                data = scraper.scrape_financial_modeling_data(annual=True)
                results.append(_summary(
                    data, elapsed=time.monotonic() - started,
                    failed=scraper.failed_statements,
                ))
            except Exception as error:
                results.append({
                    "ticker": ticker.upper(),
                    "elapsed_seconds": round(time.monotonic() - started, 2),
                    "error_type": type(error).__name__,
                    "status": "failed",
                })
    return results


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("tickers", nargs="+", help="Equity symbols to exercise")
    parser.add_argument("--env-file", help="Optional dotenv file with provider keys")
    args = parser.parse_args(argv)
    if args.env_file:
        from dotenv import load_dotenv
        # An explicit canary input must win over blank/stale shell variables;
        # otherwise the command can silently test Yahoo-only behavior while
        # claiming to exercise the supplied licensed provider credentials.
        load_dotenv(args.env_file, override=True)
    rows = run(args.tickers)
    print(json.dumps(rows, indent=2, sort_keys=True))
    return 1 if any(row.get("status") == "failed" for row in rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
