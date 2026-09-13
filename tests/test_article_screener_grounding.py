from dataclasses import asdict

from src.article_screener import (
    ArticleReference,
    ArticleScreener,
    Catalyst,
    DirectQuote,
    Mitigation,
    Risk,
)
from src.evidence_extractor import EvidenceExtractor


def _screener():
    screener = ArticleScreener.__new__(ArticleScreener)
    screener.logger = None
    screener.ticker = "AAPL"
    return screener


ARTICLE = {
    "title": "Apple says iPhone demand rose 12% in China",
    "source_url": "https://www.reuters.com/technology/apple-demand/?utm_source=test",
    "publish_date": "2026-09-10",
    "serpapi_snippet": "Apple said iPhone demand rose 12% in China during the quarter.",
    "text": "Apple said iPhone demand rose 12% in China during the quarter.",
}


def _catalyst(description="iPhone demand rose 12% in China"):
    return Catalyst(
        type="product", description=description, confidence=0.8,
        supporting_evidence=["iPhone demand rose 12% in China", "Services grew 99%"],
        timeline="short-term",
        source_articles=[ArticleReference(
            title=ARTICLE["title"],
            url="https://www.reuters.com/technology/apple-demand/",
        )],
        direct_quotes=[
            DirectQuote(
                quote="Apple said iPhone demand rose 12% in China during the quarter.",
                source_article=ARTICLE["title"], source_url=ARTICLE["source_url"],
                context="quarterly update",
            ),
            DirectQuote(
                quote="Apple launched an imaginary product on Mars.",
                source_article=ARTICLE["title"], source_url=ARTICLE["source_url"],
                context="invented",
            ),
        ],
    )


def test_grounding_canonicalizes_source_and_keeps_only_verbatim_quotes():
    catalysts, risks, mitigations = _screener()._ground_insights(
        [_catalyst()], [], [], [ARTICLE]
    )
    assert risks == [] and mitigations == []
    assert len(catalysts) == 1
    item = catalysts[0]
    assert item.source_articles[0].title == ARTICLE["title"]
    assert item.source_articles[0].url == ARTICLE["source_url"]
    assert item.source_articles[0].publish_date == "2026-09-10"
    assert "demand rose 12%" in item.source_articles[0].snippet
    assert [quote.context for quote in item.direct_quotes] == ["quarterly update"]
    assert item.supporting_evidence == ["iPhone demand rose 12% in China"]
    assert item.confidence == 0.8
    assert "single_source_with_verified_excerpt" in item.confidence_basis


def test_single_source_confidence_is_capped_but_raw_model_score_is_preserved():
    catalyst = _catalyst()
    catalyst.confidence = 0.99
    catalyst.llm_confidence = 0.99

    grounded, _, _ = _screener()._ground_insights(
        [catalyst], [], [], [ARTICLE]
    )

    assert grounded[0].llm_confidence == 0.99
    assert grounded[0].confidence == 0.8
    assert "evidence_cap=0.80" in grounded[0].confidence_basis


def test_verified_direct_quote_is_limited_to_a_short_verbatim_excerpt():
    words = [f"word{index}" for index in range(40)]
    long_quote = "Apple demand " + " ".join(words)
    article = {
        **ARTICLE,
        "text": f"{ARTICLE['text']} {long_quote}",
    }
    catalyst = _catalyst()
    catalyst.direct_quotes = [DirectQuote(
        quote=long_quote,
        source_article=ARTICLE["title"],
        source_url=ARTICLE["source_url"],
        context="long excerpt",
    )]

    grounded, _, _ = _screener()._ground_insights(
        [catalyst], [], [], [article]
    )

    excerpt = grounded[0].direct_quotes[0].quote
    assert excerpt.endswith("…")
    assert len(excerpt.removesuffix("…").split()) <= 25
    assert long_quote.startswith(excerpt.removesuffix("…"))


def test_unknown_model_returned_source_is_dropped():
    catalyst = _catalyst()
    catalyst.source_articles = [ArticleReference(
        title="Invented source", url="https://fake.example/invented"
    )]
    catalyst.direct_quotes = []
    catalysts, _, _ = _screener()._ground_insights([catalyst], [], [], [ARTICLE])
    assert catalysts == []


def test_claim_with_number_absent_from_source_is_dropped():
    catalysts, _, _ = _screener()._ground_insights(
        [_catalyst("iPhone demand rose 99% in China")], [], [], [ARTICLE]
    )
    assert catalysts == []


def test_evidence_pack_uses_real_source_excerpt_not_model_description():
    catalysts, _, _ = _screener()._ground_insights([_catalyst()], [], [], [ARTICLE])
    pack = EvidenceExtractor().build_evidence_pack({
        "catalysts": [asdict(catalysts[0])], "risks": [],
    })
    evidence = pack["evidence"][0]
    assert evidence["source"] == "reuters.com"
    assert evidence["source_article_title"] == ARTICLE["title"]
    assert evidence["source_quality"] == "tier-1"
    assert evidence["snippet"] == ARTICLE["text"]
    assert "reasoning" not in evidence


def test_unknown_domain_is_not_silently_promoted_to_tier_two():
    assert EvidenceExtractor()._assess_source_quality(
        "https://unknown.example/story", "Story"
    ) == "unrated"


def test_url_less_insights_and_aggregate_sentiment_are_not_citation_evidence():
    pack = EvidenceExtractor().build_evidence_pack({
        "catalysts": [{
            "description": "Model-generated catalyst without a source",
            "confidence": 0.9,
            "source_articles": [],
        }],
        "risks": [{
            "description": "Model-generated risk without a source",
            "confidence": 0.9,
            "source_articles": [{"title": "No URL", "url": ""}],
        }],
        "analysis_summary": {
            "overall_sentiment": "bullish", "articles_analyzed": 12,
        },
        "freshness": {"status": "fresh"},
    })

    assert pack["evidence"] == []


def test_each_retained_source_must_individually_support_the_claim():
    unrelated = {
        "title": "Apple opens a new office",
        "source_url": "https://example.com/apple-office",
        "publish_date": "2026-09-09",
        "text": "Apple opened a new office in Austin.",
    }
    catalyst = _catalyst()
    catalyst.source_articles.insert(0, ArticleReference(
        title=unrelated["title"], url=unrelated["source_url"]
    ))

    catalysts, _, _ = _screener()._ground_insights(
        [catalyst], [], [], [unrelated, ARTICLE]
    )

    assert [row.title for row in catalysts[0].source_articles] == [ARTICLE["title"]]


def test_untrusted_model_confidence_and_enums_are_bounded():
    screener = _screener()
    catalysts, risks, mitigations = screener._parse_batch_analysis_data({
        "catalysts": [{
            "description": "a", "confidence": 12, "timeline": "someday",
            "supporting_evidence": "not-a-list",
        }],
        "risks": [{
            "description": "b", "confidence": -4, "severity": "apocalyptic",
            "likelihood": "certain", "supporting_evidence": [],
        }],
        "mitigations": [{
            "strategy": "c", "confidence": "NaN", "effectiveness": "perfect",
            "supporting_evidence": [],
        }],
    })

    assert catalysts[0].confidence == 1.0
    assert catalysts[0].timeline == "medium-term"
    assert catalysts[0].supporting_evidence == []
    assert risks[0].confidence == 0.0
    assert risks[0].severity == "medium"
    assert risks[0].likelihood == "medium"
    assert mitigations[0].confidence == 0.5
    assert mitigations[0].effectiveness == "medium"


def test_cross_batch_duplicate_themes_keep_only_the_strongest_grounded_claim():
    first = Catalyst(
        type="product",
        description=(
            "Apple's foldable iPhone could drive a major product upgrade cycle"
        ),
        confidence=0.93,
        supporting_evidence=["Foldable phone announced"],
        timeline="short-term",
        source_articles=[ArticleReference("Source one", "https://example.com/one")],
    )
    second = Catalyst(
        type="product",
        description="Apple announced a foldable iPhone to drive an upgrade cycle",
        confidence=0.84,
        supporting_evidence=["Sales could rise"],
        timeline="medium-term",
        source_articles=[ArticleReference("Source two", "https://example.com/two")],
    )

    result = ArticleScreener._deduplicate_insights([first, second])

    assert len(result) == 1
    assert result[0].confidence == 0.93
    assert [source.title for source in result[0].source_articles] == ["Source one"]
    assert result[0].supporting_evidence == ["Foldable phone announced"]


def test_distinct_insights_from_one_article_are_not_merged():
    services = Catalyst(
        type="financial", description="Services revenue reached a quarterly record",
        confidence=0.9, supporting_evidence=[], timeline="immediate",
    )
    earnings = Catalyst(
        type="financial", description="Earnings per share grew after margin expansion",
        confidence=0.9, supporting_evidence=[], timeline="immediate",
    )
    assert len(ArticleScreener._deduplicate_insights([services, earnings])) == 2


def test_sentiment_uses_average_unique_theme_intensity_with_dead_band():
    screener = _screener()
    catalysts = [
        Catalyst("product", f"catalyst {index}", 0.86, [], "short-term")
        for index in range(7)
    ]
    risks = [
        Risk("market", f"risk {index}", "medium", 0.88, [], "impact")
        for index in range(7)
    ]
    assert screener._determine_overall_sentiment(catalysts, risks) == "neutral"

    risks = [Risk("market", "critical event", "critical", 0.95, [], "impact")]
    assert screener._determine_overall_sentiment(catalysts, risks) == "bearish"


def test_duplicate_mitigations_merge_but_distinct_actions_remain():
    foldable_one = Mitigation(
        "slow upgrades", "Use the foldable iPhone to stimulate an upgrade cycle",
        0.9, [], "high",
    )
    foldable_two = Mitigation(
        "innovation risk", "Use a foldable iPhone launch to stimulate upgrades",
        0.8, [], "medium",
    )
    services = Mitigation(
        "hardware cyclicality", "Grow recurring services revenue", 0.9, [], "high",
    )
    result = ArticleScreener._deduplicate_insights(
        [foldable_one, foldable_two, services]
    )
    assert len(result) == 2
