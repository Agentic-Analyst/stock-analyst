"""The valuation engine must select a method the asset can actually support."""

from src.valuation_methodology import assess_valuation_methodology, normalize_peer_comps_policy


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
    assert result["primary_method"] == "dcf_only"
    assert result["publication_allowed"] is True
    assert result["cash_flow_profile"]["positive_fcf_periods"] == 3


def test_broad_sector_roster_is_named_as_a_cross_check_not_close_comps():
    data = _operating_company()
    data["industry_data"] = {"peer_comps": {
        "confidence": "low",
        "role": "broad_sector_cross_check",
        "included_in_blended_value": False,
    }}
    result = assess_valuation_methodology(data)
    assert result["primary_method"] == "dcf_with_broad_market_cross_check"
    assert result["publication_allowed"] is True


def test_legacy_sector_leader_artifact_is_still_only_a_cross_check():
    data = _operating_company()
    data["industry_data"] = {"peer_comps": {
        "grouping": "sector_leaders",
        "peer_universe_source": "yahoo_sector_leaders",
        "median_ev_ebitda": 20.0,
    }}

    result = assess_valuation_methodology(data)

    assert result["primary_method"] == "dcf_with_broad_market_cross_check"


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


def test_unknown_and_non_equity_instruments_fail_closed():
    missing = _operating_company()
    missing["company_data"]["basic_info"].pop("quote_type")
    index = _operating_company()
    index["company_data"]["basic_info"]["quote_type"] = "INDEX"

    for payload in (missing, index):
        result = assess_valuation_methodology(payload)
        assert result["primary_method"] == "unsupported_asset_type"
        assert result["specialized_service"] == "unsupported_asset"
        assert result["publication_allowed"] is False


def test_cross_currency_equity_requires_a_verified_fx_rate():
    company = _operating_company()
    company["company_data"]["basic_info"].update({
        "listing_currency": "GBP", "currency": "USD",
    })
    company["company_data"]["market_data"] = {
        "fx_listing_to_financial": None,
    }

    result = assess_valuation_methodology(company)

    assert result["publication_allowed"] is False
    assert "currency conversion is unavailable" in result["reason"]


def test_reit_is_not_published_from_a_generic_corporate_dcf():
    reit = _operating_company()
    reit["company_data"]["basic_info"].update({
        "sector": "Real Estate",
        "industry": "REIT - Retail",
    })

    result = assess_valuation_methodology(reit)

    assert result["primary_method"] == "reit_affo_nav"
    assert result["specialized_service"] == "reit"
    assert result["publication_allowed"] is False
    assert "FFO/AFFO" in result["reason"]


def test_insurer_requires_reserve_float_and_book_value_methodology():
    insurer = _operating_company()
    insurer["company_data"]["basic_info"].update({
        "sector": "Financial Services",
        "industry": "Insurance - Diversified",
    })

    result = assess_valuation_methodology(insurer)

    assert result["primary_method"] == "insurance_book_value_embedded_value"
    assert result["specialized_service"] == "insurance"
    assert result["publication_allowed"] is False
    assert "reserve adequacy" in result["reason"]


def test_insurance_broker_remains_an_operating_company_dcf():
    broker = _operating_company()
    broker["company_data"]["basic_info"].update({
        "sector": "Financial Services",
        "industry": "Insurance Brokers",
    })

    result = assess_valuation_methodology(broker)

    assert result["primary_method"] == "dcf_only"
    assert result["publication_allowed"] is True


def test_commodity_producer_requires_a_normalized_cycle_case():
    producer = _operating_company()
    producer["company_data"]["basic_info"].update({
        "sector": "Energy",
        "industry": "Oil & Gas Integrated",
    })

    result = assess_valuation_methodology(producer)

    assert result["primary_method"] == "cyclically_normalized_dcf"
    assert result["specialized_service"] == "commodity_cycle"
    assert result["publication_allowed"] is False
    assert "commodity price deck" in result["reason"]


def test_captive_finance_industrial_requires_an_operating_finance_sotp():
    data = _operating_company()
    data["company_data"]["basic_info"].update({
        "sector": "Industrials",
        "industry": "Farm & Heavy Construction Machinery",
        "business_summary": (
            "The Financial Products segment provides operating and finance leases, "
            "dealer financing, working capital loans, and insurance products."
        ),
    })

    result = assess_valuation_methodology(data)

    assert result["primary_method"] == "scenario_only_pending_operating_finance_sotp"
    assert result["publication_allowed"] is False
    assert "finance receivables" in result["reason"]
    assert "sum-of-the-parts" in result["reason"]


def test_ordinary_industrial_is_not_misclassified_as_captive_finance():
    data = _operating_company()
    data["company_data"]["basic_info"].update({
        "sector": "Industrials",
        "industry": "Specialty Industrial Machinery",
        "business_summary": "The company manufactures pumps and provides service contracts.",
    })

    assert assess_valuation_methodology(data)["primary_method"] == "dcf_only"


def test_conglomerate_does_not_get_a_fake_sotp_without_segment_inputs():
    data = _operating_company()
    data["company_data"]["basic_info"]["industry"] = "Diversified Holdings"
    result = assess_valuation_methodology(data)

    assert result["primary_method"] == "scenario_only_pending_sotp"
    assert result["publication_allowed"] is False
    assert result["sotp"]["status"] == "data_required"
    assert "verified segments" in result["sotp"]["reason"]


def test_raw_segment_inputs_do_not_count_as_a_completed_sotp():
    data = _operating_company()
    data["company_data"]["basic_info"]["industry"] = "Diversified Holdings"
    data["segment_data"] = [
        {
            "name": "Cloud",
            "revenue": 60.0,
            "operating_income": 18.0,
            "valuation_multiple": 12.0,
        },
        {
            "name": "Devices",
            "revenue": 40.0,
            "operating_income": 4.0,
            "valuation_multiple": 7.0,
        },
    ]

    result = assess_valuation_methodology(data)

    assert result["sotp"]["status"] == "ready"
    assert result["primary_method"] == "scenario_only_pending_sotp"
    assert result["publication_allowed"] is False
    assert "has not been completed" in result["reason"]


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
    assert result["primary_method"] == "dcf_only"
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


def test_balance_sheet_lender_with_missing_bank_inputs_never_falls_to_dcf():
    data = _operating_company()
    data["company_data"].update({
        "basic_info": {
            "quote_type": "EQUITY",
            "sector": "Financial Services",
            "industry": "Banks - Diversified",
        },
        "valuation_metrics": {},
        "growth_profitability": {},
        "market_data": {"current_price": 150.0},
    })
    data["modeling_metrics"] = {"financial_ratios": {"financial_profile": {
        "interest_income_to_revenue": 1.20,
    }}}

    result = assess_valuation_methodology(data)

    assert result["primary_method"] == "justified_pb_roe"
    assert result["publication_allowed"] is False
    assert result["specialized_service"] == "bank_valuation_input_gap"
    assert "Corporate free-cash-flow DCF is suppressed" in result["reason"]


def test_policy_normalizer_recognizes_a_complete_bank_peer_contract():
    policy = normalize_peer_comps_policy({
        "status": "ready",
        "included_in_blended_value": True,
        "confidence": "high",
        "role": "bank_comparable_company_valuation",
        "selected_method": "price_to_book",
        "size_screen_applied": True,
        "fundamental_screen_applied": True,
        "selected_peer_count": 6,
    })

    assert policy["policy_complete"] is True
    assert policy["included_in_blended_value"] is True
