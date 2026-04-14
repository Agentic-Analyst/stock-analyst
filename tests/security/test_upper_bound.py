from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from security.models import CalculatorContribution
from security.upper_bound_study import (
    _build_conclusion,
    _select_strongest_catalyst_index,
    _select_strongest_risk_index,
    _variant_payload,
)


class UpperBoundStudyTests(unittest.TestCase):
    def test_select_strongest_catalyst_prefers_immediate_financial(self) -> None:
        catalysts = [
            {"type": "market", "timeline": "medium-term", "confidence": 0.9},
            {"type": "financial", "timeline": "immediate", "confidence": 0.85},
            {"type": "product", "timeline": "short-term", "confidence": 0.95},
        ]
        self.assertEqual(_select_strongest_catalyst_index(catalysts), 1)

    def test_select_strongest_risk_prefers_high_high(self) -> None:
        risks = [
            {"severity": "medium", "likelihood": "medium", "confidence": 0.9},
            {"severity": "high", "likelihood": "high", "confidence": 0.8},
            {"severity": "high", "likelihood": "medium", "confidence": 0.95},
        ]
        self.assertEqual(_select_strongest_risk_index(risks), 1)

    def test_variant_payload_marks_bearish_cross(self) -> None:
        baseline = CalculatorContribution(
            adj_val_gap_pct=0.0,
            catalyst_score_pct=10.0,
            risk_score_pct=5.0,
            net_catalyst_risk_pct=5.0,
            momentum_score_pct=0.0,
            expected_return_pct_12m=-1.0,
            rating="HOLD",
        )
        candidate = CalculatorContribution(
            adj_val_gap_pct=0.0,
            catalyst_score_pct=8.0,
            risk_score_pct=12.0,
            net_catalyst_risk_pct=-4.0,
            momentum_score_pct=0.0,
            expected_return_pct_12m=-6.0,
            rating="SELL",
        )
        payload = _variant_payload(
            name="demo",
            family="compound",
            plausibility="single_doc_aggressive",
            description="demo",
            baseline=baseline,
            candidate=candidate,
            target_direction="bearish",
        )
        self.assertTrue(payload["crosses_target_band"])
        self.assertGreater(payload["signed_gain_toward_target_pct"], 0)

    def test_build_conclusion_prefers_simplest_crossing_variant(self) -> None:
        conclusion = _build_conclusion(
            target_direction="bearish",
            boundary_distance_pct=4.8,
            crossing_variants=[
                {
                    "name": "extreme_variant",
                    "plausibility": "upper_bound_extreme",
                    "signed_gain_toward_target_pct": 8.0,
                },
                {
                    "name": "aggressive_variant",
                    "plausibility": "single_doc_aggressive",
                    "signed_gain_toward_target_pct": 5.0,
                },
            ],
            best_variant={"name": "extreme_variant", "signed_gain_toward_target_pct": 8.0},
        )
        self.assertIn("aggressive_variant", conclusion)


if __name__ == "__main__":
    unittest.main()
