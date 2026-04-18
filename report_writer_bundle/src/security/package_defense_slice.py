"""
Package one defended benchmark slice into report-facing JSON and Markdown artifacts.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from .final_artifacts import (
    REPORT_DIR,
    REPO_ROOT,
    build_defense_slice_report,
    render_defense_slice_markdown,
    write_json,
    write_markdown,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Package one defense slice for reporting")
    parser.add_argument("--summary", type=Path, required=True, help="Path to summary.json")
    parser.add_argument(
        "--raw-runs",
        type=Path,
        default=None,
        help="Optional raw_runs.jsonl path for per-case outcomes",
    )
    parser.add_argument("--label", required=True, help="Human-readable artifact label")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=REPO_ROOT / "datasets" / "security" / "cases.jsonl",
        help="Manifest used to score case pairs",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=REPORT_DIR / "guarded_v2_static.json",
        help="Output JSON path",
    )
    parser.add_argument(
        "--output-md",
        type=Path,
        default=REPORT_DIR / "guarded_v2_static.md",
        help="Output Markdown path",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = build_defense_slice_report(
        summary_path=args.summary,
        raw_runs_path=args.raw_runs,
        label=args.label,
        manifest_path=args.manifest,
    )
    write_json(args.output_json, payload)
    write_markdown(args.output_md, render_defense_slice_markdown(payload))


if __name__ == "__main__":
    main()
