"""LLM Provider Manager orchestrating OpenRouter primary and Groq fallback.

Enforces safe provider selection, circuit-breaker boundaries, draft preservation,
and zero key exposure.
"""
import logging
import time
from typing import Any, Dict, Optional

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
    LLMClientInterface,
    LLMRequest,
    LLMResponse,
)
from backend.app.llm.openrouter import OpenRouterClient

logger = logging.getLogger(__name__)


class LLMProviderManager:
    """Central orchestrator managing OpenRouter primary and optional Groq fallback."""

    def __init__(
        self,
        settings: Optional[LLMSettings] = None,
        openrouter_client: Optional[LLMClientInterface] = None,
        groq_client: Optional[LLMClientInterface] = None,
    ) -> None:
        self.settings = settings or LLMSettings()
        self.openrouter = openrouter_client or OpenRouterClient(self.settings)
        self.groq = groq_client or GroqClient(self.settings)

    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Executes completion via OpenRouter first, falling back to Groq if appropriate."""
        diagnostics: Dict[str, Any] = {}
        start_time = time.time()
        deadline = getattr(self.settings, "TOTAL_GENERATION_DEADLINE", 95.0)

        or_err: Optional[Exception] = None

        # 1. Attempt Primary Provider: OpenRouter
        if self.openrouter.is_configured:
            try:
                response = await self.openrouter.complete(request)
                return response
            except (AuthenticationError, InsufficientCreditsError, RateLimitError, ProviderUnavailableError, TimeoutError, ModelUnavailableError) as err:
                or_err = err
                diagnostics["openrouter_error"] = {
                    "type": err.__class__.__name__,
                    "message": err.message,
                    "status_code": err.status_code,
                }
                logger.warning(
                    "OpenRouter encountered %s (%s). Evaluating fallback options.",
                    err.__class__.__name__,
                    err.message,
                )

                if not self.groq.is_configured:
                    raise AllProvidersUnavailableError(
                        message=f"Primary provider (OpenRouter) failed: {err.message}",
                        preserved_draft=request.preserved_draft,
                        diagnostics=diagnostics,
                        category=err.__class__.__name__.replace("Error", "").upper(),
                    ) from err
            except UnsupportedFeatureError as ufe:
                # Malformed feature request (e.g. invalid response format) - do not blindly switch providers
                raise ufe
        else:
            diagnostics["openrouter_status"] = "Not configured"
            if not self.groq.is_configured:
                raise AllProvidersUnavailableError(
                    message="No LLM providers are configured. Set OPENROUTER_API_KEY_1 in .env.",
                    preserved_draft=request.preserved_draft,
                    diagnostics=diagnostics,
                    category="NO_PROVIDERS_CONFIGURED",
                )

        # 2. Attempt Optional Fallback Provider: Groq
        if self.groq.is_configured:
            elapsed = time.time() - start_time
            remaining = deadline - elapsed
            if remaining < 12.0:
                logger.warning("Remaining generation deadline (%.1fs) insufficient for Groq fallback.", remaining)
                raise AllProvidersUnavailableError(
                    message=f"Generation deadline ({deadline}s) reached before Groq fallback could complete. Draft preserved.",
                    preserved_draft=request.preserved_draft,
                    diagnostics=diagnostics,
                    category="TIMEOUT",
                )

            logger.info("Attempting fallback completion via Groq provider (%.1fs deadline remaining).", remaining)
            groq_request = request.model_copy(deep=True)
            groq_request.timeout = min(request.timeout or self.settings.LLM_REQUEST_TIMEOUT, remaining)
            # Default to Groq configured model if the requested model was OpenRouter-specific or absent
            target_groq_model = self.settings.GROQ_MODEL
            if not target_groq_model or target_groq_model.startswith("openai/"):
                target_groq_model = "llama-3.3-70b-versatile"

            if (
                not groq_request.model
                or any(prefix in groq_request.model for prefix in ("nvidia/", "google/", "liquid/", "cohere/", "openai/"))
            ):
                groq_request.model = target_groq_model

            try:
                response = await self.groq.complete(groq_request)
                response.metadata["fallback_from"] = "openrouter"
                return response
            except LLMError as groq_err:
                diagnostics["groq_error"] = {
                    "type": groq_err.__class__.__name__,
                    "message": groq_err.message,
                    "status_code": groq_err.status_code,
                }
                logger.error("Fallback provider Groq also failed: %s", groq_err.message)

                # Determine actionable category and next step
                category = "PROVIDER_UNAVAILABLE"
                suggestion = "Please retry shortly or verify provider settings."
                if isinstance(or_err, RateLimitError) or isinstance(groq_err, RateLimitError):
                    category = "RATE_LIMIT_EXCEEDED"
                    suggestion = "Provider rate limits reached. Please wait a moment and retry."
                elif isinstance(or_err, AuthenticationError) and isinstance(groq_err, AuthenticationError):
                    category = "AUTHENTICATION_FAILED"
                    suggestion = "Please verify your API keys in .env or Settings."
                elif isinstance(or_err, TimeoutError) or isinstance(groq_err, TimeoutError):
                    category = "TIMEOUT"
                    suggestion = "Network timeout occurred while reaching AI provider. Please retry."
                elif isinstance(or_err, ModelUnavailableError) or isinstance(groq_err, ModelUnavailableError):
                    category = "MODEL_UNAVAILABLE"
                    suggestion = "Configured models are temporarily unavailable. Please verify model settings."

                raise AllProvidersUnavailableError(
                    message=(
                        f"All LLM providers unavailable ({category}). OpenRouter and Groq both failed. "
                        f"{suggestion} Workflow draft has been preserved."
                    ),
                    preserved_draft=request.preserved_draft,
                    diagnostics=diagnostics,
                    category=category,
                ) from groq_err

        raise AllProvidersUnavailableError(
            message="All configured LLM providers are unavailable.",
            preserved_draft=request.preserved_draft,
            diagnostics=diagnostics,
            category="ALL_PROVIDERS_UNAVAILABLE",
        )

    async def get_health_status(self) -> Dict[str, Any]:
        """Returns safe health status of both providers without disclosing secrets."""
        return {
            "primary": await self.openrouter.get_health_status(),
            "fallback": await self.groq.get_health_status(),
        }
