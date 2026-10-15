"""LLM Provider Layer package.

Provides a unified interface, OpenRouter primary provider (4-key pool),
and optional Groq fallback provider.
"""
from backend.app.llm.config import LLMSettings
from backend.app.llm.exceptions import (
    AllProvidersUnavailableError,
    AuthenticationError,
    InsufficientCreditsError,
    LLMError,
    ModelUnavailableError,
    ProviderUnavailableError,
    RateLimitError,
    TimeoutError,
    UnsupportedFeatureError,
)
from backend.app.llm.groq import GroqClient
from backend.app.llm.interface import (
    ChatMessage,
    LLMClientInterface,
    LLMRequest,
    LLMResponse,
    TokenUsage,
)
from backend.app.llm.manager import LLMProviderManager
from backend.app.llm.openrouter import OpenRouterClient

__all__ = [
    "AllProvidersUnavailableError",
    "AuthenticationError",
    "ChatMessage",
    "GroqClient",
    "InsufficientCreditsError",
    "LLMClientInterface",
    "LLMError",
    "LLMProviderManager",
    "LLMRequest",
    "LLMResponse",
    "LLMSettings",
    "ModelUnavailableError",
    "OpenRouterClient",
    "ProviderUnavailableError",
    "RateLimitError",
    "TimeoutError",
    "TokenUsage",
    "UnsupportedFeatureError",
]
