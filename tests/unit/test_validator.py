"""Unit tests for the schema-aware Workflow Validator service."""
import pytest
from backend.app.schemas.ir import (
    ConnectionType,
    IREdge,
    IRNode,
    WorkflowIR,
)
from backend.app.schemas.validation import ValidationIssueSeverity
from backend.app.services.node_registry import NodeRegistry
from backend.app.services.validator import WorkflowValidator, validate_workflow


@pytest.fixture
def validator() -> WorkflowValidator:
    """Fixture providing WorkflowValidator with the real n8n 2.42.6 registry."""
    return WorkflowValidator(registry=NodeRegistry())


def test_valid_workflow_passes_validation(validator: WorkflowValidator):
    """Verifies that a well-formed workflow passes schema-aware validation."""
    workflow = WorkflowIR(
        id="wf_valid_001",
        name="Valid HTTP Pipeline",
        nodes=[
            IRNode(
                id="n_trig",
                name="Schedule Trigger",
                node_type="n8n-nodes-base.scheduleTrigger",
                type_version=1.2,
            ),
            IRNode(
                id="n_http",
                name="Call Weather API",
                node_type="n8n-nodes-base.httpRequest",
                type_version=4.2,
                parameters={"url": "https://api.weather.com/data", "method": "GET"},
            ),
        ],
        edges=[
            IREdge(source_id="n_trig", target_id="n_http"),
        ],
    )

    report = validator.validate(workflow)
    assert report.is_valid is True
    assert not report.has_fatal_errors


def test_unknown_node_type_reported_as_fatal(validator: WorkflowValidator):
    """Verifies that referencing a non-existent n8n node type emits NODE_TYPE_UNKNOWN."""
    workflow = WorkflowIR(
        id="wf_unk_node_001",
        name="Unknown Node Workflow",
        nodes=[
            IRNode(
                id="n1",
                name="Fictional Node",
                node_type="n8n-nodes-base.superQuantumProcessor",
                type_version=1.0,
            ),
        ],
    )

    report = validator.validate(workflow)
    assert report.is_valid is False
    assert any(i.rule_code == "NODE_TYPE_UNKNOWN" for i in report.issues)
    assert report.checks_skipped is True


def test_unsupported_node_version_warning(validator: WorkflowValidator):
    """Verifies that an out-of-range typeVersion produces a warning."""
    workflow = WorkflowIR(
        id="wf_ver_warn_001",
        name="Unsupported Version",
        nodes=[
            IRNode(
                id="n1",
                name="Schedule Trigger",
                node_type="n8n-nodes-base.scheduleTrigger",
                type_version=99.9,  # Non-existent future version
            ),
        ],
    )

    report = validator.validate(workflow)
    assert any(i.rule_code == "NODE_VERSION_UNSUPPORTED" for i in report.issues)
    assert any(i.severity == ValidationIssueSeverity.WARNING for i in report.issues)


def test_missing_required_parameter_reported(validator: WorkflowValidator):
    """Verifies that omitting an unconditionally required parameter produces MISSING_REQUIRED_PARAMETER."""
    workflow = WorkflowIR(
        id="wf_missing_param_001",
        name="Missing URL",
        nodes=[
            IRNode(
                id="n_http",
                name="HTTP Call",
                node_type="n8n-nodes-base.httpRequest",
                type_version=4.2,
                parameters={},  # 'url' is required on httpRequest!
            ),
        ],
    )

    report = validator.validate(workflow)
    assert report.is_valid is False
    assert any(i.rule_code == "MISSING_REQUIRED_PARAMETER" and "url" in (i.property_path or "") for i in report.issues)


def test_invalid_parameter_option_reported(validator: WorkflowValidator):
    """Verifies that selecting an option outside the allowed enum raises INVALID_PARAMETER_OPTION."""
    workflow = WorkflowIR(
        id="wf_invalid_option_001",
        name="Invalid HTTP Method",
        nodes=[
            IRNode(
                id="n_http",
                name="HTTP Call",
                node_type="n8n-nodes-base.httpRequest",
                type_version=4.2,
                parameters={
                    "url": "https://api.example.com",
                    "method": "INVALID_VERB",  # Only GET, POST, PUT, DELETE, etc. allowed
                },
            ),
        ],
    )

    report = validator.validate(workflow)
    assert report.is_valid is False
    assert any(i.rule_code == "INVALID_PARAMETER_OPTION" for i in report.issues)


def test_expression_bypasses_static_type_validation(validator: WorkflowValidator):
    """Verifies that n8n expressions like '{{ $json.myMethod }}' bypass static option validation."""
    workflow = WorkflowIR(
        id="wf_expr_001",
        name="Dynamic Method Expression",
        nodes=[
            IRNode(
                id="n_http",
                name="HTTP Call",
                node_type="n8n-nodes-base.httpRequest",
                type_version=4.2,
                parameters={
                    "url": "https://api.example.com",
                    "method": "{{ $json.dynamicMethod }}",
                },
            ),
        ],
    )

    report = validator.validate(workflow)
    # The expression should NOT produce an INVALID_PARAMETER_OPTION error
    assert not any(i.rule_code == "INVALID_PARAMETER_OPTION" for i in report.issues)


def test_unsupported_node_operation_reported(validator: WorkflowValidator):
    """Verifies that specifying an unsupported operation reports NODE_OPERATION_UNSUPPORTED."""
    workflow = WorkflowIR(
        id="wf_unsupported_op_001",
        name="Unsupported Slack Op",
        nodes=[
            IRNode(
                id="n_slack",
                name="Slack Action",
                node_type="n8n-nodes-base.slack",
                operation="teleport_messages_to_mars",
            ),
        ],
    )

    report = validator.validate(workflow)
    assert report.is_valid is False
    assert any(i.rule_code == "NODE_OPERATION_UNSUPPORTED" for i in report.issues)


def test_insecure_literal_credentials_warning(validator: WorkflowValidator):
    """Verifies warning when literal API keys or passwords appear in credentials mapping."""
    workflow = WorkflowIR(
        id="wf_insecure_cred_001",
        name="Insecure Secret Workflow",
        nodes=[
            IRNode(
                id="n_http",
                name="HTTP Node",
                node_type="n8n-nodes-base.httpRequest",
                parameters={"url": "https://example.com"},
                credentials={
                    "httpBasicAuth": {
                        "password": "plain_text_secret_12345",  # Literal secret!
                    }
                },
            ),
        ],
    )

    report = validator.validate(workflow)
    assert any(i.rule_code == "INSECURE_CREDENTIAL_DATA" for i in report.issues)


def test_duplicate_node_display_name_reported(validator: WorkflowValidator):
    """Verifies that duplicate display names are caught by the validator."""
    workflow = WorkflowIR(
        id="wf_dup_name_001",
        name="Duplicate Display Name",
        nodes=[
            IRNode(id="n1", name="Fetch Records", node_type="n8n-nodes-base.manualTrigger"),
            IRNode(id="n2", name="Fetch Records", node_type="n8n-nodes-base.noOp"),
        ],
    )

    report = validator.validate(workflow)
    assert report.is_valid is False
    assert any(i.rule_code == "DUPLICATE_NODE_NAME" for i in report.issues)


def test_controlled_loop_accepted_and_uncontrolled_cycle_rejected(validator: WorkflowValidator):
    """Verifies that SplitInBatches loop is accepted as INFO while uncontrolled loop is FATAL."""
    # 1. Controlled loop
    controlled_wf = WorkflowIR(
        id="wf_controlled_001",
        name="Controlled Batch Loop",
        nodes=[
            IRNode(id="n_trig", name="Trigger", node_type="n8n-nodes-base.manualTrigger"),
            IRNode(id="n_loop", name="Loop Batch", node_type="n8n-nodes-base.splitInBatches"),
            IRNode(id="n_proc", name="Process", node_type="n8n-nodes-base.noOp"),
        ],
        edges=[
            IREdge(source_id="n_trig", target_id="n_loop"),
            IREdge(source_id="n_loop", target_id="n_proc", source_output_index=0),
            IREdge(source_id="n_proc", target_id="n_loop", source_output_index=0),
        ],
    )
    report_controlled = validator.validate(controlled_wf)
    assert report_controlled.is_valid is True
    assert any(i.rule_code == "CONTROLLED_LOOP_DETECTED" for i in report_controlled.issues)

    # 2. Uncontrolled cycle (A -> B -> A with no controller)
    uncontrolled_wf = WorkflowIR(
        id="wf_uncontrolled_001",
        name="Uncontrolled Infinite Cycle",
        nodes=[
            IRNode(id="nA", name="Node A", node_type="n8n-nodes-base.noOp"),
            IRNode(id="nB", name="Node B", node_type="n8n-nodes-base.noOp"),
        ],
        edges=[
            IREdge(source_id="nA", target_id="nB"),
            IREdge(source_id="nB", target_id="nA"),
        ],
    )
    report_uncontrolled = validator.validate(uncontrolled_wf)
    assert report_uncontrolled.is_valid is False
    assert any(i.rule_code == "UNCONTROLLED_CYCLE" for i in report_uncontrolled.issues)
