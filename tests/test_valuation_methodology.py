"""The valuation engine must select a method the asset can actually support."""

from src.valuation_methodology import assess_valuation_methodology


def _operating_company(*, current_ocf=30.0, current_capex=-10.0, periods=3):
    dates = ("2025-12-31", "2024-12-31", "2023-12-31")[:periods]
    return {
        "company_data": {
            "basic_info": {
                "quote_type": "EQUITY",
                "sector": "Technology",
                "industry": "Consumer Electronics",
            },
        },
        "financial_statements": {
            "income_statement": {
                date: {"Total Revenue": 100.0, "Operating Income": 20.0}
                for date in dates
            },
            "cash_flow": {
                date: {
                    "Operating Cash Flow": current_ocf,
                    "Capital Expenditure": current_capex,
                }
                for date in dates
            },
        },
    }


def test_cash_generative_operating_company_supports_dcf_publication():
    result = assess_valuation_methodology(_operating_company())
    assert result["primary_method"] == "dcf_plus_market_comps"
    assert result["publication_allowed"] is True
    assert result["cash_flow_profile"]["positive_fcf_periods"] == 3


def test_pre_cash_flow_company_gets_scenarios_but_not_a_point_rating():
    result = assess_valuation_methodology(
        _operating_company(current_ocf=-5.0, current_capex=-20.0)
    )
    assert result["primary_method"] == "scenario_only"
    assert result["publication_allowed"] is False
    assert "non-positive" in result["reason"]
    assert "not yet established" in result["reason"]


def test_thin_history_cannot_support_a_long_duration_point_dcf():
    result = assess_valuation_methodology(_operating_company(periods=1))
    assert result["publication_allowed"] is False
    assert "fewer than two aligned" in result["reason"]


def test_fund_and_crypto_are_routed_away_from_corporate_dcf():
    fund = _operating_company()
    fund["company_data"]["basic_info"]["quote_type"] = "ETF"
    crypto = _operating_company()
    crypto["company_data"]["basic_info"]["quote_type"] = "CRYPTOCURRENCY"

    assert assess_valuation_methodology(fund)["specialized_service"] == "fund"
    assert assess_valuation_methodology(crypto)["specialized_service"] == "crypto"
    assert assess_valuation_methodology(fund)["publication_allowed"] is False
    assert assess_valuation_methodology(crypto)["publication_allowed"] is False


def test_conglomerate_does_not_get_a_fake_sotp_without_segment_inputs():
    data = _operating_company()
    data["company_data"]["basic_info"]["industry"] = "Diversified Holdings"
    result = assess_valuation_methodology(data)

    assert result["primary_method"] == "dcf_plus_market_comps"
    assert result["sotp"]["status"] == "data_required"
    assert "verified segments" in result["sotp"]["reason"]


def test_payment_processor_is_not_sent_through_the_bank_method():
    data = _operating_company()
    data["company_data"].update({
        "basic_info": {
            "quote_type": "EQUITY",
            "sector": "Financial Services",
            "industry": "Credit Services",
        },
        "valuation_metrics": {"book_value": 20.0},
        "growth_profitability": {"return_on_equity": 0.20},
        "market_data": {"current_price": 80.0},
        "capital_structure": {"beta": 1.0},
    })
    data["modeling_metrics"] = {"financial_ratios": {"financial_profile": {
        "interest_income_to_revenue": 0.02,
    }}}

    result = assess_valuation_methodology(data)
    assert result["primary_method"] == "dcf_plus_market_comps"
    assert result["publication_allowed"] is True


def test_balance_sheet_lender_uses_justified_pb_roe():
    data = _operating_company()
    data["company_data"].update({
        "basic_info": {
            "quote_type": "EQUITY",
            "sector": "Financial Services",
            "industry": "Credit Services",
        },
        "valuation_metrics": {"book_value": 100.0},
        "growth_profitability": {"return_on_equity": 0.16},
        "market_data": {"current_price": 150.0},
        "capital_structure": {"beta": 1.0},
    })
    data["modeling_metrics"] = {"financial_ratios": {"financial_profile": {
        "interest_income_to_revenue": 1.20,
    }}}

    result = assess_valuation_methodology(data)
    assert result["primary_method"] == "justified_pb_roe"
    assert result["publication_allowed"] is True
