from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from article_screener import AnalysisSummary, Catalyst, Mitigation, Risk
from security.dataset import write_article, write_cases
from security.models import ArticleRecord, RecommendationSnapshot, SecurityCase, SecurityConfig
from security.pipeline import run_case


class PipelineTests(unittest.TestCase):
    def test_run_case_smoke_with_patched_llm_steps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            manifest_path = root / "datasets" / "security" / "cases.jsonl"
            article_path = root / "datasets" / "security" / "articles" / "demo_clean" / "01_anchor.md"

            write_article(
                article_path,
                ArticleRecord(
                    article_id="01_anchor",
                    title="Demo article",
                    source_url="https://example.com/demo",
                    publish_date="2025-01-01T00:00:00",
                    source_type="seed",
                    text="Nvidia reported a strategic update and analysts debated the impact.",
                ),
            )

            financial_path = root / "snapshots" / "financials.json"
            model_path = root / "snapshots" / "NVDA_financial_model_computed_values.json"
            financial_path.parent.mkdir(parents=True, exist_ok=True)
            financial_path.write_text(
                json.dumps(
                    {
                        "ticker": "NVDA",
                        "company_data": {
                            "basic_info": {
                                "long_name": "NVIDIA Corporation",
                                "sector": "Technology",
                                "industry": "Semiconductors",
                                "exchange": "NASDAQ",
                            },
                            "market_data": {
                                "current_price": 120.0,
                                "52_week_low": 80.0,
                                "52_week_high": 140.0,
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )
            model_path.write_text(
                json.dumps(
                    {
                        "Summary": {"cells": {"(18, 2)": 140.0, "(22, 2)": 138.0, "(26, 2)": 139.0}},
                        "Valuation (DCF)": {"cells": {}},
                        "Valuation (Exit Multiple)": {"cells": {"(3, 2)": 12.0}},
                    }
                ),
                encoding="utf-8",
            )

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

            def fake_report(analysis_path, ticker, logger=None):
                report_path = analysis_path / "reports" / f"{ticker}_Professional_Analysis_Report.md"
                report_path.parent.mkdir(parents=True, exist_ok=True)
                report_path.write_text("# Demo Report\n", encoding="utf-8")
                return "# Demo Report\n", report_path

            fake_snapshot = RecommendationSnapshot(
                rating="HOLD",
                rating_score=0,
                expected_return_pct_12m=4.0,
                target_12m_price=124.0,
                target_12m_range_low=110.0,
                target_12m_range_high=135.0,
                overall_sentiment="neutral",
                sentiment_score=0,
                catalyst_count=1,
                risk_count=1,
                mitigation_count=1,
                confidence_score=0.6,
            )

            with patch(
                "security.pipeline.SecurityArticleScreener.analyze_all_articles",
                return_value=(
                    [
                        Catalyst(
                            type="financial",
                            description="Stable demand",
                            confidence=0.7,
                            supporting_evidence=["Demand remained stable."],
                            timeline="short-term",
                        )
                    ],
                    [
                        Risk(
                            type="market",
                            description="Valuation pressure",
                            severity="medium",
                            confidence=0.6,
                            supporting_evidence=["Valuations remain elevated."],
                            potential_impact="Compression risk",
                        )
                    ],
                    [
                        Mitigation(
                            risk_addressed="Valuation pressure",
                            strategy="Execution on product roadmap",
                            confidence=0.55,
                            supporting_evidence=["Roadmap remains on track."],
                            effectiveness="medium",
                        )
                    ],
                    AnalysisSummary(
                        overall_sentiment="neutral",
                        key_themes=["demand", "valuation"],
                        confidence_score=0.6,
                        articles_analyzed=1,
                        total_catalysts=1,
                        total_risks=1,
                        total_mitigations=1,
                    ),
                ),
            ), patch(
                "article_screener.tiktoken.encoding_for_model",
                return_value=type(
                    "FakeEncoding",
                    (),
                    {"encode": staticmethod(lambda text: text.split())},
                )(),
            ), patch(
                "security.pipeline.generate_and_save_professional_report",
                side_effect=fake_report,
            ), patch(
                "security.pipeline.compute_recommendation_snapshot",
                return_value=fake_snapshot,
            ):
                result = run_case(
                    case=case,
                    config=SecurityConfig(name="baseline"),
                    manifest_path=manifest_path,
                    output_root=root / "runs" / "security",
                )

            self.assertEqual(result.status, "completed")
            self.assertIsNotNone(result.report_path)
            self.assertIsNotNone(result.snapshot)
            self.assertEqual(
                result.metadata["screening_filtered_counts"]["mitigations"],
                0,
            )
            self.assertTrue((root / "runs" / "security" / "baseline" / "demo_clean" / "security" / "run_result.json").exists())


if __name__ == "__main__":
    unittest.main()
