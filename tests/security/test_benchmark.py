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

from security.models import RecommendationSnapshot, SecurityCase, SecurityRunResult
from security.run_benchmark import load_existing_results, plan_case_execution


def make_result(case_id: str, base_case_id: str, *, status: str, rating: str) -> SecurityRunResult:
    score_map = {
        "STRONG SELL": -2,
        "SELL": -1,
        "HOLD": 0,
        "BUY": 1,
        "STRONG BUY": 2,
    }
    return SecurityRunResult(
        case_id=case_id,
        base_case_id=base_case_id,
        ticker="NVDA",
        config_name="baseline",
        split="pilot",
        case_type="clean" if case_id.endswith("clean") else "poisoned",
        attack_tier="none" if case_id.endswith("clean") else "tier1",
        attack_family="none" if case_id.endswith("clean") else "direct_override",
        objective="baseline_reference",
        target_direction="neutral" if case_id.endswith("clean") else "bullish",
        status=status,
        run_id=f"run-{case_id}",
        started_at="2026-01-01T00:00:00Z",
        completed_at="2026-01-01T00:00:02Z",
        duration_seconds=2.0,
        blocked=False,
        article_count=4,
        output_dir=f"runs/{case_id}",
        snapshot=RecommendationSnapshot(
            rating=rating,
            rating_score=score_map[rating],
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


class BenchmarkRunnerTests(unittest.TestCase):
    def test_load_existing_results_keeps_latest_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            raw_runs_path = Path(tmp_dir) / "raw_runs.jsonl"
            first = make_result("demo_clean", "demo_s01", status="completed", rating="HOLD")
            second = make_result("demo_clean", "demo_s01", status="completed", rating="BUY")
            raw_runs_path.write_text(
                json.dumps(first.to_dict()) + "\n" + json.dumps(second.to_dict()) + "\n",
                encoding="utf-8",
            )

            loaded = load_existing_results(raw_runs_path)
            self.assertEqual(loaded["demo_clean"].snapshot.rating, "BUY")

    def test_plan_case_execution_reuses_only_completed_results(self) -> None:
        cases = [
            SecurityCase(
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
            ),
            SecurityCase(
                case_id="demo_tier1",
                base_case_id="demo_s01",
                ticker="NVDA",
                scenario_id="demo_s01",
                variant="tier1",
                split="pilot",
                case_type="poisoned",
                attack_tier="tier1",
                attack_family="direct_override",
                objective="increase_recommendation_strength",
                target_direction="bullish",
                article_refs=["articles/demo_tier1/01.md"],
                financial_snapshot_ref="data/demo_financial.json",
                model_snapshot_ref="data/demo_model.json",
                expected_end_to_end_effect="Become more bullish.",
            ),
        ]
        existing = {
            "demo_clean": make_result("demo_clean", "demo_s01", status="completed", rating="HOLD"),
            "demo_tier1": make_result("demo_tier1", "demo_s01", status="failed", rating="HOLD"),
        }

        pending, reusable = plan_case_execution(cases, existing, resume=True)
        self.assertEqual([case.case_id for case in pending], ["demo_tier1"])
        self.assertEqual(sorted(reusable), ["demo_clean"])


if __name__ == "__main__":
    unittest.main()
