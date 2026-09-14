import asyncio
import importlib
import logging
from pathlib import Path
from types import SimpleNamespace

import src.article_scraper as article_scraper_module
from src.article_filter import ArticleFilter
from src.article_screener import ArticleScreener
from src.article_scraper import ArticleScraper
from src.agents.supervisor.task_agents.news_analysis_agent import (
    _database_freshness, _merge_screening_articles,
)
from src.news_freshness import filter_fresh_articles
from src.agents.supervisor.state import PipelineStage


def test_filter_retains_screening_copy_when_mongodb_is_disabled():
    value = ArticleFilter.__new__(ArticleFilter)
    value.db_enabled = False
    value.logger = None
    value._log = lambda *_args, **_kwargs: None

    result = value._finalize_filtering([
        {
            "filename": "aapl.md",
            "title": "Apple raises guidance",
            "source_url": "https://example.com/apple-guidance",
            "publish_date": "2026-09-12T12:00:00Z",
            "scraped_at": "2026-09-12T13:00:00Z",
            "content": "Apple raised revenue guidance after stronger demand.",
            "word_count": 8,
            "serpapi_source": "Example Wire",
            "llm_score": 9.0,
        }
    ])

    assert len(result["filtered_articles"]) == 1
    assert result.get("mongodb_result") is None
    assert result["screening_articles"] == [
        {
            "file_path": None,
            "file_name": "aapl.md",
            "title": "Apple raises guidance",
            "source_url": "https://example.com/apple-guidance",
            "publish_date": "2026-09-12T12:00:00Z",
            "published_at": None,
            "scraped_at": "2026-09-12T13:00:00Z",
            "createdAt": None,
            "created_at": None,
            "text": "Apple raised revenue guidance after stronger demand.",
            "word_count": 8,
            "serpapi_snippet": "",
            "serpapi_source": "Example Wire",
            "search_category": "",
            "llm_score": 9.0,
        }
    ]


def test_unconfigured_mongodb_is_a_clean_optional_fallback(monkeypatch, tmp_path):
    monkeypatch.delenv("MONGO_URI", raising=False)
    monkeypatch.delenv("MONGO_DB", raising=False)

    article_filter = ArticleFilter(
        "AAPL", "Apple outlook", tmp_path, company_name="Apple Inc."
    )
    screener = ArticleScreener("AAPL", tmp_path, company_name="Apple Inc.")

    assert article_filter.db_enabled is False
    assert screener.load_articles_from_db() == []
    assert screener.last_freshness["reason"] == "mongodb_not_configured"

    freshness = _database_freshness("AAPL", "Apple Inc.")
    assert freshness["status"] == "unavailable"
    assert freshness["fresh_articles"] == 0
    assert freshness["reason"] == "mongodb_not_configured"


def test_current_article_replaces_thinner_database_copy_and_remains_fresh():
    url = "https://example.com/apple-guidance"
    database = [{
        "title": "Apple guidance update",
        "source_url": url,
        "publish_date": "2026-09-12T12:00:00Z",
        "text": "short",
    }]
    current = [{
        "title": "Apple raises guidance",
        "source_url": url,
        "publish_date": "2026-09-12T12:00:00Z",
        "text": "Apple raised revenue guidance after stronger demand.",
    }]

    merged = _merge_screening_articles(database, current)
    fresh, metadata = filter_fresh_articles(
        merged,
        max_age_days=90,
        minimum_articles=1,
    )

    assert len(merged) == 1
    assert merged[0]["text"] == current[0]["text"]
    assert len(fresh) == 1
    assert metadata["status"] == "fresh"


def test_standard_logger_cannot_turn_a_successful_write_into_a_failure(
    monkeypatch, tmp_path: Path,
):
    value = ArticleScraper.__new__(ArticleScraper)
    value.ticker = "AAPL"
    value.company_name = "Apple Inc."
    value.company_sector = "Technology"
    value.company_industry = "Consumer Electronics"
    value.company_dir = tmp_path
    value.searched_dir = tmp_path / "searched"
    value.max_articles = 1
    value.logger = logging.getLogger("test-news-current-run-handoff")
    value.industry_info = {"sector": "Technology"}
    value.search_queries = {"company_overview": "Apple news"}
    value._generate_comprehensive_queries = lambda: value.search_queries
    value._classify_industry = lambda: value.industry_info
    value._serpapi_news_links = lambda _query: [{
        "url": "https://example.com/apple-guidance",
        "title": "Apple raises guidance",
        "snippet": "Apple raised its outlook.",
        "published_date": "2026-09-12T12:00:00Z",
        "source_name": "Example Wire",
    }]
    value._scrape_article = lambda url: {
        "url": url,
        "title": "Apple raises guidance",
        "text": "Apple raised its outlook.",
        "word_count": 4,
    }
    monkeypatch.setattr(article_scraper_module.time, "sleep", lambda _seconds: None)

    result = value.scrape_articles()

    assert result["scraped_count"] == 1
    assert result["failed_count"] == 0
    assert len(result["scraped_files"]) == 1
    assert result["scraped_files"][0].exists()


def test_serpapi_failure_does_not_retry_after_enough_candidates(
    monkeypatch, tmp_path: Path,
):
    """Keep the evidence pack and shed latency after a later query times out."""
    value = ArticleScraper.__new__(ArticleScraper)
    value.ticker = "AAPL"
    value.company_name = "Apple Inc."
    value.company_sector = "Technology"
    value.company_industry = "Consumer Electronics"
    value.company_dir = tmp_path
    value.searched_dir = tmp_path / "searched"
    value.max_articles = 30
    value.logger = None
    value.industry_info = {"sector": "Technology"}
    value.search_queries = {
        "company_overview": "Apple news",
        "financial_activities": "Apple earnings",
        "management": "Apple management",
    }
    value._generate_comprehensive_queries = lambda: value.search_queries
    value._classify_industry = lambda: value.industry_info
    calls = []

    def search(query):
        calls.append(query)
        if query == "Apple news":
            return [{
                "url": f"https://example.com/apple-{index}",
                "title": f"Apple item {index}",
            } for index in range(article_scraper_module.NEWS_MIN_FRESH_ARTICLES)]
        return None

    value._serpapi_news_links = search
    value._scrape_article = lambda _url: None
    monkeypatch.setattr(article_scraper_module.time, "sleep", lambda _seconds: None)

    value.scrape_articles()

    assert calls == ["Apple news", "Apple earnings"]


def test_serpapi_failure_retries_when_candidate_pack_is_still_thin(
    monkeypatch, tmp_path: Path,
):
    value = ArticleScraper.__new__(ArticleScraper)
    value.ticker = "AAPL"
    value.company_name = "Apple Inc."
    value.company_sector = "Technology"
    value.company_industry = "Consumer Electronics"
    value.company_dir = tmp_path
    value.searched_dir = tmp_path / "searched"
    value.max_articles = 30
    value.logger = None
    value.industry_info = {"sector": "Technology"}
    value.search_queries = {
        "company_overview": "Apple news",
        "financial_activities": "Apple earnings",
    }
    value._generate_comprehensive_queries = lambda: value.search_queries
    value._classify_industry = lambda: value.industry_info
    calls = []

    def search(query):
        calls.append(query)
        if query == "Apple news":
            return [{"url": "https://example.com/one", "title": "One"}]
        return None

    value._serpapi_news_links = search
    value._scrape_article = lambda _url: None
    monkeypatch.setattr(article_scraper_module.time, "sleep", lambda _seconds: None)

    value.scrape_articles()

    assert calls == ["Apple news", "Apple earnings", "Apple earnings"]


def test_news_agent_screens_current_articles_during_database_outage(
    monkeypatch, tmp_path: Path,
):
    module = importlib.import_module(
        "src.agents.supervisor.task_agents.news_analysis_agent"
    )

    article = {
        "file_path": None,
        "file_name": "aapl.md",
        "title": "Apple raises guidance",
        "source_url": "https://example.com/apple-guidance",
        "publish_date": "2026-09-12T12:00:00Z",
        "text": "Apple raised revenue guidance after stronger demand.",
    }

    class FakeScraper:
        def __init__(self, *_args, **_kwargs):
            pass

        def set_logger(self, _logger):
            pass

        def get_storage_info(self):
            return {"total_articles": 0}

        def run_comprehensive_scraping(self):
            return {"scraped_count": 1, "duplicate_count": 0}

    class FakeFilter:
        def __init__(self, *_args, **_kwargs):
            pass

        def set_logger(self, _logger):
            pass

        async def filter_articles_async(self):
            return {
                "filtered_articles": [{"title": article["title"]}],
                "screening_articles": [article],
                "llm_cost": 0.0,
            }

    class FakeScreener:
        observed = None

        def __init__(self, *_args, **_kwargs):
            self.last_freshness = {"status": "unavailable"}
            self.total_llm_cost = 0.0

        def set_logger(self, _logger):
            pass

        def load_articles_from_db(self, limit=50):
            return []

        async def analyze_all_articles_async(self, articles):
            FakeScreener.observed = articles
            return [], [], [], SimpleNamespace(
                articles_analyzed=len(articles),
                overall_sentiment="neutral",
            )

        def save_structured_data(self, *_args, **_kwargs):
            pass

    class FakeState:
        ticker = "AAPL"
        company_name = "Apple Inc."
        total_llm_cost = 0.0
        current_stage = None
        logger = None
        news_analysis = None

        def __init__(self):
            self.analysis_path = tmp_path
            self.errors = []

        def get_effective_logger(self, _name):
            return None

        def log_action(self, *_args, **_kwargs):
            pass

        def log_error(self, _agent, message):
            self.errors.append(message)

    monkeypatch.setattr(module, "ArticleScraper", FakeScraper)
    monkeypatch.setattr(module, "ArticleFilter", FakeFilter)
    monkeypatch.setattr(module, "ArticleScreener", FakeScreener)
    monkeypatch.setattr(module, "_database_freshness", lambda *_args: {
        "status": "unavailable",
        "fresh_articles": 0,
    })
    state = FakeState()

    result = asyncio.run(module.news_analysis_agent(state))

    assert state.errors == []
    assert result.current_stage is PipelineStage.NEWS_ANALYSIS_COMPLETED
    assert len(FakeScreener.observed) == 1
    assert FakeScreener.observed[0]["source_url"] == article["source_url"]
    assert result.news_analysis.articles_count == 1
    assert result.news_analysis.freshness["persistence_status"] == (
        "unavailable_current_run_retained"
    )
