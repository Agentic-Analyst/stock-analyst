"""
Disk-backed cache for deterministic benchmark LLM calls.

The security benchmark frequently replays identical prompts while iterating on
downstream scoring, defenses, and dataset construction. A simple cache keeps
that iteration loop cheap without changing the benchmark codepaths.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple


_CACHE_ENABLED = False
_CACHE_DIR: Optional[Path] = None


def configure_llm_cache(*, enabled: bool, cache_dir: str | Path | None) -> None:
    """Configure the process-local LLM cache runtime."""
    global _CACHE_ENABLED, _CACHE_DIR
    _CACHE_ENABLED = enabled
    _CACHE_DIR = Path(cache_dir).resolve() if enabled and cache_dir else None
    if _CACHE_DIR is not None:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)


def llm_cache_enabled() -> bool:
    return _CACHE_ENABLED and _CACHE_DIR is not None


def cache_key_for_request(
    *,
    model_name: str,
    messages: List[Dict],
    temperature: float,
) -> str:
    payload = {
        "model_name": model_name,
        "messages": messages,
        "temperature": temperature,
    }
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def get_cached_llm_response(
    *,
    model_name: str,
    messages: List[Dict],
    temperature: float,
) -> Optional[Tuple[str, float]]:
    """Return a cached response when available."""
    if not llm_cache_enabled():
        return None

    cache_path = _CACHE_DIR / f"{cache_key_for_request(model_name=model_name, messages=messages, temperature=temperature)}.json"  # type: ignore[operator]
    if not cache_path.exists():
        return None

    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    return str(payload["response_text"]), 0.0


def store_cached_llm_response(
    *,
    model_name: str,
    messages: List[Dict],
    temperature: float,
    response_text: str,
    cost: float,
) -> None:
    """Store one LLM response in the on-disk cache."""
    if not llm_cache_enabled():
        return

    cache_path = _CACHE_DIR / f"{cache_key_for_request(model_name=model_name, messages=messages, temperature=temperature)}.json"  # type: ignore[operator]
    payload = {
        "model_name": model_name,
        "temperature": temperature,
        "response_text": response_text,
        "original_cost": cost,
    }

    fd, tmp_path = tempfile.mkstemp(
        prefix=f"{cache_path.stem}.",
        suffix=".tmp",
        dir=str(cache_path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False)
        Path(tmp_path).replace(cache_path)
    finally:
        tmp_file = Path(tmp_path)
        if tmp_file.exists():
            tmp_file.unlink()
