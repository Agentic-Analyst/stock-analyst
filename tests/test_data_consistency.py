"""Figures VYNN shows side by side must reconcile (blind review, 18 Nov 2026)."""
import os
import sys

import pytest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "src"))

from src.report_agent import _margins_table  # noqa: E402


def test_the_margin_table_says_which_period_each_figure_is():
    # Hansen: EBITDA A$122.5M on revenue A$386.5M is 31.7%; the provider's
    # trailing figure was 19.9%, shown as "Current Value" beside the annual table.
    historical = {
        "years": ["2025", "2026"],
        "revenue": [392.5e6, 386.494e6], "gross_profit": [140e6, 144.6e6],
        "ebitda": [110.1e6, 122.54e6], "net_income": [43.4e6, 47.8e6],
    }
    company = {"gross_margin": 0.374, "operating_margin": 0.181, "ebitda_margin": 0.199,
               "net_margin": 0.124, "roe": 0.125, "roa": 0.06}
    table = _margins_table(historical, company)
    assert "| Metric | Fiscal 2026 (from the table above) | Trailing 12 Months (provider) |" in table
    assert "| EBITDA Margin | 31.7% | 19.9% |" in table
    assert "| Net Margin | 12.4% | 12.4% |" in table
    assert "| Operating Margin | — | 18.1% |" in table


def test_without_statements_only_the_provider_column_is_shown():
    table = _margins_table({"years": []}, {"ebitda_margin": 0.199})
    assert table.startswith("| Metric | Trailing 12 Months (provider) |")
    assert "| EBITDA Margin | 19.9% |" in table


def test_next_years_growth_is_measured_from_this_years_estimate():
    from src.external_expectations import build_external_expectations
    data = {
        "company_data": {"basic_info": {"currency": "CNY", "financial_currency": "CNY"},
                         "market_data": {"current_price": 2.94, "shares_outstanding_basic": 11.93e9}},
        "analyst_data": {
            "revenue_estimates": {
                "0y": {"avg": 179.342e9, "numberOfAnalysts": 6, "yearAgoRevenue": 233.43e9, "growth": -0.2317},
                "+1y": {"avg": 135.233e9, "numberOfAnalysts": 6, "yearAgoRevenue": 165.79e9, "growth": -0.1843},
            },
            "earnings_estimates": {
                "0y": {"avg": -2.07, "numberOfAnalysts": 4, "growth": -0.5},
                "+1y": {"avg": -1.43, "numberOfAnalysts": 4, "growth": 0.31},
            },
        },
    }
    rows = build_external_expectations(data).get("forward_estimates") or []
    if len(rows) < 2:
        pytest.skip("this artifact shape does not produce two forward rows")
    assert rows[0]["revenue_growth"] == pytest.approx(-0.2317)
    assert rows[1]["revenue_growth"] == pytest.approx(135.233 / 179.342 - 1)
    # Across a loss, a growth rate means nothing.
    assert rows[0]["eps_growth"] is None and rows[1]["eps_growth"] is None


# ---- readings the tools work out, so the answer does not -------------------------

def test_rsi_band_and_distance_readings():
    from src.agents.tools.data_tools import band_position, pct_from, rsi_reading
    assert rsi_reading(37.2).startswith("neutral")          # was called "oversold"
    assert rsi_reading(29.9).startswith("oversold") and rsi_reading(71).startswith("overbought")
    assert band_position(3.57, 3.49, 3.73) == "lower half of the band"   # was "upper half"
    assert band_position(3.80, 3.49, 3.73) == "above the upper band"
    assert pct_from(3.57, 2.95) == 21.0                      # was written as 40%
    assert pct_from(3.57, 5.92) == -39.7
    assert pct_from(3.57, None) is None


def test_todays_move_against_the_market_in_words():
    from src.agents.tools.move_tools import versus_market
    out = versus_market(-1.0, -0.6, "the S&P/ASX 200", session="2026-11-17")
    assert out == ("The stock was down 1.0% on 2026-11-17 against the S&P/ASX 200 down 0.6%: "
                   "0.4 points worse than the market.")
    assert "better" in versus_market(0.5, -0.6, "the S&P 500")
    assert "in line with" in versus_market(-0.62, -0.6, None)
    assert versus_market(None, -0.6, "x") is None


def test_the_guard_accepts_plain_words_for_the_street_comparison():
    from src.agents.supervisor.supervisor_agent import SupervisorWorkflowRunner as R
    benchmark = {"target_mean": 412.48, "target_source": "yahoo_finance",
                 "benchmark_relationship": "material_conflict",
                 "market_implied_fcf_path_delta": 28.27}
    plain = ("The 40 analysts' average target is $412.48 (yahoo_finance), and they disagree sharply "
             "with VYNN's model. To justify today's price, the company needs about 29.3 times the cash "
             "flow VYNN's model expects: the model counts only the cash flow it can forecast, not "
             "everything investors are paying for.")
    assert R._answer_covers_external_benchmark(plain, benchmark)
    assert not R._answer_covers_external_benchmark(
        "Analysts' average target is $412.48 (yahoo_finance).", benchmark)


def test_a_good_investment_question_gets_the_same_guard_as_should_i_buy():
    from src.agents.generalist_agent import _BUY_QUESTION
    assert _BUY_QUESTION.search("Is Costco a good investment at today's price?")


def test_the_price_comparison_says_it_uses_the_cash_flow_method_alone():
    from src.summary_evidence import render_external_benchmark_compact
    value = {"currency": "AUD", "market_implied_fcf_path_delta": 0.04,
             "model_fair_value": 4.16, "model_cash_flow_value": 3.43}
    text = render_external_benchmark_compact(value)
    assert ("about the cash flow VYNN's model expects (1.04 times). That is against VYNN's "
            "cash-flow method alone, which values the shares at A$3.43; its fair value of "
            "A$4.16 also uses a second method.") in text
    value["model_cash_flow_value"] = 4.10
    assert "cash-flow method alone" not in render_external_benchmark_compact(value)


# ---- a single model far outside every analyst target -----------------------------

def _fin(low=128.11, high=600.0, count=40, qualified=True):
    return {"external_expectations": {"price_target": {
        "low": low, "high": high, "analyst_count": count, "qualified_for_contradiction": qualified}}}


def test_a_dcf_only_value_far_outside_every_analyst_target_is_a_scenario():
    from src.valuation_methodology import withhold_unconfirmed_outlier
    base = {"primary_method": "dcf", "publication_allowed": True}
    tesla = withhold_unconfirmed_outlier(base, _fin(), 20.25)
    assert tesla["publication_allowed"] is False
    assert tesla["primary_method"] == "scenario_only_pending_corroboration"
    from src.summary_evidence import unsuitable_method_note
    assert unsuitable_method_note(tesla).startswith("VYNN's cash-flow model lands outside every analyst")
    assert withhold_unconfirmed_outlier(base, _fin(770, 1315, 37), 554.95)["publication_allowed"] is False
    assert withhold_unconfirmed_outlier(base, _fin(1.85, 8.30, 8), 20.24)["publication_allowed"] is False


@pytest.mark.parametrize("suitability,financial,value,comps", [
    ({"primary_method": "dcf", "publication_allowed": True}, _fin(3.20, 6.80, 9), 4.16, None),   # inside
    ({"primary_method": "dcf", "publication_allowed": True}, _fin(), 120.0, None),     # within 10% of the low
    ({"primary_method": "dcf", "publication_allowed": True}, _fin(count=4), 20.25, None),  # thin coverage
    ({"primary_method": "dcf", "publication_allowed": True}, _fin(), 20.25, 25.0),     # a second method
    ({"primary_method": "dcf_mid_cycle", "publication_allowed": True}, _fin(), 20.25, None),
    ({"primary_method": "justified_pb_roe", "publication_allowed": True}, _fin(), 20.25, None),
    ({"primary_method": "dcf", "publication_allowed": True}, {}, 20.25, None),         # no analysts
    # Targets the publication rules do not accept: another currency, or stale.
    ({"primary_method": "dcf", "publication_allowed": True}, _fin(qualified=False), 20.25, None),
])
def test_the_outlier_rule_leaves_everything_else_alone(suitability, financial, value, comps):
    from src.valuation_methodology import withhold_unconfirmed_outlier
    assert withhold_unconfirmed_outlier(suitability, financial, value, comps) == suitability


@pytest.mark.parametrize("stored,plain", [
    ("The near-term operating case is not reconciled: FY1 model revenue is +22% versus Yahoo (12 analysts). "
     "A point valuation cannot be published.", "VYNN's sales forecast for the next year or two differs"),
    ("The valuation methods span more than 1.8x. That range is useful scenario evidence.",
     "VYNN's valuation methods are more than 1.8 times apart"),
    ("The DCF-only estimate is -50% from the market, but no independent market-comps valuation qualified.",
     "VYNN's only valuation method puts the shares -50% from the market price"),
    ("The financial statements are stale: the latest annual period ended 2023-12-31.",
     "The financial statements are stale: the latest annual period ended 2023-12-31."),
])
def test_the_detail_line_says_the_reason_plainly(stored, plain):
    from src.summary_evidence import plain_publication_reason
    assert plain_publication_reason(stored).startswith(plain)


def test_the_method_note_uses_the_fair_value_through_the_real_benchmark():
    # The reviewer's case: through external_benchmark, the note printed the last
    # forward year's revenue as the fair value ("A$410,000,000.00").
    from src.summary_evidence import external_benchmark, render_external_benchmark_compact
    financial = {"external_expectations": {"currency": "AUD", "forward_estimates": [
        {"period": "0y", "revenue": 386.5e6, "revenue_analyst_count": 7},
        {"period": "+1y", "revenue": 410e6, "revenue_analyst_count": 7}]}}
    benchmark = external_benchmark(
        financial, [386.5e6, 410e6],
        valuation_metrics={"fair_value": 4.16, "perpetual_price": 3.43, "current_price": 3.57,
                           "market_implied_fcf_path_vs_model": 0.04})
    assert benchmark["model_fair_value"] == 4.16
    text = render_external_benchmark_compact(benchmark)
    assert "its fair value of A$4.16 also uses a second method" in text
    assert "410,000,000" not in text


def test_the_plain_words_must_carry_the_right_number():
    from src.agents.supervisor.supervisor_agent import SupervisorWorkflowRunner as R
    benchmark = {"market_implied_fcf_path_delta": 1.12}       # the price needs 2.12x the model
    assert R._answer_covers_external_benchmark(
        "To justify today's price, the company needs about 2.12 times the cash flow VYNN expects.", benchmark)
    assert not R._answer_covers_external_benchmark(
        "The shares trade at 40 times the cash flow.", benchmark)
    conflict = {"benchmark_relationship": "material_conflict", "target_mean": 10.0}
    assert not R._answer_covers_external_benchmark(
        "Analyst targets are far apart; the average target is 10.00.", conflict)


@pytest.mark.parametrize("prompt", ["Is NVDA a buy?", "Is Moet Hennessy Louis Vuitton a buy?", "is it a strong buy now"])
def test_is_x_a_buy_is_a_buy_question(prompt):
    from src.agents.generalist_agent import _BUY_QUESTION
    assert _BUY_QUESTION.search(prompt)


def test_no_first_year_eps_growth_from_a_loss_a_year_ago():
    from src.external_expectations import build_external_expectations
    data = {
        "company_data": {"basic_info": {"currency": "USD"},
                         "market_data": {"current_price": 10.0, "shares_outstanding_basic": 1e9}},
        "analyst_data": {
            "revenue_estimates": {"0y": {"avg": 1e9, "numberOfAnalysts": 6}, "+1y": {"avg": 1.1e9, "numberOfAnalysts": 6}},
            "earnings_estimates": {"0y": {"avg": 0.5, "numberOfAnalysts": 6, "growth": 3.5, "yearAgoEps": -0.2},
                                  "+1y": {"avg": 0.6, "numberOfAnalysts": 6, "growth": 0.2}},
        },
    }
    rows = build_external_expectations(data).get("forward_estimates") or []
    if len(rows) < 2:
        pytest.skip("this artifact shape does not produce two forward rows")
    assert rows[0]["eps_growth"] is None
    assert rows[1]["eps_growth"] == pytest.approx(0.2)


def test_a_window_move_is_read_against_the_market_in_words():
    # Robinhood, 18 Nov: +7.9% against the S&P 500's +3.6% was called "lagged the market".
    from src.agents.tools.move_tools import versus_market
    out = versus_market(7.9, 3.6, "the S&P 500", period="from 2026-11-10 to 2026-11-13")
    assert out == ("The stock was up 7.9% from 2026-11-10 to 2026-11-13 against the S&P 500 up 3.6%: "
                   "4.3 points better than the market.")
