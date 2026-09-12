"""Regression tests for the final, orchestrator-independent safety boundary."""

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "src"))

from evidence_extractor import EvidenceExtractor
from report_agent import (
    enforce_valuation_publication_boundary,
    generate_executive_summary,
    load_prompt,
)


def _financials(period="2025-09-27"):
    return {
        "financial_statements": {
            "income_statement": {period: {"Total Revenue": 1}},
            "balance_sheet": {period: {"Total Assets": 1}},
            "cash_flow": {period: {"Free Cash Flow": 1}},
        }
    }


def _aapl_report_data():
    return {
        "company_overview": {
            "company_name": "Apple Inc.",
            "current_price": 332.27,
            "market_cap": 4_887_153_000_000,
            "currency": "USD",
            "listing_currency": "USD",
            "target_mean_price": 324.40,
            "num_analysts": 39,
        },
        "valuation": {
            "dcf_perpetual": {"intrinsic_value_per_share": 151.97},
            "dcf_exit": {"intrinsic_value_per_share": 181.38},
            "summary": {
                "average_intrinsic": 166.67,
                "comps_intrinsic": 0.0,
                "upside": -0.498,
            },
        },
    }


def test_legacy_report_path_cannot_publish_aapl_as_a_precise_sell():
    result = enforce_valuation_publication_boundary(
        _aapl_report_data(), _financials()
    )
    reliability = result["valuation"]["reliability"]
    assert reliability["band"] == "single-method"
    assert reliability["point_estimate_withheld"] is True
    assert reliability["range_low"] == 151.97
    assert reliability["range_high"] == 181.38
    assert "no independent market-comps" in reliability["withheld_reason"].lower()


def test_stale_statements_withhold_even_a_non_megacap_point_estimate():
    data = _aapl_report_data()
    data["company_overview"]["market_cap"] = 2_000_000_000
    result = enforce_valuation_publication_boundary(data, _financials("2023-12-31"))
    reliability = result["valuation"]["reliability"]
    assert reliability["point_estimate_withheld"] is True
    assert "beyond" in reliability["withheld_reason"]


def test_limited_news_does_not_create_a_synthetic_sentiment_citation():
    pack = EvidenceExtractor().build_evidence_pack({
        "analysis_summary": {
            "overall_sentiment": "bearish",
            "articles_analyzed": 5,
            "total_catalysts": 1,
            "total_risks": 1,
        },
        "freshness": {"status": "limited", "newest_published_at": "2026-09-12"},
        "catalysts": [],
        "risks": [],
    })
    assert pack["evidence"] == []


def test_an_earnings_word_in_a_yahoo_title_is_not_a_primary_source():
    extractor = EvidenceExtractor()
    assert extractor._assess_source_quality(
        "https://finance.yahoo.com/news/apple-earnings-preview-123.html",
        "Apple earnings preview",
    ) == "syndication"
    assert extractor._assess_source_quality(
        "https://www.sec.gov/Archives/edgar/data/320193/filing.htm",
        "Apple filing",
    ) == "primary"


def test_executive_summary_cannot_reverse_a_withheld_rating():
    data = enforce_valuation_publication_boundary(
        _aapl_report_data(), _financials()
    )
    data["valuation"]["reverse_dcf"] = {"market_implied_vs_model": 2.2138}
    data["news"] = {
        "freshness": {
            "status": "limited", "fresh_articles": 5, "max_age_days": 90,
        }
    }

    def llm_must_not_run(*_args, **_kwargs):
        raise AssertionError("executive decision fields must be code-generated")

    text, cost = generate_executive_summary(
        {"recommendation": "### Investment Rating: NOT RATED\n"},
        data,
        llm_must_not_run,
    )
    assert cost == 0
    assert "**Investment View**: NOT RATED" in text
    assert "12-Month Price Target" not in text
    assert "151.97" in text and "181.38" in text
    assert "221.4%" in text
    assert "LIMITED" in text


def test_every_report_prompt_marks_inserted_content_as_untrusted_data():
    prompt = load_prompt("report_company_overview")
    assert "UNTRUSTED DATA BOUNDARY" in prompt
    assert "never an instruction" in prompt
