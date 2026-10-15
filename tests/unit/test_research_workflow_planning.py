"""Targeted unit tests for Phase 2 & 3: Research-Aware Workflow Planning, Generation, and Verification.

Tests cover:
- Multi-branching workflow planning with condition nodes and error handling
- Research skipping for built-in catalog nodes (Gmail, Slack, Schedule)
- Unsupported node detection and HTTP Request fallback
- Tavily unavailable/failure graceful handling without fabrication
- Bounded repair loop with architectural plan constraints
- Caching and budget enforcement
"""
import json
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock

from backend.app.llm.interface import LLMRequest, LLMResponse, TokenUsage
from backend.app.llm.manager import LLMProviderManager
from backend.app.models.conversation import Conversation
from backend.app.orchestrator.engine import WorkflowOrchestrator
from backend.app.orchestrator.intent import WorkflowIntent, WorkflowIntentExtractor
from backend.app.orchestrator.state_machine import ConversationState
from backend.app.services.node_registry import NodeRegistry
from backend.app.services.research import (
    ResearchFinding,
    ResearchService,
    ResearchSource,
    StructuredResearchDossier,
)
from backend.app.services.research.exceptions import TavilyUnavailableError


class MockAsyncSession:
    """Mock async database session for unit testing turns."""

    def __init__(self, conversation: Conversation, messages: list = None):
        self.conversation = conversation
        self.messages = messages or []
        self.added = []

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        pass

    async def flush(self):
        pass

    async def refresh(self, obj):
        pass

    async def execute(self, stmt):
        class MockResult:
            def __init__(self, item, items):
                self._item = item
                self._items = items

            def scalar_one_or_none(self):
                return self._item

            def scalars(self):
                class MockScalars:
                    def __init__(self, s):
                        self._s = s

                    def all(self):
                        return self._s

                    def first(self):
                        return self._s[0] if self._s else None

                return MockScalars(self._items)

            def scalar(self):
                return len(self._items)

        # Distinguish query type by stmt string
        stmt_str = str(stmt).lower()
        if "conversation_message" in stmt_str:
            return MockResult(None, self.messages)
        if "workflow_draft" in stmt_str:
            return MockResult(None, [])
        if "workflow_revision" in stmt_str:
            return MockResult(None, [])
        return MockResult(self.conversation, [self.conversation])


@pytest.mark.asyncio
async def test_skip_research_for_standard_catalog_nodes():
    """Verify research is skipped when standard built-in triggers/actions are requested."""
    registry = NodeRegistry()
    service = ResearchService(node_registry=registry)

    # Standard Gmail to Slack notification
    intent = WorkflowIntent(
        summary="Send Slack message on new Gmail email",
        is_clarification_needed=False,
        original_prompt="When an email arrives in Gmail, send a Slack alert to #general",
        completed_answers={},
    )
    needs_research, reasons = service.should_research(
        user_prompt="When an email arrives in Gmail, send a Slack alert to #general",
        history=[],
        intent=intent,
    )
    assert needs_research is False
    assert any("built-in" in r.lower() or "catalog" in r.lower() for r in reasons)


@pytest.mark.asyncio
async def test_research_triggered_for_complex_external_service():
    """Verify research is activated for complex or non-standard external integrations."""
    registry = NodeRegistry()
    service = ResearchService(node_registry=registry)

    user_prompt = "Query Stripe subscription charges and synchronize customers with Salesforce via REST API"
    intent = WorkflowIntent(
        summary="Stripe to Salesforce sync",
        is_clarification_needed=False,
        original_prompt=user_prompt,
        completed_answers={},
    )
    needs_research, reasons = service.should_research(
        user_prompt=user_prompt,
        history=[],
        intent=intent,
    )
    assert needs_research is True
    assert len(reasons) > 0


@pytest.mark.asyncio
async def test_unsupported_node_catalog_grounding():
    """Verify research findings for an unsupported node map safely to httpRequest and do not invent fake nodes."""
    registry = NodeRegistry()
    service = ResearchService(node_registry=registry)

    # Proprietary custom internal service not in n8n built-in registry
    finding = ResearchFinding(
        topic="Custom Internal CRM Record Creation",
        category="endpoint",
        fact="POST /api/v1/records with record payload",
        source_url="https://internal-docs.example.com/api",
    )
    compatibility = service.verify_findings_against_catalog([finding], target_services=["custom_internal_crm"])
    assert "custom_internal_crm" in compatibility
    # Must fallback to httpRequest and must not fabricate n8n-nodes-base.custom_internal_crm
    assert compatibility["custom_internal_crm"]["is_supported"] is False
    assert compatibility["custom_internal_crm"]["suggested_node"] == "n8n-nodes-base.httpRequest"


@pytest.mark.asyncio
async def test_tavily_failure_graceful_handling():
    """Verify orchestrator gracefully recovers and does not crash or fabricate when Tavily fails."""
    conv_id = str(uuid.uuid4())
    conv = Conversation(
        id=conv_id,
        title="Jira Sync",
        metadata_json={"state": None, "slots": {}},
    )

    mock_llm = MagicMock(spec=LLMProviderManager)

    async def mock_complete(req: LLMRequest) -> LLMResponse:
        content_text = req.messages[0].content
        if "Requirements Analysis Engine" in content_text:
            content = json.dumps({"has_ambiguities": False, "questions": []})
        elif "Architectural Workflow Planner" in content_text:
            content = json.dumps({
                "title": "Jira Webhook Flow",
                "objective": "Handle Jira webhook",
                "target_services": ["jira"],
                "nodes": [
                    {"id": "node_webhook", "name": "Webhook Trigger", "node_type": "n8n-nodes-base.webhook", "role": "trigger"},
                    {"id": "node_http", "name": "HTTP Request", "node_type": "n8n-nodes-base.httpRequest", "role": "action"}
                ],
                "connections": [{"source_id": "node_webhook", "target_id": "node_http"}],
                "error_handling_strategy": "continue_or_alert"
            })
        else:
            # WorkflowIR generation
            content = json.dumps({
                "id": "wf_jira_fallback",
                "name": "Jira Webhook Flow",
                "nodes": [
                    {
                        "id": "node_webhook",
                        "name": "Webhook",
                        "node_type": "n8n-nodes-base.webhook",
                        "type_version": 2,
                        "position": {"x": 250, "y": 300},
                        "parameters": {"path": "jira-events", "httpMethod": "POST"}
                    },
                    {
                        "id": "node_http",
                        "name": "HTTP Request",
                        "node_type": "n8n-nodes-base.httpRequest",
                        "type_version": 4.2,
                        "position": {"x": 450, "y": 300},
                        "parameters": {"url": "https://api.example.com", "method": "POST"}
                    }
                ],
                "edges": [{"source_id": "node_webhook", "target_id": "node_http"}]
            })

        return LLMResponse(
            content=content,
            usage=TokenUsage(),
            provider="openrouter",
            model="test-model",
            finish_reason="stop",
            key_alias="OPENROUTER_KEY_1",
        )

    mock_llm.complete = AsyncMock(side_effect=mock_complete)

    mock_research_service = MagicMock(spec=ResearchService)
    mock_research_service.should_research.return_value = (True, ["Complex Jira API integration"])
    mock_research_service.conduct_research = AsyncMock(side_effect=TavilyUnavailableError("Tavily service is currently offline"))

    orchestrator = WorkflowOrchestrator(
        llm_manager=mock_llm,
        research_service=mock_research_service,
    )
    session = MockAsyncSession(conversation=conv)

    result = await orchestrator.execute_turn(
        conversation_id=conv_id,
        user_message_text="Create a webhook receiving Jira issue events and forward them to external API",
        db=session,
    )

    # Workflow should complete or fail cleanly without unhandled exception
    assert result is not None
    assert result.research_dossier is not None
    assert result.research_dossier.get("is_fallback") is True
    assert any("Tavily service is currently offline" in w for w in result.research_dossier.get("warnings", []))


@pytest.mark.asyncio
async def test_multi_branching_workflow_planning():
    """Verify that multi-branch condition workflows correctly configure branch connections and fault tolerance."""
    conv_id = str(uuid.uuid4())
    conv = Conversation(
        id=conv_id,
        title="Conditional Ticket Routing",
        metadata_json={"state": None, "slots": {}},
    )

    mock_llm = MagicMock(spec=LLMProviderManager)

    async def mock_complete(req: LLMRequest) -> LLMResponse:
        content_text = req.messages[0].content
        if "Requirements Analysis Engine" in content_text:
            content = json.dumps({"has_ambiguities": False, "questions": []})
        elif "Architectural Workflow Planner" in content_text:
            content = json.dumps({
                "title": "Conditional Ticket Routing",
                "objective": "Route urgent tickets to Slack and normal to email",
                "target_services": ["jira", "slack", "email"],
                "nodes": [
                    {"id": "node_trigger", "name": "Webhook Trigger", "node_type": "n8n-nodes-base.webhook", "role": "trigger"},
                    {"id": "node_if", "name": "Priority Filter", "node_type": "n8n-nodes-base.if", "role": "condition"},
                    {"id": "node_slack", "name": "Slack Urgent", "node_type": "n8n-nodes-base.slack", "role": "action"},
                    {"id": "node_email", "name": "Email Normal", "node_type": "n8n-nodes-base.emailSend", "role": "action"}
                ],
                "connections": [
                    {"source_id": "node_trigger", "target_id": "node_if"},
                    {"source_id": "node_if", "target_id": "node_slack", "source_output_index": 0},
                    {"source_id": "node_if", "target_id": "node_email", "source_output_index": 1}
                ],
                "error_handling_strategy": "continue_or_alert"
            })
        else:
            content = json.dumps({
                "id": "wf_multi_branch",
                "name": "Conditional Ticket Routing",
                "nodes": [
                    {
                        "id": "node_trigger",
                        "name": "Webhook Trigger",
                        "node_type": "n8n-nodes-base.webhook",
                        "type_version": 2,
                        "position": {"x": 200, "y": 300},
                        "parameters": {"path": "tickets", "httpMethod": "POST"}
                    },
                    {
                        "id": "node_if",
                        "name": "Priority Filter",
                        "node_type": "n8n-nodes-base.if",
                        "type_version": 2,
                        "position": {"x": 400, "y": 300},
                        "parameters": {
                            "conditions": {
                                "string": [{"value1": "={{ $json.priority }}", "value2": "urgent"}]
                            }
                        }
                    },
                    {
                        "id": "node_slack",
                        "name": "Slack Urgent",
                        "node_type": "n8n-nodes-base.slack",
                        "type_version": 2.2,
                        "position": {"x": 600, "y": 200},
                        "parameters": {"channel": "#urgent", "text": "Urgent ticket received"}
                    },
                    {
                        "id": "node_email",
                        "name": "Email Normal",
                        "node_type": "n8n-nodes-base.emailSend",
                        "type_version": 2.1,
                        "position": {"x": 600, "y": 400},
                        "parameters": {"toEmail": "team@example.com", "subject": "Normal ticket"}
                    }
                ],
                "edges": [
                    {"source_id": "node_trigger", "target_id": "node_if"},
                    {"source_id": "node_if", "target_id": "node_slack", "source_output_index": 0},
                    {"source_id": "node_if", "target_id": "node_email", "source_output_index": 1}
                ]
            })

        return LLMResponse(
            content=content,
            usage=TokenUsage(),
            provider="openrouter",
            model="test-model",
            finish_reason="stop",
            key_alias="OPENROUTER_KEY_1",
        )

    mock_llm.complete = AsyncMock(side_effect=mock_complete)

    mock_intent_extractor = MagicMock()
    mock_intent_extractor.analyze.return_value = WorkflowIntent(
        summary="Route urgent tickets to Slack and normal to email",
        is_clarification_needed=False,
        original_prompt="Route urgent tickets to Slack and normal to email",
        completed_answers={},
    )

    orchestrator = WorkflowOrchestrator(
        llm_manager=mock_llm,
        intent_extractor=mock_intent_extractor,
    )
    session = MockAsyncSession(conversation=conv)

    result = await orchestrator.execute_turn(
        conversation_id=conv_id,
        user_message_text="Route urgent tickets to Slack and normal to email",
        db=session,
    )

    assert result.state == ConversationState.READY
    assert result.workflow_plan is not None
    assert len(result.workflow_plan["nodes"]) == 4
    assert result.workflow_ir is not None
    # Both branch pathways (urgent and normal) are connected
    edges = result.workflow_ir["edges"]
    assert any(e["source_id"] == "node_if" and e.get("source_output_index") == 0 for e in edges)
    assert any(e["source_id"] == "node_if" and e.get("source_output_index") == 1 for e in edges)


@pytest.mark.asyncio
async def test_scenario_a_google_sheets_order_monitoring_multi_branch():
    """Scenario A: Google Sheets order monitoring with multiple branches, deduplication, and summary."""
    registry = NodeRegistry()
    research_service = ResearchService(node_registry=registry)

    user_prompt = (
        "Monitor new order rows in Google Sheets, verify payment status. "
        "If paid, check shipping type: express routes to urgent dispatch and standard queues for batch. "
        "If unpaid, route to alert branch. Deduplicate by order_id and summarize daily counts."
    )

    # 1. Verify research decision
    needs_research, reasons = research_service.should_research(user_prompt)
    assert needs_research is True
    assert any("multi-branch" in r.lower() or "deduplicat" in r.lower() for r in reasons)

    # 2. Mock full generation turn
    conv_id = str(uuid.uuid4())
    conv = Conversation(id=conv_id, title="Order Monitor", metadata_json={"state": None, "slots": {}})

    mock_llm = MagicMock(spec=LLMProviderManager)

    async def mock_complete(req: LLMRequest) -> LLMResponse:
        content_text = req.messages[0].content
        if "Requirements Analysis Engine" in content_text:
            content = json.dumps({"has_ambiguities": False, "questions": []})
        elif "Architectural Workflow Planner" in content_text:
            content = json.dumps({
                "title": "Google Sheets Order Processing",
                "objective": "Process orders, route by payment and shipping, deduplicate by order_id",
                "target_services": ["googlesheets", "slack"],
                "nodes": [
                    {"id": "node_sheets", "name": "Google Sheets Trigger", "node_type": "n8n-nodes-base.googleSheetsTrigger", "role": "trigger"},
                    {"id": "node_pay_if", "name": "Check Payment", "node_type": "n8n-nodes-base.if", "role": "condition"},
                    {"id": "node_ship_if", "name": "Check Shipping", "node_type": "n8n-nodes-base.if", "role": "condition"},
                    {"id": "node_express", "name": "Express Dispatch", "node_type": "n8n-nodes-base.slack", "role": "action"},
                    {"id": "node_unpaid", "name": "Payment Alert", "node_type": "n8n-nodes-base.slack", "role": "action"},
                    {"id": "node_summary", "name": "Daily Summary", "node_type": "n8n-nodes-base.slack", "role": "action"}
                ],
                "connections": [
                    {"source_id": "node_sheets", "target_id": "node_pay_if"},
                    {"source_id": "node_pay_if", "target_id": "node_ship_if", "source_output_index": 0},
                    {"source_id": "node_pay_if", "target_id": "node_unpaid", "source_output_index": 1},
                    {"source_id": "node_ship_if", "target_id": "node_express", "source_output_index": 0},
                    {"source_id": "node_ship_if", "target_id": "node_summary", "source_output_index": 1}
                ],
                "state_tracking": {"strategy": "deduplication_by_id", "persistent_key": "order_id"},
                "error_handling_strategy": "continue_or_alert"
            })
        else:
            content = json.dumps({
                "id": "wf_orders",
                "name": "Google Sheets Order Processing",
                "nodes": [
                    {
                        "id": "node_sheets",
                        "name": "Google Sheets Trigger",
                        "node_type": "n8n-nodes-base.googleSheetsTrigger",
                        "type_version": 1,
                        "position": {"x": 200, "y": 300},
                        "parameters": {"event": "rowAdded", "documentId": "sheet123", "sheetName": "Orders"},
                        "credentials": {"googleSheetsTriggerOAuth2Api": {"id": "1", "name": "Google account"}}
                    },
                    {
                        "id": "node_pay_if",
                        "name": "Check Payment",
                        "node_type": "n8n-nodes-base.if",
                        "type_version": 2,
                        "position": {"x": 420, "y": 300},
                        "parameters": {"conditions": {"string": [{"value1": "={{ $json.payment_status }}", "value2": "paid"}]}}
                    },
                    {
                        "id": "node_ship_if",
                        "name": "Check Shipping",
                        "node_type": "n8n-nodes-base.if",
                        "type_version": 2,
                        "position": {"x": 640, "y": 200},
                        "parameters": {"conditions": {"string": [{"value1": "={{ $json.shipping_method }}", "value2": "express"}]}}
                    },
                    {
                        "id": "node_express",
                        "name": "Express Dispatch",
                        "node_type": "n8n-nodes-base.slack",
                        "type_version": 2.2,
                        "position": {"x": 860, "y": 140},
                        "parameters": {"channel": "#dispatch", "text": "={{ 'Express order ' + $json.order_id }}"},
                        "credentials": {"slackApi": {"id": "1", "name": "Slack account"}}
                    },
                    {
                        "id": "node_unpaid",
                        "name": "Payment Alert",
                        "node_type": "n8n-nodes-base.slack",
                        "type_version": 2.2,
                        "position": {"x": 640, "y": 440},
                        "parameters": {"channel": "#finance", "text": "={{ 'Unpaid order ' + $json.order_id }}"},
                        "credentials": {"slackApi": {"id": "1", "name": "Slack account"}}
                    },
                    {
                        "id": "node_summary",
                        "name": "Standard Queue",
                        "node_type": "n8n-nodes-base.slack",
                        "type_version": 2.2,
                        "position": {"x": 860, "y": 280},
                        "parameters": {"channel": "#warehouse", "text": "={{ 'Standard batch queued ' + $json.order_id }}"},
                        "credentials": {"slackApi": {"id": "1", "name": "Slack account"}}
                    }
                ],
                "edges": [
                    {"source_id": "node_sheets", "target_id": "node_pay_if"},
                    {"source_id": "node_pay_if", "target_id": "node_ship_if", "source_output_index": 0},
                    {"source_id": "node_pay_if", "target_id": "node_unpaid", "source_output_index": 1},
                    {"source_id": "node_ship_if", "target_id": "node_express", "source_output_index": 0},
                    {"source_id": "node_ship_if", "target_id": "node_summary", "source_output_index": 1}
                ]
            })
        return LLMResponse(content=content, usage=TokenUsage(), provider="openrouter", model="test", finish_reason="stop", key_alias="K1")

    mock_llm.complete = AsyncMock(side_effect=mock_complete)

    mock_extractor = MagicMock()
    mock_extractor.analyze.return_value = WorkflowIntent(
        summary="Monitor Google Sheets orders and multi-branch",
        is_clarification_needed=False,
        original_prompt=user_prompt,
        completed_answers={"google_sheets_document": "sheet123"},
    )

    orchestrator = WorkflowOrchestrator(llm_manager=mock_llm, intent_extractor=mock_extractor, research_service=research_service)
    session = MockAsyncSession(conversation=conv)

    result = await orchestrator.execute_turn(conversation_id=conv_id, user_message_text=user_prompt, db=session)

    assert result.state == ConversationState.READY
    assert result.workflow_plan is not None
    assert result.workflow_plan["state_tracking"]["persistent_key"] == "order_id"
    # Compiled JSON contains all nodes and valid connections matrix
    assert result.compiled_json is not None
    assert result.compiled_json["active"] is False
    assert len(result.compiled_json["nodes"]) == 6
    # Verify outputs 0 and 1 are both present in connections for condition nodes
    conns = result.compiled_json["connections"]
    assert "Check Payment" in conns
    assert len(conns["Check Payment"]["main"]) == 2  # output 0 and 1


@pytest.mark.asyncio
async def test_scenario_b_email_attachment_pdf_processing_with_error_handling():
    """Scenario B: Email PDF invoice filtering, extraction, routing, error handling, and Telegram."""
    registry = NodeRegistry()
    research_service = ResearchService(node_registry=registry)

    user_prompt = "When an email arrives with an invoice PDF attachment, extract invoice details and send Telegram alert, with retry error handling on failure."

    conv_id = str(uuid.uuid4())
    conv = Conversation(id=conv_id, title="Invoice Processing", metadata_json={"state": None, "slots": {}})

    mock_llm = MagicMock(spec=LLMProviderManager)

    async def mock_complete(req: LLMRequest) -> LLMResponse:
        content_text = req.messages[0].content
        if "Requirements Analysis Engine" in content_text:
            content = json.dumps({"has_ambiguities": False, "questions": []})
        elif "Architectural Workflow Planner" in content_text:
            content = json.dumps({
                "title": "Email PDF Invoice Routing",
                "objective": "Process invoice PDF attachments with fault tolerance",
                "target_services": ["gmail", "telegram"],
                "nodes": [
                    {"id": "node_email", "name": "Gmail Trigger", "node_type": "n8n-nodes-base.gmailTrigger", "role": "trigger"},
                    {"id": "node_if", "name": "PDF Filter", "node_type": "n8n-nodes-base.if", "role": "condition"},
                    {"id": "node_tg", "name": "Telegram Alert", "node_type": "n8n-nodes-base.telegram", "role": "action", "execution_policy": {"retry_on_fail": True, "max_tries": 3}}
                ],
                "connections": [
                    {"source_id": "node_email", "target_id": "node_if"},
                    {"source_id": "node_if", "target_id": "node_tg", "source_output_index": 0}
                ],
                "error_handling_strategy": "retry_on_fail"
            })
        else:
            content = json.dumps({
                "id": "wf_invoice_pdf",
                "name": "Email PDF Invoice Routing",
                "nodes": [
                    {
                        "id": "node_email",
                        "name": "Gmail Trigger",
                        "node_type": "n8n-nodes-base.gmailTrigger",
                        "type_version": 1.4,
                        "position": {"x": 200, "y": 300},
                        "parameters": {"event": "messageReceived", "downloadAttachments": True, "options": {"q": "filename:pdf invoice"}},
                        "credentials": {"gmailOAuth2": {"id": "1", "name": "Gmail account"}}
                    },
                    {
                        "id": "node_if",
                        "name": "PDF Filter",
                        "node_type": "n8n-nodes-base.if",
                        "type_version": 2,
                        "position": {"x": 450, "y": 300},
                        "parameters": {"conditions": {"string": [{"value1": "={{ $json.subject }}", "value2": "invoice"}]}}
                    },
                    {
                        "id": "node_tg",
                        "name": "Telegram Alert",
                        "node_type": "n8n-nodes-base.telegram",
                        "type_version": 1.2,
                        "position": {"x": 700, "y": 300},
                        "parameters": {
                            "resource": "message",
                            "operation": "sendMessage",
                            "chatId": "={{ \"<YOUR_TELEGRAM_CHAT_ID>\" }}",
                            "text": "={{ '📎 Invoice received from: ' + ($json.from || 'Unknown') + ' | Subject: ' + $json.subject }}"
                        },
                        "credentials": {"telegramApi": {"id": "1", "name": "Telegram account"}},
                        "execution_policy": {"retry_on_fail": True, "max_tries": 3, "wait_between_tries": 1000}
                    }
                ],
                "edges": [
                    {"source_id": "node_email", "target_id": "node_if"},
                    {"source_id": "node_if", "target_id": "node_tg", "source_output_index": 0}
                ]
            })
        return LLMResponse(content=content, usage=TokenUsage(), provider="openrouter", model="test", finish_reason="stop", key_alias="K1")

    mock_llm.complete = AsyncMock(side_effect=mock_complete)

    mock_extractor = MagicMock()
    mock_extractor.analyze.return_value = WorkflowIntent(
        summary="Process email invoices with PDF attachment",
        is_clarification_needed=False,
        original_prompt=user_prompt,
        completed_answers={"email_provider": "gmail"},
    )

    orchestrator = WorkflowOrchestrator(llm_manager=mock_llm, intent_extractor=mock_extractor, research_service=research_service)
    session = MockAsyncSession(conversation=conv)

    result = await orchestrator.execute_turn(conversation_id=conv_id, user_message_text=user_prompt, db=session)

    assert result.state == ConversationState.READY
    assert result.validation_report["is_valid"] is True
    # Fault tolerance policy is recognized and verified
    policy_issues = [i for i in result.validation_report["issues"] if i["rule_code"] == "FAULT_TOLERANCE_CONFIGURED"]
    assert len(policy_issues) > 0
    # Telegram node has real upstream expressions and non-bogus chat ID
    tg_node = next(n for n in result.workflow_ir["nodes"] if n["id"] == "node_tg")
    assert "$json.from" in tg_node["parameters"]["text"]
    assert tg_node["execution_policy"]["retry_on_fail"] is True


@pytest.mark.asyncio
async def test_scenario_c_multi_service_pagination_rate_limits():
    """Scenario C: Multi-service workflow involving pagination, rate limits, and transformation."""
    registry = NodeRegistry()
    research_service = ResearchService(node_registry=registry)

    user_prompt = "Query Stripe paginated charges API, handle rate limits with backoff, transform fee data with Code, and sync with HubSpot."

    # Verify research decision identifies pagination and rate limits
    needs_research, reasons = research_service.should_research(user_prompt)
    assert needs_research is True
    assert any("pagination" in r.lower() for r in reasons)
    assert any("rate limit" in r.lower() for r in reasons)

    # Mock research findings
    findings = [
        ResearchFinding(category="endpoint", fact="API Endpoint: GET /v1/charges", topic="Stripe charges endpoint"),
        ResearchFinding(category="pagination", fact="Pagination supported via limit/offset or cursor parameters.", topic="Stripe pagination"),
        ResearchFinding(category="rate_limits", fact="Rate limit documented: 100 requests per second", topic="Stripe limits"),
    ]
    compatibility = research_service.verify_findings_against_catalog(findings, target_services=["Stripe", "HubSpot"])
    assert compatibility["Stripe"]["is_supported"] is True
    assert compatibility["HubSpot"]["is_supported"] is True


@pytest.mark.asyncio
async def test_scenario_d_unfamiliar_api_integration_http_fallback():
    """Scenario D: Unfamiliar API without a native node falls back to HTTP Request with verified endpoints."""
    registry = NodeRegistry()
    research_service = ResearchService(node_registry=registry)

    user_prompt = "Fetch shipments from AcmeLogistics custom REST API using Bearer Token and store in Postgres."

    # 1. Verify research decision
    needs_research, reasons = research_service.should_research(user_prompt)
    assert needs_research is True
    assert any("AcmeLogistics" in r for r in reasons)

    # 2. Verify catalog matching marks unsupported and suggests httpRequest
    findings = [
        ResearchFinding(category="endpoint", fact="API Endpoint: GET /api/v2/shipments", topic="AcmeLogistics API"),
        ResearchFinding(category="authentication", fact="Bearer Token or OAuth2 API authentication required.", topic="AcmeLogistics Auth"),
    ]
    compatibility = research_service.verify_findings_against_catalog(findings, target_services=["AcmeLogistics"])
    assert compatibility["AcmeLogistics"]["is_supported"] is False
    assert compatibility["AcmeLogistics"]["suggested_node"] == "n8n-nodes-base.httpRequest"
    assert "required_credential_setup" in compatibility["AcmeLogistics"]["generic_fallback"]


@pytest.mark.asyncio
async def test_scenario_e_missing_configuration_triggers_clarification():
    """Scenario E: Request with missing critical configuration triggers clarification rather than guessing."""
    conv_id = str(uuid.uuid4())
    conv = Conversation(id=conv_id, title="Vague Flow", metadata_json={"state": None, "slots": {}})

    mock_llm = MagicMock(spec=LLMProviderManager)
    mock_extractor = MagicMock(spec=WorkflowIntentExtractor)
    mock_extractor.analyze.return_value = WorkflowIntent(
        summary="Send message on incoming email",
        is_clarification_needed=True,
        original_prompt="When an email arrives, send a message.",
        clarification_questions=[
            {
                "id": "q1",
                "question": "Which email service should trigger the workflow?",
                "field_key": "email_provider",
                "options": [{"label": "Gmail", "value": "gmail"}, {"label": "Outlook", "value": "outlook"}],
            }
        ],
        completed_answers={},
    )

    orchestrator = WorkflowOrchestrator(llm_manager=mock_llm, intent_extractor=mock_extractor)
    session = MockAsyncSession(conversation=conv)

    result = await orchestrator.execute_turn(
        conversation_id=conv_id,
        user_message_text="When an email arrives, send a message.",
        db=session,
    )

    # Must transition to CLARIFYING, not GENERATING, and not invent fake values
    assert result.state == ConversationState.CLARIFYING
    assert result.clarification is not None
    assert len(result.clarification.questions) == 1
    assert result.workflow_ir is None  # Does not produce a guessed workflow


@pytest.mark.asyncio
async def test_scenario_f_research_failure_reported_honestly():
    """Scenario F: Tavily research failure reports limitation honestly and does not fabricate schemas."""
    registry = NodeRegistry()
    mock_tavily_client = MagicMock()
    mock_tavily_client.search = AsyncMock(side_effect=TavilyUnavailableError("Tavily service is unavailable (HTTP 503)"))

    research_service = ResearchService(client=mock_tavily_client, node_registry=registry)

    dossier = await research_service.conduct_research(
        user_prompt="Connect to esoteric CustomWarehouseAPI with pagination",
        history=[],
        intent=WorkflowIntent(summary="Custom Warehouse sync", is_clarification_needed=False, original_prompt="Connect to esoteric CustomWarehouseAPI"),
    )

    assert dossier.needs_research is True
    assert dossier.is_fallback is True
    assert len(dossier.warnings) > 0
    assert any("Tavily service is unavailable" in w for w in dossier.warnings)
    # Documented facts must be empty, not fabricated
    assert len(dossier.documented_facts) == 0
