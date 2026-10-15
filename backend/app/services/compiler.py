"""Deterministic workflow compiler translating WorkflowIR into native n8n JSON.

This compiler takes a valid WorkflowIR model and compiles it into the exact native
workflow structure required by n8n v2.42.6. It handles topological tiering for
deterministic canvas coordinates, multidimensional connection arrays (supporting
branching, fan-out, fan-in, loops, and error paths), node parameter mapping, and
execution policies without modifying execution semantics.
"""
from __future__ import annotations

import json
from collections import defaultdict, deque
from typing import Any, Dict, List, Optional, Set, Tuple

from backend.app.schemas.ir import ConnectionType, IREdge, IRNode, WorkflowIR
from backend.app.services.node_registry import NodeRegistry


class CompilationError(Exception):
    """Raised when workflow compilation fails due to unresolvable structural defects."""
    pass


class WorkflowCompiler:
    """Deterministic compiler transforming WorkflowIR into native n8n v2.42.6 JSON."""

    def __init__(self, registry: Optional[NodeRegistry] = None):
        self.registry = registry

    def compile(self, workflow: WorkflowIR) -> Dict[str, Any]:
        """Compiles a WorkflowIR instance into n8n native workflow dictionary.

        Args:
            workflow: A valid WorkflowIR instance.

        Returns:
            Dictionary matching n8n's native JSON workflow schema.

        Raises:
            CompilationError: If the workflow is invalid or contains unresolvable references.
        """
        if not workflow.nodes:
            raise CompilationError("Cannot compile empty workflow with no nodes.")

        # Check for unique node names required by n8n connection referencing
        seen_names: Set[str] = set()
        for node in workflow.nodes:
            if node.name in seen_names:
                raise CompilationError(
                    f"Duplicate node display name '{node.name}' detected. "
                    "n8n connections require unique node names within a workflow."
                )
            seen_names.add(node.name)

        node_map: Dict[str, IRNode] = {n.id: n for n in workflow.nodes}

        # 1. Compute deterministic canvas layout coordinates
        positions = self._calculate_canvas_positions(workflow)

        # 2. Compile discrete node representations
        # Sort nodes deterministically by ID to ensure repeatable compilation output
        sorted_nodes = sorted(workflow.nodes, key=lambda n: n.id)
        compiled_nodes: List[Dict[str, Any]] = []

        for node in sorted_nodes:
            pos = positions[node.id]
            node_dict: Dict[str, Any] = {
                "id": node.id,
                "name": node.name,
                "type": node.node_type,
                "typeVersion": node.type_version,
                "position": [pos[0], pos[1]],
                "parameters": dict(node.parameters),
            }

            if node.disabled:
                node_dict["disabled"] = True

            if node.notes:
                node_dict["notes"] = node.notes

            if node.credentials:
                normalized_creds = {}
                for cred_type, cred_val in node.credentials.items():
                    if isinstance(cred_val, dict):
                        normalized_creds[cred_type] = dict(cred_val)
                    elif isinstance(cred_val, str) and cred_val.strip():
                        normalized_creds[cred_type] = {"id": cred_val.strip()}
                if normalized_creds:
                    node_dict["credentials"] = normalized_creds

            # Node execution policies
            if node.execution_policy.continue_on_fail:
                node_dict["continueOnFail"] = True

            if node.execution_policy.retry_on_fail:
                node_dict["retryOnFail"] = True
                node_dict["maxTries"] = node.execution_policy.max_tries
                node_dict["waitBetweenTries"] = node.execution_policy.wait_between_tries

            compiled_nodes.append(node_dict)

        # 3. Assemble connection matrix
        connections = self._assemble_connections(workflow, node_map)

        # 4. Compile execution settings
        settings: Dict[str, Any] = {
            "executionTimeout": workflow.settings.execution_timeout,
            "saveExecutionProgress": workflow.settings.save_execution_progress,
            "saveManualExecutions": workflow.settings.save_manual_executions,
            "timezone": workflow.settings.timezone,
            "executionOrder": "v1",
        }
        if workflow.settings.error_workflow_id:
            settings["errorWorkflow"] = workflow.settings.error_workflow_id

        # 5. Build final payload
        compiled_payload: Dict[str, Any] = {
            "name": workflow.name,
            "nodes": compiled_nodes,
            "connections": connections,
            "active": False,  # Generated workflows are strictly inactive drafts
            "settings": settings,
            "meta": {
                "templateCredsSetupCompleted": True,
                "compiler": "n8n-workflow-ai-compiler",
                "compilerVersion": "2.42.6",
                "irVersion": workflow.version,
            },
            "pinData": {},
        }

        return compiled_payload

    def compile_to_json(self, workflow: WorkflowIR, indent: int = 2) -> str:
        """Convenience method returning serialized JSON string."""
        compiled_dict = self.compile(workflow)
        return json.dumps(compiled_dict, indent=indent, sort_keys=True)

    def _calculate_canvas_positions(self, workflow: WorkflowIR) -> Dict[str, Tuple[float, float]]:
        """Calculates collision-free 2D grid coordinates based on topological tiers.

        Preserves explicitly defined non-zero coordinates if present in the IR.
        """
        node_map = {n.id: n for n in workflow.nodes}
        positions: Dict[str, Tuple[float, float]] = {}

        # If all nodes already have explicit non-zero positions, preserve them
        has_full_positions = all(
            n.position is not None and (n.position.x != 0.0 or n.position.y != 0.0)
            for n in workflow.nodes
        )
        if has_full_positions:
            for n in workflow.nodes:
                positions[n.id] = (n.position.x, n.position.y)  # type: ignore[union-attr]
            return positions

        # Build forward adjacency for layout tiering (using main connections)
        incoming_count: Dict[str, int] = {n.id: 0 for n in workflow.nodes}
        adj: Dict[str, List[str]] = defaultdict(list)

        for edge in workflow.edges:
            if edge.connection_type == ConnectionType.MAIN:
                adj[edge.source_id].append(edge.target_id)
                incoming_count[edge.target_id] += 1

        # Roots are trigger nodes or nodes with 0 incoming main edges
        roots = [
            n.id for n in workflow.nodes
            if incoming_count[n.id] == 0 or "trigger" in n.node_type.lower() or "webhook" in n.node_type.lower()
        ]
        if not roots:
            roots = [workflow.nodes[0].id]

        # Assign tiers via BFS, breaking cycles using visited sets
        tier_assignment: Dict[str, int] = {}
        queue: deque[Tuple[str, int]] = deque((r, 0) for r in sorted(roots))
        visited: Set[str] = set()

        while queue:
            node_id, tier = queue.popleft()
            if node_id in visited:
                continue
            visited.add(node_id)
            tier_assignment[node_id] = max(tier_assignment.get(node_id, 0), tier)

            for target_id in sorted(adj.get(node_id, [])):
                if target_id not in visited:
                    queue.append((target_id, tier + 1))

        # Any unvisited nodes (e.g. disconnected components) get tier 0 or max_tier + 1
        max_tier = max(tier_assignment.values()) if tier_assignment else 0
        for n in workflow.nodes:
            if n.id not in tier_assignment:
                tier_assignment[n.id] = max_tier + 1

        # Group nodes by tier
        tier_groups: Dict[int, List[str]] = defaultdict(list)
        for nid, tier in sorted(tier_assignment.items()):
            tier_groups[tier].append(nid)

        # Calculate coordinates: x moves right with tier, y centers vertically
        for tier, node_ids in tier_groups.items():
            x_pos = 240.0 + (tier * 260.0)
            node_ids_sorted = sorted(node_ids)  # Stable sorting
            count = len(node_ids_sorted)
            vertical_spacing = 180.0
            start_y = 300.0 - ((count - 1) * vertical_spacing / 2.0)

            for idx, nid in enumerate(node_ids_sorted):
                node = node_map[nid]
                if node.position is not None and (node.position.x != 0.0 or node.position.y != 0.0):
                    positions[nid] = (node.position.x, node.position.y)
                else:
                    y_pos = start_y + (idx * vertical_spacing)
                    positions[nid] = (x_pos, y_pos)

        return positions

    def _assemble_connections(
        self,
        workflow: WorkflowIR,
        node_map: Dict[str, IRNode]
    ) -> Dict[str, Dict[str, List[List[Dict[str, Any]]]]]:
        """Assembles the nested n8n connections matrix.

        n8n format:
        connections[source_node_name][connection_type][source_output_index] = [
            {"node": target_node_name, "type": connection_type, "index": target_input_index}
        ]
        """
        connections: Dict[str, Dict[str, List[List[Dict[str, Any]]]]] = {}

        # Deterministically sort edges to ensure repeatable output
        sorted_edges = sorted(
            workflow.edges,
            key=lambda e: (e.source_id, e.connection_type.value, e.source_output_index, e.target_id, e.target_input_index)
        )

        for edge in sorted_edges:
            src_node = node_map.get(edge.source_id)
            tgt_node = node_map.get(edge.target_id)
            if not src_node:
                raise CompilationError(f"Edge references non-existent source node '{edge.source_id}'.")
            if not tgt_node:
                raise CompilationError(f"Edge references non-existent target node '{edge.target_id}'.")

            src_name = src_node.name
            tgt_name = tgt_node.name
            conn_type = edge.connection_type.value
            out_idx = edge.source_output_index
            in_idx = edge.target_input_index

            if src_name not in connections:
                connections[src_name] = {}
            if conn_type not in connections[src_name]:
                connections[src_name][conn_type] = []

            # Ensure enough array slots for the output index
            while len(connections[src_name][conn_type]) <= out_idx:
                connections[src_name][conn_type].append([])

            connections[src_name][conn_type][out_idx].append({
                "node": tgt_name,
                "type": conn_type,
                "index": in_idx,
            })

        return connections


def compile_workflow(workflow: WorkflowIR, registry: Optional[NodeRegistry] = None) -> Dict[str, Any]:
    """Top-level functional compiler entrypoint."""
    compiler = WorkflowCompiler(registry=registry)
    return compiler.compile(workflow)
