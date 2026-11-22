"""THE RISK: a valuation built on last quarter's sales days after the company reported a new one, shown as current.

NVIDIA reported its October quarter on 17 Nov 2026 ($115.8B of sales). On 21-22 Nov Yahoo's quarter table still ended
in July, so VYNN started from $303B instead of $362B and placed NVIDIA half-way through its fiscal year instead of
three-quarters. The fixtures below are NVIDIA's real figures (SEC company facts and filings list, Yahoo summary, as of
22 Nov 2026), trimmed.
"""
from datetime import date

import pytest

import src.latest_quarter as lq
from src.agents.fm import netcache
from src.agents.fm.assumption_grounding import _rolling_consensus_revenue_path

# NVIDIA's three-month revenue facts (SEC XBRL, us-gaap:Revenues), plus the FY2026 10-K year and a nine-month span.
NVDA_FACTS = [
    {"start": "2025-04-28", "end": "2025-07-27", "val": 46_743e6, "form": "10-Q", "filed": "2025-08-27"},
    {"start": "2025-07-28", "end": "2025-10-26", "val": 57_006e6, "form": "10-Q", "filed": "2025-11-19"},
    {"start": "2025-01-27", "end": "2025-10-26", "val": 147_811e6, "form": "10-Q", "filed": "2025-11-19"},
    {"start": "2025-01-27", "end": "2026-01-25", "val": 215_938e6, "form": "10-K", "filed": "2026-02-25"},
    {"start": "2025-01-27", "end": "2025-04-27", "val": 44_062e6, "form": "10-Q", "filed": "2025-05-28"},
    {"start": "2026-01-26", "end": "2026-04-26", "val": 81_614e6, "form": "10-Q", "filed": "2026-05-20"},
    {"start": "2026-04-27", "end": "2026-07-26", "val": 96_221e6, "form": "10-Q", "filed": "2026-08-26"},
]
NVDA_FILINGS = {"filings": {"recent": {
    "form": ["144", "8-K", "13F-HR", "8-K", "8-K"],
    "filingDate": ["2026-11-19", "2026-11-17", "2026-11-16", "2026-11-12", "2026-08-26"],
    "items": ["", "2.02,9.01", "", "5.02,9.01", "2.02,9.01"],
    "accessionNumber": ["a1", "0001045810-26-000085", "a3", "a4", "a5"],
}}}
YAHOO_NOW = {"totalRevenue": 361_800e6, "mostRecentQuarter": 1792886400}   # 2026-10-25 00:00 UTC


def _bridge(revenue=302_970e6, period="2026-07-31"):
    return {"status": "current", "latest_period": period, "normalized": {"revenue": revenue}}


@pytest.fixture
def sec(monkeypatch):
    """The SEC as NVIDIA's real data stood on 22 Nov: facts to July, a results release on 17 Nov."""
    state = {"facts": list(NVDA_FACTS), "filings": NVDA_FILINGS}
    monkeypatch.setattr(lq, "_cik", lambda ticker: 1045810 if ticker == "NVDA" else None)

    def fake(url, cache_name):
        if "companyconcept" in url:
            return {"units": {"USD": state["facts"]}} if url.endswith("/Revenues.json") else None
        return state["filings"]
    monkeypatch.setattr(lq, "_sec_json", fake)
    return state


def test_quarters_include_the_fourth_quarter_derived_from_the_year():
    quarters = lq.quarters_from_facts(NVDA_FACTS)
    q4 = quarters[date(2026, 1, 25)][0]
    assert q4 == pytest.approx(215_938e6 - 44_062e6 - 46_743e6 - 57_006e6)      # 68,127m, as NVIDIA reported
    twelve = lq.twelve_months(quarters)
    assert twelve["period_end"] == "2026-07-26"
    assert twelve["revenue"] == pytest.approx(57_006e6 + q4 + 81_614e6 + 96_221e6)


def test_nvidia_on_22_nov_takes_yahoo_s_newer_quarter(sec):
    update = lq.fresh_revenue(_bridge(), "NVDA", YAHOO_NOW)
    fresh = update["fresh_revenue"]
    assert fresh["source"] == "yahoo_summary" and fresh["period_end"] == "2026-10-25"
    assert fresh["revenue"] == pytest.approx(361_800e6)
    assert fresh["previous_period_end"] == "2026-07-31"


def test_once_the_quarterly_report_is_filed_the_sec_figure_wins_and_yahoo_cross_checks(sec):
    sec["facts"] = NVDA_FACTS + [
        {"start": "2026-07-27", "end": "2026-10-25", "val": 115_800e6, "form": "10-Q", "filed": "2026-11-24"}]
    fresh = lq.fresh_revenue(_bridge(), "NVDA", YAHOO_NOW)["fresh_revenue"]
    assert fresh["source"] == "sec_xbrl" and fresh["period_end"] == "2026-10-25"
    assert fresh["revenue"] == pytest.approx(68_127e6 + 81_614e6 + 96_221e6 + 115_800e6)
    assert fresh["cross_check"]["source"] == "yahoo_summary" and abs(fresh["cross_check"]["difference"]) < 0.01


def test_results_released_but_no_figures_yet_is_said_not_hidden(sec):
    update = lq.fresh_revenue(_bridge(), "NVDA", info={})          # Yahoo's summary not updated either
    assert "fresh_revenue" not in update
    assert update["results_pending"]["filed"] == "2026-11-17"
    assert update["results_pending"]["figures_through"] == "2026-07-31"


def test_the_bridge_s_own_quarter_release_is_not_mistaken_for_a_later_one(sec):
    sec["filings"] = {"filings": {"recent": {"form": ["8-K"], "filingDate": ["2026-08-26"],
                                             "items": ["2.02,9.01"], "accessionNumber": ["a5"]}}}
    assert lq.fresh_revenue(_bridge(), "NVDA", info={}) == {}


def test_nothing_newer_changes_nothing(sec):
    current = {"totalRevenue": 302_970e6, "mostRecentQuarter": 1785024000}   # 2026-07-26
    sec["filings"] = {"filings": {"recent": {"form": [], "filingDate": [], "items": [], "accessionNumber": []}}}
    assert lq.fresh_revenue(_bridge(), "NVDA", current) == {}


def test_an_implausible_figure_is_refused(sec):
    wrong_unit = {"totalRevenue": 361_800e3, "mostRecentQuarter": 1792886400}   # thousands, not units
    update = lq.fresh_revenue(_bridge(), "NVDA", wrong_unit)
    assert "fresh_revenue" not in update and "results_pending" in update


def test_non_us_companies_use_yahoo_only_and_failures_change_nothing(monkeypatch):
    monkeypatch.setattr(lq, "_cik", lambda ticker: None)
    assert lq.fresh_revenue(_bridge(), "HSN.AX", YAHOO_NOW)["fresh_revenue"]["source"] == "yahoo_summary"

    def boom(*a, **k):
        raise RuntimeError("network down")
    monkeypatch.setattr(lq, "yahoo_twelve_month_revenue", boom)
    assert lq.fresh_revenue(_bridge(), "HSN.AX", YAHOO_NOW) == {}
    assert lq.fresh_revenue({"status": "stale"}, "NVDA", YAHOO_NOW) == {}


def test_switched_off_by_environment(monkeypatch, sec):
    monkeypatch.setenv("VYNN_FRESH_RESULTS", "0")
    assert lq.fresh_revenue(_bridge(), "NVDA", YAHOO_NOW) == {}


def _nvda_grounding(fresh=None):
    bridge = {**_bridge(), "status": "current"}
    if fresh:
        bridge["fresh_revenue"] = fresh
    return {"financial_statements": {"income_statement": {"2026-01-31": {"Total Revenue": 215_938e6}}},
            "ttm_bridge": bridge}


CONSENSUS = {"0y": (423_754e6, 49), "+1y": (725_522e6, 57)}   # Yahoo, 22 Nov 2026


def test_the_forecast_starts_from_the_new_quarter_and_the_right_point_in_the_year():
    stale = _rolling_consensus_revenue_path(_nvda_grounding(), CONSENSUS, 0.025)
    fresh = _rolling_consensus_revenue_path(
        _nvda_grounding({"revenue": 361_800e6, "period_end": "2026-10-25", "source": "yahoo_summary"}), CONSENSUS, 0.025)
    assert stale["base_revenue_source"] == "ttm_bridge" and stale["fiscal_year_progress"] == pytest.approx(181 / 365)
    assert fresh["base_revenue_source"] == "yahoo_summary" and fresh["base_revenue"] == pytest.approx(361_800e6)
    assert fresh["fiscal_year_progress"] == pytest.approx(267 / 365)
    # Next-twelve-months sales against the base: stale +89%, fresh about +78%.
    assert stale["revenue_growth_rates"][0] == pytest.approx(0.89, abs=0.02)
    assert fresh["revenue_growth_rates"][0] == pytest.approx(0.78, abs=0.02)


def test_a_fresh_quarter_that_closes_the_fiscal_year_is_not_blended_across_it():
    closing = {"revenue": 380_000e6, "period_end": "2027-01-25", "source": "yahoo_summary"}
    path = _rolling_consensus_revenue_path(_nvda_grounding(closing), CONSENSUS, 0.025)
    assert path["base_revenue_source"] == "ttm_bridge" and path["period_end"] == "2026-07-31"


def test_sec_requests_carry_the_contact_email_and_others_do_not(monkeypatch):
    monkeypatch.delenv("SEC_CONTACT_EMAIL", raising=False)
    assert netcache._user_agent("https://data.sec.gov/submissions/CIK0001045810.json") == "VYNN AI zanwen@vynnai.com"
    assert netcache._user_agent("https://www.sec.gov/files/company_tickers.json") == "VYNN AI zanwen@vynnai.com"
    assert "@" not in netcache._user_agent("https://query1.finance.yahoo.com/v7/finance/quote")
    assert "@" not in netcache._user_agent("https://notsec.gov.example.com/x")
    monkeypatch.setenv("SEC_CONTACT_EMAIL", "ops@vynnai.com")
    assert netcache._user_agent("https://data.sec.gov/x") == "VYNN AI ops@vynnai.com"
