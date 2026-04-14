from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from recommendation_calculator import RecommendationCalculator
from security.analyze_calculator import (
    build_analysis_payload,
    build_attackability_record,
    load_dev_subset_base_cases,
    load_run_results,
)
from security.dataset import load_cases


class CalculatorAnalysisTests(unittest.TestCase):
    def test_risk_severity_critical_is_not_stronger_than_high(self) -> None:
        calculator = RecommendationCalculator()
        high_risk = [
            {
                "severity": "high",
                "likelihood": "high",
                "confidence": 1.0,
            }
        ]
        critical_risk = [
            {
                "severity": "critical",
                "likelihood": "high",
                "confidence": 1.0,
            }
        ]

        self.assertGreater(
            calculator.estimate_risk_impact(high_risk),
            calculator.estimate_risk_impact(critical_risk),
        )

    def test_risk_likelihood_low_maps_like_medium_today(self) -> None:
        calculator = RecommendationCalculator()
        low_likelihood = [
            {
                "severity": "high",
                "likelihood": "low",
                "confidence": 1.0,
            }
        ]
        medium_likelihood = [
            {
                "severity": "high",
                "likelihood": "medium",
                "confidence": 1.0,
            }
        ]

        self.assertEqual(
            calculator.estimate_risk_impact(low_likelihood),
            calculator.estimate_risk_impact(medium_likelihood),
        )

    def test_clean_attackability_reproduces_existing_snapshot(self) -> None:
        runs_path = REPO_ROOT / "runs" / "security-openai-clean-reset-v2" / "baseline" / "raw_runs.jsonl"
        cases_path = REPO_ROOT / "datasets" / "security" / "cases.jsonl"
        if not runs_path.exists() or not cases_path.exists():
            self.skipTest("Canonical clean reset artifacts are not available")

        results = load_run_results(runs_path)
        cases = {case.case_id: case for case in load_cases(cases_path)}
        run = next(result for result in results if result.case_id == "aapl_s05_clean")
        record = build_attackability_record(cases["aapl_s05_clean"], run)

        self.assertEqual(record.contribution.rating, run.snapshot.rating)
        self.assertAlmostEqual(
            record.contribution.expected_return_pct_12m,
            run.snapshot.expected_return_pct_12m,
            places=2,
        )

    def test_canonical_stage_recommendations_match_calculator_first_plan(self) -> None:
        runs_path = REPO_ROOT / "runs" / "security-openai-clean-reset-v2" / "baseline" / "raw_runs.jsonl"
        cases_path = REPO_ROOT / "datasets" / "security" / "cases.jsonl"
        dev_subset_path = REPO_ROOT / "datasets" / "security" / "attack_development_subset.json"
        if not runs_path.exists() or not cases_path.exists() or not dev_subset_path.exists():
            self.skipTest("Canonical calculator-first inputs are not available")

        results = load_run_results(runs_path)
        cases = {case.case_id: case for case in load_cases(cases_path)}
        dev_subset_base_cases = load_dev_subset_base_cases(dev_subset_path)
        payload = build_analysis_payload(
            results=results,
            cases=cases,
            dev_subset_base_cases=dev_subset_base_cases,
        )

        self.assertEqual(
            payload["stage_recommendations"]["stage1_targets"],
            ["aapl_s05_clean", "aapl_s01_clean", "nvda_s01_clean"],
        )
        self.assertEqual(
            payload["stage_recommendations"]["first_bearish_reentry_case"],
            "meta_s04_clean",
        )

        by_case = {
            record["case_id"]: record
            for record in payload["cases"]
        }
        self.assertEqual(by_case["aapl_s05_clean"]["difficulty"], "easy")
        self.assertEqual(by_case["aapl_s01_clean"]["difficulty"], "easy")
        self.assertEqual(by_case["nvda_s01_clean"]["difficulty"], "moderate")
        self.assertFalse(by_case["amzn_s03_clean"]["attackable_with_single_doc"])


if __name__ == "__main__":
    unittest.main()
