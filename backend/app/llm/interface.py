"""Provider-independent LLM contracts and abstract base class.

Decouples the Workflow Architect Orchestrator and other services from vendor-specific
APIs or SDK formats.
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field


class ChatMessage(BaseModel):
    """Normalized chat message structure."""
    model_config = ConfigDict(frozen=True)

    role: Literal["system", "user", "assistant"] = Field(
        ..., description="Message author role"
    )
    content: str = Field(..., min_length=1, description="Message text content")


class LLMRequest(BaseModel):
    """Normalized completion request."""
    model_config = ConfigDict(validate_assignment=True)

    messages: List[ChatMessage] = Field(
        ..., min_length=1, description="Sequential dialogue messages"
    )
    model: Optional[str] = Field(
        default=None, description="Optional override of default provider model"
    )
    temperature: float = Field(
        default=0.2, ge=0.0, le=2.0, description="Sampling temperature"
    )
    max_tokens: Optional[int] = Field(
        default=None, ge=1, description="Maximum completion tokens"
    )
    response_format: Optional[Dict[str, Any]] = Field(
        default=None, description="Structured output configuration (e.g. {'type': 'json_object'})"
    )
    timeout: Optional[float] = Field(
        default=None, ge=1.0, description="Per-request timeout override in seconds"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Arbitrary safe tracking metadata"
    )
    preserved_draft: Optional[Any] = Field(
        default=None, description="Optional active workflow draft to preserve on failure"
    )


class TokenUsage(BaseModel):
    """Normalized token accounting."""
    model_config = ConfigDict(frozen=True)

    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)


class LLMResponse(BaseModel):
    """Normalized completion response returned to calling application."""
    model_config = ConfigDict(frozen=True)

    content: str = Field(..., description="Generated text content")
    provider: str = Field(..., description="Provider name ('openrouter' or 'groq')")
    model: str = Field(..., description="Actual model ID that served the completion")
    usage: Optional[TokenUsage] = Field(default=None, description="Token consumption metrics")
    finish_reason: Optional[str] = Field(default=None, description="Reason model stopped generating")
    key_alias: Optional[str] = Field(
        default=None, description="Safe key identifier (e.g. 'OPENROUTER_KEY_1'), never raw secret"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Safe operational metrics (e.g. latency, retry count)"
    )


class LLMClientInterface(ABC):
    """Abstract interface implemented by all LLM provider adapters."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Normalized unique identifier of the provider."""
        pass

    @property
    @abstractmethod
    def is_configured(self) -> bool:
        """True if minimum credentials exist to attempt requests."""
        pass

    @abstractmethod
    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Execute chat completion with retry handling and normalized response."""
        pass

    @abstractmethod
    async def get_health_status(self) -> Dict[str, Any]:
        """Return safe operational status without exposing secret values."""
        pass
