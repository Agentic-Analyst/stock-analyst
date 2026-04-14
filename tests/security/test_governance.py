from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from security.governance import (
    build_dataset_metadata,
    compute_dataset_corpus_version,
    load_dataset_metadata,
    write_dataset_metadata,
)
from security.metrics import summarize_results
from security.models import RecommendationSnapshot, SecurityCase, SecurityRunResult


class GovernanceTests(unittest.TestCase):
    def test_dataset_metadata_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            dataset_root = Path(tmp_dir) / "datasets" / "security"
            dataset_root.mkdir(parents=True, exist_ok=True)
            (dataset_root / "cases.jsonl").write_text("{}\n", encoding="utf-8")
            metadata = build_dataset_metadata(
                dataset_root=dataset_root,
                seed_source="mongo",
                tickers=["AAPL", "META"],
                scenarios_per_ticker=5,
                bundle_size=4,
                pilot_scenarios_per_ticker=1,
                mongo_limit=80,
                direction_map_path=None,
                notes="test-build",
            )
            write_dataset_metadata(dataset_root, metadata)
            loaded = load_dataset_metadata(dataset_root)
            self.assertEqual(loaded["seed_source"], "mongo")
            self.assertEqual(loaded["notes"], "test-build")
            self.assertTrue(loaded["corpus_version"].startswith("corpus-"))

    def test_summary_includes_benchmark_metadata(self) -> None:
        clean_case = SecurityCase(
            case_id="demo_clean",
            base_case_id="demo_s01",
            ticker="NVDA",
            scenario_id="demo_s01",
            variant="clean",
            split="pilot",
            case_type="clean",
            attack_tier="none",
            attack_family="none",
            objective="baseline_reference",
            target_direction="neutral",
            article_refs=["articles/demo_clean/01.md"],
            financial_snapshot_ref="data/demo_financial.json",
            model_snapshot_ref="data/demo_model.json",
            expected_end_to_end_effect="Preserve the clean baseline.",
        )
        clean_run = SecurityRunResult(
            case_id="demo_clean",
            base_case_id="demo_s01",
            ticker="NVDA",
            config_name="baseline",
            split="pilot",
            case_type="clean",
            attack_tier="none",
            attack_family="none",
            objective="baseline_reference",
            target_direction="neutral",
            status="completed",
            run_id="run-clean",
            started_at="2026-01-01T00:00:00Z",
            completed_at="2026-01-01T00:00:02Z",
            duration_seconds=2.0,
            blocked=False,
            article_count=4,
            output_dir="runs/demo_clean",
            corpus_version="corpus-demo",
            direction_map_version="direction-demo",
            attack_template_version="attack-v3",
            metric_version="metric-v2",
            target_model="gpt-4o-mini",
            code_commit="abc123",
            run_validity="sanity_check",
            notes="demo-note",
            snapshot=RecommendationSnapshot(
                rating="HOLD",
                rating_score=0,
                expected_return_pct_12m=4.0,
                target_12m_price=120.0,
                target_12m_range_low=100.0,
                target_12m_range_high=130.0,
                overall_sentiment="neutral",
                sentiment_score=0,
                catalyst_count=2,
                risk_count=2,
                mitigation_count=1,
                confidence_score=0.55,
            ),
        )
        summary = summarize_results([clean_run], {clean_case.case_id: clean_case})
        self.assertEqual(summary["benchmark_metadata"]["corpus_version"], "corpus-demo")
        self.assertEqual(summary["benchmark_metadata"]["run_validity"], "sanity_check")


if __name__ == "__main__":
    unittest.main()
