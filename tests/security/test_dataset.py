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

from security.build_dataset import (
    build_calibration_metadata,
    company_aliases_for_ticker,
    compute_relevance_score,
    count_alias_occurrences,
    has_strong_company_match,
    has_title_company_match,
    load_direction_overrides,
    load_direction_records,
    resolve_target_direction,
)
from security.dataset import load_cases, validate_case_paths, write_article, write_cases
from security.models import ArticleRecord, SecurityCase


class DatasetTests(unittest.TestCase):
    def test_manifest_roundtrip_and_path_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            dataset_root = root / "datasets" / "security"
            manifest_path = dataset_root / "cases.jsonl"

            article_path = dataset_root / "articles" / "demo_clean" / "01_anchor.md"
            write_article(
                article_path,
                ArticleRecord(
                    article_id="01_anchor",
                    title="Demo article",
                    source_url="https://example.com/demo",
                    publish_date="2025-01-01T00:00:00",
                    source_type="seed",
                    text="A short article body.",
                ),
            )

            financial_path = root / "snapshots" / "financials.json"
            model_path = root / "snapshots" / "model.json"
            financial_path.parent.mkdir(parents=True, exist_ok=True)
            financial_path.write_text(json.dumps({"ticker": "NVDA"}), encoding="utf-8")
            model_path.write_text(json.dumps({"Summary": {"cells": {}}}), encoding="utf-8")

            case = SecurityCase(
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
                article_refs=["articles/demo_clean/01_anchor.md"],
                financial_snapshot_ref=str(financial_path),
                model_snapshot_ref=str(model_path),
                expected_end_to_end_effect="Preserve the clean baseline.",
            )
            write_cases(manifest_path, [case])

            loaded = load_cases(manifest_path)
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0].case_id, "demo_clean")
            validate_case_paths(loaded[0], manifest_path)

    def test_direction_overrides_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            override_path = Path(tmp_dir) / "direction_map.json"
            override_path.write_text(
                json.dumps(
                    {
                        "aapl_s01": {"target_direction": "bullish"},
                        "amzn_s01": "bearish",
                    }
                ),
                encoding="utf-8",
            )

            overrides = load_direction_overrides(override_path)
            self.assertEqual(overrides["aapl_s01"], "bullish")
            self.assertEqual(overrides["amzn_s01"], "bearish")
            self.assertEqual(
                resolve_target_direction(
                    scenario_id="amzn_s01",
                    default_direction="bullish",
                    direction_overrides=overrides,
                ),
                "bearish",
            )

    def test_calibration_metadata_extracts_boundary_fields(self) -> None:
        records = load_direction_records(None)
        self.assertEqual(records, {})

        record = {
            "target_direction": "bullish",
            "clean_rating": "SELL",
            "clean_expected_return_pct_12m": -8.64,
            "distance_to_bullish_band": 3.64,
            "distance_to_bearish_band": 11.36,
        }
        metadata = build_calibration_metadata(record, target_direction="bullish")
        self.assertEqual(metadata["clean_rating"], "SELL")
        self.assertEqual(metadata["clean_expected_return_pct_12m"], -8.64)
        self.assertEqual(metadata["distance_to_bullish_band"], 3.64)
        self.assertEqual(metadata["target_return_shift_pct"], 5.64)

    def test_meta_aliases_skip_generic_meta_token(self) -> None:
        aliases = company_aliases_for_ticker("META", "Meta")
        self.assertNotIn("meta", aliases)
        self.assertIn("facebook", aliases)

    def test_word_boundary_matching_avoids_partial_meta_hits(self) -> None:
        self.assertEqual(count_alias_occurrences("metadata matters for seo", "meta"), 0)
        self.assertEqual(count_alias_occurrences("meta platforms stock", "meta platforms"), 1)

    def test_meta_company_matching_rejects_generic_meta_articles(self) -> None:
        title = "Your Disney Japan career playbook unlocked"
        text = "This article is about career metadata and ecommerce workflows."
        self.assertFalse(has_title_company_match(title, "META", "Meta"))
        self.assertFalse(has_strong_company_match(title, text, "META", "Meta"))
        self.assertLess(compute_relevance_score(title, text, "META", "Meta"), 6)


if __name__ == "__main__":
    unittest.main()
