"""
Local end-to-end benchmark pipeline for security cases.
"""

from __future__ import annotations

import json
import shutil
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from .dataset import copy_snapshot_file, load_article, resolve_path
from .defenses import (
    SecurityArticleScreener,
    transform_articles_for_security,
    verify_screening_output,
)
from .metrics import compute_recommendation_snapshot
from .models import SecurityCase, SecurityConfig, SecurityRunResult
from .runtime import load_project_env

load_project_env()

from config import MIN_CONFIDENCE  # type: ignore  # noqa: E402
from logger import setup_logger  # type: ignore  # noqa: E402
from report_agent import generate_and_save_professional_report  # type: ignore  # noqa: E402


def run_case(
    *,
    case: SecurityCase,
    config: SecurityConfig,
    manifest_path: Path,
    output_root: Path,
) -> SecurityRunResult:
    """Execute one clean or poisoned case through the local VYNN path."""
    run_started = time.perf_counter()
    run_id = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    case_output_dir = output_root / config.name / case.case_id
    case_output_dir.mkdir(parents=True, exist_ok=True)

    logger = setup_logger(
        ticker=case.ticker,
        base_path=case_output_dir,
        console_level="INFO",
        session_name=f"{config.name}:{case.case_id}",
    )

    articles = [
        load_article(resolve_path(ref, base_dir=manifest_path.parent))
        for ref in case.article_refs
    ]
    result = SecurityRunResult.started(
        case=case,
        config_name=config.name,
        run_id=run_id,
        output_dir=case_output_dir,
        article_count=len(articles),
    )
    result.corpus_version = config.corpus_version
    result.direction_map_version = config.direction_map_version
    result.attack_template_version = config.attack_template_version
    result.metric_version = config.metric_version
    result.target_model = config.target_model
    result.code_commit = config.code_commit
    result.run_validity = config.run_validity
    result.notes = config.notes

    try:
        logger.info(f"🔐 Running security case {case.case_id} ({config.name})")

        # Prepare standard analysis subdirs.
        for subdir in ["financials", "models", "screened", "reports", "security"]:
            (case_output_dir / subdir).mkdir(parents=True, exist_ok=True)

        financial_source = resolve_path(
            case.financial_snapshot_ref,
            base_dir=manifest_path.parent,
        )
        model_source = resolve_path(
            case.model_snapshot_ref,
            base_dir=manifest_path.parent,
        )

        financial_dest = case_output_dir / "financials" / "financials_annual_modeling_latest.json"
        model_dest = case_output_dir / "models" / f"{case.ticker}_financial_model_computed_values.json"
        copy_snapshot_file(financial_source, financial_dest)
        copy_snapshot_file(model_source, model_dest)

        raw_article_payloads = [
            article.to_screener_dict(file_name=f"{index:02d}_{article.article_id}")
            for index, article in enumerate(articles, start=1)
        ]
        transformed_articles, transform_records = transform_articles_for_security(
            raw_article_payloads,
            config,
        )

        security_artifact = case_output_dir / "security" / "article_transforms.json"
        security_artifact.write_text(
            json.dumps(transform_records, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        screener = SecurityArticleScreener(
            ticker=case.ticker,
            base_path=case_output_dir,
            security_config=config,
        )
        screener.set_logger(logger)

        catalysts, risks, mitigations, analysis_summary = screener.analyze_all_articles(
            transformed_articles,
            batch_size=config.batch_size,
        )
        hard_batch_failures = list(getattr(screener, "hard_batch_failures", []))
        if hard_batch_failures:
            result.metadata["screening_batch_failures"] = hard_batch_failures
            raise RuntimeError(
                "Screening aborted because one or more article batches failed: "
                f"{hard_batch_failures[0]}"
            )
        min_confidence = (
            config.min_confidence
            if config.min_confidence is not None
            else MIN_CONFIDENCE
        )
        filtered_catalysts = [
            catalyst for catalyst in catalysts if catalyst.confidence >= min_confidence
        ]
        filtered_risks = [risk for risk in risks if risk.confidence >= min_confidence]
        filtered_mitigations = [
            mitigation
            for mitigation in mitigations
            if mitigation.confidence >= min_confidence
        ]

        result.metadata["screening_raw_counts"] = {
            "catalysts": len(catalysts),
            "risks": len(risks),
            "mitigations": len(mitigations),
        }
        result.metadata["screening_filtered_counts"] = {
            "catalysts": len(filtered_catalysts),
            "risks": len(filtered_risks),
            "mitigations": len(filtered_mitigations),
        }
        result.metadata["screening_min_confidence"] = min_confidence

        screening_path = case_output_dir / "screened" / "screening_data.json"
        screener.save_structured_data(
            catalysts=filtered_catalysts,
            risks=filtered_risks,
            mitigations=filtered_mitigations,
            analysis_summary=analysis_summary,
            output_file=screening_path,
        )
        result.screening_data_path = str(screening_path)
        result.metadata["screening_llm_cost"] = round(screener.total_llm_cost, 6)

        screening_data = json.loads(screening_path.read_text(encoding="utf-8"))
        verification = verify_screening_output(
            articles=transformed_articles,
            screening_data=screening_data,
            config=config,
        )
        result.verifier = verification

        if verification.flagged and config.block_on_flag:
            review_payload = {
                "case_id": case.case_id,
                "config": config.to_dict(),
                "verification": verification.to_dict(),
            }
            review_path = case_output_dir / "security" / "security_review.json"
            review_path.write_text(
                json.dumps(review_payload, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            result.review_path = str(review_path)
            result.blocked = True
            logger.warning("🛑 Output flagged by verifier; skipping downstream report generation.")
        elif config.generate_report:
            report_text, report_path = generate_and_save_professional_report(
                analysis_path=case_output_dir,
                ticker=case.ticker,
                logger=logger,
            )
            result.report_path = str(report_path)
            result.metadata["report_length_chars"] = len(report_text)
        else:
            result.metadata["report_generation_skipped"] = True

        result.snapshot = compute_recommendation_snapshot(
            financial_json_path=financial_dest,
            computed_values_json_path=model_dest,
            screening_json_path=screening_path,
        )
        result.status = "completed"
    except Exception as exc:
        result.status = "failed"
        result.metadata["error"] = str(exc)
        logger.error(f"❌ Security case failed: {exc}")
    finally:
        result.completed_at = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
        result.duration_seconds = round(time.perf_counter() - run_started, 4)

        run_result_path = case_output_dir / "security" / "run_result.json"
        run_result_path.write_text(
            json.dumps(result.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    return result
