"""
LLM Provider - Unified LLM configuration and provider system.
"""

import os
from typing import Callable, Tuple, List, Dict

# Import all available models
from .openai import gpt_4o_mini
from .claude import claude_3_5_sonnet, claude_3_5_haiku, claude_3_opus


class LLMProvider:
    """Unified LLM provider with simple model switching."""
    
    # Available models and their required API keys
    MODELS = {
        "gpt-4o-mini": {"function": gpt_4o_mini, "api_key": "OPENAI_API_KEY"},
        "claude-3.5-sonnet": {"function": claude_3_5_sonnet, "api_key": "ANTHROPIC_API_KEY"},
        "claude-3.5-haiku": {"function": claude_3_5_haiku, "api_key": "ANTHROPIC_API_KEY"},
        "claude-3-opus": {"function": claude_3_opus, "api_key": "ANTHROPIC_API_KEY"},
    }
    
    def __init__(self, model_name: str = "gpt-4o-mini"):
        if model_name not in self.MODELS:
            raise ValueError(f"Model '{model_name}' not available. Available: {list(self.MODELS.keys())}")
        
        # Verify API key is available
        required_key = self.MODELS[model_name]["api_key"]
        if not os.getenv(required_key):
            raise ValueError(f"API key '{required_key}' not found in environment variables")
        
        self.current_model = model_name
        self.current_llm = self.MODELS[model_name]["function"]
    
    def set_model(self, model_name: str):
        """Set the current model with API key verification."""
        if model_name not in self.MODELS:
            raise ValueError(f"Model '{model_name}' not available")
        
        # Verify API key is available
        required_key = self.MODELS[model_name]["api_key"]
        if not os.getenv(required_key):
            raise ValueError(f"API key '{required_key}' not found in environment variables")
        
        self.current_model = model_name
        self.current_llm = self.MODELS[model_name]["function"]
    
    def __call__(self, messages: List[Dict], temperature: float = 0.3) -> Tuple[str, float]:
        """Call the current LLM."""
        return self.current_llm(messages, temperature)
    
    @classmethod
    def list_models(cls) -> List[str]:
        """List all available models."""
        return list(cls.MODELS.keys())
    
    @classmethod
    def list_available_models(cls) -> List[str]:
        """List models that have API keys available."""
        available = []
        for model_name, config in cls.MODELS.items():
            if os.getenv(config["api_key"]):
                available.append(model_name)
        return available


# Global provider instance
_global_provider = None

def init_llm(model_name: str = "gpt-4o-mini") -> LLMProvider:
    """Initialize the global LLM provider."""
    global _global_provider
    _global_provider = LLMProvider(model_name)
    return _global_provider

def get_llm() -> Callable:
    """Get the current LLM function."""
    if _global_provider is None:
        init_llm()
    return _global_provider

def list_models() -> List[str]:
    """List available models."""
    return LLMProvider.list_models()

def list_available_models() -> List[str]:
    """List models with API keys available."""
    return LLMProvider.list_available_models()
