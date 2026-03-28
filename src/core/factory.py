# src/llm/factory.py
from typing import Dict, Any, Type
from src.core.llm_client import LLM_Client, OpenRouterClient 
# from .clients import OllamaClient, GeminiClient, etc.

PROVIDER_MAP: Dict[str, Type[LLM_Client]] = {
    "openrouter.ai": OpenRouterClient,
    # "ollama": OllamaClient,        # If you create this
    # "gemini": GeminiClient,        # If you create this
}

def create_llm_client(agent_name: str, provider: str, **config_kwargs) -> LLM_Client:
    """
    Factory: Returns the correct LLM client subclass based on provider.
    
    Args:
        agent_name: Name for logging/trajectories
        provider: Provider string from YAML, e.g. "openrouter.ai"
        **config_kwargs: model, temperature, api_key, etc. from YAML
    """
    client_cls = PROVIDER_MAP.get(provider.lower())
    if not client_cls:
        available = ", ".join(PROVIDER_MAP.keys())
        raise ValueError(
            f"Unknown provider '{provider}'. Available: {available}"
        )
    
    # Filter out None values to avoid overriding defaults
    clean_kwargs = {k: v for k, v in config_kwargs.items() if v is not None}
    
    # Instantiate with agent name + config
    return client_cls(agent=agent_name, provider=provider, **clean_kwargs)