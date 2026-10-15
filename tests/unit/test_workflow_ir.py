"""Automated tests for Workflow Intermediate Representation (IR) schemas and validation."""
import pytest
from pydantic import ValidationError

from backend.app.schemas.ir import (
    ConnectionType,
    IREdge,
    IRNode,
    NodeExecutionPolicy,
    NodePosition,
    WorkflowDraftStatus,
    WorkflowIR,
    WorkflowIRParseError,
    WorkflowMetadata,
    WorkflowSettings,
    parse_workflow_ir,
    validate_workflow_ir,
)
from backend.app.schemas.validation import ValidationIssueSeverity


# ------------------------------------------------------------------------------
# 1. Valid Workflows & Basic Operations
# ------------------------------------------------------------------------------

def test_valid_linear_workflow():
    """Validates that a standard linear workflow builds and passes validation."""
    trigger = IRNode(
        id="node_trigger",
        name="Schedule Trigger",
        node_type="n8n-nodes-base.scheduleTrigger",
        type_version=1.2,
        parameters={"rule": {"interval": [{"field": "hours", "hoursInterval": 1}]}},
    )
    http_node = IRNode(
        id="node_http",
        name="Fetch External API",
        node_type="n8n-nodes-base.httpRequest",
        type_version=4.2,
        operation="GET",
        parameters={"url": "https://api.example.com/data"},
        execution_policy=NodeExecutionPolicy(retry_on_fail=True, max_tries=3),
    )
    edge = IREdge(
        source_id="node_trigger",
        target_id="node_http",
        connection_type=ConnectionType.MAIN,
        source_output_index=0,
        target_input_index=0,
    )
    workflow = WorkflowIR(
        id="wf_linear_01",
        name="Hourly Data Sync",
        nodes=[trigger, http_node],
        edges=[edge],
    )

    assert len(workflow.nodes) == 2
    assert len(workflow.edges) == 1
    assert workflow.draft_status == WorkflowDraftStatus.DRAFT

    report = validate_workflow_ir(workflow)
    assert report.is_valid is True
    assert report.has_fatal_errors is False
    assert len(report.fatal_issues) == 0


def test_canvas_coordinates_independence():
    """Validates that canvas positions are optional and do not determine semantics."""
    node_with_pos = IRNode(
        id="node_1",
        name="Node with Pos",
        node_type="n8n-nodes-base.manualTrigger",
        position=NodePosition(x=100.5, y=200.0),
    )
    node_without_pos = IRNode(
        id="node_2",
        name="Node without Pos",
        node_type="n8n-nodes-base.code",
        position=None,
    )
    edge = IREdge(source_id="node_1", target_id="node_2")
    workflow = WorkflowIR(
        id="wf_coords",
        name="Coordinates Test",
        nodes=[node_with_pos, node_without_pos],
        edges=[edge],
    )

    report = validate_workflow_ir(workflow)
    assert report.is_valid is True
    assert workflow.get_node("node_1").position.x == 100.5
    assert workflow.get_node("node_2").position is None


# ------------------------------------------------------------------------------
# 2. Branching & Parallel Connection Topologies
# ------------------------------------------------------------------------------

def test_branching_workflow():
    """Validates multi-output conditional routing (If node with True and False branches)."""
    trigger = IRNode(
        id="node_webhook",
        name="Inbound Webhook",
        node_type="n8n-nodes-base.webhook",
    )
    if_node = IRNode(
        id="node_if",
        name="Check Amount",
        node_type="n8n-nodes-base.if",
        type_version=2.0,
    )
    slack_node = IRNode(
        id="node_slack",
        name="Slack Alert (High Value)",
        node_type="n8n-nodes-base.slack",
    )
    email_node = IRNode(
        id="node_email",
        name="Send Email (Normal)",
        node_type="n8n-nodes-base.emailSend",
    )

    edges = [
        IREdge(source_id="node_webhook", target_id="node_if"),
        IREdge(source_id="node_if", target_id="node_slack", source_output_index=0, description="True Branch"),
        IREdge(source_id="node_if", target_id="node_email", source_output_index=1, description="False Branch"),
    ]

    workflow = WorkflowIR(
        id="wf_branching",
        name="Conditional Routing",
        nodes=[trigger, if_node, slack_node, email_node],
        edges=edges,
    )

    report = validate_workflow_ir(workflow)
    assert report.is_valid is True
    assert len(workflow.get_outgoing_edges("node_if")) == 2


def test_parallel_fan_out_and_fan_in():
    """Validates parallel execution (one source into two targets) and synchronization (two sources into Merge node)."""
    trigger = IRNode(
        id="node_trigger",
        name="Start",
        node_type="n8n-nodes-base.manualTrigger",
    )
    fetch_a = IRNode(
        id="node_fetch_a",
        name="Carrier A API",
        node_type="n8n-nodes-base.httpRequest",
    )
    fetch_b = IRNode(
        id="node_fetch_b",
        name="Carrier B API",
        node_type="n8n-nodes-base.httpRequest",
    )
    merge_node = IRNode(
        id="node_merge",
        name="Merge Responses",
        node_type="n8n-nodes-base.merge",
        type_version=3.0,
    )

    edges = [
        # Fan-out: trigger to both carriers
        IREdge(source_id="node_trigger", target_id="node_fetch_a"),
        IREdge(source_id="node_trigger", target_id="node_fetch_b"),
        # Fan-in: both carriers into Merge node at inputs 0 and 1
        IREdge(source_id="node_fetch_a", target_id="node_merge", target_input_index=0),
        IREdge(source_id="node_fetch_b", target_id="node_merge", target_input_index=1),
    ]

    workflow = WorkflowIR(
        id="wf_parallel",
        name="Parallel Merge Sync",
        nodes=[trigger, fetch_a, fetch_b, merge_node],
        edges=edges,
    )

    report = validate_workflow_ir(workflow)
    assert report.is_valid is True
    assert len(workflow.get_outgoing_edges("node_trigger")) == 2
    assert len(workflow.get_incoming_edges("node_merge")) == 2


# ------------------------------------------------------------------------------
# 3. Missing References & Structural Corruption (Pydantic Invariants)
# ------------------------------------------------------------------------------

def test_missing_source_node_reference():
    """Asserts that referencing a non-existent source_id raises ValidationError."""
    node_b = IRNode(id="node_b", name="Target Node", node_type="n8n-nodes-base.code")
    edge = IREdge(source_id="node_nonexistent", target_id="node_b")

    with pytest.raises(ValidationError) as exc_info:
        WorkflowIR(
            id="wf_missing_src",
            name="Missing Source",
            nodes=[node_b],
            edges=[edge],
        )
    assert "Edge source_id 'node_nonexistent' does not exist" in str(exc_info.value)


def test_missing_target_node_reference():
    """Asserts that referencing a non-existent target_id raises ValidationError."""
    node_a = IRNode(id="node_a", name="Source Node", node_type="n8n-nodes-base.manualTrigger")
    edge = IREdge(source_id="node_a", target_id="node_missing_dest")

    with pytest.raises(ValidationError) as exc_info:
        WorkflowIR(
            id="wf_missing_tgt",
            name="Missing Target",
            nodes=[node_a],
            edges=[edge],
        )
    assert "Edge target_id 'node_missing_dest' does not exist" in str(exc_info.value)


def test_duplicate_node_ids():
    """Asserts that duplicate node IDs in the nodes list raise ValidationError."""
    node_1 = IRNode(id="duplicate_id", name="Node A", node_type="n8n-nodes-base.code")
    node_2 = IRNode(id="duplicate_id", name="Node B", node_type="n8n-nodes-base.httpRequest")

    with pytest.raises(ValidationError) as exc_info:
        WorkflowIR(
            id="wf_dup",
            name="Duplicate Test",
            nodes=[node_1, node_2],
            edges=[],
        )
    assert "Duplicate node ID detected in workflow: 'duplicate_id'" in str(exc_info.value)


def test_duplicate_connection_definitions():
    """Asserts that defining the exact same connection twice raises ValidationError."""
    node_a = IRNode(id="node_a", name="A", node_type="n8n-nodes-base.manualTrigger")
    node_b = IRNode(id="node_b", name="B", node_type="n8n-nodes-base.code")
    edge_1 = IREdge(source_id="node_a", target_id="node_b", source_output_index=0, target_input_index=0)
    edge_2 = IREdge(source_id="node_a", target_id="node_b", source_output_index=0, target_input_index=0)

    with pytest.raises(ValidationError) as exc_info:
        WorkflowIR(
            id="wf_dup_edge",
            name="Duplicate Edge Test",
            nodes=[node_a, node_b],
            edges=[edge_1, edge_2],
        )
    assert "Duplicate connection detected" in str(exc_info.value)


# ------------------------------------------------------------------------------
# 4. Malformed Input Validation
# ------------------------------------------------------------------------------

def test_malformed_empty_strings():
    """Asserts that blank or whitespace-only IDs and names fail validation."""
    with pytest.raises(ValidationError):
        IRNode(id="   ", name="Valid Name", node_type="n8n-nodes-base.code")

    with pytest.raises(ValidationError):
        IRNode(id="node_1", name="", node_type="n8n-nodes-base.code")

    with pytest.raises(ValidationError):
        WorkflowIR(id="", name="Valid Name", nodes=[], edges=[])


def test_execution_policy_bounds():
    """Asserts that retry policies enforce boundaries (e.g. max_tries 1..10)."""
    with pytest.raises(ValidationError):
        NodeExecutionPolicy(retry_on_fail=True, max_tries=0)

    with pytest.raises(ValidationError):
        NodeExecutionPolicy(retry_on_fail=True, max_tries=15)

    valid_policy = NodeExecutionPolicy(retry_on_fail=True, max_tries=5, wait_between_tries=2000)
    assert valid_policy.max_tries == 5


# ------------------------------------------------------------------------------
# 5. Deep Structural Validator Checks
# ------------------------------------------------------------------------------

def test_empty_workflow_reporting():
    """Validates that a workflow with no nodes is reported as empty (fatal)."""
    empty_wf = WorkflowIR(id="wf_empty", name="Empty Workflow", nodes=[], edges=[])
    report = validate_workflow_ir(empty_wf)

    assert report.is_valid is False
    assert report.has_fatal_errors is True
    assert any(issue.rule_code == "EMPTY_WORKFLOW" for issue in report.issues)


def test_trigger_has_incoming_connection():
    """Validates that a trigger node with an incoming edge is flagged as fatal."""
    node_code = IRNode(id="node_code", name="Transform", node_type="n8n-nodes-base.code")
    node_trigger = IRNode(id="node_sched", name="Schedule", node_type="n8n-nodes-base.scheduleTrigger")
    edge = IREdge(source_id="node_code", target_id="node_sched")

    wf = WorkflowIR(
        id="wf_bad_trigger",
        name="Bad Trigger",
        nodes=[node_code, node_trigger],
        edges=[edge],
    )
    report = validate_workflow_ir(wf)

    assert report.is_valid is False
    assert any(issue.rule_code == "TRIGGER_HAS_INCOMING_EDGE" for issue in report.issues)


def test_invalid_output_index_on_known_nodes():
    """Validates that exceeding known output counts (e.g. If node output 2) is flagged as fatal."""
    trigger = IRNode(id="trig", name="Trigger", node_type="n8n-nodes-base.manualTrigger")
    if_node = IRNode(id="if_node", name="Condition", node_type="n8n-nodes-base.if")
    target = IRNode(id="target", name="Next", node_type="n8n-nodes-base.code")

    edges = [
        IREdge(source_id="trig", target_id="if_node"),
        # If node only has outputs 0 and 1. Output index 2 is invalid!
        IREdge(source_id="if_node", target_id="target", source_output_index=2),
    ]

    wf = WorkflowIR(id="wf_invalid_idx", name="Invalid Index", nodes=[trigger, if_node, target], edges=edges)
    report = validate_workflow_ir(wf)

    assert report.is_valid is False
    assert any(issue.rule_code == "INVALID_OUTPUT_INDEX" for issue in report.issues)


def test_orphan_node_warning():
    """Validates that a disconnected non-trigger node produces a warning, not a fatal error."""
    trigger = IRNode(id="trig", name="Trigger", node_type="n8n-nodes-base.manualTrigger")
    code = IRNode(id="code", name="Code", node_type="n8n-nodes-base.code")
    orphan = IRNode(id="orphan", name="Forgotten Node", node_type="n8n-nodes-base.httpRequest")

    wf = WorkflowIR(
        id="wf_orphan",
        name="Orphan Test",
        nodes=[trigger, code, orphan],
        edges=[IREdge(source_id="trig", target_id="code")],
    )
    report = validate_workflow_ir(wf)

    assert report.is_valid is True  # Warning does not invalidate workflow
    assert any(issue.rule_code == "ORPHAN_NODE" and issue.severity == ValidationIssueSeverity.WARNING for issue in report.issues)


# ------------------------------------------------------------------------------
# 6. Supported Loops vs. Uncontrolled Cycles
# ------------------------------------------------------------------------------

def test_supported_loop_construct_accepted():
    """Validates that legitimate loops (e.g. SplitInBatches loopback) are accepted as valid controlled loops."""
    trigger = IRNode(id="trig", name="Schedule", node_type="n8n-nodes-base.scheduleTrigger")
    batch_node = IRNode(id="batch", name="Split in Batches", node_type="n8n-nodes-base.splitInBatches")
    process_node = IRNode(id="process", name="Process Item", node_type="n8n-nodes-base.httpRequest")
    done_node = IRNode(id="done", name="Notify Completed", node_type="n8n-nodes-base.slack")

    edges = [
        IREdge(source_id="trig", target_id="batch"),
        # Output 0 (batch item) routes to processing
        IREdge(source_id="batch", target_id="process", source_output_index=0),
        # Processing loops back to batch node input 0
        IREdge(source_id="process", target_id="batch", target_input_index=0),
        # Output 1 (done) routes to completion summary
        IREdge(source_id="batch", target_id="done", source_output_index=1),
    ]

    wf = WorkflowIR(
        id="wf_loop_valid",
        name="Batch Loop Workflow",
        nodes=[trigger, batch_node, process_node, done_node],
        edges=edges,
    )
    report = validate_workflow_ir(wf)

    # Must be valid! The cycle is controlled by splitInBatches
    assert report.is_valid is True
    assert report.has_fatal_errors is False
    assert any(issue.rule_code == "CONTROLLED_LOOP_DETECTED" and issue.severity == ValidationIssueSeverity.INFO for issue in report.issues)


def test_uncontrolled_cycle_rejected():
    """Validates that cycles without loop control or branching nodes are flagged as fatal infinite loops."""
    trigger = IRNode(id="trig", name="Manual", node_type="n8n-nodes-base.manualTrigger")
    node_a = IRNode(id="node_a", name="Set Step A", node_type="n8n-nodes-base.set")
    node_b = IRNode(id="node_b", name="Code Step B", node_type="n8n-nodes-base.code")

    edges = [
        IREdge(source_id="trig", target_id="node_a"),
        IREdge(source_id="node_a", target_id="node_b"),
        # Infinite cycle: Node B loops directly back to Node A without any controller
        IREdge(source_id="node_b", target_id="node_a"),
    ]

    wf = WorkflowIR(
        id="wf_bad_cycle",
        name="Infinite Cycle Workflow",
        nodes=[trigger, node_a, node_b],
        edges=edges,
    )
    report = validate_workflow_ir(wf)

    assert report.is_valid is False
    assert report.has_fatal_errors is True
    assert any(issue.rule_code == "UNCONTROLLED_CYCLE" for issue in report.issues)


# ------------------------------------------------------------------------------
# 7. Serialization & Deserialization
# ------------------------------------------------------------------------------

def test_json_roundtrip_serialization():
    """Validates that WorkflowIR serializes to dict/JSON and deserializes identically."""
    trigger = IRNode(id="n_trig", name="Trigger", node_type="n8n-nodes-base.scheduleTrigger")
    action = IRNode(id="n_act", name="Action", node_type="n8n-nodes-base.httpRequest")
    edge = IREdge(source_id="n_trig", target_id="n_act")
    wf = WorkflowIR(id="wf_serial", name="Serial Test", nodes=[trigger, action], edges=[edge])

    data = wf.model_dump()
    assert isinstance(data, dict)
    assert data["id"] == "wf_serial"
    assert len(data["nodes"]) == 2

    reconstructed = WorkflowIR.model_validate(data)
    assert reconstructed.id == wf.id
    assert reconstructed.name == wf.name
    assert len(reconstructed.nodes) == 2
    assert reconstructed.edges[0].source_id == "n_trig"


# ------------------------------------------------------------------------------
# 8. Model Parsing Boundary & Regression Tests (parse_workflow_ir)
# ------------------------------------------------------------------------------

def _sample_valid_workflow_dict():
    return {
        "id": "wf_google_sheets_telegram",
        "name": "Google Sheets to Telegram Notification",
        "nodes": [
            {
                "id": "node_sheets",
                "name": "Google Sheets Trigger",
                "node_type": "n8n-nodes-base.googleSheetsTrigger",
                "type_version": 1.0,
                "parameters": {"event": "rowAdded"},
            },
            {
                "id": "node_tg",
                "name": "Telegram",
                "node_type": "n8n-nodes-base.telegram",
                "type_version": 1.2,
                "parameters": {"resource": "message", "operation": "sendMessage"},
            },
        ],
        "edges": [{"source_id": "node_sheets", "target_id": "node_tg"}],
    }


def test_parse_workflow_ir_from_valid_dict():
    """Verify parse_workflow_ir accepts a standard valid dictionary."""
    data = _sample_valid_workflow_dict()
    wf = parse_workflow_ir(data)
    assert isinstance(wf, WorkflowIR)
    assert wf.id == "wf_google_sheets_telegram"
    assert len(wf.nodes) == 2
    assert len(wf.edges) == 1


def test_parse_workflow_ir_from_instance():
    """Verify parse_workflow_ir accepts an existing WorkflowIR instance unmodified."""
    data = _sample_valid_workflow_dict()
    original = WorkflowIR.model_validate(data)
    result = parse_workflow_ir(original)
    assert result is original


def test_parse_workflow_ir_exact_reported_list_input_crash():
    """Verify that a single workflow wrapped in a 1-item list (the exact crash report) is normalized.

    Calling WorkflowIR.model_validate([wf_dict]) raises:
    ValidationError: 1 validation error for WorkflowIR: Input should be a valid dictionary or instance of WorkflowIR; input_type=list
    Calling parse_workflow_ir([wf_dict]) must normalize it explicitly without error.
    """
    raw_payload = [_sample_valid_workflow_dict()]

    # Demonstrate that raw model_validate crashes with input_type=list
    with pytest.raises(ValidationError) as exc_info:
        WorkflowIR.model_validate(raw_payload)
    assert "input_type=list" in str(exc_info.value)

    # Prove that the explicit parsing boundary normalizes it cleanly
    wf = parse_workflow_ir(raw_payload)
    assert isinstance(wf, WorkflowIR)
    assert wf.id == "wf_google_sheets_telegram"
    assert len(wf.nodes) == 2


def test_parse_workflow_ir_json_string_with_fences():
    """Verify parse_workflow_ir handles JSON strings wrapped in markdown codeblock fences."""
    data = _sample_valid_workflow_dict()
    import json
    json_str = f"```json\n{json.dumps(data)}\n```"
    wf = parse_workflow_ir(json_str)
    assert wf.id == "wf_google_sheets_telegram"


def test_parse_workflow_ir_rejects_empty_list():
    """Verify parse_workflow_ir rejects an empty list with a clear WorkflowIRParseError."""
    with pytest.raises(WorkflowIRParseError) as exc_info:
        parse_workflow_ir([])
    assert "empty list" in str(exc_info.value).lower()


def test_parse_workflow_ir_rejects_multiple_workflows():
    """Verify parse_workflow_ir rejects multiple workflow candidates and never silently takes the first."""
    wf1 = _sample_valid_workflow_dict()
    wf2 = dict(wf1)
    wf2["id"] = "wf_candidate_2"
    with pytest.raises(WorkflowIRParseError) as exc_info:
        parse_workflow_ir([wf1, wf2])
    assert "multiple candidate workflows" in str(exc_info.value).lower()


def test_parse_workflow_ir_rejects_list_of_nodes():
    """Verify parse_workflow_ir rejects a list of node dictionaries instead of a full workflow."""
    node_list = [
        {"id": "n1", "name": "Trigger", "node_type": "n8n-nodes-base.scheduleTrigger"},
        {"id": "n2", "name": "HTTP", "node_type": "n8n-nodes-base.httpRequest"},
    ]
    with pytest.raises(WorkflowIRParseError) as exc_info:
        parse_workflow_ir(node_list)
    assert "list of 2 node dictionaries" in str(exc_info.value).lower()


def test_parse_workflow_ir_rejects_single_node_dict():
    """Verify parse_workflow_ir rejects a single node dict missing workflow structure."""
    single_node = {"id": "n1", "name": "Trigger", "node_type": "n8n-nodes-base.scheduleTrigger"}
    with pytest.raises(WorkflowIRParseError) as exc_info:
        parse_workflow_ir(single_node)
    assert "single node dictionary" in str(exc_info.value).lower()


def test_parse_workflow_ir_rejects_malformed_json():
    """Verify parse_workflow_ir rejects invalid JSON strings."""
    with pytest.raises(WorkflowIRParseError) as exc_info:
        parse_workflow_ir("{not valid json: true}")
    assert "malformed json" in str(exc_info.value).lower()


def test_parse_workflow_ir_rejects_missing_required_fields():
    """Verify parse_workflow_ir rejects payloads missing required fields (e.g. name or nodes)."""
    broken_payload = {"id": "wf_broken"}
    with pytest.raises(WorkflowIRParseError) as exc_info:
        parse_workflow_ir(broken_payload)
    assert "schema validation failed" in str(exc_info.value).lower()


def test_parse_workflow_ir_normalizes_wrapped_workflow_keys():
    """Verify parse_workflow_ir normalizes dicts wrapped in 'workflow' or 'workflows' with 1 item."""
    inner = _sample_valid_workflow_dict()
    wf_single_key = parse_workflow_ir({"workflow": inner})
    assert wf_single_key.id == "wf_google_sheets_telegram"

    wf_list_key = parse_workflow_ir({"workflows": [inner]})
    assert wf_list_key.id == "wf_google_sheets_telegram"

    with pytest.raises(WorkflowIRParseError) as exc_info:
        parse_workflow_ir({"workflows": [inner, inner]})
    assert "multiple candidate workflows" in str(exc_info.value).lower()


def test_parse_workflow_ir_rescues_edges_misplaced_in_nodes():
    """Verify parse_workflow_ir rescues edge objects (id, source, target, index) placed inside nodes.

    Prevents fatal Pydantic ValidationError:
    nodes.2.name Field required
    nodes.2.node_type Field required
    """
    raw_dict = _sample_valid_workflow_dict()
    # Erroneously inject an edge object into nodes collection
    misplaced_edge = {
        "id": "edge_misplaced_01",
        "source": "node_sheets",
        "target": "node_tg",
        "index": 0,
    }
    raw_dict["nodes"].append(misplaced_edge)
    # Clear edges so we can verify the rescued edge populates edges
    raw_dict["edges"] = []

    wf = parse_workflow_ir(raw_dict)
    assert isinstance(wf, WorkflowIR)
    # The misplaced edge should be pruned from nodes
    assert len(wf.nodes) == 2
    for n in wf.nodes:
        assert n.id != "edge_misplaced_01"
        assert n.name is not None
        assert n.node_type is not None

    # And rescued into edges with normalized fields
    assert len(wf.edges) == 1
    rescued = wf.edges[0]
    assert rescued.source_id == "node_sheets"
    assert rescued.target_id == "node_tg"
    assert rescued.source_output_index == 0


def test_parse_workflow_ir_rejects_truly_corrupted_node_in_nodes():
    """Verify that a truly corrupt node (not an edge, but missing name/node_type) is rejected cleanly."""
    raw_dict = _sample_valid_workflow_dict()
    corrupt_node = {
        "id": "broken_node_xyz",
        "parameters": {"some": "value"},
    }
    raw_dict["nodes"].append(corrupt_node)
    with pytest.raises(WorkflowIRParseError) as exc_info:
        parse_workflow_ir(raw_dict)
    assert "schema validation failed" in str(exc_info.value).lower()


