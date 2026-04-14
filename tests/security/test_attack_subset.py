from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from security.models import SecurityCase
from security.select_attack_development import select_attack_development_cases


def make_case(case_id: str, ticker: str, tier: str, shift: float) -> SecurityCase:
    scenario_id = case_id.rsplit("_", 1)[0]
    return SecurityCase(
        case_id=case_id,
        base_case_id=scenario_id,
        ticker=ticker,
        scenario_id=scenario_id,
        variant=tier,
        split="pilot",
        case_type="poisoned",
        attack_tier=tier,
        attack_family=tier,
        objective="increase_recommendation_strength",
        target_direction="bullish",
        article_refs=["articles/demo/01.md"],
        financial_snapshot_ref="data/demo_financial.json",
        model_snapshot_ref="data/demo_model.json",
        expected_end_to_end_effect="Move recommendation upward.",
        metadata={
            "target_return_shift_pct": shift,
            "clean_rating": "SELL",
        },
    )


class AttackSubsetSelectionTests(unittest.TestCase):
    def test_selection_preserves_tier_coverage(self) -> None:
        cases = [
            make_case("aapl_s01_tier1", "AAPL", "tier1", 4.0),
            make_case("aapl_s01_tier2", "AAPL", "tier2", 4.0),
            make_case("aapl_s01_tier3", "AAPL", "tier3", 4.0),
            make_case("meta_s01_tier2", "META", "tier2", 4.5),
            make_case("meta_s01_tier3", "META", "tier3", 4.5),
            make_case("nvda_s01_tier1", "NVDA", "tier1", 5.0),
            make_case("nvda_s01_tier2", "NVDA", "tier2", 5.0),
            make_case("nvda_s01_tier3", "NVDA", "tier3", 5.0),
        ]
        selection = select_attack_development_cases(cases, total_cases=6, max_target_shift=8.0)
        tiers = [row["attack_tier"] for row in selection]
        tickers = {row["ticker"] for row in selection}
        self.assertGreaterEqual(tiers.count("tier1"), 1)
        self.assertGreaterEqual(tiers.count("tier2"), 2)
        self.assertGreaterEqual(tiers.count("tier3"), 2)
        self.assertGreaterEqual(len(tickers), 2)

    def test_selection_replaces_overconcentrated_ticker(self) -> None:
        cases = [
            make_case("aapl_s01_tier1", "AAPL", "tier1", 3.6),
            make_case("aapl_s02_tier1", "AAPL", "tier1", 3.7),
            make_case("aapl_s01_tier2", "AAPL", "tier2", 3.6),
            make_case("aapl_s02_tier2", "AAPL", "tier2", 3.7),
            make_case("aapl_s01_tier3", "AAPL", "tier3", 3.6),
            make_case("aapl_s02_tier3", "AAPL", "tier3", 3.7),
            make_case("meta_s01_tier1", "META", "tier1", 5.0),
            make_case("meta_s01_tier2", "META", "tier2", 5.0),
            make_case("meta_s01_tier3", "META", "tier3", 5.0),
        ]
        selection = select_attack_development_cases(cases, total_cases=6, max_target_shift=8.0)
        tickers = {row["ticker"] for row in selection}
        self.assertIn("META", tickers)


if __name__ == "__main__":
    unittest.main()
