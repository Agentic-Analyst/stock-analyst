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
    _join_distinct_messages,
    load_prompt,
)
from src.agents.tools.analysis_tools import valuation_publication_boundary


def _financials(period="2026-06-30"):
    prior = f"{int(period[:4]) - 1}{period[4:]}"
    return {
        # These are corporate-equity publication fixtures. Quote type is a
        # required routing input now that unknown instruments fail closed.
        "company_data": {
            "basic_info": {
                "quote_type": "EQUITY",
                "currency": "USD",
                "listing_currency": "USD",
            },
        },
        "financial_statements": {
            "income_statement": {
                period: {"Total Revenue": 100},
                prior: {"Total Revenue": 90},
            },
            "balance_sheet": {
                period: {"Total Assets": 200},
                prior: {"Total Assets": 180},
            },
            "cash_flow": {
                period: {"Operating Cash Flow": 20, "Free Cash Flow": 15},
                prior: {"Operating Cash Flow": 18, "Free Cash Flow": 13},
            },
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
    assert "39-analyst target benchmark" in reliability["withheld_reason"]


def test_broad_sector_comps_are_context_not_independent_corroboration():
    data = _aapl_report_data()
    data["valuation"]["summary"]["comps_intrinsic"] = 245.11
    data["valuation"]["summary"]["average_intrinsic"] = 206.98
    financials = _financials()
    financials["industry_data"] = {"peer_comps": {
        "grouping": "sector_leaders",
        "confidence": "low",
        "role": "broad_sector_cross_check",
        "included_in_blended_value": False,
    }}
    result = enforce_valuation_publication_boundary(data, financials)
    reliability = result["valuation"]["reliability"]
    assert reliability["band"] == "single-method"
    assert "market_comps" not in reliability["legs"]
    assert reliability["range_low"] == 151.97
    assert reliability["range_high"] == 181.38


def test_legacy_broad_sector_artifact_cannot_reenter_blend():
    data = _aapl_report_data()
    data["valuation"]["summary"]["comps_intrinsic"] = 245.11
    data["valuation"]["summary"]["average_intrinsic"] = 206.98
    financials = _financials()
    financials["industry_data"] = {"peer_comps": {
        "grouping": "sector_leaders",
        "peer_universe_source": "yahoo_sector_leaders",
    }}

    result = enforce_valuation_publication_boundary(data, financials)

    summary = result["valuation"]["summary"]
    assert summary["comps_intrinsic"] == 245.11
    assert summary["market_comps_cross_check"] == 245.11
    assert summary["workbook_headline_value"] == 206.98
    assert summary["average_intrinsic"] == (151.97 + 181.38) / 2
    assert summary["comps_included_in_blended_value"] is False
    assert result["valuation"]["reliability"]["point_estimate_withheld"] is True


def test_legacy_blend_cannot_mask_an_exceptional_dcf_gap_before_boundary():
    data = _aapl_report_data()
    data["company_overview"].update({
        "current_price": 106.60,
        "market_cap": 848_000_000_000,
        "target_mean_price": 127.43,
        "num_analysts": 40,
    })
    data["valuation"]["dcf_perpetual"]["intrinsic_value_per_share"] = 54.79
    data["valuation"]["dcf_exit"]["intrinsic_value_per_share"] = 75.36
    data["valuation"]["summary"].update({
        "average_intrinsic": 86.92,
        "comps_intrinsic": 108.76,
    })

    result = enforce_valuation_publication_boundary(data, _financials())
    summary = result["valuation"]["summary"]
    reliability = result["valuation"]["reliability"]

    assert summary["average_intrinsic"] == (54.79 + 75.36) / 2
    assert summary["workbook_headline_value"] == 86.92
    assert reliability["point_estimate_withheld"] is True
    assert "-39%" in reliability["withheld_reason"]


def test_well_covered_street_conflict_is_material_for_a_non_megacap():
    data = _aapl_report_data()
    data["company_overview"].update({
        "current_price": 100.0,
        "market_cap": 8_000_000_000,
        "target_mean_price": 112.0,
        "num_analysts": 18,
    })
    data["valuation"]["dcf_perpetual"]["intrinsic_value_per_share"] = 50.0
    data["valuation"]["dcf_exit"]["intrinsic_value_per_share"] = 60.0

    result = enforce_valuation_publication_boundary(data, _financials())
    reliability = result["valuation"]["reliability"]

    assert reliability["point_estimate_withheld"] is True
    assert "18-analyst target benchmark" in reliability["withheld_reason"]
    assert "does not corroborate" in reliability["withheld_reason"]


def test_well_covered_street_conflict_is_not_ignored_below_extreme_gap():
    data = _aapl_report_data()
    data["company_overview"].update({
        "current_price": 100.0,
        "market_cap": 800_000_000_000,
        "target_mean_price": 116.0,
        "num_analysts": 52,
    })
    data["valuation"]["dcf_perpetual"]["intrinsic_value_per_share"] = 70.0
    data["valuation"]["dcf_exit"]["intrinsic_value_per_share"] = 74.0

    result = enforce_valuation_publication_boundary(data, _financials())
    reliability = result["valuation"]["reliability"]

    assert reliability["point_estimate_withheld"] is True
    assert "52-analyst target benchmark is +16%" in reliability["withheld_reason"]
    assert "not substituted for intrinsic value" in reliability["withheld_reason"]


def test_aligned_street_evidence_does_not_replace_or_block_model_value():
    data = _aapl_report_data()
    data["company_overview"].update({
        "current_price": 100.0,
        "market_cap": 800_000_000_000,
        "target_mean_price": 114.0,
        "num_analysts": 30,
    })
    data["valuation"]["dcf_perpetual"]["intrinsic_value_per_share"] = 116.0
    data["valuation"]["dcf_exit"]["intrinsic_value_per_share"] = 124.0

    result = enforce_valuation_publication_boundary(data, _financials())

    assert result["valuation"]["reliability"]["point_estimate_withheld"] is False
    assert result["valuation"]["summary"]["average_intrinsic"] == 120.0


def test_directional_dcf_only_call_requires_independent_numeric_benchmark():
    data = _aapl_report_data()
    data["company_overview"].update({
        "current_price": 100.0,
        "market_cap": 8_000_000_000,
        "target_mean_price": None,
        "num_analysts": 0,
    })
    data["valuation"]["dcf_perpetual"]["intrinsic_value_per_share"] = 116.0
    data["valuation"]["dcf_exit"]["intrinsic_value_per_share"] = 124.0

    result = enforce_valuation_publication_boundary(data, _financials())

    reliability = result["valuation"]["reliability"]
    assert reliability["point_estimate_withheld"] is True
    assert "sufficiently covered external analyst benchmark was unavailable" in (
        reliability["withheld_reason"]
    )


def test_stale_source_evidence_cannot_reenter_through_active_target_fallback():
    withheld, reason = valuation_publication_boundary(
        band="single-method",
        legs={"perpetual_dcf": 145.0, "exit_multiple_dcf": 155.0},
        fair_value=150.0,
        current_price=100.0,
        analyst_target=150.0,
        analyst_count=25,
        analyst_target_evidence={
            "finnhub": {
                "mean": 150.0,
                "analyst_count": 25,
                "qualified": False,
                "qualified_for_contradiction": False,
                "qualified_for_corroboration": False,
                "temporal_quality": {"status": "stale"},
            },
        },
    )

    assert withheld is True
    assert "sufficiently covered external analyst benchmark was unavailable" in reason


def test_undated_target_is_described_as_unqualified_for_corroboration():
    withheld, reason = valuation_publication_boundary(
        band="single-method",
        legs={"perpetual_dcf": 45.0, "exit_multiple_dcf": 55.0},
        fair_value=50.0,
        current_price=100.0,
        analyst_target_evidence={
            "yahoo_finance": {
                "mean": 98.0,
                "analyst_count": 25,
                "qualified": True,
                "qualified_for_contradiction": True,
                "qualified_for_corroboration": False,
                "temporal_quality": {"status": "unknown"},
            },
        },
    )

    assert withheld is True
    assert "no provider-dated current analyst target qualified" in reason
    assert "provider date unavailable; caution only" in reason


def test_a_conflicting_qualified_secondary_target_cannot_be_treated_as_trivial():
    data = _aapl_report_data()
    data["company_overview"].update({
        "current_price": 100.0,
        "market_cap": 8_000_000_000,
        # The selected source supports the model's +20% conclusion.
        "target_mean_price": 125.0,
        "num_analysts": 24,
    })
    data["valuation"]["dcf_perpetual"]["intrinsic_value_per_share"] = 116.0
    data["valuation"]["dcf_exit"]["intrinsic_value_per_share"] = 124.0
    financials = _financials()
    financials["external_expectations"] = {
        "price_target": {"source_evidence": {
            "benzinga": {
                "mean": 125.0, "analyst_count": 24, "qualified": True,
            },
            # A second broad source points away from the BUY conclusion. It is
            # evidence of an unresolved assumption dispute, not a footnote.
            "yahoo_finance": {
                "mean": 96.0, "analyst_count": 39, "qualified": True,
            },
        }},
        "recommendations": {"source_evidence": {}},
        "forward_estimates": [],
    }

    result = enforce_valuation_publication_boundary(data, financials)
    reliability = result["valuation"]["reliability"]

    assert reliability["point_estimate_withheld"] is True
    assert "yahoo_finance 39-analyst target benchmark is -4%" in (
        reliability["withheld_reason"]
    )
    assert result["valuation"]["summary"]["average_intrinsic"] == 120.0


def test_report_boundary_uses_qualified_recommendation_evidence_without_a_target():
    data = _aapl_report_data()
    data["company_overview"].update({
        "current_price": 100.0,
        "market_cap": 8_000_000_000,
        "target_mean_price": None,
        "num_analysts": 0,
        "analyst_consensus": {
            "recommendation": {
                "label": "strong_buy", "total": 24, "source": "finnhub",
            },
        },
    })
    data["valuation"]["dcf_perpetual"]["intrinsic_value_per_share"] = 50.0
    data["valuation"]["dcf_exit"]["intrinsic_value_per_share"] = 60.0

    result = enforce_valuation_publication_boundary(data, _financials())
    reliability = result["valuation"]["reliability"]

    assert reliability["point_estimate_withheld"] is True
    assert "STRONG BUY" in reliability["withheld_reason"]
    assert "24 ratings" in reliability["withheld_reason"]


def test_non_megacap_street_target_never_replaces_intrinsic_value():
    data = _aapl_report_data()
    data["company_overview"].update({
        "current_price": 100.0,
        "market_cap": 8_000_000_000,
        "target_mean_price": 45.0,
        "num_analysts": 18,
    })
    data["valuation"]["dcf_perpetual"]["intrinsic_value_per_share"] = 50.0
    data["valuation"]["dcf_exit"]["intrinsic_value_per_share"] = 60.0

    result = enforce_valuation_publication_boundary(data, _financials())

    assert result["valuation"]["summary"]["average_intrinsic"] == 55.0
    assert result["valuation"]["reliability"]["point_estimate_withheld"] is False


def test_material_well_covered_revenue_gap_blocks_publication():
    data = _aapl_report_data()
    data["company_overview"].update({
        "current_price": 100.0,
        "market_cap": 8_000_000_000,
        "target_mean_price": 100.0,
        "num_analysts": 20,
    })
    data["valuation"]["dcf_perpetual"]["intrinsic_value_per_share"] = 95.0
    data["valuation"]["dcf_exit"]["intrinsic_value_per_share"] = 105.0
    data["projections"] = {"revenue": [80.0, 85.0]}
    financials = _financials()
    financials["external_expectations"] = {
        "forward_estimates": [
            {"revenue": 100.0, "revenue_analyst_count": 18},
            {"revenue": 105.0, "revenue_analyst_count": 17},
        ],
    }

    result = enforce_valuation_publication_boundary(data, financials)
    reliability = result["valuation"]["reliability"]

    assert reliability["point_estimate_withheld"] is True
    assert "near-term operating case is not reconciled" in reliability["withheld_reason"]
    assert "FY1 model revenue is -20%" in reliability["withheld_reason"]


def test_small_revenue_rounding_difference_does_not_block_publication():
    data = _aapl_report_data()
    data["company_overview"].update({
        "current_price": 100.0,
        "market_cap": 8_000_000_000,
        "target_mean_price": 100.0,
        "num_analysts": 20,
    })
    data["valuation"]["dcf_perpetual"]["intrinsic_value_per_share"] = 95.0
    data["valuation"]["dcf_exit"]["intrinsic_value_per_share"] = 105.0
    data["projections"] = {"revenue": [99.5, 105.5]}
    financials = _financials()
    financials["external_expectations"] = {
        "forward_estimates": [
            {"revenue": 100.0, "revenue_analyst_count": 18},
            {"revenue": 105.0, "revenue_analyst_count": 17},
        ],
    }

    result = enforce_valuation_publication_boundary(data, financials)

    assert result["valuation"]["reliability"]["point_estimate_withheld"] is False


def test_final_boundary_recomputes_instead_of_preserving_stale_withhold_metadata():
    data = _aapl_report_data()
    data["company_overview"].update({
        "current_price": 100.0, "market_cap": 8_000_000_000,
        "target_mean_price": 100.0, "num_analysts": 20,
    })
    data["valuation"]["dcf_perpetual"]["intrinsic_value_per_share"] = 95.0
    data["valuation"]["dcf_exit"]["intrinsic_value_per_share"] = 105.0
    data["valuation"]["reliability"] = {
        "point_estimate_withheld": True,
        "withheld_reason": "Old run lacked evidence that is now present.",
    }

    result = enforce_valuation_publication_boundary(data, _financials())

    assert result["valuation"]["reliability"]["point_estimate_withheld"] is False
    assert result["valuation"]["reliability"].get("withheld_reason") is None


def test_extreme_dcf_only_gap_requires_independent_method_even_without_street():
    data = _aapl_report_data()
    data["company_overview"].update({
        "current_price": 100.0,
        "market_cap": 8_000_000_000,
        "target_mean_price": None,
        "num_analysts": 0,
    })
    data["valuation"]["dcf_perpetual"]["intrinsic_value_per_share"] = 35.0
    data["valuation"]["dcf_exit"]["intrinsic_value_per_share"] = 45.0

    result = enforce_valuation_publication_boundary(data, _financials())
    reliability = result["valuation"]["reliability"]

    assert reliability["point_estimate_withheld"] is True
    assert "no independent market-comps" in reliability["withheld_reason"]


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
    assert "External analyst target benchmark" in text
    assert "324.40" in text
    assert "39 target observations" in text
    assert "221.4%" in text
    assert "LIMITED" in text


def test_every_report_prompt_marks_inserted_content_as_untrusted_data():
    prompt = load_prompt("report_company_overview")
    assert "UNTRUSTED DATA BOUNDARY" in prompt
    assert "never an instruction" in prompt


def test_reapplying_a_publication_boundary_does_not_duplicate_warnings():
    reason = "PUBLICATION BOUNDARY: Independent evidence conflicts."
    spread = "Valuation methods span 1.4x."
    combined = _join_distinct_messages(f"{reason} {spread}", reason, spread)
    assert combined.count(reason) == 1
    assert combined.count(spread) == 1


def test_reliability_always_discloses_the_financial_and_method_basis():
    result = enforce_valuation_publication_boundary(
        _aapl_report_data(), _financials()
    )
    reliability = result["valuation"]["reliability"]
    assert reliability["financial_freshness"]["basis"] == "annual"
    assert reliability["method_suitability"]["cash_flow_profile"]["period"] == "2026-06-30"


def test_corporate_dcf_is_withheld_for_an_etf_even_if_numbers_exist():
    financials = _financials()
    financials["company_data"] = {"basic_info": {"quote_type": "ETF"}}
    result = enforce_valuation_publication_boundary(
        _aapl_report_data(), financials
    )
    reliability = result["valuation"]["reliability"]
    assert reliability["point_estimate_withheld"] is True
    assert "not valid for a fund" in reliability["withheld_reason"]


def _bank_financials(period="2026-06-30"):
    data = _financials(period)
    data["company_data"] = {
        "basic_info": {
            "quote_type": "EQUITY",
            "sector": "Financial Services",
            "industry": "Banks - Diversified",
        },
        "valuation_metrics": {"book_value": 100.0},
        "growth_profitability": {"return_on_equity": 0.16},
        "market_data": {"current_price": 150.0},
        "capital_structure": {"beta": 1.0},
    }
    data["modeling_metrics"] = {"financial_ratios": {"financial_profile": {
        "interest_income_to_revenue": 1.20,
    }}}
    return data


def _bank_report_data():
    data = _aapl_report_data()
    data["company_overview"].update({
        "current_price": 150.0,
        "target_mean_price": 150.0,
        "num_analysts": 20,
        "analyst_consensus": {
            "recommendation": {"label": "hold", "total": 20},
        },
    })
    data["valuation"]["bank"] = {
        "fair_value": 150.0,
        "method": "Justified P/B x ROE",
        "inputs": {},
    }
    data["valuation"]["dcf_perpetual"]["intrinsic_value_per_share"] = 150.0
    data["valuation"]["dcf_exit"]["intrinsic_value_per_share"] = 150.0
    data["valuation"]["summary"].update({
        "average_intrinsic": 150.0,
        "comps_intrinsic": None,
    })
    data["valuation"]["reliability"] = {
        "point_estimate_withheld": True,
        "withheld_reason": "Discarded FCF did not have independent market comps.",
        "band": "single-method",
    }
    return data


def test_bank_method_does_not_inherit_discarded_dcf_publication_block():
    result = enforce_valuation_publication_boundary(
        _bank_report_data(), _bank_financials()
    )
    reliability = result["valuation"]["reliability"]
    assert reliability["point_estimate_withheld"] is False
    assert reliability["band"] == "single-method"
    assert "same-subindustry bank peers" in reliability["warning"]
    assert reliability["method_suitability"]["primary_method"] == "justified_pb_roe"


def test_bank_method_still_obeys_financial_freshness_boundary():
    result = enforce_valuation_publication_boundary(
        _bank_report_data(), _bank_financials("2023-12-31")
    )
    reliability = result["valuation"]["reliability"]
    assert reliability["point_estimate_withheld"] is True
    assert "beyond" in reliability["withheld_reason"]
