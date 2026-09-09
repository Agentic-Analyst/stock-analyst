"""
THE BUG: every company's Python-side WACC used the same hardcoded tax rate.

_effective_tax_rate consulted only company_data["growth_profitability"], which
the scraper never populates with a tax rate — checked across all 43 real runs on
disk: zero contain `effective_tax_rate` or `tax_rate`. So the fallback fired
every single time, while the report presented WACC as derived from that issuer's
own figures.

Real rates from the runs on disk: AAPL 15.6%, AMZN 13.5%, META 11.8%,
MSFT 17.6%, NVDA 13.3% — all shown as 25%. About 19bp of WACC on NVDA. Small in
itself, and a fabricated input on the one page whose claim is that every input
is real and sourced.

The rate now comes from the issuer's own income statement, mirroring the
workbook's Assumptions!B20 formula including its tax-credit edge case.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agents.fm.assumption_grounding import (
    _TAX_DEFAULT,
    _effective_tax_rate,
    _tax_rate_from_statements,
)


def payload(rows, period="2025-01-31"):
    return {"financial_statements": {"income_statement": {period: rows}}}


# ------------------------------------------------------ from statements

def test_the_ratio_of_provision_to_pretax_income_is_used():
    rate = _tax_rate_from_statements(payload({"Tax Provision": 2861e6, "Pretax Income": 15998e6}))
    assert rate is not None and abs(rate - 0.1788) < 0.001


def test_yahoos_own_calc_rate_wins_when_present():
    """The workbook prefers it, so the Python side must agree."""
    rate = _tax_rate_from_statements(payload({
        "Tax Rate For Calcs": 0.21, "Tax Provision": 100.0, "Pretax Income": 1000.0}))
    assert rate == 0.21


def test_a_tax_credit_year_is_refused_not_negated():
    """
    PC Jeweller booked a -9.7M provision on 7.1B of pretax income. A negative
    rate would discount debt at an after-tax cost ABOVE its pre-tax cost.
    """
    assert _tax_rate_from_statements(payload({"Tax Provision": -9.7e6, "Pretax Income": 7.1e9})) is None


def test_a_loss_making_year_is_refused():
    assert _tax_rate_from_statements(payload({"Tax Provision": 50.0, "Pretax Income": -1000.0})) is None


def test_an_absurd_rate_is_refused():
    assert _tax_rate_from_statements(payload({"Tax Provision": 900.0, "Pretax Income": 1000.0})) is None


def test_the_newest_period_wins():
    data = {"financial_statements": {"income_statement": {
        "2023-01-31": {"Tax Provision": 400.0, "Pretax Income": 1000.0},
        "2025-01-31": {"Tax Provision": 150.0, "Pretax Income": 1000.0},
    }}}
    assert abs(_tax_rate_from_statements(data) - 0.15) < 1e-9


def test_an_older_usable_year_is_used_when_the_newest_is_not():
    data = {"financial_statements": {"income_statement": {
        "2024-01-31": {"Tax Provision": 200.0, "Pretax Income": 1000.0},
        "2025-01-31": {"Tax Provision": -5.0, "Pretax Income": 1000.0},   # credit year
    }}}
    assert abs(_tax_rate_from_statements(data) - 0.20) < 1e-9


def test_no_statements_yields_nothing():
    for bad in ({}, None, {"financial_statements": {}}, {"financial_statements": {"income_statement": {}}}):
        assert _tax_rate_from_statements(bad) is None


# ------------------------------------------------------------ the chain

def test_an_explicit_company_rate_still_wins():
    cd = {"growth_profitability": {"effective_tax_rate": 0.19}}
    assert _effective_tax_rate(cd, payload({"Tax Provision": 100.0, "Pretax Income": 1000.0})) == 0.19


def test_the_statement_rate_is_used_when_company_data_has_none():
    """The real case — company_data NEVER carries one."""
    rate = _effective_tax_rate({}, payload({"Tax Provision": 150.0, "Pretax Income": 1000.0}))
    assert abs(rate - 0.15) < 1e-9
    assert rate != _TAX_DEFAULT


def test_an_etf_with_no_income_statement_keeps_the_default():
    assert _effective_tax_rate({}, {}) == _TAX_DEFAULT


def test_the_old_signature_still_works():
    """capm_components is called from two places; one passes no payload."""
    assert _effective_tax_rate({}) == _TAX_DEFAULT
