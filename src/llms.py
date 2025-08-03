from openai import OpenAI
import time
import os
from typing import Tuple, List, Dict


def calculate_cost(response, model_name):
    """Calculate the cost of an OpenAI API call."""
    usage = response.usage
    prompt_tokens = usage.prompt_tokens
    completion_tokens = usage.completion_tokens

    # Updated prices as of January 2025 (per 1K tokens)
    prices = {
        "gpt-4o-mini": {"prompt": 0.000150, "completion": 0.000600},
        "gpt-4o": {"prompt": 0.005, "completion": 0.015},
        "gpt-4": {"prompt": 0.03, "completion": 0.06},
        "gpt-3.5-turbo": {"prompt": 0.0005, "completion": 0.0015},
    }

    if model_name not in prices:
        return 0

    cost = (
        prompt_tokens * prices[model_name]["prompt"] / 1000
        + completion_tokens * prices[model_name]["completion"] / 1000
    )
    return cost


def gpt_4o_mini(messages: List[Dict], max_tokens: int = 1500, temperature: float = 0.3) -> Tuple[str, float]:
    """
    Call OpenAI GPT-4o-mini with retry logic and error handling.
    
    Args:
        messages: List of message dictionaries with 'role' and 'content'
        max_tokens: Maximum tokens in response
        temperature: Sampling temperature (0.0 to 1.0)
        
    Returns:
        Tuple of (Generated text response, Cost in USD)
        
    Raises:
        Exception: If all retry attempts fail
    """
    max_retries = 3
    
    for attempt in range(max_retries):
        try:
            client = OpenAI()
            
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=30
            )
            
            # Calculate cost
            cost = calculate_cost(response, "gpt-4o-mini")
            
            # print(f"[info] LLM call succeeded (attempt {attempt + 1}/{max_retries}):\n {response.choices[0].message.content}")
            return response.choices[0].message.content, cost
            
        except Exception as e:
            wait_time = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
            # Use logger if available, otherwise print
            try:
                from logger import get_logger
                logger = get_logger()
                if logger:
                    logger.error(f"LLM call failed (attempt {attempt + 1}/{max_retries}): {e}")
                    if attempt < max_retries - 1:
                        logger.info(f"Retrying in {wait_time} seconds...")
                    else:
                        logger.error(f"All {max_retries} attempts failed")
                else:
                    raise ImportError("No logger available")
            except ImportError:
                print(f"[error] LLM call failed (attempt {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    print(f"[info] Retrying in {wait_time} seconds...")
                else:
                    print(f"[error] All {max_retries} attempts failed")
            
            if attempt < max_retries - 1:
                time.sleep(wait_time)
            else:
                raise Exception(f"Connection error")


def test_connection() -> bool:
    """Quick test to verify OpenAI connection works."""
    try:
        test_messages = [{"role": "user", "content": "Hello"}]
        response, cost = gpt_4o_mini(test_messages)
        
        # Use logger if available, otherwise print
        try:
            from logger import get_logger
            logger = get_logger()
            if logger:
                logger.info(f"Connection test passed! Cost: ${cost:.6f}")
            else:
                raise ImportError("No logger available")
        except ImportError:
            print(f"[llm] Connection test passed! Cost: ${cost:.6f}")
        
        return True
    except Exception as e:
        # Use logger if available, otherwise print
        try:
            from logger import get_logger
            logger = get_logger()
            if logger:
                logger.error(f"Connection test failed: {e}")
            else:
                raise ImportError("No logger available")
        except ImportError:
            print(f"[llm] Connection test failed: {e}")
        
        return False


if __name__ == "__main__":
    print("Testing OpenAI connection...")
    if test_connection():
        print("✅ Ready to use!")
    else:
        print("❌ Connection issues detected")

