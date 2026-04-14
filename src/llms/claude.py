from __future__ import annotations

import os
import time
from typing import Dict, List, Tuple

from anthropic import Anthropic
from anthropic import APIConnectionError, APITimeoutError, RateLimitError

from logger import get_logger


# Prices are stored per 1M tokens and converted to USD in `calculate_cost`.
# These values are used only for lightweight logging/cost estimation.
MODEL_PRICES_PER_MTOK = {
    "claude-sonnet-4-20250514": {"input": 3.0, "output": 15.0},
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0},
    "claude-haiku-4-5-20251001": {"input": 1.0, "output": 5.0},
    "claude-opus-4-20250514": {"input": 15.0, "output": 75.0},
    "claude-opus-4-6": {"input": 15.0, "output": 75.0},
    "claude-3-5-sonnet-20241022": {"input": 3.0, "output": 15.0},
    "claude-3-5-haiku-20241022": {"input": 0.8, "output": 4.0},
    "claude-3-opus-20240229": {"input": 15.0, "output": 75.0},
    "claude-3-sonnet-20240229": {"input": 3.0, "output": 15.0},
    "claude-3-haiku-20240307": {"input": 0.25, "output": 1.25},
}


def calculate_cost(response, model_name: str) -> float:
    """Calculate the cost of an Anthropic Claude API call."""
    usage = response.usage
    input_tokens = usage.input_tokens
    output_tokens = usage.output_tokens

    prices = MODEL_PRICES_PER_MTOK.get(model_name)
    if not prices:
        return 0.0

    return (
        input_tokens * prices["input"] / 1_000_000
        + output_tokens * prices["output"] / 1_000_000
    )


def _call_claude_model(
    *,
    model_name: str,
    display_name: str,
    messages: List[Dict],
    temperature: float = 0.3,
) -> Tuple[str, float]:
    """Call one Anthropic Claude model with retry logic and error handling."""
    max_retries = 3
    logger = get_logger()
    last_error = None

    for attempt in range(max_retries):
        try:
            client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

            system_message = None
            user_messages = []
            for message in messages:
                if message["role"] == "system":
                    system_message = message["content"]
                elif message["role"] in ["user", "assistant"]:
                    user_messages.append(
                        {
                            "role": message["role"],
                            "content": message["content"],
                        }
                    )

            kwargs = {
                "model": model_name,
                "messages": user_messages,
                "temperature": temperature,
                "max_tokens": 4096,
                "timeout": 60,
            }
            if system_message:
                kwargs["system"] = system_message

            response = client.messages.create(**kwargs)
            cost = calculate_cost(response, model_name)

            if logger:
                logger.info(f"LLM call succeeded (attempt {attempt + 1}/{max_retries})")
                logger.llm_call(
                    display_name,
                    cost,
                    response.usage.input_tokens + response.usage.output_tokens,
                )
            else:
                print(f"[llm] LLM call succeeded (attempt {attempt + 1}/{max_retries})")

            return response.content[0].text, cost

        except RateLimitError as exc:
            last_error = exc
            if logger:
                logger.error(
                    f"Rate limit exceeded (attempt {attempt + 1}/{max_retries}): {exc}"
                )
            else:
                print(f"[llm] Rate limit exceeded (attempt {attempt + 1}/{max_retries}): {exc}")

        except (APITimeoutError, APIConnectionError) as exc:
            last_error = exc
            if logger:
                logger.error(
                    f"Connection/timeout error (attempt {attempt + 1}/{max_retries}): {exc}"
                )
            else:
                print(
                    f"[llm] Connection/timeout error (attempt {attempt + 1}/{max_retries}): {exc}"
                )

        except Exception as exc:
            last_error = exc
            error_type = type(exc).__name__
            if logger:
                logger.error(
                    f"Unexpected error (attempt {attempt + 1}/{max_retries}): {error_type}: {exc}"
                )
            else:
                print(
                    f"[llm] Unexpected error (attempt {attempt + 1}/{max_retries}): "
                    f"{error_type}: {exc}"
                )

        if attempt < max_retries - 1:
            if logger:
                logger.info("Retrying in 1 seconds...")
            else:
                print("[llm] Retrying in 1 seconds...")
            time.sleep(1)
        else:
            error_msg = (
                f"Claude API call failed after {max_retries} attempts. "
                f"Last error: {type(last_error).__name__}: {last_error}"
            )
            if logger:
                logger.error(f"All {max_retries} attempts failed")
                logger.error(error_msg)
            else:
                print(f"[llm] All {max_retries} attempts failed")
            raise Exception(error_msg)


def claude_sonnet_4(messages: List[Dict], temperature: float = 0.3) -> Tuple[str, float]:
    return _call_claude_model(
        model_name="claude-sonnet-4-20250514",
        display_name="claude-sonnet-4",
        messages=messages,
        temperature=temperature,
    )


def claude_sonnet_4_6(messages: List[Dict], temperature: float = 0.3) -> Tuple[str, float]:
    return _call_claude_model(
        model_name="claude-sonnet-4-6",
        display_name="claude-sonnet-4-6",
        messages=messages,
        temperature=temperature,
    )


def claude_haiku_4_5(messages: List[Dict], temperature: float = 0.3) -> Tuple[str, float]:
    return _call_claude_model(
        model_name="claude-haiku-4-5-20251001",
        display_name="claude-haiku-4-5",
        messages=messages,
        temperature=temperature,
    )


def claude_3_5_sonnet(messages: List[Dict], temperature: float = 0.3) -> Tuple[str, float]:
    return _call_claude_model(
        model_name="claude-3-5-sonnet-20241022",
        display_name="claude-3-5-sonnet",
        messages=messages,
        temperature=temperature,
    )


def claude_3_5_haiku(messages: List[Dict], temperature: float = 0.3) -> Tuple[str, float]:
    return _call_claude_model(
        model_name="claude-3-5-haiku-20241022",
        display_name="claude-3-5-haiku",
        messages=messages,
        temperature=temperature,
    )


def claude_3_opus(messages: List[Dict], temperature: float = 0.3) -> Tuple[str, float]:
    return _call_claude_model(
        model_name="claude-3-opus-20240229",
        display_name="claude-3-opus",
        messages=messages,
        temperature=temperature,
    )
