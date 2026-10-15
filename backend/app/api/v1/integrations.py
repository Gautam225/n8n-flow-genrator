"""Endpoints for external service integrations (n8n, database, LLMs)."""
import time
from typing import List, Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.app.services.n8n_client import (
    N8nClient,
    N8nStatusResponse,
)
from backend.app.llm.config import LLMSettings
from backend.app.llm.manager import LLMProviderManager
from backend.app.llm.interface import ChatMessage, LLMRequest
from backend.app.llm.exceptions import (
    AllProvidersUnavailableError,
    AuthenticationError,
    InsufficientCreditsError,
    ModelUnavailableError,
    ProviderUnavailableError,
    RateLimitError,
    TimeoutError,
    UnsupportedFeatureError,
)
from backend.app.security.auth import UserContext, get_current_user
from backend.app.security.sanitizer import sanitize_secrets

router = APIRouter(prefix="/integrations", tags=["integrations"])


# --- N8N Integration ---

async def get_n8n_client() -> N8nClient:
    """Dependency provider for N8nClient ensuring proper resource cleanup."""
    async with N8nClient() as client:
        yield client


@router.get("/n8n/status", response_model=N8nStatusResponse)
async def get_n8n_connection_status(
    client: N8nClient = Depends(get_n8n_client),
    current_user: UserContext = Depends(get_current_user),
) -> N8nStatusResponse:
    """Check connectivity and authentication status of the configured n8n instance.

    Performs a safe, read-only GET request to n8n's workflow API with X-N8N-API-KEY.
    Returns sanitized status without leaking secrets, tokens, or raw exception traces.
    """
    return await client.check_connection()


class N8nCredentialSummary(BaseModel):
    """Sanitized metadata summary of an existing n8n credential."""
    id: str
    name: str
    type: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


@router.get("/n8n/credentials", response_model=List[N8nCredentialSummary])
async def list_n8n_credentials(
    client: N8nClient = Depends(get_n8n_client),
    current_user: UserContext = Depends(get_current_user),
) -> List[N8nCredentialSummary]:
    """Fetch sanitized list of existing credentials in the target n8n instance.

    Read-only introspection: returns only metadata ('id', 'name', 'type', 'created_at', 'updated_at').
    Raw secret values (passwords, tokens, keys) are never retrieved or exposed.
    """
    creds = await client.get_credentials()
    return [N8nCredentialSummary(**c) for c in creds]


# --- LLM Integration ---

class LLMStatusResponse(BaseModel):
    primary_provider: str
    primary_model: str
    fallback_models: List[str]
    is_primary_configured: bool
    healthy_keys_count: int
    total_keys_count: int
    fallback_provider: Optional[str] = None
    fallback_model: Optional[str] = None
    is_fallback_configured: bool = False
    status_summary: str


class LLMTestResponse(BaseModel):
    status: str  # "connected", "model_unavailable", "rate_limited", "unauthorized", "insufficient_credits", "timeout", "error"
    provider: str
    model: str
    latency_sec: float
    message: str
    supports_structured_json: bool


def get_llm_manager() -> LLMProviderManager:
    return LLMProviderManager()


@router.get("/llm/status", response_model=LLMStatusResponse)
async def get_llm_provider_status(
    llm_manager: LLMProviderManager = Depends(get_llm_manager),
    current_user: UserContext = Depends(get_current_user),
) -> LLMStatusResponse:
    """Inspect configured LLM provider and model status without disclosing secrets."""
    settings = llm_manager.settings
    health = await llm_manager.get_health_status()
    primary_health = health.get("primary", {})
    fallback_health = health.get("fallback", {})

    is_primary_cfg = primary_health.get("configured", False)
    healthy_keys = primary_health.get("healthy_keys", 0)
    total_keys = primary_health.get("total_keys", 0)
    is_fallback_cfg = fallback_health.get("configured", False)

    fallback_models_list = (
        settings.OPENROUTER_FALLBACK_MODELS
        if isinstance(settings.OPENROUTER_FALLBACK_MODELS, list)
        else [m.strip() for m in str(settings.OPENROUTER_FALLBACK_MODELS).split(",") if m.strip()]
    )

    if not is_primary_cfg:
        summary = "No OpenRouter API keys configured in .env."
    elif healthy_keys == 0:
        summary = "All OpenRouter keys in cooldown or disabled."
    else:
        summary = f"Ready with {healthy_keys}/{total_keys} active keys on {settings.OPENROUTER_MODEL}."

    return LLMStatusResponse(
        primary_provider="openrouter",
        primary_model=settings.OPENROUTER_MODEL,
        fallback_models=fallback_models_list,
        is_primary_configured=is_primary_cfg,
        healthy_keys_count=healthy_keys,
        total_keys_count=total_keys,
        fallback_provider="groq" if is_fallback_cfg else None,
        fallback_model=settings.GROQ_MODEL if is_fallback_cfg else None,
        is_fallback_configured=is_fallback_cfg,
        status_summary=summary,
    )


@router.post("/llm/test", response_model=LLMTestResponse)
async def test_llm_connection(
    llm_manager: LLMProviderManager = Depends(get_llm_manager),
    current_user: UserContext = Depends(get_current_user),
) -> LLMTestResponse:
    """Performs a live test completion to verify model availability and structured JSON capability."""
    settings = llm_manager.settings
    test_request = LLMRequest(
        messages=[
            ChatMessage(role="system", content="You are a system health check assistant."),
            ChatMessage(role="user", content="Ping. Return a JSON object with key 'status' set to 'ok'."),
        ],
        temperature=0.1,
        max_tokens=60,
        response_format={"type": "json_object"},
    )

    start_time = time.time()
    try:
        response = await llm_manager.complete(test_request)
        latency = round(time.time() - start_time, 3)
        return LLMTestResponse(
            status="connected",
            provider=response.provider,
            model=response.model,
            latency_sec=latency,
            message=f"Model '{response.model}' connected and successfully generated structured JSON in {latency}s.",
            supports_structured_json=True,
        )
    except ModelUnavailableError as e:
        latency = round(time.time() - start_time, 3)
        return LLMTestResponse(
            status="model_unavailable",
            provider=e.provider or "openrouter",
            model=e.model or settings.OPENROUTER_MODEL,
            latency_sec=latency,
            message=sanitize_secrets(e.message),
            supports_structured_json=False,
        )
    except RateLimitError as e:
        latency = round(time.time() - start_time, 3)
        return LLMTestResponse(
            status="rate_limited",
            provider=e.provider or "openrouter",
            model=e.model or settings.OPENROUTER_MODEL,
            latency_sec=latency,
            message=sanitize_secrets(e.message),
            supports_structured_json=False,
        )
    except AuthenticationError as e:
        latency = round(time.time() - start_time, 3)
        return LLMTestResponse(
            status="unauthorized",
            provider=e.provider or "openrouter",
            model=e.model or settings.OPENROUTER_MODEL,
            latency_sec=latency,
            message=sanitize_secrets(e.message),
            supports_structured_json=False,
        )
    except InsufficientCreditsError as e:
        latency = round(time.time() - start_time, 3)
        return LLMTestResponse(
            status="insufficient_credits",
            provider=e.provider or "openrouter",
            model=e.model or settings.OPENROUTER_MODEL,
            latency_sec=latency,
            message=sanitize_secrets(e.message),
            supports_structured_json=False,
        )
    except TimeoutError as e:
        latency = round(time.time() - start_time, 3)
        return LLMTestResponse(
            status="timeout",
            provider=e.provider or "openrouter",
            model=e.model or settings.OPENROUTER_MODEL,
            latency_sec=latency,
            message=sanitize_secrets(e.message),
            supports_structured_json=False,
        )
    except AllProvidersUnavailableError as e:
        latency = round(time.time() - start_time, 3)
        return LLMTestResponse(
            status="error",
            provider="openrouter",
            model=settings.OPENROUTER_MODEL,
            latency_sec=latency,
            message=sanitize_secrets(e.message),
            supports_structured_json=False,
        )
    except Exception as e:
        latency = round(time.time() - start_time, 3)
        return LLMTestResponse(
            status="error",
            provider="openrouter",
            model=settings.OPENROUTER_MODEL,
            latency_sec=latency,
            message=sanitize_secrets(f"Unexpected connection error: {str(e)}"),
            supports_structured_json=False,
        )
