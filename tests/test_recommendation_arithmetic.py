"""
TWO BUGS in the recommendation path, both visible to a reader.

1. SENTIMENT WAS LOST. report_agent.extract_news_analysis renamed
   `analysis_summary` to `summary`, but the dict it returns is handed to
   RecommendationEngineV3 as its `screening_data`, and the engine reads the RAW
   key (recommendation_engine.py:108 and :146). Both lookups missed on every run
   ever produced: NVDA's screen was `bearish` over 30 articles and reached the
   engine as `neutral` over 0. Sentiment is 20% of expected return via
   calculate_momentum, so every bearish screen scored 3pp too optimistic; and
   `articles_analyzed == 0` trips the has_news_evidence guard, so a run with real
   news could disable its own citations and say the evidence was unavailable.

2. THE BREAKDOWN DID NOT ADD UP. The ±30% cap is applied AFTER the weighted sum,
   but the methodology section printed the three weighted lines directly above
   the CAPPED total. A shipped VOO report reads -32.0 +2.6 -2.0 under a Total of
   -30.0. On a product whose claim is that its figures are checkable, arithmetic
   that visibly fails to add up is the worst kind of error to print.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from recommendation_calculator import RecommendationCalculator
from report_agent import extract_news_analysis

SCREEN = {
    "analysis_summary": {"overall_sentiment": "bearish", "articles_analyzed": 30,
                         "confidence_score": 0.86},
    "catalysts": [{"description": "a"}],
    "risks": [{"description": "b"}],
    "mitigations": [],
    "analysis_method": "batch_llm",
}


# ------------------------------------------------- 1. sentiment survives

def test_the_engine_can_still_read_the_raw_key():
    news = extract_news_analysis(SCREEN)
    assert news["analysis_summary"]["overall_sentiment"] == "bearish"
    assert news["analysis_summary"]["articles_analyzed"] == 30


def test_the_report_sections_still_read_summary():
    """Both names are carried; renaming one broke the other consumer."""
    news = extract_news_analysis(SCREEN)
    assert news["summary"]["overall_sentiment"] == "bearish"


def test_both_names_are_the_same_object():
    news = extract_news_analysis(SCREEN)
    assert news["summary"] == news["analysis_summary"]


def test_a_screen_with_no_summary_does_not_invent_one():
    news = extract_news_analysis({"catalysts": [], "risks": []})
    assert news["analysis_summary"] == {}
    assert news["summary"] == {}


def test_sentiment_actually_changes_momentum():
    """Why the lost key mattered: it is 20% of expected return."""
    calc = RecommendationCalculator(sector="Technology")
    bear = calc.calculate_momentum(188.15, 86.62, 212.19, "bearish")
    neut = calc.calculate_momentum(188.15, 86.62, 212.19, "neutral")
    assert abs(neut - bear) >= 2.0, "a lost sentiment is not a rounding difference"


def test_the_real_nvda_screen_round_trips():
    path = Path("data/zanwen/NVDA/115/screened/screening_data.json")
    if not path.is_file():
        import pytest
        pytest.skip("no run data on this machine")
    news = extract_news_analysis(json.loads(path.read_text()))
    assert news["analysis_summary"]["overall_sentiment"] == "bearish"
    assert news["analysis_summary"]["articles_analyzed"] == 30


# ------------------------------------------------ 2. the breakdown sums

def numbers(**kw):
    base = dict(ticker="X", current_price=500.0, dcf_perpetual=480.0, dcf_exit=490.0,
                catalyst_score_pct=5.0, risk_score_pct=2.0,
                momentum_score_pct=3.0, hist_vol_annual_pct=18.0)
    base.update(kw)
    return base


def lines_sum(inputs):
    return (0.4 * inputs["adj_val_gap_pct"]
            + 0.4 * inputs["net_catalyst_risk_pct"]
            + 0.2 * inputs["momentum_score_pct"])


def test_the_three_lines_sum_to_the_uncapped_figure():
    calc = RecommendationCalculator(sector="Financial Services")
    out = calc.calculate_fixed_numbers(**numbers())
    i = out["inputs"]
    assert abs(lines_sum(i) - i["uncapped_expected_return_pct"]) < 0.05


def test_a_capped_run_reports_the_cap_rather_than_hiding_it():
    """The shipped VOO shape: lines summing past the cap."""
    calc = RecommendationCalculator(sector="Financial Services")
    out = calc.calculate_fixed_numbers(**numbers(
        dcf_perpetual=20.0, dcf_exit=25.0, momentum_score_pct=-10.0, risk_score_pct=0.0,
        catalyst_score_pct=6.5))
    i = out["inputs"]
    assert i["cap_applied"] is True
    assert abs(lines_sum(i) - i["uncapped_expected_return_pct"]) < 0.05
    assert out["expected_return_pct_12m"] == -i["cap_pct"]
    assert abs(i["uncapped_expected_return_pct"]) > i["cap_pct"]


def test_an_uncapped_run_says_so():
    calc = RecommendationCalculator(sector="Technology")
    out = calc.calculate_fixed_numbers(**numbers())
    i = out["inputs"]
    assert i["cap_applied"] is False
    assert abs(out["expected_return_pct_12m"] - i["uncapped_expected_return_pct"]) < 0.05


def test_the_cap_is_reported_so_the_report_can_name_it():
    calc = RecommendationCalculator(sector="Technology")
    i = calc.calculate_fixed_numbers(**numbers())["inputs"]
    assert i["cap_pct"] == 30.0
