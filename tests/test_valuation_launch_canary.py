from src.valuation_launch_canary import _summary


def test_canary_output_is_compact_and_flags_low_confidence_peers():
    data = {
        "ticker": "AAPL",
        "company_data": {
            "basic_info": {
                "quote_type": "EQUITY", "currency": "TWD",
                "listing_currency": "USD",
            },
            "market_data": {
                "current_price": 10_508.50,
                "current_price_listing": 332.27,
                "fx_listing_to_financial": 31.625,
            },
            "analyst_consensus": {
                "price_target": {"mean": 324.4, "analyst_count": 39,
                                 "source": "yahoo_finance"},
                "recommendation": {"label": "strong_buy", "source": "finnhub"},
            },
        },
        "external_expectations": {"coverage": "high", "forward_estimates": []},
        "industry_data": {"peer_comps": {
            "confidence": "low", "role": "broad_sector_cross_check",
            "included_in_blended_value": False,
        }},
    }
    got = _summary(data, elapsed=1.234, failed=0)
    assert got["elapsed_seconds"] == 1.23
    assert got["financial_currency"] == "TWD"
    assert got["listing_currency"] == "USD"
    assert got["current_price_listing"] == 332.27
    assert got["fx_listing_to_financial"] == 31.625
    assert got["street"]["target_mean"] == 324.4
    assert got["peers"]["included_in_blended_value"] is False
    assert got["warnings"] == [
        "broad peer cross-check is low confidence and excluded from blend"
    ]
    assert "financial_statements" not in got
