"""
Materialize a compact attack-development manifest from the canonical benchmark.

This keeps the main frozen benchmark unchanged while allowing a small subset of
poisoned cases to be regenerated with the latest attack templates.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Dict, List, Sequence

from .attacks import ATTACK_TEMPLATE_VERSION, build_poisoned_article
from .dataset import load_article, load_cases, resolve_path, write_article, write_cases
from .governance import (
    compute_dataset_corpus_version,
    get_code_commit,
    load_dataset_metadata,
    write_dataset_metadata,
)
from .metrics import METRIC_VERSION
from .models import ArticleRecord, SecurityCase
from .runtime import REPO_ROOT


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Materialize a small attack-development manifest with current attack templates"
    )
    parser.add_argument(
        "--source-cases",
        type=Path,
        default=REPO_ROOT / "datasets" / "security" / "cases.jsonl",
        help="Canonical source manifest",
    )
    parser.add_argument(
        "--selection",
        type=Path,
        default=REPO_ROOT / "datasets" / "security" / "attack_development_subset.json",
        help="Selection JSON emitted by select_attack_development.py",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=REPO_ROOT / "datasets" / "security_attack_dev",
        help="Output directory for the dev manifest and article files",
    )
    parser.add_argument(
        "--case-id",
        action="append",
        default=[],
        help="Restrict to specific poisoned case IDs from the selection file",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Delete and recreate the output directory before writing",
    )
    parser.add_argument(
        "--notes",
        default="calculator-first attack development manifest rematerialized from canonical corpus",
        help="Notes recorded in benchmark_metadata.json",
    )
    return parser.parse_args()


def load_selected_case_ids(selection_path: Path) -> List[str]:
    payload = json.loads(selection_path.read_text(encoding="utf-8"))
    return [item["case_id"] for item in payload.get("selected_cases", []) if item.get("case_id")]


def _load_case_articles(case: SecurityCase, manifest_path: Path) -> List[ArticleRecord]:
    return [
        load_article(resolve_path(ref, base_dir=manifest_path.parent))
        for ref in case.article_refs
    ]


def _display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def _copy_articles_for_case(
    *,
    case: SecurityCase,
    articles: Sequence[ArticleRecord],
    manifest_path: Path,
    output_root: Path,
) -> List[str]:
    refs: List[str] = []
    for ref, article in zip(case.article_refs, articles):
        source_path = resolve_path(ref, base_dir=manifest_path.parent)
        destination = output_root / "articles" / case.case_id / source_path.name
        write_article(destination, article)
        refs.append(destination.relative_to(output_root).as_posix())
    return refs


def _copy_clean_case(
    *,
    source_case: SecurityCase,
    manifest_path: Path,
    output_root: Path,
) -> SecurityCase:
    articles = _load_case_articles(source_case, manifest_path)
    refs = _copy_articles_for_case(
        case=source_case,
        articles=articles,
        manifest_path=manifest_path,
        output_root=output_root,
    )
    copied = SecurityCase.from_dict(source_case.to_dict())
    copied.article_refs = refs
    return copied


def _materialize_poisoned_case(
    *,
    source_case: SecurityCase,
    clean_case: SecurityCase,
    manifest_path: Path,
    output_root: Path,
) -> SecurityCase:
    clean_articles = _load_case_articles(clean_case, manifest_path)
    if not clean_articles:
        raise ValueError(f"{clean_case.case_id} has no articles to poison")

    anchor_article = clean_articles[0]
    context_articles = list(clean_articles[1:])
    company_name = str(source_case.metadata.get("company_name", source_case.ticker))
    attack_context = dict(source_case.metadata)
    poisoned_anchor, labels = build_poisoned_article(
        seed_article=anchor_article,
        ticker=source_case.ticker,
        company_name=company_name,
        attack_tier=source_case.attack_tier,
        target_direction=source_case.target_direction,
        attack_context=attack_context,
    )
    materialized_articles = [poisoned_anchor] + context_articles
    refs = _copy_articles_for_case(
        case=source_case,
        articles=materialized_articles,
        manifest_path=manifest_path,
        output_root=output_root,
    )

    copied = SecurityCase.from_dict(source_case.to_dict())
    copied.article_refs = refs
    copied.metadata = {
        **copied.metadata,
        "poison_span_labels": labels,
        "dev_materialized_from_case_id": source_case.case_id,
        "dev_materialized_from_clean_case_id": clean_case.case_id,
        "dev_attack_template_version": ATTACK_TEMPLATE_VERSION,
    }
    return copied


def materialize_attack_development_manifest(
    *,
    source_manifest: Path,
    selection_path: Path,
    output_root: Path,
    selected_case_ids: Sequence[str] | None = None,
    force: bool = False,
    notes: str = "",
) -> Dict[str, object]:
    source_manifest = source_manifest.resolve()
    source_dataset_root = source_manifest.parent
    output_root = output_root.resolve()

    if force and output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    source_cases = {case.case_id: case for case in load_cases(source_manifest)}
    selected_ids = list(selected_case_ids or load_selected_case_ids(selection_path))
    if not selected_ids:
        raise ValueError("No attack-development cases were selected")

    selected_poisoned: List[SecurityCase] = []
    selected_base_case_ids: List[str] = []
    for case_id in selected_ids:
        case = source_cases.get(case_id)
        if case is None:
            raise ValueError(f"Selected case {case_id} not found in {source_manifest}")
        if case.case_type != "poisoned":
            raise ValueError(f"Selected case {case_id} is not a poisoned case")
        selected_poisoned.append(case)
        if case.base_case_id not in selected_base_case_ids:
            selected_base_case_ids.append(case.base_case_id)

    materialized_cases: List[SecurityCase] = []
    clean_case_lookup: Dict[str, SecurityCase] = {}
    for base_case_id in selected_base_case_ids:
        clean_case_id = f"{base_case_id}_clean"
        clean_case = source_cases.get(clean_case_id)
        if clean_case is None:
            raise ValueError(f"Missing clean baseline {clean_case_id} for dev materialization")
        copied_clean = _copy_clean_case(
            source_case=clean_case,
            manifest_path=source_manifest,
            output_root=output_root,
        )
        materialized_cases.append(copied_clean)
        clean_case_lookup[base_case_id] = clean_case

    for poisoned_case in selected_poisoned:
        materialized_cases.append(
            _materialize_poisoned_case(
                source_case=poisoned_case,
                clean_case=clean_case_lookup[poisoned_case.base_case_id],
                manifest_path=source_manifest,
                output_root=output_root,
            )
        )

    manifest_path = output_root / "cases.jsonl"
    write_cases(manifest_path, materialized_cases)

    source_metadata = load_dataset_metadata(source_dataset_root)
    metadata = {
        "corpus_version": None,
        "direction_map_version": source_metadata.get("direction_map_version", "unknown"),
        "attack_template_version": ATTACK_TEMPLATE_VERSION,
        "metric_version": source_metadata.get("metric_version", METRIC_VERSION),
        "code_commit": get_code_commit(),
        "notes": notes,
        "source_manifest": _display_path(source_manifest),
        "selection_path": _display_path(selection_path),
        "parent_corpus_version": source_metadata.get("corpus_version"),
        "parent_attack_template_version": source_metadata.get("attack_template_version"),
        "selected_poisoned_case_ids": selected_ids,
        "selected_clean_case_ids": [f"{base_case_id}_clean" for base_case_id in selected_base_case_ids],
    }
    metadata["corpus_version"] = compute_dataset_corpus_version(output_root)
    write_dataset_metadata(output_root, metadata)

    return {
        "manifest_path": manifest_path,
        "output_root": output_root,
        "materialized_case_ids": [case.case_id for case in materialized_cases],
        "poisoned_case_ids": selected_ids,
        "clean_case_ids": [f"{base_case_id}_clean" for base_case_id in selected_base_case_ids],
        "benchmark_metadata": metadata,
    }


def main() -> None:
    args = parse_args()
    summary = materialize_attack_development_manifest(
        source_manifest=args.source_cases,
        selection_path=args.selection,
        output_root=args.output_root,
        selected_case_ids=args.case_id or None,
        force=args.force,
        notes=args.notes,
    )
    print(
        json.dumps(
            {
                "manifest_path": str(summary["manifest_path"]),
                "case_count": len(summary["materialized_case_ids"]),
                "poisoned_case_ids": summary["poisoned_case_ids"],
                "clean_case_ids": summary["clean_case_ids"],
                "corpus_version": summary["benchmark_metadata"]["corpus_version"],
                "attack_template_version": summary["benchmark_metadata"]["attack_template_version"],
            },
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
