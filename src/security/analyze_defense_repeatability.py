"""
Analyze repeatability across repeated defense runs.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from .final_artifacts import (
    REPORT_DIR,
    REPO_ROOT,
    build_defense_repeatability_analysis,
    render_defense_repeatability_markdown,
    write_json,
    write_markdown,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze repeatability across repeated defense runs")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=REPO_ROOT / "datasets" / "security" / "cases.jsonl",
        help="Case manifest used for attack-success scoring",
    )
    parser.add_argument(
        "--clean-case-id",
        action="append",
        default=[],
        help="Clean case IDs to include in utility stability analysis",
    )
    parser.add_argument(
        "--attack-case-id",
        action="append",
        default=[],
        help="Attack case IDs to include in defended stability analysis",
    )
    parser.add_argument(
        "--baseline-runs",
        type=Path,
        action="append",
        default=[],
        help="Repeated raw_runs.jsonl paths for baseline",
    )
    parser.add_argument(
        "--struqlite-runs",
        type=Path,
        action="append",
        default=[],
        help="Repeated raw_runs.jsonl paths for struq-lite",
    )
    parser.add_argument(
        "--guarded-runs",
        type=Path,
        action="append",
        default=[],
        help="Repeated raw_runs.jsonl paths for guarded-v2",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=REPORT_DIR / "defense_repeatability.json",
        help="Output JSON path",
    )
    parser.add_argument(
        "--output-md",
        type=Path,
        default=REPORT_DIR / "defense_repeatability.md",
        help="Output Markdown path",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_groups = {
        "baseline": args.baseline_runs,
        "struq-lite": args.struqlite_runs,
    }
    if args.guarded_runs:
        run_groups["guarded-v2"] = args.guarded_runs
    payload = build_defense_repeatability_analysis(
        manifest_path=args.manifest,
        run_groups=run_groups,
        clean_case_ids=args.clean_case_id,
        attack_case_ids=args.attack_case_id,
    )
    write_json(args.output_json, payload)
    write_markdown(args.output_md, render_defense_repeatability_markdown(payload))


if __name__ == "__main__":
    main()
