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


def test_qualitative_scores_do_not_manufacture_a_return_forecast():
    calc = RecommendationCalculator(sector="Financial Services")
    baseline = calc.calculate_fixed_numbers(**numbers(
        fair_value=485.0, catalyst_score_pct=0, risk_score_pct=0,
        momentum_score_pct=0))
    noisy = calc.calculate_fixed_numbers(**numbers(
        fair_value=485.0, catalyst_score_pct=25, risk_score_pct=1,
        momentum_score_pct=10))
    assert noisy["expected_return_pct_12m"] == baseline["expected_return_pct_12m"] == -3.0
    assert noisy["targets"]["m12"]["price"] == 485.0
    assert noisy["inputs"]["qualitative_signals_used_in_target"] is False


def test_target_is_not_arbitrarily_capped_away_from_published_fair_value():
    calc = RecommendationCalculator(sector="Financial Services")
    out = calc.calculate_fixed_numbers(**numbers(
        current_price=100.0, dcf_perpetual=150.0, dcf_exit=170.0,
        fair_value=160.0, analyst_target=170.0, analyst_count=20))
    assert out["inputs"]["cap_applied"] is False
    assert out["expected_return_pct_12m"] == 60.0
    assert out["targets"]["m12"]["price"] == 160.0


def test_short_horizon_paths_are_not_invented():
    calc = RecommendationCalculator(sector="Technology")
    out = calc.calculate_fixed_numbers(**numbers())
    assert out["targets"]["m3"]["price"] is None
    assert out["targets"]["m6"]["price"] is None
    assert out["target_basis"] == "published_intrinsic_value_convergence"


def test_no_return_cap_is_presented_as_model_evidence():
    calc = RecommendationCalculator(sector="Technology")
    i = calc.calculate_fixed_numbers(**numbers())["inputs"]
    assert i["cap_applied"] is False
    assert i["cap_pct"] is None


def test_rating_uses_the_same_blended_fair_value_the_report_shows():
    calc = RecommendationCalculator(sector="Technology")
    out = calc.calculate_fixed_numbers(**numbers(
        current_price=200.0,
        dcf_perpetual=50.0,
        dcf_exit=60.0,
        fair_value=220.0,
        catalyst_score_pct=0.0,
        risk_score_pct=0.0,
        momentum_score_pct=0.0,
    ))
    assert out["inputs"]["valuation_basis"] == "blended_fair_value"
    assert out["inputs"]["raw_val_gap_pct"] == 10.0
    assert out["expected_return_pct_12m"] == 10.0
    assert out["rating"] == "HOLD"


def test_rating_bands_are_symmetric_around_hold():
    calc = RecommendationCalculator()
    assert calc._determine_rating(14.99) == "HOLD"
    assert calc._determine_rating(-14.99) == "HOLD"
    assert calc._determine_rating(15.0) == "BUY"
    assert calc._determine_rating(-15.0) == "SELL"
    assert calc._determine_rating(30.0) == "STRONG BUY"
    assert calc._determine_rating(-30.0) == "STRONG SELL"


def test_consensus_is_recorded_as_a_cross_check_not_added_to_return():
    calc = RecommendationCalculator()
    out = calc.calculate_fixed_numbers(**numbers(
        current_price=100.0,
        dcf_perpetual=100.0,
        dcf_exit=100.0,
        fair_value=100.0,
        analyst_target=150.0,
        analyst_count=25,
        catalyst_score_pct=0.0,
        risk_score_pct=0.0,
        momentum_score_pct=0.0,
    ))
    assert out["expected_return_pct_12m"] == 0.0
    assert out["inputs"]["analyst_target_gap_pct"] == 50.0
    assert out["inputs"]["analyst_count"] == 25


def test_well_covered_opposite_consensus_withholds_the_call_symmetrically():
    calc = RecommendationCalculator()
    common = dict(
        catalyst_score_pct=0.0, risk_score_pct=0.0,
        momentum_score_pct=0.0, hist_vol_annual_pct=20.0,
        analyst_count=20,
    )
    bearish = calc.calculate_fixed_numbers(
        ticker="X", current_price=100.0, dcf_perpetual=30.0, dcf_exit=30.0,
        fair_value=30.0, analyst_target=120.0, **common)
    bullish = calc.calculate_fixed_numbers(
        ticker="X", current_price=100.0, dcf_perpetual=170.0, dcf_exit=170.0,
        fair_value=170.0, analyst_target=80.0, **common)
    assert bearish["expected_return_pct_12m"] is None
    assert bearish["rating"] == "NOT RATED"
    assert bullish["expected_return_pct_12m"] is None
    assert bullish["rating"] == "NOT RATED"
    assert bearish["rating_confidence"] is bullish["rating_confidence"] is None
    assert bearish["inputs"]["consensus_alignment"] == "conflicting"


def test_well_covered_analyst_ratings_are_not_discarded_when_target_is_neutral():
    calc = RecommendationCalculator()
    out = calc.calculate_fixed_numbers(**numbers(
        current_price=100.0,
        dcf_perpetual=40.0,
        dcf_exit=50.0,
        fair_value=45.0,
        analyst_target=98.0,
        analyst_count=39,
        analyst_rating="strong_buy",
        analyst_rating_count=53,
        catalyst_score_pct=0.0,
        risk_score_pct=0.0,
        momentum_score_pct=0.0,
    ))
    assert out["inputs"]["analyst_target_gap_pct"] == -2.0
    assert out["inputs"]["analyst_rating"] == "strong_buy"
    assert out["inputs"]["analyst_rating_count"] == 53
    assert out["inputs"]["consensus_alignment"] == "conflicting"
    assert out["rating"] == "NOT RATED"
    assert out["rating_confidence"] is None


def test_external_alignment_is_auditable_even_when_publication_is_withheld():
    calc = RecommendationCalculator()
    out = calc.calculate_fixed_numbers(**numbers(
        current_price=100.0,
        dcf_perpetual=40.0,
        dcf_exit=50.0,
        fair_value=45.0,
        analyst_rating="buy",
        analyst_rating_count=20,
        valuation_reliability={
            "point_estimate_withheld": True,
            "withheld_reason": "Independent evidence conflicts.",
        },
    ))
    assert out["rating"] == "NOT RATED"
    assert out["inputs"]["consensus_alignment"] == "conflicting"


def test_malformed_numeric_provider_inputs_fail_neutral_not_with_an_exception():
    calc = RecommendationCalculator()
    out = calc.calculate_fixed_numbers(**numbers(
        current_price="not-a-price",
        dcf_perpetual=float("nan"),
        dcf_exit=True,
        catalyst_score_pct="high",
        risk_score_pct={"bad": "shape"},
        momentum_score_pct=float("inf"),
        hist_vol_annual_pct=-1,
        analyst_target=120.0,
        analyst_count="many",
        analyst_rating="buy",
        analyst_rating_count=float("inf"),
    ))

    assert out["rating"] == "NOT RATED"
    assert out["price_available"] is False
    assert out["inputs"]["analyst_count"] == 0
    assert out["inputs"]["analyst_rating_count"] == 0
    assert out["inputs"]["hist_vol_annual_pct"] == 18.0


def test_company_context_formats_percentages_and_multiples_for_humans():
    from recommendation_engine import RecommendationEngineV3

    prompt = RecommendationEngineV3()._build_explainer_prompt(
        {"rating_available": True}, {"evidence": []},
        {
            "revenue_growth": .16, "net_margin": .28, "roe": 1.49,
            "debt_to_equity": .78, "pe_trailing": 29.123,
        }, {}, citations_enabled=False,
    )
    assert '"revenue_growth": "16.0%"' in prompt
    assert '"net_margin": "28.0%"' in prompt
    assert '"roe": "149.0%"' in prompt
    assert '"debt_equity": "0.78x"' in prompt
    assert '"pe_ratio": "29.12x"' in prompt


def test_limited_news_is_not_described_as_unavailable_when_articles_exist():
    from recommendation_engine import RecommendationEngineV3

    prompt = RecommendationEngineV3()._build_explainer_prompt(
        {"rating_available": True}, {"evidence": []}, {}, {}, citations_enabled=False)
    # No freshness object genuinely means unavailable.
    assert "No source-dated news evidence is available" in prompt

    limited = RecommendationEngineV3()._build_explainer_prompt(
        {"rating_available": True},
        {"evidence": [], "news_freshness": {"status": "limited", "fresh_articles": 8},
         "articles_analyzed": 8},
        {}, {}, citations_enabled=False,
    )
    assert "News coverage is limited (8 source-dated articles)" in limited
    assert "insufficient/limited, not unavailable" in limited


def test_fallback_recommendation_keeps_the_rating_confidence():
    from recommendation_engine import RecommendationEngineV3

    text = RecommendationEngineV3()._minimal_recommendation({
        "rating": "SELL",
        "rating_confidence": "low",
        "price_available": False,
    })
    assert "### Investment Rating: SELL" in text
    assert "**Rating Confidence**: Low" in text


def test_unreliable_valuation_cannot_publish_a_rating_or_target():
    calc = RecommendationCalculator()
    out = calc.calculate_fixed_numbers(**numbers(
        current_price=100.0,
        dcf_perpetual=25.0,
        dcf_exit=125.0,
        fair_value=75.0,
        valuation_reliability={
            "band": "unreliable",
            "dispersion_ratio": 5.0,
            "point_estimate_withheld": True,
            "range_low": 25.0,
            "range_high": 125.0,
        },
    ))
    assert out["rating"] == "NOT RATED"
    assert out["rating_available"] is False
    assert out["rating_confidence"] is None
    assert out["expected_return_pct_12m"] is None
    assert out["targets"]["m12"]["price"] is None
    assert "do not converge" in out["rating_withheld_reason"]


def test_wide_valuation_withholds_the_point_view():
    calc = RecommendationCalculator()
    out = calc.calculate_fixed_numbers(**numbers(
        valuation_reliability={
            "band": "wide",
            "dispersion_ratio": 2.0,
            "point_estimate_withheld": False,
            "range_low": 240.0,
            "range_high": 480.0,
        },
    ))
    assert out["rating_available"] is False
    assert out["rating"] == "NOT RATED"
    assert out["rating_confidence"] is None
    assert out["targets"]["m12"]["price"] is None


def test_historical_volatility_uses_saved_daily_prices():
    from report_agent import historical_volatility_pct

    closes = [100 * (1.01 if i % 2 else 0.99) ** i for i in range(40)]
    data = {"market_data": {"historical_prices": {"prices": {
        f"2026-01-{i + 1:02d}": {"close": close}
        for i, close in enumerate(closes)
    }}}}
    value = historical_volatility_pct(data)
    assert isinstance(value, float) and value > 0
