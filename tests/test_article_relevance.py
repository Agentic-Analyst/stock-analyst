from src.article_relevance import (
    article_is_about_subject,
    article_mentions_subject,
    article_uses_subject_only_as_commentator,
    company_aliases,
    filter_subject_articles,
    investment_relevance_score_cap,
)


def test_unrelated_peer_story_is_rejected_despite_subject_metadata():
    article = {
        "title": "Microsoft launches new Copilot hardware",
        "serpapi_snippet": "Microsoft shares gained after the product event.",
        "content": "The Redmond company discussed Windows and Azure.",
        "ticker": "AAPL",
        "company": "Apple Inc.",
    }
    assert article_mentions_subject(article, "AAPL", "Apple Inc.") is False


def test_comparative_story_is_kept_when_the_subject_is_actually_present():
    article = {
        "title": "Microsoft and Apple take different approaches to on-device AI",
        "content": "The comparison covers Apple margins and Microsoft's cloud strategy.",
    }
    assert article_mentions_subject(article, "AAPL", "Apple Inc.") is True


def test_one_passing_body_reference_in_a_peer_story_is_not_prominent_enough():
    article = {
        "title": "Microsoft changes Xbox pricing after memory costs rise",
        "serpapi_snippet": "Microsoft shares moved after Stifel changed its target.",
        "content": (
            "Microsoft discussed Xbox, Windows, Azure, and console margins. "
            "A commentator also noted Apple's higher MacBook prices."
        ),
    }
    assert article_mentions_subject(article, "AAPL", "Apple Inc.") is False


def test_exact_ticker_or_url_token_can_establish_identity():
    assert article_mentions_subject(
        {"title": "AAPL earnings preview"}, "AAPL", None
    )
    assert article_mentions_subject(
        {"title": "Earnings preview", "url": "https://example.com/stocks/aapl/outlook"},
        "AAPL", None,
    )


def test_short_common_ticker_requires_an_explicit_market_form():
    assert not article_mentions_subject(
        {"title": "C language tools can improve build times"}, "C", "Citigroup Inc."
    )
    assert article_mentions_subject(
        {"title": "NYSE:C earnings preview focuses on credit costs"},
        "C", "Citigroup Inc.",
    )


def test_legal_suffixes_and_distinctive_short_name_are_removed_safely():
    assert company_aliases("JPMorgan Chase & Co.") == [
        "jpmorgan chase", "jp morgan", "jpmorgan",
    ]


def test_research_call_on_another_company_is_not_news_about_the_analyst():
    article = {
        "title": "Porsche AG Stock Gains as JP Morgan Reiterates Overweight Rating",
        "content": "JP Morgan analysts discussed Porsche shares and vehicle demand.",
    }
    assert article_mentions_subject(article, "JPM", "JPMorgan Chase & Co.")
    assert article_uses_subject_only_as_commentator(
        article, "JPM", "JPMorgan Chase & Co."
    )
    assert not article_is_about_subject(article, "JPM", "JPMorgan Chase & Co.")


def test_commodity_forecast_is_not_a_catalyst_for_research_provider():
    article = {
        "title": (
            "Gold, Silver Pullback Is Not The End Of Rally, JPMorgan Reportedly "
            "Says After Forecast Cut"
        ),
        "content": "JPMorgan lowered its gold-price forecast after softer demand.",
    }
    assert not article_is_about_subject(article, "JPM", "JPMorgan Chase & Co.")


def test_subjects_own_corporate_action_remains_eligible():
    article = {
        "title": "JPMorgan raises dividend and announces a new share buyback",
        "content": "JPMorgan Chase said its board approved both capital actions.",
    }
    assert article_is_about_subject(article, "JPM", "JPMorgan Chase & Co.")


def test_subject_stock_article_remains_eligible_when_another_analyst_comments():
    article = {
        "title": "JPM Stock Gains After Goldman Sachs Raises Its Price Target",
        "content": "JPMorgan Chase shares rose after the new target was published.",
    }
    assert article_is_about_subject(article, "JPM", "JPMorgan Chase & Co.")


def test_filter_reports_rejection_count():
    kept, rejected = filter_subject_articles(
        [
            {"title": "Apple reports quarterly results"},
            {"title": "Copart reports quarterly results"},
        ],
        "AAPL", "Apple Inc.",
    )
    assert len(kept) == 1
    assert rejected == 1


def test_consumer_availability_liveblog_is_not_investment_evidence():
    article = {
        "title": "iPhone 18 Pro Max live pre-order updates: which UK retailers have stock",
        "serpapi_snippet": "Follow availability at major mobile networks and shops.",
    }
    assert investment_relevance_score_cap(article) == 3.0


def test_availability_story_with_financial_demand_evidence_is_not_capped():
    article = {
        "title": "iPhone availability update",
        "serpapi_snippet": "Shipment forecast rises as Apple reports stronger unit sales.",
    }
    assert investment_relevance_score_cap(article) is None
