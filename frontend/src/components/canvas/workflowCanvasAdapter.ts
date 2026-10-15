import type { Node, Edge } from '@xyflow/react';
import type { WorkflowIR, IRNode, IREdge } from '../../types/workflow';

export interface CanvasGraphData {
  nodes: Node<IRNode>[];
  edges: Edge[];
}

/**
 * Deterministically computes 2D coordinates for nodes that lack explicit positions.
 * Groups nodes by DAG topological depth and distributes them horizontally.
 */
export function computeFallbackLayout(nodes: IRNode[], edges: IREdge[]): Map<string, { x: number; y: number }> {
  const positions = new Map<string, { x: number; y: number }>();
  if (!nodes || nodes.length === 0) return positions;

  // Build adjacency list and in-degree counts
  const nodeIds = new Set(nodes.map((n) => n.id));
  const adj = new Map<string, string[]>();
  const inDegree = new Map<string, number>();

  nodes.forEach((n) => {
    adj.set(n.id, []);
    inDegree.set(n.id, 0);
  });

  edges.forEach((e) => {
    if (nodeIds.has(e.source_id) && nodeIds.has(e.target_id)) {
      adj.get(e.source_id)?.push(e.target_id);
      inDegree.set(e.target_id, (inDegree.get(e.target_id) || 0) + 1);
    }
  });

  // Assign depths via BFS
  const depthMap = new Map<string, number>();
  const queue: string[] = [];

  // Root nodes have inDegree 0
  nodes.forEach((n) => {
    if ((inDegree.get(n.id) || 0) === 0) {
      depthMap.set(n.id, 0);
      queue.push(n.id);
    }
  });

  // If no root node (e.g. cycle), seed with first node
  if (queue.length === 0 && nodes.length > 0) {
    depthMap.set(nodes[0].id, 0);
    queue.push(nodes[0].id);
  }

  while (queue.length > 0) {
    const currId = queue.shift()!;
    const currDepth = depthMap.get(currId) || 0;
    const neighbors = adj.get(currId) || [];

    for (const nextId of neighbors) {
      const nextDepth = depthMap.get(nextId);
      if (nextDepth === undefined || nextDepth < currDepth + 1) {
        depthMap.set(nextId, currDepth + 1);
        queue.push(nextId);
      }
    }
  }

  // Any unreached nodes get depth 0
  nodes.forEach((n) => {
    if (!depthMap.has(n.id)) {
      depthMap.set(n.id, 0);
    }
  });

  // Group by depth
  const layers = new Map<number, string[]>();
  nodes.forEach((n) => {
    const d = depthMap.get(n.id) || 0;
    if (!layers.has(d)) layers.set(d, []);
    layers.get(d)!.push(n.id);
  });

  // Calculate coordinates: X = 100 + depth * 320, Y = 150 + rank * 160
  layers.forEach((idsAtDepth, depth) => {
    idsAtDepth.forEach((id, index) => {
      positions.set(id, {
        x: 100 + depth * 320,
        y: 150 + index * 160,
      });
    });
  });

  return positions;
}

/**
 * Transforms a raw or validated WorkflowIR into @xyflow/react nodes and edges.
 * Handles missing fields, custom positions, branching handles, and connection styling.
 */
export function mapWorkflowIRToCanvas(workflow?: WorkflowIR | null): CanvasGraphData {
  if (!workflow || !Array.isArray(workflow.nodes) || workflow.nodes.length === 0) {
    return { nodes: [], edges: [] };
  }

  const validNodes = workflow.nodes.filter((n) => n && typeof n.id === 'string' && n.id.trim().length > 0);
  const nodeMap = new Map<string, IRNode>(validNodes.map((n) => [n.id, n]));

  // Compute fallback layout for all nodes so any node lacking explicit coordinates retains a valid coordinate
  const fallbackLayout = computeFallbackLayout(validNodes, workflow.edges || []);

  const flowNodes: Node<IRNode>[] = validNodes.map((node) => {
    let x = 100;
    let y = 150;

    if (node.position && (node.position.x !== 0 || node.position.y !== 0)) {
      x = node.position.x;
      y = node.position.y;
    } else if (fallbackLayout.has(node.id)) {
      const pos = fallbackLayout.get(node.id)!;
      x = pos.x;
      y = pos.y;
    }

    return {
      id: node.id,
      type: 'n8nNode',
      position: { x, y },
      data: node,
      dragHandle: '.node-card-drag-handle',
    };
  });

  const validEdges = Array.isArray(workflow.edges) ? workflow.edges : [];
  const flowEdges: Edge[] = [];

  validEdges.forEach((edge, index) => {
    // Only map edges between nodes that actually exist in the workflow
    if (!edge || !nodeMap.has(edge.source_id) || !nodeMap.has(edge.target_id)) {
      return;
    }

    const isError = edge.connection_type === 'error';
    const sourceOutputIndex = typeof edge.source_output_index === 'number' ? edge.source_output_index : 0;
    const targetInputIndex = typeof edge.target_input_index === 'number' ? edge.target_input_index : 0;

    const sourceHandle = isError ? 'error' : `output-${sourceOutputIndex}`;
    const targetHandle = `input-${targetInputIndex}`;

    let label: string | undefined = edge.description;
    if (!label) {
      if (isError) {
        label = 'Error';
      } else if (sourceOutputIndex === 1) {
        label = 'False';
      } else if (sourceOutputIndex > 1) {
        label = `Branch ${sourceOutputIndex}`;
      }
    }

    flowEdges.push({
      id: `edge-${edge.source_id}-${edge.target_id}-${sourceOutputIndex}-${targetInputIndex}-${index}`,
      source: edge.source_id,
      target: edge.target_id,
      sourceHandle,
      targetHandle,
      type: 'smoothstep',
      animated: false,
      label,
      labelStyle: {
        fill: isError ? 'var(--state-error, #ef4444)' : 'var(--text-secondary, #9CA3AF)',
        fontSize: 10,
        fontWeight: 600,
        fontFamily: 'var(--font-mono, monospace)',
      },
      labelBgStyle: {
        fill: 'var(--bg-surface, #111827)',
        fillOpacity: 0.9,
      },
      labelBgPadding: [4, 2],
      labelBgBorderRadius: 2,
      style: {
        stroke: isError ? 'var(--state-error, #ef4444)' : 'var(--border-focused, #6B7280)',
        strokeWidth: 2,
      },
    });
  });

  return { nodes: flowNodes, edges: flowEdges };
}
