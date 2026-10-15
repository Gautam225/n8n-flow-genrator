"""OpenRouter Primary LLM Provider Client.

Implements multi-key pool management (4 keys), bounded retries with jitter,
per-key cooldowns, circuit-breaker states, and strict secret masking.
"""
import asyncio
import logging
import random
import time
from typing import Any, Dict, List, Optional
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
    ChatMessage,
    LLMClientInterface,
    LLMRequest,
    LLMResponse,
    TokenUsage,
)

logger = logging.getLogger(__name__)


class KeySlot:
    """Represents an individual OpenRouter API key slot with circuit breaker state."""

    def __init__(self, alias: str, secret: str) -> None:
        self.alias = alias
        self.secret = secret
        self.status: str = "HEALTHY"  # HEALTHY, COOLDOWN, CIRCUIT_OPEN, DISABLED
        self.cooldown_until: float = 0.0
        self.consecutive_failures: int = 0
        self.disabled_reason: Optional[str] = None

    def is_available(self, current_time: float) -> bool:
        if self.status == "DISABLED":
            return False
        if self.status in ("COOLDOWN", "CIRCUIT_OPEN"):
            if current_time >= self.cooldown_until:
                self.status = "HEALTHY"
                self.consecutive_failures = 0
                return True
            return False
        return True

    def mark_cooldown(self, seconds: float, reason: str = "Rate limited") -> None:
        self.status = "COOLDOWN"
        self.cooldown_until = time.time() + max(1.0, seconds)
        self.consecutive_failures += 1
        self.disabled_reason = reason

    def mark_circuit_open(self, seconds: float = 60.0, reason: str = "Consecutive provider failures") -> None:
        self.status = "CIRCUIT_OPEN"
        self.cooldown_until = time.time() + max(5.0, seconds)
        self.consecutive_failures += 1
        self.disabled_reason = reason

    def mark_disabled(self, reason: str) -> None:
        self.status = "DISABLED"
        self.disabled_reason = reason

    def mark_success(self) -> None:
        self.status = "HEALTHY"
        self.consecutive_failures = 0
        self.disabled_reason = None


class OpenRouterClient(LLMClientInterface):
    """OpenRouter API client managing a pool of up to 4 keys."""

    ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"

    def __init__(
        self,
        settings: Optional[LLMSettings] = None,
        http_client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self.settings = settings or LLMSettings()
        self._http_client = http_client
        self._key_slots: List[KeySlot] = [
            KeySlot(alias, key) for alias, key in self.settings.get_openrouter_keys()
        ]

    @property
    def provider_name(self) -> str:
        return "openrouter"

    @property
    def is_configured(self) -> bool:
        return len(self._key_slots) > 0

    def get_available_key(self) -> Optional[KeySlot]:
        """Finds the next healthy key in the pool, or None if all are cooling down / disabled."""
        now = time.time()
        for slot in self._key_slots:
            if slot.is_available(now):
                return slot
        return None

    def get_min_cooldown_remaining(self) -> float:
        """Returns seconds until the earliest key in cooldown becomes available."""
        now = time.time()
        remaining = [
            slot.cooldown_until - now
            for slot in self._key_slots
            if slot.status in ("COOLDOWN", "CIRCUIT_OPEN")
        ]
        return max(0.0, min(remaining)) if remaining else 0.0

    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Executes a chat completion across available models and keys."""
        if not self.is_configured:
            raise AuthenticationError(
                message="No OpenRouter API keys configured. Set OPENROUTER_API_KEY_1 in .env.",
                provider=self.provider_name,
            )

        # Build model cascade: requested model or primary model, then fallbacks
        models_to_try = []
        primary_model = request.model or self.settings.OPENROUTER_MODEL
        models_to_try.append(primary_model)
        for fb in self.settings.OPENROUTER_FALLBACK_MODELS:
            if fb not in models_to_try:
                models_to_try.append(fb)

        last_error: Optional[Exception] = None
        start_time = time.time()
        deadline = getattr(self.settings, "TOTAL_GENERATION_DEADLINE", 95.0)

        attempted_count = 0
        max_models_to_try = 2  # Try primary + at most 1 distinct fallback before bubbling up to Groq

        for model in models_to_try:
            attempted_count += 1
            if attempted_count > max_models_to_try:
                logger.info(
                    "Bounded OpenRouter model attempts reached (%d models tried). Concluding OpenRouter cascade.",
                    attempted_count - 1,
                )
                break

            elapsed = time.time() - start_time
            remaining = deadline - elapsed
            if remaining < 25.0:
                logger.warning(
                    "Overall generation deadline approaching (%.1fs elapsed of %.1fs, %.1fs remaining). Halting OpenRouter cascade to preserve fallback budget.",
                    elapsed,
                    deadline,
                    remaining,
                )
                break

            try:
                return await self._complete_with_model(request, model, remaining_deadline=remaining)
            except (ModelUnavailableError, UnsupportedFeatureError) as e:
                logger.warning(
                    "OpenRouter model '%s' failed with non-retryable error: %s. Attempting fallback.",
                    model,
                    e.message,
                )
                last_error = e
                continue
            except (AuthenticationError, InsufficientCreditsError):
                # Account-wide fatal errors should not cascade through models
                raise
            except RateLimitError as e:
                logger.warning(
                    "OpenRouter model '%s' rate limited across keys. Attempting fallback model.",
                    model,
                )
                last_error = e
                continue
            except (TimeoutError, ProviderUnavailableError) as e:
                logger.warning(
                    "OpenRouter model '%s' encountered provider/timeout error: %s. Attempting fallback model.",
                    model,
                    e.message,
                )
                last_error = e
                continue
            except Exception as e:
                last_error = e
                break

        if isinstance(last_error, Exception):
            raise last_error

        raise ProviderUnavailableError(
            message="All configured OpenRouter models failed.",
            provider=self.provider_name,
        )

    async def _complete_with_model(
        self, request: LLMRequest, model: str, remaining_deadline: Optional[float] = None
    ) -> LLMResponse:
        """Attempts completion for a specific model with bounded key retries and jitter."""
        max_retries = self.settings.LLM_MAX_RETRIES
        base_backoff = self.settings.LLM_BASE_BACKOFF_SEC
        base_timeout = request.timeout or self.settings.LLM_REQUEST_TIMEOUT
        if remaining_deadline is not None:
            timeout = min(base_timeout, max(5.0, remaining_deadline))
        else:
            timeout = base_timeout

        client = self._http_client or httpx.AsyncClient(timeout=timeout)
        should_close_client = self._http_client is None

        try:
            for attempt in range(max_retries):
                slot = self.get_available_key()
                if not slot:
                    cooldown = self.get_min_cooldown_remaining()
                    raise RateLimitError(
                        message=f"All configured OpenRouter keys are in cooldown. Available in {cooldown:.1f}s.",
                        provider=self.provider_name,
                        model=model,
                        retry_after=cooldown,
                    )

                headers = {
                    "Authorization": f"Bearer {slot.secret}",
                    "HTTP-Referer": self.settings.OPENROUTER_SITE_URL,
                    "X-Title": self.settings.OPENROUTER_APP_NAME,
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
                    slot.consecutive_failures += 1
                    logger.warning(
                        "Model '%s' timed out (ReadTimeout after %.1fs). Advancing to next fallback model.",
                        model,
                        timeout,
                    )
                    # For a ReadTimeout (server took too long to generate), DO NOT burn another 55s retrying the same slow model!
                    # Fast-fail this model immediately so the cascade moves to the next model.
                    raise TimeoutError(
                        message=f"Model '{model}' timed out after {timeout:.1f}s while generating response.",
                        provider=self.provider_name,
                        model=model,
                    ) from exc
                except (httpx.ConnectTimeout, httpx.WriteTimeout) as exc:
                    slot.consecutive_failures += 1
                    if slot.consecutive_failures >= 3:
                        slot.mark_circuit_open(30.0, "Connection timeout threshold met")
                    if attempt == max_retries - 1:
                        raise TimeoutError(
                            message=f"Connection to OpenRouter timed out after {timeout:.1f}s.",
                            provider=self.provider_name,
                            model=model,
                        ) from exc
                    await self._backoff_sleep(attempt, base_backoff)
                    continue
                except httpx.RequestError as exc:
                    slot.consecutive_failures += 1
                    if attempt == max_retries - 1:
                        raise ProviderUnavailableError(
                            message=f"Network error connecting to OpenRouter: {exc.__class__.__name__}",
                            provider=self.provider_name,
                            model=model,
                        ) from exc
                    await self._backoff_sleep(attempt, base_backoff)
                    continue

                # Process HTTP status codes
                if response.status_code == 200:
                    slot.mark_success()
                    return self._parse_success_response(response.json(), model, slot.alias, time.time() - start_time)

                if response.status_code == 401:
                    slot.mark_disabled("HTTP 401: Invalid credentials")
                    # If other keys exist, try them on the next attempt
                    if self.get_available_key():
                        continue
                    raise AuthenticationError(
                        message="OpenRouter authentication failed. Please verify configured API keys.",
                        provider=self.provider_name,
                        model=model,
                    )

                if response.status_code == 402:
                    slot.mark_disabled("HTTP 402: Insufficient credits")
                    raise InsufficientCreditsError(
                        message="OpenRouter account credits exhausted or quota exceeded.",
                        provider=self.provider_name,
                        model=model,
                    )

                if response.status_code == 429:
                    err_text = response.text.lower()
                    retry_after = self._extract_retry_after(response)
                    backoff = retry_after if retry_after else (base_backoff * (2 ** attempt))

                    # Distinguish upstream provider rate limit on a specific model from gateway key exhaustion
                    if "upstream" in err_text or "provider returned error" in err_text or "rate-limited upstream" in err_text:
                        raise ModelUnavailableError(
                            message=f"Model '{model}' is temporarily rate-limited upstream by provider.",
                            provider=self.provider_name,
                            model=model,
                        )

                    slot.mark_cooldown(backoff, "HTTP 429: Rate limit")
                    # If retry_after is significant (>8s), fail this model fast to let fallback take over
                    if retry_after and retry_after > 8.0:
                        raise RateLimitError(
                            message=f"Model '{model}' is rate-limited (Retry-After: {retry_after}s). Switching to fallback.",
                            provider=self.provider_name,
                            model=model,
                            retry_after=retry_after,
                        )

                    # Try next key on next attempt if available, otherwise sleep or raise
                    if attempt == max_retries - 1 or not self.get_available_key():
                        raise RateLimitError(
                            message=f"OpenRouter rate limit exceeded for model '{model}'.",
                            provider=self.provider_name,
                            model=model,
                            retry_after=backoff,
                        )
                    continue

                if response.status_code in (400, 404):
                    err_text = response.text.lower()
                    if "response_format" in err_text or "json_object" in err_text:
                        raise UnsupportedFeatureError(
                            message=f"Structured JSON output is not supported by model '{model}'.",
                            provider=self.provider_name,
                            model=model,
                        )
                    if (
                        "model" in err_text
                        or response.status_code == 404
                        or "not found" in err_text
                        or "unknown" in err_text
                        or "does not exist" in err_text
                    ):
                        raise ModelUnavailableError(
                            message=f"Model '{model}' is unavailable or not found on OpenRouter.",
                            provider=self.provider_name,
                            model=model,
                        )
                    raise ProviderUnavailableError(
                        message=f"OpenRouter returned client error {response.status_code}: {response.text[:200]}",
                        provider=self.provider_name,
                        model=model,
                        status_code=response.status_code,
                    )

                if response.status_code in (502, 503, 504):
                    slot.consecutive_failures += 1
                    logger.warning(
                        "OpenRouter model '%s' returned HTTP %d. Switching to fallback model.",
                        model,
                        response.status_code,
                    )
                    raise ProviderUnavailableError(
                        message=f"OpenRouter upstream service error (HTTP {response.status_code}) for model '{model}'.",
                        provider=self.provider_name,
                        model=model,
                        status_code=response.status_code,
                    )

                if response.status_code >= 500:
                    slot.consecutive_failures += 1
                    if slot.consecutive_failures >= 3:
                        slot.mark_circuit_open(60.0, f"HTTP {response.status_code} server error")
                    if attempt == max_retries - 1:
                        raise ProviderUnavailableError(
                            message=f"OpenRouter server error (HTTP {response.status_code}).",
                            provider=self.provider_name,
                            model=model,
                            status_code=response.status_code,
                        )
                    await self._backoff_sleep(attempt, base_backoff)
                    continue

                # Unexpected status
                raise ProviderUnavailableError(
                    message=f"Unexpected status HTTP {response.status_code} from OpenRouter.",
                    provider=self.provider_name,
                    model=model,
                    status_code=response.status_code,
                )

        finally:
            if should_close_client:
                await client.aclose()

    def _parse_success_response(
        self, data: Dict[str, Any], model: str, key_alias: str, latency: float
    ) -> LLMResponse:
        choices = data.get("choices", [])
        if not choices:
            err_obj = data.get("error")
            err_detail = err_obj.get("message") if isinstance(err_obj, dict) else ""
            msg = f"OpenRouter returned empty choices array. {err_detail}".strip()
            raise ProviderUnavailableError(
                message=msg,
                provider=self.provider_name,
                model=model,
            )
        first_choice = choices[0]
        content = first_choice.get("message", {}).get("content", "")
        if not content or not str(content).strip():
            raise ProviderUnavailableError(
                message="OpenRouter returned blank message content.",
                provider=self.provider_name,
                model=model,
            )
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
            key_alias=key_alias,
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
        """Returns safe health status of key pool without revealing secrets."""
        now = time.time()
        pool_status = []
        for slot in self._key_slots:
            cooldown_rem = max(0.0, slot.cooldown_until - now) if slot.cooldown_until > now else 0.0
            pool_status.append({
                "alias": slot.alias,
                "status": slot.status,
                "consecutive_failures": slot.consecutive_failures,
                "cooldown_remaining_sec": round(cooldown_rem, 1),
                "reason": slot.disabled_reason,
            })
        return {
            "provider": self.provider_name,
            "configured": self.is_configured,
            "total_keys": len(self._key_slots),
            "healthy_keys": sum(1 for s in self._key_slots if s.is_available(now)),
            "pool": pool_status,
        }
