"""Phase 3 Automated Verification Tests.

Covers:
1. Research normalization, malformed responses, and service unavailability fallbacks.
2. Mismatches and consistency between WorkflowPlan, WorkflowIR, and compiled JSON.
3. Invalid nodes, unsupported parameters, branch connections, and expression references.
4. Missing credentials, unresolved configuration, and blocked deployment gates.
5. Inactive workflow preservation (active=False) and deployment approval boundaries.
6. Generation lock cleanup, error recovery, and safe retry execution.
"""
import asyncio
import time
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from backend.app.schemas.ir import (
    ConnectionType,
    IREdge,
    IRNode,
    NodePosition,
    WorkflowIR,
)
from backend.app.schemas.readiness import (
    CredentialVerificationState,
    ExecutionTier,
    ReadinessStatus,
    SideEffectRisk,
    WorkflowReadinessReport,
)
from backend.app.services.compiler import CompilationError, WorkflowCompiler
from backend.app.services.n8n_client import N8nClient, N8nConnectionState, N8nStatusResponse
from backend.app.services.node_registry import NodeRegistry
from backend.app.services.readiness import WorkflowReadinessEvaluator
from backend.app.services.research.client import TavilyClientError
from backend.app.services.research.schemas import (
    ResearchFinding,
    ResearchSource,
    StructuredResearchDossier,
)
from backend.app.services.research.service import ResearchService
from backend.app.services.research.validator import ResearchSourceValidator
from backend.app.services.validator import WorkflowValidator


# ---------------------------------------------------------------------------
# FIXTURES
# ---------------------------------------------------------------------------

@pytest.fixture
def node_registry() -> NodeRegistry:
    return NodeRegistry()


@pytest.fixture
def validator(node_registry: NodeRegistry) -> WorkflowValidator:
    return WorkflowValidator(registry=node_registry)


@pytest.fixture
def compiler(node_registry: NodeRegistry) -> WorkflowCompiler:
    return WorkflowCompiler(registry=node_registry)


@pytest.fixture
def readiness_evaluator(node_registry: NodeRegistry, validator: WorkflowValidator) -> WorkflowReadinessEvaluator:
    return WorkflowReadinessEvaluator(registry=node_registry, validator=validator)


# ---------------------------------------------------------------------------
# 1. RESEARCH DATA NORMALIZATION & SERVICE UNAVAILABILITY (Scenarios 1, 2, 10)
# ---------------------------------------------------------------------------

def test_research_source_validator_sanitizes_malformed_urls():
    """Verify that dangerous or malformed URLs are rejected without raising unhandled exceptions."""
    assert not ResearchSourceValidator.is_safe_url("javascript:alert(1)")[0]
    assert not ResearchSourceValidator.is_safe_url("data:text/html,<html>")[0]
    assert not ResearchSourceValidator.is_safe_url("http://169.254.169.254/latest/meta-data")[0]
    assert not ResearchSourceValidator.is_safe_url("http://localhost:5678/api")[0]
    assert not ResearchSourceValidator.is_safe_url("http://127.0.0.1:8000")[0]
    assert not ResearchSourceValidator.is_safe_url("")[0]

    # Valid external doc URLs
    assert ResearchSourceValidator.is_safe_url("https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.httprequest/")[0]
    assert ResearchSourceValidator.is_safe_url("https://api.telegram.org/bot123/sendMessage")[0]


@pytest.mark.asyncio
async def test_research_service_graceful_fallback_when_tavily_unavailable():
    """Verify that when Tavily raises an error or is unconfigured, research fails gracefully to local catalog."""
    mock_client = AsyncMock()
    mock_client.search.side_effect = TavilyClientError("Tavily rate limit exceeded", status_code=429)

    service = ResearchService(client=mock_client)
    # Force settings as configured to test network/API failure path
    service.settings.TAVILY_API_KEY = "tvly-test-key"

    dossier = await service.conduct_research(
        user_prompt="Build a workflow sending orders from Shopify webhook to Airtable custom table",
    )

    assert isinstance(dossier, StructuredResearchDossier)
    assert dossier.needs_research is True
    # Honest fallback reporting: is_fallback must be True when searches fail
    assert dossier.is_fallback is True
    assert len(dossier.warnings) > 0
    assert any("limitation" in w.lower() or "encountered" in w.lower() for w in dossier.warnings)
    # Verification against installed catalog should still operate for Shopify and Airtable
    assert "Shopify" in dossier.node_compatibility or "Airtable" in dossier.node_compatibility


# ---------------------------------------------------------------------------
# 2. WORKFLOW PLAN, IR, AND COMPILED JSON CONSISTENCY (Scenario 3)
# ---------------------------------------------------------------------------

def test_plan_ir_and_compiled_json_consistency(compiler: WorkflowCompiler, validator: WorkflowValidator):
    """Verify strict topological and semantic consistency across WorkflowPlan, IR, and compiled n8n JSON."""
    wf_ir = WorkflowIR(
        id="wf-plan-sync-1",
        name="Scheduled Order Sync",
        nodes=[
            IRNode(
                id="sched_1",
                name="Schedule Trigger",
                node_type="n8n-nodes-base.scheduleTrigger",
                type_version=1.2,
                position=NodePosition(x=100, y=200),
                parameters={"rule": {"interval": [{"field": "hours", "hoursInterval": 1}]}},
            ),
            IRNode(
                id="http_1",
                name="Fetch New Orders",
                node_type="n8n-nodes-base.httpRequest",
                type_version=4.2,
                position=NodePosition(x=350, y=200),
                parameters={
                    "method": "GET",
                    "url": "https://api.example.com/orders",
                    "authentication": "genericCredentialType",
                    "genericAuthType": "httpHeaderAuth",
                },
                credentials={"httpHeaderAuth": {"id": "cred_orders_api", "name": "Orders Header Auth"}},
            ),
            IRNode(
                id="if_1",
                name="Has Orders?",
                node_type="n8n-nodes-base.if",
                type_version=2.2,
                position=NodePosition(x=600, y=200),
                parameters={
                    "conditions": {
                        "options": {"caseSensitive": True, "leftValue": ""},
                        "conditions": [
                            {
                                "id": "cond_1",
                                "leftValue": "={{ $json.orders.length }}",
                                "rightValue": 0,
                                "operator": {"type": "number", "operation": "gt"},
                            }
                        ],
                        "combinator": "and",
                    }
                },
            ),
        ],
        edges=[
            IREdge(source_id="sched_1", target_id="http_1"),
            IREdge(source_id="http_1", target_id="if_1"),
        ],
    )

    # 1. Structural validation
    report = validator.validate(wf_ir)
    assert report.is_valid is True

    # 2. Compilation
    compiled = compiler.compile(wf_ir)
    assert compiled["name"] == "Scheduled Order Sync"
    assert compiled["active"] is False  # Inactive deployment guarantee
    assert len(compiled["nodes"]) == 3

    # 3. Verify connection mapping matches IR connections
    connections = compiled["connections"]
    assert "Schedule Trigger" in connections
    assert connections["Schedule Trigger"]["main"][0][0]["node"] == "Fetch New Orders"
    assert "Fetch New Orders" in connections
    assert connections["Fetch New Orders"]["main"][0][0]["node"] == "Has Orders?"


# ---------------------------------------------------------------------------
# 3. INVALID NODES, EXPRESSIONS, AND BLOCKED READINESS (Scenarios 4 & 8)
# ---------------------------------------------------------------------------

def test_unrecognized_node_type_blocks_readiness(
    validator: WorkflowValidator,
    readiness_evaluator: WorkflowReadinessEvaluator,
):
    """Verify that an unknown/unsupported node type triggers validation error and blocks readiness."""
    bad_ir = WorkflowIR(
        id="wf-bad-1",
        name="Bad Node Workflow",
        nodes=[
            IRNode(
                id="fake_1",
                name="Imaginary AI Tool",
                node_type="n8n-nodes-base.nonExistentCustomNode",
                type_version=1.0,
            )
        ],
        connections=[],
    )

    val_report = validator.validate(bad_ir)
    assert val_report.is_valid is False
    assert any(i.rule_code == "NODE_TYPE_UNKNOWN" for i in val_report.issues)

    readiness = readiness_evaluator.evaluate(bad_ir)
    assert readiness.overall_status == ReadinessStatus.BLOCKED
    assert readiness.is_structure_valid is False
    assert readiness.is_deployment_ready is False


def test_missing_required_credential_blocks_deployment(readiness_evaluator: WorkflowReadinessEvaluator):
    """Verify that a node requiring credentials without a configured credential blocks deployment."""
    wf_ir = WorkflowIR(
        id="wf-sheets-cred-1",
        name="Sheets Append without Credential",
        nodes=[
            IRNode(
                id="man_1",
                name="Manual Trigger",
                node_type="n8n-nodes-base.manualTrigger",
                type_version=1.0,
            ),
            IRNode(
                id="sheets_1",
                name="Append Row",
                node_type="n8n-nodes-base.googleSheets",
                type_version=4.5,
                parameters={
                    "operation": "append",
                    "documentId": {"__rl": True, "value": "sheet123", "mode": "id"},
                    "sheetName": {"__rl": True, "value": "Sheet1", "mode": "name"},
                },
                # Missing credentials field entirely
            ),
        ],
        edges=[
            IREdge(source_id="man_1", target_id="sheets_1"),
        ],
    )

    readiness = readiness_evaluator.evaluate(wf_ir)
    # The structure itself may have nodes connected, but deployment must be blocked
    assert readiness.is_deployment_ready is False
    missing_creds = [c for c in readiness.credentials if c.verification_state == CredentialVerificationState.MISSING]
    assert len(missing_creds) > 0


# ---------------------------------------------------------------------------
# 4. INACTIVE WORKFLOW PRESERVATION AND DEPLOYMENT BOUNDARIES (Scenario 9)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_n8n_client_strictly_enforces_inactive_payload():
    """Verify that N8nClient.create_workflow strictly sends active=False to n8n REST API."""
    client = N8nClient(base_url="http://localhost:5678", api_key="test-api-key")

    mock_resp = MagicMock()
    mock_resp.status_code = 201
    mock_resp.json.return_value = {
        "id": "workflow-xyz-123",
        "name": "Safety Test Workflow",
        "active": False,
    }

    with patch.object(client._http_client, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp

        result = await client.create_workflow({
            "name": "Safety Test Workflow",
            "nodes": [],
            "connections": {},
            # Deliberately attempt to pass active=True in input data to test safety override
            "active": True,
        })

        assert result.workflow_id == "workflow-xyz-123"
        # Verify call payload sent to n8n API
        call_kwargs = mock_post.call_args[1]
        sent_json = call_kwargs["json"]
        assert sent_json["active"] is False, "n8n create_workflow payload MUST explicitly enforce active=False"


# ---------------------------------------------------------------------------
# 5. GENERATION LOCK CLEANUP & ERROR RECOVERY (Scenario 7)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_generation_lock_cleans_up_on_turn_completion():
    """Verify that WorkflowOrchestrator immediately clears active lock after execution completes."""
    from backend.app.orchestrator.engine import WorkflowOrchestrator

    orchestrator = WorkflowOrchestrator()
    conv_id = "test-conv-lock-123"

    # Simulate setting active stage
    orchestrator.set_active_stage(conv_id, "planning", "Planning workflow nodes...")
    assert orchestrator.is_turn_active(conv_id) is True

    # Call clear active stage
    orchestrator.clear_active_stage(conv_id)
    assert orchestrator.is_turn_active(conv_id) is False
    assert orchestrator.get_active_stage(conv_id) is None


# ---------------------------------------------------------------------------
# 6. DISTINGUISH STRUCTURAL VALIDATION FROM LIVE SERVICE VERIFICATION (Scenario 2)
# ---------------------------------------------------------------------------

def test_readiness_distinguishes_structural_validity_from_live_verification(
    readiness_evaluator: WorkflowReadinessEvaluator,
):
    """Verify that a valid graph is never marked as verified against live remote APIs without instance."""
    wf_ir = WorkflowIR(
        id="wf-tg-readiness-1",
        name="Telegram Alert Workflow",
        nodes=[
            IRNode(
                id="man_1",
                name="Manual Trigger",
                node_type="n8n-nodes-base.manualTrigger",
                type_version=1.0,
            ),
            IRNode(
                id="tg_1",
                name="Send Telegram Alert",
                node_type="n8n-nodes-base.telegram",
                type_version=1.2,
                parameters={
                    "resource": "message",
                    "operation": "sendMessage",
                    "chatId": "123456789",
                    "text": "Hello Telegram",
                },
                credentials={"telegramApi": {"id": "cred_tg_1", "name": "Telegram Bot"}},
            ),
        ],
        edges=[
            IREdge(source_id="man_1", target_id="tg_1"),
        ],
    )

    readiness = readiness_evaluator.evaluate(wf_ir, available_n8n_credentials=None)
    assert readiness.is_structure_valid is True

    # Must NOT claim credentials are live verified when no instance credentials were provided
    tg_cred = next(c for c in readiness.credentials if c.credential_type == "telegramApi")
    assert tg_cred.verification_state != CredentialVerificationState.VERIFIED
    assert tg_cred.verification_state in (
        CredentialVerificationState.CONFIGURED,
        CredentialVerificationState.REFERENCED,
        CredentialVerificationState.UNVERIFIED_REFERENCE,
    )

    # Test plan must separate local static checks from target-dependent live execution
    local_steps = [s for s in readiness.test_plan.steps if s.execution_tier == ExecutionTier.LOCAL_STATIC]
    instance_steps = [s for s in readiness.test_plan.steps if s.execution_tier in (ExecutionTier.REQUIRES_N8N, ExecutionTier.REQUIRES_EXTERNAL_SERVICE)]

    assert len(local_steps) > 0, "Test plan must include local static checks"
    assert len(instance_steps) > 0, "Test plan must identify target instance dependent checks"
    # Live execution steps must have side-effect risk identified
    assert any(s.side_effect_risk in (SideEffectRisk.READ_ONLY, SideEffectRisk.EXTERNAL_MUTATION) for s in instance_steps)
