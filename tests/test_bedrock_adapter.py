"""Claude on Bedrock with a Bedrock API key: the request VYNN builds, routed by model name."""
import os
import sys
from types import SimpleNamespace

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "src"))

import pytest  # noqa: E402
from llms import bedrock  # noqa: E402
from llms.config import LLMProvider  # noqa: E402

PAYLOAD = {"id": "msg_1", "type": "message", "role": "assistant", "model": "claude-haiku-5-5",
           "content": [{"type": "text", "text": "Looking it up."},
                       {"type": "tool_use", "id": "tu_1", "name": "get_prices", "input": {"ticker": "HSN.AX"}}],
           "stop_reason": "tool_use", "stop_sequence": None,
           "usage": {"input_tokens": 10_000, "output_tokens": 400, "cache_read_input_tokens": 0}}


def test_request_goes_to_the_global_profile_with_the_key_as_bearer(monkeypatch):
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "test-token")
    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    url, body, headers = bedrock._request({"model": "claude-haiku-5-5-bedrock", "max_tokens": 64, "temperature": 0.4,
                                           "messages": [{"role": "user", "content": "hi"}], "timeout": 60})
    assert "temperature" not in body           # Claude 5.5 refuses it with HTTP 400
    assert url == "https://bedrock-runtime.us-east-1.amazonaws.com/model/global.anthropic.claude-haiku-5-5/invoke"
    assert headers["authorization"] == "Bearer test-token"
    assert "model" not in body and "timeout" not in body and body["anthropic_version"] == "bedrock-2023-05-31"


def test_reply_becomes_the_sdk_message_and_costs_bedrock_prices():
    msg = bedrock._message(200, PAYLOAD, "")
    assert [b.type for b in msg.content] == ["text", "tool_use"] and msg.content[1].input == {"ticker": "HSN.AX"}
    assert bedrock.cost(msg, "claude-haiku-5-5-bedrock") == pytest.approx((10_000 * 0.10 + 400 * 0.50) / 1e6)
    # an assistant turn appended verbatim goes back as plain JSON
    assert bedrock._plain(msg.content)[1] == {"type": "tool_use", "id": "tu_1", "name": "get_prices",
                                              "input": {"ticker": "HSN.AX"}}


def test_errors_keep_the_status_for_the_retry_rules_and_never_the_key(monkeypatch):
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "test-token")
    with pytest.raises(bedrock.BedrockError, match="HTTP 429") as caught:
        bedrock._message(429, None, '{"message":"Too many requests"}')
    assert "test-token" not in str(caught.value)
    with pytest.raises(bedrock.BedrockError, match="not set"):
        monkeypatch.delenv("AWS_BEARER_TOKEN_BEDROCK")
        bedrock._request({"model": "claude-sonnet-5-5-bedrock", "messages": []})


def test_models_are_registered_and_take_the_anthropic_tool_path():
    from llms.async_client import AsyncLLMProvider
    for name in bedrock.PROFILES:
        assert LLMProvider.MODELS[name]["api_key"] == "AWS_BEARER_TOKEN_BEDROCK"
        assert AsyncLLMProvider(name).is_openai is False
