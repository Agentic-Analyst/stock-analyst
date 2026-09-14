"""Container-build contracts that unit tests cannot otherwise observe."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _locked_versions():
    versions = {}
    for raw in (ROOT / "requirements.lock").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if "==" not in line or line.startswith("#"):
            continue
        name, version = line.split("==", 1)
        versions[name.casefold()] = version
    return versions


def test_revision_metadata_does_not_invalidate_dependency_layer():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert dockerfile.index("COPY requirements.txt requirements.lock") < dockerfile.index(
        "ARG VYNN_SOURCE_REVISION"
    )


def test_runtime_build_tool_is_security_patched():
    version = tuple(map(int, _locked_versions()["setuptools"].split(".")))

    assert version >= (83, 0, 0)
