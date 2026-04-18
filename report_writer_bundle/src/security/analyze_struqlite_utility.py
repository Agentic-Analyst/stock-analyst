"""
Quantify clean-utility drift under the frozen struq-lite defense slice.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from .final_artifacts import (
    REPORT_DIR,
    build_struqlite_clean_utility_analysis,
    render_struqlite_clean_utility_markdown,
    write_json,
    write_markdown,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze clean-utility drift under frozen struq-lite results")
    parser.add_argument(
        "--output-json",
        type=Path,
        default=REPORT_DIR / "struqlite_clean_utility.json",
        help="Machine-readable struq-lite clean-utility analysis output path",
    )
    parser.add_argument(
        "--output-md",
        type=Path,
        default=REPORT_DIR / "struqlite_clean_utility.md",
        help="Markdown companion for the struq-lite clean-utility analysis",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = build_struqlite_clean_utility_analysis()
    write_json(args.output_json, payload)
    write_markdown(args.output_md, render_struqlite_clean_utility_markdown(payload))


if __name__ == "__main__":
    main()
