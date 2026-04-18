"""
Summarize cross-case attackability and observed static outcomes.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from .final_artifacts import (
    OFFICIAL_FROZEN_PATHS,
    OFFICIAL_STATIC_OBSERVED_RAW_RUNS,
    REPORT_DIR,
    REPO_ROOT,
    build_cross_case_attackability_analysis,
    render_cross_case_attackability_markdown,
    write_json,
    write_markdown,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze cross-case attackability against observed static outcomes"
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=REPO_ROOT / "datasets" / "security" / "cases.jsonl",
        help="Case manifest used to recover scenario metadata",
    )
    parser.add_argument(
        "--attack-surface",
        type=Path,
        default=OFFICIAL_FROZEN_PATHS["calculator_attack_surface_json"],
        help="Calculator attack-surface JSON artifact",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=REPORT_DIR / "cross_case_attackability.json",
        help="Output JSON path",
    )
    parser.add_argument(
        "--output-md",
        type=Path,
        default=REPORT_DIR / "cross_case_attackability.md",
        help="Output Markdown path",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = build_cross_case_attackability_analysis(
        manifest_path=args.manifest,
        attack_surface_path=args.attack_surface,
        observed_raw_runs=OFFICIAL_STATIC_OBSERVED_RAW_RUNS,
    )
    write_json(args.output_json, payload)
    write_markdown(args.output_md, render_cross_case_attackability_markdown(payload))


if __name__ == "__main__":
    main()
