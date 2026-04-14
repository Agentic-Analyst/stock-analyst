"""
CLI entrypoint for the local security benchmark.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import json
from pathlib import Path
from typing import Dict, List

from .dataset import append_jsonl, load_cases, validate_case_paths
from .executor import deserialize_run_result, run_case_worker
from .governance import DEFAULT_RUN_VALIDITY, RUN_VALIDITY_CHOICES, resolve_run_governance
from .metrics import summarize_results, write_summary_markdown
from .models import SecurityCase, SecurityConfig, SecurityRunResult
from .pipeline import run_case
from .runtime import REPO_ROOT, load_project_env

load_project_env()

from llms.config import configure_llm_cache, init_llm  # type: ignore  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the VYNN AI security benchmark")
    parser.add_argument(
        "--cases",
        type=Path,
        default=REPO_ROOT / "datasets" / "security" / "cases.jsonl",
        help="Path to the security case manifest",
    )
    parser.add_argument(
        "--config",
        default="baseline",
        help="Security config preset name",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=REPO_ROOT / "runs" / "security",
        help="Root directory for run artifacts",
    )
    parser.add_argument(
        "--split",
        choices=["pilot", "main", "validation"],
        default=None,
        help="Filter to one manifest split",
    )
    parser.add_argument(
        "--case-id",
        action="append",
        default=[],
        help="Run only specific case IDs",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit the number of selected cases",
    )
    parser.add_argument(
        "--case-type",
        choices=["all", "clean", "poisoned", "stale_sidecar"],
        default="all",
        help="Filter to one case type",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate the manifest and exit without executing cases",
    )
    parser.add_argument(
        "--input-separation",
        action="store_true",
        help="Override the preset and enable StruQ-inspired separation",
    )
    parser.add_argument(
        "--sanitizer",
        action="store_true",
        help="Override the preset and enable deterministic sanitization",
    )
    parser.add_argument(
        "--verifier",
        action="store_true",
        help="Override the preset and enable the output verifier",
    )
    parser.add_argument(
        "--block-on-flag",
        action="store_true",
        help="Override the preset and block downstream report generation on verifier flags",
    )
    parser.add_argument(
        "--target-model",
        default=None,
        help="Override the preset target model for screening/report generation",
    )
    parser.add_argument(
        "--verifier-model",
        default=None,
        help="Override the preset verifier model",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help="Override the screener batch size",
    )
    parser.add_argument(
        "--skip-report",
        action="store_true",
        help="Run the benchmark through recommendation snapshot generation without full report generation",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=None,
        help="Maximum number of case workers to run in parallel",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Reuse completed case outputs from the existing raw_runs.jsonl file and only run missing cases",
    )
    cache_group = parser.add_mutually_exclusive_group()
    cache_group.add_argument(
        "--cache-llm",
        dest="cache_llm",
        action="store_true",
        help="Enable the disk-backed LLM cache for benchmark calls",
    )
    cache_group.add_argument(
        "--no-cache",
        dest="cache_llm",
        action="store_false",
        help="Disable the disk-backed LLM cache for benchmark calls",
    )
    parser.set_defaults(cache_llm=None)
    parser.add_argument(
        "--run-validity",
        choices=sorted(RUN_VALIDITY_CHOICES),
        default=DEFAULT_RUN_VALIDITY,
        help="Label the intended validity of this run for later reporting",
    )
    parser.add_argument(
        "--notes",
        default="",
        help="Optional experiment notes to record in benchmark artifacts",
    )
    return parser.parse_args()


def select_cases(
    cases: List[SecurityCase],
    *,
    split: str | None,
    case_ids: List[str],
    case_type: str,
    limit: int | None,
) -> List[SecurityCase]:
    selected = cases
    if split:
        selected = [case for case in selected if case.split == split]
    if case_ids:
        case_id_set = set(case_ids)
        selected = [case for case in selected if case.case_id in case_id_set]
    if case_type != "all":
        selected = [case for case in selected if case.case_type == case_type]
    if limit is not None:
        selected = selected[:limit]
    return selected


def apply_flag_overrides(config: SecurityConfig, args: argparse.Namespace) -> SecurityConfig:
    if args.input_separation:
        config.input_separation = True
    if args.sanitizer:
        config.sanitizer = True
    if args.verifier:
        config.verifier = True
    if args.block_on_flag:
        config.block_on_flag = True
    if args.target_model:
        config.target_model = args.target_model
    if args.verifier_model:
        config.verifier_model = args.verifier_model
    if args.batch_size is not None:
        config.batch_size = args.batch_size
    if args.skip_report:
        config.generate_report = False
    if args.max_workers is not None:
        config.max_workers = max(1, args.max_workers)
    if args.resume:
        config.resume = True
    if args.cache_llm is not None:
        config.cache_llm = args.cache_llm
    return config


def load_existing_results(raw_runs_path: Path) -> Dict[str, SecurityRunResult]:
    """Load the latest result for each case from an append-only raw run log."""
    if not raw_runs_path.exists():
        return {}

    results: Dict[str, SecurityRunResult] = {}
    with raw_runs_path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            result = SecurityRunResult.from_dict(json.loads(line))
            results[result.case_id] = result
    return results


def plan_case_execution(
    selected_cases: List[SecurityCase],
    existing_results: Dict[str, SecurityRunResult],
    *,
    resume: bool,
) -> tuple[List[SecurityCase], Dict[str, SecurityRunResult]]:
    """Split selected cases into pending vs reusable completed results."""
    reusable: Dict[str, SecurityRunResult] = {}
    pending: List[SecurityCase] = []

    for case in selected_cases:
        existing = existing_results.get(case.case_id)
        if resume and existing is not None and existing.status == "completed":
            reusable[case.case_id] = existing
        else:
            pending.append(case)

    return pending, reusable


def execute_cases_serial(
    *,
    cases_to_run: List[SecurityCase],
    config: SecurityConfig,
    manifest_path: Path,
    output_root: Path,
    raw_runs_path: Path,
) -> List[SecurityRunResult]:
    configure_llm_cache(enabled=config.cache_llm, cache_dir=config.cache_dir)
    init_llm(config.target_model)

    results: List[SecurityRunResult] = []
    for case in cases_to_run:
        result = run_case(
            case=case,
            config=config,
            manifest_path=manifest_path,
            output_root=output_root,
        )
        results.append(result)
        append_jsonl(raw_runs_path, result.to_dict())
    return results


def execute_cases_parallel(
    *,
    cases_to_run: List[SecurityCase],
    config: SecurityConfig,
    manifest_path: Path,
    output_root: Path,
    raw_runs_path: Path,
) -> List[SecurityRunResult]:
    results: List[SecurityRunResult] = []
    with ProcessPoolExecutor(max_workers=config.max_workers) as executor:
        futures = {
            executor.submit(
                run_case_worker,
                case.to_dict(),
                config.to_dict(),
                str(manifest_path),
                str(output_root),
            ): case.case_id
            for case in cases_to_run
        }
        for future in as_completed(futures):
            result = deserialize_run_result(future.result())
            results.append(result)
            append_jsonl(raw_runs_path, result.to_dict())
    return results


def main() -> None:
    args = parse_args()
    config = apply_flag_overrides(SecurityConfig.from_name(args.config), args)
    manifest_path = args.cases.resolve()
    governance = resolve_run_governance(
        manifest_path=manifest_path,
        target_model=config.target_model,
        config_name=config.name,
        run_validity=args.run_validity,
        notes=args.notes,
    )
    config.corpus_version = governance["corpus_version"]
    config.direction_map_version = governance["direction_map_version"]
    config.attack_template_version = governance["attack_template_version"]
    config.metric_version = governance["metric_version"]
    config.code_commit = governance["code_commit"]
    config.run_validity = governance["run_validity"]
    config.notes = governance["notes"]
    cases = load_cases(manifest_path)

    for case in cases:
        validate_case_paths(case, manifest_path)

    selected_cases = select_cases(
        cases,
        split=args.split,
        case_ids=args.case_id,
        case_type=args.case_type,
        limit=args.limit,
    )

    if args.dry_run:
        print(
            f"Validated {len(cases)} total cases; {len(selected_cases)} selected for execution."
        )
        return

    if not selected_cases:
        print("No cases selected.")
        return

    output_root = args.output_root.resolve()
    if not config.cache_dir:
        config.cache_dir = str((REPO_ROOT / "runs" / "security" / "llm_cache").resolve())

    output_dir = output_root / config.name
    raw_runs_path = output_dir / "raw_runs.jsonl"
    existing_results = load_existing_results(raw_runs_path)
    pending_cases, reusable_results = plan_case_execution(
        selected_cases,
        existing_results,
        resume=config.resume,
    )

    executed_results: List[SecurityRunResult] = []
    case_lookup: Dict[str, SecurityCase] = {case.case_id: case for case in cases}

    if pending_cases:
        if config.max_workers > 1 and len(pending_cases) > 1:
            executed_results = execute_cases_parallel(
                cases_to_run=pending_cases,
                config=config,
                manifest_path=manifest_path,
                output_root=output_root,
                raw_runs_path=raw_runs_path,
            )
        else:
            executed_results = execute_cases_serial(
                cases_to_run=pending_cases,
                config=config,
                manifest_path=manifest_path,
                output_root=output_root,
                raw_runs_path=raw_runs_path,
            )

    latest_results: Dict[str, SecurityRunResult] = dict(reusable_results)
    for result in executed_results:
        latest_results[result.case_id] = result

    summary_results = [
        latest_results[case.case_id]
        for case in selected_cases
        if case.case_id in latest_results
    ]
    summary = summarize_results(summary_results, case_lookup)
    summary_path = output_dir / "summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    write_summary_markdown(summary, output_dir / "summary.md")

    print(
        f"Selected {len(selected_cases)} cases with config '{config.name}': "
        f"executed {len(executed_results)}, reused {len(reusable_results)}. "
        f"Summary written to {summary_path}."
    )


if __name__ == "__main__":
    main()
