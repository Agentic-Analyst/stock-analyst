"""
Async LLM client — additive, non-breaking counterpart to the synchronous
``get_llm()`` path in ``llms/config.py``.

Why this exists
---------------
The news pipeline analyses articles in independent batches, but the synchronous
client forces those batches to run one-after-another (see
``article_screener.analyze_all_articles``). Each batch is a self-contained LLM
call whose results are simply concatenated, so they are embarrassingly
parallelisable. This module exposes an ``async`` calling surface backed by
``AsyncAnthropic`` / ``AsyncOpenAI`` so callers can fan batches out with
``asyncio.gather`` under a concurrency cap.

Design guarantees
-----------------
* **Purely additive.** The sync ``LLMProvider`` in ``config.py`` is untouched;
  nothing here changes existing behaviour. Callers opt in via ``get_async_llm()``.
* **Same contract.** ``await get_async_llm()(messages, temperature)`` returns the
  same ``(text, cost)`` tuple as the sync path, using the same model selected by
  ``init_llm()`` and the same cost math.
* **Exponential backoff + jitter.** Replaces the old fixed 1-second retry, so a
  rate-limited call backs off (0.5s, 1s, 2s, 4s … + jitter) instead of hammering.
* **Circuit breaker.** After a run-wide threshold of consecutive hard failures the
  breaker opens and further calls fail fast for a cool-off window. This is the
  guard against the multi-hour "retry storm" tail runs, where recursive batch
  splitting multiplied calls against an already-saturated API.
"""

from __future__ import annotations

import asyncio
import os
import random
import time
from typing import Dict, List, Optional, Tuple

from logger import get_logger

# Reuse the *cost* helpers and model registry from the sync layer so pricing and
# model-name resolution stay in exactly one place. (Only the calculate_cost
# helpers are imported — they exist on every branch — so this module never
# hard-depends on branch-specific symbols like a prices table.)
from .openai import calculate_cost as _openai_cost
from .claude import calculate_cost as _claude_cost
from .config import LLMProvider


# ---------------------------------------------------------------------------
# Circuit breaker (process-wide, best-effort)
# ---------------------------------------------------------------------------
class _CircuitBreaker:
    """
    Minimal consecutive-failure breaker.

    Trips open after ``fail_threshold`` consecutive failures and stays open for
    ``reset_after`` seconds, during which calls raise immediately instead of
    issuing a doomed network request. Any success closes it and resets the count.
    Deliberately simple and dependency-free.
    """

    def __init__(self, fail_threshold: int = 6, reset_after: float = 30.0):
        self.fail_threshold = fail_threshold
        self.reset_after = reset_after
        self._consecutive_failures = 0
        self._opened_at: Optional[float] = None

    def is_open(self) -> bool:
        if self._opened_at is None:
            return False
        # Cool-off elapsed → allow a trial call (half-open).
        if (time.monotonic() - self._opened_at) >= self.reset_after:
            self._opened_at = None
            self._consecutive_failures = 0
            return False
        return True

    def record_success(self) -> None:
        self._consecutive_failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= self.fail_threshold and self._opened_at is None:
            self._opened_at = time.monotonic()


# One breaker per process. The news fan-out shares it, so a genuine provider
# outage trips it once for everyone rather than each batch discovering it.
_breaker = _CircuitBreaker()


def reset_circuit_breaker() -> None:
    """Test/ops hook: force the breaker closed."""
    _breaker.record_success()


class CircuitOpenError(RuntimeError):
    """Raised when the breaker is open and a call is short-circuited."""


# ---------------------------------------------------------------------------
# Async clients (lazily constructed, cached per event loop is unnecessary — the
# SDK clients are cheap and safe to reuse across the process)
# ---------------------------------------------------------------------------
_async_anthropic = None
_async_openai = None


def _get_async_anthropic():
    global _async_anthropic
    if _async_anthropic is None:
        from anthropic import AsyncAnthropic
        _async_anthropic = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    return _async_anthropic


def _get_async_openai():
    global _async_openai
    if _async_openai is None:
        from openai import AsyncOpenAI
        _async_openai = AsyncOpenAI()
    return _async_openai


# Map the model *name* selected by init_llm() to the underlying provider + the
# concrete model id passed to the API. Mirrors LLMProvider.MODELS but for the
# async SDKs. Kept in sync via the shared registry check below.
_MODEL_TO_ANTHROPIC_ID = {
    "claude-sonnet-4-20250514": "claude-sonnet-4-20250514",
    "claude-sonnet-4-6": "claude-sonnet-4-6",
    "claude-haiku-4-5-20251001": "claude-haiku-4-5-20251001",
    "claude-3.5-sonnet": "claude-3-5-sonnet-20241022",
    "claude-3.5-haiku": "claude-3-5-haiku-20241022",
    "claude-3-opus": "claude-3-opus-20240229",
}
_OPENAI_MODELS = {"gpt-4o-mini", "gpt-5.4-mini", "gpt-5-mini"}


def _is_rate_limit_like(exc: Exception) -> bool:
    """True for errors that warrant a backoff-and-retry (rate/timeout/5xx)."""
    name = type(exc).__name__.lower()
    msg = str(exc).lower()
    if any(k in name for k in ("ratelimit", "timeout", "connection", "apistatus", "internalserver")):
        return True
    return any(
        k in msg
        for k in (
            "rate limit", "rate_limit", "ratelimit", "429", "500", "502", "503",
            "overloaded", "timeout", "temporarily unavailable", "connection",
        )
    )


async def _call_anthropic_async(
    model_id: str, messages: List[Dict], temperature: float
) -> Tuple[str, float]:
    system_message = None
    user_messages = []
    for message in messages:
        if message["role"] == "system":
            system_message = message["content"]
        elif message["role"] in ("user", "assistant"):
            user_messages.append({"role": message["role"], "content": message["content"]})

    kwargs = {
        "model": model_id,
        "messages": user_messages,
        "temperature": temperature,
        "max_tokens": 4096,
    }
    if system_message:
        kwargs["system"] = system_message

    client = _get_async_anthropic()
    response = await client.messages.create(**kwargs)
    cost = _claude_cost(response, model_id)
    return response.content[0].text, cost


async def _call_openai_async(
    model_id: str, messages: List[Dict], temperature: float
) -> Tuple[str, float]:
    client = _get_async_openai()
    response = await client.chat.completions.create(
        model=model_id, messages=messages, temperature=temperature
    )
    cost = _openai_cost(response, model_id)
    return response.choices[0].message.content, cost


# ---------------------------------------------------------------------------
# Tool-calling (native function calling) — used by the generalizable ReAct agent
# ---------------------------------------------------------------------------
class ToolCall:
    """One tool invocation requested by the model."""

    __slots__ = ("id", "name", "arguments")

    def __init__(self, id: str, name: str, arguments: dict):
        self.id = id
        self.name = name
        self.arguments = arguments or {}

    def __repr__(self):
        return f"ToolCall(name={self.name!r}, args={self.arguments!r})"


class LLMToolResponse:
    """
    Normalized response from a tool-calling turn, uniform across providers.

    * ``text``       — any assistant prose in the turn (may be empty when the
                       model only requested tools).
    * ``tool_calls`` — list[ToolCall] the model wants executed (empty → it's done).
    * ``cost``       — USD for the turn.
    * ``raw``        — the provider-native assistant message, so the caller can
                       append it verbatim to the running transcript (important for
                       Anthropic, whose tool_use/tool_result blocks must round-trip).
    """

    __slots__ = ("text", "tool_calls", "cost", "raw")

    def __init__(self, text, tool_calls, cost, raw):
        self.text = text or ""
        self.tool_calls = tool_calls or []
        self.cost = cost
        self.raw = raw

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0


async def _call_anthropic_tools(model_id, messages, tools, temperature, tool_choice=None):
    """
    One Anthropic tool-calling turn. `messages` is the running transcript in
    Anthropic shape (list of {role, content}); `tools` is a list of
    anthropic tool schemas (name/description/input_schema). Returns LLMToolResponse.
    """
    system_message = None
    conv = []
    for m in messages:
        if m["role"] == "system":
            system_message = m["content"]
        else:
            conv.append({"role": m["role"], "content": m["content"]})

    kwargs = {
        "model": model_id,
        "messages": conv,
        "temperature": temperature,
        "max_tokens": 4096,
    }
    if tools:  # omit an empty tools array — Anthropic rejects it
        kwargs["tools"] = tools
        if tool_choice:
            kwargs["tool_choice"] = tool_choice
    if system_message:
        kwargs["system"] = system_message

    client = _get_async_anthropic()
    resp = await client.messages.create(**kwargs)
    cost = _claude_cost(resp, model_id)

    text_parts, calls = [], []
    for block in resp.content:
        if block.type == "text":
            text_parts.append(block.text)
        elif block.type == "tool_use":
            calls.append(ToolCall(id=block.id, name=block.name, arguments=dict(block.input or {})))
    # The raw assistant message (list of content blocks) must be appended verbatim.
    raw_assistant = {"role": "assistant", "content": resp.content}
    return LLMToolResponse("\n".join(text_parts).strip(), calls, cost, raw_assistant)


async def _call_openai_tools(model_id, messages, tools, temperature, tool_choice=None):
    """One OpenAI tool-calling turn. `tools` is a list of openai function schemas."""
    import json as _json

    client = _get_async_openai()
    kwargs = {
        "model": model_id,
        "messages": messages,
        "temperature": temperature,
    }
    if tools:  # omit empty tools array
        kwargs["tools"] = tools
        if tool_choice:
            kwargs["tool_choice"] = tool_choice
    resp = await client.chat.completions.create(**kwargs)
    cost = _openai_cost(resp, model_id)

    msg = resp.choices[0].message
    calls = []
    for tc in (msg.tool_calls or []):
        try:
            args = _json.loads(tc.function.arguments or "{}")
        except Exception:
            args = {}
        calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))
    # Raw assistant message for transcript round-tripping.
    raw_assistant = {"role": "assistant", "content": msg.content or "", "tool_calls": msg.tool_calls}
    return LLMToolResponse(msg.content or "", calls, cost, raw_assistant)


class AsyncLLMProvider:
    """
    Async mirror of ``LLMProvider``. Resolves the currently-selected model name
    (from the global sync provider, so ``init_llm("...")`` governs both paths)
    to the right async SDK, with backoff + circuit breaker.
    """

    def __init__(self, model_name: str):
        self.model_name = model_name

    @property
    def is_openai(self) -> bool:
        return self.model_name in _OPENAI_MODELS

    def resolved_model_id(self) -> str:
        if self.is_openai:
            return self.model_name
        return _MODEL_TO_ANTHROPIC_ID.get(self.model_name, self.model_name)

    async def __call__(
        self, messages: List[Dict], temperature: float = 0.3, *, max_retries: int = 4
    ) -> Tuple[str, float]:
        logger = get_logger()

        if _breaker.is_open():
            # Fail fast — do not add load to a provider we already believe is down.
            raise CircuitOpenError(
                "LLM circuit breaker is open (too many consecutive failures); "
                "skipping call to avoid a retry storm."
            )

        last_error: Optional[Exception] = None
        for attempt in range(max_retries):
            try:
                if self.model_name in _OPENAI_MODELS:
                    text, cost = await _call_openai_async(self.model_name, messages, temperature)
                else:
                    model_id = _MODEL_TO_ANTHROPIC_ID.get(self.model_name, self.model_name)
                    text, cost = await _call_anthropic_async(model_id, messages, temperature)

                _breaker.record_success()
                if logger:
                    logger.llm_call(self.model_name, cost, 0)
                return text, cost

            except Exception as exc:  # noqa: BLE001 — we re-raise below
                last_error = exc
                retryable = _is_rate_limit_like(exc)
                if logger:
                    logger.error(
                        f"[async-llm] {type(exc).__name__} on attempt "
                        f"{attempt + 1}/{max_retries} (retryable={retryable}): {exc}"
                    )
                if not retryable or attempt == max_retries - 1:
                    # Only hard/terminal failures count toward the breaker.
                    _breaker.record_failure()
                    break
                # Exponential backoff with full jitter: 0.5, 1, 2, 4 … + [0, base).
                base = 0.5 * (2 ** attempt)
                await asyncio.sleep(base + random.uniform(0, base))

        raise Exception(
            f"Async LLM call failed after {max_retries} attempts. "
            f"Last error: {type(last_error).__name__}: {last_error}"
        )

    async def call_with_tools(
        self,
        messages: List[Dict],
        tools: List[Dict],
        temperature: float = 0.3,
        *,
        tool_choice=None,
        max_retries: int = 4,
    ) -> "LLMToolResponse":
        """
        One tool-calling turn (the primitive the ReAct loop drives).

        ``messages`` and ``tools`` must already be in the shape the selected
        provider expects (the caller builds them per provider — see the agent).
        Same backoff + circuit-breaker behaviour as ``__call__``.
        """
        logger = get_logger()
        if _breaker.is_open():
            raise CircuitOpenError(
                "LLM circuit breaker is open (too many consecutive failures)."
            )

        last_error: Optional[Exception] = None
        for attempt in range(max_retries):
            try:
                if self.is_openai:
                    resp = await _call_openai_tools(
                        self.model_name, messages, tools, temperature, tool_choice
                    )
                else:
                    resp = await _call_anthropic_tools(
                        self.resolved_model_id(), messages, tools, temperature, tool_choice
                    )
                _breaker.record_success()
                if logger:
                    logger.llm_call(self.model_name, resp.cost, 0)
                return resp
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                retryable = _is_rate_limit_like(exc)
                if logger:
                    logger.error(
                        f"[async-llm/tools] {type(exc).__name__} attempt "
                        f"{attempt + 1}/{max_retries} (retryable={retryable}): {exc}"
                    )
                if not retryable or attempt == max_retries - 1:
                    _breaker.record_failure()
                    break
                base = 0.5 * (2 ** attempt)
                await asyncio.sleep(base + random.uniform(0, base))

        raise Exception(
            f"Async tool call failed after {max_retries} attempts. "
            f"Last error: {type(last_error).__name__}: {last_error}"
        )


_global_async_provider: Optional[AsyncLLMProvider] = None
_global_async_model: Optional[str] = None


def get_async_llm() -> AsyncLLMProvider:
    """
    Return an async callable for the *currently selected* model.

    The model is whatever ``init_llm()`` set on the sync global provider, so a
    single ``init_llm("claude-...")`` at startup governs both the sync and async
    paths. Rebuilds if the selected model changed.
    """
    global _global_async_provider, _global_async_model
    # Resolve the active model name from the sync provider (source of truth).
    from .config import _global_provider  # local import to avoid cycle at import time

    model_name = _global_provider.current_model if _global_provider else "gpt-4o-mini"
    if _global_async_provider is None or _global_async_model != model_name:
        # Validate against the shared registry so we never silently diverge.
        if model_name not in LLMProvider.MODELS:
            raise ValueError(f"Async model '{model_name}' not in LLMProvider.MODELS")
        _global_async_provider = AsyncLLMProvider(model_name)
        _global_async_model = model_name
    return _global_async_provider
