"""The chat agent reasons on CHAT_MODEL; the tools' bulk steps stay on the worker's model (19 Nov 2026).

On Claude Sonnet the news insight step cost ~$0.45 per report against ~$0.007
on GPT-6 Luna (production, Oct-Nov 2026), so only the chat agent's own calls
use CHAT_MODEL.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import llms.async_client as async_client  # noqa: E402
from llms.config import init_llm  # noqa: E402


def _keys(monkeypatch, openai=True, bedrock=True):
    for key, on in (("OPENAI_API_KEY", openai), ("AWS_BEARER_TOKEN_BEDROCK", bedrock)):
        if on:
            monkeypatch.setenv(key, "set-for-the-test")
        else:
            monkeypatch.delenv(key, raising=False)


def test_the_chat_agent_uses_the_chat_model_and_the_tools_keep_the_worker_s(monkeypatch):
    _keys(monkeypatch)
    monkeypatch.setenv("CHAT_MODEL", "claude-sonnet-5-5-bedrock")
    init_llm("gpt-6-luna")
    assert async_client.get_chat_llm().model_name == "claude-sonnet-5-5-bedrock"
    assert async_client.get_async_llm().model_name == "gpt-6-luna"


def test_without_the_chat_model_s_key_the_chat_agent_uses_the_worker_s_model(monkeypatch):
    _keys(monkeypatch, bedrock=False)
    monkeypatch.setenv("CHAT_MODEL", "claude-sonnet-5-5-bedrock")
    init_llm("gpt-6-luna")
    assert async_client.get_chat_llm().model_name == "gpt-6-luna"


def test_no_chat_model_means_the_worker_s_model(monkeypatch):
    _keys(monkeypatch)
    monkeypatch.delenv("CHAT_MODEL", raising=False)
    init_llm("gpt-6-luna")
    assert async_client.get_chat_llm().model_name == "gpt-6-luna"


def test_an_openai_outage_does_not_stop_the_claude_chat_agent(monkeypatch):
    # Review, 19 Nov 2026: one shared breaker let failing OpenAI news batches
    # short-circuit the chat agent's healthy Claude turns.
    _keys(monkeypatch)
    async_client.reset_circuit_breaker()
    openai_side = async_client.AsyncLLMProvider("gpt-6-luna")
    claude_side = async_client.AsyncLLMProvider("claude-sonnet-5-5-bedrock")
    for _ in range(20):
        async_client._breaker_for(openai_side.is_openai).record_failure()
    assert async_client._breaker_for(openai_side.is_openai).is_open()
    assert not async_client._breaker_for(claude_side.is_openai).is_open()
    async_client.reset_circuit_breaker()
    assert not async_client._breaker_for(openai_side.is_openai).is_open()
