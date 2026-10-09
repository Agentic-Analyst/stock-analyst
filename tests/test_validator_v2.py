"""
The recommendation narrative passes validation it can meet, and nothing else.

Captured 2026-10-09 through the production image (AAPL, JPM, MSFT, TSLA): every
run that reached the validator shipped the evidence-safe fallback, because the
contract forbade citing news for VYNN's own figures while coverage counted
those sentences as uncited claims, the 12-month driver among them; the rewrite
was told only how many claims failed; and replacing the valuation perspective
forced a rewrite of every draft.

Two attempts to exempt "model statements" heuristically were broken by
independent reviews (PR #48), so nothing the model writes is exempted here:

1. VYNN's own figures are an evidence item, E0, built by the engine. A
   sentence restating them cites [E0] and passes main's support check
   against E0's text, plus E0-only rules that make it stricter: one of E0's
   figures or its rating, no other rating, two shared words, no word E0
   does not say, no negation E0 does not make.
2. Coverage skips only text the engine wrote itself (the 12-month driver),
   matched exactly; no phrase excuses a sentence.
3. The rewrite is shown each failing sentence, JSON-quoted, with its reason;
   its advice is only ever to cite a source that states it, restate what
   the source says, or delete it.
4. Replacing the engine's own texts never forces a rewrite; the loop stops
   only when a response is valid and nothing in it was corrected.
5. Main's checker is otherwise unchanged, except that the company's own name
   is never shared wording and printed items with a figure or date must cite.
"""

import json
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "src"))

from src.recommendation_engine import RecommendationEngineV3, model_evidence_item
from src.recommendation_validator import RecommendationValidator


FIXED = {
    "as_of": "2026-10-09",
    "ticker": "AAPL",
    "rating": "STRONG SELL",
    "rating_confidence": "low",
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
        "target of 39 analysts is 4% below it, which backs less than half of that move."),
    "inputs": {"analyst_target": 328.09, "analyst_count": 39, "catalyst_score_pct": 10.23},
}
CONTEXT = {"pe_ratio": "36.89x", "net_margin": "26.9%", "week_52_low": 200.0, "week_52_high": 360.0}
E0 = model_evidence_item(FIXED, CONTEXT, "$")

NEWS = [
    {"id": "E1", "type": "catalyst_financial", "date": "2026-09-12",
     "source_article_title": "Cook Hands Ternus Apple (AAPL) that Still has to Prove itself on AI",
     "snippet": ("fiscal third-quarter revenue reached $109.4 billion, up 16% year over year, "
                 "with iPhone revenue up 22% to $54.3 billion and Services setting its own record")},
    {"id": "E2", "type": "catalyst_product", "date": "2026-09-11",
     "source_article_title": "Apple Stock Rises 4% Following New Foldable iPhone Duo Launch",
     "snippet": ("Apple (AAPL) stock climbed 4% on Thursday after the company officially launched "
                 "its long-awaited foldable phone, the iPhone Duo")},
    {"id": "E3", "type": "risk_financial", "date": "2026-09-25",
     "source_article_title": "Tesla Opens First High-Volume Semi Factory in Nevada",
     "snippet": ("Tesla expects capital spending of more than $25 billion this year, and free "
                 "cash flow turned negative in Q2.")},
    {"id": "E4", "type": "risk_market", "date": "2026-09-27",
     "source_article_title": "Ford Motor vs. Tesla: What Revenue Trends Reveal About These Automotive Titans",
     "snippet": "Market Cap $1.5T Gross Margin 18.85 % P/E Ratio 345.73 EPS (TTM) $ 1.08"},
    {"id": "E7", "type": "risk_competitive", "date": "2026-09-11",
     "source_article_title": "Xiaomi and Huawei Launch Foldable Smartphones Ahead of Apple's Launch",
     "snippet": ("It controlled 22.6% of China's overall smartphone market during the second "
                 "quarter, ahead of Apple's 18.1%, according to IDC data cited by Reuters.")},
    {"id": "E8", "type": "catalyst_product", "date": "2026-09-26",
     "source_article_title": "Microsoft Advances Azure Disclosure and Custom AI Chips",
     "snippet": "Microsoft has been steadily building its own artificial-intelligence chips."},
    {"id": "E10", "type": "risk_market", "date": "2026-09-20",
     "source_article_title": "Tesla may slow down Cybertruck output",
     "snippet": "Tesla could slow down Cybertruck production at Giga Texas, a person familiar said."},
]
PACK = {"evidence": [E0] + NEWS, "subject": {"ticker": "AAPL", "name": "Apple Inc."}}

THESIS = "Fiscal third-quarter revenue reached $109.4 billion, up 16% year over year [E1]."


def _response(thesis=THESIS, *, driver="", watch=None, monitoring=None, holders="Hold, do not add.",
              rating="STRONG SELL", perspective="The model's own perspective, replaced."):
    return {
        "rating": rating,
        "thesis": thesis,
        "valuation_perspective": perspective,
        "price_targets": {
            "m3": {"price": None, "range_low": None, "range_high": None, "driver": ""},
            "m6": {"price": None, "range_low": None, "range_high": None, "driver": ""},
            "m12": {"price": 226.89, "range_low": 206.61, "range_high": 247.17, "driver": driver},
        },
        "catalysts": [{"statement": "Apple officially launched its foldable phone, the iPhone Duo [E2].",
                       "evidence": ["E2"]}],
        "risks": [{"statement": "Free cash flow turned negative in Q2 as capital spending rose [E3].",
                   "evidence": ["E3"]}],
        "scenarios": {
            name: {"narrative": "iPhone revenue rose 22% to $54.3 billion [E1].",
                   "watch": list(watch or [])}
            for name in ("bull", "base", "bear")
        },
        "action": {"buyers": "Wait for a better entry.", "holders": holders, "watch": []},
        "monitoring_plan": list(monitoring or ["Next quarterly results"]),
    }


def _validate(response, fixed=FIXED, pack=PACK):
    return RecommendationValidator().validate_and_correct(json.dumps(response), fixed, pack)


def _issue_for(sentence, pack=PACK, fixed=FIXED):
    """The support failure of one cited sentence, or None when supported."""
    issues = RecommendationValidator()._validate_citation_support({"thesis": sentence}, pack, fixed)
    return issues[0]["reason"] if issues else None


def _counted(sentence, **kwargs):
    """Appended uncited to a valid response: is it counted as an uncited claim?"""
    _, report = _validate(_response(THESIS + " " + sentence, **kwargs))
    uncited = report["coverage_details"].get("uncited_sentences", [])
    return report["valid"] is False and any(sentence.rstrip(".")[:40] in u for u in uncited)


def test_the_base_response_is_valid():
    _, report = _validate(_response())
    assert report["valid"] is True, report["errors"]


# --- 1. E0 ------------------------------------------------------------------

class TestModelEvidence:
    def test_e0_states_each_figure_with_its_role(self):
        text = E0["snippet"]
        for fragment in ("VYNN's rating is STRONG SELL, at low confidence.",
                         "VYNN's fair value, its published intrinsic value and 12-month "
                         "convergence target, is $226.89 per share.",
                         "VYNN's DCF scenario range is $206.61 to $247.17.",
                         "VYNN's reference share price at the run is $340.42.",
                         "The implied 12-month return is -33.35% (33.35% downside).",
                         "The analysts' mean target is $328.09 (39 analysts).",
                         FIXED["target_assumption"], FIXED["confidence_alert_text"],
                         "P/E ratio 36.89x", "net margin 26.9%", "52-week range $200.00 to $360.00"):
            assert fragment in text, fragment
        assert "(not news)" in E0["source_article_title"]
        assert E0["id"] == "E0" and E0["type"] == "vynn_model"

    def test_every_e0_sentence_quoted_verbatim_is_supported(self):
        # Gate57: "The current price at the run is $333.25 [E0]" shared no
        # countable word with E0 and stalled two runs; E0 must pass its own check.
        import re
        for sentence in re.split(RecommendationValidator.SENTENCE_PATTERN, E0["snippet"]):
            sentence = sentence.strip().rstrip(".")
            if sentence:
                assert _issue_for(f"{sentence} [E0].") is None, sentence

    @pytest.mark.parametrize("sentence", [
        "VYNN's fair value is $226.89 per share, against a current price at the run of $340.42 [E0].",
        "The DCF scenario range is $206.61 to $247.17 [E0].",
        "The rating is STRONG SELL at low confidence [E0].",
        "VYNN's fair value is 33% below the market price, while the mean target of 39 analysts is 4% below it [E0].",
        "The 12-month case assumes convergence to the currently published intrinsic value; "
        "it is not a statistically forecast market price [E0].",
        "The implied 12-month return is -33.35% [E0].",
        "Apple's P/E ratio is 36.89x in the provider market data [E0].",
    ])
    def test_a_restatement_citing_e0_is_supported(self, sentence):
        assert _issue_for(sentence) is None

    @pytest.mark.parametrize("sentence", [
        # News claims laundered through E0.
        "Apple lost its Epic Games appeal [E0].",
        "Analysts worry about weak iPhone demand [E0].",
        "Apple shares fell 4% after the DOJ suit [E0].",
        "The mean target of 39 analysts fell 4% [E0].",
        "Apple's free cash flow declined 33% [E0].",
        # VYNN's figures misstated.
        "VYNN's fair value implies 33% upside [E0].",
        "VYNN's fair value is 33% above the market price [E0].",
        "VYNN's fair value is 33% over the market price [E0].",
        "VYNN's fair value is not 33% below the market price [E0].",
        "VYNN does not rate Apple a STRONG SELL [E0].",
        "VYNN's fair value is 4% below the market price, a substantial disagreement [E0].",
        # Another rating.
        "VYNN rates Apple a STRONG BUY [E0].",
        "VYNN rates Apple a Buy, with low confidence [E0].",
    ])
    def test_e0_launders_nothing(self, sentence):
        assert _issue_for(sentence) is not None, sentence

    def test_the_rewrite_is_told_which_words_e0_does_not_use(self):
        # Gate55: drafts framed E0's figures ("VYNN's calculator lists ...",
        # "The model states that ..."), and reasons given as stems ("list,
        # stat") had the rewrite swap one framing verb for another.
        reason = _issue_for("VYNN's calculator lists a published intrinsic value of $226.89 per share [E0].")
        assert "(calculator, lists)" in reason and "no framing of your own" in reason

    def test_another_rating_beside_e0_figures_fails(self):
        # Every word and figure is E0's; only the label is not.
        assert _issue_for("VYNN's fair value is $226.89 per share, a STRONG BUY [E0].") is not None

    def test_a_sentence_without_e0_figures_cannot_borrow_its_words(self):
        # Tesla's alert says the Street is "5% above": with no figure, E0's
        # words alone would let VYNN's fair value be "above the market price".
        fixed = {**FIXED, "confidence_alert_text": (
            "Low confidence: VYNN's fair value is 94% below the market price, while the mean "
            "target of 37 analysts is 5% above it.")}
        pack = {**PACK, "evidence": [model_evidence_item(fixed, CONTEXT, "$")] + NEWS}
        assert _issue_for("VYNN's fair value is above the market price [E0].",
                          pack=pack, fixed=fixed) is not None

    def test_e0_is_not_counted_as_news(self):
        # With no news items the engine never calls the model; E0 is added only
        # to a pack that has news.
        engine = RecommendationEngineV3(sector="default")
        company, valuation, screening = _engine_inputs()
        screening["catalysts"] = []
        calls = []
        _, _, pack = engine.generate_recommendation(
            company, valuation, screening, lambda m, temperature=0.6: (calls.append(m), ("{}", 0.0))[1])
        assert calls == []
        assert all(item.get("id") != "E0" for item in pack.get("evidence") or [])


# --- 2. coverage: only the engine's own text is excluded ---------------------

class TestCoverage:
    def test_a_rejected_claim_without_its_citation_is_still_counted(self):
        claim = "Fallout from the EU fine over Apple's App Store steering rules [E1]"
        _, report = RecommendationValidator().validate_and_correct(
            json.dumps(_response(watch=[claim.replace(" [E1]", "")])), FIXED, PACK,
            rejected_claims={claim})
        assert report["valid"] is False
        assert any("EU fine" in u for u in report["coverage_details"]["uncited_sentences"])

    def test_the_engine_writes_the_driver_and_it_is_not_counted(self):
        driver = "Strong iPhone demand, up 25% this year, will lift the target."
        corrected, report = _validate(_response(driver=driver))
        assert corrected["price_targets"]["m12"]["driver"] == FIXED["target_assumption"]
        assert report["valid"] is True, report["errors"]
        assert not report["narrative_corrections"]

    def test_only_an_exact_copy_of_engine_text_is_excluded(self):
        # A paraphrase of the target assumption is the model's sentence.
        assert _counted("This is the published intrinsic value under an explicit 12-month "
                        "convergence assumption, not a statistically forecast market price.")

    @pytest.mark.parametrize("sentence", [
        "The bear case reflects Apple losing its Epic Games appeal, which will cut App Store revenue by a third.",
        "The base case is the published intrinsic value of 226.89 under the 12-month convergence assumption.",
        "The expected return is -33.35% under the 12-month assumption.",
        "Apple's P/E ratio is 36.89x, a premium valuation.",
    ])
    def test_no_phrase_excuses_a_sentence(self, sentence):
        assert _counted(sentence)

    def test_a_printed_item_with_a_figure_or_date_must_cite(self):
        _, report = _validate(_response(watch=[
            "Apple's fiscal Q4 earnings call on October 30, 2026, where management will guide "
            "iPhone Duo shipments of 8 million units"]))
        assert report["valid"] is False
        _, report = _validate(_response(monitoring=["Watch for iPhone Duo shipments of 8 million units"]))
        assert report["valid"] is False
        _, report = _validate(_response(holders="Holders should sell before the EU's $12 billion fine lands."))
        assert report["valid"] is False

    def test_an_item_without_a_figure_is_not_counted(self):
        _, report = _validate(_response(watch=["Foldable iPhone demand"],
                                        monitoring=["Next quarterly results"]))
        assert report["valid"] is True, report["errors"]


# --- 3. rewrite feedback -----------------------------------------------------

class TestRewriteFeedback:
    def _prompt(self, report, corrected):
        return RecommendationEngineV3(sector="default")._build_rewrite_prompt(
            corrected_json=corrected, fixed_numbers=FIXED, evidence_pack=PACK,
            validation_report=report, attempt=1)

    def test_each_failing_sentence_is_named_quoted_and_explained(self):
        response = _response(THESIS + ' Apple lost the "Epic"\nappeal [E2].',
                             watch=["Apple's App Store fine fallout [E1]"])
        corrected, report = _validate(response)
        prompt = self._prompt(report, corrected)
        assert '"thesis" cites E2: "Apple lost the \\"Epic\\"\\nappeal [E2]"' in prompt
        assert '"scenarios.bull.watch[0]" cites E1' in prompt
        assert "its wording is not what the cited source says" in prompt
        assert ("cite a source that states it, restate only what the cited source says, "
                "or delete the sentence or item") in prompt

    def test_the_advice_never_says_to_drop_a_citation(self):
        corrected, report = _validate(_response(
            THESIS + " VYNN's fair value is $226.89 per share [E1]. Apple will exit China.",
            watch=["Apple's App Store fine fallout [E1]"]))
        prompt = self._prompt(report, corrected).lower()
        for phrase in ("remove the [e#]", "remove its [e#]", "remove the citation",
                       "drop the [e#]", "drop its [e#]", "needs no citation", "takes no citation"):
            assert phrase not in prompt, phrase
        assert "e0 for vynn's own figures" in prompt

    def test_watch_items_are_in_the_rewrites_scope(self):
        corrected, report = _validate(_response(watch=["Apple's App Store fine fallout [E1]"]))
        prompt = self._prompt(report, corrected)
        assert "`scenarios.bull/base/bear.watch`" in prompt and "`action.watch`" in prompt


# --- 4. the loop -------------------------------------------------------------

def _engine_inputs():
    company = {"ticker": "AAPL", "current_price": 340.42, "week_52_low": 200.0,
               "week_52_high": 360.0, "currency": "USD", "company_name": "Apple Inc."}
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


def _draft(fixed, *, thesis_extra="", rating=None, watch=None):
    targets = fixed["targets"]
    news_id = "E1"
    return json.dumps({
        "rating": rating or fixed["rating"],
        "thesis": f"Apple officially launched its foldable phone, the iPhone Duo [{news_id}]." + thesis_extra,
        "valuation_perspective": "Our own perspective, replaced by the fixed text.",
        "price_targets": {k: {**targets[k], "driver": "Our own driver."} for k in ("m3", "m6", "m12")},
        "catalysts": [{"statement": f"Apple launched the long-awaited foldable iPhone Duo [{news_id}].",
                       "evidence": [news_id]}],
        "risks": [],
        "scenarios": {name: {"narrative": f"Apple stock climbed 4% after the iPhone Duo launch [{news_id}].",
                             "watch": list(watch or [])} for name in ("bull", "base", "bear")},
        "action": {"buyers": "Wait.", "holders": "Hold.", "watch": []},
        "monitoring_plan": ["Next quarterly results"],
    })


def _run(first, rewrite):
    engine = RecommendationEngineV3(sector="default")
    company, valuation, screening = _engine_inputs()
    calls, seen = [], {}

    def llm(messages, temperature=0.6):
        prompt = messages[0]["content"]
        calls.append(prompt)
        if len(calls) == 1:
            seen.update(json.loads(prompt.split("```json", 1)[1].split("```", 1)[0]))
            return first(seen), 0.0
        return rewrite(seen, prompt), 0.0

    output, _, pack = engine.generate_recommendation(company, valuation, screening, llm)
    return output, pack, calls


class TestLoop:
    def test_a_valid_first_draft_with_a_model_sentence_ships_without_a_rewrite(self):
        extra = " The DCF scenario range is $206.61 to $247.17 [E0]."
        output, pack, calls = _run(lambda f: _draft(f, thesis_extra=extra), None)
        assert len(calls) == 1
        assert pack["validation"]["status"] == "passed"
        assert "The DCF scenario range is $206.61 to $247.17 [E0]" in output
        assert pack["evidence"][0]["id"] == "E0"
        assert pack["subject"] == {"ticker": "AAPL", "name": "Apple Inc."}

    def test_an_uncited_model_sentence_is_cited_to_e0_in_one_rewrite(self):
        bare = " The DCF scenario range is $206.61 to $247.17."

        def rewrite(fixed, prompt):
            assert json.dumps(bare.strip().rstrip(".")) in prompt
            return _draft(fixed, thesis_extra=bare.rstrip(".") + " [E0].")

        output, pack, calls = _run(lambda f: _draft(f, thesis_extra=bare), rewrite)
        assert len(calls) == 2
        assert pack["validation"]["status"] == "passed"

    def test_a_corrected_rating_never_ships(self):
        def draft(fixed, *_):
            return _draft(fixed, rating="BUY", thesis_extra=" We rate Apple a BUY.")

        output, pack, calls = _run(draft, draft)
        assert len(calls) == 4
        assert pack["validation"]["status"] == "degraded"
        assert "We rate Apple a BUY" not in output

    def test_obeying_the_advice_never_ships_a_false_claim(self):
        # review48 e2e: a false news claim with a figure; the rewrite drops the
        # citation, as the earlier advice told it to.
        claim = " Apple shares fell 12% after the DOJ antitrust suit, a risk VYNN's fair value already reflects"

        output, pack, calls = _run(lambda f: _draft(f, thesis_extra=claim + " [E1]."),
                                   lambda f, p: _draft(f, thesis_extra=claim + "."))
        assert "fell 12% after the DOJ" not in output
        assert pack["validation"]["status"] == "degraded"

    def test_a_claim_stripped_of_its_failed_citation_never_ships(self):
        # review48b e2e2 case A: the rewrite drops the citation from a watch
        # item and the holders' line it failed on; neither states a figure.
        item = "Fallout from the EU fine over Apple's App Store steering rules"
        hold = "Holders should sell before the EU fine over App Store steering rules lands"

        def draft(fixed, cite):
            d = json.loads(_draft(fixed, watch=[item + (" [E1]" if cite else "")]))
            d["action"]["holders"] = hold + (" [E1]." if cite else ".")
            return json.dumps(d)

        output, pack, calls = _run(lambda f: draft(f, True), lambda f, p: draft(f, False))
        assert "EU fine" not in output
        assert pack["validation"]["status"] == "degraded"

    def test_a_watch_item_stripped_of_its_citation_never_ships_a_claim_with_a_figure(self):
        # review48b e2e2 case A, with the figure that makes it a claim.
        item = "Fallout from the $12 billion EU fine over Apple's App Store steering rules"
        output, pack, calls = _run(lambda f: _draft(f, watch=[item + " [E1]"]),
                                   lambda f, p: _draft(f, watch=[item]))
        assert "$12 billion EU fine" not in output
        assert pack["validation"]["status"] == "degraded"


# --- 5. main's checker, not loosened; the company's name never shared ----------

class TestNotLoosened:
    @pytest.mark.parametrize("sentence", [
        # An item's date is not its text (the date rule is not carried).
        "Apple launched its foldable iPhone Duo on September 11, 2026 [E2].",
        "Black warned that limited foldable production will restrict incremental earnings throughout 2026 [E2].",
        # Two figures and one word (the table rule is not carried).
        "A P/E ratio of 345.73 on EPS of $1.08 shows Tesla will be removed from the S&P 500 [E4].",
        # A plain word is not the source's words joined (no joined runs).
        "China's economic slowdown will hurt Apple iPhone demand [E10].",
        # The company's own name is never shared wording.
        "The 22.6% and 18.1% figures confirm Apple's antitrust exposure [E7].",
        "The 22.6% and 18.1% figures show Apple will exit China [E7].",
        "In China, 22.6% versus Apple's 18.1% shows Apple will exit the country [E7].",
    ])
    def test_rejected(self, sentence):
        assert _issue_for(sentence) is not None, sentence

    def test_the_company_name_does_not_make_a_table_claim(self):
        pack = {**PACK, "subject": {"ticker": "TSLA", "name": "Tesla, Inc."}}
        assert _issue_for("Tesla's P/E ratio of 345.73 and EPS of $1.08 confirm collapsing "
                          "Cybertruck demand [E4].", pack=pack) is not None

    def test_a_long_company_name_carries_nothing(self):
        pack = {**PACK, "subject": {"ticker": "MSFT", "name": "Microsoft Corporation"}}
        assert _issue_for("Microsoft faces a DOJ antitrust probe [E8].", pack=pack) is not None

    def test_what_the_source_says_is_still_supported(self):
        assert _issue_for("Huawei controlled 22.6% of China's smartphone market in the second "
                          "quarter, ahead of Apple's 18.1% [E7].") is None


# --- review repros: every uncited one is counted -----------------------------

REVIEW_UNCITED = [
    # review48 s1/s3/s4/s5
    "Apple lost its Epic Games appeal, which will cut App Store revenue by a third.",
    "Our STRONG SELL rating reflects Apple losing its Epic Games appeal, which will cut App Store revenue by a third.",
    "The STRONG SELL rating reflects the DOJ antitrust ruling that forces Apple to end its Google search deal.",
    "Apple shares fell 4% after the DOJ sued over the App Store, a reminder of the risk behind VYNN's fair value.",
    "VYNN's valuation does not include the $12 billion EU fine Apple received this week.",
    "The model does not capture the 33% drop in iPhone sales in China reported last quarter.",
    "VYNN's fair value excludes Apple's $113 billion buyback announced in May.",
    "The valuation ignores that 39 countries have now banned the iPhone Duo.",
    "Apple's valuation hit $4 trillion as Berkshire sold 53 million shares.",
    "VYNN's fair value of $340.42 is in line with the market, so the model sees no downside.",
    "VYNN's fair value implies 33% upside from the current market price.",
    "The DCF valuation range runs from $113 to $39.",
    "VYNN's intrinsic value is $4, roughly 53 times below the market.",
    "Tesla's Model Y deliveries rose 12% in Q3 as Robotaxi expanded to 5 cities.",
    "Tesla's Model Y price cut of $5,000 lifted orders.",
    "Tesla's valuation surged after the company delivered 375 thousand vehicles in Q3.",
    "Tesla's Model 3 recall covered 1 million cars.",
    "Tesla's Model Y was banned in 37 countries.",
    "JPMorgan's valuation absorbs a $1 billion fine from the CFPB announced this week.",
    "JPMorgan's fair value already reflects the 22 branch closures and 30 percent layoffs announced Friday.",
    "JPMorgan's HOLD rating reflects its loss of the Epstein lawsuit, which will cost billions.",
    # review48b a_aapl / a_words / a_jpm / a_msft / a_tsla
    "VYNN's STRONG SELL rating follows a substantial decline in Apple's market share.",
    "VYNN's STRONG SELL rating follows the Street's move to sell.",
    "VYNN's low-confidence fair value is half the market price.",
    "VYNN's model does not factor the news of a high decline in Apple's market share.",
    "Apple's share price declined 4% on the news, a move VYNN's model does not factor.",
    "Apple's market price declined 33% below VYNN's fair value.",
    "VYNN's model holds that Apple's free cash flow declined 33%.",
    "VYNN's fair value is 4% below the market price.",
    "VYNN's model implies 113% upside from the current market price.",
    "VYNN's fair value implies 3.62% downside.",
    "VYNN's fair value is $206.61, below the market price.",
    "VYNN's fair value range is $206.61 to $340.42.",
    "VYNN's fair value range is $226.89 to $328.09.",
    "VYNN's fair value is 33% over the market price.",
    "VYNN's fair value is 33% short of the market price.",
    "VYNN's fair value exceeds the market price by 33%.",
    "VYNN does not rate Apple a STRONG SELL.",
    "VYNN's fair value is not 33% below the market price.",
    "VYNN rates Apple a Strong Buy.",
    "We rate Apple a buy, with high confidence.",
    "VYNN rates Apple a STRONG BUY, in line with the Street consensus.",
    "VYNN's fair value is twelve percent below the market price.",
    "VYNN's fair value is 3335 basis points below the market price.",
    "VYNN's fair value is €226.89, well below the market price.",
    "VYNN's fair value of 226.89 euros is below the market price.",
    "VYNN's fair value excludes Apple Intelligence revenue.",
    "VYNN rates Apple a buy given strong iPhone demand.",
    "VYNN's STRONG SELL rating follows a guidance cut.",
    "VYNN's STRONG SELL rating follows a record decline in iPhone sales.",
    "VYNN's STRONG SELL rating follows an analyst upgrade.",
    "VYNN's STRONG SELL rating follows Apple's earnings beat.",
    "VYNN's STRONG SELL rating reflects regulatory risk.",
    "VYNN's STRONG SELL rating follows a significant decline in Apple's share price on the news.",
    "VYNN's STRONG SELL rating is backed by the Street's move to a sell consensus.",
    "The model's high-confidence call: Apple's market share will decline substantially.",
    "VYNN's fair value is 12.45% above the market price.",
    "VYNN's model implies 12.45% upside for JPMorgan.",
    "VYNN's fair value of $352.28 sits above the market price.",
    "VYNN's fair value is 1.03% over the market price.",
    "VYNN rates JPMorgan a Strong Buy.",
    "VYNN's HOLD rating follows the Street's move to sell.",
    "VYNN's fair value is 14.86% under the market price.",
    "VYNN's fair value is 14.86% less than the market price.",
    "VYNN's fair value sits at a 14.86% discount to the market price.",
    "VYNN's 12-month expected return is 12.44%.",
    "VYNN's fair value is $662.70, above the market price.",
    "VYNN's model implies 3256% upside from the current market price.",
    "VYNN's fair value is 94% over the market price.",
    "VYNN does not rate Tesla a STRONG SELL.",
    "Tesla's market price declined 94% below VYNN's fair value.",
]


@pytest.mark.parametrize("sentence", REVIEW_UNCITED)
def test_every_uncited_review_repro_is_counted(sentence):
    assert _counted(sentence), sentence


@pytest.mark.parametrize("field,item", [
    ("watch", "Apple shares at $340.42 after the Epic Games ruling cut App Store fees"),
    ("monitoring", "Apple's market price decline of 33% below VYNN's fair value after the iPhone Duo recall"),
    ("holders", "Holders should sell now because the EU fined Apple $12 billion over its App Store rules."),
])
def test_review_items_with_figures_are_counted(field, item):
    kwargs = {"watch": [item]} if field == "watch" else (
        {"monitoring": [item]} if field == "monitoring" else {"holders": item})
    _, report = _validate(_response(**kwargs))
    assert report["valid"] is False, item
