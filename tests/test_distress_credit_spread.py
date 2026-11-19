"""A company that cannot cover its interest borrows at a distressed rate, in any currency.

China Vanke (18 Nov 2026) loses money from operations, yet was lent to at
the 1.5% house spread (3.1% all in) and discounted at 2.5%: the synthetic
rating table is calibrated on large US firms, so it was skipped for a yuan
reporter. Distress (EBIT below 1.25x interest) now applies it anywhere; a
healthy issuer outside the table's scope keeps the house fallback.
"""
import pytest

from src.agents.fm.assumption_grounding import _DEBT_SPREAD, _issuer_credit_spread


def _company(currency, market_cap, rows):
    company = {"basic_info": {"currency": currency}, "market_data": {"market_cap": market_cap}}
    statements = {f"{2022 + i}-12-31": {"Operating Income": ebit, "Interest Expense": interest}
                  for i, (ebit, interest) in enumerate(rows)}
    return company, {"financial_statements": {"income_statement": statements}}


def test_a_yuan_reporter_losing_money_gets_the_distress_spread():
    company, data = _company("CNY", 30e9, [(-5.0e9, 4.0e9), (-2.3e9, 3.8e9), (1.0e9, 3.5e9)])
    spread = _issuer_credit_spread(company, data)
    assert spread["synthetic"] and spread["rating"] == "D2/D" and spread["spread"] == pytest.approx(0.19)
    assert "outside its USD scope" in spread["source"]


def test_a_healthy_yuan_reporter_keeps_the_house_fallback():
    company, data = _company("CNY", 30e9, [(9.0e9, 1.0e9), (8.0e9, 1.0e9)])
    spread = _issuer_credit_spread(company, data)
    assert not spread["synthetic"] and spread["spread"] == pytest.approx(_DEBT_SPREAD)


def test_a_small_us_company_in_distress_gets_its_spread_too():
    company, data = _company("USD", 2e9, [(0.5e9, 1.0e9), (0.6e9, 1.0e9)])
    spread = _issuer_credit_spread(company, data)
    assert spread["rating"] == "C2/C" and "below its >$5B scope" in spread["source"]


def test_a_small_healthy_us_company_keeps_the_house_fallback():
    company, data = _company("USD", 2e9, [(3.0e9, 1.0e9), (3.2e9, 1.0e9)])
    assert _issuer_credit_spread(company, data)["spread"] == pytest.approx(_DEBT_SPREAD)


def test_one_bad_year_is_not_distress():
    # The median of the observations decides, not the single worst year.
    company, data = _company("EUR", 10e9, [(-1.0e9, 1.0e9), (4.0e9, 1.0e9), (4.5e9, 1.0e9)])
    assert not _issuer_credit_spread(company, data)["synthetic"]
