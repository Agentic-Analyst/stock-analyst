import logging
from types import SimpleNamespace

from src.agents.supervisor import supervisor_agent


def test_immediate_answer_cannot_leak_withheld_value_or_unverified_sentiment(
        monkeypatch):
    captured = {}

    def fake_llm(messages, temperature=0):
        captured["prompt"] = messages[-1]["content"]
        return "Guarded answer", 0.0

    monkeypatch.setattr(supervisor_agent, "get_llm", lambda: fake_llm)
    raw = {
        "company_data": {"basic_info": {"currency": "EUR"}},
        "external_expectations": {
            "currency": "EUR",
            "price_target": {
                "mean": 200.0,
                "analyst_count": 20,
                "source": "yahoo_finance",
            },
            "recommendations": {},
            "forward_estimates": [{
                "revenue": 100e9,
                "revenue_analyst_count": 15,
            }],
        },
    }
    runner = supervisor_agent.SupervisorWorkflowRunner.__new__(
        supervisor_agent.SupervisorWorkflowRunner)
    runner.ticker = "TEST.PA"
    runner.user_prompt = "What is the valuation?"
    runner.logger = logging.getLogger("test_supervisor_guardrails")
    runner.state = SimpleNamespace(
        total_llm_cost=0.0,
        is_financial_data_collected=lambda: True,
        financial_data=SimpleNamespace(
            key_metrics={
                "basic_info": {"currency": "EUR"},
                "market_data": {"current_price": 300.0},
            },
            raw_data=raw,
        ),
        is_news_analyzed=lambda: True,
        news_analysis=SimpleNamespace(
            articles_count=2,
            overall_sentiment="bearish",
            freshness={"status": "limited"},
            catalysts=[],
            risks=[],
        ),
        is_model_generated=lambda: True,
        financial_model=SimpleNamespace(
            model_type="DCF",
            valuation_metrics={
                "fair_value": 167.67,
                "perpetual_price": 153.91,
                "exit_multiple_price": 183.79,
                "current_price": 300.0,
                "upside_vs_market": -0.44,
                "point_estimate_withheld": True,
                "publication_withheld_reason": "independent evidence conflicts",
                "model_revenue_forecast": [100e9],
            },
            assumptions={
                "revenue_growth_source": (
                    "yahoo_analyst_consensus_with_deterministic_fade"
                ),
            },
        ),
    )

    answer = runner._check_for_immediate_answer("model_generation_agent")

    assert answer.startswith("TEST.PA is NOT RATED")
    assert "€153.91–€183.79 EUR" in answer
    assert "independent evidence conflicts" in answer
    assert "Human-analyst and market benchmark reconciliation" in answer
    assert "EUR 200.00" in answer
    prompt = captured["prompt"]
    assert "Supported method range: €153.91-€183.79 EUR" in prompt
    assert "Rating / point fair value: NOT RATED / withheld" in prompt
    assert "Fair Value: €167.67" not in prompt
    assert "News Sentiment: unavailable" in prompt
    assert "News Sentiment: bearish" not in prompt
    assert "used as a model revenue anchor" in prompt


def test_guard_preserves_named_external_consensus_but_rejects_model_rating():
    runner = supervisor_agent.SupervisorWorkflowRunner.__new__(
        supervisor_agent.SupervisorWorkflowRunner)
    runner.ticker = "TEST"
    runner.state = SimpleNamespace(
        financial_data=SimpleNamespace(raw_data={}),
        news_analysis=None,
        financial_model=SimpleNamespace(
            assumptions={},
            valuation_metrics={
                "fair_value": 167.67,
                "perpetual_price": 153.91,
                "exit_multiple_price": 183.79,
                "upside_vs_market": -0.44,
                "point_estimate_withheld": True,
                "publication_withheld_reason": "independent evidence conflicts",
            },
        ),
    )

    external = (
        "TEST is NOT RATED and the supported range is $153.91–$183.79. "
        "The independent analyst consensus rating is BUY, but that is only a "
        "cross-check and not our intrinsic-value conclusion."
    )
    assert runner._guard_user_answer(external) == external

    unsafe = (
        "TEST is NOT RATED, but the model rating is SELL with a fair value of "
        "$167.67 and -44.0% implied return."
    )
    guarded = runner._guard_user_answer(unsafe)
    assert guarded.startswith("TEST is NOT RATED")
    assert "$153.91–$183.79 USD" in guarded
    assert "SELL" not in guarded
    assert "167.67" not in guarded
    assert "-44.0%" not in guarded


def test_withheld_equal_method_outputs_are_one_scenario_estimate_not_a_range():
    runner = supervisor_agent.SupervisorWorkflowRunner.__new__(
        supervisor_agent.SupervisorWorkflowRunner)
    runner.ticker = "TSM"
    runner.state = SimpleNamespace(
        financial_data=SimpleNamespace(
            key_metrics={"basic_info": {"currency": "TWD"}}, raw_data={}
        ),
        news_analysis=None,
        financial_model=SimpleNamespace(
            assumptions={},
            valuation_metrics={
                "perpetual_price": 13245.003,
                "exit_multiple_price": 13245.004,
                "point_estimate_withheld": True,
                "publication_withheld_reason": "single-method scenario only",
            },
        ),
    )

    answer = runner._safe_withheld_valuation_answer()

    assert "supported DCF scenario estimate" in answer
    assert "NT$13,245.00 TWD" in answer
    assert "valuation-method range" not in answer


def test_guard_removes_unverified_news_sentiment_without_dropping_valuation():
    runner = supervisor_agent.SupervisorWorkflowRunner.__new__(
        supervisor_agent.SupervisorWorkflowRunner)
    runner.ticker = "TEST"
    runner.state = SimpleNamespace(
        financial_data=SimpleNamespace(raw_data={}),
        news_analysis=SimpleNamespace(freshness={"status": "limited"}),
        financial_model=SimpleNamespace(
            assumptions={},
            valuation_metrics={
                "fair_value": 120.0,
                "point_estimate_withheld": False,
            },
        ),
    )

    guarded = runner._guard_user_answer(
        "The supported fair value is $120.00. News sentiment is bearish."
    )
    assert guarded == "The supported fair value is $120.00."


def test_withheld_answer_must_explain_reverse_dcf_and_human_benchmark():
    runner = supervisor_agent.SupervisorWorkflowRunner.__new__(
        supervisor_agent.SupervisorWorkflowRunner)
    runner.ticker = "TEST"
    runner.state = SimpleNamespace(
        financial_data=SimpleNamespace(
            key_metrics={"basic_info": {"currency": "USD"}},
            raw_data={
                "external_expectations": {
                    "currency": "USD",
                    "price_target": {
                        "mean": 210.0,
                        "analyst_count": 12,
                        "source": "benzinga",
                    },
                    "recommendations": {},
                    "forward_estimates": [],
                },
            },
        ),
        news_analysis=None,
        financial_model=SimpleNamespace(
            assumptions={},
            valuation_metrics={
                "perpetual_price": 100.0,
                "exit_multiple_price": 120.0,
                "point_estimate_withheld": True,
                "publication_withheld_reason": "market evidence conflicts",
                "market_implied_terminal_fcf": 15e9,
                "market_implied_fcf_vs_model": 0.573,
            },
        ),
    )

    guarded = runner._guard_user_answer(
        "TEST is NOT RATED and its supported range is $100-$120."
    )

    assert guarded.startswith("TEST is NOT RATED")
    assert "human-analyst mean target USD 210.00" in guarded
    assert "reverse DCF" in guarded
    assert "57.3% above the model" in guarded


def test_generic_analyst_mention_cannot_replace_numeric_benchmark():
    runner = supervisor_agent.SupervisorWorkflowRunner.__new__(
        supervisor_agent.SupervisorWorkflowRunner)
    runner.ticker = "TEST"
    runner.state = SimpleNamespace(
        financial_data=SimpleNamespace(
            key_metrics={"basic_info": {"currency": "USD"}},
            raw_data={
                "external_expectations": {
                    "currency": "USD",
                    "price_target": {
                        "mean": 210.0,
                        "analyst_count": 12,
                        "source": "benzinga",
                    },
                    "recommendations": {},
                    "forward_estimates": [],
                },
            },
        ),
        news_analysis=None,
        financial_model=SimpleNamespace(
            assumptions={},
            valuation_metrics={
                "perpetual_price": 100.0,
                "exit_multiple_price": 120.0,
                "point_estimate_withheld": True,
                "publication_withheld_reason": "market evidence conflicts",
            },
        ),
    )

    guarded = runner._guard_user_answer(
        "TEST is NOT RATED. Analysts were considered as a cross-check."
    )

    assert "human-analyst mean target USD 210.00" in guarded


def test_broad_answer_requires_multiple_available_firm_attributions():
    runner = supervisor_agent.SupervisorWorkflowRunner.__new__(
        supervisor_agent.SupervisorWorkflowRunner)
    runner.ticker = "TEST"
    runner.state = SimpleNamespace(
        financial_data=SimpleNamespace(
            key_metrics={"basic_info": {"currency": "USD"}},
            raw_data={"external_expectations": {
                "currency": "USD",
                "price_target": {},
                "recommendations": {},
                "forward_estimates": [],
                "analyst_observations": {
                    "source": "benzinga", "observation_count": 2,
                    "as_of": "2026-09-12",
                    "observations": [
                        {
                            "date": "2026-09-12", "firm": "Firm One",
                            "action": "Maintains", "rating": "buy",
                            "price_target": 150.0,
                            "source": "benzinga",
                            "content_role": "structured_external_analyst_observation",
                            "temporal_quality": {"status": "current"},
                        },
                        {
                            "date": "2026-09-11", "firm": "Firm Two",
                            "action": "Raises", "rating": "hold",
                            "price_target": 130.0,
                            "source": "benzinga",
                            "content_role": "structured_external_analyst_observation",
                            "temporal_quality": {"status": "current"},
                        },
                    ],
                },
            }},
        ),
        news_analysis=None,
        report=None,
        financial_model=SimpleNamespace(
            assumptions={},
            valuation_metrics={
                "fair_value": 120.0,
                "point_estimate_withheld": False,
            },
        ),
    )

    incomplete = runner._guard_user_answer(
        "TEST has a model fair value of $120. Analysts were reviewed.",
        require_full_benchmark=True,
    )
    assert incomplete.startswith("TEST audited report headline")
    assert "headline:;" not in incomplete
    assert "Firm One" in incomplete and "Firm Two" in incomplete

    complete = (
        "TEST has a model fair value of $120. Firm One maintained Buy with a "
        "$150 target, while Firm Two raised Hold with a $130 target; these "
        "analyst records are external benchmarks."
    )
    assert runner._guard_user_answer(
        complete, require_full_benchmark=True
    ) == complete


def test_withheld_answer_requires_dated_material_conflict_and_whole_path():
    runner = supervisor_agent.SupervisorWorkflowRunner.__new__(
        supervisor_agent.SupervisorWorkflowRunner)
    runner.ticker = "AAPL"
    runner.state = SimpleNamespace(
        financial_data=SimpleNamespace(
            key_metrics={"basic_info": {"currency": "USD"}},
            raw_data={
                "external_expectations": {
                    "currency": "USD",
                    "price_target": {
                        "mean": 335.72, "median": 350.0,
                        "low": 245.0, "high": 400.0,
                        "return_vs_market": 0.01,
                        "analyst_count": 26, "source": "benzinga",
                        "provider_as_of": "2026-09-10",
                        "qualified_for_contradiction": True,
                        "qualified_for_corroboration": True,
                    },
                    "recommendations": {},
                    "forward_estimates": [{
                        "revenue": 477.8e9,
                        "revenue_analyst_count": 39,
                    }],
                },
            },
        ),
        news_analysis=None,
        financial_model=SimpleNamespace(
            assumptions={
                "revenue_growth_source": (
                    "yahoo_analyst_consensus_with_deterministic_fade"
                ),
            },
            valuation_metrics={
                "fair_value": 170.0,
                "current_price": 332.27,
                "upside_vs_market": -0.488,
                "perpetual_price": 157.8,
                "exit_multiple_price": 182.4,
                "point_estimate_withheld": True,
                "publication_withheld_reason": "external evidence conflicts",
                "model_revenue_forecast": [477.8e9],
                "market_implied_fcf_path_vs_model": 1.1245,
                "analyst_target_implied_fcf_path_vs_model": 1.1737,
            },
        ),
    )

    incomplete = (
        "AAPL is NOT RATED. The analyst target is USD 335.72, but the model "
        "range is USD 157.80-182.40."
    )
    guarded = runner._guard_user_answer(incomplete)

    assert guarded.startswith("AAPL is NOT RATED")
    assert "benzinga" in guarded
    assert "2026-09-10" in guarded
    assert "materially conflicts" in guarded
    assert "whole-path reverse DCF" in guarded
    assert "market 2.12×" in guarded
    assert "analyst mean target 2.17×" in guarded


def test_extreme_expectation_gap_requires_an_explicit_model_scope_warning():
    runner = supervisor_agent.SupervisorWorkflowRunner.__new__(
        supervisor_agent.SupervisorWorkflowRunner)
    runner.ticker = "TSLA"
    runner.state = SimpleNamespace(
        financial_data=SimpleNamespace(
            key_metrics={"basic_info": {"currency": "USD"}},
            raw_data={},
        ),
        news_analysis=None,
        financial_model=SimpleNamespace(
            assumptions={},
            valuation_metrics={
                "perpetual_price": 15.44,
                "point_estimate_withheld": True,
                "publication_withheld_reason": "extreme expectations gap",
                "market_implied_fcf_path_vs_model": 42.07,
            },
        ),
    )

    incomplete = (
        "TSLA is NOT RATED. The whole-path reverse DCF says the market is "
        "43.07x the model FCF path."
    )
    guarded = runner._guard_user_answer(incomplete)

    assert guarded != incomplete
    assert "modeled operating cash-flow path" in guarded
    assert "not a comprehensive company value" in guarded
