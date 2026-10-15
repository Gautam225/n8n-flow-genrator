"""Groq Optional Fallback LLM Provider Client.

Implements chat completion calls to https://api.groq.com/openai/v1/chat/completions.
Groq is strictly optional: if GROQ_API_KEY is unset, the client safely reports
unconfigured status without crashing the application.
"""
import asyncio
import logging
import random
import time
from typing import Any, Dict, Optional
import httpx

from backend.app.llm.config import LLMSettings
from backend.app.llm.exceptions import (
    AuthenticationError,
    InsufficientCreditsError,
    ModelUnavailableError,
    ProviderUnavailableError,
    RateLimitError,
    TimeoutError,
    UnsupportedFeatureError,
)
from backend.app.llm.interface import (
    LLMClientInterface,
    LLMRequest,
    LLMResponse,
    TokenUsage,
)

logger = logging.getLogger(__name__)


class GroqClient(LLMClientInterface):
    """Groq API client implementing normalized LLMClientInterface."""

    ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"

    def __init__(
        self,
        settings: Optional[LLMSettings] = None,
        http_client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self.settings = settings or LLMSettings()
        self._http_client = http_client
        self._cooldown_until: float = 0.0
        self._consecutive_failures: int = 0
        self._status: str = "HEALTHY"

    @property
    def provider_name(self) -> str:
        return "groq"

    @property
    def is_configured(self) -> bool:
        return bool(self.settings.GROQ_API_KEY and self.settings.GROQ_API_KEY.strip())

    def is_available(self) -> bool:
        if not self.is_configured:
            return False
        if self._status == "DISABLED":
            return False
        if time.time() < self._cooldown_until:
            return False
        return True

    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Executes a chat completion via Groq across configured and fallback models."""
        if not self.is_configured:
            raise AuthenticationError(
                message="Groq provider is not configured. Set GROQ_API_KEY in .env.",
                provider=self.provider_name,
            )

        if not self.is_available():
            remaining = max(0.0, self._cooldown_until - time.time())
            raise RateLimitError(
                message=f"Groq provider is currently cooling down. Available in {remaining:.1f}s.",
                provider=self.provider_name,
                retry_after=remaining,
            )

        # Build model cascade: requested or configured primary model, then fallbacks
        models_to_try = []
        primary_model = request.model or self.settings.GROQ_MODEL
        models_to_try.append(primary_model)
        for fb in getattr(self.settings, "GROQ_FALLBACK_MODELS", []):
            if fb not in models_to_try:
                models_to_try.append(fb)

        last_error: Optional[Exception] = None
        start_time = time.time()
        deadline = getattr(self.settings, "TOTAL_GENERATION_DEADLINE", 95.0)

        for model in models_to_try:
            elapsed = time.time() - start_time
            remaining = deadline - elapsed
            if remaining < 10.0:
                logger.warning(
                    "Overall generation deadline approaching (%.1fs elapsed of %.1fs). Halting Groq model cascade.",
                    elapsed,
                    deadline,
                )
                raise TimeoutError(
                    message=f"Overall generation deadline ({deadline}s) reached while synthesizing workflow.",
                    provider=self.provider_name,
                    model=model,
                )

            try:
                return await self._complete_with_model(request, model, remaining_deadline=remaining)
            except (ModelUnavailableError, UnsupportedFeatureError) as e:
                logger.warning(
                    "Groq model '%s' unavailable: %s. Attempting fallback model.",
                    model,
                    e.message,
                )
                last_error = e
                continue
            except (AuthenticationError, InsufficientCreditsError):
                raise
            except RateLimitError as e:
                logger.warning("Groq model '%s' rate limited: %s. Attempting fallback.", model, e.message)
                last_error = e
                continue
            except (TimeoutError, ProviderUnavailableError) as e:
                logger.warning("Groq model '%s' encountered error: %s. Attempting fallback.", model, e.message)
                last_error = e
                continue
            except Exception as e:
                last_error = e
                break

        if isinstance(last_error, Exception):
            raise last_error

        raise ProviderUnavailableError(
            message="All configured Groq models failed.",
            provider=self.provider_name,
        )

    async def _complete_with_model(
        self, request: LLMRequest, model: str, remaining_deadline: Optional[float] = None
    ) -> LLMResponse:
        """Executes chat completion attempts for a specific Groq model."""
        base_timeout = request.timeout or self.settings.LLM_REQUEST_TIMEOUT
        if remaining_deadline is not None:
            timeout = min(base_timeout, max(5.0, remaining_deadline))
        else:
            timeout = base_timeout
        max_retries = self.settings.LLM_MAX_RETRIES
        base_backoff = self.settings.LLM_BASE_BACKOFF_SEC

        client = self._http_client or httpx.AsyncClient(timeout=timeout)
        should_close_client = self._http_client is None

        try:
            for attempt in range(max_retries):
                headers = {
                    "Authorization": f"Bearer {self.settings.GROQ_API_KEY.strip()}",
                    "Content-Type": "application/json",
                }

                payload: Dict[str, Any] = {
                    "model": model,
                    "messages": [m.model_dump() for m in request.messages],
                    "temperature": request.temperature,
                }
                if request.max_tokens:
                    payload["max_tokens"] = request.max_tokens
                if request.response_format:
                    payload["response_format"] = request.response_format

                start_time = time.time()
                try:
                    response = await client.post(self.ENDPOINT, headers=headers, json=payload, timeout=timeout)
                except httpx.ReadTimeout as exc:
                    self._consecutive_failures += 1
                    logger.warning(
                        "Groq model '%s' timed out (ReadTimeout after %.1fs). Advancing to next fallback model.",
                        model,
                        timeout,
                    )
                    raise TimeoutError(
                        message=f"Request to Groq model '{model}' timed out after {timeout:.1f}s.",
                        provider=self.provider_name,
                        model=model,
                    ) from exc
                except (httpx.ConnectTimeout, httpx.WriteTimeout) as exc:
                    self._consecutive_failures += 1
                    if attempt == max_retries - 1:
                        raise TimeoutError(
                            message=f"Request to Groq timed out after {timeout:.1f}s.",
                            provider=self.provider_name,
                            model=model,
                        ) from exc
                    await self._backoff_sleep(attempt, base_backoff)
                    continue
                except httpx.RequestError as exc:
                    self._consecutive_failures += 1
                    if attempt == max_retries - 1:
                        raise ProviderUnavailableError(
                            message=f"Network error connecting to Groq: {exc.__class__.__name__}",
                            provider=self.provider_name,
                            model=model,
                        ) from exc
                    await self._backoff_sleep(attempt, base_backoff)
                    continue

                if response.status_code == 200:
                    self._status = "HEALTHY"
                    self._consecutive_failures = 0
                    return self._parse_success_response(response.json(), model, time.time() - start_time)

                if response.status_code == 401:
                    self._status = "DISABLED"
                    raise AuthenticationError(
                        message="Groq authentication failed. Please check GROQ_API_KEY.",
                        provider=self.provider_name,
                        model=model,
                    )

                if response.status_code == 429:
                    retry_after = self._extract_retry_after(response)
                    backoff = retry_after if retry_after else (base_backoff * (2 ** attempt))
                    self._cooldown_until = time.time() + backoff
                    self._status = "COOLDOWN"
                    if retry_after and retry_after > 8.0:
                        raise RateLimitError(
                            message=f"Groq model '{model}' rate-limited (Retry-After: {retry_after}s). Switching to fallback.",
                            provider=self.provider_name,
                            model=model,
                            retry_after=retry_after,
                        )
                    if attempt == max_retries - 1:
                        raise RateLimitError(
                            message=f"Groq rate limit exceeded for model '{model}'.",
                            provider=self.provider_name,
                            model=model,
                            retry_after=backoff,
                        )
                    await asyncio.sleep(min(backoff, 5.0))
                    continue

                if response.status_code in (400, 404):
                    err_text = response.text.lower()
                    if "response_format" in err_text or "json_object" in err_text:
                        raise UnsupportedFeatureError(
                            message=f"Structured JSON output is not supported by model '{model}' on Groq.",
                            provider=self.provider_name,
                            model=model,
                        )
                    if "model" in err_text or response.status_code == 404:
                        raise ModelUnavailableError(
                            message=f"Model '{model}' is unavailable or not found on Groq.",
                            provider=self.provider_name,
                            model=model,
                        )
                    raise ProviderUnavailableError(
                        message=f"Groq returned error {response.status_code}: {response.text[:200]}",
                        provider=self.provider_name,
                        model=model,
                        status_code=response.status_code,
                    )

                if response.status_code in (502, 503, 504):
                    self._consecutive_failures += 1
                    logger.warning("Groq model '%s' returned HTTP %d. Switching to fallback.", model, response.status_code)
                    raise ProviderUnavailableError(
                        message=f"Groq upstream error (HTTP {response.status_code}) for model '{model}'.",
                        provider=self.provider_name,
                        model=model,
                        status_code=response.status_code,
                    )

                if response.status_code >= 500:
                    self._consecutive_failures += 1
                    if attempt == max_retries - 1:
                        raise ProviderUnavailableError(
                            message=f"Groq upstream server error (HTTP {response.status_code}).",
                            provider=self.provider_name,
                            model=model,
                            status_code=response.status_code,
                        )
                    await self._backoff_sleep(attempt, base_backoff)
                    continue

                raise ProviderUnavailableError(
                    message=f"Unexpected status HTTP {response.status_code} from Groq.",
                    provider=self.provider_name,
                    model=model,
                    status_code=response.status_code,
                )

        finally:
            if should_close_client:
                await client.aclose()

    def _parse_success_response(self, data: Dict[str, Any], model: str, latency: float) -> LLMResponse:
        choices = data.get("choices", [])
        if not choices:
            raise ProviderUnavailableError(
                message="Groq returned empty choices array.",
                provider=self.provider_name,
                model=model,
            )
        first_choice = choices[0]
        content = first_choice.get("message", {}).get("content", "")
        finish_reason = first_choice.get("finish_reason")

        usage_data = data.get("usage")
        usage = None
        if usage_data:
            usage = TokenUsage(
                prompt_tokens=usage_data.get("prompt_tokens", 0),
                completion_tokens=usage_data.get("completion_tokens", 0),
                total_tokens=usage_data.get("total_tokens", 0),
            )

        return LLMResponse(
            content=content,
            provider=self.provider_name,
            model=data.get("model", model),
            usage=usage,
            finish_reason=finish_reason,
            key_alias="GROQ_KEY",
            metadata={"latency_sec": round(latency, 3)},
        )

    def _extract_retry_after(self, response: httpx.Response) -> Optional[float]:
        retry_val = response.headers.get("retry-after")
        if retry_val:
            try:
                return float(retry_val)
            except ValueError:
                pass
        return None

    async def _backoff_sleep(self, attempt: int, base: float) -> None:
        delay = base * (2 ** attempt) + (random.random() * 0.5)
        await asyncio.sleep(delay)

    async def get_health_status(self) -> Dict[str, Any]:
        """Returns safe health status of Groq provider without exposing secret."""
        now = time.time()
        cooldown_rem = max(0.0, self._cooldown_until - now) if self._cooldown_until > now else 0.0
        return {
            "provider": self.provider_name,
            "configured": self.is_configured,
            "status": self._status,
            "consecutive_failures": self._consecutive_failures,
            "cooldown_remaining_sec": round(cooldown_rem, 1),
        }
