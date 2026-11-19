"""A cut-off news batch is split and retried, not lost (release check, 19 Nov 2026).

Claude Sonnet wrote more than 4,096 output tokens for a 9-10 article batch; the
reply was cut off, could not be read, and every Sonnet report run (24 of 24)
came out with no catalysts or risks.
"""
import asyncio
import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import llms.async_client as async_client  # noqa: E402
from src.article_screener import ARTICLES_PER_BATCH, ArticleScreener  # noqa: E402


def _screener(tmp_path, monkeypatch, cut_off_above):
    screener = ArticleScreener("AAPL", tmp_path, company_name="Apple Inc.")
    calls = []
    monkeypatch.setattr(screener, "_format_articles_for_batch", lambda articles: "x")
    monkeypatch.setattr(screener, "_create_batch_analysis_prompt",
                        lambda content, ticker, size: [{"role": "user", "content": str(size)}])
    from types import SimpleNamespace
    insight = lambda _: SimpleNamespace(confidence=0.9, type="earnings", description="d")  # noqa: E731
    monkeypatch.setattr(screener, "_parse_batch_analysis_data",
                        lambda data: ([insight(c) for c in data.get("catalysts") or []], [], []))
    monkeypatch.setattr(screener, "_ground_insights", lambda c, r, m, articles: (c, r, m))

    async def fake_llm(prompt):
        size = int(prompt[0]["content"])
        calls.append(size)
        if size > cut_off_above:
            return '{"catalysts": [{"type": "earn', 0.01      # cut off mid-reply
        return '{"catalysts": [' + ", ".join(['"c"'] * size) + "]}", 0.01

    monkeypatch.setattr(async_client, "get_async_llm", lambda: fake_llm)
    return screener, calls


def test_a_cut_off_batch_is_split_until_it_reads(tmp_path, monkeypatch):
    screener, calls = _screener(tmp_path, monkeypatch, cut_off_above=1)
    articles = [{"title": f"a{i}"} for i in range(3)]
    catalysts, risks, mitigations = asyncio.run(screener._analyze_article_batch_async(articles, 1))
    assert len(catalysts) == 3          # every article's insight arrives
    assert calls == [3, 1, 2, 1, 1]


def test_splitting_stops_two_levels_down(tmp_path, monkeypatch):
    screener, calls = _screener(tmp_path, monkeypatch, cut_off_above=0)   # nothing ever reads
    articles = [{"title": f"a{i}"} for i in range(8)]
    catalysts, _, _ = asyncio.run(screener._analyze_article_batch_async(articles, 1))
    assert catalysts == []
    assert len(calls) == 1 + 2 + 4     # 8 -> 4+4 -> 2+2+2+2, then no further


def test_batches_are_small_by_default():
    assert ARTICLES_PER_BATCH == 3
    for method in (ArticleScreener.analyze_all_articles, ArticleScreener.analyze_all_articles_async):
        assert inspect.signature(method).parameters["batch_size"].default == ARTICLES_PER_BATCH


def test_the_sequential_path_splits_too(tmp_path, monkeypatch):
    import src.article_screener as screener_module
    screener, calls = _screener(tmp_path, monkeypatch, cut_off_above=1)
    fake_async = async_client.get_async_llm()

    def fake_sync(prompt):
        return asyncio.run(fake_async(prompt))

    monkeypatch.setattr(screener_module, "get_llm", lambda: fake_sync)
    articles = [{"title": f"a{i}"} for i in range(3)]
    catalysts, _, _ = screener._analyze_article_batch(articles, 1)
    assert len(catalysts) == 3
    assert calls == [3, 1, 2, 1, 1]
