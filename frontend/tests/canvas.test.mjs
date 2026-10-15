import test from 'node:test';
import assert from 'node:assert/strict';

// Import canvas adapter
import { mapWorkflowIRToCanvas } from '../src/components/canvas/workflowCanvasAdapter.ts';

// Test 1: Real workflow IR mapping into canvas nodes and edges
test('mapWorkflowIRToCanvas maps valid linear workflow into nodes and edges', () => {
  const linearWorkflow = {
    id: 'wf_linear_1',
    name: 'Slack Notification Pipeline',
    nodes: [
      {
        id: 'node_schedule',
        name: 'Schedule Trigger',
        node_type: 'n8n-nodes-base.scheduleTrigger',
        type_version: 1.2,
        position: { x: 250, y: 300 },
        parameters: { rule: { interval: [{ field: 'hours', hoursInterval: 1 }] } },
      },
      {
        id: 'node_slack',
        name: 'Slack Alert',
        node_type: 'n8n-nodes-base.slack',
        type_version: 2.2,
        position: { x: 570, y: 300 },
        parameters: { channel: '#general', text: 'Health check OK' },
      },
    ],
    edges: [
      {
        source_id: 'node_schedule',
        target_id: 'node_slack',
        connection_type: 'main',
        source_output_index: 0,
        target_input_index: 0,
      },
    ],
  };

  const { nodes, edges } = mapWorkflowIRToCanvas(linearWorkflow);

  assert.equal(nodes.length, 2);
  assert.equal(edges.length, 1);

  // Verify node data
  const scheduleNode = nodes.find((n) => n.id === 'node_schedule');
  assert.ok(scheduleNode);
  assert.equal(scheduleNode.position.x, 250);
  assert.equal(scheduleNode.position.y, 300);
  assert.equal(scheduleNode.data.name, 'Schedule Trigger');
  assert.equal(scheduleNode.data.node_type, 'n8n-nodes-base.scheduleTrigger');

  const slackNode = nodes.find((n) => n.id === 'node_slack');
  assert.ok(slackNode);
  assert.equal(slackNode.position.x, 570);
  assert.equal(slackNode.position.y, 300);

  // Verify edge handles
  const edge = edges[0];
  assert.equal(edge.source, 'node_schedule');
  assert.equal(edge.target, 'node_slack');
  assert.equal(edge.sourceHandle, 'output-0');
  assert.equal(edge.targetHandle, 'input-0');
  assert.equal(edge.animated, false);
});

// Test 2: Branching and multiple connections mapping
test('mapWorkflowIRToCanvas handles branching (If node True/False) and error connections', () => {
  const branchingWorkflow = {
    id: 'wf_branching',
    name: 'Conditional Triage Flow',
    nodes: [
      {
        id: 'node_webhook',
        name: 'Webhook Trigger',
        node_type: 'n8n-nodes-base.webhook',
        type_version: 2.0,
      },
      {
        id: 'node_if',
        name: 'Urgency Filter',
        node_type: 'n8n-nodes-base.if',
        type_version: 2.2,
      },
      {
        id: 'node_urgent_slack',
        name: 'Urgent Slack',
        node_type: 'n8n-nodes-base.slack',
        type_version: 2.2,
      },
      {
        id: 'node_normal_email',
        name: 'Normal Email',
        node_type: 'n8n-nodes-base.emailSend',
        type_version: 2.1,
      },
      {
        id: 'node_error_handler',
        name: 'Error Handler',
        node_type: 'n8n-nodes-base.slack',
        type_version: 2.2,
      },
    ],
    edges: [
      {
        source_id: 'node_webhook',
        target_id: 'node_if',
        connection_type: 'main',
        source_output_index: 0,
        target_input_index: 0,
      },
      {
        source_id: 'node_if',
        target_id: 'node_urgent_slack',
        connection_type: 'main',
        source_output_index: 0,
        target_input_index: 0,
        description: 'High Urgency',
      },
      {
        source_id: 'node_if',
        target_id: 'node_normal_email',
        connection_type: 'main',
        source_output_index: 1,
        target_input_index: 0,
      },
      {
        source_id: 'node_if',
        target_id: 'node_error_handler',
        connection_type: 'error',
        source_output_index: 0,
        target_input_index: 0,
      },
    ],
  };

  const { nodes, edges } = mapWorkflowIRToCanvas(branchingWorkflow);

  assert.equal(nodes.length, 5);
  assert.equal(edges.length, 4);

  // Check True branch edge (output-0)
  const trueEdge = edges.find((e) => e.target === 'node_urgent_slack');
  assert.ok(trueEdge);
  assert.equal(trueEdge.sourceHandle, 'output-0');
  assert.equal(trueEdge.label, 'High Urgency');

  // Check False branch edge (output-1)
  const falseEdge = edges.find((e) => e.target === 'node_normal_email');
  assert.ok(falseEdge);
  assert.equal(falseEdge.sourceHandle, 'output-1');
  assert.equal(falseEdge.label, 'False');

  // Check Error branch edge
  const errorEdge = edges.find((e) => e.target === 'node_error_handler');
  assert.ok(errorEdge);
  assert.equal(errorEdge.sourceHandle, 'error');
  assert.equal(errorEdge.label, 'Error');
  assert.ok(errorEdge.style.stroke.includes('#ef4444') || errorEdge.style.stroke.includes('--state-error'));
});

// Test 3: Fallback layout computation when positions are omitted
test('mapWorkflowIRToCanvas computes deterministic DAG layout when coordinates are missing', () => {
  const unpositionedWorkflow = {
    id: 'wf_unpositioned',
    name: 'Pipeline Without Coordinates',
    nodes: [
      { id: 'node_1', name: 'Trigger', node_type: 'n8n-nodes-base.scheduleTrigger', type_version: 1.0 },
      { id: 'node_2', name: 'Transform', node_type: 'n8n-nodes-base.code', type_version: 2.0 },
      { id: 'node_3', name: 'Destination', node_type: 'n8n-nodes-base.postgres', type_version: 2.5 },
    ],
    edges: [
      { source_id: 'node_1', target_id: 'node_2' },
      { source_id: 'node_2', target_id: 'node_3' },
    ],
  };

  const { nodes } = mapWorkflowIRToCanvas(unpositionedWorkflow);

  assert.equal(nodes.length, 3);
  const n1 = nodes.find((n) => n.id === 'node_1');
  const n2 = nodes.find((n) => n.id === 'node_2');
  const n3 = nodes.find((n) => n.id === 'node_3');

  // Depth progression: n1.x < n2.x < n3.x
  assert.ok(n1.position.x < n2.position.x, 'Root node must have lower X than downstream node');
  assert.ok(n2.position.x < n3.position.x, 'Mid node must have lower X than tail node');
});

// Test 4: Empty and null workflows return safe empty canvas data
test('mapWorkflowIRToCanvas handles null, undefined, and empty workflows gracefully', () => {
  assert.deepEqual(mapWorkflowIRToCanvas(null), { nodes: [], edges: [] });
  assert.deepEqual(mapWorkflowIRToCanvas(undefined), { nodes: [], edges: [] });
  assert.deepEqual(mapWorkflowIRToCanvas({ id: 'empty', name: 'Empty', nodes: [], edges: [] }), {
    nodes: [],
    edges: [],
  });
  assert.deepEqual(mapWorkflowIRToCanvas({ id: 'no_nodes' }), { nodes: [], edges: [] });
});

// Test 5: Malformed and dangling edges are filtered safely
test('mapWorkflowIRToCanvas ignores dangling edges referencing non-existent nodes', () => {
  const workflowWithDanglingEdge = {
    id: 'wf_dangling',
    name: 'Dangling Edge Test',
    nodes: [
      { id: 'valid_1', name: 'Node 1', node_type: 'n8n-nodes-base.scheduleTrigger', type_version: 1.0 },
      { id: 'valid_2', name: 'Node 2', node_type: 'n8n-nodes-base.slack', type_version: 2.0 },
    ],
    edges: [
      { source_id: 'valid_1', target_id: 'valid_2' },
      { source_id: 'valid_1', target_id: 'non_existent_node_99' },
      { source_id: 'phantom_source', target_id: 'valid_2' },
    ],
  };

  const { nodes, edges } = mapWorkflowIRToCanvas(workflowWithDanglingEdge);
  assert.equal(nodes.length, 2);
  assert.equal(edges.length, 1);
  assert.equal(edges[0].source, 'valid_1');
  assert.equal(edges[0].target, 'valid_2');
});

// Test 6: Malformed or missing optional node fields are safely preserved
test('mapWorkflowIRToCanvas preserves missing optional node fields without error', () => {
  const minimalNodeWorkflow = {
    id: 'wf_minimal',
    name: 'Minimal Node Fields',
    nodes: [
      {
        id: 'min_node',
        name: 'Barebones Node',
        node_type: 'n8n-nodes-base.manualTrigger',
        // type_version omitted
        // parameters omitted
        // credentials omitted
        // execution_policy omitted
      },
    ],
    edges: [],
  };

  const { nodes, edges } = mapWorkflowIRToCanvas(minimalNodeWorkflow);
  assert.equal(nodes.length, 1);
  assert.equal(edges.length, 0);
  assert.equal(nodes[0].data.name, 'Barebones Node');
  assert.equal(nodes[0].data.node_type, 'n8n-nodes-base.manualTrigger');
});
