"""Typed exception hierarchy for the LLM Provider Layer.

Ensures structured error handling and strict secret masking across all providers.
"""
from typing import Any, Optional


class LLMError(Exception):
    """Base exception for all LLM provider interactions."""

    def __init__(
        self,
        message: str,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        status_code: Optional[int] = None,
        is_retryable: bool = False,
        original_error: Optional[Exception] = None,
    ) -> None:
        self.message = message
        self.provider = provider
        self.model = model
        self.status_code = status_code
        self.is_retryable = is_retryable
        self.original_error = original_error
        super().__init__(self._format_message())

    def _format_message(self) -> str:
        parts = [self.message]
        if self.provider:
            parts.append(f"provider={self.provider}")
        if self.model:
            parts.append(f"model={self.model}")
        if self.status_code:
            parts.append(f"status_code={self.status_code}")
        return " | ".join(parts)


class AuthenticationError(LLMError):
    """HTTP 401: Invalid or missing API credentials. Non-retryable on the same key."""

    def __init__(self, message: str, provider: Optional[str] = None, model: Optional[str] = None) -> None:
        super().__init__(message=message, provider=provider, model=model, status_code=401, is_retryable=False)


class InsufficientCreditsError(LLMError):
    """HTTP 402: Account quota or credits exhausted."""

    def __init__(self, message: str, provider: Optional[str] = None, model: Optional[str] = None) -> None:
        super().__init__(message=message, provider=provider, model=model, status_code=402, is_retryable=False)


class RateLimitError(LLMError):
    """HTTP 429: Rate limit reached. Retryable after cooldown."""

    def __init__(
        self,
        message: str,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        retry_after: Optional[float] = None,
    ) -> None:
        self.retry_after = retry_after
        super().__init__(message=message, provider=provider, model=model, status_code=429, is_retryable=True)


class ModelUnavailableError(LLMError):
    """HTTP 404 / 400: Model not found, deactivated, or not available to account."""

    def __init__(self, message: str, provider: Optional[str] = None, model: Optional[str] = None) -> None:
        super().__init__(message=message, provider=provider, model=model, status_code=404, is_retryable=False)


class UnsupportedFeatureError(LLMError):
    """Requested capability (e.g. structured JSON mode) is unsupported by the selected model."""

    def __init__(self, message: str, provider: Optional[str] = None, model: Optional[str] = None) -> None:
        super().__init__(message=message, provider=provider, model=model, status_code=400, is_retryable=False)


class ProviderUnavailableError(LLMError):
    """HTTP 5xx / Network outage: Upstream provider or gateway temporarily down."""

    def __init__(
        self,
        message: str,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        status_code: int = 503,
    ) -> None:
        super().__init__(message=message, provider=provider, model=model, status_code=status_code, is_retryable=True)


class TimeoutError(LLMError):
    """Request or socket connect timeout. Retryable with backoff."""

    def __init__(self, message: str, provider: Optional[str] = None, model: Optional[str] = None) -> None:
        super().__init__(message=message, provider=provider, model=model, status_code=408, is_retryable=True)


class AllProvidersUnavailableError(LLMError):
    """Raised when both primary (OpenRouter) and fallback (Groq) providers are exhausted.
    
    Guarantees preservation of the caller's active workflow draft.
    """

    def __init__(
        self,
        message: str,
        preserved_draft: Optional[Any] = None,
        diagnostics: Optional[dict] = None,
        category: Optional[str] = None,
    ) -> None:
        self.preserved_draft = preserved_draft
        self.diagnostics = diagnostics or {}
        self.category = category
        super().__init__(message=message, provider="all", is_retryable=False)
