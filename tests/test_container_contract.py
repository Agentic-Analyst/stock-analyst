"""Container-build contracts that unit tests cannot otherwise observe."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_revision_metadata_does_not_invalidate_dependency_layer():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert dockerfile.index("COPY requirements.txt requirements.lock") < dockerfile.index(
        "ARG VYNN_SOURCE_REVISION"
    )
