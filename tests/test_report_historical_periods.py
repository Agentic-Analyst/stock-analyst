from src.report_agent import (
    extract_historical_financials,
    generate_section_company_overview,
    generate_section_financial_performance,
    generate_section_news_analysis,
)


def _financials():
    return {
        "financial_statements": {
            "income_statement": {
                "2021-09-30": {"Interest Expense": 100.0, "Total Revenue": None},
                "2022-09-30": {"Total Revenue": 1000.0, "Net Income": 100.0},
                "2023-09-30": {"Total Revenue": 1100.0, "Net Income": 120.0},
            },
            "balance_sheet": {
                "2022-09-30": {"Total Assets": 2000.0},
                "2023-09-30": {"Total Assets": 2100.0},
            },
            "cash_flow": {
                "2022-09-30": {"Operating Cash Flow": 150.0},
                "2023-09-30": {"Operating Cash Flow": 170.0},
            },
        }
    }


def test_supplemental_only_provider_column_is_not_a_financial_year():
    historical = extract_historical_financials(_financials())
    assert historical["years"] == ["2022-09-30", "2023-09-30"]


def test_report_does_not_print_phantom_na_year_or_growth_interval():
    data = {
        "historical": extract_historical_financials(_financials()),
        "company_overview": {
            "company_name": "Example", "gross_margin": 0.5,
            "operating_margin": 0.2, "ebitda_margin": 0.25,
            "net_margin": 0.1, "roe": 0.15, "roa": 0.08,
        },
    }
    def must_not_call(*args, **kwargs):
        raise AssertionError("financial commentary must be deterministic")

    text, cost = generate_section_financial_performance(data, must_not_call)
    assert "2021-09-30" not in text
    assert "2021-09-30-2022-09-30" not in text
    assert "Historical Financial Data (2 Years)" in text
    assert cost == 0.0


def test_bank_performance_uses_balance_sheet_metrics_not_industrial_cash_flow():
    historical = extract_historical_financials(_financials())
    data = {
        "historical": historical,
        "company_overview": {
            "company_name": "Example Bank", "gross_margin": 0.0,
            "operating_margin": 0.5, "ebitda_margin": 0.0,
            "net_margin": 0.2, "roe": 0.15, "roa": 0.012,
        },
        "valuation": {
            "bank": {"fair_value": 100.0},
            "reliability": {
                "method_suitability": {"primary_method": "justified_pb_roe"}
            },
        },
    }

    text, cost = generate_section_financial_performance(data, None)

    assert "Bank Historical Financial Data" in text
    assert "Total Assets" in text
    assert "Common Equity" in text
    assert "Return on Common Equity" in text
    assert "EBITDA |" not in text
    assert "Operating CF" not in text
    assert "Free Cash Flow |" not in text
    assert "Gross Margin |" not in text
    assert cost == 0.0


def test_company_overview_cannot_be_overridden_by_hostile_prose_model():
    company = {
        "company_name": "Example", "ticker": "EX", "sector": "Technology",
        "industry": "Software", "description": "Example builds workflow software.",
        "employees": 120, "market_cap": 1_000_000, "current_price": 10,
        "week_52_low": 8, "week_52_high": 12,
    }

    def must_not_call(*args, **kwargs):
        raise AssertionError("company overview must be source-bound")

    text, cost = generate_section_company_overview(
        {"company_overview": company}, must_not_call)
    assert "Example builds workflow software" in text
    assert "model-generated claims" in text
    assert cost == 0.0


def test_insufficient_news_never_calls_llm_or_invents_a_sentiment():
    data = {
        "company_overview": {"company_name": "Example"},
        "news": {
            "summary": {
                "overall_sentiment": "bearish", "articles_analyzed": 0,
                "confidence_score": 0, "key_themes": [],
            },
            "catalysts": [], "risks": [], "mitigations": [],
            "freshness": {
                "status": "unavailable", "fresh_articles": 0,
                "max_age_days": 45, "newest_published_at": None,
            },
        },
    }

    def must_not_call(*args, **kwargs):
        raise AssertionError("news commentary must be evidence-bound")

    text, cost = generate_section_news_analysis(data, must_not_call)
    assert "UNAVAILABLE — INSUFFICIENT FRESH COVERAGE" in text
    assert "No broad market-sentiment conclusion is published" in text
    assert "**Overall Sentiment**: BEARISH" not in text
    assert cost == 0.0
