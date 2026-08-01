from openai import OpenAI
from openai import RateLimitError, APITimeoutError, APIConnectionError
import time
import os
from typing import Tuple, List, Dict
from logger import get_logger


def calculate_cost(response, model_name):
    """Calculate the cost of an OpenAI API call."""
    usage = response.usage
    prompt_tokens = usage.prompt_tokens
    completion_tokens = usage.completion_tokens

    # Prices per 1K tokens.
    prices = {
        "gpt-4o-mini": {"prompt": 0.000150, "completion": 0.000600},
        "gpt-4o": {"prompt": 0.005, "completion": 0.015},
        "gpt-4": {"prompt": 0.03, "completion": 0.06},
        "gpt-3.5-turbo": {"prompt": 0.0005, "completion": 0.0015},
        # gpt-5.4-mini (approx; used for lightweight cost logging only).
        "gpt-5.4-mini": {"prompt": 0.00025, "completion": 0.00200},
        "gpt-5-mini": {"prompt": 0.00025, "completion": 0.00200},
    }

    if model_name not in prices:
        return 0

    cost = (
        prompt_tokens * prices[model_name]["prompt"] / 1000
        + completion_tokens * prices[model_name]["completion"] / 1000
    )
    return cost


def _call_openai_model(model_name: str, messages: List[Dict], temperature: float = 0.3) -> Tuple[str, float]:
    """Call an OpenAI chat model with retry logic. Backs the per-model wrappers."""
    max_retries = 3
    logger = get_logger()
    last_error = None

    for attempt in range(max_retries):
        try:
            client = OpenAI()

            response = client.chat.completions.create(
                model=model_name,
                messages=messages,
                temperature=temperature,
                timeout=60
            )

            # Calculate cost
            cost = calculate_cost(response, model_name)
            if logger:
                logger.info(f"LLM call succeeded (attempt {attempt + 1}/{max_retries})")
                logger.llm_call(model_name, cost, response.usage.total_tokens)
            else:
                print(f"[llm] LLM call succeeded (attempt {attempt + 1}/{max_retries})")

            return response.choices[0].message.content, cost
            
        except RateLimitError as e:
            last_error = e
            if logger:
                logger.error(f"Rate limit exceeded (attempt {attempt + 1}/{max_retries}): {e}")
            else:
                print(f"[llm] Rate limit exceeded (attempt {attempt + 1}/{max_retries}): {e}")
            
        except (APITimeoutError, APIConnectionError) as e:
            last_error = e
            if logger:
                logger.error(f"Connection/timeout error (attempt {attempt + 1}/{max_retries}): {e}")
            else:
                print(f"[llm] Connection/timeout error (attempt {attempt + 1}/{max_retries}): {e}")
            
        except Exception as e:
            last_error = e
            error_type = type(e).__name__
            if logger:
                logger.error(f"Unexpected error (attempt {attempt + 1}/{max_retries}): {error_type}: {e}")
            else:
                print(f"[llm] Unexpected error (attempt {attempt + 1}/{max_retries}): {error_type}: {e}")

        if attempt < max_retries - 1:
            if logger:
                logger.info(f"Retrying in 1 seconds...")
            else:
                print(f"[llm] Retrying in 1 seconds...")
            time.sleep(1)
        else:
            error_msg = f"OpenAI API call failed after {max_retries} attempts. Last error: {type(last_error).__name__}: {last_error}"
            if logger:
                logger.error(f"All {max_retries} attempts failed")
                logger.error(error_msg)
            else:
                print(f"[llm] All {max_retries} attempts failed")
            raise Exception(error_msg)


def gpt_4o_mini(messages: List[Dict], temperature: float = 0.3) -> Tuple[str, float]:
    """Call OpenAI GPT-4o-mini. Returns (text, cost)."""
    return _call_openai_model("gpt-4o-mini", messages, temperature)


def gpt_5_4_mini(messages: List[Dict], temperature: float = 0.3) -> Tuple[str, float]:
    """Call OpenAI gpt-5.4-mini. Returns (text, cost)."""
    return _call_openai_model("gpt-5.4-mini", messages, temperature)

