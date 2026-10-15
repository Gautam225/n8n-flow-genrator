"""Targeted Unit Tests for Phase 2: Dynamic Requirements Discovery, Consolidated Clarification, and Real Stage Reporting."""
import json
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock

from backend.app.llm.interface import LLMResponse, TokenUsage
from backend.app.llm.manager import LLMProviderManager
from backend.app.models.conversation import Conversation, ConversationMessage
from backend.app.orchestrator.engine import WorkflowOrchestrator
from backend.app.orchestrator.intent import WorkflowIntentExtractor
from backend.app.orchestrator.schemas import ClarificationAnswerItem
from backend.app.orchestrator.state_machine import ConversationState
from backend.app.services.node_registry import NodeRegistry
from tests.unit.test_intent_planner import MockAsyncSession


@pytest.fixture
def node_registry():
    return NodeRegistry()


@pytest.fixture
def intent_extractor(node_registry):
    return WorkflowIntentExtractor(node_registry=node_registry)


def test_different_requests_produce_different_requirement_sets(intent_extractor):
    """Verify that different requests dynamically discover their own service-specific requirements."""
    # 1. Google Sheets -> Telegram
    intent1 = intent_extractor.analyze(
        user_prompt="When a new row is added to Google Sheets, send me a Telegram message.",
        history=[],
        accumulated_slots={},
    )
    q_keys_1 = [q.field_key for q in intent1.clarification_questions]
    assert "google_sheets_document" in q_keys_1
    assert "telegram_chat_id" in q_keys_1
    assert "slack_channel" not in q_keys_1
    assert "email_provider" not in q_keys_1

    # 2. Webhook -> Slack
    intent2 = intent_extractor.analyze(
        user_prompt="Listen for incoming webhook POST requests and post alert to Slack.",
        history=[],
        accumulated_slots={},
    )
    q_keys_2 = [q.field_key for q in intent2.clarification_questions]
    assert "slack_channel" in q_keys_2
    assert "google_sheets_document" not in q_keys_2
    assert "telegram_chat_id" not in q_keys_2

    # 3. Email -> Telegram
    intent3 = intent_extractor.analyze(
        user_prompt="Forward new incoming emails to my Telegram.",
        history=[],
        accumulated_slots={},
    )
    q_keys_3 = [q.field_key for q in intent3.clarification_questions]
    assert "email_provider" in q_keys_3
    assert "telegram_chat_id" in q_keys_3
    assert "google_sheets_document" not in q_keys_3


def test_google_sheets_to_telegram_dynamic_extraction_and_mapping(intent_extractor):
    """Verify extraction of Google Sheets trigger, Telegram action, and column data mappings."""
    prompt = "Whenever a new row is added to my Google Sheet, send me a Telegram message containing the person's name, email, and phone number."
    intent = intent_extractor.analyze(
        user_prompt=prompt,
        history=[],
        accumulated_slots={},
    )

    # Required questions should be consolidated together
    q_map = {q.field_key: q for q in intent.clarification_questions}
    assert "google_sheets_document" in q_map
    assert "telegram_chat_id" in q_map

    # Inspect Google Sheets question schema
    gs_q = q_map["google_sheets_document"]
    assert gs_q.group == "Trigger: Google Sheets"
    assert gs_q.input_type == "url"
    assert gs_q.validation_rules.get("format") == "url_or_id"
    assert gs_q.required is True

    # Inspect Telegram question schema
    tg_q = q_map["telegram_chat_id"]
    assert tg_q.group == "Action: Telegram Alert"
    assert tg_q.input_type == "single_select"
    assert tg_q.required is True
    assert any(opt.value == "private_chat" for opt in tg_q.options)

    # Check extracted data mappings for name, email, phone
    from_fields = [m["from"] for m in intent.data_mappings]
    assert "sheets.name" in from_fields
    assert "sheets.email" in from_fields
    assert any("phone" in f for f in from_fields)


def test_already_supplied_answers_are_not_asked_again(intent_extractor):
    """Verify that if the user supplies document URL or Telegram Chat ID in prompt or slots, they are not asked again."""
    # 1. User provides Google Spreadsheet URL in the prompt
    prompt_with_url = (
        "When a new row is added to https://docs.google.com/spreadsheets/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms/edit, "
        "send me a message on Telegram."
    )
    intent1 = intent_extractor.analyze(
        user_prompt=prompt_with_url,
        history=[],
        accumulated_slots={},
    )
    q_keys_1 = [q.field_key for q in intent1.clarification_questions]
    # Document is already extracted! Must NOT be asked again
    assert "google_sheets_document" not in q_keys_1
    assert "telegram_chat_id" in q_keys_1
    assert intent1.completed_answers.get("google_sheets_document") == "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms"

    # 2. User provides Telegram Chat ID in prompt
    prompt_with_chat_id = "When a new row is added to Google Sheets, send Telegram notification to chat 123456789."
    intent2 = intent_extractor.analyze(
        user_prompt=prompt_with_chat_id,
        history=[],
        accumulated_slots={},
    )
    q_keys_2 = [q.field_key for q in intent2.clarification_questions]
    assert "telegram_chat_id" not in q_keys_2
    assert "google_sheets_document" in q_keys_2
    assert intent2.completed_answers.get("telegram_chat_id") == "123456789"

    # 3. User provides both in accumulated slots
    intent3 = intent_extractor.analyze(
        user_prompt="When a new row is added to Google Sheets, send Telegram notification.",
        history=[],
        accumulated_slots={
            "google_sheets_document": "test_sheet_id",
            "telegram_chat_id": "987654321",
        },
    )
    assert len(intent3.clarification_questions) == 0


@pytest.mark.asyncio
async def test_telegram_bot_username_rejected_with_honest_error():
    """Verify that providing a bot username ending in 'bot' fails validation with actionable advice."""
    conv_id = str(uuid.uuid4())
    conv = Conversation(
        id=conv_id,
        title="Test Sheets to Telegram",
        metadata_json={
            "state": ConversationState.CLARIFYING.value,
            "slots": {},
            "original_prompt": "When a new row is added to Google Sheets, send Telegram notification.",
            "clarification": {
                "questions": [
                    {
                        "id": "telegram_chat_id",
                        "field_key": "telegram_chat_id",
                        "question": "Where should the Telegram notification be sent?",
                    },
                    {
                        "id": "google_sheets_document",
                        "field_key": "google_sheets_document",
                        "question": "Spreadsheet URL",
                    },
                ]
            },
        },
    )
    mock_llm = MagicMock(spec=LLMProviderManager)
    orchestrator = WorkflowOrchestrator(llm_manager=mock_llm)
    session = MockAsyncSession(conversation=conv, messages=[])

    with pytest.raises(ValueError) as excinfo:
        await orchestrator.execute_turn(
            conversation_id=conv_id,
            user_message_text="",
            db=session,
            clarification_answers=[
                ClarificationAnswerItem(
                    question_id="telegram_chat_id",
                    field_key="telegram_chat_id",
                    selected_value="other",
                    custom_text="@MyAlerts_bot",
                ),
            ],
        )

    assert "Bot usernames ending in 'bot'" in str(excinfo.value)


@pytest.mark.asyncio
async def test_active_stage_tracking_and_cleanup():
    """Verify that stage updates are tracked live during turn execution and cleared in finally."""
    orchestrator = WorkflowOrchestrator()
    conv_id = "test-live-stage-conv"

    assert orchestrator.get_active_stage(conv_id) is None

    orchestrator.set_active_stage(conv_id, "understanding", "Analyzing user prompt...")
    active_info = orchestrator.get_active_stage(conv_id)
    assert active_info is not None
    assert active_info["is_active"] is True
    assert active_info["stage"] == "understanding"
    assert active_info["message"] == "Analyzing user prompt..."
    assert active_info["elapsed_seconds"] >= 0.0

    orchestrator.set_active_stage(conv_id, "planning", "Discovering installed nodes from registry...")
    updated_info = orchestrator.get_active_stage(conv_id)
    assert updated_info["stage"] == "planning"

    orchestrator.clear_active_stage(conv_id)
    assert orchestrator.get_active_stage(conv_id) is None


@pytest.mark.asyncio
async def test_duplicate_turn_execution_blocked():
    """Verify that concurrent turn execution for the same conversation is immediately rejected."""
    orchestrator = WorkflowOrchestrator()
    conv_id = "test-dup-turn-conv"
    orchestrator._active_conversations.add(conv_id)

    session = MockAsyncSession(conversation=Conversation(id=conv_id, title="Test"), messages=[])

    with pytest.raises(ValueError) as exc:
        await orchestrator.execute_turn(
            conversation_id=conv_id,
            user_message_text="Hello",
            db=session,
        )

    assert "already in progress" in str(exc.value)
    orchestrator._active_conversations.discard(conv_id)
