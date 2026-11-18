"""Claude on Amazon Bedrock, authenticated with a Bedrock API key.

The Anthropic SDK's own Bedrock client signs requests with full AWS account keys.
A Bedrock API key (``AWS_BEARER_TOKEN_BEDROCK``) can call models and nothing else,
so this module sends the same Messages-API request VYNN already builds to Bedrock's
InvokeModel endpoint with that key as a bearer token, and returns the SDK's own
``Message`` object, so every caller (tool loop, plain calls, cost) is unchanged.

Selected by model name: ``claude-haiku-5-5-bedrock``, ``claude-sonnet-5-5-bedrock``,
``claude-opus-5-5-bedrock`` (``CHAT_MODEL`` or ``--llm``). Region from ``AWS_REGION``
or ``AWS_DEFAULT_REGION`` (default us-east-1); the global inference profiles route
the request to any commercial region.
"""
from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Tuple
from urllib.parse import quote

# VYNN model name -> Bedrock global inference profile.
PROFILES = {
    "claude-haiku-5-5-bedrock": "global.anthropic.claude-haiku-5-5",
    "claude-sonnet-5-5-bedrock": "global.anthropic.claude-sonnet-5-5",
    "claude-opus-5-5-bedrock": "global.anthropic.claude-opus-5-5",
}
# USD per million tokens on Bedrock: input, output, cache read, cache write
# (taste-is-all-you-need pricing table, as of 2026-10-16).
PRICES = {
    "claude-haiku-5-5-bedrock": (0.10, 0.50, 0.01, 0.125),
    "claude-sonnet-5-5-bedrock": (2.00, 10.00, 0.10, 2.50),
    "claude-opus-5-5-bedrock": (4.00, 20.00, 0.20, 5.00),
}
ANTHROPIC_VERSION = "bedrock-2023-05-31"
TIMEOUT_SECONDS = 120.0


class BedrockError(Exception):
    """A refused or failed Bedrock call; the message carries the HTTP status (never the key)."""


def is_bedrock_model(model: str) -> bool:
    return model in PROFILES


def cost(response: Any, model: str) -> float:
    usage = getattr(response, "usage", None)
    if usage is None or model not in PRICES:
        return 0.0
    p_in, p_out, p_read, p_write = PRICES[model]
    return (
        (getattr(usage, "input_tokens", 0) or 0) * p_in
        + (getattr(usage, "output_tokens", 0) or 0) * p_out
        + (getattr(usage, "cache_read_input_tokens", 0) or 0) * p_read
        + (getattr(usage, "cache_creation_input_tokens", 0) or 0) * p_write
    ) / 1_000_000


def _plain(value: Any) -> Any:
    """SDK content blocks (an assistant turn appended verbatim) back to JSON."""
    if hasattr(value, "model_dump"):
        return value.model_dump(exclude_none=True)
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    return value


_CACHE = {"type": "ephemeral"}
_NO_CACHE_BLOCKS = ("thinking", "redacted_thinking")


def _with_cache_points(body: Dict[str, Any]) -> Dict[str, Any]:
    """Mark the shared prefix for prompt caching (tools, system, transcript so far).

    The chat sends the same ~20 tool definitions and long instructions on every
    turn of its loop (up to 8 per question) and the transcript only grows, so a
    cache point after the tools, after the system text and on the newest message
    lets each turn re-read the earlier ones at a tenth of the input price.
    Content under the model's minimum is silently not cached (no error).
    """
    tools = body.get("tools")
    if isinstance(tools, list) and tools and isinstance(tools[-1], dict):
        tools[-1] = {**tools[-1], "cache_control": _CACHE}
    system = body.get("system")
    if isinstance(system, str) and system.strip():
        body["system"] = [{"type": "text", "text": system, "cache_control": _CACHE}]
    messages = body.get("messages")
    if isinstance(messages, list) and messages and isinstance(messages[-1], dict):
        last = dict(messages[-1])
        content = last.get("content")
        if isinstance(content, str) and content.strip():
            last["content"] = [{"type": "text", "text": content, "cache_control": _CACHE}]
        elif isinstance(content, list) and content and isinstance(content[-1], dict) \
                and content[-1].get("type") not in _NO_CACHE_BLOCKS:
            last["content"] = content[:-1] + [{**content[-1], "cache_control": _CACHE}]
        messages[-1] = last
    return body


def _log_usage(response: Any, model: str) -> None:
    """One line per call, so a run can show whether the cache is hit."""
    try:
        from logger import get_logger
        logger = get_logger()
        u = response.usage
        line = (f"[bedrock] {model} usage: input {u.input_tokens}, cache read "
                f"{getattr(u, 'cache_read_input_tokens', 0) or 0}, cache write "
                f"{getattr(u, 'cache_creation_input_tokens', 0) or 0}, output {u.output_tokens}")
        if logger:
            logger.info(line)
    except Exception:
        pass


def _request(kwargs: Dict[str, Any]) -> Tuple[str, Dict[str, Any], Dict[str, str]]:
    model = kwargs.get("model", "")
    if model not in PROFILES:
        raise BedrockError(f"{model!r} is not a Bedrock model name")
    token = os.getenv("AWS_BEARER_TOKEN_BEDROCK", "")
    if not token:
        raise BedrockError("AWS_BEARER_TOKEN_BEDROCK is not set")
    region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"
    url = f"https://bedrock-runtime.{region}.amazonaws.com/model/{quote(PROFILES[model], safe='')}/invoke"
    # Claude 5.5 refuses sampling settings ("`temperature` is deprecated for this
    # model", HTTP 400), and VYNN sends one with every call.
    body = {k: _plain(v) for k, v in kwargs.items()
            if k not in ("model", "timeout", "stream", "temperature", "top_p", "top_k")}
    body["anthropic_version"] = ANTHROPIC_VERSION
    _with_cache_points(body)
    headers = {"authorization": f"Bearer {token}", "content-type": "application/json",
               "accept": "application/json"}
    return url, body, headers


def _message(status: int, payload: Any, text: str):
    if status == 200:
        from anthropic.types import Message
        return Message.model_validate(payload)
    # The status is kept in the message so the callers' retry rules (429, 5xx,
    # "throttl") keep working; the body is AWS's error text, which holds no key.
    raise BedrockError(f"Bedrock HTTP {status}: {text[:300]}")


class _AsyncMessages:
    async def create(self, **kwargs: Any):
        import httpx
        url, body, headers = _request(kwargs)
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS, trust_env=False) as client:
            r = await client.post(url, json=body, headers=headers)
        message = _message(r.status_code, r.json() if r.status_code == 200 else None, r.text)
        _log_usage(message, kwargs.get("model", ""))
        return message


class _Messages:
    def create(self, **kwargs: Any):
        import httpx
        url, body, headers = _request(kwargs)
        with httpx.Client(timeout=TIMEOUT_SECONDS, trust_env=False) as client:
            r = client.post(url, json=body, headers=headers)
        message = _message(r.status_code, r.json() if r.status_code == 200 else None, r.text)
        _log_usage(message, kwargs.get("model", ""))
        return message


class AsyncBedrockClaude:
    """Stands in for ``anthropic.AsyncAnthropic``: only ``messages.create`` is used."""
    def __init__(self) -> None:
        self.messages = _AsyncMessages()


class BedrockClaude:
    """Stands in for ``anthropic.Anthropic``."""
    def __init__(self) -> None:
        self.messages = _Messages()


def chat_function(model: str):
    """A plain-text call for LLMProvider.MODELS: (messages, temperature) -> (text, cost)."""
    def call(messages: List[Dict], temperature: float = 0.3) -> Tuple[str, float]:
        from logger import get_logger
        logger = get_logger()
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system") or None
        conv = [{"role": m["role"], "content": m["content"]} for m in messages if m["role"] in ("user", "assistant")]
        kwargs = {"model": model, "messages": conv, "temperature": temperature, "max_tokens": 4096}
        if system:
            kwargs["system"] = system
        last = None
        for attempt in range(3):
            try:
                response = BedrockClaude().messages.create(**kwargs)
                spent = cost(response, model)
                if logger:
                    logger.llm_call(model, spent, response.usage.input_tokens + response.usage.output_tokens)
                text = "".join(getattr(b, "text", "") for b in response.content if getattr(b, "type", "") == "text")
                return text, spent
            except BedrockError as error:
                last = error
                retry = any(s in str(error) for s in ("HTTP 429", "HTTP 5", "hrottl"))
                if not retry or attempt == 2:
                    break
                time.sleep(2 * (attempt + 1))
        raise Exception(f"Bedrock call failed: {last}")
    return call
