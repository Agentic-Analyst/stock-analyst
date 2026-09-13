from financial_scraper import FinancialScraper, _specialized_peer_comps_exclusion


def test_non_equity_is_classified_before_corporate_endpoints(monkeypatch):
    scraper = FinancialScraper.__new__(FinancialScraper)
    scraper.ticker = "VOO"
    scraper._log = lambda *_args, **_kwargs: None
    scraper.scrape_comprehensive_company_data = lambda: {
        "basic_info": {"quote_type": "ETF", "currency": "USD"},
        "market_data": {"current_price": 700.0},
    }

    def forbidden(*_args, **_kwargs):
        raise AssertionError("corporate endpoint must not be called for an ETF")

    scraper.scrape_income_statement = forbidden
    scraper.scrape_balance_sheet = forbidden
    scraper.scrape_cash_flow = forbidden
    scraper._scrape_quarterly_bridge_statements = forbidden
    scraper.scrape_historical_prices = forbidden
    scraper.scrape_analyst_estimates = forbidden

    result = scraper.scrape_financial_modeling_data()

    assert result["valuation_methodology"]["specialized_service"] == "fund"
    assert result["financial_freshness"]["status"] == "not_applicable"
    assert scraper.failed_statements == 0


def test_generic_peers_are_explicitly_excluded_for_specialized_equities():
    for service in ("reit", "insurance", "commodity_cycle"):
        result = _specialized_peer_comps_exclusion({"specialized_service": service})
        assert result["status"] == "not_applicable"
        assert result["included_in_blended_value"] is False
        assert service in result["reason"]
    assert _specialized_peer_comps_exclusion({"primary_method": "dcf_only"}) is None
