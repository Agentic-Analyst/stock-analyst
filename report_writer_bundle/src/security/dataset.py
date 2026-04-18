"""
Dataset helpers for the security benchmark.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import yaml

from .models import ArticleRecord, SecurityCase
from .runtime import REPO_ROOT


def resolve_path(path_str: str, base_dir: Optional[Path] = None) -> Path:
    """
    Resolve a manifest path.

    Paths are accepted relative to:
    1. the provided base directory
    2. the repository root
    """
    path = Path(path_str)
    candidates = []
    if path.is_absolute():
        candidates.append(path)
    if base_dir is not None:
        candidates.append((base_dir / path).resolve())
    candidates.append((REPO_ROOT / path).resolve())

    for candidate in candidates:
        if candidate.exists():
            return candidate

    # Fall back to the first meaningful candidate for error reporting.
    return candidates[0]


def load_cases(manifest_path: Path) -> List[SecurityCase]:
    """Load a JSONL manifest of security cases."""
    manifest_path = manifest_path.resolve()
    cases: List[SecurityCase] = []
    with manifest_path.open("r", encoding="utf-8") as handle:
        for line_no, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                case = SecurityCase.from_dict(data)
            except Exception as exc:  # pragma: no cover - wrapped with line number
                raise ValueError(
                    f"Failed to parse {manifest_path}:{line_no}: {exc}"
                ) from exc
            cases.append(case)
    return cases


def write_cases(manifest_path: Path, cases: Iterable[SecurityCase]) -> None:
    """Write a JSONL manifest."""
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with manifest_path.open("w", encoding="utf-8") as handle:
        for case in cases:
            handle.write(json.dumps(case.to_dict(), ensure_ascii=False) + "\n")


def load_article(path: Path) -> ArticleRecord:
    """Load an article markdown file with YAML front matter."""
    content = path.read_text(encoding="utf-8")
    if not content.startswith("---"):
        raise ValueError(f"Expected YAML front matter in {path}")

    end = content.find("\n---", 3)
    if end == -1:
        raise ValueError(f"Could not find closing front matter marker in {path}")

    frontmatter = content[3:end]
    text = content[end + 4 :].lstrip("\n")
    data = yaml.safe_load(frontmatter) or {}
    data["text"] = text
    return ArticleRecord.from_dict(data)


def write_article(path: Path, article: ArticleRecord) -> None:
    """Write an article markdown file with YAML front matter."""
    path.parent.mkdir(parents=True, exist_ok=True)
    frontmatter = yaml.safe_dump(
        article.to_frontmatter_dict(),
        sort_keys=False,
        allow_unicode=True,
    ).strip()
    payload = f"---\n{frontmatter}\n---\n\n{article.text.strip()}\n"
    path.write_text(payload, encoding="utf-8")


def validate_case_paths(case: SecurityCase, manifest_path: Path) -> None:
    """Validate that case refs exist."""
    base_dir = manifest_path.parent
    for ref in case.article_refs:
        path = resolve_path(ref, base_dir=base_dir)
        if not path.exists():
            raise FileNotFoundError(f"{case.case_id} missing article ref: {ref}")

    for ref in [case.financial_snapshot_ref, case.model_snapshot_ref]:
        path = resolve_path(ref, base_dir=base_dir)
        if not path.exists():
            raise FileNotFoundError(f"{case.case_id} missing snapshot ref: {ref}")


def copy_snapshot_file(source: Path, destination: Path) -> Path:
    """Copy a frozen snapshot into the run directory."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return destination


def append_jsonl(path: Path, payload: Dict) -> None:
    """Append one JSON record to a JSONL file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

