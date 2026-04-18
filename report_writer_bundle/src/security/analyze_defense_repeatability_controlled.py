"""
Analyze controlled same-slice repeatability for baseline vs struq-lite.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from .final_artifacts import (
    CONTROLLED_REPEATABILITY_ATTACK_CASE_IDS,
    CONTROLLED_REPEATABILITY_CLEAN_CASE_IDS,
    REPORT_DIR,
    REPO_ROOT,
    build_controlled_defense_repeatability_analysis,
    render_controlled_defense_repeatability_markdown,
    write_json,
    write_markdown,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze the controlled same-slice repeatability experiment"
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=REPO_ROOT / "datasets" / "security" / "cases.jsonl",
        help="Case manifest used for attack-success scoring",
    )
    parser.add_argument(
        "--baseline-runs",
        type=Path,
        action="append",
        default=[],
        help="Fresh baseline raw_runs.jsonl paths for the controlled slice",
    )
    parser.add_argument(
        "--struqlite-runs",
        type=Path,
        action="append",
        default=[],
        help="Fresh struq-lite raw_runs.jsonl paths for the controlled slice",
    )
    parser.add_argument(
        "--expected-repeats",
        type=int,
        default=3,
        help="Expected repeat count per configuration",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=REPORT_DIR / "defense_repeatability_controlled.json",
        help="Output JSON path",
    )
    parser.add_argument(
        "--output-md",
        type=Path,
        default=REPORT_DIR / "defense_repeatability_controlled.md",
        help="Output Markdown path",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = build_controlled_defense_repeatability_analysis(
        manifest_path=args.manifest,
        baseline_runs=args.baseline_runs,
        struq_lite_runs=args.struqlite_runs,
        clean_case_ids=CONTROLLED_REPEATABILITY_CLEAN_CASE_IDS,
        attack_case_ids=CONTROLLED_REPEATABILITY_ATTACK_CASE_IDS,
        expected_repeat_count=args.expected_repeats,
    )
    write_json(args.output_json, payload)
    write_markdown(args.output_md, render_controlled_defense_repeatability_markdown(payload))


if __name__ == "__main__":
    main()
