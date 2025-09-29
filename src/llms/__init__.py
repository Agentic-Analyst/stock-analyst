"""
LLMs package - Multi-provider LLM integration for stock analysis.

This package provides unified interfaces for different LLM providers:
- OpenAI (GPT-4o, GPT-4o-mini, GPT-4, GPT-3.5-turbo)
- Anthropic Claude (Claude-3.5-Sonnet, Claude-3.5-Haiku, Claude-3-Opus)

All functions follow the same interface:
- Input: List of messages, temperature
- Output: Tuple of (response_text, cost_in_usd)
- Error handling: Retry logic with exponential backoff
- Logging: Integrated with the stock analyst logger

Usage:
    # Direct model usage
    from llms import gpt_4o_mini, claude_3_5_sonnet
    
    # Configurable usage
    from llms import get_llm, set_default_llm
    set_default_llm("claude-3.5-sonnet")
    llm = get_llm()  # Returns claude_3_5_sonnet
"""

# OpenAI models
from .openai import gpt_4o_mini, calculate_cost as calculate_openai_cost

# Anthropic Claude models  
from .claude import (
    claude_3_5_sonnet,
    claude_3_5_haiku, 
    claude_3_opus,
    calculate_cost as calculate_claude_cost
)

# Configuration and utilities
from .config import (
    init_llm,
    get_llm,
    list_models
)

# Default model aliases for easy switching
default_model = gpt_4o_mini  # Fast and cost-effective default
premium_model = claude_3_5_sonnet  # High-quality for complex tasks
budget_model = claude_3_5_haiku  # Fastest and cheapest
flagship_model = claude_3_opus  # Most capable for complex reasoning

__all__ = [
    # OpenAI
    'gpt_4o_mini',
    'calculate_openai_cost',
    
    # Claude
    'claude_3_5_sonnet',
    'claude_3_5_haiku', 
    'claude_3_opus',
    'calculate_claude_cost',
    
    # Configuration
    'init_llm',
    'get_llm',
    'list_models',
]