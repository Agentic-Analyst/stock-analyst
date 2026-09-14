"""Current-data, real-model launch canary for the valuation engine.

Unlike ``valuation_launch_canary``, this builds the deterministic numerical
model once per symbol, evaluates every workbook formula, applies the
publication boundary, and audits the saved workbook. It never invokes an LLM,
generates news, or writes a narrative report.
Outputs go to a temporary directory unless ``--output-root`` is supplied.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from financial_scraper import FinancialScraper
from src.agents.fm import create_financial_model
from src.valuation_artifact_audit import audit_run
from src.valuation_methodology import assess_valuation_methodology


class _QuietLogger:
    def __getattr__(self, _name):
        return lambda *_args, **_kwargs: None


def _valid_specialized_refusal(
    financial: Dict[str, Any], methodology: Dict[str, Any],
) -> bool:
    """Tell a real-symbol canary from an upstream data-acquisition failure.

    Refusing a known fund, crypto asset, REIT, or other explicitly classified
    instrument is a successful safety outcome.  ``UNKNOWN`` paired with the
    generic unsupported-asset route usually means the quote provider never
    returned the requested company.  Treating that as a passing launch canary
    hid DNS/auth/provider outages.
    """
    quote_type = str(
        (((financial.get("company_data") or {}).get("basic_info") or {}).get(
            "quote_type"
        ) or "UNKNOWN")
    ).strip().upper()
    return not (
        methodology.get("specialized_service") == "unsupported_asset"
        and quote_type in {"", "UNKNOWN"}
    )


def _compact(audit: Dict[str, Any], *, elapsed: float) -> Dict[str, Any]:
    keys = (
        "status", "ticker", "quote_type", "financial_currency",
        "listing_currency", "current_price", "current_price_listing",
        "fx_listing_to_financial", "method",
        "dcf_perpetual", "dcf_exit", "dcf_midpoint", "dcf_gap_vs_market",
        "bank_intrinsic_value", "bank_forward_consensus_value",
        "bank_peer_value", "peer_value",
        "street_target", "street_target_count", "street_target_gap_vs_market",
        "street_coverage", "reliability_band", "range_low", "range_high",
        "analyst_observation_count", "analyst_observation_as_of",
        "analyst_observations_included_in_intrinsic_value",
        "point_estimate_withheld", "withheld_reason",
        "reverse_dcf_market_implied_vs_model", "stored_publication_allowed",
        "market_implied_fcf_path_vs_model",
        "analyst_target_implied_fcf_path_vs_model",
        "model_wacc", "model_tax_rate", "model_terminal_growth",
        "market_implied_wacc", "market_implied_wacc_vs_model",
        "analyst_target_implied_wacc", "analyst_target_implied_wacc_vs_model",
        "market_implied_terminal_growth",
        "market_implied_terminal_growth_vs_model",
        "analyst_target_implied_terminal_growth",
        "analyst_target_implied_terminal_growth_vs_model",
        "stored_publication_status", "formula_integrity_status",
        "formula_integrity_issue_count", "model_integrity_status",
        "model_integrity_issue_count", "workbook_headline_label", "checks",
    )
    return {
        **{key: audit.get(key) for key in keys},
        "elapsed_seconds": round(elapsed, 2),
    }


def run(tickers: Sequence[str], root: Path) -> list[Dict[str, Any]]:
    rows = []
    logger = _QuietLogger()
    for raw_ticker in tickers:
        ticker = str(raw_ticker or "").strip().upper()
        started = time.monotonic()
        run_root = root / ticker / "current"
        scraper = FinancialScraper(ticker, run_root)
        scraper.set_logger(logger)
        try:
            financial = scraper.scrape_financial_modeling_data(annual=True)
            financial_path = scraper.save_financial_data(financial)
            (run_root / "models").mkdir(parents=True, exist_ok=True)
            methodology = assess_valuation_methodology(financial)
            if methodology.get("specialized_service"):
                if not _valid_specialized_refusal(financial, methodology):
                    raise RuntimeError(
                        "Upstream company classification is UNKNOWN; this is a "
                        "data-acquisition failure, not a passing specialized-asset refusal."
                    )
                try:
                    create_financial_model(
                        ticker, financial_path, logger,
                        run_root / "models" / f"{ticker}_financial_model.xlsx",
                    )
                except ValueError:
                    rows.append({
                        "status": "passed_specialized_refusal",
                        "ticker": ticker,
                        "method": methodology.get("primary_method"),
                        "specialized_service": methodology.get("specialized_service"),
                        "reason": methodology.get("reason"),
                        "elapsed_seconds": round(time.monotonic() - started, 2),
                    })
                    continue
                raise RuntimeError("specialized asset incorrectly built a corporate DCF")

            create_financial_model(
                ticker, financial_path, logger,
                run_root / "models" / f"{ticker}_financial_model.xlsx",
            )
            rows.append(_compact(
                audit_run(run_root), elapsed=time.monotonic() - started,
            ))
        except Exception as error:
            rows.append({
                "status": "failed", "ticker": ticker,
                "error_type": type(error).__name__,
                "error": str(error)[:500],
                "elapsed_seconds": round(time.monotonic() - started, 2),
            })
    return rows


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("tickers", nargs="+")
    parser.add_argument(
        "--env-file", action="append", default=[],
        help="Dotenv file to load; repeat for split model/provider credentials",
    )
    parser.add_argument("--output-root", type=Path)
    args = parser.parse_args(argv)
    if args.env_file:
        from dotenv import load_dotenv
        for env_file in args.env_file:
            load_dotenv(env_file, override=True)

    if args.output_root:
        args.output_root.mkdir(parents=True, exist_ok=True)
        rows = run(args.tickers, args.output_root)
    else:
        with tempfile.TemporaryDirectory(prefix="vynn-model-canary-") as temp:
            rows = run(args.tickers, Path(temp))
    print(json.dumps(rows, indent=2, sort_keys=True))
    return 1 if any(row.get("status") == "failed" for row in rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
