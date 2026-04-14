"""
Shared runtime helpers for the security benchmark.

The legacy codebase expects `src/` to be present on `sys.path` so that modules
like `config`, `logger`, and `article_screener` can be imported without the
`src.` prefix. Security modules reuse those entrypoints, so we normalize the
runtime path here.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


def load_project_env() -> None:
    """Load the repository `.env` file when python-dotenv is available."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return

    load_dotenv(REPO_ROOT / ".env")

