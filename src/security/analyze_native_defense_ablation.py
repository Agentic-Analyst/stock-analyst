"""
Package the native-defense ablation / decomposition analysis.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from .final_artifacts import (
    REPORT_DIR,
    REPO_ROOT,
    build_native_defense_ablation,
    render_native_defense_ablation_markdown,
    write_json,
    write_markdown,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze native defense layers from frozen benchmark artifacts"
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=REPO_ROOT / "datasets" / "security" / "cases.jsonl",
        help="Case manifest used for boundary metadata",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=REPORT_DIR / "native_defense_ablation.json",
        help="Output JSON path",
    )
    parser.add_argument(
        "--output-md",
        type=Path,
        default=REPORT_DIR / "native_defense_ablation.md",
        help="Output Markdown path",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = build_native_defense_ablation(manifest_path=args.manifest)
    write_json(args.output_json, payload)
    write_markdown(args.output_md, render_native_defense_ablation_markdown(payload))


if __name__ == "__main__":
    main()
