"""Regression guards for documented dependency vulnerability exceptions."""

from pathlib import Path

import newspaper


ROOT = Path(__file__).resolve().parents[1]
AFFECTED_NLTK_API_NAMES = (
    "TransitionParser",
    "AveragedPerceptron",
    "PerceptronTagger",
    "save_maxent_params",
)


def _affected_api_references(root: Path):
    return [
        f"{path}:{api_name}"
        for path in root.rglob("*.py")
        for api_name in AFFECTED_NLTK_API_NAMES
        if api_name in path.read_text(encoding="utf-8", errors="ignore")
    ]


def test_nltk_model_path_advisory_is_not_reachable():
    """Keep CVE-2026-81726 unreachable while no patched NLTK exists."""

    newspaper_root = Path(newspaper.__file__).resolve().parent

    assert _affected_api_references(ROOT / "src") == []
    assert _affected_api_references(newspaper_root) == []
