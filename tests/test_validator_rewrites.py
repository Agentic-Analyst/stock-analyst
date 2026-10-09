"""
Why the recommendation narrative failed all three rewrites in every run.

Captured 2026-10-09 through the production image (AAPL, JPM, MSFT, TSLA):
every run shipped the evidence-safe fallback. The validator and its rewrite
loop could not converge:

- The 12-month price-target driver's sentence was counted as an uncited
  claim, but the contract tells the model to explain the deterministic
  convergence basis there and never cite news for it. "This is the published intrinsic value
  under an explicit 12-month convergence assumption, not a statistically
  forecast market price" was uncited in all 16 attempts; with 16 counted
  sentences that one alone is 93.8% < 95% (JPM's last two attempts failed on
  nothing else).
- Sentences stating the fixed numbers (the DCF range, the confidence alert's
  gaps) were counted as uncited claims. Cited to news they failed support, so
  the model alternated between the two failures.
- The rewrite prompt gave only a count of unsupported claims and listed the
  fields to rewrite without the `watch` items, so cited watch items that
  failed support were copied unchanged through every attempt.
- Replacing the valuation perspective with the fixed text counted as an
  auto-correction on every response, so even a valid first draft was sent
  back for a rewrite it could only lose.
- "free-cash-flow" never matched a source's "free cash flow"; an article's own
  date did not support "reported in September 2026"; a data table's exact
  figures ("P/E Ratio 345.73 EPS (TTM) $ 1.08") shared one word with any
  sentence about them.

The anti-laundering guarantee (a real but unrelated [E#] fails) is pinned in
test_citation_support.py and re-checked here against each new allowance.
"""

import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "src"))

from src.recommendation_engine import RecommendationEngineV3
from src.recommendation_validator import RecommendationValidator


FIXED = {
    "rating": "STRONG SELL",
    "current_price": 340.42,
    "expected_return_pct_12m": -33.35,
    "target_assumption": (
        "The 12-month case assumes convergence to the currently published intrinsic "
        "value; it is not a statistically forecast market price."),
    "targets": {
        "m3": {"price": None, "range_low": None, "range_high": None},
        "m6": {"price": None, "range_low": None, "range_high": None},
        "m12": {"price": 226.89, "range_low": 206.61, "range_high": 247.17},
    },
    "confidence_alert": {"model_gap": -0.3335, "benchmark_gap": -0.0362, "analyst_count": 39},
    "confidence_alert_text": (
        "Low confidence: VYNN's fair value is 33% below the market price, while the mean "
        "target of 39 analysts is 4% below it."),
}

PACK = {"evidence": [
    {
        "id": "E1", "type": "catalyst_financial", "date": "2026-09-12",
        "source_article_title": "Cook Hands Ternus Apple (AAPL) that Still has to Prove itself on AI",
        "snippet": ("fiscal third-quarter revenue reached $109.4 billion, up 16% year over year, "
                    "with iPhone revenue up 22% to $54.3 billion and Services setting its own record"),
        "title": "Strong revenue and Services performance",
    },
    {
        "id": "E2", "type": "catalyst_product", "date": "2026-09-11",
        "source_article_title": "Apple Stock Rises 4% Following New Foldable iPhone Duo Launch",
        "snippet": ("Apple (AAPL) stock climbed 4% on Thursday after the company officially "
                    "launched its long-awaited foldable phone, the iPhone Duo"),
    },
    {
        "id": "E3", "type": "risk_financial", "date": "2026-09-25",
        "source_article_title": "Tesla Opens First High-Volume Semi Factory in Nevada",
        "snippet": ("Tesla expects capital spending of more than $25 billion this year, and free "
                    "cash flow turned negative in Q2."),
    },
    {
        "id": "E4", "type": "risk_market", "date": "2026-09-27",
        "source_article_title": "Ford Motor vs. Tesla: What Revenue Trends Reveal",
        "snippet": "Market Cap $1.5T Gross Margin 18.85 % P/E Ratio 345.73 EPS (TTM) $ 1.08",
    },
]}

DRIVER = ("This is the published intrinsic value under an explicit 12-month convergence "
          "assumption, not a statistically forecast market price.")
PERSPECTIVE = "The model's own words about the fixed valuation, which the validator replaces."


def _response(thesis, *, driver=DRIVER, watch=None, risks=None, rating="STRONG SELL",
              perspective=PERSPECTIVE):
    return {
        "rating": rating,
        "thesis": thesis,
        "valuation_perspective": perspective,
        "price_targets": {
            "m3": {"price": None, "range_low": None, "range_high": None, "driver": ""},
            "m6": {"price": None, "range_low": None, "range_high": None, "driver": ""},
            "m12": {"price": 226.89, "range_low": 206.61, "range_high": 247.17, "driver": driver},
        },
        "catalysts": [{"statement": "Apple launched the foldable iPhone Duo [E2].",
                       "evidence": ["E2"]}],
        "risks": risks if risks is not None else [{
            "statement": "Free cash flow turned negative while capital spending rises [E3].",
            "evidence": ["E3"]}],
        "scenarios": {
            name: {"narrative": "Fiscal third-quarter revenue reached $109.4 billion [E1].",
                   "watch": list(watch or [])}
            for name in ("bull", "base", "bear")
        },
        "action": {"buyers": "Wait for a better entry.", "holders": "Hold, do not add.",
                   "watch": []},
        "monitoring_plan": ["Next quarterly results"],
    }


def _validate(response, fixed=FIXED, pack=PACK):
    return RecommendationValidator().validate_and_correct(json.dumps(response), fixed, pack)


NEWS = "Fiscal third-quarter revenue reached $109.4 billion, up 16% year over year [E1]."


class TestCoverageCountsNewsClaimsOnly:
    def test_the_12_month_driver_is_not_an_uncited_claim(self):
        _, report = _validate(_response(NEWS))
        assert report["valid"] is True, report["errors"]
        assert report["coverage_details"]["coverage_pct"] == 100.0

    def test_news_in_the_driver_still_has_to_cite(self):
        driver = "Strong iPhone demand, up 25% this year, will lift the target."
        _, report = _validate(_response(NEWS, driver=driver))
        assert report["valid"] is False
        assert any("25%" in s for s in report["coverage_details"]["uncited_sentences"])

    def test_a_sentence_of_fixed_figures_needs_no_citation(self):
        thesis = NEWS + (
            " The fixed DCF scenario range is 206.61 to 247.17. The supplied alert says the "
            "39-analyst mean target is 4% below the market, compared with the model's 33% downside.")
        _, report = _validate(_response(thesis))
        assert report["valid"] is True, report["errors"]
        # The two sentences, and the 12-month driver's.
        assert report["coverage_details"]["model_statements"] == 3

    def test_naming_the_fixed_rating_is_a_model_statement(self):
        thesis = NEWS + " Taken together, these factors support the assigned STRONG SELL rating."
        _, report = _validate(_response(thesis))
        assert report["valid"] is True, report["errors"]

    def test_a_figure_the_model_does_not_hold_is_still_a_claim_to_cite(self):
        # Anchored to the valuation, but 25% is no FIXED_NUMBERS figure.
        thesis = NEWS + " The valuation reflects iPhone sales falling 25% next year."
        _, report = _validate(_response(thesis))
        assert report["valid"] is False
        assert any("25%" in s for s in report["coverage_details"]["uncited_sentences"])

    def test_a_news_sentence_sharing_a_model_figure_is_still_counted(self):
        # 4 is one of the alert's figures, but nothing ties this to the model.
        thesis = NEWS + " Apple stock climbed 4% on Thursday after the launch."
        _, report = _validate(_response(thesis))
        assert report["valid"] is False
        assert any("climbed 4%" in s for s in report["coverage_details"]["uncited_sentences"])

    def test_a_wrong_model_figure_is_not_waved_through(self):
        thesis = NEWS + " The fixed DCF scenario range is 196.61 to 247.17."
        _, report = _validate(_response(thesis))
        assert report["valid"] is False

    def test_a_cited_driver_is_still_support_checked(self):
        driver = "The target reflects Apple's antitrust trial outcome [E2]."
        _, report = _validate(_response(NEWS, driver=driver))
        assert report["valid"] is False
        assert report["citation_support_issues"][0]["field"] == "price_targets.m12.driver"


class TestSupportFailuresSayWhereAndWhy:
    def test_model_figures_cited_to_news_are_named_as_such(self):
        thesis = NEWS + " The fixed DCF scenario range is 206.61 to 247.17 [E1]."
        _, report = _validate(_response(thesis))
        issue = report["citation_support_issues"][0]
        assert issue["field"] == "thesis"
        assert issue["reason"] == "model_figures_cited_to_news"
        assert issue["citations"] == ["E1"]

    def test_a_watch_item_failure_carries_its_path(self):
        watch = ["Evidence of AI execution during the CEO transition [E1]"]
        _, report = _validate(_response(NEWS, watch=watch))
        fields = {issue["field"] for issue in report["citation_support_issues"]}
        assert "scenarios.bull.watch[0]" in fields
        assert report["citation_support_issues"][0]["reason"] == "wording_not_in_source"

    def test_a_figure_missing_from_the_source_is_listed(self):
        thesis = "Fiscal third-quarter revenue reached $112.0 billion [E1]."
        _, report = _validate(_response(thesis))
        issue = report["citation_support_issues"][0]
        assert issue["reason"] == "numbers_not_in_source"
        assert issue["numbers"] == ["112"]


class TestSupportFalsePositives:
    def test_a_hyphenated_compound_matches_the_spaced_source(self):
        risks = [{"statement": "Monitor the capital-spending plan and the free-cash-flow trend [E3].",
                  "evidence": ["E3"]}]
        _, report = _validate(_response(NEWS, risks=risks))
        assert "citation_support_issues" not in report, report.get("citation_support_issues")

    def test_the_items_own_date_supports_its_year_and_day(self):
        thesis = NEWS + " Apple officially launched the foldable iPhone Duo, reported on September 11, 2026 [E2]."
        _, report = _validate(_response(thesis))
        assert "citation_support_issues" not in report, report.get("citation_support_issues")

    def test_exact_table_figures_support_the_sentence(self):
        # Production's TSLA sentence: one shared word ("ratio"), two exact figures.
        risks = [{"statement": "The cited comparison lists a P/E ratio of 345.73 and TTM EPS of $1.08 [E4].",
                  "evidence": ["E4"]}]
        _, report = _validate(_response(NEWS, risks=risks))
        assert "citation_support_issues" not in report, report.get("citation_support_issues")


class TestLaunderingStillFails:
    def test_an_unrelated_real_citation_is_rejected(self):
        thesis = NEWS + " Apple faces a Department-of-Justice antitrust trial [E2]."
        _, report = _validate(_response(thesis))
        assert report["valid"] is False
        assert report["citation_support_issues"][0]["citations"] == ["E2"]

    def test_a_date_supports_numbers_never_wording(self):
        # E2's date makes "September 2026" a supported figure, but the month
        # is not shared wording: the claim itself is still unrelated.
        thesis = NEWS + " Apple faces a DOJ antitrust trial starting September 2026 [E2]."
        _, report = _validate(_response(thesis))
        assert report["valid"] is False
        assert report["citation_support_issues"][0]["reason"] == "wording_not_in_source"

    def test_one_shared_figure_does_not_entail_an_unrelated_claim(self):
        risks = [{"statement": "Tesla faces a $1.08 billion recall over Semi brakes [E4].",
                  "evidence": ["E4"]}]
        _, report = _validate(_response(NEWS, risks=risks))
        assert report["valid"] is False

    def test_two_figures_without_a_shared_word_do_not_entail(self):
        risks = [{"statement": "Recall costs of 345.73 million and 1.08 billion loom [E4].",
                  "evidence": ["E4"]}]
        _, report = _validate(_response(NEWS, risks=risks))
        assert report["valid"] is False

    def test_a_model_statement_with_a_citation_is_not_exempt(self):
        # Exemption is for uncited sentences; a cited one must be supported.
        thesis = NEWS + " The supplied alert says the 39-analyst mean target is 4% below the market [E2]."
        _, report = _validate(_response(thesis))
        assert report["valid"] is False


class TestRewriteTrigger:
    def test_replacing_the_valuation_perspective_alone_triggers_no_rewrite(self):
        validator = RecommendationValidator()
        _, report = _validate(_response(NEWS))
        assert report["auto_corrected"] is True
        assert report["valid"] is True
        assert validator.needs_rewrite(report) is False

    def test_a_corrected_rating_still_triggers_a_rewrite(self):
        validator = RecommendationValidator()
        _, report = _validate(_response(NEWS, rating="BUY"))
        assert report["narrative_corrections"]
        assert validator.needs_rewrite(report) is True

    def test_a_corrected_target_still_triggers_a_rewrite(self):
        response = _response(NEWS)
        response["price_targets"]["m12"]["price"] = 300.0
        validator = RecommendationValidator()
        _, report = _validate(response)
        assert validator.needs_rewrite(report) is True


def _engine_inputs():
    company = {
        "ticker": "AAPL", "current_price": 340.42,
        "week_52_low": 200.0, "week_52_high": 360.0, "currency": "USD",
    }
    valuation = {
        "dcf_perpetual": {"intrinsic_value_per_share": 206.61},
        "dcf_exit": {"intrinsic_value_per_share": 247.17},
        "summary": {"average_intrinsic": 226.89},
        "reliability": {},
    }
    screening = {
        "analysis_summary": {"overall_sentiment": "neutral", "articles_analyzed": 1},
        "freshness": {"status": "fresh"},
        "catalysts": [{
            "type": "product", "description": "Foldable launch", "confidence": 0.8,
            "source_articles": [{
                "title": "Apple Stock Rises 4% Following New Foldable iPhone Duo Launch",
                "url": "https://example.com/duo",
                "snippet": ("Apple (AAPL) stock climbed 4% on Thursday after the company "
                            "officially launched its long-awaited foldable phone, the iPhone Duo"),
                "published": "2026-09-11",
            }],
        }],
        "risks": [],
    }
    return company, valuation, screening


def _draft(fixed_numbers, *, watch):
    """A first draft as the explainer writes it, cited to the engine's E1."""
    targets = fixed_numbers["targets"]
    return json.dumps({
        "rating": fixed_numbers["rating"],
        "thesis": "Apple officially launched its foldable phone, the iPhone Duo [E1].",
        "valuation_perspective": "Our own perspective, replaced by the fixed text.",
        "price_targets": {k: {**targets[k], "driver": ""} for k in ("m3", "m6", "m12")},
        "catalysts": [{"statement": "Apple launched the long-awaited foldable iPhone Duo [E1].",
                       "evidence": ["E1"]}],
        "risks": [],
        "scenarios": {name: {"narrative": "Apple stock climbed 4% after the iPhone Duo launch [E1].",
                             "watch": list(watch)} for name in ("bull", "base", "bear")},
        "action": {"buyers": "Wait.", "holders": "Hold.", "watch": []},
        "monitoring_plan": ["Next quarterly results"],
    })


class TestTheLoopConverges:
    def test_a_valid_first_draft_ships_without_a_rewrite(self):
        engine = RecommendationEngineV3(sector="default")
        company, valuation, screening = _engine_inputs()
        calls = []

        def llm(messages, temperature=0.6):
            calls.append(messages)
            fixed = json.loads(messages[0]["content"].split("```json", 1)[1].split("```", 1)[0])
            return _draft(fixed, watch=[]), 0.0

        output, _, pack = engine.generate_recommendation(company, valuation, screening, llm)

        assert len(calls) == 1
        assert pack["validation"]["status"] == "passed"
        assert "Narrative validation fallback" not in output
        assert "iPhone Duo" in output

    def test_a_named_watch_item_is_fixed_in_one_rewrite(self):
        engine = RecommendationEngineV3(sector="default")
        company, valuation, screening = _engine_inputs()
        calls = []
        fixed_seen = {}

        def llm(messages, temperature=0.6):
            prompt = messages[0]["content"]
            calls.append(prompt)
            if len(calls) == 1:
                fixed_seen.update(json.loads(prompt.split("```json", 1)[1].split("```", 1)[0]))
                return _draft(fixed_seen, watch=["Evidence of AI execution during the CEO transition [E1]"]), 0.0
            # The rewrite is told which watch item failed, where, and why.
            assert "`scenarios.bull.watch[0]` cites E1" in prompt
            assert "Evidence of AI execution during the CEO transition" in prompt
            assert "in their words, or remove the citation" in prompt
            return _draft(fixed_seen, watch=["AI execution during the CEO transition"]), 0.0

        output, _, pack = engine.generate_recommendation(company, valuation, screening, llm)

        assert len(calls) == 2
        assert pack["validation"]["status"] == "passed"
        assert "Narrative validation fallback" not in output

    def test_the_rewrite_prompt_says_model_figures_take_no_citation(self):
        engine = RecommendationEngineV3(sector="default")
        prompt = engine._build_rewrite_prompt(
            corrected_json={"thesis": "x"},
            fixed_numbers=FIXED,
            evidence_pack=PACK,
            validation_report={
                "errors": ["1 cited claim(s) are not supported by their evidence"],
                "citation_support_issues": [{
                    "claim": "The fixed DCF scenario range is 206.61 to 247.17 [E1]",
                    "citations": ["E1"], "field": "scenarios.bear.narrative",
                    "reason": "model_figures_cited_to_news",
                }],
            },
            attempt=1,
        )
        assert "`scenarios.bear.narrative` cites E1" in prompt
        assert "remove the [E#] from this sentence and keep the figures as given" in prompt
        assert "`scenarios.bull/base/bear.watch`" in prompt
        assert "carries NO [E#]" in prompt
