"""Focused tests for Reliability Fix: Clarification Deduplication, Lock Cleanup, Concurrency, and Stale Lock Recovery."""
import asyncio
import time
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock

from backend.app.llm.interface import LLMResponse, TokenUsage
from backend.app.models.conversation import Conversation, ConversationMessage
from backend.app.orchestrator.engine import WorkflowOrchestrator, ActiveTurnLock
from backend.app.orchestrator.intent import WorkflowIntentExtractor
from backend.app.orchestrator.schemas import (
    ClarificationAnswerItem,
    ClarificationOption,
    ClarificationPlan,
    ClarificationQuestion,
)
from backend.app.orchestrator.state_machine import ConversationState
from backend.app.services.node_registry import NodeRegistry
from tests.unit.test_intent_planner import MockAsyncSession


@pytest.fixture
def node_registry():
    return NodeRegistry()


@pytest.fixture
def intent_extractor(node_registry):
    return WorkflowIntentExtractor(node_registry=node_registry)


def test_clarification_questions_are_not_duplicated_and_have_stable_ids(intent_extractor):
    """Verify that email to Telegram workflow questions are deduplicated across triggers and actions."""
    prompt = "Forward new incoming emails to my Telegram."
    intent = intent_extractor.analyze(
        user_prompt=prompt,
        history=[],
        accumulated_slots={},
    )
    # Check that questions list has unique IDs and field keys
    q_ids = [q.id for q in intent.clarification_questions]
    q_keys = [q.field_key for q in intent.clarification_questions]
    assert len(q_ids) == len(set(q_ids)), "Question IDs must be strictly unique"
    assert len(q_keys) == len(set(q_keys)), "Field keys must be strictly unique"

    # Both email_provider and telegram_chat_id should be present once
    assert "email_provider" in q_keys
    assert "telegram_chat_id" in q_keys
    assert q_keys.count("email_provider") == 1
    assert q_keys.count("telegram_chat_id") == 1


def test_distinct_questions_with_similar_labels_remain_distinct(intent_extractor):
    """Verify that two questions with similar labels/categories retain distinct unique IDs."""
    q1 = ClarificationQuestion(
        id="q_source_email",
        question="Which email account should we monitor?",
        field_key="source_email",
        group="Trigger: Email",
        required=True,
    )
    q2 = ClarificationQuestion(
        id="q_destination_email",
        question="Which email account should receive reports?",
        field_key="dest_email",
        group="Action: Email",
        required=True,
    )

    seen = set()
    deduped = []
    for q in [q1, q2]:
        key = q.id or q.field_key
        if key not in seen:
            seen.add(key)
            deduped.append(q)

    assert len(deduped) == 2
    assert deduped[0].id == "q_source_email"
    assert deduped[1].id == "q_destination_email"
    assert deduped[0].group != deduped[1].group


def test_stale_lock_discarded_after_timeout():
    """Verify that an ActiveTurnLock exceeding timeout is considered stale and automatically discarded."""
    orchestrator = WorkflowOrchestrator()
    conv_id = "test-stale-conv"

    stale_lock = ActiveTurnLock(
        request_id=str(uuid.uuid4()),
        conversation_id=conv_id,
        started_at=time.time() - 300,
        updated_at=time.time() - 300,
        current_stage="planning",
        stage_message="Processing...",
    )
    orchestrator._active_locks[conv_id] = stale_lock

    assert stale_lock.is_stale(timeout_seconds=120.0) is True
    # is_turn_active should clean it up and return False
    assert orchestrator.is_turn_active(conv_id) is False
    assert conv_id not in orchestrator._active_locks


def test_completed_task_lock_is_stale():
    """Verify that if the asyncio Task associated with a lock has completed, is_stale returns True."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        async def dummy():
            return 42

        task = loop.create_task(dummy())
        loop.run_until_complete(task)
        # task is now done
        assert task.done() is True
        lock = ActiveTurnLock(
            request_id=str(uuid.uuid4()),
            conversation_id="conv-done",
            started_at=time.time(),
            updated_at=time.time(),
            task=task,
        )
        assert lock.is_stale() is True
    finally:
        loop.close()


def test_two_different_conversations_can_generate_independently():
    """Verify that an active turn on conversation A does not block conversation B."""
    orchestrator = WorkflowOrchestrator()
    conv_a = "conv-alpha"
    conv_b = "conv-beta"

    orchestrator.set_active_stage(conv_a, "planning", "Planning alpha...")

    assert orchestrator.is_turn_active(conv_a) is True
    assert orchestrator.is_turn_active(conv_b) is False

    # Setting stage on beta works without interference
    orchestrator.set_active_stage(conv_b, "building", "Building beta...")
    assert orchestrator.is_turn_active(conv_b) is True

    # Clearing alpha leaves beta active
    orchestrator.clear_active_stage(conv_a)
    assert orchestrator.is_turn_active(conv_a) is False
    assert orchestrator.is_turn_active(conv_b) is True

    orchestrator.clear_active_stage(conv_b)
    assert orchestrator.is_turn_active(conv_b) is False


@pytest.mark.asyncio
async def test_lock_released_on_llm_failure():
    """Verify that an unexpected exception or LLM failure reliably clears the active turn lock."""
    orchestrator = WorkflowOrchestrator()
    conv_id = f"test-fail-lock-{uuid.uuid4()}"

    # Mock intent extractor to raise an unexpected runtime error
    orchestrator.intent_extractor.analyze = MagicMock(side_effect=RuntimeError("AI Provider Connection Reset"))

    session = MockAsyncSession(
        conversation=Conversation(id=conv_id, title="Test Fail", metadata_json={"state": "planning", "slots": {}}),
        messages=[],
    )

    with pytest.raises(RuntimeError):
        await orchestrator.execute_turn(
            conversation_id=conv_id,
            user_message_text="Create a workflow",
            db=session,
        )

    # Lock must be released in finally block!
    assert orchestrator.is_turn_active(conv_id) is False
    assert conv_id not in orchestrator._active_locks
    assert conv_id not in orchestrator._active_stages


def test_telegram_chat_id_in_original_request_is_recognized_and_not_asked_again(intent_extractor):
    """Verify that a Telegram chat ID provided in the original request is extracted and never re-asked."""
    prompt = "Forward incoming emails to Telegram. My Telegram chat ID is 8716438750."
    intent = intent_extractor.analyze(
        user_prompt=prompt,
        history=[],
        accumulated_slots={},
    )
    assert intent.completed_answers.get("telegram_chat_id") == "8716438750"
    q_keys = [q.field_key for q in intent.clarification_questions]
    assert "telegram_chat_id" not in q_keys
    # Only email_provider should be asked
    assert "email_provider" in q_keys


def test_natural_language_answers_in_history_recognized(intent_extractor):
    """Verify that natural language answers provided across conversation history are recognized."""
    orig_prompt = "When a new row is added in Google Sheets, send a notification on Telegram."
    history = [
        ConversationMessage(id="1", conversation_id="c1", role="user", content=orig_prompt),
        ConversationMessage(id="2", conversation_id="c1", role="assistant", content="What is your sheet and chat ID?"),
        ConversationMessage(id="3", conversation_id="c1", role="user", content="My sheet is https://docs.google.com/spreadsheets/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms/edit and chat ID is -1001234567890"),
    ]
    intent = intent_extractor.analyze(
        user_prompt="I have provided the sheet and chat ID above.",
        history=history,
        accumulated_slots={},
        original_prompt=orig_prompt,
    )
    assert intent.completed_answers.get("google_sheets_document") == "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms"
    assert intent.completed_answers.get("telegram_chat_id") == "-1001234567890"
    assert len(intent.clarification_questions) == 0
    assert intent.is_clarification_needed is False


def test_multiple_missing_integration_fields_asked_together(intent_extractor):
    """Verify that multiple missing fields across integrations are requested in a single clarification round."""
    prompt = "When a new row is added in Google Sheets, send a notification on Telegram."
    intent = intent_extractor.analyze(
        user_prompt=prompt,
        history=[],
        accumulated_slots={},
    )
    q_keys = [q.field_key for q in intent.clarification_questions]
    # Both google_sheets_document and telegram_chat_id must be asked together in one batch
    assert "google_sheets_document" in q_keys
    assert "telegram_chat_id" in q_keys
    assert len(intent.clarification_questions) >= 2


def test_bot_usernames_ending_in_bot_rejected():
    """Verify that bot usernames ending in 'bot' are strictly rejected with an informative error."""
    orchestrator = WorkflowOrchestrator()
    conv_id = f"test-bot-check-{uuid.uuid4()}"
    session = MockAsyncSession(
        conversation=Conversation(
            id=conv_id,
            title="Bot Check",
            metadata_json={"state": "clarifying", "slots": {}, "original_prompt": "Send email to Telegram"},
        ),
        messages=[],
    )

    with pytest.raises(ValueError, match="Bot usernames ending in 'bot' cannot receive messages"):
        asyncio.run(
            orchestrator.execute_turn(
                conversation_id=conv_id,
                user_message_text="",
                selected_options={"telegram_chat_id": "@MyCoolAlertBot"},
                db=session,
            )
        )


def test_canonical_synonyms_normalize_and_prevent_duplicate_questions(intent_extractor):
    """Verify that synonym keys like 'chat_id' or 'spreadsheet_id' normalize and prevent duplicate questions."""
    intent = intent_extractor.analyze(
        user_prompt="Send rows to Telegram",
        history=[],
        accumulated_slots={
            "chat_id": "8716438750",
            "spreadsheet_id": "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms",
        },
        original_prompt="When a new row is added in Google Sheets, send to Telegram",
    )
    assert intent.completed_answers.get("telegram_chat_id") == "8716438750"
    assert intent.completed_answers.get("google_sheets_document") == "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms"
    q_keys = [q.field_key for q in intent.clarification_questions]
    assert "telegram_chat_id" not in q_keys
    assert "google_sheets_document" not in q_keys

