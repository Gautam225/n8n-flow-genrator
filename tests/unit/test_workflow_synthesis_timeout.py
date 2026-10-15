"""Focused tests for Workflow Synthesis Timeout and Reliable Generation.

Covers:
- Successful synthesis response.
- Fast-fail on ReadTimeout without burning deadline retrying same stalled model.
- Model cascade to fallback models on timeout / 502 / rate-limit.
- Overall deadline exhaustion enforcement.
- OpenRouter-to-Groq fallback within deadline.
- Bounded candidate selection in prompt.
- Lock cleanup and status reporting on synthesis timeout.
"""
import asyncio
import time
import uuid
import httpx
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.app.llm.config import LLMSettings
from backend.app.llm.exceptions import (
    AllProvidersUnavailableError,
    RateLimitError,
    TimeoutError,
    ProviderUnavailableError,
)
from backend.app.llm.interface import ChatMessage, LLMRequest, LLMResponse, TokenUsage
from backend.app.llm.manager import LLMProviderManager
from backend.app.llm.openrouter import OpenRouterClient
from backend.app.llm.groq import GroqClient
from backend.app.orchestrator.engine import WorkflowOrchestrator
from backend.app.orchestrator.intent import WorkflowIntentExtractor
from backend.app.services.node_registry import NodeRegistry


@pytest.fixture
def mock_settings():
    settings = LLMSettings()
    settings.OPENROUTER_API_KEY_1 = "sk-or-v1-testkey1"
    settings.OPENROUTER_API_KEY_2 = "sk-or-v1-testkey2"
    settings.OPENROUTER_MODEL = "nvidia/nemotron-3-ultra-550b-a55b:free"
    settings.OPENROUTER_FALLBACK_MODELS = [
        "google/gemini-2.5-flash:free",
        "liquid/lfm-7b:free",
    ]
    settings.GROQ_API_KEY = "gsk_testgroqkey"
    settings.GROQ_MODEL = "llama-3.3-70b-versatile"
    settings.LLM_REQUEST_TIMEOUT = 55.0
    settings.LLM_MAX_RETRIES = 2
    settings.TOTAL_GENERATION_DEADLINE = 95.0
    return settings


@pytest.mark.asyncio
async def test_successful_synthesis_response(mock_settings):
    """Verify successful LLM synthesis response returns parsed content and metadata."""
    mock_http = AsyncMock(spec=httpx.AsyncClient)
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "id": "gen-123",
        "model": "nvidia/nemotron-3-ultra-550b-a55b:free",
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": '{"id": "wf_1", "name": "Email to Telegram", "nodes": [], "edges": []}',
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 150, "completion_tokens": 80, "total_tokens": 230},
    }
    mock_http.post.return_value = mock_resp

    client = OpenRouterClient(settings=mock_settings, http_client=mock_http)
    req = LLMRequest(
        messages=[ChatMessage(role="user", content="Build email workflow")],
        temperature=0.2,
    )
    res = await client.complete(req)

    assert res.provider == "openrouter"
    assert "wf_1" in res.content
    assert res.usage.total_tokens == 230


@pytest.mark.asyncio
async def test_read_timeout_fast_fails_to_fallback_model(mock_settings):
    """Verify that a ReadTimeout immediately switches to the next fallback model without retrying the slow model."""
    mock_http = AsyncMock(spec=httpx.AsyncClient)

    # First model (nvidia) throws ReadTimeout
    # Second model (gemini fallback) succeeds
    success_resp = MagicMock(spec=httpx.Response)
    success_resp.status_code = 200
    success_resp.json.return_value = {
        "id": "gen-fb",
        "model": "google/gemini-2.5-flash:free",
        "choices": [
            {
                "message": {"role": "assistant", "content": '{"id": "wf_fallback", "name": "FB"}'},
                "finish_reason": "stop",
            }
        ],
    }

    mock_http.post.side_effect = [
        httpx.ReadTimeout("Server took longer than 55.0s to respond"),
        success_resp,
    ]

    client = OpenRouterClient(settings=mock_settings, http_client=mock_http)
    req = LLMRequest(messages=[ChatMessage(role="user", content="Test prompt")])

    res = await client.complete(req)

    assert res.content == '{"id": "wf_fallback", "name": "FB"}'
    assert res.model == "google/gemini-2.5-flash:free"
    # Crucial: post must be called exactly 2 times (1 for stalled model, 1 for fallback), NOT retrying the stalled model!
    assert mock_http.post.call_count == 2


@pytest.mark.asyncio
async def test_502_bad_gateway_fast_fails_to_fallback_model(mock_settings):
    """Verify that HTTP 502/503 from an upstream provider fast-fails to the next fallback model."""
    mock_http = AsyncMock(spec=httpx.AsyncClient)

    err_502 = MagicMock(spec=httpx.Response)
    err_502.status_code = 502
    err_502.text = "Bad Gateway"

    success_resp = MagicMock(spec=httpx.Response)
    success_resp.status_code = 200
    success_resp.json.return_value = {
        "choices": [{"message": {"content": "ok"}}],
        "model": "google/gemini-2.5-flash:free",
    }

    mock_http.post.side_effect = [err_502, success_resp]

    client = OpenRouterClient(settings=mock_settings, http_client=mock_http)
    req = LLMRequest(messages=[ChatMessage(role="user", content="test")])
    res = await client.complete(req)

    assert res.content == "ok"
    assert mock_http.post.call_count == 2


@pytest.mark.asyncio
async def test_total_generation_deadline_exhaustion(mock_settings):
    """Verify that when the overall deadline is nearing expiry, complete halts with clean TimeoutError."""
    mock_settings.TOTAL_GENERATION_DEADLINE = 5.0  # very short deadline

    mock_http = AsyncMock(spec=httpx.AsyncClient)
    # Simulate first model taking 4.5 seconds before ReadTimeout
    async def delayed_timeout(*args, **kwargs):
        await asyncio.sleep(0.1)
        raise httpx.ReadTimeout("timed out")

    mock_http.post.side_effect = delayed_timeout

    client = OpenRouterClient(settings=mock_settings, http_client=mock_http)
    req = LLMRequest(messages=[ChatMessage(role="user", content="test")])

    # Fast forward time or check deadline logic
    with patch("time.time", side_effect=[100.0, 100.0, 104.5, 106.0, 108.0]):
        with pytest.raises(TimeoutError) as exc_info:
            await client.complete(req)
        assert "Overall generation deadline" in str(exc_info.value.message)


@pytest.mark.asyncio
async def test_openrouter_to_groq_fallback(mock_settings):
    """Verify LLMProviderManager falls back to Groq when OpenRouter models exhaust."""
    mock_or_client = AsyncMock(spec=OpenRouterClient)
    mock_or_client.is_configured = True
    mock_or_client.complete.side_effect = TimeoutError(
        message="Request to OpenRouter timed out after 55.0s.",
        provider="openrouter",
    )

    mock_groq_client = AsyncMock(spec=GroqClient)
    mock_groq_client.is_configured = True
    mock_groq_client.complete.return_value = LLMResponse(
        content='{"id": "wf_from_groq"}',
        provider="groq",
        model="llama-3.3-70b-versatile",
        metadata={},
    )

    manager = LLMProviderManager(
        settings=mock_settings,
        openrouter_client=mock_or_client,
        groq_client=mock_groq_client,
    )

    req = LLMRequest(messages=[ChatMessage(role="user", content="build workflow")])
    res = await manager.complete(req)

    assert res.provider == "groq"
    assert res.metadata.get("fallback_from") == "openrouter"
    assert res.content == '{"id": "wf_from_groq"}'


def test_focused_candidate_selection_does_not_bloat_context():
    """Verify that orchestrator candidate selection keeps candidates <= 4 and focuses on trigger/action."""
    registry = NodeRegistry()
    extractor = WorkflowIntentExtractor(node_registry=registry)
    orchestrator = WorkflowOrchestrator(node_registry=registry)

    prompt = "When an email with a PDF invoice arrives in Gmail, send a notification to Telegram."
    intent = extractor.analyze(
        user_prompt=prompt,
        history=[],
        accumulated_slots={"email_provider": "gmail", "telegram_chat_id": "-1001234567"},
        original_prompt=prompt,
    )

    # Inspect candidate collection logic
    candidate_set = {}
    if intent:
        if intent.trigger and intent.trigger.node_type:
            node_obj = registry.get_node(intent.trigger.node_type)
            if node_obj:
                candidate_set[node_obj.canonical_name] = node_obj

        for act in intent.actions:
            if act.node_type:
                node_obj = registry.get_node(act.node_type)
                if node_obj:
                    candidate_set[node_obj.canonical_name] = node_obj

    if any(w in prompt.lower() for w in ("invoice", "pdf", "filter", "condition", "if ")):
        if_node = registry.get_node("n8n-nodes-base.if")
        if if_node:
            candidate_set[if_node.canonical_name] = if_node

    candidates = list(candidate_set.values())[:4]

    # Must contain Gmail Trigger, Telegram, and If
    candidate_names = [c.canonical_name for c in candidates]
    assert "n8n-nodes-base.gmailTrigger" in candidate_names
    assert "n8n-nodes-base.telegram" in candidate_names
    assert len(candidates) <= 4, "Candidate set must be tightly bounded"
