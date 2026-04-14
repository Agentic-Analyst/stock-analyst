"""
Export the frozen qualitative case-study pack used for the final paper.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from .final_artifacts import (
    REPORT_DIR,
    build_final_case_study_pack,
    render_final_case_studies_markdown,
    write_json,
    write_markdown,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export frozen final case studies")
    parser.add_argument(
        "--output-json",
        type=Path,
        default=REPORT_DIR / "final_case_study_pack.json",
        help="Machine-readable final case-study pack output path",
    )
    parser.add_argument(
        "--output-md",
        type=Path,
        default=REPORT_DIR / "final_case_studies.md",
        help="Markdown companion for the final case studies",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = build_final_case_study_pack()
    write_json(args.output_json, payload)
    write_markdown(args.output_md, render_final_case_studies_markdown(payload))


if __name__ == "__main__":
    main()
