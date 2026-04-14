"""
Governance helpers for benchmark versioning and experiment metadata.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterable

from .attacks import ATTACK_TEMPLATE_VERSION
from .metrics import METRIC_VERSION
from .runtime import REPO_ROOT


DEFAULT_RUN_VALIDITY = "benchmark_candidate"
RUN_VALIDITY_CHOICES = {
    "benchmark_candidate",
    "historical_exploration",
    "sanity_check",
    "invalidated",
    "final_evidence",
}

DATASET_METADATA_FILENAME = "benchmark_metadata.json"


def short_sha256(parts: Iterable[bytes], *, prefix: str) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(part)
    return f"{prefix}-{digest.hexdigest()[:12]}"


def compute_file_version(path: Path, *, prefix: str) -> str:
    return short_sha256([path.read_bytes()], prefix=prefix)


def compute_dataset_corpus_version(dataset_root: Path) -> str:
    files = []
    for path in sorted(dataset_root.rglob("*")):
        if path.is_file() and path.name != DATASET_METADATA_FILENAME:
            files.append(path)
    parts = []
    for path in files:
        parts.append(path.relative_to(dataset_root).as_posix().encode("utf-8"))
        parts.append(b"\0")
        parts.append(path.read_bytes())
        parts.append(b"\0")
    return short_sha256(parts, prefix="corpus")


def get_code_commit(*, repo_root: Path = REPO_ROOT) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return "unknown"
    return result.stdout.strip() or "unknown"


def dataset_root_for_manifest(manifest_path: Path) -> Path:
    return manifest_path.resolve().parent


def dataset_metadata_path(dataset_root: Path) -> Path:
    return dataset_root / DATASET_METADATA_FILENAME


def load_dataset_metadata(dataset_root: Path) -> Dict[str, Any]:
    metadata_path = dataset_metadata_path(dataset_root)
    if not metadata_path.exists():
        return {}
    return json.loads(metadata_path.read_text(encoding="utf-8"))


def write_dataset_metadata(dataset_root: Path, payload: Dict[str, Any]) -> Path:
    metadata_path = dataset_metadata_path(dataset_root)
    metadata_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return metadata_path


def build_dataset_metadata(
    *,
    dataset_root: Path,
    seed_source: str,
    tickers: list[str],
    scenarios_per_ticker: int,
    bundle_size: int,
    pilot_scenarios_per_ticker: int,
    mongo_limit: int,
    direction_map_path: Path | None,
    notes: str | None = None,
) -> Dict[str, Any]:
    direction_map_version = (
        compute_file_version(direction_map_path, prefix="direction-map")
        if direction_map_path is not None and direction_map_path.exists()
        else None
    )
    direction_map_ref = (
        direction_map_path.resolve().relative_to(REPO_ROOT).as_posix()
        if direction_map_path is not None and direction_map_path.exists()
        else None
    )
    corpus_version = compute_dataset_corpus_version(dataset_root)
    return {
        "corpus_version": corpus_version,
        "direction_map_ref": direction_map_ref,
        "direction_map_version": direction_map_version,
        "attack_template_version": ATTACK_TEMPLATE_VERSION,
        "metric_version": METRIC_VERSION,
        "code_commit": get_code_commit(),
        "seed_source": seed_source,
        "tickers": tickers,
        "scenarios_per_ticker": scenarios_per_ticker,
        "bundle_size": bundle_size,
        "pilot_scenarios_per_ticker": pilot_scenarios_per_ticker,
        "mongo_limit": mongo_limit,
        "notes": notes or "",
    }


def resolve_run_governance(
    *,
    manifest_path: Path,
    target_model: str,
    config_name: str,
    run_validity: str,
    notes: str | None = None,
) -> Dict[str, Any]:
    dataset_root = dataset_root_for_manifest(manifest_path)
    dataset_metadata = load_dataset_metadata(dataset_root)
    governance = {
        "corpus_version": dataset_metadata.get(
            "corpus_version",
            compute_dataset_corpus_version(dataset_root),
        ),
        "direction_map_version": dataset_metadata.get("direction_map_version", "unknown"),
        "attack_template_version": dataset_metadata.get(
            "attack_template_version",
            ATTACK_TEMPLATE_VERSION,
        ),
        "metric_version": dataset_metadata.get("metric_version", METRIC_VERSION),
        "target_model": target_model,
        "config_name": config_name,
        "code_commit": get_code_commit(),
        "run_validity": run_validity,
        "notes": notes or "",
    }
    return governance
