"""Unit and regression tests for Intent-Driven Planning, Clarification, and Semantic Validation."""
import json
import uuid
from typing import Any, Dict, List, Optional
import pytest
from unittest.mock import AsyncMock, MagicMock

from backend.app.llm.interface import LLMRequest, LLMResponse, TokenUsage
from backend.app.llm.manager import LLMProviderManager
from backend.app.models.conversation import Conversation, ConversationMessage
from backend.app.orchestrator.engine import WorkflowOrchestrator
from backend.app.orchestrator.intent import WorkflowIntent, WorkflowIntentExtractor
from backend.app.orchestrator.schemas import ClarificationAnswerItem
from backend.app.orchestrator.state_machine import ConversationState
from backend.app.schemas.ir import ConnectionType, IREdge, IRNode, WorkflowIR
from backend.app.schemas.readiness import ReadinessStatus, CredentialVerificationState
from backend.app.services.compiler import WorkflowCompiler
from backend.app.services.node_registry import NodeRegistry
from backend.app.services.readiness import WorkflowReadinessEvaluator
from backend.app.services.validator import WorkflowValidator
from backend.app.security.sanitizer import SecretSanitizer


class MockAsyncSession:
    """Mock async database session for multi-turn turn testing."""

    def __init__(self, conversation: Conversation, messages: list):
        self.conversation = conversation
        self.messages = list(messages)
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
        if isinstance(entity, ConversationMessage):
            self.messages.append(entity)

    async def flush(self):
        pass

    async def commit(self):
        pass

    async def refresh(self, entity):
        pass


def make_email_telegram_ir(
    trigger_type: str = "n8n-nodes-base.gmailTrigger",
    trigger_version: float = 1.4,
    chat_id: str = "={{ '<YOUR_TELEGRAM_CHAT_ID>' }}",
    message_text: str = "={{ '📬 New Email Received\\n\\nFrom: ' + ($json.from || 'Unknown') + '\\nSubject: ' + ($json.subject || '(No Subject)') }}",
    has_creds: bool = True,
) -> Dict:
    """Helper creating a test WorkflowIR dict for Email to Telegram."""
    trigger_creds = {"gmailOAuth2": {"id": "1", "name": "Gmail account"}} if (has_creds and "gmail" in trigger_type) else {}
    if "emailreadimap" in trigger_type.lower() and has_creds:
        trigger_creds = {"imap": {"id": "1", "name": "IMAP account"}}

    tg_creds = {"telegramApi": {"id": "1", "name": "Telegram account"}} if has_creds else {}

    return {
        "id": "wf_email_telegram_test",
        "name": "Email to Telegram Notification",
        "nodes": [
            {
                "id": "node_email_trigger",
                "name": "Email Trigger",
                "node_type": trigger_type,
                "type_version": trigger_version,
                "position": {"x": 250, "y": 300},
                "parameters": {"event": "messageReceived", "simple": True} if "gmail" in trigger_type else {},
                "credentials": trigger_creds,
            },
            {
                "id": "node_telegram",
                "name": "Telegram",
                "node_type": "n8n-nodes-base.telegram",
                "type_version": 1.2,
                "position": {"x": 500, "y": 300},
                "parameters": {
                    "resource": "message",
                    "operation": "sendMessage",
                    "chatId": chat_id,
                    "text": message_text,
                },
                "credentials": tg_creds,
            },
        ],
        "edges": [
            {
                "source_id": "node_email_trigger",
                "target_id": "node_telegram",
                "source_output_index": 0,
                "target_input_index": 0,
            }
        ],
    }


def make_google_sheets_telegram_ir(
    workflow_id: str = "wf_sheets_telegram_test",
    chat_id: str = "={{ '<YOUR_TELEGRAM_CHAT_ID>' }}",
    message_text: str = "={{ '📊 New Row: ' + JSON.stringify($json) }}",
) -> Dict[str, Any]:
    return {
        "id": workflow_id,
        "name": "Google Sheets to Telegram Notification",
        "nodes": [
            {
                "id": "node_sheets",
                "name": "Google Sheets Trigger",
                "node_type": "n8n-nodes-base.googleSheetsTrigger",
                "type_version": 1.0,
                "position": {"x": 250, "y": 300},
                "parameters": {
                    "event": "rowAdded",
                    "documentId": {"mode": "list", "value": "test_doc"},
                    "sheetName": {"mode": "list", "value": "Sheet1"},
                },
                "credentials": {
                    "googleApi": {"id": "1", "name": "Google account"},
                    "googleSheetsTriggerOAuth2Api": {"id": "1", "name": "Google account"},
                },
            },
            {
                "id": "node_telegram",
                "name": "Telegram",
                "node_type": "n8n-nodes-base.telegram",
                "type_version": 1.2,
                "position": {"x": 500, "y": 300},
                "parameters": {
                    "resource": "message",
                    "operation": "sendMessage",
                    "chatId": chat_id,
                    "text": message_text,
                },
                "credentials": {"telegramApi": {"id": "1", "name": "Telegram account"}},
            },
        ],
        "edges": [{"source_id": "node_sheets", "target_id": "node_telegram"}],
    }


# =====================================================================
# 1. Clarification & Intent Understanding Tests
# =====================================================================

@pytest.mark.asyncio
async def test_email_to_telegram_clarification_on_unspecified_provider():
    """Verify that 'When I receive an email, send me a notification on Telegram' asks for email provider."""
    conv_id = str(uuid.uuid4())
    conv = Conversation(
        id=conv_id,
        title="Email to Telegram",
        metadata_json={"state": None, "slots": {}},
    )

    mock_llm = MagicMock(spec=LLMProviderManager)
    orchestrator = WorkflowOrchestrator(llm_manager=mock_llm)
    session = MockAsyncSession(conversation=conv, messages=[])

    result = await orchestrator.execute_turn(
        conversation_id=conv_id,
        user_message_text="When I receive an email, send me a notification on Telegram.",
        db=session,
    )

    # Must ask for email provider clarification rather than guessing
    assert result.state == ConversationState.CLARIFYING
    assert result.clarification is not None
    assert result.clarification.has_ambiguities is True
    assert any(q.field_key == "email_provider" for q in result.clarification.questions)

    # Check question text and all 4 selectable options (Gmail, Outlook, IMAP, Other)
    q = next(q for q in result.clarification.questions if q.field_key == "email_provider")
    assert q.question == "Which email service should trigger the workflow?"
    option_values = [opt.value for opt in q.options]
    assert "gmail" in option_values
    assert "outlook" in option_values
    assert "imap" in option_values
    assert "other" in option_values


@pytest.mark.asyncio
async def test_email_to_telegram_multi_turn_resumption():
    """Verify user clarification answer resumes planning with prior context preserved."""
    conv_id = str(uuid.uuid4())
    conv = Conversation(
        id=conv_id,
        title="Email to Telegram",
        metadata_json={"state": ConversationState.CLARIFYING.value, "slots": {}},
    )

    # Initial history with turn 1
    m1 = ConversationMessage(
        id=str(uuid.uuid4()),
        conversation_id=conv_id,
        role="user",
        content="When I receive an email, send me a notification on Telegram.",
    )
    m2 = ConversationMessage(
        id=str(uuid.uuid4()),
        conversation_id=conv_id,
        role="assistant",
        content="Which email service would you like to monitor?",
        metadata_json={"state": "clarifying"},
    )

    generated_ir_dict = make_email_telegram_ir()
    mock_llm = MagicMock(spec=LLMProviderManager)
    mock_llm.complete = AsyncMock(
        return_value=LLMResponse(
            content=json.dumps(generated_ir_dict),
            usage=TokenUsage(),
            provider="openrouter",
            model="nvidia/nemotron-3-super-120b-a12b:free",
            finish_reason="stop",
            key_alias="OPENROUTER_KEY_1",
        )
    )

    orchestrator = WorkflowOrchestrator(llm_manager=mock_llm)
    session = MockAsyncSession(conversation=conv, messages=[m1, m2])

    # Turn 2: user selects Gmail -> must ask for Telegram Chat ID next without skipping
    result_turn2 = await orchestrator.execute_turn(
        conversation_id=conv_id,
        user_message_text="Gmail",
        db=session,
        selected_options={"email_provider": "gmail"},
    )

    # Must stay in CLARIFYING, preserve original prompt, and ask for telegram_chat_id
    assert result_turn2.state == ConversationState.CLARIFYING
    assert result_turn2.clarification is not None
    assert result_turn2.clarification.current_question_id == "telegram_chat_id"
    assert result_turn2.original_prompt == "When I receive an email, send me a notification on Telegram."
    assert result_turn2.completed_answers.get("email_provider") == "gmail"

    # Turn 3: user provides Telegram Chat ID -> now all required fields complete -> READY
    result_turn3 = await orchestrator.execute_turn(
        conversation_id=conv_id,
        user_message_text="123456789",
        db=session,
        selected_options={"telegram_chat_id": "123456789"},
    )

    assert result_turn3.state == ConversationState.READY
    assert result_turn3.workflow_ir is not None
    assert len(result_turn3.workflow_ir["nodes"]) == 2
    node_types = [n["node_type"] for n in result_turn3.workflow_ir["nodes"]]
    assert "n8n-nodes-base.gmailTrigger" in node_types
    assert "n8n-nodes-base.telegram" in node_types


@pytest.mark.asyncio
async def test_email_to_telegram_direct_generation_when_provider_specified():
    """Verify that when both email provider and chat ID are explicitly stated, generation proceeds directly."""
    conv_id = str(uuid.uuid4())
    conv = Conversation(
        id=conv_id,
        title="Gmail to Telegram",
        metadata_json={"state": None, "slots": {}},
    )

    generated_ir_dict = make_email_telegram_ir(chat_id="123456789")
    mock_llm = MagicMock(spec=LLMProviderManager)
    mock_llm.complete = AsyncMock(
        return_value=LLMResponse(
            content=json.dumps(generated_ir_dict),
            usage=TokenUsage(),
            provider="openrouter",
            model="nvidia/nemotron-3-super-120b-a12b:free",
            finish_reason="stop",
            key_alias="OPENROUTER_KEY_1",
        )
    )

    orchestrator = WorkflowOrchestrator(llm_manager=mock_llm)
    session = MockAsyncSession(conversation=conv, messages=[])

    result = await orchestrator.execute_turn(
        conversation_id=conv_id,
        user_message_text="When I receive an email in Gmail, send me a notification on Telegram to chat 123456789.",
        db=session,
    )

    assert result.state == ConversationState.READY
    assert result.workflow_ir is not None
    tg_node = next(n for n in result.workflow_ir["nodes"] if n["node_type"] == "n8n-nodes-base.telegram")
    # Verify Telegram node parameters
    assert tg_node["parameters"]["resource"] == "message"
    assert tg_node["parameters"]["operation"] == "sendMessage"
    assert "$json.from" in tg_node["parameters"]["text"]
    assert "$json.subject" in tg_node["parameters"]["text"]
    # Verify no fabricated values
    assert tg_node["parameters"]["chatId"] != "Emcheckmebot"
    assert tg_node["parameters"]["text"] != "gmail"


# =====================================================================
# 2. Semantic Validation Tests
# =====================================================================

def test_semantic_validation_rejects_manual_trigger_when_email_requested():
    """Verify validator flags manualTrigger as fatal when email trigger was requested."""
    validator = WorkflowValidator()
    ir_dict = {
        "id": "wf_bad_manual",
        "name": "Bad Manual Flow",
        "nodes": [
            {
                "id": "node_manual",
                "name": "Manual Trigger",
                "node_type": "n8n-nodes-base.manualTrigger",
                "type_version": 1.0,
                "position": {"x": 250, "y": 300},
                "parameters": {},
            },
            {
                "id": "node_telegram",
                "name": "Telegram",
                "node_type": "n8n-nodes-base.telegram",
                "type_version": 1.2,
                "position": {"x": 500, "y": 300},
                "parameters": {
                    "resource": "message",
                    "operation": "sendMessage",
                    "chatId": "={{ '<YOUR_TELEGRAM_CHAT_ID>' }}",
                    "text": "Email arrived",
                },
            },
        ],
        "edges": [{"source_id": "node_manual", "target_id": "node_telegram"}],
    }
    wf = WorkflowIR.model_validate(ir_dict)
    report = validator.validate(
        wf,
        prompt_context="When I receive an email, send me a notification on Telegram.",
    )

    assert not report.is_valid
    assert any(i.rule_code == "TRIGGER_INTENT_MISMATCH" and i.severity == "fatal" for i in report.issues)


def test_semantic_validation_rejects_fabricated_placeholder_values():
    """Verify validator flags known bogus placeholders (Emcheckmebot, 'gmail') as fatal."""
    validator = WorkflowValidator()
    bad_ir = make_email_telegram_ir(
        chat_id="Emcheckmebot",
        message_text="gmail",
    )
    wf = WorkflowIR.model_validate(bad_ir)
    report = validator.validate(
        wf,
        prompt_context="When I receive an email in Gmail, send me a notification on Telegram.",
    )

    assert not report.is_valid
    codes = [i.rule_code for i in report.issues]
    assert "FABRICATED_PLACEHOLDER_PARAMETER" in codes


def test_semantic_validation_flags_missing_telegram_action():
    """Verify validator flags missing Telegram node when Telegram notification was requested."""
    validator = WorkflowValidator()
    ir_dict = {
        "id": "wf_missing_tg",
        "name": "Missing Telegram",
        "nodes": [
            {
                "id": "node_email",
                "name": "Gmail Trigger",
                "node_type": "n8n-nodes-base.gmailTrigger",
                "type_version": 1.4,
                "position": {"x": 250, "y": 300},
                "parameters": {"event": "messageReceived"},
            },
            {
                "id": "node_noop",
                "name": "NoOp",
                "node_type": "n8n-nodes-base.noOp",
                "type_version": 1.0,
                "position": {"x": 500, "y": 300},
                "parameters": {},
            },
        ],
        "edges": [{"source_id": "node_email", "target_id": "node_noop"}],
    }
    wf = WorkflowIR.model_validate(ir_dict)
    report = validator.validate(
        wf,
        prompt_context="When I receive an email, send me a notification on Telegram.",
    )

    assert not report.is_valid
    assert any(i.rule_code == "ACTION_INTENT_MISMATCH" for i in report.issues)


# =====================================================================
# 3. Readiness Evaluation & Credential Honesty Tests
# =====================================================================

def test_readiness_honesty_for_unconfigured_credentials():
    """Verify readiness evaluator marks unconfigured credentials as NEEDS_ATTENTION, never falsely READY."""
    evaluator = WorkflowReadinessEvaluator()
    valid_ir = make_email_telegram_ir(has_creds=False)  # No credentials attached
    wf = WorkflowIR.model_validate(valid_ir)

    readiness = evaluator.evaluate(
        wf,
        prompt_context="When I receive an email in Gmail, send me a notification on Telegram.",
    )

    # Must be NEEDS_ATTENTION because credentials are not verified/configured
    assert readiness.overall_status == ReadinessStatus.NEEDS_ATTENTION
    assert readiness.is_deployable_to_n8n is False
    assert any(c.credential_type == "telegramApi" for c in readiness.credentials)


# =====================================================================
# 4. Complex Graph Support Tests
# =====================================================================

def test_complex_workflow_branching_and_conditions():
    """Verify validator and compiler correctly handle multi-node conditional branching."""
    complex_ir_dict = {
        "id": "wf_complex_lead_scoring",
        "name": "Lead Routing with If Branching",
        "nodes": [
            {
                "id": "node_webhook",
                "name": "Webhook Trigger",
                "node_type": "n8n-nodes-base.webhook",
                "type_version": 1.1,
                "position": {"x": 200, "y": 300},
                "parameters": {"path": "lead-webhook", "httpMethod": "POST"},
            },
            {
                "id": "node_if",
                "name": "Score Threshold Check",
                "node_type": "n8n-nodes-base.if",
                "type_version": 2.2,
                "position": {"x": 450, "y": 300},
                "parameters": {},
            },
            {
                "id": "node_telegram_high",
                "name": "High Priority Telegram",
                "node_type": "n8n-nodes-base.telegram",
                "type_version": 1.2,
                "position": {"x": 700, "y": 200},
                "parameters": {
                    "resource": "message",
                    "operation": "sendMessage",
                    "chatId": "={{ '<YOUR_TELEGRAM_CHAT_ID>' }}",
                    "text": "={{ '🚨 High Priority Lead: ' + $json.leadName }}",
                },
                "credentials": {"telegramApi": {"id": "1", "name": "Telegram account"}},
            },
            {
                "id": "node_slack_low",
                "name": "Standard Slack Log",
                "node_type": "n8n-nodes-base.slack",
                "type_version": 2.2,
                "position": {"x": 700, "y": 400},
                "parameters": {"channel": "#leads", "text": "New standard lead received"},
                "credentials": {"slackApi": {"id": "1", "name": "Slack account"}},
            },
        ],
        "edges": [
            {"source_id": "node_webhook", "target_id": "node_if", "source_output_index": 0, "target_input_index": 0},
            {"source_id": "node_if", "target_id": "node_telegram_high", "source_output_index": 0, "target_input_index": 0},
            {"source_id": "node_if", "target_id": "node_slack_low", "source_output_index": 1, "target_input_index": 0},
        ],
    }

    wf = WorkflowIR.model_validate(complex_ir_dict)
    validator = WorkflowValidator()
    report = validator.validate(wf)
    assert report.is_valid is True

    compiler = WorkflowCompiler()
    compiled = compiler.compile(wf)
    assert "nodes" in compiled
    assert len(compiled["nodes"]) == 4
    assert "connections" in compiled


# =====================================================================
# 5. Regression Tests for Clarification, IMAP, Outlook & Secrecy
# =====================================================================

@pytest.mark.asyncio
async def test_email_to_telegram_imap_selection():
    """Verify selecting IMAP generates the supported EmailReadImap trigger node."""
    conv_id = str(uuid.uuid4())
    conv = Conversation(
        id=conv_id,
        title="Email to Telegram",
        metadata_json={"state": ConversationState.CLARIFYING.value, "slots": {}},
    )

    m1 = ConversationMessage(
        id=str(uuid.uuid4()),
        conversation_id=conv_id,
        role="user",
        content="When I receive an email, send me a notification on Telegram.",
    )
    m2 = ConversationMessage(
        id=str(uuid.uuid4()),
        conversation_id=conv_id,
        role="assistant",
        content="Which email service should trigger this workflow?",
        metadata_json={"state": "clarifying"},
    )

    generated_ir_dict = make_email_telegram_ir(trigger_type="n8n-nodes-base.emailReadImap", trigger_version=2.2)
    mock_llm = MagicMock(spec=LLMProviderManager)
    mock_llm.complete = AsyncMock(
        return_value=LLMResponse(
            content=json.dumps(generated_ir_dict),
            usage=TokenUsage(),
            provider="openrouter",
            model="nvidia/nemotron-3-super-120b-a12b:free",
            finish_reason="stop",
            key_alias="OPENROUTER_KEY_1",
        )
    )

    orchestrator = WorkflowOrchestrator(llm_manager=mock_llm)
    session = MockAsyncSession(conversation=conv, messages=[m1, m2])

    result = await orchestrator.execute_turn(
        conversation_id=conv_id,
        user_message_text="IMAP / Custom Email",
        db=session,
        selected_options={"email_provider": "imap", "telegram_chat_id": "123456789"},
    )

    assert result.state == ConversationState.READY
    assert result.workflow_ir is not None
    node_types = [n["node_type"] for n in result.workflow_ir["nodes"]]
    assert "n8n-nodes-base.emailReadImap" in node_types
    assert "n8n-nodes-base.telegram" in node_types


@pytest.mark.asyncio
async def test_email_to_telegram_outlook_selection():
    """Verify selecting Outlook generates the supported microsoftOutlookTrigger node."""
    conv_id = str(uuid.uuid4())
    conv = Conversation(
        id=conv_id,
        title="Email to Telegram",
        metadata_json={"state": ConversationState.CLARIFYING.value, "slots": {"telegram_chat_id": "123456789"}},
    )

    m1 = ConversationMessage(
        id=str(uuid.uuid4()),
        conversation_id=conv_id,
        role="user",
        content="When I receive an email, send me a notification on Telegram.",
    )

    generated_ir_dict = make_email_telegram_ir(trigger_type="n8n-nodes-base.microsoftOutlookTrigger", trigger_version=1.0)
    mock_llm = MagicMock(spec=LLMProviderManager)
    mock_llm.complete = AsyncMock(
        return_value=LLMResponse(
            content=json.dumps(generated_ir_dict),
            usage=TokenUsage(),
            provider="openrouter",
            model="nvidia/nemotron-3-super-120b-a12b:free",
            finish_reason="stop",
            key_alias="OPENROUTER_KEY_1",
        )
    )

    orchestrator = WorkflowOrchestrator(llm_manager=mock_llm)
    session = MockAsyncSession(conversation=conv, messages=[m1])

    result = await orchestrator.execute_turn(
        conversation_id=conv_id,
        user_message_text="Outlook",
        db=session,
        selected_options={"email_provider": "outlook"},
    )

    assert result.state == ConversationState.READY
    assert result.workflow_ir is not None
    node_types = [n["node_type"] for n in result.workflow_ir["nodes"]]
    assert "n8n-nodes-base.microsoftOutlookTrigger" in node_types
    assert "n8n-nodes-base.telegram" in node_types


def test_missing_telegram_chat_id_not_invented():
    """Verify intent extractor sets placeholder and does NOT invent fake chat IDs like Emcheckmebot."""
    extractor = WorkflowIntentExtractor()
    intent = extractor.analyze(
        user_prompt="When I receive an email in Gmail, send me a notification on Telegram.",
        history=[],
        accumulated_slots={"email_provider": "gmail"},
    )

    assert intent.trigger is not None
    assert intent.trigger.service == "gmail"
    assert len(intent.actions) == 1
    tg_action = intent.actions[0]
    assert tg_action.service == "telegram"
    # Parameter chatId must be the standard placeholder, not a fake username
    assert tg_action.parameters["chatId"] != "Emcheckmebot"
    assert "YOUR_TELEGRAM_CHAT_ID" in tg_action.parameters["chatId"]


def test_telegram_bot_token_never_exposed_or_requested_in_chat():
    """Verify clarification questions never request bot tokens and SecretSanitizer scrubs bot tokens."""
    extractor = WorkflowIntentExtractor()
    intent = extractor.analyze(
        user_prompt="When I receive an email, send me a notification on Telegram.",
        history=[],
        accumulated_slots={},
    )

    # Clarification questions must NEVER ask for bot tokens or secrets
    for q in intent.clarification_questions:
        q_text_lower = q.question.lower()
        assert "token" not in q_text_lower
        assert "bot token" not in q_text_lower
        assert "api key" not in q_text_lower
        assert "password" not in q_text_lower

    # SecretSanitizer must scrub raw Telegram bot tokens
    sanitizer = SecretSanitizer()
    fake_token = "123456789:ABCdefGhIjkLmNoPqRsTuVwXyZ12345678"
    scrubbed = sanitizer.sanitize(f"Error connecting with token {fake_token} to telegram")
    assert fake_token not in scrubbed
    assert "[REDACTED]" in scrubbed


@pytest.mark.asyncio
async def test_clarification_does_not_repeat_after_valid_answer():
    """Verify once email_provider is answered, the same question is not repeated in a loop."""
    conv_id = str(uuid.uuid4())
    conv = Conversation(
        id=conv_id,
        title="Email to Telegram",
        metadata_json={"state": ConversationState.CLARIFYING.value, "slots": {"email_provider": "gmail"}},
    )

    m1 = ConversationMessage(
        id=str(uuid.uuid4()),
        conversation_id=conv_id,
        role="user",
        content="When I receive an email, send me a notification on Telegram.",
    )
    m2 = ConversationMessage(
        id=str(uuid.uuid4()),
        conversation_id=conv_id,
        role="assistant",
        content="Which email service should trigger this workflow?",
    )
    m3 = ConversationMessage(
        id=str(uuid.uuid4()),
        conversation_id=conv_id,
        role="user",
        content="Gmail",
        metadata_json={"selected_options": {"email_provider": "gmail"}},
    )

    generated_ir_dict = make_email_telegram_ir()
    mock_llm = MagicMock(spec=LLMProviderManager)
    mock_llm.complete = AsyncMock(
        return_value=LLMResponse(
            content=json.dumps(generated_ir_dict),
            usage=TokenUsage(),
            provider="openrouter",
            model="nvidia/nemotron-3-super-120b-a12b:free",
            finish_reason="stop",
            key_alias="OPENROUTER_KEY_1",
        )
    )

    orchestrator = WorkflowOrchestrator(llm_manager=mock_llm)
    session = MockAsyncSession(conversation=conv, messages=[m1, m2, m3])

    # Subsequent message does not ask email_provider again
    result = await orchestrator.execute_turn(
        conversation_id=conv_id,
        user_message_text="Proceed with Gmail",
        db=session,
        selected_options={"telegram_chat_id": "123456789"},
    )

    # Must generate workflow rather than asking email_provider again
    assert result.state == ConversationState.READY
    assert result.workflow_ir is not None


def test_mind_change_updates_provider_without_losing_chat_id():
    """Verify changing email provider updates slot without losing previously provided chat ID."""
    extractor = WorkflowIntentExtractor()
    # Turn 1: user provided chat ID alongside email trigger
    intent1 = extractor.analyze(
        user_prompt="When I receive an email, send Telegram to 123456789.",
        history=[],
        accumulated_slots={"telegram_chat_id": "123456789", "email_provider": "gmail"},
    )
    assert intent1.completed_answers.get("email_provider") == "gmail"
    assert intent1.completed_answers.get("telegram_chat_id") == "123456789"

    # Turn 2: user changes mind to Outlook
    intent2 = extractor.analyze(
        user_prompt="Actually, use Outlook instead.",
        history=[],
        accumulated_slots=intent1.completed_answers,
        original_prompt="When I receive an email, send Telegram to 123456789.",
    )
    assert intent2.completed_answers.get("email_provider") == "outlook"
    assert intent2.completed_answers.get("telegram_chat_id") == "123456789"
    assert intent2.trigger.service == "outlook"
    assert intent2.trigger.node_type == "n8n-nodes-base.microsoftOutlookTrigger"


def test_telegram_bot_username_rejected_as_chat_id():
    """Verify Telegram bot usernames ending with 'bot' are strictly rejected as numeric chat IDs."""
    extractor = WorkflowIntentExtractor()

    # User attempts to pass bot username as chat ID
    for bogus_id in ["Emcheckmebot", "@Emcheckmebot", "my_test_bot", "@alertbot"]:
        intent = extractor.analyze(
            user_prompt=f"Chat ID: {bogus_id}",
            history=[],
            accumulated_slots={"email_provider": "gmail"},
            original_prompt="When I receive an email, send me a notification on Telegram.",
        )
        # Must not be accepted as telegram_chat_id
        assert intent.completed_answers.get("telegram_chat_id") is None
        assert "telegram_chat_id" in intent.outstanding_questions
        assert intent.current_question is not None
        assert intent.current_question.id == "telegram_chat_id"

    # Valid numeric chat ID is accepted
    valid_intent = extractor.analyze(
        user_prompt="Chat ID: 987654321",
        history=[],
        accumulated_slots={"email_provider": "gmail"},
        original_prompt="When I receive an email, send me a notification on Telegram.",
    )
    assert valid_intent.completed_answers.get("telegram_chat_id") == "987654321"
    assert "telegram_chat_id" not in valid_intent.outstanding_questions


def test_custom_other_email_provider_maps_to_imap():
    """Verify selecting Other with custom provider like Zoho Mail maps to IMAP trigger."""
    extractor = WorkflowIntentExtractor()
    intent = extractor.analyze(
        user_prompt="I use Zoho Mail",
        history=[],
        accumulated_slots={},
        original_prompt="When I receive an email, send me a notification on Telegram.",
    )
    assert intent.completed_answers.get("email_provider") == "imap"
    assert intent.trigger is not None
    assert intent.trigger.service == "imap"
    assert intent.trigger.node_type == "n8n-nodes-base.emailReadImap"


@pytest.mark.asyncio
async def test_batch_clarification_questions_returned_simultaneously():
    """Verify that multiple missing requirements are returned together in one clarification plan."""
    conv_id = str(uuid.uuid4())
    conv = Conversation(
        id=conv_id,
        title="Email to Telegram",
        metadata_json={"state": None, "slots": {}},
    )

    mock_llm = MagicMock(spec=LLMProviderManager)
    orchestrator = WorkflowOrchestrator(llm_manager=mock_llm)
    session = MockAsyncSession(conversation=conv, messages=[])

    result = await orchestrator.execute_turn(
        conversation_id=conv_id,
        user_message_text="When I receive an email, send me a notification on Telegram.",
        db=session,
    )

    assert result.state == ConversationState.CLARIFYING
    assert result.clarification is not None
    assert result.clarification.has_ambiguities is True
    # Both questions must be returned together
    assert len(result.clarification.questions) == 2
    question_keys = [q.field_key for q in result.clarification.questions]
    assert "email_provider" in question_keys
    assert "telegram_chat_id" in question_keys


@pytest.mark.asyncio
async def test_batch_clarification_answer_submission_proceeds_to_ready():
    """Verify batch answering all clarification questions simultaneously completes the workflow."""
    conv_id = str(uuid.uuid4())
    conv = Conversation(
        id=conv_id,
        title="Email to Telegram",
        metadata_json={
            "state": ConversationState.CLARIFYING.value,
            "slots": {},
            "original_prompt": "When I receive an email, send me a notification on Telegram.",
            "clarification": {
                "questions": [
                    {"id": "email_provider", "field_key": "email_provider", "question": "Which email service?"},
                    {"id": "telegram_chat_id", "field_key": "telegram_chat_id", "question": "Where should notification be sent?"},
                ]
            },
        },
    )

    m1 = ConversationMessage(
        id=str(uuid.uuid4()),
        conversation_id=conv_id,
        role="user",
        content="When I receive an email, send me a notification on Telegram.",
    )
    m2 = ConversationMessage(
        id=str(uuid.uuid4()),
        conversation_id=conv_id,
        role="assistant",
        content="Please provide email service and Telegram destination.",
        metadata_json={"state": "clarifying"},
    )

    generated_ir_dict = make_email_telegram_ir(chat_id="123456789")
    mock_llm = MagicMock(spec=LLMProviderManager)
    mock_llm.complete = AsyncMock(
        return_value=LLMResponse(
            content=json.dumps(generated_ir_dict),
            usage=TokenUsage(),
            provider="openrouter",
            model="nvidia/nemotron-3-super-120b-a12b:free",
            finish_reason="stop",
            key_alias="OPENROUTER_KEY_1",
        )
    )

    orchestrator = WorkflowOrchestrator(llm_manager=mock_llm)
    session = MockAsyncSession(conversation=conv, messages=[m1, m2])

    batch_answers = [
        ClarificationAnswerItem(question_id="email_provider", field_key="email_provider", selected_value="gmail"),
        ClarificationAnswerItem(question_id="telegram_chat_id", field_key="telegram_chat_id", selected_value="123456789"),
    ]

    result = await orchestrator.execute_turn(
        conversation_id=conv_id,
        user_message_text="",
        db=session,
        clarification_answers=batch_answers,
    )

    assert result.state == ConversationState.READY
    assert result.workflow_ir is not None
    assert result.completed_answers.get("email_provider") == "gmail"
    assert result.completed_answers.get("telegram_chat_id") == "123456789"


@pytest.mark.asyncio
async def test_batch_clarification_validation_rejects_empty_other_and_bot_usernames():
    """Verify validation rejects empty custom text when Other is selected and rejects bot usernames."""
    conv_id = str(uuid.uuid4())
    conv = Conversation(
        id=conv_id,
        title="Email to Telegram",
        metadata_json={
            "state": ConversationState.CLARIFYING.value,
            "slots": {},
            "clarification": {
                "questions": [
                    {"id": "email_provider", "field_key": "email_provider", "question": "Which email service?"},
                    {"id": "telegram_chat_id", "field_key": "telegram_chat_id", "question": "Where should notification be sent?"},
                ]
            },
        },
    )

    mock_llm = MagicMock(spec=LLMProviderManager)
    orchestrator = WorkflowOrchestrator(llm_manager=mock_llm)
    session = MockAsyncSession(conversation=conv, messages=[])

    # 1. Other selected with empty custom_text -> rejected
    with pytest.raises(ValueError, match="custom answer is required"):
        await orchestrator.execute_turn(
            conversation_id=conv_id,
            user_message_text="",
            db=session,
            clarification_answers=[
                ClarificationAnswerItem(question_id="email_provider", field_key="email_provider", selected_value="other", custom_text=""),
            ],
        )

    # 2. Bot username ending in 'bot' -> rejected
    with pytest.raises(ValueError, match="Bot usernames ending in 'bot' cannot receive personal notifications"):
        await orchestrator.execute_turn(
            conversation_id=conv_id,
            user_message_text="",
            db=session,
            clarification_answers=[
                ClarificationAnswerItem(question_id="telegram_chat_id", field_key="telegram_chat_id", selected_value="@Emcheckmebot"),
            ],
        )

    # 3. Unknown question ID -> rejected
    with pytest.raises(ValueError, match="Unknown clarification question ID"):
        await orchestrator.execute_turn(
            conversation_id=conv_id,
            user_message_text="",
            db=session,
            clarification_answers=[
                ClarificationAnswerItem(question_id="unknown_bogus_id", field_key="unknown", selected_value="val"),
            ],
        )


@pytest.mark.asyncio
async def test_batch_clarification_no_repetition_of_answered_questions():
    """Verify that once a question is answered, it is never presented again in subsequent turns."""
    conv_id = str(uuid.uuid4())
    conv = Conversation(
        id=conv_id,
        title="Email to Telegram",
        metadata_json={"state": None, "slots": {}},
    )

    mock_llm = MagicMock(spec=LLMProviderManager)
    orchestrator = WorkflowOrchestrator(llm_manager=mock_llm)
    session = MockAsyncSession(conversation=conv, messages=[])

    # Turn 1: user enters request -> both questions missing
    res1 = await orchestrator.execute_turn(
        conversation_id=conv_id,
        user_message_text="When I receive an email, send me a notification on Telegram.",
        db=session,
    )
    assert len(res1.clarification.questions) == 2

    # Turn 2: user only answers email_provider
    res2 = await orchestrator.execute_turn(
        conversation_id=conv_id,
        user_message_text="Gmail",
        db=session,
        selected_options={"email_provider": "gmail"},
    )
    assert res2.state == ConversationState.CLARIFYING
    assert len(res2.clarification.questions) == 1
    assert res2.clarification.questions[0].field_key == "telegram_chat_id"
    # email_provider must NOT be in the outstanding questions
    assert "email_provider" not in res2.outstanding_questions
    assert res2.completed_answers.get("email_provider") == "gmail"


@pytest.mark.asyncio
async def test_google_sheets_new_row_to_telegram_preserves_both_nodes():
    """Verify Google Sheets new row to Telegram preserves both nodes without asking for email or trigger type."""
    conv_id = str(uuid.uuid4())
    conv = Conversation(
        id=conv_id,
        title="Google Sheets to Telegram",
        metadata_json={"state": None, "slots": {}},
    )

    sheets_tg_ir = {
        "id": "wf_sheets_telegram",
        "name": "Google Sheets to Telegram Notification",
        "nodes": [
            {
                "id": "node_sheets",
                "name": "Google Sheets Trigger",
                "node_type": "n8n-nodes-base.googleSheetsTrigger",
                "type_version": 1.0,
                "position": {"x": 250, "y": 300},
                "parameters": {
                    "event": "rowAdded",
                    "documentId": {"mode": "list", "value": "test_doc"},
                    "sheetName": {"mode": "list", "value": "Sheet1"},
                },
                "credentials": {
                    "googleApi": {"id": "1", "name": "Google account"},
                    "googleSheetsTriggerOAuth2Api": {"id": "1", "name": "Google account"},
                },
            },
            {
                "id": "node_telegram",
                "name": "Telegram",
                "node_type": "n8n-nodes-base.telegram",
                "type_version": 1.2,
                "position": {"x": 500, "y": 300},
                "parameters": {
                    "resource": "message",
                    "operation": "sendMessage",
                    "chatId": "123456789",
                    "text": "={{ '📊 New Row in Google Sheets: ' + JSON.stringify($json) }}",
                },
                "credentials": {"telegramApi": {"id": "1", "name": "Telegram account"}},
            },
        ],
        "edges": [{"source_id": "node_sheets", "target_id": "node_telegram"}],
    }

    async def mock_llm_complete(req):
        content_str = req.messages[0].content
        if "Requirements Analysis" in content_str:
            return LLMResponse(
                content=json.dumps({"has_ambiguities": False, "questions": []}),
                usage=TokenUsage(),
                provider="openrouter",
                model="nvidia/nemotron-3-super-120b-a12b:free",
                finish_reason="stop",
                key_alias="OPENROUTER_KEY_1",
            )
        return LLMResponse(
            content=json.dumps(sheets_tg_ir),
            usage=TokenUsage(),
            provider="openrouter",
            model="nvidia/nemotron-3-super-120b-a12b:free",
            finish_reason="stop",
            key_alias="OPENROUTER_KEY_1",
        )

    mock_llm = MagicMock(spec=LLMProviderManager)
    mock_llm.complete = AsyncMock(side_effect=mock_llm_complete)
    orchestrator = WorkflowOrchestrator(llm_manager=mock_llm)
    session = MockAsyncSession(conversation=conv, messages=[])

    # Turn 1: user requests Google Sheets to Telegram
    res1 = await orchestrator.execute_turn(
        conversation_id=conv_id,
        user_message_text="When a new row is added to Google Sheets, send me a notification on Telegram.",
        db=session,
    )

    # Must NOT ask for email provider or generic trigger type
    assert res1.state == ConversationState.CLARIFYING
    assert res1.clarification is not None
    q_keys = [q.field_key for q in res1.clarification.questions]
    assert "email_provider" not in q_keys
    assert "trigger" not in q_keys
    # Must ask for telegram_chat_id and google_sheets_document
    assert "telegram_chat_id" in q_keys
    assert "google_sheets_document" in q_keys

    # Turn 2: user provides telegram_chat_id and google_sheets_document
    res2 = await orchestrator.execute_turn(
        conversation_id=conv_id,
        user_message_text="",
        db=session,
        clarification_answers=[
            ClarificationAnswerItem(
                question_id="telegram_chat_id",
                field_key="telegram_chat_id",
                selected_value="private_chat",
                custom_text="123456789",
            ),
            ClarificationAnswerItem(
                question_id="google_sheets_document",
                field_key="google_sheets_document",
                selected_value="https://docs.google.com/spreadsheets/d/test_doc/edit",
            ),
        ],
    )

    assert res2.state == ConversationState.READY
    assert res2.workflow_ir is not None
    node_types = [n["node_type"] for n in res2.workflow_ir["nodes"]]
    # Both Google Sheets Trigger and Telegram must be preserved
    assert "n8n-nodes-base.googleSheetsTrigger" in node_types
    assert "n8n-nodes-base.telegram" in node_types


@pytest.mark.asyncio
async def test_unsupported_service_handled_honestly_without_fabrication():
    """Verify that requesting an unsupported service is flagged honestly rather than fabricating a node."""
    extractor = WorkflowIntentExtractor()
    intent = extractor.analyze(
        user_prompt="When an incident is created in UnsupportedIncidentDesk, send a notification on Telegram.",
        history=[],
        accumulated_slots={},
    )

    assert "UnsupportedIncidentDesk" in intent.unsupported_services
    # Must generate an honest clarification question offering Webhook / HTTP Request alternatives
    assert len(intent.clarification_questions) > 0
    unsup_q = next((q for q in intent.clarification_questions if "unsupported" in q.id), None)
    assert unsup_q is not None
    assert "not available in the installed n8n node catalog" in unsup_q.question
    opt_vals = [o.value for o in unsup_q.options]
    assert "webhook" in opt_vals
    assert "http_request" in opt_vals


@pytest.mark.asyncio
async def test_choices_referring_to_nonexistent_node_types_are_filtered():
    """Verify that options pointing to nonexistent node types are filtered out from clarification questions."""
    mock_llm = MagicMock(spec=LLMProviderManager)
    # LLM proposes choices including a nonexistent node type
    fake_plan = {
        "has_ambiguities": True,
        "questions": [
            {
                "id": "q_svc",
                "question": "Which database service do you want to query?",
                "field_key": "db_service",
                "options": [
                    {"label": "PostgreSQL", "value": "n8n-nodes-base.postgres"},
                    {"label": "ImaginaryDB", "value": "n8n-nodes-base.imaginaryDb"},
                ],
            }
        ],
    }
    mock_llm.complete = AsyncMock(
        return_value=LLMResponse(
            content=json.dumps(fake_plan),
            usage=TokenUsage(),
            provider="openrouter",
            model="nvidia/nemotron-3-super-120b-a12b:free",
            finish_reason="stop",
            key_alias="OPENROUTER_KEY_1",
        )
    )
    orchestrator = WorkflowOrchestrator(llm_manager=mock_llm)
    plan = await orchestrator._evaluate_requirements(
        user_prompt="Query my database",
        history=[],
        accumulated_slots={},
    )

    assert plan.has_ambiguities is True
    q = plan.questions[0]
    opt_values = [o.value for o in q.options]
    assert "n8n-nodes-base.postgres" in opt_values
    # Nonexistent node type must be filtered out
    assert "n8n-nodes-base.imaginaryDb" not in opt_values


@pytest.mark.asyncio
async def test_bounded_clarification_prevents_infinite_loop():
    """Verify orchestrator fails safely after 4 unresolved clarification rounds instead of looping forever."""
    conv_id = str(uuid.uuid4())
    conv = Conversation(
        id=conv_id,
        title="Loop Test",
        metadata_json={"state": ConversationState.CLARIFYING.value, "slots": {}, "clarification_turns": 4},
    )

    orchestrator = WorkflowOrchestrator()
    session = MockAsyncSession(conversation=conv, messages=[])

    res = await orchestrator.execute_turn(
        conversation_id=conv_id,
        user_message_text="When I receive an email, notify Telegram.",
        db=session,
    )

    assert res.state == ConversationState.FAILED
    assert "Clarification limit reached" in res.assistant_message


def test_semantic_validation_rejects_manual_trigger_when_google_sheets_requested():
    """Verify validator flags manualTrigger as fatal when Google Sheets trigger was requested."""
    validator = WorkflowValidator()
    ir_dict = {
        "id": "wf_bad_sheets_manual",
        "name": "Bad Sheets Manual Flow",
        "nodes": [
            {
                "id": "node_manual",
                "name": "Manual Trigger",
                "node_type": "n8n-nodes-base.manualTrigger",
                "type_version": 1.0,
                "position": {"x": 250, "y": 300},
                "parameters": {},
            },
            {
                "id": "node_telegram",
                "name": "Telegram",
                "node_type": "n8n-nodes-base.telegram",
                "type_version": 1.2,
                "position": {"x": 500, "y": 300},
                "parameters": {
                    "resource": "message",
                    "operation": "sendMessage",
                    "chatId": "123456789",
                    "text": "Row added",
                },
            },
        ],
        "edges": [{"source_id": "node_manual", "target_id": "node_telegram"}],
    }
    wf = WorkflowIR.model_validate(ir_dict)
    report = validator.validate(
        wf,
        prompt_context="When a new row is added to Google Sheets, send me a notification on Telegram.",
    )

    assert not report.is_valid
    assert any(i.rule_code == "TRIGGER_INTENT_MISMATCH" and i.severity == "fatal" for i in report.issues)


def test_gmail_explicit_does_not_ask_email_provider():
    """Verify 'When I receive a Gmail message, notify me on Telegram' does not ask which email provider."""
    extractor = WorkflowIntentExtractor()
    intent = extractor.analyze(
        user_prompt="When I receive a Gmail message, notify me on Telegram",
        history=[],
        accumulated_slots={},
    )
    assert intent.trigger is not None
    assert intent.trigger.service == "gmail"
    assert intent.trigger.node_type == "n8n-nodes-base.gmailTrigger"
    # email_provider must NOT be asked
    q_fields = [q.field_key for q in intent.clarification_questions]
    assert "email_provider" not in q_fields
    assert "email_provider" not in intent.outstanding_questions


def test_google_sheets_trigger_does_not_ask_email_question():
    """Verify 'When a new row is added to Google Sheets, notify me on Telegram' does not ask an email question."""
    extractor = WorkflowIntentExtractor()
    intent = extractor.analyze(
        user_prompt="When a new row is added to Google Sheets, notify me on Telegram",
        history=[],
        accumulated_slots={},
    )
    assert intent.trigger is not None
    assert intent.trigger.service == "google sheets"
    assert intent.trigger.node_type == "n8n-nodes-base.googleSheetsTrigger"
    q_fields = [q.field_key for q in intent.clarification_questions]
    assert "email_provider" not in q_fields
    assert "trigger" not in q_fields


def test_schedule_trigger_identifies_schedule_rather_than_email():
    """Verify 'Every morning, send me a Telegram report' identifies schedule rather than asking about email."""
    extractor = WorkflowIntentExtractor()
    intent = extractor.analyze(
        user_prompt="Every morning, send me a Telegram report",
        history=[],
        accumulated_slots={},
    )
    assert intent.trigger is not None
    assert intent.trigger.service == "schedule"
    assert intent.trigger.node_type == "n8n-nodes-base.scheduleTrigger"
    q_fields = [q.field_key for q in intent.clarification_questions]
    assert "email_provider" not in q_fields


def test_webhook_to_slack_does_not_ask_unrelated_trigger_question():
    """Verify 'When a webhook receives an order, notify Slack' does not ask an unrelated trigger question."""
    extractor = WorkflowIntentExtractor()
    intent = extractor.analyze(
        user_prompt="When a webhook receives an order, notify Slack",
        history=[],
        accumulated_slots={},
    )
    assert intent.trigger is not None
    assert intent.trigger.service == "webhook"
    assert intent.trigger.node_type == "n8n-nodes-base.webhook"
    assert len(intent.actions) > 0
    assert intent.actions[0].service == "slack"
    q_fields = [q.field_key for q in intent.clarification_questions]
    assert "email_provider" not in q_fields
    assert "trigger" not in q_fields


def test_action_email_not_confused_with_trigger_email():
    """Verify 'When a new row is added to Google Sheets, email me an alert' treats Google Sheets as trigger."""
    extractor = WorkflowIntentExtractor()
    intent = extractor.analyze(
        user_prompt="When a new row is added to Google Sheets, email me an alert",
        history=[],
        accumulated_slots={},
    )
    assert intent.trigger is not None
    assert intent.trigger.service == "google sheets"
    assert intent.trigger.node_type == "n8n-nodes-base.googleSheetsTrigger"
    q_fields = [q.field_key for q in intent.clarification_questions]
    assert "email_provider" not in q_fields


@pytest.mark.asyncio
async def test_orchestrator_handles_list_wrapped_workflow_without_crash():
    """Verify that when the LLM returns a single workflow wrapped in a list (e.g. [wf_google_sheets]),
    the orchestrator normalizes it cleanly and completes generation without the input_type=list crash.
    """
    conv_id = str(uuid.uuid4())
    conv = Conversation(
        id=conv_id,
        title="Google Sheets List Wrapped Test",
        metadata_json={"state": None, "slots": {"telegram_chat_id": "123456789", "google_sheets_document": "test_doc"}},
    )

    sheets_tg_ir = make_google_sheets_telegram_ir(
        workflow_id="wf_google_sheets_list_wrapped",
        chat_id="123456789",
    )
    list_wrapped_response = [sheets_tg_ir]

    async def mock_llm_complete(req):
        content_str = req.messages[0].content
        if "Requirements Analysis" in content_str:
            return LLMResponse(
                content=json.dumps({"has_ambiguities": False, "questions": []}),
                usage=TokenUsage(),
                provider="openrouter",
                model="nvidia/nemotron-3-super-120b-a12b:free",
                finish_reason="stop",
                key_alias="OPENROUTER_KEY_1",
            )
        return LLMResponse(
            content=json.dumps(list_wrapped_response),
            usage=TokenUsage(),
            provider="openrouter",
            model="nvidia/nemotron-3-super-120b-a12b:free",
            finish_reason="stop",
            key_alias="OPENROUTER_KEY_1",
        )

    mock_llm = MagicMock(spec=LLMProviderManager)
    mock_llm.complete = AsyncMock(side_effect=mock_llm_complete)
    orchestrator = WorkflowOrchestrator(llm_manager=mock_llm)
    session = MockAsyncSession(conversation=conv, messages=[])

    res = await orchestrator.execute_turn(
        conversation_id=conv_id,
        user_message_text="When a new row is added to Google Sheets, send me a notification on Telegram.",
        db=session,
    )

    assert res.state == ConversationState.READY
    assert res.workflow_ir is not None
    assert res.workflow_ir["id"] == "wf_google_sheets_list_wrapped"
    assert len(res.workflow_ir["nodes"]) == 2
    assert res.compiled_json is not None


@pytest.mark.asyncio
async def test_telegram_category_selection_without_custom_text_does_not_repeat():
    """Verify selecting 'private_chat' without custom text satisfies the slot and does not repeat the question."""
    conv_id = str(uuid.uuid4())
    conv = Conversation(
        id=conv_id,
        title="Telegram Destination Test",
        metadata_json={"state": None, "slots": {"google_sheets_document": "test_doc"}},
    )

    sheets_tg_ir = make_google_sheets_telegram_ir(
        workflow_id="wf_sheets_tg_cat",
        chat_id="={{ '<YOUR_TELEGRAM_CHAT_ID>' }}",
    )

    async def mock_llm_complete(req):
        content_str = req.messages[0].content
        if "Requirements Analysis" in content_str:
            return LLMResponse(
                content=json.dumps({"has_ambiguities": False, "questions": []}),
                usage=TokenUsage(),
                provider="openrouter",
                model="nvidia/nemotron-3-super-120b-a12b:free",
                finish_reason="stop",
                key_alias="OPENROUTER_KEY_1",
            )
        return LLMResponse(
            content=json.dumps(sheets_tg_ir),
            usage=TokenUsage(),
            provider="openrouter",
            model="nvidia/nemotron-3-super-120b-a12b:free",
            finish_reason="stop",
            key_alias="OPENROUTER_KEY_1",
        )

    mock_llm = MagicMock(spec=LLMProviderManager)
    mock_llm.complete = AsyncMock(side_effect=mock_llm_complete)
    orchestrator = WorkflowOrchestrator(llm_manager=mock_llm)
    session = MockAsyncSession(conversation=conv, messages=[])

    # Turn 1: user prompt asks for Google Sheets to Telegram
    res1 = await orchestrator.execute_turn(
        conversation_id=conv_id,
        user_message_text="When a new row is added to Google Sheets, send a notification to Telegram.",
        db=session,
    )
    assert res1.state == ConversationState.CLARIFYING
    assert res1.clarification is not None
    q_fields = [q.field_key for q in res1.clarification.questions]
    assert "telegram_chat_id" in q_fields

    # Turn 2: user selects 'private_chat' with NO custom text
    res2 = await orchestrator.execute_turn(
        conversation_id=conv_id,
        user_message_text="",
        db=session,
        clarification_answers=[
            ClarificationAnswerItem(
                question_id="telegram_chat_id",
                field_key="telegram_chat_id",
                selected_value="private_chat",
                custom_text=None,
            )
        ],
    )

    # Must advance to READY and NOT repeat the telegram question
    assert res2.state == ConversationState.READY
    assert res2.workflow_ir is not None


@pytest.mark.asyncio
async def test_orchestrator_handles_list_wrapped_repair_workflow():
    """Verify that when the repair LLM returns a list-wrapped workflow, it is properly normalized."""
    conv_id = str(uuid.uuid4())
    conv = Conversation(
        id=conv_id,
        title="Repair List Wrapped Test",
        metadata_json={"state": None, "slots": {"telegram_chat_id": "123456789", "google_sheets_document": "test_doc"}},
    )

    # Broken initial IR (uses manualTrigger instead of googleSheetsTrigger)
    broken_initial_ir = {
        "id": "wf_initial_broken",
        "name": "Broken Workflow",
        "nodes": [
            {
                "id": "node_manual",
                "name": "Manual",
                "node_type": "n8n-nodes-base.manualTrigger",
                "type_version": 1.0,
            },
            {
                "id": "node_telegram",
                "name": "Telegram",
                "node_type": "n8n-nodes-base.telegram",
                "type_version": 1.2,
                "parameters": {"resource": "message", "operation": "sendMessage", "chatId": "123456789"},
                "credentials": {"telegramApi": {"id": "1", "name": "Telegram account"}},
            },
        ],
        "edges": [{"source_id": "node_manual", "target_id": "node_telegram"}],
    }

    # Fixed repaired IR wrapped in a 1-item list
    repaired_ir = make_google_sheets_telegram_ir(
        workflow_id="wf_repaired_clean",
        chat_id="123456789",
    )

    call_count = 0

    async def mock_llm_complete(req):
        nonlocal call_count
        call_count += 1
        content_str = req.messages[0].content
        if "Repair Engine" in content_str:
            # Repair returns list-wrapped workflow
            return LLMResponse(
                content=json.dumps([repaired_ir]),
                usage=TokenUsage(),
                provider="openrouter",
                model="nvidia/nemotron-3-super-120b-a12b:free",
                finish_reason="stop",
                key_alias="OPENROUTER_KEY_1",
            )
        # Initial generation returns broken IR
        return LLMResponse(
            content=json.dumps(broken_initial_ir),
            usage=TokenUsage(),
            provider="openrouter",
            model="nvidia/nemotron-3-super-120b-a12b:free",
            finish_reason="stop",
            key_alias="OPENROUTER_KEY_1",
        )

    mock_llm = MagicMock(spec=LLMProviderManager)
    mock_llm.complete = AsyncMock(side_effect=mock_llm_complete)
    orchestrator = WorkflowOrchestrator(llm_manager=mock_llm)
    session = MockAsyncSession(conversation=conv, messages=[])

    res = await orchestrator.execute_turn(
        conversation_id=conv_id,
        user_message_text="When a new row is added to Google Sheets, send me a notification on Telegram.",
        db=session,
    )

    assert res.state == ConversationState.READY
    assert res.workflow_ir is not None
    assert res.workflow_ir["id"] == "wf_repaired_clean"






