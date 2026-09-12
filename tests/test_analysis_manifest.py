import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from analysis_manifest import build_analysis_manifest


def test_manifest_is_stable_and_contains_no_credentials():
    env = {
        "ANALYSIS_MODEL_VERSION": "valuation-v2",
        "ANALYSIS_BACKEND_IMAGE": "worker@sha256:" + "a" * 64,
        "ANALYSIS_LLM_MODEL": "gpt-4o-mini",
        "PEER_COMPS_ENABLED": "true",
        "FINNHUB_API_KEY": "must-not-appear",
        "OPENAI_API_KEY": "must-not-appear-either",
    }
    first = build_analysis_manifest(env)
    second = build_analysis_manifest(dict(reversed(list(env.items()))))

    assert first == second
    assert len(first["configuration_sha256"]) == 64
    assert first["backend_image"].endswith("a" * 64)
    assert "must-not-appear" not in repr(first)


def test_material_configuration_change_changes_the_fingerprint():
    base = {"ANALYSIS_MODEL_VERSION": "v2", "PEER_COMPS_ENABLED": "false"}
    changed = {**base, "PEER_COMPS_ENABLED": "true"}
    assert (build_analysis_manifest(base)["configuration_sha256"] !=
            build_analysis_manifest(changed)["configuration_sha256"])
