"""Unit tests for the Workflow Orchestrator engine."""
import json
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock

from backend.app.llm.interface import ChatMessage, LLMRequest, LLMResponse, TokenUsage
from backend.app.llm.manager import LLMProviderManager
from backend.app.models.conversation import Conversation, ConversationMessage
from backend.app.orchestrator.engine import WorkflowOrchestrator
from backend.app.orchestrator.state_machine import ConversationState
from backend.app.orchestrator.intent import WorkflowIntent
from backend.app.schemas.ir import IRNode, IREdge, NodePosition, WorkflowIR
from backend.app.services.compiler import WorkflowCompiler
from backend.app.services.node_registry import NodeRegistry
from backend.app.services.validator import WorkflowValidator


class MockAsyncSession:
    """Mock async database session for unit testing orchestrator turns."""

    def __init__(self, conversation: Conversation, messages: list):
        self.conversation = conversation
        self.messages = messages
        self.added = []

    async def execute(self, stmt):
        mock_res = MagicMock()
        stmt_str = str(stmt).lower()
        if "from conversations" in stmt_str:
            mock_res.scalar_one_or_none.return_value = self.conversation
        elif "from conversation_messages" in stmt_str:
            mock_res.scalars.return_value.all.return_value = self.messages
        elif "from workflow_drafts" in stmt_str:
            mock_res.scalar_one_or_none.return_value = None
        elif "from workflow_revisions" in stmt_str:
            mock_res.scalars.return_value.all.return_value = []
        return mock_res

    def add(self, entity):
        self.added.append(entity)

    async def flush(self):
        pass

    async def commit(self):
        pass

    async def refresh(self, entity):
        pass


@pytest.mark.asyncio
async def test_orchestrator_clarification_flow():
    """Verify orchestrator requests clarifications when prompt is missing required information."""
    conv_id = str(uuid.uuid4())
    conv = Conversation(
        id=conv_id,
        title="Ambiguous Flow",
        metadata_json={"state": None, "slots": {}},
    )

    # Mock LLM returning clarification questions
    mock_llm = MagicMock(spec=LLMProviderManager)
    clarification_json = {
        "has_ambiguities": True,
        "questions": [
            {
                "id": "trigger_type",
                "question": "How should this automation be triggered?",
                "field_key": "trigger",
                "is_required": True,
                "default_value": "schedule",
                "options": [
                    {"label": "On a Schedule", "value": "schedule"},
                    {"label": "Via Webhook", "value": "webhook"},
                ],
            }
        ],
    }
    mock_llm.complete = AsyncMock(
        return_value=LLMResponse(
            content=json.dumps(clarification_json),
            usage=TokenUsage(),
            provider="openrouter",
            model="test-model",
            finish_reason="stop",
            key_alias="OPENROUTER_KEY_1",
        )
    )

    mock_intent_extractor = MagicMock()
    mock_intent_extractor.analyze.return_value = WorkflowIntent(
        summary="Send data to Slack",
        is_clarification_needed=False,
        original_prompt="Send data to Slack",
        completed_answers={},
    )
    orchestrator = WorkflowOrchestrator(llm_manager=mock_llm, intent_extractor=mock_intent_extractor)
    session = MockAsyncSession(conversation=conv, messages=[])

    result = await orchestrator.execute_turn(
        conversation_id=conv_id,
        user_message_text="Send data to Slack",
        db=session,
    )

    assert result.state == ConversationState.CLARIFYING
    assert result.clarification is not None
    assert result.clarification.has_ambiguities is True
    assert len(result.clarification.questions) == 1
    assert "How should this automation be triggered?" in result.assistant_message


@pytest.mark.asyncio
async def test_orchestrator_workflow_generation_flow():
    """Verify orchestrator successfully plans, generates, compiles, and validates a clean workflow."""
    conv_id = str(uuid.uuid4())
    conv = Conversation(
        id=conv_id,
        title="Hourly Slack Sync",
        metadata_json={"state": ConversationState.PLANNING.value, "slots": {}},
    )

    valid_ir_dict = {
        "id": "wf_test_1",
        "name": "Hourly Slack Sync",
        "nodes": [
            {
                "id": "node_schedule",
                "name": "Schedule Trigger",
                "node_type": "n8n-nodes-base.scheduleTrigger",
                "type_version": 1.2,
                "position": {"x": 250, "y": 300},
                "parameters": {"rule": {"interval": [{"field": "hours", "hoursInterval": 1}]}},
            },
            {
                "id": "node_slack",
                "name": "Slack Alert",
                "node_type": "n8n-nodes-base.slack",
                "type_version": 2.2,
                "position": {"x": 450, "y": 300},
                "parameters": {"channel": "#general", "text": "Hourly check"},
            },
        ],
        "edges": [
            {"source_id": "node_schedule", "target_id": "node_slack"}
        ],
    }

    mock_llm = MagicMock(spec=LLMProviderManager)

    async def mock_complete(req: LLMRequest) -> LLMResponse:
        # First call is requirements evaluation
        if "Requirements Analysis Engine" in req.messages[0].content:
            content = json.dumps({"has_ambiguities": False, "questions": []})
        elif "Architectural Workflow Planner" in req.messages[0].content:
            content = json.dumps({
                "title": "Hourly Slack Sync",
                "objective": "Hourly check",
                "target_services": ["slack"],
                "nodes": [
                    {"id": "node_schedule", "name": "Schedule Trigger", "node_type": "n8n-nodes-base.scheduleTrigger", "role": "trigger"},
                    {"id": "node_slack", "name": "Slack Alert", "node_type": "n8n-nodes-base.slack", "role": "action"}
                ],
                "connections": [
                    {"source_id": "node_schedule", "target_id": "node_slack"}
                ],
                "error_handling_strategy": "continue_or_alert"
            })
        else:
            # Workflow IR generation
            content = json.dumps(valid_ir_dict)

        return LLMResponse(
            content=content,
            usage=TokenUsage(),
            provider="openrouter",
            model="test-model",
            finish_reason="stop",
            key_alias="OPENROUTER_KEY_1",
        )

    mock_llm.complete = AsyncMock(side_effect=mock_complete)

    orchestrator = WorkflowOrchestrator(llm_manager=mock_llm)
    session = MockAsyncSession(conversation=conv, messages=[])

    result = await orchestrator.execute_turn(
        conversation_id=conv_id,
        user_message_text="Every hour post a health check message to the #general Slack channel",
        db=session,
    )

    assert result.state == ConversationState.READY
    assert result.workflow_ir is not None
    assert result.workflow_ir["name"] == "Hourly Slack Sync"
    assert result.compiled_json is not None
    assert result.validation_report is not None
    assert result.validation_report["is_valid"] is True
    assert "0 fatal errors" in result.assistant_message


@pytest.mark.asyncio
async def test_orchestrator_handles_provider_outage_safely():
    """Verify orchestrator fails gracefully and records error state when provider raises exception."""
    conv_id = str(uuid.uuid4())
    conv = Conversation(
        id=conv_id,
        title="Outage Flow",
        metadata_json={"state": None, "slots": {}},
    )

    mock_llm = MagicMock(spec=LLMProviderManager)
    mock_llm.complete = AsyncMock(side_effect=RuntimeError("Connection to OpenRouter timed out."))

    orchestrator = WorkflowOrchestrator(llm_manager=mock_llm)
    session = MockAsyncSession(conversation=conv, messages=[])

    result = await orchestrator.execute_turn(
        conversation_id=conv_id,
        user_message_text="Build a webhook workflow",
        db=session,
    )

    # Catches safely and reports FAILED state
    assert result.state == ConversationState.FAILED
    assert "Failed to complete workflow planning" in result.assistant_message
    assert result.original_prompt == "Build a webhook workflow"
    assert conv.metadata_json.get("original_prompt") == "Build a webhook workflow"


@pytest.mark.asyncio
async def test_orchestrator_concurrency_guard():
    """Verify orchestrator blocks concurrent generation on the same conversation."""
    import asyncio

    conv_id = str(uuid.uuid4())
    conv = Conversation(
        id=conv_id,
        title="Concurrent Test",
        metadata_json={"state": None, "slots": {}},
    )

    started_event = asyncio.Event()
    finish_event = asyncio.Event()

    class PausingAsyncSession(MockAsyncSession):
        async def execute(self, stmt):
            stmt_str = str(stmt).lower()
            if "from conversations" in stmt_str and not started_event.is_set():
                started_event.set()
                await finish_event.wait()
            return await super().execute(stmt)

    mock_llm = MagicMock(spec=LLMProviderManager)
    orchestrator = WorkflowOrchestrator(llm_manager=mock_llm)
    session = PausingAsyncSession(conversation=conv, messages=[])

    # Start first turn in background
    task1 = asyncio.create_task(
        orchestrator.execute_turn(
            conversation_id=conv_id,
            user_message_text="Workflow prompt 1",
            db=session,
        )
    )
    # Wait until task1 has entered execute_turn and acquired active conversation status
    await started_event.wait()

    # Attempt concurrent second turn with same conversation_id
    with pytest.raises(ValueError, match="already in progress"):
        await orchestrator.execute_turn(
            conversation_id=conv_id,
            user_message_text="Workflow prompt 2",
            db=session,
        )

    # Release task1 and wait for completion
    finish_event.set()
    await task1
    assert conv_id not in orchestrator._active_conversations



@pytest.mark.asyncio
async def test_orchestrator_skip_user_message_persistence():
    """Verify skip_user_message_persistence avoids adding a duplicate user message."""
    conv_id = str(uuid.uuid4())
    conv = Conversation(
        id=conv_id,
        title="Retry Test",
        metadata_json={"state": None, "slots": {}, "original_prompt": "Initial user prompt"},
    )

    mock_llm = MagicMock(spec=LLMProviderManager)
    mock_llm.complete = AsyncMock(
        return_value=LLMResponse(
            content=json.dumps({"has_ambiguities": False, "questions": []}),
            usage=TokenUsage(),
            provider="openrouter",
            model="test-model",
            finish_reason="stop",
            key_alias="OPENROUTER_KEY_1",
        )
    )

    orchestrator = WorkflowOrchestrator(llm_manager=mock_llm)
    session = MockAsyncSession(conversation=conv, messages=[])

    await orchestrator.execute_turn(
        conversation_id=conv_id,
        user_message_text="Initial user prompt",
        db=session,
        skip_user_message_persistence=True,
    )

    # No user message should have been added by execute_turn
    user_msgs = [m for m in session.added if isinstance(m, ConversationMessage) and m.role == "user"]
    assert len(user_msgs) == 0

