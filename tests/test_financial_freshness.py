from datetime import datetime, timezone

from src.financial_freshness import financial_statement_freshness

NOW = datetime(2026, 9, 12, tzinfo=timezone.utc)


def quarterly_statements():
    periods = ("2026-06-30", "2026-03-31", "2025-12-31", "2025-09-30")
    return {
        "income_statement": {
            period: {"Total Revenue": 100, "Operating Income": 20}
            for period in periods
        },
        "balance_sheet": {
            period: {"Cash And Cash Equivalents": 20}
            for period in periods
        },
        "cash_flow": {
            period: {"Operating Cash Flow": 30, "Capital Expenditure": -10}
            for period in periods
        },
    }


def test_current_annual_statement_is_accepted(monkeypatch):
    monkeypatch.setenv("FINANCIAL_STATEMENT_MAX_AGE_DAYS", "200")
    result = financial_statement_freshness({
        "financial_statements": {
            "income_statement": {"2026-06-30": {}},
            "balance_sheet": {"2026-06-30": {}},
            "cash_flow": {"2026-06-30": {}},
        },
    }, as_of=NOW)
    assert result["status"] == "current"
    assert result["basis"] == "annual"
    assert result["latest_period"] == "2026-06-30"


def test_annual_only_case_is_stale_when_interim_financials_should_exist():
    result = financial_statement_freshness({
        "financial_statements": {
            "income_statement": {"2025-12-31": {}},
            "balance_sheet": {"2025-12-31": {}},
            "cash_flow": {"2025-12-31": {}},
        },
    }, as_of=NOW)

    assert result["status"] == "stale"
    assert result["max_age_days"] == 200
    assert "quarterly/TTM bridge is required" in result["reason"]


def test_environment_cannot_extend_annual_only_freshness_past_eight_months(monkeypatch):
    monkeypatch.setenv("FINANCIAL_STATEMENT_MAX_AGE_DAYS", "9999")
    result = financial_statement_freshness({
        "financial_statements": {
            "income_statement": {"2025-09-30": {}},
            "balance_sheet": {"2025-09-30": {}},
            "cash_flow": {"2025-09-30": {}},
        },
    }, as_of=NOW)

    assert result["max_age_days"] == 240
    assert result["status"] == "stale"


def test_scrape_time_cannot_hide_stale_statements(monkeypatch):
    monkeypatch.setenv("FINANCIAL_STATEMENT_MAX_AGE_DAYS", "550")
    result = financial_statement_freshness({
        "scraped_at": "2026-09-12T00:00:00Z",
        "financial_statements": {
            "income_statement": {"2024-01-01": {}},
            "balance_sheet": {"2024-01-01": {}},
            "cash_flow": {"2024-01-01": {}},
        },
    }, as_of=NOW)
    assert result["status"] == "stale"
    assert "beyond" in result["reason"]


def test_missing_period_is_unavailable():
    assert financial_statement_freshness({}, as_of=NOW)["status"] == "unavailable"


def test_persisted_current_flag_does_not_refresh_old_statements(monkeypatch):
    monkeypatch.setenv("FINANCIAL_STATEMENT_MAX_AGE_DAYS", "550")
    result = financial_statement_freshness({
        "financial_freshness": {"status": "current"},
        "financial_statements": {
            "income_statement": {"2023-09-30": {}},
            "balance_sheet": {"2023-09-30": {}},
            "cash_flow": {"2023-09-30": {}},
        },
    }, as_of=NOW)
    assert result["status"] == "stale"


def test_one_current_statement_cannot_mask_missing_or_misaligned_inputs():
    missing = financial_statement_freshness({
        "financial_statements": {
            "income_statement": {"2025-09-30": {}},
            "balance_sheet": {"2025-09-30": {}},
        },
    }, as_of=NOW)
    assert missing["status"] == "unavailable"
    assert "cash_flow" in missing["reason"]

    misaligned = financial_statement_freshness({
        "financial_statements": {
            "income_statement": {"2025-09-30": {}},
            "balance_sheet": {"2025-06-30": {}},
            "cash_flow": {"2025-03-31": {}},
        },
    }, as_of=NOW)
    assert misaligned["status"] == "unavailable"
    assert "No common actual period" in misaligned["reason"]


def test_future_period_cannot_establish_freshness():
    result = financial_statement_freshness({
        "financial_statements": {
            "income_statement": {"2027-09-30": {}},
            "balance_sheet": {"2027-09-30": {}},
            "cash_flow": {"2027-09-30": {}},
        },
    }, as_of=NOW)
    assert result["status"] == "unavailable"


def test_newer_valid_ttm_period_becomes_the_freshness_basis(monkeypatch):
    monkeypatch.setenv("QUARTERLY_STATEMENT_MAX_AGE_DAYS", "150")
    result = financial_statement_freshness({
        "financial_statements": {
            "income_statement": {"2025-09-30": {}},
            "balance_sheet": {"2025-09-30": {}},
            "cash_flow": {"2025-09-30": {}},
        },
        "quarterly_financial_statements": quarterly_statements(),
    }, as_of=NOW)
    assert result["status"] == "current"
    assert result["basis"] == "ttm"
    assert result["latest_period"] == "2026-06-30"
    assert result["annual_latest_period"] == "2025-09-30"
