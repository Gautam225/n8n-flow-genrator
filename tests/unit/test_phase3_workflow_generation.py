"""Phase 3 Focused Unit Tests: Registry-Grounded Workflow Generation, End-to-End Pipeline, and Honesty."""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from backend.app.schemas.ir import (
    ConnectionType,
    IREdge,
    IRNode,
    NodePosition,
    WorkflowIR,
    parse_workflow_ir,
)
from backend.app.schemas.validation import ValidationIssueSeverity, ValidationReport
from backend.app.services.compiler import WorkflowCompiler
from backend.app.services.node_registry import NodeRegistry
from backend.app.services.readiness import (
    CredentialVerificationState,
    ReadinessCategory,
    ReadinessStatus,
    WorkflowReadinessEvaluator,
)
from backend.app.services.validator import WorkflowValidator
from backend.app.orchestrator.intent import WorkflowIntentExtractor
from backend.app.orchestrator.engine import WorkflowOrchestrator


@pytest.fixture
def registry() -> NodeRegistry:
    return NodeRegistry()


@pytest.fixture
def compiler() -> WorkflowCompiler:
    return WorkflowCompiler()


@pytest.fixture
def validator(registry: NodeRegistry) -> WorkflowValidator:
    return WorkflowValidator(registry=registry)


@pytest.fixture
def readiness_evaluator(registry: NodeRegistry, validator: WorkflowValidator) -> WorkflowReadinessEvaluator:
    return WorkflowReadinessEvaluator(registry=registry, validator=validator)


@pytest.fixture
def intent_extractor(registry: NodeRegistry) -> WorkflowIntentExtractor:
    return WorkflowIntentExtractor(node_registry=registry)


# -------------------------------------------------------------------------
# Test 1: Google Sheets to Telegram Regression Case End-to-End
# -------------------------------------------------------------------------
def test_google_sheets_to_telegram_pipeline_end_to_end(
    intent_extractor: WorkflowIntentExtractor,
    compiler: WorkflowCompiler,
    validator: WorkflowValidator,
    readiness_evaluator: WorkflowReadinessEvaluator,
):
    """Verifies the complete generation, compilation, validation, and readiness pipeline

    for: "Whenever a new row is added to my Google Sheet, send me a Telegram message containing the person's name, email, and phone number."
    """
    prompt = "Whenever a new row is added to my Google Sheet, send me a Telegram message containing the person's name, email, and phone number."

    # 1. Intent Analysis & Requirements Discovery
    intent = intent_extractor.analyze(
        user_prompt=prompt,
        history=[],
        accumulated_slots={
            "google_sheets_document": "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms",
            "google_sheets_sheet_name": "Sheet1",
            "telegram_chat_id": "123456789",
        },
    )

    # Confirm extracted nodes and operations match real catalogue
    assert intent.trigger is not None
    assert intent.trigger.node_type == "n8n-nodes-base.googleSheetsTrigger"
    assert intent.trigger.operation == "rowAdded"
    assert len(intent.actions) == 1
    assert intent.actions[0].node_type == "n8n-nodes-base.telegram"
    assert intent.actions[0].operation == "sendMessage"

    # Confirm data mappings for name, email, phone were extracted
    from_mappings = [m["from"] for m in intent.data_mappings]
    assert "sheets.name" in from_mappings
    assert "sheets.email" in from_mappings
    assert any("phone" in m for m in from_mappings)

    # 2. Canonical Workflow IR Construction (using real registered node schemas)
    text_expr = intent.actions[0].parameters["text"]
    assert "$json['name']" in text_expr or "$json['Name']" in text_expr
    assert "$json['email']" in text_expr or "$json['Email']" in text_expr

    workflow_ir = WorkflowIR(
        id="wf_gs_to_tg_001",
        name="Google Sheets to Telegram Notification",
        nodes=[
            IRNode(
                id="node_sheets",
                name="Google Sheets Trigger",
                node_type="n8n-nodes-base.googleSheetsTrigger",
                type_version=1.0,
                parameters={
                    "event": "rowAdded",
                    "documentId": "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms",
                    "sheetName": "Sheet1",
                },
                credentials={
                    "googleSheetsTriggerOAuth2Api": {
                        "id": "cred_gs_001",
                        "name": "Google Sheets OAuth account",
                    }
                },
            ),
            IRNode(
                id="node_telegram",
                name="Telegram Alert",
                node_type="n8n-nodes-base.telegram",
                type_version=1.2,
                parameters={
                    "resource": "message",
                    "operation": "sendMessage",
                    "chatId": "123456789",
                    "text": text_expr,
                },
                credentials={
                    "telegramApi": {
                        "id": "cred_tg_001",
                        "name": "Telegram Bot account",
                    }
                },
            ),
        ],
        edges=[
            IREdge(
                source_id="node_sheets",
                target_id="node_telegram",
                source_output_index=0,
                target_input_index=0,
            )
        ],
    )

    # 3. Deterministic Compilation into native n8n JSON
    compiled = compiler.compile(workflow_ir)
    assert compiled["name"] == "Google Sheets to Telegram Notification"
    assert len(compiled["nodes"]) == 2
    assert "Google Sheets Trigger" in compiled["connections"]
    tg_conn = compiled["connections"]["Google Sheets Trigger"]["main"][0][0]
    assert tg_conn["node"] == "Telegram Alert"
    assert tg_conn["type"] == "main"
    assert tg_conn["index"] == 0

    # 4. Structural, Schema, and Semantic Validation
    val_report = validator.validate(workflow_ir, prompt_context=prompt, intent=intent)
    assert val_report.is_valid is True
    assert not val_report.has_fatal_errors
    # No unmapped data warning because expression maps the columns
    assert not any(i.rule_code == "UNRESOLVED_DATA_MAPPING" for i in val_report.issues)

    # 5. Readiness Assessment
    readiness = readiness_evaluator.evaluate(workflow_ir, prompt_context=prompt)
    assert readiness.is_structure_valid is True
    # Credentials: only googleSheetsTriggerOAuth2Api and telegramApi are expected (not bogus googleApi duplicate)
    assert len(readiness.credentials) == 2
    assert {c.credential_type for c in readiness.credentials} == {
        "googleSheetsTriggerOAuth2Api",
        "telegramApi",
    }
    assert all(
        c.verification_state in (CredentialVerificationState.UNVERIFIED_REFERENCE, CredentialVerificationState.MISSING, CredentialVerificationState.REFERENCED)
        for c in readiness.credentials
    )
    # Status is ready for review with notice that credentials require setup in n8n
    assert readiness.overall_status in (ReadinessStatus.READY, ReadinessStatus.NEEDS_ATTENTION)


# -------------------------------------------------------------------------
# Test 2: Conditional Workflow (If Branching) End-to-End
# -------------------------------------------------------------------------
def test_conditional_if_branching_workflow_end_to_end(
    compiler: WorkflowCompiler,
    validator: WorkflowValidator,
    readiness_evaluator: WorkflowReadinessEvaluator,
):
    """Verifies that an If branching workflow preserves output indices 0 (True) and 1 (False)

    and compiles correctly without flattening.
    """
    workflow_ir = WorkflowIR(
        id="wf_if_branch_001",
        name="Conditional Webhook Router",
        nodes=[
            IRNode(
                id="n_webhook",
                name="Webhook Trigger",
                node_type="n8n-nodes-base.webhook",
                type_version=2.0,
                parameters={"path": "order-events", "httpMethod": "POST"},
            ),
            IRNode(
                id="n_if",
                name="Check Priority",
                node_type="n8n-nodes-base.if",
                type_version=2.2,
                parameters={},
            ),
            IRNode(
                id="n_slack",
                name="Slack Alert",
                node_type="n8n-nodes-base.slack",
                type_version=2.1,
                parameters={
                    "resource": "message",
                    "operation": "post",
                    "select": "channel",
                    "channelId": "C12345",
                    "text": "VIP Order Received",
                },
                credentials={"slackApi": {"id": "1", "name": "Slack account"}},
            ),
            IRNode(
                id="n_email",
                name="Email Summary",
                node_type="n8n-nodes-base.emailSend",
                type_version=2.1,
                parameters={"toEmail": "team@example.com", "subject": "Standard Order"},
                credentials={"smtp": {"id": "1", "name": "SMTP account"}},
            ),
        ],
        edges=[
            IREdge(source_id="n_webhook", target_id="n_if", source_output_index=0),
            IREdge(source_id="n_if", target_id="n_slack", source_output_index=0, description="True: High Priority"),
            IREdge(source_id="n_if", target_id="n_email", source_output_index=1, description="False: Normal"),
        ],
    )

    # Validate structure & socket bounds (If node has 2 outputs)
    val_report = validator.validate(workflow_ir)
    assert val_report.is_valid is True
    assert not val_report.has_fatal_errors

    # Compile and verify distinct branch arrays
    compiled = compiler.compile(workflow_ir)
    if_conns = compiled["connections"]["Check Priority"]["main"]
    assert len(if_conns) == 2
    assert if_conns[0][0]["node"] == "Slack Alert"
    assert if_conns[1][0]["node"] == "Email Summary"

    # Readiness assessment confirms valid DAG topology and safe test plan
    readiness = readiness_evaluator.evaluate(workflow_ir)
    assert readiness.is_structure_valid is True
    assert any(c.category == ReadinessCategory.TOPOLOGY and c.title == "DAG cycle policy satisfied" for c in readiness.checks)


# -------------------------------------------------------------------------
# Test 3: Multi-Action Fan-Out Workflow End-to-End
# -------------------------------------------------------------------------
def test_multi_action_fan_out_workflow_end_to_end(
    compiler: WorkflowCompiler,
    validator: WorkflowValidator,
    readiness_evaluator: WorkflowReadinessEvaluator,
):
    """Verifies that a single trigger fanning out to 3 concurrent action nodes compiles

    and positions nodes without collision.
    """
    workflow_ir = WorkflowIR(
        id="wf_fan_out_001",
        name="Multi-Channel Notification Broadcast",
        nodes=[
            IRNode(
                id="n_trigger",
                name="Schedule",
                node_type="n8n-nodes-base.scheduleTrigger",
                type_version=1.2,
                parameters={},
            ),
            IRNode(
                id="n_act1",
                name="Telegram Alert",
                node_type="n8n-nodes-base.telegram",
                type_version=1.2,
                parameters={"resource": "message", "operation": "sendMessage", "chatId": "12345", "text": "Daily update"},
                credentials={"telegramApi": {"id": "1", "name": "Telegram account"}},
            ),
            IRNode(
                id="n_act2",
                name="Slack Alert",
                node_type="n8n-nodes-base.slack",
                type_version=2.1,
                parameters={
                    "resource": "message",
                    "operation": "post",
                    "select": "channel",
                    "channelId": "C12345",
                    "text": "Daily update",
                },
                credentials={"slackApi": {"id": "1", "name": "Slack account"}},
            ),
            IRNode(
                id="n_act3",
                name="Email Alert",
                node_type="n8n-nodes-base.emailSend",
                type_version=2.1,
                parameters={"toEmail": "admin@example.com", "subject": "Daily update"},
                credentials={"smtp": {"id": "1", "name": "SMTP account"}},
            ),
        ],
        edges=[
            IREdge(source_id="n_trigger", target_id="n_act1"),
            IREdge(source_id="n_trigger", target_id="n_act2"),
            IREdge(source_id="n_trigger", target_id="n_act3"),
        ],
    )

    val_report = validator.validate(workflow_ir)
    assert val_report.is_valid is True

    compiled = compiler.compile(workflow_ir)
    trig_conns = compiled["connections"]["Schedule"]["main"][0]
    assert len(trig_conns) == 3
    target_names = {c["node"] for c in trig_conns}
    assert target_names == {"Telegram Alert", "Slack Alert", "Email Alert"}

    # Positions should not overlap vertically
    positions = {n["name"]: n["position"] for n in compiled["nodes"]}
    y_coords = [positions[name][1] for name in target_names]
    assert len(set(y_coords)) == 3  # All 3 target nodes have distinct Y coordinates!


# -------------------------------------------------------------------------
# Test 4: Operation-Specific Conditional Parameter Validation
# -------------------------------------------------------------------------
def test_operation_specific_conditional_parameter_validation(validator: WorkflowValidator):
    """Verifies that missing parameters are validated conditionally based on the active operation."""
    # Telegram with operation='sendMessage' requires chatId
    tg_missing_chat_id = WorkflowIR(
        id="wf_tg_missing_chat",
        name="Missing Chat ID",
        nodes=[
            IRNode(
                id="n_trig",
                name="Manual Trigger",
                node_type="n8n-nodes-base.manualTrigger",
            ),
            IRNode(
                id="n_tg",
                name="Telegram",
                node_type="n8n-nodes-base.telegram",
                type_version=1.2,
                parameters={
                    "resource": "message",
                    "operation": "sendMessage",
                    "text": "Hello",
                    # chatId omitted!
                },
                credentials={"telegramApi": {"id": "1", "name": "Telegram account"}},
            ),
        ],
        edges=[IREdge(source_id="n_trig", target_id="n_tg")],
    )

    report1 = validator.validate(tg_missing_chat_id)
    assert report1.is_valid is False
    assert any(
        i.rule_code == "MISSING_REQUIRED_PARAMETER"
        and "chatId" in (i.property_path or "")
        and i.resolved_category == "missing_required_config"
        for i in report1.issues
    )


# -------------------------------------------------------------------------
# Test 5: Actionable Validation Categories
# -------------------------------------------------------------------------
def test_actionable_validation_categories(validator: WorkflowValidator):
    """Verifies that validation issues expose standard actionable categories."""
    # Unknown node
    wf_bad_node = WorkflowIR(
        id="wf_bad_node",
        name="Bad Node",
        nodes=[IRNode(id="n1", name="Alien", node_type="n8n-nodes-base.alienNode")],
        edges=[],
    )
    rep = validator.validate(wf_bad_node)
    issue = next(i for i in rep.issues if i.rule_code == "NODE_TYPE_UNKNOWN")
    assert issue.resolved_category == "unknown_node_type"
    assert issue.suggested_fix is not None


# -------------------------------------------------------------------------
# Test 6: Conversation Status Isolation and Stale Timeout
# -------------------------------------------------------------------------
def test_conversation_status_isolation_and_timeout():
    """Verifies orchestrator status isolation across conversation IDs and stale timeout."""
    orchestrator = WorkflowOrchestrator(
        llm_manager=MagicMock(),
        node_registry=MagicMock(),
        compiler=MagicMock(),
        validator=MagicMock(),
        intent_extractor=MagicMock(),
    )

    # Conversation A active
    orchestrator.set_active_stage("conv-aaa", "generating", "Synthesizing graph...")
    status_a = orchestrator.get_active_stage("conv-aaa")
    assert status_a is not None
    assert status_a["conversation_id"] == "conv-aaa"
    assert status_a["stage"] == "generating"

    # Conversation B should be None
    status_b = orchestrator.get_active_stage("conv-bbb")
    assert status_b is None

    # Clear Conversation A
    orchestrator.clear_active_stage("conv-aaa")
    assert orchestrator.get_active_stage("conv-aaa") is None

    # Stale record (> 120s) auto-discarded
    orchestrator.set_active_stage("conv-stale", "planning", "Planning...")
    orchestrator._active_stages["conv-stale"]["started_at"] = 0
    orchestrator._active_stages["conv-stale"]["updated_at"] = 0
    assert orchestrator.get_active_stage("conv-stale") is None
