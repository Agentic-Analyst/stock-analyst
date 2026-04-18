"""
Package a verifier replay run into report-facing JSON and Markdown artifacts.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from .final_artifacts import (
    REPORT_DIR,
    build_verifier_replay_evaluation,
    render_verifier_replay_evaluation_markdown,
    write_json,
    write_markdown,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Package verifier replay results for reporting")
    parser.add_argument(
        "--summary",
        type=Path,
        required=True,
        help="Path to verifier_summary.json",
    )
    parser.add_argument(
        "--replay",
        type=Path,
        required=True,
        help="Path to verifier_replay.jsonl",
    )
    parser.add_argument(
        "--label",
        required=True,
        help="Human-readable artifact label",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=REPORT_DIR / "verifier_v2_evaluation.json",
        help="Output JSON path",
    )
    parser.add_argument(
        "--output-md",
        type=Path,
        default=REPORT_DIR / "verifier_v2_evaluation.md",
        help="Output Markdown path",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = build_verifier_replay_evaluation(
        summary_path=args.summary,
        replay_path=args.replay,
        label=args.label,
    )
    write_json(args.output_json, payload)
    write_markdown(args.output_md, render_verifier_replay_evaluation_markdown(payload))


if __name__ == "__main__":
    main()
