"""gpt-6-luna must be called in its documented Chat Completions compatible mode.

gpt-6-luna defaults to reasoning effort "medium". Against the live API on
2026-09-27 that default rejected both things this codebase sends on every call:
  - temperature 0.3: "'temperature' does not support 0.3 with this model";
  - function tools: "Function tools with reasoning_effort are not supported for
    gpt-6-luna in /v1/chat/completions ... set reasoning_effort to 'none'".
With reasoning_effort "none" both succeeded. Other models' requests must not
change.
"""
import asyncio
import os
import sys
import types

import pytest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "src"))

from llms import async_client  # noqa: E402
from llms import openai as openai_llm  # noqa: E402
from llms.config import LLMProvider  # noqa: E402


def _response(text="ok", tool_calls=None):
    usage = types.SimpleNamespace(prompt_tokens=1000, completion_tokens=1000, total_tokens=2000)
    message = types.SimpleNamespace(content=text, tool_calls=tool_calls)
    return types.SimpleNamespace(usage=usage, choices=[types.SimpleNamespace(message=message)])


class _Recorder:
    def __init__(self):
        self.kwargs = None


def _sync_client(recorder):
    class Completions:
        def create(self, **kwargs):
            recorder.kwargs = kwargs
            return _response()

    class Client:
        def __init__(self, *args, **kwargs):
            self.chat = types.SimpleNamespace(completions=Completions())

    return Client


def _async_client(recorder):
    class Completions:
        async def create(self, **kwargs):
            recorder.kwargs = kwargs
            return _response()

    return types.SimpleNamespace(chat=types.SimpleNamespace(completions=Completions()))


def test_only_gpt_6_luna_needs_reasoning_effort_none():
    assert openai_llm.openai_request_options("gpt-6-luna") == {"reasoning_effort": "none"}
    for model in ("gpt-4o-mini", "gpt-4o-mini-2024-07-18", "gpt-5.4-mini", "gpt-5-mini", ""):
        assert openai_llm.openai_request_options(model) == {}


def test_the_sync_call_sends_reasoning_effort_none_with_its_temperature(monkeypatch):
    recorder = _Recorder()
    monkeypatch.setattr(openai_llm, "OpenAI", _sync_client(recorder))
    text, cost = openai_llm.gpt_6_luna([{"role": "user", "content": "hi"}], 0.3)
    assert text == "ok"
    assert recorder.kwargs["model"] == "gpt-6-luna"
    assert recorder.kwargs["reasoning_effort"] == "none"
    assert recorder.kwargs["temperature"] == 0.3
    assert cost == pytest.approx(1000 * 0.00010 / 1000 + 1000 * 0.00050 / 1000)

    # Every other model's request is exactly what it was.
    openai_llm.gpt_5_4_mini([{"role": "user", "content": "hi"}], 0.3)
    assert recorder.kwargs["model"] == "gpt-5.4-mini"
    assert "reasoning_effort" not in recorder.kwargs


def test_the_chat_agent_tool_call_sends_reasoning_effort_none(monkeypatch):
    recorder = _Recorder()
    monkeypatch.setattr(async_client, "_get_async_openai", lambda: _async_client(recorder))
    tools = [{"type": "function", "function": {
        "name": "get_price", "parameters": {"type": "object", "properties": {}}}}]
    asyncio.run(async_client._call_openai_tools(
        "gpt-6-luna", [{"role": "user", "content": "AAPL?"}], tools, 0.4, "auto",
    ))
    assert recorder.kwargs["reasoning_effort"] == "none"
    assert recorder.kwargs["tools"] == tools
    assert recorder.kwargs["temperature"] == 0.4

    asyncio.run(async_client._call_openai_tools(
        "gpt-5.4-mini", [{"role": "user", "content": "AAPL?"}], tools, 0.4, "auto",
    ))
    assert "reasoning_effort" not in recorder.kwargs


def test_the_async_text_call_sends_reasoning_effort_none(monkeypatch):
    recorder = _Recorder()
    monkeypatch.setattr(async_client, "_get_async_openai", lambda: _async_client(recorder))
    asyncio.run(async_client._call_openai_async("gpt-6-luna", [{"role": "user", "content": "hi"}], 0.3))
    assert recorder.kwargs["reasoning_effort"] == "none"
    asyncio.run(async_client._call_openai_async("gpt-4o-mini", [{"role": "user", "content": "hi"}], 0.3))
    assert "reasoning_effort" not in recorder.kwargs


def test_gpt_6_luna_is_a_selectable_openai_model(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    assert "gpt-6-luna" in LLMProvider.list_models()
    provider = LLMProvider("gpt-6-luna")
    assert provider.current_model == "gpt-6-luna"
    assert "gpt-6-luna" in async_client._OPENAI_MODELS
