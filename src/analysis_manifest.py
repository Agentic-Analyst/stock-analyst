"""Deterministic, credential-free identity for a valuation run."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, Mapping, Optional


TRACKED_ENV = (
    "ANALYSIS_MODEL_VERSION",
    "ANALYSIS_BACKEND_IMAGE",
    "ANALYSIS_LLM_MODEL",
    "OPENAI_GPT_4O_MINI_SNAPSHOT",
    "ANALYST_CONSENSUS_PROVIDER",
    "ANALYST_CONSENSUS_MIN_ANALYSTS",
    "BENZINGA_CONSENSUS_LOOKBACK_DAYS",
    "PEER_COMPS_ENABLED",
    "PEER_COMPS_MAX_PEERS",
    "PEER_COMPS_MIN_SIZE_RATIO",
    "PEER_COMPS_REQUEST_DELAY_SECONDS",
    "NEWS_MAX_AGE_DAYS",
    "NEWS_MIN_FRESH_ARTICLES",
    "FINANCIAL_STATEMENT_MAX_AGE_DAYS",
    "QUARTERLY_STATEMENT_MAX_AGE_DAYS",
    "RISK_FREE_USD",
)


def _file_set_hash(paths) -> Optional[str]:
    digest = hashlib.sha256()
    found = False
    for path in sorted(paths, key=lambda item: str(item)):
        if not path.is_file():
            continue
        found = True
        digest.update(str(path.name).encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest() if found else None


def build_analysis_manifest(environ: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
    source = environ if environ is not None else os.environ
    root = Path(__file__).resolve().parents[1]
    prompt_root = root / "prompts"
    prompt_files = [
        path for path in prompt_root.rglob("*")
        if path.suffix.lower() in {".md", ".txt", ".json", ".yaml", ".yml"}
    ] if prompt_root.exists() else []
    requirements = root / "requirements.lock"
    if not requirements.exists():
        requirements = root / "requirements.txt"
    config = {
        key: str(source[key]).strip()
        for key in TRACKED_ENV if source.get(key) is not None
    }
    identity = {
        "source_revision": str(source.get("VYNN_SOURCE_REVISION") or "unversioned"),
        "model_version": str(source.get("ANALYSIS_MODEL_VERSION") or "unversioned"),
        "backend_image": source.get("ANALYSIS_BACKEND_IMAGE"),
        "llm_model": source.get("ANALYSIS_LLM_MODEL") or "gpt-4o-mini",
        "prompt_set_sha256": _file_set_hash(prompt_files),
        "requirements_sha256": _file_set_hash([requirements]),
        "configuration": config,
    }
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {**identity, "configuration_sha256": hashlib.sha256(encoded).hexdigest()}
