"""What the market price requires, packaged for the dashboard.

The chat answer and the report compute these sentences from the saved model
at read time. The dashboard reads run summaries through api-runner, which
never imports this engine, so the same benchmark is persisted once, at build
time, under ``_vynn["market_expectations"]`` in the computed-values file.

Everything here is a benchmark: none of it enters intrinsic value, and a
method the methodology ruled out (captive lender, memory cycle, unfinished
sum of the parts) states no direction and no growth comparison.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

SCHEMA_VERSION = 1

_GROWTH_FIELDS = (
    "years", "required_growth", "required_growth_beyond_bound",
    "model_equivalent_growth", "model_equivalent_growth_beyond_bound",
    "best_operating_margin", "required_growth_at_best_margin",
    "required_growth_at_best_margin_beyond_bound", "model_revenue_growth",
    "revenue_source",
)


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def build_market_expectations(
    computed: Dict[str, Any],
    financial_data: Dict[str, Any],
    publication: Dict[str, Any],
) -> Dict[str, Any]:
    """Assemble the dashboard payload; never raises."""
    try:
        from src.external_expectations import required_revenue_growth_from_workbook
        from src.summary_evidence import (
            model_view_summary, plain_rating_note, required_growth_sentence,
            supported_valuation_span, unsuitable_method_note,
        )
        from src.valuation_methodology import assess_valuation_methodology

        method_note = unsuitable_method_note(
            assess_valuation_methodology(financial_data or {})
        )
        required: Dict[str, Any] = (
            {} if method_note else required_revenue_growth_from_workbook(computed)
        )
        sentence = None if method_note else required_growth_sentence(required)

        headline = None
        publication = publication if isinstance(publication, dict) else {}
        if publication.get("point_estimate_withheld"):
            values = [
                value for value in (publication.get("range_low"), publication.get("range_high"))
                if _number(value) is not None and float(value) > 0
            ]
            summary = ((computed or {}).get("Summary") or {}).get("cells") or {}
            company = ((financial_data or {}).get("company_data") or {})
            basic = company.get("basic_info") or {}
            target = (((financial_data or {}).get("external_expectations") or {})
                      .get("price_target") or {})
            view = model_view_summary(
                span=supported_valuation_span(values),
                current_price=summary.get("(9, 2)"),
                street_target=target.get("mean"),
                street_count=target.get("analyst_count"),
                currency=str(basic.get("listing_currency") or basic.get("currency") or ""),
                required_growth=required,
                method_note=method_note,
            )
            headline = view.get("headline") or None

        return {
            "schema_version": SCHEMA_VERSION,
            "status": "ready",
            "role": "market_expectations_benchmark_only",
            "required_growth": {
                key: required.get(key) for key in _GROWTH_FIELDS if key in required
            } if required.get("available") else None,
            "sentence": sentence,
            "model_view_headline": headline,
            "method_note": method_note,
            "rating_note": (
                plain_rating_note(publication.get("withheld_reason"), method_note)
                if publication.get("point_estimate_withheld") else None
            ),
        }
    except Exception as error:  # a benchmark must never break a model build
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "error",
            "error_type": type(error).__name__,
        }
