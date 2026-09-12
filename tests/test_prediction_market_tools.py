import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from src.agents.tools.prediction_market_tools import GetPredictionMarketsTool


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
    assert "No open prediction markets" in result["note"]
    assert len(calls) == 1 and calls[0][0].endswith("/public-search")
