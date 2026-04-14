"""
Process-safe case execution helpers for the security benchmark.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from .models import SecurityCase, SecurityConfig, SecurityRunResult
from .pipeline import run_case
from .runtime import load_project_env

load_project_env()

from llms.config import configure_llm_cache, init_llm  # type: ignore  # noqa: E402


def run_case_worker(
    case_payload: Dict[str, Any],
    config_payload: Dict[str, Any],
    manifest_path: str,
    output_root: str,
) -> Dict[str, Any]:
    """Execute one case inside a subprocess and return a JSON-safe payload."""
    case = SecurityCase.from_dict(case_payload)
    config = SecurityConfig(**config_payload)

    configure_llm_cache(enabled=config.cache_llm, cache_dir=config.cache_dir)
    init_llm(config.target_model)

    result = run_case(
        case=case,
        config=config,
        manifest_path=Path(manifest_path),
        output_root=Path(output_root),
    )
    return result.to_dict()


def deserialize_run_result(payload: Dict[str, Any]) -> SecurityRunResult:
    return SecurityRunResult.from_dict(payload)
