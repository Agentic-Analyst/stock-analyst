from datetime import datetime, timezone

from news_freshness import article_publication_datetime, filter_fresh_articles


NOW = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)


def test_absolute_iso_and_conventional_dates_are_parsed():
    assert article_publication_datetime({"publish_date": "2026-09-10T08:00:00Z"}).year == 2026
    assert article_publication_datetime({"publish_date": "Sep 10, 2026"}).day == 10


def test_relative_date_is_anchored_to_scrape_time_not_run_time():
    published = article_publication_datetime({
        "publish_date": "5 days ago",
        "scraped_at": "2025-11-18T12:00:00Z",
    })
    assert published.isoformat() == "2025-11-13T12:00:00+00:00"


def test_ingestion_time_never_makes_an_undated_article_current():
    article = {"title": "old backfill", "createdAt": "2026-09-12T10:00:00Z"}
    fresh, meta = filter_fresh_articles(
        [article], max_age_days=90, minimum_articles=1, as_of=NOW,
    )
    assert fresh == []
    assert meta["unknown_date_articles_excluded"] == 1
    assert meta["status"] == "unavailable"


def test_stale_future_and_undated_articles_are_excluded_and_reported():
    articles = [
        {"title": "fresh", "publish_date": "2026-09-11"},
        {"title": "stale", "publish_date": "2025-11-18"},
        {"title": "future", "publish_date": "2027-01-01"},
        {"title": "unknown", "publish_date": "sometime"},
    ]
    fresh, meta = filter_fresh_articles(
        articles, max_age_days=90, minimum_articles=2, as_of=NOW,
    )
    assert [row["title"] for row in fresh] == ["fresh"]
    assert meta["status"] == "limited"
    assert meta["stale_articles_excluded"] == 1
    assert meta["future_date_articles_excluded"] == 1
    assert meta["unknown_date_articles_excluded"] == 1
