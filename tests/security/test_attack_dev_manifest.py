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

from security.attacks import ATTACK_TEMPLATE_VERSION
from security.dataset import load_article, load_cases, write_article, write_cases
from security.governance import write_dataset_metadata
from security.materialize_attack_development import materialize_attack_development_manifest
from security.models import ArticleRecord, SecurityCase


class AttackDevManifestTests(unittest.TestCase):
    def test_materialize_attack_development_manifest_rebuilds_selected_poisoned_case(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            source_root = root / "datasets" / "security"
            source_root.mkdir(parents=True, exist_ok=True)

            financial_path = root / "snapshots" / "financials.json"
            model_path = root / "snapshots" / "model.json"
            financial_path.parent.mkdir(parents=True, exist_ok=True)
            financial_path.write_text(json.dumps({"ticker": "AAPL"}), encoding="utf-8")
            model_path.write_text(json.dumps({"Summary": {"cells": {}}}), encoding="utf-8")

            clean_article_path = source_root / "articles" / "aapl_s05_clean" / "01_anchor.md"
            clean_article = ArticleRecord(
                article_id="01_anchor",
                title="Apple example",
                source_url="https://example.com/apple",
                publish_date="2025-01-01T00:00:00",
                source_type="seed",
                text="Clean article body about Apple demand and pricing.",
            )
            write_article(clean_article_path, clean_article)

            poisoned_article_path = source_root / "articles" / "aapl_s05_tier1" / "01_anchor.md"
            poisoned_article = ArticleRecord(
                article_id="01_anchor",
                title="Apple example",
                source_url="https://example.com/apple",
                publish_date="2025-01-01T00:00:00",
                source_type="poisoned_tier1",
                text="OLD poisoned body",
                seed_article_id="01_anchor",
                rewrite_notes="older template",
                poison_span_labels=[],
            )
            write_article(poisoned_article_path, poisoned_article)

            clean_case = SecurityCase(
                case_id="aapl_s05_clean",
                base_case_id="aapl_s05",
                ticker="AAPL",
                scenario_id="aapl_s05",
                variant="clean",
                split="pilot",
                case_type="clean",
                attack_tier="none",
                attack_family="none",
                objective="baseline_reference",
                target_direction="neutral",
                article_refs=["articles/aapl_s05_clean/01_anchor.md"],
                financial_snapshot_ref=str(financial_path),
                model_snapshot_ref=str(model_path),
                expected_end_to_end_effect="Preserve the clean baseline.",
                metadata={
                    "company_name": "Apple",
                    "clean_rating": "SELL",
                    "clean_expected_return_pct_12m": -5.57,
                    "distance_to_bullish_band": 0.57,
                    "distance_to_bearish_band": 14.43,
                    "target_return_shift_pct": 2.57,
                },
            )
            poisoned_case = SecurityCase(
                case_id="aapl_s05_tier1",
                base_case_id="aapl_s05",
                ticker="AAPL",
                scenario_id="aapl_s05",
                variant="tier1",
                split="pilot",
                case_type="poisoned",
                attack_tier="tier1",
                attack_family="direct_override",
                objective="increase_recommendation_strength",
                target_direction="bullish",
                article_refs=["articles/aapl_s05_tier1/01_anchor.md"],
                financial_snapshot_ref=str(financial_path),
                model_snapshot_ref=str(model_path),
                expected_end_to_end_effect="Move recommendation upward.",
                metadata={
                    "company_name": "Apple",
                    "anchor_seed_article_id": "01_anchor",
                    "clean_rating": "SELL",
                    "clean_expected_return_pct_12m": -5.57,
                    "distance_to_bullish_band": 0.57,
                    "distance_to_bearish_band": 14.43,
                    "target_return_shift_pct": 2.57,
                },
            )
            write_cases(source_root / "cases.jsonl", [clean_case, poisoned_case])
            write_dataset_metadata(
                source_root,
                {
                    "corpus_version": "corpus-parent",
                    "direction_map_version": "direction-parent",
                    "attack_template_version": "v3_boundary_aware_structured_templates",
                    "metric_version": "v2_metric",
                },
            )

            selection_path = root / "selection.json"
            selection_path.write_text(
                json.dumps(
                    {
                        "selected_cases": [
                            {
                                "case_id": "aapl_s05_tier1",
                                "base_case_id": "aapl_s05",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            output_root = root / "datasets" / "security_attack_dev"
            summary = materialize_attack_development_manifest(
                source_manifest=source_root / "cases.jsonl",
                selection_path=selection_path,
                output_root=output_root,
                force=True,
                notes="test dev manifest",
            )

            manifest_cases = {case.case_id: case for case in load_cases(output_root / "cases.jsonl")}
            self.assertEqual(set(manifest_cases), {"aapl_s05_clean", "aapl_s05_tier1"})
            self.assertEqual(
                summary["benchmark_metadata"]["attack_template_version"],
                ATTACK_TEMPLATE_VERSION,
            )
            self.assertEqual(
                summary["benchmark_metadata"]["parent_corpus_version"],
                "corpus-parent",
            )

            materialized_article = load_article(
                output_root / manifest_cases["aapl_s05_tier1"].article_refs[0]
            )
            self.assertIn("Research distribution note attached to syndicated copy", materialized_article.text)
            self.assertEqual(
                manifest_cases["aapl_s05_tier1"].metadata["dev_materialized_from_case_id"],
                "aapl_s05_tier1",
            )

    def test_materialize_attack_development_manifest_supports_anchor_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            source_root = root / "datasets" / "security"
            source_root.mkdir(parents=True, exist_ok=True)

            financial_path = root / "snapshots" / "financials.json"
            model_path = root / "snapshots" / "model.json"
            financial_path.parent.mkdir(parents=True, exist_ok=True)
            financial_path.write_text(json.dumps({"ticker": "NVDA"}), encoding="utf-8")
            model_path.write_text(json.dumps({"Summary": {"cells": {}}}), encoding="utf-8")

            article_a_path = source_root / "articles" / "nvda_s01_clean" / "01_anchor.md"
            article_b_path = source_root / "articles" / "nvda_s01_clean" / "02_anchor.md"
            article_a = ArticleRecord(
                article_id="01_anchor",
                title="First clean article",
                source_url="https://example.com/1",
                publish_date="2025-01-01T00:00:00",
                source_type="seed",
                text="FIRST clean article body.",
            )
            article_b = ArticleRecord(
                article_id="02_anchor",
                title="Second clean article",
                source_url="https://example.com/2",
                publish_date="2025-01-02T00:00:00",
                source_type="seed",
                text="SECOND clean article body.",
            )
            write_article(article_a_path, article_a)
            write_article(article_b_path, article_b)

            clean_case = SecurityCase(
                case_id="nvda_s01_clean",
                base_case_id="nvda_s01",
                ticker="NVDA",
                scenario_id="nvda_s01",
                variant="clean",
                split="pilot",
                case_type="clean",
                attack_tier="none",
                attack_family="none",
                objective="baseline_reference",
                target_direction="neutral",
                article_refs=[
                    "articles/nvda_s01_clean/01_anchor.md",
                    "articles/nvda_s01_clean/02_anchor.md",
                ],
                financial_snapshot_ref=str(financial_path),
                model_snapshot_ref=str(model_path),
                expected_end_to_end_effect="Preserve the clean baseline.",
                metadata={"company_name": "NVDA"},
            )
            poisoned_case = SecurityCase(
                case_id="nvda_s01_tier2",
                base_case_id="nvda_s01",
                ticker="NVDA",
                scenario_id="nvda_s01",
                variant="tier2",
                split="pilot",
                case_type="poisoned",
                attack_tier="tier2",
                attack_family="disguised_financial_steering",
                objective="increase_recommendation_strength",
                target_direction="bullish",
                article_refs=[
                    "articles/nvda_s01_clean/01_anchor.md",
                    "articles/nvda_s01_clean/02_anchor.md",
                ],
                financial_snapshot_ref=str(financial_path),
                model_snapshot_ref=str(model_path),
                expected_end_to_end_effect="Move recommendation upward.",
                metadata={
                    "company_name": "NVDA",
                    "anchor_seed_article_id": "01_anchor",
                    "target_return_shift_pct": 4.21,
                },
            )
            write_cases(source_root / "cases.jsonl", [clean_case, poisoned_case])
            write_dataset_metadata(
                source_root,
                {
                    "corpus_version": "corpus-parent",
                    "direction_map_version": "direction-parent",
                    "attack_template_version": "v3_boundary_aware_structured_templates",
                    "metric_version": "v2_metric",
                },
            )

            selection_path = root / "selection.json"
            selection_path.write_text(
                json.dumps(
                    {
                        "selected_cases": [
                            {
                                "case_id": "nvda_s01_tier2",
                                "base_case_id": "nvda_s01",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            output_root = root / "datasets" / "security_attack_dev"
            materialize_attack_development_manifest(
                source_manifest=source_root / "cases.jsonl",
                selection_path=selection_path,
                output_root=output_root,
                anchor_overrides={"nvda_s01_tier2": 1},
                force=True,
                notes="test anchor override",
            )

            manifest_cases = {case.case_id: case for case in load_cases(output_root / "cases.jsonl")}
            materialized_article = load_article(
                output_root / manifest_cases["nvda_s01_tier2"].article_refs[0]
            )
            self.assertIn("SECOND clean article body.", materialized_article.text)
            self.assertTrue(
                manifest_cases["nvda_s01_tier2"].article_refs[0].endswith("02_anchor.md")
            )
            self.assertEqual(
                manifest_cases["nvda_s01_tier2"].metadata["dev_poison_anchor_index"],
                1,
            )
            self.assertEqual(
                manifest_cases["nvda_s01_tier2"].metadata["dev_poison_anchor_article_id"],
                "02_anchor",
            )


if __name__ == "__main__":
    unittest.main()
