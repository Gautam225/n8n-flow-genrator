"""Unit tests for workflow review, readiness evaluation, and safe test planning."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from backend.app.schemas.ir import IREdge, IRNode, WorkflowIR
from backend.app.schemas.readiness import (
    CredentialVerificationState,
    ExecutionTier,
    ReadinessItemStatus,
    ReadinessStatus,
    SideEffectRisk,
)
from backend.app.services.node_registry import NodeRegistry
from backend.app.services.readiness import WorkflowReadinessEvaluator, evaluate_readiness


@pytest.fixture
def registry():
    return NodeRegistry()


@pytest.fixture
def evaluator(registry):
    return WorkflowReadinessEvaluator(registry=registry)


def test_readiness_valid_linear_workflow(evaluator):
    """Verifies that a valid linear workflow is marked READY with complete test plan."""
    workflow = WorkflowIR(
        id="wf_linear",
        name="Valid Linear Workflow",
        nodes=[
            IRNode(
                id="node_1",
                name="Manual Trigger",
                node_type="n8n-nodes-base.manualTrigger",
                type_version=1,
            ),
            IRNode(
                id="node_2",
                name="Set Data",
                node_type="n8n-nodes-base.set",
                type_version=2,
                parameters={"mode": "manual", "duplicateItem": False},
            ),
            IRNode(
                id="node_3",
                name="Code Logic",
                node_type="n8n-nodes-base.code",
                type_version=2,
                parameters={"mode": "runOnceForEachItem", "jsCode": "return $input.item;"},
            ),
        ],
        edges=[
            IREdge(source_id="node_1", target_id="node_2"),
            IREdge(source_id="node_2", target_id="node_3"),
        ],
    )

    report = evaluator.evaluate(workflow)

    assert report.overall_status == ReadinessStatus.READY
    assert report.is_deployable_to_n8n is True
    assert report.validation_report.is_valid is True
    assert len(report.checks) > 0

    # Test plan verification
    assert report.test_plan.can_run_local_dry_run is True
    assert len(report.test_plan.steps) == 3
    assert report.test_plan.steps[0].node_id == "node_1"
    assert report.test_plan.steps[1].node_id == "node_2"
    assert report.test_plan.steps[2].node_id == "node_3"
    assert all(s.testable_locally for s in report.test_plan.steps)


def test_readiness_missing_required_parameter(evaluator):
    """Verifies that missing required parameters block readiness and surface actionable feedback."""
    workflow = WorkflowIR(
        id="wf_missing_param",
        name="Missing Parameter Workflow",
        nodes=[
            IRNode(
                id="node_1",
                name="Manual Trigger",
                node_type="n8n-nodes-base.manualTrigger",
                type_version=1,
            ),
            IRNode(
                id="node_2",
                name="HTTP Fetch",
                node_type="n8n-nodes-base.httpRequest",
                type_version=4,
                # Missing required 'url' parameter
                parameters={"method": "GET"},
            ),
        ],
        edges=[IREdge(source_id="node_1", target_id="node_2")],
    )

    report = evaluator.evaluate(workflow)

    assert report.overall_status == ReadinessStatus.BLOCKED
    assert report.is_deployable_to_n8n is False
    assert report.validation_report.is_valid is False

    # Check that parameter issue is flagged
    param_checks = [c for c in report.checks if c.category.value == "parameters"]
    assert any(c.status == ReadinessItemStatus.FAIL for c in param_checks)


def test_readiness_credentials_unverified_honesty(evaluator):
    """Verifies that credentials are NEVER claimed verified and unconfigured ones require attention."""
    # Scenario A: Node requires credential but none configured -> marked MISSING
    wf_missing = WorkflowIR(
        id="wf_cred_missing",
        name="GitHub Unconfigured",
        nodes=[
            IRNode(
                id="node_1",
                name="Manual Trigger",
                node_type="n8n-nodes-base.manualTrigger",
                type_version=1,
            ),
            IRNode(
                id="node_2",
                name="GitHub Issues",
                node_type="n8n-nodes-base.github",
                type_version=1,
                parameters={"resource": "issue", "operation": "get", "owner": "org", "repository": "repo", "issueNumber": 42},
                credentials={},
            ),
        ],
        edges=[IREdge(source_id="node_1", target_id="node_2")],
    )

    rep_missing = evaluator.evaluate(wf_missing)
    assert rep_missing.overall_status == ReadinessStatus.NEEDS_ATTENTION
    assert any(c.verification_state == CredentialVerificationState.MISSING for c in rep_missing.credentials)

    # Scenario B: Node has logical reference -> marked UNVERIFIED_REFERENCE (never claims verified)
    wf_referenced = WorkflowIR(
        id="wf_cred_ref",
        name="GitHub Referenced",
        nodes=[
            IRNode(
                id="node_1",
                name="Manual Trigger",
                node_type="n8n-nodes-base.manualTrigger",
                type_version=1,
            ),
            IRNode(
                id="node_2",
                name="GitHub Issues",
                node_type="n8n-nodes-base.github",
                type_version=1,
                parameters={"resource": "issue", "operation": "get", "owner": "org", "repository": "repo", "issueNumber": 42},
                credentials={"githubApi": {"id": "cred_vault_123"}},
            ),
        ],
        edges=[IREdge(source_id="node_1", target_id="node_2")],
    )

    rep_ref = evaluator.evaluate(wf_referenced)
    ref_creds = [c for c in rep_ref.credentials if c.credential_type == "githubApi"]
    assert len(ref_creds) > 0
    assert ref_creds[0].verification_state == CredentialVerificationState.UNVERIFIED_REFERENCE
    assert "active n8n instance" in ref_creds[0].guidance


def test_readiness_orphan_and_trigger_warnings(evaluator):
    """Verifies that workflows without triggers or with disconnected nodes raise clear warnings."""
    workflow = WorkflowIR(
        id="wf_orphan",
        name="Orphan Workflow",
        nodes=[
            IRNode(
                id="node_1",
                name="Set Data",
                node_type="n8n-nodes-base.set",
                type_version=2,
                parameters={"mode": "manual"},
            ),
            IRNode(
                id="node_2",
                name="Disconnected Code",
                node_type="n8n-nodes-base.code",
                type_version=2,
                parameters={"mode": "runOnceForEachItem", "jsCode": "return $input.item;"},
            ),
        ],
        edges=[],  # No edges -> orphan and no trigger
    )

    report = evaluator.evaluate(workflow)

    assert report.overall_status == ReadinessStatus.NEEDS_ATTENTION
    assert any(c.title == "No identifiable trigger node" for c in report.checks)
    assert any("Disconnected Node" in c.title or "orphan" in c.title.lower() for c in report.checks)


def test_safe_simulation_dry_run_success(evaluator):
    """Verifies deterministic static dry-run without external execution or mutating effects."""
    workflow = WorkflowIR(
        id="wf_sim_success",
        name="Simulatable Flow",
        nodes=[
            IRNode(
                id="t_1",
                name="Webhook",
                node_type="n8n-nodes-base.webhook",
                type_version=1,
                parameters={"httpMethod": "POST", "path": "test-webhook"},
            ),
            IRNode(
                id="s_1",
                name="Transform Data",
                node_type="n8n-nodes-base.set",
                type_version=2,
                parameters={"mode": "manual"},
            ),
        ],
        edges=[IREdge(source_id="t_1", target_id="s_1")],
    )

    sim = evaluator.simulate_dry_run(workflow)

    assert sim.success is True
    assert sim.execution_type == "deterministic_static_dry_run"
    assert "No external services" in sim.disclaimer
    assert sim.total_nodes == 2
    assert sim.passed_nodes == 2
    assert len(sim.node_results) == 2
    assert sim.node_results[0].status == "simulated_success"
    assert "headers" in sim.node_results[0].sample_output_keys
    assert sim.node_results[1].status == "simulated_success"


def test_safe_simulation_dry_run_blocked_on_fatal_error(evaluator):
    """Verifies that simulation halts on fatal nodes and does not mark success."""
    workflow = WorkflowIR(
        id="wf_fatal_error",
        name="Fatal Error Flow",
        nodes=[
            IRNode(
                id="node_1",
                name="Unknown Node",
                node_type="n8n-nodes-base.nonExistentCustomNode",
                type_version=1,
            ),
        ],
        edges=[],
    )

    sim = evaluator.simulate_dry_run(workflow)

    assert sim.success is False
    assert sim.passed_nodes == 0
    assert sim.node_results[0].status == "blocked"
    assert "fatal validation errors" in sim.node_results[0].summary
