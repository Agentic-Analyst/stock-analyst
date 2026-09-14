import asyncio

import src.article_filter as article_filter_module
from src.article_filter import ArticleFilter


def _filter():
    value = ArticleFilter.__new__(ArticleFilter)
    value.llm_call_count = 0
    value.total_llm_cost = 0.0
    value.batch_size = 10
    value.logger = None
    value._log = lambda *_args, **_kwargs: None
    value._build_relevance_prompt = lambda _batch: "score these"
    return value


def test_missing_and_out_of_range_scores_fail_closed_and_are_bounded():
    value = _filter()

    assert value._parse_llm_scores("1:12.5 3:7", 3) == [10.0, 0.0, 7.0]
    assert value._parse_llm_scores("not structured", 2) == [0.0, 0.0]


def test_sync_llm_failure_rejects_entire_batch(monkeypatch):
    def broken_llm():
        def invoke(*_args, **_kwargs):
            raise TimeoutError("provider timeout")
        return invoke

    monkeypatch.setattr(article_filter_module, "get_llm", broken_llm)
    value = _filter()
    articles = [{"title": "one"}, {"title": "two"}]

    result = value._process_llm_batch(articles)

    assert [row["llm_score"] for row in result] == [0.0, 0.0]


def test_async_batch_failure_rejects_entire_batch():
    value = _filter()

    async def broken(_batch):
        raise TimeoutError("provider timeout")

    value._process_llm_batch_async = broken
    articles = [{"title": "one"}, {"title": "two"}]

    result = asyncio.run(value._score_articles_with_llm_async(articles))

    assert [row["llm_score"] for row in result] == [0.0, 0.0]


def test_llm_cannot_promote_consumer_availability_liveblog(monkeypatch):
    def high_scoring_llm():
        return lambda *_args, **_kwargs: ("1:9", 0.0)

    monkeypatch.setattr(article_filter_module, "get_llm", high_scoring_llm)
    value = _filter()
    articles = [{
        "title": "iPhone 18 Pro Max live pre-order updates: which UK retailers have stock",
        "serpapi_snippet": "Follow availability at mobile networks and shops.",
    }]

    result = value._process_llm_batch(articles)

    assert result[0]["llm_score"] == 3.0
