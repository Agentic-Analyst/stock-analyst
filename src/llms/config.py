"""
LLM Provider - Unified LLM configuration and provider system.
"""

from typing import Callable, Tuple, List, Dict

# Import all available models
from .openai import gpt_4o_mini
from .claude import claude_3_5_sonnet, claude_3_5_haiku, claude_3_opus


class LLMProvider:
    """Unified LLM provider with simple model switching."""
    
    # Available models
    MODELS = {
        "gpt-4o-mini": gpt_4o_mini,
        "claude-3.5-sonnet": claude_3_5_sonnet,
        "claude-3.5-haiku": claude_3_5_haiku,
        "claude-3-opus": claude_3_opus,
    }
    
    def __init__(self, model_name: str = "gpt-4o-mini"):
        self.current_model = model_name
        self.current_llm = self.MODELS[model_name]
    
    def set_model(self, model_name: str):
        """Set the current model."""
        if model_name not in self.MODELS:
            raise ValueError(f"Model '{model_name}' not available")
        self.current_model = model_name
        self.current_llm = self.MODELS[model_name]
    
    def __call__(self, messages: List[Dict], temperature: float = 0.3) -> Tuple[str, float]:
        """Call the current LLM."""
        return self.current_llm(messages, temperature)
    
    @classmethod
    def list_models(cls) -> List[str]:
        """List all available models."""
        return list(cls.MODELS.keys())


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
