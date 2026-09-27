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


def test_a_blank_year_and_an_unreported_line_never_take_the_section_down():
    # Booking Holdings: no gross profit in any year, and the provider left the
    # latest EBITDA blank. Dividing that blank by the prior year raised
    # TypeError and the report printed "Section unavailable".
    financials = {"financial_statements": {
        "income_statement": {
            "2024-12-31": {"Total Revenue": 23739.0, "Operating Income": 7555.0,
                           "EBITDA": 9340.0, "Net Income": 5882.0},
            "2025-12-31": {"Total Revenue": 26917.0, "Operating Income": 9282.0,
                           "EBITDA": None, "Net Income": 5400.0},
        },
        "balance_sheet": {},
        "cash_flow": {
            "2024-12-31": {"Operating Cash Flow": 8320.0, "Free Cash Flow": 7890.0},
            "2025-12-31": {"Operating Cash Flow": 9410.0, "Free Cash Flow": 9090.0},
        },
    }}
    historical = extract_historical_financials(financials)
    assert historical["gross_profit"] == [None, None]

    section, _ = generate_section_financial_performance({
        "historical": historical,
        "company_overview": {
            "gross_margin": None, "operating_margin": 0.34, "ebitda_margin": 0.37,
            "net_margin": 0.2, "roe": None, "roa": 0.2,
        },
        "valuation": {},
    }, llm=None)

    rows = {line.split("|")[1].strip(): line for line in section.splitlines()
            if line.startswith("| 20")}
    assert "| N/A | N/A |" in rows["2025-12-31"]          # gross profit, EBITDA
    growth = next(line for line in section.splitlines()
                  if line.startswith("| 2024-12-31-2025-12-31"))
    assert growth.split("|")[2].strip() == "13.39%"       # revenue still computed
    assert growth.split("|")[3].strip() == "N/A"          # gross profit
    assert growth.split("|")[4].strip() == "N/A"          # EBITDA
