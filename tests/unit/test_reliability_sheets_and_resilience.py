"""Targeted unit tests for Google Sheets canonicalization, OpenRouter empty choices, and registry caching."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.app.orchestrator.intent import (
    canonicalize_slot_key,
    extract_spreadsheet_info,
)
from backend.app.services.node_registry import NodeRegistry
from backend.app.llm.openrouter import OpenRouterClient
from backend.app.llm.exceptions import ProviderUnavailableError
from backend.app.llm.interface import ChatMessage, LLMRequest


def test_extract_spreadsheet_info_standard_url():
    """Verify standard Google Sheets URL extracts document ID and tab name."""
    url = "https://docs.google.com/spreadsheets/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms/edit?gid=123#gid=123"
    doc_id, tab_name = extract_spreadsheet_info(url)
    assert doc_id == "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms"
    assert tab_name == "123"


def test_extract_spreadsheet_info_multi_account_url():
    """Verify multi-account /u/0/ Google Sheets URL extracts document ID."""
    url = "https://docs.google.com/spreadsheets/u/0/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms/edit"
    doc_id, tab_name = extract_spreadsheet_info(url)
    assert doc_id == "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms"


def test_extract_spreadsheet_info_raw_id():
    """Verify standalone spreadsheet ID string is recognized."""
    raw_id = "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms"
    doc_id, tab_name = extract_spreadsheet_info(raw_id)
    assert doc_id == raw_id


def test_extract_spreadsheet_info_short_string_not_id():
    """Verify regular non-ID text is not mistakenly identified as a spreadsheet ID."""
    doc_id, tab_name = extract_spreadsheet_info("LeadTrackerSheet")
    assert doc_id is None


def test_canonicalize_slot_key_synonyms():
    """Verify various aliases map to canonical document and sheet name slot keys."""
    assert canonicalize_slot_key("spreadsheet_url") == "google_sheets_document"
    assert canonicalize_slot_key("spreadsheet_id") == "google_sheets_document"
    assert canonicalize_slot_key("sheet_url") == "google_sheets_document"
    assert canonicalize_slot_key("sheet_id") == "google_sheets_document"
    assert canonicalize_slot_key("sheet_name") == "google_sheets_sheet_name"
    assert canonicalize_slot_key("tab_name") == "google_sheets_sheet_name"
    assert canonicalize_slot_key("chat_id") == "telegram_chat_id"


def test_node_registry_singleton_catalog_caching():
    """Verify NodeRegistry reuses the class-level index cache without reloading."""
    reg1 = NodeRegistry()
    node_count_1 = len(reg1.list_nodes())
    assert node_count_1 > 0
    assert NodeRegistry._DEFAULT_INDEXES is not None

    # Instantiate another registry instance
    reg2 = NodeRegistry()
    assert reg2._nodes_by_canonical == reg1._nodes_by_canonical
    assert len(reg2.list_nodes()) == node_count_1


from backend.app.llm.config import LLMSettings


def test_openrouter_empty_choices_raises_provider_unavailable():
    """Verify OpenRouter raising ProviderUnavailableError on empty choices or blank content."""
    settings = LLMSettings(OPENROUTER_API_KEY_1="sk-or-test-mock")
    client = OpenRouterClient(settings=settings)
    
    # 1. Empty choices array
    with pytest.raises(ProviderUnavailableError) as exc_info:
        client._parse_success_response({"choices": []}, "test-model", "key_1", 0.5)
    assert "empty choices array" in str(exc_info.value).lower()

    # 2. Blank content string
    with pytest.raises(ProviderUnavailableError) as exc_blank:
        client._parse_success_response(
            {"choices": [{"message": {"content": "   "}}]},
            "test-model",
            "key_1",
            0.5,
        )
    assert "blank message content" in str(exc_blank.value).lower()


@pytest.mark.asyncio
async def test_openrouter_complete_bounds_fallback_on_empty_choices():
    """Verify OpenRouter attempts at most 2 model attempts and does not hang indefinitely."""
    settings = LLMSettings(
        OPENROUTER_API_KEY_1="sk-or-test-mock",
        OPENROUTER_FALLBACK_MODELS=["fb-1", "fb-2", "fb-3", "fb-4", "fb-5"],
    )
    client = OpenRouterClient(settings=settings)
    req = LLMRequest(
        messages=[ChatMessage(role="user", content="hello")],
        model="primary-free-model",
    )

    attempt_count = 0

    async def mock_complete_with_model(request, model, remaining_deadline=None):
        nonlocal attempt_count
        attempt_count += 1
        raise ProviderUnavailableError(
            message="OpenRouter returned empty choices array.",
            provider="openrouter",
        )

    with patch.object(client, "_complete_with_model", side_effect=mock_complete_with_model):
        with pytest.raises(ProviderUnavailableError) as exc:
            await client.complete(req)
        assert "empty choices array" in str(exc.value).lower()
        # Strictly bounded to at most 2 attempts (primary + 1 fallback)
        assert attempt_count == 2

