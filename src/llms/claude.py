from anthropic import Anthropic
from anthropic import RateLimitError, APITimeoutError, APIConnectionError
import time
import os
from typing import Tuple, List, Dict
from logger import get_logger


def calculate_cost(response, model_name):
    """Calculate the cost of an Anthropic Claude API call."""
    usage = response.usage
    input_tokens = usage.input_tokens
    output_tokens = usage.output_tokens

    # Updated prices as of September 2025 (per 1K tokens)
    prices = {
        "claude-3-5-sonnet-20241022": {"input": 0.003, "output": 0.015},
        "claude-3-5-haiku-20241022": {"input": 0.001, "output": 0.005},
        "claude-3-opus-20240229": {"input": 0.015, "output": 0.075},
        "claude-3-sonnet-20240229": {"input": 0.003, "output": 0.015},
        "claude-3-haiku-20240307": {"input": 0.00025, "output": 0.00125},
    }

    if model_name not in prices:
        return 0

    cost = (
        input_tokens * prices[model_name]["input"] / 1000
        + output_tokens * prices[model_name]["output"] / 1000
    )
    return cost


def claude_3_5_sonnet(messages: List[Dict], temperature: float = 0.3) -> Tuple[str, float]:
    """
    Call Anthropic Claude-3.5-Sonnet with retry logic and error handling.
    
    Args:
        messages: List of message dictionaries with 'role' and 'content'
        temperature: Sampling temperature (0.0 to 1.0)
        
    Returns:
        Tuple of (Generated text response, Cost in USD)
        
    Raises:
        Exception: If all retry attempts fail
    """
    # Check API key first
    if not os.getenv('ANTHROPIC_API_KEY'):
        raise Exception("ANTHROPIC_API_KEY environment variable is not set")
    
    max_retries = 3
    logger = get_logger()
    last_error = None
    
    for attempt in range(max_retries):
        try:
            client = Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))
            
            # Convert OpenAI format messages to Claude format
            system_message = None
            user_messages = []
            
            for msg in messages:
                if msg['role'] == 'system':
                    system_message = msg['content']
                elif msg['role'] in ['user', 'assistant']:
                    user_messages.append({
                        'role': msg['role'],
                        'content': msg['content']
                    })
            
            # Create the API call
            kwargs = {
                "model": "claude-3-5-sonnet-20241022",
                "messages": user_messages,
                "temperature": temperature,
                "timeout": 60
            }
            
            if system_message:
                kwargs["system"] = system_message
            
            response = client.messages.create(**kwargs)
            
            # Calculate cost
            cost = calculate_cost(response, "claude-3-5-sonnet-20241022")
            if logger:
                logger.info(f"LLM call succeeded (attempt {attempt + 1}/{max_retries})")
                logger.llm_call("claude-3-5-sonnet", cost, response.usage.input_tokens + response.usage.output_tokens)
            else:
                print(f"[llm] LLM call succeeded (attempt {attempt + 1}/{max_retries})")

            return response.content[0].text, cost
            
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
            error_msg = f"Claude API call failed after {max_retries} attempts. Last error: {type(last_error).__name__}: {last_error}"
            if logger:
                logger.error(f"All {max_retries} attempts failed")
                logger.error(error_msg)
            else:
                print(f"[llm] All {max_retries} attempts failed")
            raise Exception(error_msg)


def claude_3_5_haiku(messages: List[Dict], temperature: float = 0.3) -> Tuple[str, float]:
    """
    Call Anthropic Claude-3.5-Haiku with retry logic and error handling.
    
    Args:
        messages: List of message dictionaries with 'role' and 'content'
        temperature: Sampling temperature (0.0 to 1.0)
        
    Returns:
        Tuple of (Generated text response, Cost in USD)
        
    Raises:
        Exception: If all retry attempts fail
    """
    # Check API key first
    if not os.getenv('ANTHROPIC_API_KEY'):
        raise Exception("ANTHROPIC_API_KEY environment variable is not set")
    
    max_retries = 3
    logger = get_logger()
    last_error = None
    
    for attempt in range(max_retries):
        try:
            client = Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))
            
            # Convert OpenAI format messages to Claude format
            system_message = None
            user_messages = []
            
            for msg in messages:
                if msg['role'] == 'system':
                    system_message = msg['content']
                elif msg['role'] in ['user', 'assistant']:
                    user_messages.append({
                        'role': msg['role'],
                        'content': msg['content']
                    })
            
            # Create the API call
            kwargs = {
                "model": "claude-3-5-haiku-20241022",
                "messages": user_messages,
                "temperature": temperature,
                "timeout": 60
            }
            
            if system_message:
                kwargs["system"] = system_message
            
            response = client.messages.create(**kwargs)
            
            # Calculate cost
            cost = calculate_cost(response, "claude-3-5-haiku-20241022")
            if logger:
                logger.info(f"LLM call succeeded (attempt {attempt + 1}/{max_retries})")
                logger.llm_call("claude-3-5-haiku", cost, response.usage.input_tokens + response.usage.output_tokens)
            else:
                print(f"[llm] LLM call succeeded (attempt {attempt + 1}/{max_retries})")

            return response.content[0].text, cost
            
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
                logger.error(f"Unexpected error (attempt {attempt + 1}/{max_retries}): {e}")
            else:
                print(f"[llm] Unexpected error (attempt {attempt + 1}/{max_retries}): {e}")

        if attempt < max_retries - 1:
            if logger:
                logger.info(f"Retrying in 1 seconds...")
            else:
                print(f"[llm] Retrying in 1 seconds...")
            time.sleep(1)
        else:
            error_msg = f"Claude API call failed after {max_retries} attempts. Last error: {type(last_error).__name__}: {last_error}"
            if logger:
                logger.error(f"All {max_retries} attempts failed")
                logger.error(error_msg)
            else:
                print(f"[llm] All {max_retries} attempts failed")
            raise Exception(error_msg)


def claude_3_opus(messages: List[Dict], temperature: float = 0.3) -> Tuple[str, float]:
    """
    Call Anthropic Claude-3-Opus with retry logic and error handling.
    
    Args:
        messages: List of message dictionaries with 'role' and 'content'
        temperature: Sampling temperature (0.0 to 1.0)
        
    Returns:
        Tuple of (Generated text response, Cost in USD)
        
    Raises:
        Exception: If all retry attempts fail
    """
    # Check API key first
    if not os.getenv('ANTHROPIC_API_KEY'):
        raise Exception("ANTHROPIC_API_KEY environment variable is not set")
    
    max_retries = 3
    logger = get_logger()
    last_error = None
    
    for attempt in range(max_retries):
        try:
            client = Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))
            
            # Convert OpenAI format messages to Claude format
            system_message = None
            user_messages = []
            
            for msg in messages:
                if msg['role'] == 'system':
                    system_message = msg['content']
                elif msg['role'] in ['user', 'assistant']:
                    user_messages.append({
                        'role': msg['role'],
                        'content': msg['content']
                    })
            
            # Create the API call
            kwargs = {
                "model": "claude-3-opus-20240229",
                "messages": user_messages,
                "temperature": temperature,
                "timeout": 60
            }
            
            if system_message:
                kwargs["system"] = system_message
            
            response = client.messages.create(**kwargs)
            
            # Calculate cost
            cost = calculate_cost(response, "claude-3-opus-20240229")
            if logger:
                logger.info(f"LLM call succeeded (attempt {attempt + 1}/{max_retries})")
                logger.llm_call("claude-3-opus", cost, response.usage.input_tokens + response.usage.output_tokens)
            else:
                print(f"[llm] LLM call succeeded (attempt {attempt + 1}/{max_retries})")

            return response.content[0].text, cost
            
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
                logger.error(f"Unexpected error (attempt {attempt + 1}/{max_retries}): {e}")
            else:
                print(f"[llm] Unexpected error (attempt {attempt + 1}/{max_retries}): {e}")

        if attempt < max_retries - 1:
            if logger:
                logger.info(f"Retrying in 1 seconds...")
            else:
                print(f"[llm] Retrying in 1 seconds...")
            time.sleep(1)
        else:
            error_msg = f"Claude API call failed after {max_retries} attempts. Last error: {type(last_error).__name__}: {last_error}"
            if logger:
                logger.error(f"All {max_retries} attempts failed")
                logger.error(error_msg)
            else:
                print(f"[llm] All {max_retries} attempts failed")
            raise Exception(error_msg)

