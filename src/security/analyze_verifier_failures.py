"""
Summarize why the frozen verifier replay failed as a standalone defense.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from .final_artifacts import (
    REPORT_DIR,
    build_verifier_failure_analysis,
    render_verifier_failure_markdown,
    write_json,
    write_markdown,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze frozen verifier replay failures")
    parser.add_argument(
        "--output-json",
        type=Path,
        default=REPORT_DIR / "verifier_failure_analysis.json",
        help="Machine-readable verifier failure analysis output path",
    )
    parser.add_argument(
        "--output-md",
        type=Path,
        default=REPORT_DIR / "verifier_failure_analysis.md",
        help="Markdown companion for the verifier failure analysis",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = build_verifier_failure_analysis()
    write_json(args.output_json, payload)
    write_markdown(args.output_md, render_verifier_failure_markdown(payload))


if __name__ == "__main__":
    main()
