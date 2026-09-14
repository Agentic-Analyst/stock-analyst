import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from src.agents.tools.prediction_market_tools import GetPredictionMarketsTool


def market(**overrides):
    value = {
        "id": "gamma-1", "conditionId": "0xcondition",
        "question": "Will rates fall?", "active": True, "closed": False,
        "outcomes": '["Yes", "No"]', "outcomePrices": '["0.42", "0.58"]',
        "clobTokenIds": '["123", "456"]', "volumeNum": "1000",
        "liquidityNum": "250", "endDate": "2027-01-01T00:00:00Z",
        "oneWeekPriceChange": 0.03,
    }
    value.update(overrides)
    return value


def test_exact_search_miss_does_not_substitute_unrelated_trending_markets(monkeypatch):
    import requests

    calls = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"events": []}

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return Response()

    monkeypatch.setattr(requests, "get", get)
    result = json.loads(asyncio.run(
        GetPredictionMarketsTool().execute("Cerebras earnings", limit=4)
    ))

    assert result["status"] == "ok" and result["markets"] == []
    assert "No matching open prediction markets" in result["note"]
    assert len(calls) == 1 and calls[0][0].endswith("/public-search")
    assert calls[0][1]["params"]["optimized"] == "false"
    assert calls[0][1]["params"]["search_tags"] == "false"


def test_search_preserves_all_outcomes_and_labels_gamma_as_indicative(monkeypatch):
    import requests
    from src.agents.tools import prediction_market_tools as module

    module._cache.clear()

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"events": [{"id": "event-1", "slug": "rates", "markets": [market()]}]}

    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: Response())
    result = json.loads(asyncio.run(GetPredictionMarketsTool().execute("rates", limit=4)))

    found = result["markets"][0]
    assert found["market_id"] == "0xcondition"
    assert found["outcomes"] == [
        {"outcome_id": "123", "label": "Yes", "indicative_probability": 0.42},
        {"outcome_id": "456", "label": "No", "indicative_probability": 0.58},
    ]
    assert result["source"] == "gamma_indicative"
    assert result["capabilities"]["executable_quotes"] is False
    assert result["capabilities"]["settlement_confirmation"] is False


def test_incoherent_probability_vector_is_suppressed_not_renormalized(monkeypatch):
    import requests
    from src.agents.tools import prediction_market_tools as module

    module._cache.clear()

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"events": [{"markets": [market(
                outcomePrices='["0.9", "0.9"]',
            )]}]}

    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: Response())
    found = json.loads(asyncio.run(GetPredictionMarketsTool().execute("rates")))["markets"][0]

    assert found["indicative_probability_status"] == "incoherent"
    assert found["indicative_probability_sum"] == 1.8
    assert all(row["indicative_probability"] is None for row in found["outcomes"])


def test_research_preserves_resolution_rules_without_calling_them_a_url(monkeypatch):
    import requests
    from src.agents.tools import prediction_market_tools as module

    module._cache.clear()

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"events": [{"markets": [market(
                description="Rule one.\nRule two.",
                resolutionSource="Official agency release controls.\nRevisions do not count.",
            )]}]}

    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: Response())
    found = json.loads(asyncio.run(GetPredictionMarketsTool().execute("rates")))["markets"][0]
    assert found["description"] == "Rule one.\nRule two."
    assert found["resolution_url"] is None
    assert found["resolution_source_text"] == (
        "Official agency release controls.\nRevisions do not count."
    )
    assert found["resolution_metadata_available"] is True


def test_event_level_resolution_metadata_fills_sparse_market_rows(monkeypatch):
    import requests
    from src.agents.tools import prediction_market_tools as module

    module._cache.clear()

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"events": [{
                "description": "Event-level resolution rules.",
                "resolutionSource": "https://example.gov/release",
                "markets": [market(description=None, resolutionSource=None)],
            }]}

    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: Response())
    found = json.loads(asyncio.run(GetPredictionMarketsTool().execute("rates")))["markets"][0]

    assert found["description"] == "Event-level resolution rules."
    assert found["resolution_url"] == "https://example.gov/release"
    assert found["resolution_metadata_available"] is True


def test_bad_identity_arrays_are_not_guessed(monkeypatch):
    import requests
    from src.agents.tools import prediction_market_tools as module

    module._cache.clear()

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"events": [{"markets": [market(clobTokenIds='["123"]')]}]}

    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: Response())
    found = json.loads(asyncio.run(GetPredictionMarketsTool().execute("rates")))["markets"][0]
    assert found["outcome_identities_complete"] is False
    assert all(row["outcome_id"] is None for row in found["outcomes"])


def test_provider_exception_is_generic_and_limits_are_enforced(monkeypatch):
    import requests
    from src.agents.tools import prediction_market_tools as module

    module._cache.clear()

    def fail(*args, **kwargs):
        raise requests.ConnectionError("secret internal hostname")

    monkeypatch.setattr(requests, "get", fail)
    failed = json.loads(asyncio.run(GetPredictionMarketsTool().execute("rates")))
    invalid = json.loads(asyncio.run(GetPredictionMarketsTool().execute("rates", limit=99)))
    assert failed["status"] == "error"
    assert "secret internal hostname" not in failed["error"]
    assert invalid["status"] == "error"


def test_one_transient_timeout_is_retried(monkeypatch):
    import requests
    from src.agents.tools import prediction_market_tools as module

    module._cache.clear()
    calls = 0

    class Response:
        headers = {}

        def raise_for_status(self):
            return None

        def json(self):
            return {"events": [{"markets": [market()]}]}

        def close(self):
            return None

    def get(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise requests.ReadTimeout("temporary")
        return Response()

    monkeypatch.setattr(requests, "get", get)
    result = json.loads(asyncio.run(GetPredictionMarketsTool().execute("rates")))

    assert calls == 2
    assert result["status"] == "ok" and result["count"] == 1


def test_malformed_resolution_date_is_excluded_instead_of_called_open(monkeypatch):
    import requests
    from src.agents.tools import prediction_market_tools as module

    module._cache.clear()

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"events": [{"markets": [market(endDate="not-a-date")]}]}

    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: Response())
    result = json.loads(asyncio.run(GetPredictionMarketsTool().execute("rates")))

    assert result["markets"] == []


def test_oversized_prediction_response_fails_closed_without_parsing(monkeypatch):
    import requests
    from src.agents.tools import prediction_market_tools as module

    module._cache.clear()

    class Response:
        headers = {"Content-Length": str(module.MAX_UPSTREAM_BYTES + 1)}

        def raise_for_status(self):
            return None

        def close(self):
            return None

        def json(self):
            raise AssertionError("oversized body must not be parsed")

    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: Response())
    result = json.loads(asyncio.run(GetPredictionMarketsTool().execute("rates")))

    assert result["status"] == "error"
    assert "size limit" not in result["error"]


def test_natural_language_query_retries_a_bounded_market_alias(monkeypatch):
    import requests
    from src.agents.tools import prediction_market_tools as module

    module._cache.clear()
    seen = []

    class Response:
        def __init__(self, query):
            self.query = query

        def raise_for_status(self):
            return None

        def json(self):
            return ({"events": [{"markets": [market(
                question="Will the Fed decrease interest rates by 25 bps?"
            )]}]}
                    if self.query == "Fed" else {"events": []})

    def get(_url, **kwargs):
        query = kwargs["params"]["q"]
        seen.append(query)
        return Response(query)

    monkeypatch.setattr(requests, "get", get)
    result = json.loads(asyncio.run(
        GetPredictionMarketsTool().execute("Federal Reserve rate cut")
    ))

    assert result["count"] == 1
    assert seen == ["Federal Reserve rate cut", "Fed"]
    assert result["query_variants_tried"] == seen


def test_fuzzy_provider_false_positives_are_rejected(monkeypatch):
    import requests
    from src.agents.tools import prediction_market_tools as module

    module._cache.clear()

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"events": [{
                "title": "IPOs before 2027", "slug": "ipos-before-2027",
                "markets": [market(question="Anthropic IPO before 2027?")],
            }]}

    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: Response())
    result = json.loads(asyncio.run(
        GetPredictionMarketsTool().execute("Cerebras earnings")
    ))

    assert result["status"] == "ok" and result["markets"] == []
    assert "No matching open prediction markets" in result["note"]
