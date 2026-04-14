"""
Generate the frozen, paper-facing evidence bundle from existing run artifacts.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from .final_artifacts import (
    REPORT_DIR,
    build_final_case_study_pack,
    build_final_table_values,
    build_results_ledger,
    render_final_case_studies_markdown,
    render_final_table_values_markdown,
    render_results_ledger_markdown,
    write_json,
    write_markdown,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Package the frozen final-report evidence bundle")
    parser.add_argument(
        "--results-ledger-json",
        type=Path,
        default=REPORT_DIR / "final_results_ledger.json",
        help="Machine-readable results ledger output path",
    )
    parser.add_argument(
        "--results-ledger-md",
        type=Path,
        default=REPORT_DIR / "final_results_ledger.md",
        help="Markdown companion for the results ledger",
    )
    parser.add_argument(
        "--table-values-json",
        type=Path,
        default=REPORT_DIR / "final_table_values.json",
        help="Machine-readable final table values output path",
    )
    parser.add_argument(
        "--table-values-md",
        type=Path,
        default=REPORT_DIR / "final_table_values.md",
        help="Markdown companion for the final table values",
    )
    parser.add_argument(
        "--case-study-json",
        type=Path,
        default=REPORT_DIR / "final_case_study_pack.json",
        help="Machine-readable final case-study export path",
    )
    parser.add_argument(
        "--case-study-md",
        type=Path,
        default=REPORT_DIR / "final_case_studies.md",
        help="Markdown companion for the final case studies",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    results_ledger = build_results_ledger()
    write_json(args.results_ledger_json, results_ledger)
    write_markdown(args.results_ledger_md, render_results_ledger_markdown(results_ledger))

    table_values = build_final_table_values()
    write_json(args.table_values_json, table_values)
    write_markdown(args.table_values_md, render_final_table_values_markdown(table_values))

    case_studies = build_final_case_study_pack()
    write_json(args.case_study_json, case_studies)
    write_markdown(args.case_study_md, render_final_case_studies_markdown(case_studies))


if __name__ == "__main__":
    main()
