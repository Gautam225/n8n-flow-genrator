"""Intermediate Representation (IR) schemas and structural validation for n8n workflows.

This module defines the clean, declarative intermediate workflow format decoupled
from raw n8n JSON and frontend canvas layout. It provides deterministic structural
validation, branch modeling, and cycle classification for supported n8n loops.
"""
import json
import logging
import re
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

logger = logging.getLogger(__name__)

from backend.app.schemas.validation import (
    ValidationIssue,
    ValidationIssueSeverity,
    ValidationReport,
)


class ConnectionType(str, Enum):
    """Supported connection types in n8n workflows."""
    MAIN = "main"
    ERROR = "error"


class WorkflowDraftStatus(str, Enum):
    """Lifecycle status of a workflow generation draft."""
    DRAFT = "draft"
    VALIDATING = "validating"
    PREVIEW_READY = "preview_ready"
    TESTING = "testing"
    TESTED_SUCCESS = "tested_success"
    TESTED_FAILED = "tested_failed"
    ACTIVE = "active"
    REJECTED = "rejected"


class NodePosition(BaseModel):
    """Canvas position coordinates for optional visual layout rendering.
    
    Coordinates are purely visual hints and never determine workflow semantics.
    """
    model_config = ConfigDict(frozen=True)

    x: float = Field(default=0.0, description="Horizontal coordinate on the canvas")
    y: float = Field(default=0.0, description="Vertical coordinate on the canvas")


class NodeExecutionPolicy(BaseModel):
    """Runtime execution and fault-tolerance policies for an individual node."""
    model_config = ConfigDict(validate_assignment=True)

    continue_on_fail: bool = Field(
        default=False,
        description="If True, workflow execution continues even if this node throws an error"
    )
    retry_on_fail: bool = Field(
        default=False,
        description="If True, n8n retries the node upon transient failure"
    )
    max_tries: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Maximum retry attempts if retry_on_fail is enabled"
    )
    wait_between_tries: int = Field(
        default=1000,
        ge=0,
        le=60000,
        description="Milliseconds to wait between retry attempts"
    )


class IRNode(BaseModel):
    """Declarative intermediate representation of a workflow node."""
    model_config = ConfigDict(validate_assignment=True)

    id: str = Field(
        ...,
        min_length=1,
        description="Stable unique identifier for the node within the workflow"
    )
    name: str = Field(
        ...,
        min_length=1,
        description="Human-readable display label for the node"
    )
    node_type: str = Field(
        ...,
        min_length=1,
        description="Canonical n8n node type identifier (e.g. 'n8n-nodes-base.httpRequest')"
    )
    type_version: float = Field(
        default=1.0,
        ge=1.0,
        description="Exact node type version supported by the target n8n instance"
    )
    description: Optional[str] = Field(
        default=None,
        description="Optional human-readable explanation of the node's intent"
    )
    disabled: bool = Field(
        default=False,
        description="Whether the node is deactivated during execution"
    )
    notes: Optional[str] = Field(
        default=None,
        description="User notes attached to the node on the n8n canvas"
    )
    operation: Optional[str] = Field(
        default=None,
        description="Selected high-level operation (e.g. 'getAll', 'create', 'update')"
    )
    parameters: Dict[str, Any] = Field(
        default_factory=dict,
        description="Operation-specific configuration parameters"
    )
    credentials: Dict[str, Any] = Field(
        default_factory=dict,
        description="Logical credential mappings (references only; secrets never included)"
    )
    execution_policy: NodeExecutionPolicy = Field(
        default_factory=NodeExecutionPolicy,
        description="Retry, timeout, and fault-tolerance policies"
    )
    position: Optional[NodePosition] = Field(
        default=None,
        description="Optional 2D layout coordinates; does not affect execution semantics"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Supplementary metadata (e.g. category, documentation link)"
    )

    @field_validator("id", "name", "node_type")
    @classmethod
    def validate_non_empty_strings(cls, v: str) -> str:
        trimmed = v.strip()
        if not trimmed:
            raise ValueError("Field cannot be empty or solely whitespace.")
        return trimmed


class IREdge(BaseModel):
    """Explicit directed connection between two nodes in the intermediate representation."""
    model_config = ConfigDict(frozen=True)

    source_id: str = Field(..., min_length=1, description="ID of the originating node")
    target_id: str = Field(..., min_length=1, description="ID of the receiving node")
    connection_type: ConnectionType = Field(
        default=ConnectionType.MAIN,
        description="Type of connection (main flow or error flow)"
    )
    source_output_index: int = Field(
        default=0,
        ge=0,
        description="Zero-indexed output socket on source node (e.g. 0=True, 1=False for If node)"
    )
    target_input_index: int = Field(
        default=0,
        ge=0,
        description="Zero-indexed input socket on target node (e.g. 0=Input 1, 1=Input 2 for Merge node)"
    )
    description: Optional[str] = Field(
        default=None,
        description="Optional label for the edge (e.g. 'True branch', 'Success path')"
    )

    @field_validator("source_id", "target_id")
    @classmethod
    def validate_node_ids(cls, v: str) -> str:
        trimmed = v.strip()
        if not trimmed:
            raise ValueError("Source and target IDs cannot be empty or whitespace.")
        return trimmed


class WorkflowSettings(BaseModel):
    """Global execution settings for the workflow."""
    model_config = ConfigDict(validate_assignment=True)

    execution_timeout: int = Field(
        default=300,
        ge=1,
        le=86400,
        description="Maximum workflow execution time in seconds"
    )
    save_execution_progress: bool = Field(
        default=True,
        description="Whether to persist execution step data in n8n database"
    )
    save_manual_executions: bool = Field(
        default=True,
        description="Whether manual test executions are persisted"
    )
    timezone: str = Field(
        default="Asia/Kolkata",
        description="Timezone used for schedule triggers and date expressions"
    )
    error_workflow_id: Optional[str] = Field(
        default=None,
        description="Optional ID of custom sub-workflow to invoke on unhandled error"
    )


class WorkflowMetadata(BaseModel):
    """Provenance and audit metadata for the workflow."""
    model_config = ConfigDict(validate_assignment=True)

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    tags: List[str] = Field(default_factory=list)
    author: Optional[str] = Field(default=None)
    extra: Dict[str, Any] = Field(default_factory=dict)


# Known output counts for standard control-flow nodes where structural count is fixed.
KNOWN_NODE_OUTPUT_COUNTS: Dict[str, int] = {
    "n8n-nodes-base.if": 2,               # 0: True, 1: False
    "n8n-nodes-base.splitInBatches": 2,   # 0: Batch items, 1: Done
    "n8n-nodes-base.loopOverItems": 2,    # 0: Loop item, 1: Done
}

# Known node types designed to control loops or conditional branching.
KNOWN_LOOP_CONTROL_NODES: Set[str] = {
    "n8n-nodes-base.splitInBatches",
    "n8n-nodes-base.loopOverItems",
    "n8n-nodes-base.if",
    "n8n-nodes-base.switch",
}


class WorkflowIR(BaseModel):
    """Complete Intermediate Representation of an n8n workflow."""
    model_config = ConfigDict(validate_assignment=True)

    id: str = Field(..., min_length=1, description="Unique identifier of the workflow plan")
    name: str = Field(..., min_length=1, description="Display name of the workflow")
    description: Optional[str] = Field(default=None, description="Detailed description of automation goal")
    version: int = Field(default=1, ge=1, description="Revision number of this workflow plan")
    draft_status: WorkflowDraftStatus = Field(
        default=WorkflowDraftStatus.DRAFT,
        description="Current approval/lifecycle status"
    )
    nodes: List[IRNode] = Field(
        default_factory=list,
        description="Collection of discrete workflow nodes"
    )
    edges: List[IREdge] = Field(
        default_factory=list,
        description="Collection of directed connections between nodes"
    )
    settings: WorkflowSettings = Field(
        default_factory=WorkflowSettings,
        description="Workflow runtime and execution configuration"
    )
    metadata: WorkflowMetadata = Field(
        default_factory=WorkflowMetadata,
        description="Workflow metadata and timestamps"
    )

    @field_validator("id", "name")
    @classmethod
    def validate_strings(cls, v: str) -> str:
        trimmed = v.strip()
        if not trimmed:
            raise ValueError("Workflow ID and name cannot be empty.")
        return trimmed

    @model_validator(mode="after")
    def validate_structural_invariants(self) -> "WorkflowIR":
        """Enforces critical structural invariants during model construction."""
        # 1. Enforce unique node IDs
        seen_node_ids: Set[str] = set()
        for node in self.nodes:
            if node.id in seen_node_ids:
                raise ValueError(f"Duplicate node ID detected in workflow: '{node.id}'")
            seen_node_ids.add(node.id)

        # 2. Enforce valid edge endpoints
        for edge in self.edges:
            if edge.source_id not in seen_node_ids:
                raise ValueError(
                    f"Edge source_id '{edge.source_id}' does not exist in workflow nodes."
                )
            if edge.target_id not in seen_node_ids:
                raise ValueError(
                    f"Edge target_id '{edge.target_id}' does not exist in workflow nodes."
                )

        # 3. Enforce no exact duplicate connections
        seen_connections: Set[Tuple[str, str, ConnectionType, int, int]] = set()
        for edge in self.edges:
            key = (
                edge.source_id,
                edge.target_id,
                edge.connection_type,
                edge.source_output_index,
                edge.target_input_index,
            )
            if key in seen_connections:
                raise ValueError(
                    f"Duplicate connection detected from '{edge.source_id}' (output {edge.source_output_index}) "
                    f"to '{edge.target_id}' (input {edge.target_input_index})."
                )
            seen_connections.add(key)

        return self

    def get_node(self, node_id: str) -> Optional[IRNode]:
        """Lookup node by ID."""
        for node in self.nodes:
            if node.id == node_id:
                return node
        return None

    def get_outgoing_edges(self, source_id: str) -> List[IREdge]:
        """Returns all outgoing edges originating from the specified node."""
        return [e for e in self.edges if e.source_id == source_id]

    def get_incoming_edges(self, target_id: str) -> List[IREdge]:
        """Returns all incoming edges leading to the specified node."""
        return [e for e in self.edges if e.target_id == target_id]


def _is_trigger_node(node_type: str) -> bool:
    """Heuristic identifying trigger/source nodes that cannot have incoming connections."""
    lower = node_type.lower()
    return "trigger" in lower or lower.endswith(".webhook")


def _detect_cycles_tarjan(nodes: List[IRNode], edges: List[IREdge]) -> List[List[str]]:
    """Finds all strongly connected components (SCCs) of size > 1 using Tarjan's algorithm."""
    index = 0
    indices: Dict[str, int] = {}
    lowlink: Dict[str, int] = {}
    on_stack: Set[str] = set()
    stack: List[str] = []
    sccs: List[List[str]] = []

    # Build adjacency map
    adj: Dict[str, List[str]] = {n.id: [] for n in nodes}
    for e in edges:
        if e.source_id in adj:
            adj[e.source_id].append(e.target_id)

    def strongconnect(v: str) -> None:
        nonlocal index
        indices[v] = index
        lowlink[v] = index
        index += 1
        stack.append(v)
        on_stack.add(v)

        for w in adj.get(v, []):
            if w not in indices:
                strongconnect(w)
                lowlink[v] = min(lowlink[v], lowlink[w])
            elif w in on_stack:
                lowlink[v] = min(lowlink[v], indices[w])

        if lowlink[v] == indices[v]:
            scc: List[str] = []
            while True:
                w = stack.pop()
                on_stack.remove(w)
                scc.append(w)
                if w == v:
                    break
            # A component is a cycle if it has >1 nodes OR a self-loop (edge to itself)
            if len(scc) > 1 or (len(scc) == 1 and scc[0] in adj.get(scc[0], [])):
                sccs.append(scc)

    for node in nodes:
        if node.id not in indices:
            strongconnect(node.id)

    return sccs


def validate_workflow_ir(workflow: WorkflowIR) -> ValidationReport:
    """Performs deep structural and topological validation on a WorkflowIR.

    Returns a comprehensive ValidationReport detailing all fatal errors, warnings,
    and informational recommendations without raising exceptions.
    """
    report = ValidationReport(is_valid=True, issues=[])
    node_map = {n.id: n for n in workflow.nodes}

    # 1. Empty workflow check
    if not workflow.nodes:
        report.add_issue(
            ValidationIssue(
                severity=ValidationIssueSeverity.FATAL,
                rule_code="EMPTY_WORKFLOW",
                message="Workflow does not contain any nodes.",
                suggested_fix="Add at least one trigger node to initiate automation."
            )
        )
        return report

    # 2. Check for trigger nodes
    trigger_nodes = [n for n in workflow.nodes if _is_trigger_node(n.node_type)]
    if not trigger_nodes:
        report.add_issue(
            ValidationIssue(
                severity=ValidationIssueSeverity.WARNING,
                rule_code="NO_TRIGGER_NODE",
                message="Workflow does not contain an identifiable trigger node.",
                suggested_fix="Add a trigger node (e.g. ScheduleTrigger, Webhook, or ManualTrigger)."
            )
        )

    # 3. Trigger nodes must not have incoming connections in n8n
    for t_node in trigger_nodes:
        incoming = workflow.get_incoming_edges(t_node.id)
        if incoming:
            report.add_issue(
                ValidationIssue(
                    severity=ValidationIssueSeverity.FATAL,
                    rule_code="TRIGGER_HAS_INCOMING_EDGE",
                    node_id=t_node.id,
                    message=(
                        f"Trigger node '{t_node.name}' ({t_node.id}) has incoming connections. "
                        f"In n8n, trigger nodes cannot receive inputs."
                    ),
                    suggested_fix="Remove incoming edges connecting to this trigger node."
                )
            )

    # 4. Validate output index bounds on known control-flow nodes
    for edge in workflow.edges:
        source_node = node_map.get(edge.source_id)
        if source_node and source_node.node_type in KNOWN_NODE_OUTPUT_COUNTS:
            max_outputs = KNOWN_NODE_OUTPUT_COUNTS[source_node.node_type]
            if edge.source_output_index >= max_outputs:
                report.add_issue(
                    ValidationIssue(
                        severity=ValidationIssueSeverity.FATAL,
                        rule_code="INVALID_OUTPUT_INDEX",
                        node_id=source_node.id,
                        edge_source_id=edge.source_id,
                        edge_target_id=edge.target_id,
                        message=(
                            f"Node '{source_node.name}' of type '{source_node.node_type}' only supports "
                            f"{max_outputs} outputs (indexes 0 to {max_outputs - 1}), but edge specifies "
                            f"source_output_index={edge.source_output_index}."
                        ),
                        suggested_fix=f"Use output index between 0 and {max_outputs - 1}."
                    )
                )

    # 5. Check for disconnected / orphan nodes (non-trigger nodes with 0 incoming and 0 outgoing edges)
    for node in workflow.nodes:
        incoming = workflow.get_incoming_edges(node.id)
        outgoing = workflow.get_outgoing_edges(node.id)
        if not incoming and not outgoing and not _is_trigger_node(node.node_type):
            report.add_issue(
                ValidationIssue(
                    severity=ValidationIssueSeverity.WARNING,
                    rule_code="ORPHAN_NODE",
                    node_id=node.id,
                    message=f"Node '{node.name}' ({node.id}) is disconnected from the workflow graph.",
                    suggested_fix="Connect this node to the workflow flow or remove it."
                )
            )

    # 6. Branch completeness check on If nodes
    for node in workflow.nodes:
        if node.node_type == "n8n-nodes-base.if":
            outgoing = workflow.get_outgoing_edges(node.id)
            indices_used = {e.source_output_index for e in outgoing}
            if 0 not in indices_used and 1 not in indices_used:
                report.add_issue(
                    ValidationIssue(
                        severity=ValidationIssueSeverity.WARNING,
                        rule_code="IF_NODE_UNCONNECTED",
                        node_id=node.id,
                        message=f"If node '{node.name}' has no outgoing connections for either True or False.",
                        suggested_fix="Connect at least one branch (True or False) to a downstream node."
                    )
                )

    # 7. Cycle analysis & loop policy enforcement
    cycles = _detect_cycles_tarjan(workflow.nodes, workflow.edges)
    for cycle_nodes in cycles:
        cycle_node_objects = [node_map[nid] for nid in cycle_nodes if nid in node_map]
        has_loop_controller = any(
            n.node_type in KNOWN_LOOP_CONTROL_NODES for n in cycle_node_objects
        )

        if has_loop_controller:
            # Legitimate loop construct (e.g. SplitInBatches or While-Loop with condition)
            loop_node_names = [n.name for n in cycle_node_objects if n.node_type in KNOWN_LOOP_CONTROL_NODES]
            report.add_issue(
                ValidationIssue(
                    severity=ValidationIssueSeverity.INFO,
                    rule_code="CONTROLLED_LOOP_DETECTED",
                    message=(
                        f"Controlled loop detected across nodes {cycle_nodes}. "
                        f"Governed by loop control node(s): {loop_node_names}."
                    ),
                    suggested_fix=None
                )
            )
        else:
            # Uncontrolled cycle without any branching/loop controller
            report.add_issue(
                ValidationIssue(
                    severity=ValidationIssueSeverity.FATAL,
                    rule_code="UNCONTROLLED_CYCLE",
                    message=(
                        f"Uncontrolled cycle detected among nodes {cycle_nodes}. "
                        f"None of the cycle nodes is a recognized loop or branching controller. "
                        f"This will cause an infinite execution loop."
                    ),
                    suggested_fix="Break the cycle or introduce a SplitInBatches, LoopOverItems, or conditional If node."
                )
            )

    return report


class WorkflowIRParseError(ValueError):
    """Raised when model or external payload cannot be parsed into a valid WorkflowIR structure."""
    pass


def parse_workflow_ir(payload: Any) -> WorkflowIR:
    """Explicit parsing and validation boundary converting model responses or JSON payloads into a valid WorkflowIR.

    Accepts:
    - An existing WorkflowIR instance (returned as-is)
    - A valid WorkflowIR dictionary
    - A JSON string containing a valid WorkflowIR dictionary (with optional markdown codeblock fences stripped)
    - A single workflow dictionary wrapped in a one-item list: [ {workflow} ] (normalized explicitly)
    - A dictionary wrapping a single workflow: {"workflow": {workflow}} or {"workflows": [{workflow}]} (normalized explicitly)

    Explicitly rejects:
    - An empty list: []
    - A list of multiple workflow candidates: [wf1, wf2] (multiple workflows are not silently reduced to the first one)
    - A list of node dictionaries: [{"id": "n1", "node_type": ...}, ...] (nodes without a parent workflow)
    - A dictionary representing a single node rather than a workflow
    - Malformed JSON strings
    - Payloads missing required workflow fields or containing invalid structural invariants
    """
    if isinstance(payload, WorkflowIR):
        return payload

    data = payload
    if isinstance(data, str):
        clean_str = data.strip()
        # Strip optional markdown codeblock fences
        if clean_str.startswith("```"):
            clean_str = re.sub(r"^```(?:json)?\s*", "", clean_str, flags=re.IGNORECASE)
            clean_str = re.sub(r"\s*```$", "", clean_str)
            clean_str = clean_str.strip()
        try:
            data = json.loads(clean_str)
        except Exception as json_err:
            raise WorkflowIRParseError(f"Malformed JSON in workflow response: {str(json_err)}") from json_err

    # Case: list input
    if isinstance(data, list):
        if len(data) == 0:
            raise WorkflowIRParseError("Model returned an empty list; a complete WorkflowIR dictionary is required.")

        # Check if list consists of node dictionaries rather than workflow dictionaries
        # A node dictionary typically has 'node_type' or 'type' and does NOT have 'nodes' list
        is_node_list = all(
            isinstance(item, dict) and ("node_type" in item or "type" in item) and "nodes" not in item
            for item in data
        )
        if is_node_list:
            raise WorkflowIRParseError(
                f"Model returned a list of {len(data)} node dictionaries instead of a complete WorkflowIR "
                "containing 'id', 'name', 'nodes', and 'edges'."
            )

        if len(data) > 1:
            raise WorkflowIRParseError(
                f"Model returned multiple candidate workflows (count={len(data)}); "
                "a single unambiguous WorkflowIR is required."
            )

        # Single-item list: normalize the single workflow object
        single_item = data[0]
        if not isinstance(single_item, dict):
            raise WorkflowIRParseError(
                f"Model returned a list containing a non-dictionary item of type '{type(single_item).__name__}'; "
                "expected a WorkflowIR dictionary."
            )
        data = single_item

    # Case: dictionary input
    if isinstance(data, dict):
        # Handle wrapped dicts: {"workflow": {...}} or {"workflows": [...]}
        if "workflow" in data and isinstance(data["workflow"], dict) and "nodes" not in data:
            return parse_workflow_ir(data["workflow"])

        if "workflows" in data and isinstance(data["workflows"], list) and "nodes" not in data:
            workflows_list = data["workflows"]
            if len(workflows_list) == 0:
                raise WorkflowIRParseError("Model returned an empty 'workflows' list; a complete WorkflowIR dictionary is required.")
            if len(workflows_list) > 1:
                raise WorkflowIRParseError(
                    f"Model returned multiple candidate workflows in 'workflows' key (count={len(workflows_list)}); "
                    "a single unambiguous WorkflowIR is required."
                )
            if not isinstance(workflows_list[0], dict):
                raise WorkflowIRParseError("Item in 'workflows' list is not a dictionary.")
            return parse_workflow_ir(workflows_list[0])

        # Check if the dict itself looks like a single node rather than a workflow
        if ("node_type" in data or "type" in data) and "nodes" not in data:
            raise WorkflowIRParseError(
                "Input represents a single node dictionary, not a complete WorkflowIR containing 'name', 'nodes', and 'edges'."
            )

        # Deterministically partition and normalize nodes and edges collections
        data = normalize_and_partition_workflow_collections(data)

        # Validate against WorkflowIR Pydantic schema
        try:
            return WorkflowIR.model_validate(data)
        except Exception as exc:
            raise WorkflowIRParseError(f"WorkflowIR schema validation failed: {str(exc)}") from exc

    raise WorkflowIRParseError(
        f"Unsupported model output type '{type(data).__name__}'; expected a WorkflowIR dictionary or valid JSON."
    )


def normalize_and_partition_workflow_collections(data: Dict[str, Any]) -> Dict[str, Any]:
    """Deterministically validates and normalizes 'nodes' and 'edges' collections.

    Guarantees:
    1. 'nodes' contains only node objects with required fields, never raw edge/connection objects.
    2. Any edge objects erroneously placed in 'nodes' (containing 'source' and 'target')
       are rescued into 'edges' with canonical keys (source_id, target_id, source_output_index).
    3. Connection keys in 'edges' are normalized (source -> source_id, target -> target_id, index -> source_output_index).
    4. Invalid items in 'nodes' lacking required node fields or valid edge structure are rejected with targeted errors.
    """
    if not isinstance(data, dict):
        return data

    raw_nodes = data.get("nodes")
    if not isinstance(raw_nodes, list):
        return data

    sanitized_nodes: List[Dict[str, Any]] = []
    rescued_edges: List[Dict[str, Any]] = []

    for idx, item in enumerate(raw_nodes):
        if not isinstance(item, dict):
            raise WorkflowIRParseError(
                f"Element at nodes.{idx} is of type '{type(item).__name__}'; expected a node dictionary."
            )

        has_edge_keys = "source" in item or "target" in item or "source_id" in item or "target_id" in item
        has_node_keys = "node_type" in item or "type" in item

        if has_edge_keys and not has_node_keys:
            # Edge/connection object mistakenly placed in 'nodes' collection
            src = item.get("source_id") or item.get("source")
            tgt = item.get("target_id") or item.get("target")
            out_idx = item.get("source_output_index") if "source_output_index" in item else item.get("index", 0)
            in_idx = item.get("target_input_index", 0)

            if src and tgt:
                rescued_edges.append({
                    "source_id": str(src).strip(),
                    "target_id": str(tgt).strip(),
                    "source_output_index": int(out_idx) if isinstance(out_idx, (int, float)) else 0,
                    "target_input_index": int(in_idx) if isinstance(in_idx, (int, float)) else 0,
                    "connection_type": item.get("connection_type", "main"),
                })
                logger.info(
                    "Rescued misplaced edge object from 'nodes' to 'edges' (source_id=%s, target_id=%s)",
                    src,
                    tgt,
                )
            else:
                raise WorkflowIRParseError(
                    f"Misplaced connection object at nodes.{idx} missing valid source/target IDs: {item}. "
                    "Nodes must contain 'name' and 'node_type', and connections must be placed in 'edges'."
                )
        else:
            # Normal node: normalize 'type' -> 'node_type' if needed
            node_dict = dict(item)
            if "node_type" not in node_dict and "type" in node_dict:
                node_dict["node_type"] = node_dict.pop("type")
            sanitized_nodes.append(node_dict)

    # Normalize edges collection
    raw_edges = data.get("edges", [])
    normalized_edges: List[Dict[str, Any]] = []
    if isinstance(raw_edges, list):
        for edge_item in raw_edges:
            if isinstance(edge_item, dict):
                norm_edge = dict(edge_item)
                if "source_id" not in norm_edge and "source" in norm_edge:
                    norm_edge["source_id"] = norm_edge.pop("source")
                if "target_id" not in norm_edge and "target" in norm_edge:
                    norm_edge["target_id"] = norm_edge.pop("target")
                if "source_output_index" not in norm_edge and "index" in norm_edge:
                    norm_edge["source_output_index"] = norm_edge.pop("index")
                normalized_edges.append(norm_edge)
            else:
                normalized_edges.append(edge_item)

    # Combine edges, deduplicating identical connections
    seen_edges = set()
    final_edges: List[Dict[str, Any]] = []
    for e in normalized_edges + rescued_edges:
        if isinstance(e, dict):
            key = (str(e.get("source_id")), str(e.get("target_id")), int(e.get("source_output_index", 0)))
            if key not in seen_edges:
                seen_edges.add(key)
                final_edges.append(e)
        else:
            final_edges.append(e)

    data["nodes"] = sanitized_nodes
    data["edges"] = final_edges
    return data

