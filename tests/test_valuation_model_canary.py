from src.valuation_model_canary import _compact, _valid_specialized_refusal


def test_model_canary_compacts_audit_without_hiding_launch_failures():
    result = _compact({
        "status": "failed",
        "ticker": "AAPL",
        "checks": ["FAIL workbook label"],
        "formula_integrity_issue_count": 0,
        "market_implied_wacc": 0.06,
        "financial_currency": "TWD",
        "listing_currency": "USD",
        "current_price": 13_702.08,
        "current_price_listing": 433.24,
        "fx_listing_to_financial": 31.627,
        "private_full_financials": {"too": "large"},
    }, elapsed=1.236)

    assert result["status"] == "failed"
    assert result["checks"] == ["FAIL workbook label"]
    assert result["elapsed_seconds"] == 1.24
    assert result["market_implied_wacc"] == 0.06
    assert result["financial_currency"] == "TWD"
    assert result["listing_currency"] == "USD"
    assert result["current_price_listing"] == 433.24
    assert result["fx_listing_to_financial"] == 31.627
    assert "private_full_financials" not in result


def test_unknown_quote_type_is_not_a_passing_specialized_refusal():
    financial = {"company_data": {"basic_info": {"quote_type": "UNKNOWN"}}}
    methodology = {"specialized_service": "unsupported_asset"}

    assert _valid_specialized_refusal(financial, methodology) is False


def test_known_specialized_asset_remains_a_passing_safety_outcome():
    financial = {"company_data": {"basic_info": {"quote_type": "ETF"}}}
    methodology = {"specialized_service": "fund"}

    assert _valid_specialized_refusal(financial, methodology) is True
