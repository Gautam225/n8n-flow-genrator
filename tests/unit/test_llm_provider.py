"""Unit tests for the LLM Provider Layer (OpenRouter, Groq, and ProviderManager).

All HTTP requests are mocked with httpx.MockTransport. No live API calls or keys required.
"""
import json
import pytest
import httpx

from backend.app.llm.config import LLMSettings
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
from backend.app.llm.groq import GroqClient
from backend.app.llm.interface import ChatMessage, LLMRequest
from backend.app.llm.manager import LLMProviderManager
from backend.app.llm.openrouter import OpenRouterClient
from backend.app.schemas.ir import IRNode, WorkflowIR


# Helper fixtures & settings
@pytest.fixture
def base_settings():
    return LLMSettings(
        _env_file=None,
        OPENROUTER_API_KEY_1="sk-or-test-key-1",
        OPENROUTER_API_KEY_2="sk-or-test-key-2",
        OPENROUTER_API_KEY_3=None,
        OPENROUTER_API_KEY_4=None,
        OPENROUTER_MODEL="meta-llama/llama-3.3-70b-instruct:free",
        OPENROUTER_FALLBACK_MODELS=["google/gemini-2.0-flash-exp:free"],
        GROQ_API_KEY="gsk_test_groq_key",
        GROQ_MODEL="llama-3.3-70b-versatile",
        LLM_REQUEST_TIMEOUT=5.0,
        LLM_MAX_RETRIES=2,
        LLM_BASE_BACKOFF_SEC=0.01,  # Fast backoff for tests
    )


@pytest.fixture
def sample_request():
    return LLMRequest(
        messages=[
            ChatMessage(role="system", content="You are a workflow assistant."),
            ChatMessage(role="user", content="Build a slack alert workflow."),
        ],
        temperature=0.2,
    )


def make_openrouter_payload(content="Workflow generated successfully.", model="meta-llama/llama-3.3-70b-instruct:free"):
    return {
        "id": "gen-12345",
        "model": model,
        "choices": [
            {
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 120,
            "completion_tokens": 45,
            "total_tokens": 165,
        },
    }


def make_groq_payload(content="Groq fallback generated.", model="llama-3.3-70b-versatile"):
    return {
        "id": "chatcmpl-groq-123",
        "model": model,
        "choices": [
            {
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 90,
            "completion_tokens": 30,
            "total_tokens": 120,
        },
    }


# ------------------------------------------------------------------------------
# 1. Successful Responses
# ------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_successful_openrouter_response(base_settings, sample_request):
    """Asserts that OpenRouter returns a normalized response with usage and key alias."""
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer sk-or-test-key-1"
        return httpx.Response(200, json=make_openrouter_payload("Plan created."))

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = OpenRouterClient(settings=base_settings, http_client=mock_client)

    response = await client.complete(sample_request)
    assert response.provider == "openrouter"
    assert response.content == "Plan created."
    assert response.usage.total_tokens == 165
    assert response.key_alias == "OPENROUTER_KEY_1"
    assert "sk-or-test-key-1" not in response.key_alias


@pytest.mark.asyncio
async def test_successful_groq_response(base_settings, sample_request):
    """Asserts that Groq client returns normalized response."""
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer gsk_test_groq_key"
        return httpx.Response(200, json=make_groq_payload("Groq result."))

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = GroqClient(settings=base_settings, http_client=mock_client)

    response = await client.complete(sample_request)
    assert response.provider == "groq"
    assert response.content == "Groq result."
    assert response.usage.total_tokens == 120
    assert response.key_alias == "GROQ_KEY"


@pytest.mark.asyncio
async def test_openrouter_success_does_not_invoke_groq(base_settings, sample_request):
    """Asserts that when OpenRouter succeeds, Groq is never called."""
    groq_called = False

    def or_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=make_openrouter_payload("Direct OpenRouter response."))

    def groq_handler(request: httpx.Request) -> httpx.Response:
        nonlocal groq_called
        groq_called = True
        return httpx.Response(200, json=make_groq_payload())

    or_client = OpenRouterClient(base_settings, httpx.AsyncClient(transport=httpx.MockTransport(or_handler)))
    groq_client = GroqClient(base_settings, httpx.AsyncClient(transport=httpx.MockTransport(groq_handler)))
    manager = LLMProviderManager(base_settings, or_client, groq_client)

    response = await manager.complete(sample_request)
    assert response.provider == "openrouter"
    assert groq_called is False


# ------------------------------------------------------------------------------
# 2. Fallback Behavior: OpenRouter to Groq
# ------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_openrouter_rate_limit_falls_back_to_groq(base_settings, sample_request):
    """Asserts that when all OpenRouter keys return 429, manager falls back to Groq."""
    def or_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"retry-after": "5"}, json={"error": "Rate limited"})

    def groq_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=make_groq_payload("Groq handled the fallback."))

    or_client = OpenRouterClient(base_settings, httpx.AsyncClient(transport=httpx.MockTransport(or_handler)))
    groq_client = GroqClient(base_settings, httpx.AsyncClient(transport=httpx.MockTransport(groq_handler)))
    manager = LLMProviderManager(base_settings, or_client, groq_client)

    response = await manager.complete(sample_request)
    assert response.provider == "groq"
    assert response.content == "Groq handled the fallback."
    assert response.metadata.get("fallback_from") == "openrouter"


@pytest.mark.asyncio
async def test_openrouter_transient_5xx_and_retry_behavior(base_settings, sample_request):
    """Asserts bounded retries on 5xx before succeeding or failing."""
    call_count = 0

    def or_handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(502, text="Bad Gateway")
        return httpx.Response(200, json=make_openrouter_payload("Recovered on attempt 2."))

    or_client = OpenRouterClient(base_settings, httpx.AsyncClient(transport=httpx.MockTransport(or_handler)))
    response = await or_client.complete(sample_request)

    assert call_count == 2
    assert response.content == "Recovered on attempt 2."


# ------------------------------------------------------------------------------
# 3. Provider Unavailability & Draft Preservation
# ------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_all_providers_unavailable_preserves_draft(base_settings, sample_request):
    """Asserts AllProvidersUnavailableError preserves the caller's active workflow draft."""
    mock_draft = WorkflowIR(
        id="wf_draft_01",
        name="Preserved Draft",
        nodes=[IRNode(id="trig", name="Trigger", node_type="n8n-nodes-base.manualTrigger")],
    )
    request_with_draft = sample_request.model_copy()
    request_with_draft.preserved_draft = mock_draft

    def or_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="Service Unavailable")

    def groq_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="Groq Service Unavailable")

    or_client = OpenRouterClient(base_settings, httpx.AsyncClient(transport=httpx.MockTransport(or_handler)))
    groq_client = GroqClient(base_settings, httpx.AsyncClient(transport=httpx.MockTransport(groq_handler)))
    manager = LLMProviderManager(base_settings, or_client, groq_client)

    with pytest.raises(AllProvidersUnavailableError) as exc_info:
        await manager.complete(request_with_draft)

    assert exc_info.value.preserved_draft is not None
    assert exc_info.value.preserved_draft.id == "wf_draft_01"
    assert "All LLM providers unavailable" in exc_info.value.message


@pytest.mark.asyncio
async def test_no_groq_key_configured(sample_request):
    """Asserts application functions and handles OpenRouter failures when Groq is not configured."""
    settings_no_groq = LLMSettings(
        _env_file=None,
        OPENROUTER_API_KEY_1="sk-or-valid-key",
        OPENROUTER_API_KEY_2=None,
        OPENROUTER_API_KEY_3=None,
        OPENROUTER_API_KEY_4=None,
        GROQ_API_KEY=None,  # No Groq
    )
    groq_client = GroqClient(settings_no_groq)
    assert groq_client.is_configured is False

    def or_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "Rate limited"})

    or_client = OpenRouterClient(settings_no_groq, httpx.AsyncClient(transport=httpx.MockTransport(or_handler)))
    manager = LLMProviderManager(settings_no_groq, or_client, groq_client)

    with pytest.raises(AllProvidersUnavailableError) as exc_info:
        await manager.complete(sample_request)
    assert "Primary provider (OpenRouter) failed" in exc_info.value.message


# ------------------------------------------------------------------------------
# 4. Multi-Key Management, Cooldowns & Quotas
# ------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_per_key_cooldown_and_failover_to_key_2(base_settings, sample_request):
    """Asserts that when Key 1 hits 429, Key 2 takes over seamlessly."""
    calls_by_key = []

    def or_handler(request: httpx.Request) -> httpx.Response:
        auth = request.headers["authorization"]
        if "sk-or-test-key-1" in auth:
            calls_by_key.append("KEY_1")
            return httpx.Response(429, headers={"retry-after": "10"}, json={"error": "Rate limit on Key 1"})
        if "sk-or-test-key-2" in auth:
            calls_by_key.append("KEY_2")
            return httpx.Response(200, json=make_openrouter_payload("Served by Key 2."))
        return httpx.Response(500)

    client = OpenRouterClient(base_settings, httpx.AsyncClient(transport=httpx.MockTransport(or_handler)))
    response = await client.complete(sample_request)

    assert response.content == "Served by Key 2."
    assert response.key_alias == "OPENROUTER_KEY_2"
    assert calls_by_key == ["KEY_1", "KEY_2"]


@pytest.mark.asyncio
async def test_all_openrouter_keys_rate_limited_no_infinite_rotation(base_settings, sample_request):
    """Asserts that if all keys in the pool return 429, rotation terminates with RateLimitError."""
    call_count = 0

    def or_handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(429, headers={"retry-after": "5"}, json={"error": "Rate limited"})

    client = OpenRouterClient(base_settings, httpx.AsyncClient(transport=httpx.MockTransport(or_handler)))

    with pytest.raises(RateLimitError) as exc_info:
        await client.complete(sample_request)

    # Should not infinite loop; with 2 keys and max_retries=2, calls are strictly bounded
    assert call_count <= 4
    assert exc_info.value.retry_after is not None


@pytest.mark.asyncio
async def test_account_quota_exhaustion_402(base_settings, sample_request):
    """Asserts HTTP 402 triggers InsufficientCreditsError and disables the key."""
    def or_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(402, json={"error": "Credits exhausted"})

    client = OpenRouterClient(base_settings, httpx.AsyncClient(transport=httpx.MockTransport(or_handler)))

    with pytest.raises(InsufficientCreditsError):
        await client.complete(sample_request)


# ------------------------------------------------------------------------------
# 5. Timeouts, Malformed Responses & Secret Redaction
# ------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_request_timeout(base_settings, sample_request):
    """Asserts that network connect timeouts raise TimeoutError."""
    def or_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("Connection timed out")

    client = OpenRouterClient(base_settings, httpx.AsyncClient(transport=httpx.MockTransport(or_handler)))

    with pytest.raises(TimeoutError):
        await client.complete(sample_request)


@pytest.mark.asyncio
async def test_unsupported_structured_output_feature(base_settings, sample_request):
    """Asserts that 400 for unsupported JSON format raises UnsupportedFeatureError."""
    def or_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="Model does not support response_format json_object")

    client = OpenRouterClient(base_settings, httpx.AsyncClient(transport=httpx.MockTransport(or_handler)))
    req = sample_request.model_copy()
    req.response_format = {"type": "json_object"}

    with pytest.raises(UnsupportedFeatureError):
        await client.complete(req)


@pytest.mark.asyncio
async def test_secret_redaction_in_health_status_and_errors(base_settings):
    """Asserts that raw secret values never appear in health status or representations."""
    client = OpenRouterClient(base_settings)
    status = await client.get_health_status()
    status_str = json.dumps(status)

    assert "sk-or-test-key-1" not in status_str
    assert "sk-or-test-key-2" not in status_str
    assert "OPENROUTER_KEY_1" in status_str
    assert "OPENROUTER_KEY_2" in status_str


@pytest.mark.asyncio
async def test_invalid_credentials_401(sample_request):
    """Asserts HTTP 401 raises AuthenticationError."""
    settings_single_key = LLMSettings(
        _env_file=None,
        OPENROUTER_API_KEY_1="sk-invalid-key",
        OPENROUTER_API_KEY_2=None,
        OPENROUTER_API_KEY_3=None,
        OPENROUTER_API_KEY_4=None,
    )
    def or_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "Invalid API Key"})

    client = OpenRouterClient(settings_single_key, httpx.AsyncClient(transport=httpx.MockTransport(or_handler)))

    with pytest.raises(AuthenticationError):
        await client.complete(sample_request)


@pytest.mark.asyncio
async def test_malformed_provider_response_empty_choices(base_settings, sample_request):
    """Asserts that responses with empty choices or invalid format raise ProviderUnavailableError."""
    def or_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": []})

    client = OpenRouterClient(base_settings, httpx.AsyncClient(transport=httpx.MockTransport(or_handler)))

    with pytest.raises(ProviderUnavailableError) as exc_info:
        await client.complete(sample_request)
    assert "empty choices array" in exc_info.value.message


# ------------------------------------------------------------------------------
# 6. Model Availability, Cascade & Health Test Regression Tests
# ------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_model_unavailable_cascades_to_fallback_model(sample_request):
    """Asserts that when the primary model is unavailable, OpenRouterClient cascades to the fallback model."""
    settings = LLMSettings(
        _env_file=None,
        OPENROUTER_API_KEY_1="sk-or-test-key-1",
        OPENROUTER_MODEL="retired/old-model:free",
        OPENROUTER_FALLBACK_MODELS=["nvidia/nemotron-3-super-120b-a12b:free"],
        LLM_REQUEST_TIMEOUT=5.0,
        LLM_MAX_RETRIES=2,
        LLM_BASE_BACKOFF_SEC=0.01,
    )
    models_called = []

    def or_handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        model = body.get("model")
        models_called.append(model)
        if model == "retired/old-model:free":
            return httpx.Response(404, json={"error": {"message": "Model 'retired/old-model:free' not found"}})
        if model == "nvidia/nemotron-3-super-120b-a12b:free":
            return httpx.Response(200, json=make_openrouter_payload("Served by fallback model.", model=model))
        return httpx.Response(500)

    client = OpenRouterClient(settings, httpx.AsyncClient(transport=httpx.MockTransport(or_handler)))
    response = await client.complete(sample_request)

    assert response.content == "Served by fallback model."
    assert response.model == "nvidia/nemotron-3-super-120b-a12b:free"
    assert models_called == ["retired/old-model:free", "nvidia/nemotron-3-super-120b-a12b:free"]


@pytest.mark.asyncio
async def test_all_openrouter_models_unavailable_cascades_to_groq(sample_request):
    """Asserts that when all configured OpenRouter models fail with ModelUnavailableError, manager cascades to Groq."""
    settings = LLMSettings(
        _env_file=None,
        OPENROUTER_API_KEY_1="sk-or-test-key",
        OPENROUTER_MODEL="unavailable-model-1",
        OPENROUTER_FALLBACK_MODELS=["unavailable-model-2"],
        GROQ_API_KEY="gsk_test_key",
        GROQ_MODEL="llama-3.3-70b-versatile",
        LLM_REQUEST_TIMEOUT=5.0,
        LLM_MAX_RETRIES=2,
        LLM_BASE_BACKOFF_SEC=0.01,
    )

    def or_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": {"message": "Model not found"}})

    def groq_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=make_groq_payload("Recovered via Groq."))

    or_client = OpenRouterClient(settings, httpx.AsyncClient(transport=httpx.MockTransport(or_handler)))
    groq_client = GroqClient(settings, httpx.AsyncClient(transport=httpx.MockTransport(groq_handler)))
    manager = LLMProviderManager(settings, or_client, groq_client)

    response = await manager.complete(sample_request)
    assert response.content == "Recovered via Groq."
    assert response.provider == "groq"
    assert response.metadata.get("fallback_from") == "openrouter"


@pytest.mark.asyncio
async def test_model_unavailable_without_groq_raises_descriptive_error(sample_request):
    """Asserts that when OpenRouter model is not found and Groq is unconfigured, a descriptive error is raised."""
    settings = LLMSettings(
        _env_file=None,
        OPENROUTER_API_KEY_1="sk-or-test-key",
        OPENROUTER_MODEL="nonexistent-model",
        OPENROUTER_FALLBACK_MODELS=[],
        GROQ_API_KEY=None,
        LLM_REQUEST_TIMEOUT=5.0,
        LLM_MAX_RETRIES=1,
    )

    def or_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": {"message": "No such model"}})

    or_client = OpenRouterClient(settings, httpx.AsyncClient(transport=httpx.MockTransport(or_handler)))
    groq_client = GroqClient(settings)
    manager = LLMProviderManager(settings, or_client, groq_client)

    with pytest.raises(AllProvidersUnavailableError) as exc_info:
        await manager.complete(sample_request)

    assert "Primary provider (OpenRouter) failed" in exc_info.value.message
    assert "nonexistent-model" in exc_info.value.message
    assert "unavailable or not found" in exc_info.value.message


def test_model_configuration_parsing():
    """Verify LLMSettings parses primary model and comma-separated fallback models."""
    settings = LLMSettings(
        _env_file=None,
        OPENROUTER_MODEL="custom/primary-model",
        OPENROUTER_FALLBACK_MODELS="model-fb-1, model-fb-2, model-fb-3",
    )
    assert settings.OPENROUTER_MODEL == "custom/primary-model"
    assert settings.OPENROUTER_FALLBACK_MODELS == ["model-fb-1", "model-fb-2", "model-fb-3"]


@pytest.mark.asyncio
async def test_llm_status_and_test_endpoints():
    """Verify /api/v1/integrations/llm/status and /api/v1/integrations/llm/test endpoints."""
    from backend.app.main import app
    from backend.app.api.v1.integrations import get_llm_manager

    settings = LLMSettings(
        _env_file=None,
        OPENROUTER_API_KEY_1="sk-or-test-secret-key-12345",
        OPENROUTER_MODEL="nvidia/nemotron-3-super-120b-a12b:free",
        OPENROUTER_FALLBACK_MODELS=["google/gemma-4-31b-it:free"],
        GROQ_API_KEY=None,
    )

    def or_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=make_openrouter_payload('{"status": "ok"}', model="nvidia/nemotron-3-super-120b-a12b:free"))

    mock_client = OpenRouterClient(settings, httpx.AsyncClient(transport=httpx.MockTransport(or_handler)))
    manager = LLMProviderManager(settings, openrouter_client=mock_client)

    app.dependency_overrides[get_llm_manager] = lambda: manager

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        # 1. Status endpoint
        status_resp = await ac.get("/api/v1/integrations/llm/status")
        assert status_resp.status_code == 200
        status_data = status_resp.json()
        assert status_data["primary_provider"] == "openrouter"
        assert status_data["primary_model"] == "nvidia/nemotron-3-super-120b-a12b:free"
        assert "sk-or-test-secret-key-12345" not in json.dumps(status_data)

        # 2. Test endpoint
        test_resp = await ac.post("/api/v1/integrations/llm/test")
        assert test_resp.status_code == 200
        test_data = test_resp.json()
        assert test_data["status"] == "connected"
        assert test_data["supports_structured_json"] is True
        assert "sk-or-test-secret-key-12345" not in json.dumps(test_data)

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_openrouter_upstream_rate_limit_cascades_without_key_cooldown(sample_request):
    """Asserts that upstream provider rate-limits on a model cascade to fallback models without key cooldown."""
    settings = LLMSettings(
        _env_file=None,
        OPENROUTER_API_KEY_1="sk-or-test-key",
        OPENROUTER_MODEL="google/gemma-4-26b-a4b-it:free",
        OPENROUTER_FALLBACK_MODELS=["nvidia/nemotron-3-super-120b-a12b:free"],
        GROQ_API_KEY=None,
        LLM_REQUEST_TIMEOUT=5.0,
        LLM_MAX_RETRIES=1,
    )

    def or_handler(request: httpx.Request) -> httpx.Response:
        data = json.loads(request.content)
        if data.get("model") == "google/gemma-4-26b-a4b-it:free":
            return httpx.Response(
                429,
                json={
                    "error": {
                        "message": "Provider returned error",
                        "code": 429,
                        "metadata": {
                            "raw": "google/gemma-4-26b-a4b-it:free is temporarily rate-limited upstream.",
                            "provider_name": "Google AI Studio",
                        },
                    }
                },
            )
        return httpx.Response(
            200,
            json=make_openrouter_payload("Cascade succeeded.", model="nvidia/nemotron-3-super-120b-a12b:free"),
        )

    client = OpenRouterClient(settings, httpx.AsyncClient(transport=httpx.MockTransport(or_handler)))
    resp = await client.complete(sample_request)
    assert resp.content == "Cascade succeeded."
    assert resp.model == "nvidia/nemotron-3-super-120b-a12b:free"
    # Ensure key slot is still healthy
    slot = client._key_slots[0]
    assert slot.status == "HEALTHY"


@pytest.mark.asyncio
async def test_openrouter_auth_error_with_configured_groq_falls_back(sample_request):
    """Asserts that when OpenRouter fails with AuthenticationError, Groq fallback is still attempted."""
    settings = LLMSettings(
        _env_file=None,
        OPENROUTER_API_KEY_1="sk-or-bad-key",
        GROQ_API_KEY="gsk_valid_key",
        GROQ_MODEL="openai/gpt-oss-120b",
        LLM_MAX_RETRIES=1,
    )

    def or_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "User not found."}})

    def groq_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=make_groq_payload("Groq recovered from 401.", model="openai/gpt-oss-120b"))

    or_client = OpenRouterClient(settings, httpx.AsyncClient(transport=httpx.MockTransport(or_handler)))
    groq_client = GroqClient(settings, httpx.AsyncClient(transport=httpx.MockTransport(groq_handler)))
    manager = LLMProviderManager(settings, or_client, groq_client)

    resp = await manager.complete(sample_request)
    assert resp.content == "Groq recovered from 401."
    assert resp.provider == "groq"
    assert resp.metadata.get("fallback_from") == "openrouter"


@pytest.mark.asyncio
async def test_groq_model_unavailable_cascades_to_fallback(sample_request):
    """Asserts that when primary Groq model returns 404, Groq cascades to fallback model."""
    settings = LLMSettings(
        _env_file=None,
        GROQ_API_KEY="gsk_valid_key",
        GROQ_MODEL="llama-3.3-70b-versatile",
        GROQ_FALLBACK_MODELS=["openai/gpt-oss-120b"],
        LLM_MAX_RETRIES=1,
    )

    def groq_handler(request: httpx.Request) -> httpx.Response:
        data = json.loads(request.content)
        if data.get("model") == "llama-3.3-70b-versatile":
            return httpx.Response(404, json={"error": {"message": "Model not found", "code": "model_not_found"}})
        return httpx.Response(200, json=make_groq_payload("Groq fallback model ok.", model="openai/gpt-oss-120b"))

    groq_client = GroqClient(settings, httpx.AsyncClient(transport=httpx.MockTransport(groq_handler)))
    resp = await groq_client.complete(sample_request)
    assert resp.content == "Groq fallback model ok."
    assert resp.model == "openai/gpt-oss-120b"


@pytest.mark.asyncio
async def test_both_providers_fail_returns_actionable_categorized_error(sample_request):
    """Asserts that when all providers fail, a categorized error with retry advice is returned."""
    settings = LLMSettings(
        _env_file=None,
        OPENROUTER_API_KEY_1="sk-or-key",
        GROQ_API_KEY="gsk_key",
        LLM_MAX_RETRIES=1,
    )

    def or_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"message": "Rate limit exceeded"}})

    def groq_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"message": "Rate limit exceeded"}})

    or_client = OpenRouterClient(settings, httpx.AsyncClient(transport=httpx.MockTransport(or_handler)))
    groq_client = GroqClient(settings, httpx.AsyncClient(transport=httpx.MockTransport(groq_handler)))
    manager = LLMProviderManager(settings, or_client, groq_client)

    with pytest.raises(AllProvidersUnavailableError) as exc_info:
        await manager.complete(sample_request)

    assert exc_info.value.category == "RATE_LIMIT_EXCEEDED"
    assert "retry" in exc_info.value.message.lower()
    assert "draft has been preserved" in exc_info.value.message.lower()


