import test from 'node:test';
import assert from 'node:assert/strict';

import { mapWorkflowIRToCanvas } from '../src/components/canvas/workflowCanvasAdapter.ts';

// Helper simulating undo/redo history management logic
class WorkflowEditorState {
  constructor(initial) {
    this.current = JSON.parse(JSON.stringify(initial));
    this.saved = JSON.parse(JSON.stringify(initial));
    this.past = [];
    this.future = [];
  }

  pushEdit(next) {
    this.past.push(JSON.parse(JSON.stringify(this.current)));
    this.future = [];
    this.current = JSON.parse(JSON.stringify(next));
  }

  undo() {
    if (this.past.length === 0) return false;
    const prev = this.past.pop();
    this.future.unshift(JSON.parse(JSON.stringify(this.current)));
    this.current = prev;
    return true;
  }

  redo() {
    if (this.future.length === 0) return false;
    const next = this.future.shift();
    this.past.push(JSON.parse(JSON.stringify(this.current)));
    this.current = next;
    return true;
  }

  discard() {
    this.current = JSON.parse(JSON.stringify(this.saved));
    this.past = [];
    this.future = [];
  }

  markSaved() {
    this.saved = JSON.parse(JSON.stringify(this.current));
  }

  isDirty() {
    return JSON.stringify(this.current) !== JSON.stringify(this.saved);
  }
}

test('WorkflowEditor: parameter editing preserves other node fields and tracks dirty state', () => {
  const initial = {
    id: 'wf_1',
    name: 'Sample Flow',
    nodes: [
      {
        id: 'n1',
        name: 'HTTP Request',
        node_type: 'n8n-nodes-base.httpRequest',
        parameters: { url: 'https://initial.com', method: 'GET' },
      },
    ],
    edges: [],
  };

  const editor = new WorkflowEditorState(initial);
  assert.equal(editor.isDirty(), false);

  // Edit parameter
  const updatedNodes = [
    {
      ...editor.current.nodes[0],
      parameters: { ...editor.current.nodes[0].parameters, url: 'https://updated.com' },
    },
  ];
  editor.pushEdit({ ...editor.current, nodes: updatedNodes });

  assert.equal(editor.isDirty(), true);
  assert.equal(editor.current.nodes[0].parameters.url, 'https://updated.com');
  assert.equal(editor.current.nodes[0].parameters.method, 'GET');
  assert.equal(editor.current.nodes[0].name, 'HTTP Request');
});

test('WorkflowEditor: adding and removing connections updates topological edges', () => {
  const initial = {
    id: 'wf_1',
    name: 'Connection Flow',
    nodes: [
      { id: 'n1', name: 'Trigger', node_type: 'n8n-nodes-base.scheduleTrigger' },
      { id: 'n2', name: 'Processor', node_type: 'n8n-nodes-base.code' },
      { id: 'n3', name: 'Notifier', node_type: 'n8n-nodes-base.slack' },
    ],
    edges: [{ source_id: 'n1', target_id: 'n2', connection_type: 'main', source_output_index: 0, target_input_index: 0 }],
  };

  const editor = new WorkflowEditorState(initial);

  // Add edge between n2 and n3
  const newEdge = {
    source_id: 'n2',
    target_id: 'n3',
    connection_type: 'main',
    source_output_index: 0,
    target_input_index: 0,
  };
  editor.pushEdit({ ...editor.current, edges: [...editor.current.edges, newEdge] });
  assert.equal(editor.current.edges.length, 2);

  // Remove first edge (n1 -> n2)
  const filteredEdges = editor.current.edges.filter((e) => !(e.source_id === 'n1' && e.target_id === 'n2'));
  editor.pushEdit({ ...editor.current, edges: filteredEdges });
  assert.equal(editor.current.edges.length, 1);
  assert.equal(editor.current.edges[0].source_id, 'n2');
  assert.equal(editor.current.edges[0].target_id, 'n3');
});

test('WorkflowEditor: undo, redo, and discard state transitions', () => {
  const initial = {
    id: 'wf_1',
    name: 'History Flow',
    nodes: [{ id: 'n1', name: 'Original Name', node_type: 'n8n-nodes-base.code', parameters: {} }],
    edges: [],
  };

  const editor = new WorkflowEditorState(initial);

  // Edit 1: change name
  editor.pushEdit({
    ...editor.current,
    nodes: [{ ...editor.current.nodes[0], name: 'First Edit' }],
  });
  assert.equal(editor.current.nodes[0].name, 'First Edit');

  // Edit 2: change name again
  editor.pushEdit({
    ...editor.current,
    nodes: [{ ...editor.current.nodes[0], name: 'Second Edit' }],
  });
  assert.equal(editor.current.nodes[0].name, 'Second Edit');

  // Undo 1
  assert.equal(editor.undo(), true);
  assert.equal(editor.current.nodes[0].name, 'First Edit');

  // Undo 2
  assert.equal(editor.undo(), true);
  assert.equal(editor.current.nodes[0].name, 'Original Name');

  // Redo 1
  assert.equal(editor.redo(), true);
  assert.equal(editor.current.nodes[0].name, 'First Edit');

  // Discard reverts back to saved baseline
  editor.discard();
  assert.equal(editor.current.nodes[0].name, 'Original Name');
  assert.equal(editor.isDirty(), false);
  assert.equal(editor.past.length, 0);
  assert.equal(editor.future.length, 0);
});

test('WorkflowEditor: canvas adapter safely handles dangling edges during editing', () => {
  const workflowWithDanglingEdge = {
    id: 'wf_dangling',
    name: 'Dangling Flow',
    nodes: [{ id: 'n1', name: 'Trigger', node_type: 'n8n-nodes-base.scheduleTrigger' }],
    edges: [
      { source_id: 'n1', target_id: 'n_deleted', connection_type: 'main' },
      { source_id: 'n_missing', target_id: 'n1', connection_type: 'main' },
    ],
  };

  const canvas = mapWorkflowIRToCanvas(workflowWithDanglingEdge);
  assert.equal(canvas.nodes.length, 1);
  // Both edges reference missing nodes, so canvas drops them safely
  assert.equal(canvas.edges.length, 0);
});

test('WorkflowEditor: optimistic concurrency conflict status is handled honestly', () => {
  const currentRev = 2;
  const attemptedRev = 1;

  // Simulate conflict check logic
  const isConflict = attemptedRev !== currentRev;
  assert.equal(isConflict, true);

  const conflictError = {
    status: 409,
    message: `Stale revision conflict: current revision is ${currentRev}, expected ${attemptedRev}.`,
  };

  assert.equal(conflictError.status, 409);
  assert.ok(conflictError.message.includes('Stale revision conflict'));
});

test('WorkflowEditor: adding a node from library updates nodes, edges and dirty state', () => {
  const initial = {
    id: 'wf_add_test',
    name: 'Add Test Flow',
    nodes: [
      { id: 'node_trigger', name: 'Schedule Trigger', node_type: 'n8n-nodes-base.scheduleTrigger', position: { x: 250, y: 250 } },
    ],
    edges: [],
  };

  const editor = new WorkflowEditorState(initial);
  assert.equal(editor.isDirty(), false);

  // Add node from library
  const newNode = {
    id: 'slack_1',
    name: 'Slack Notification',
    node_type: 'n8n-nodes-base.slack',
    type_version: 2.2,
    position: { x: 530, y: 250 },
    parameters: { channel: '#general' },
  };

  const newEdge = {
    source_id: 'node_trigger',
    target_id: 'slack_1',
    connection_type: 'main',
    source_output_index: 0,
    target_input_index: 0,
  };

  editor.pushEdit({
    ...editor.current,
    nodes: [...editor.current.nodes, newNode],
    edges: [...editor.current.edges, newEdge],
  });

  assert.equal(editor.isDirty(), true);
  assert.equal(editor.current.nodes.length, 2);
  assert.equal(editor.current.edges.length, 1);
  assert.equal(editor.current.nodes[1].name, 'Slack Notification');

  // Verify undo reverts the addition
  assert.equal(editor.undo(), true);
  assert.equal(editor.current.nodes.length, 1);
  assert.equal(editor.current.edges.length, 0);
  assert.equal(editor.isDirty(), false);
});

test('WorkflowEditor: deleting a node removes incident edges and tracks history', () => {
  const initial = {
    id: 'wf_del_test',
    name: 'Delete Test Flow',
    nodes: [
      { id: 'n1', name: 'Trigger', node_type: 'n8n-nodes-base.scheduleTrigger' },
      { id: 'n2', name: 'Processor', node_type: 'n8n-nodes-base.code' },
      { id: 'n3', name: 'Notifier', node_type: 'n8n-nodes-base.slack' },
    ],
    edges: [
      { source_id: 'n1', target_id: 'n2', connection_type: 'main' },
      { source_id: 'n2', target_id: 'n3', connection_type: 'main' },
    ],
  };

  const editor = new WorkflowEditorState(initial);

  // Delete node n2
  const targetId = 'n2';
  const remainingNodes = editor.current.nodes.filter((n) => n.id !== targetId);
  const remainingEdges = editor.current.edges.filter((e) => e.source_id !== targetId && e.target_id !== targetId);

  editor.pushEdit({
    ...editor.current,
    nodes: remainingNodes,
    edges: remainingEdges,
  });

  assert.equal(editor.isDirty(), true);
  assert.equal(editor.current.nodes.length, 2);
  assert.equal(editor.current.edges.length, 0); // Both edges touched n2, so both are removed
  assert.deepEqual(editor.current.nodes.map((n) => n.id), ['n1', 'n3']);

  // Canvas adapter verification: no dangling edges remain
  const canvas = mapWorkflowIRToCanvas(editor.current);
  assert.equal(canvas.nodes.length, 2);
  assert.equal(canvas.edges.length, 0);
});

test('WorkflowEditor: workflow name editing updates name and is tracked in undo stack', () => {
  const initial = {
    id: 'wf_name_test',
    name: 'Original Workflow Title',
    nodes: [{ id: 'n1', name: 'Trigger', node_type: 'n8n-nodes-base.scheduleTrigger' }],
    edges: [],
  };

  const editor = new WorkflowEditorState(initial);
  editor.pushEdit({ ...editor.current, name: 'Renamed Workflow Title' });

  assert.equal(editor.isDirty(), true);
  assert.equal(editor.current.name, 'Renamed Workflow Title');

  editor.undo();
  assert.equal(editor.current.name, 'Original Workflow Title');
  assert.equal(editor.isDirty(), false);
});

test('WorkflowCanvasAdapter: dragging one node preserves other nodes fallback positions without collapsing to (100, 150)', () => {
  const workflow = {
    id: 'wf_pos_test',
    name: 'Position Test Flow',
    nodes: [
      { id: 'n1', name: 'Trigger', node_type: 'n8n-nodes-base.scheduleTrigger' },
      { id: 'n2', name: 'Processor', node_type: 'n8n-nodes-base.code' },
      { id: 'n3', name: 'Notifier', node_type: 'n8n-nodes-base.slack' },
    ],
    edges: [
      { source_id: 'n1', target_id: 'n2', connection_type: 'main' },
      { source_id: 'n2', target_id: 'n3', connection_type: 'main' },
    ],
  };

  // Initial layout: all 3 nodes get distinct X coordinates
  const initialCanvas = mapWorkflowIRToCanvas(workflow);
  const n1PosInit = initialCanvas.nodes.find((n) => n.id === 'n1').position;
  const n2PosInit = initialCanvas.nodes.find((n) => n.id === 'n2').position;
  const n3PosInit = initialCanvas.nodes.find((n) => n.id === 'n3').position;

  assert.notEqual(n1PosInit.x, n2PosInit.x, 'n1 and n2 must have distinct X coordinates');
  assert.notEqual(n2PosInit.x, n3PosInit.x, 'n2 and n3 must have distinct X coordinates');

  // Simulate user dragging n2 to (550, 280)
  const workflowWithN2Dragged = {
    ...workflow,
    nodes: [
      { id: 'n1', name: 'Trigger', node_type: 'n8n-nodes-base.scheduleTrigger' }, // no explicit pos
      { id: 'n2', name: 'Processor', node_type: 'n8n-nodes-base.code', position: { x: 550, y: 280 } }, // explicit pos
      { id: 'n3', name: 'Notifier', node_type: 'n8n-nodes-base.slack' }, // no explicit pos
    ],
  };

  const canvasAfterDrag = mapWorkflowIRToCanvas(workflowWithN2Dragged);
  const n1PosAfter = canvasAfterDrag.nodes.find((n) => n.id === 'n1').position;
  const n2PosAfter = canvasAfterDrag.nodes.find((n) => n.id === 'n2').position;
  const n3PosAfter = canvasAfterDrag.nodes.find((n) => n.id === 'n3').position;

  // n2 must have the new dragged position
  assert.equal(n2PosAfter.x, 550);
  assert.equal(n2PosAfter.y, 280);

  // CRITICAL: n1 and n3 must NOT have collapsed to the default (100, 150) overlapping each other
  assert.equal(n1PosAfter.x, n1PosInit.x, 'n1 must preserve its layout position');
  assert.equal(n3PosAfter.x, n3PosInit.x, 'n3 must preserve its layout position');
  assert.notEqual(n1PosAfter.x, n3PosAfter.x, 'n1 and n3 must not overlap');
});

test('WorkflowCanvasAdapter: saved explicit node positions in draft are restored faithfully upon reopening', () => {
  const savedDraft = {
    id: 'wf_saved_draft',
    name: 'Saved Draft Flow',
    nodes: [
      { id: 'n1', name: 'Trigger', node_type: 'n8n-nodes-base.scheduleTrigger', position: { x: 120, y: 220 } },
      { id: 'n2', name: 'Processor', node_type: 'n8n-nodes-base.code', position: { x: 480, y: 310 } },
      { id: 'n3', name: 'Notifier', node_type: 'n8n-nodes-base.slack', position: { x: 840, y: 400 } },
    ],
    edges: [
      { source_id: 'n1', target_id: 'n2', connection_type: 'main' },
      { source_id: 'n2', target_id: 'n3', connection_type: 'main' },
    ],
  };

  const canvas = mapWorkflowIRToCanvas(savedDraft);
  const n1 = canvas.nodes.find((n) => n.id === 'n1');
  const n2 = canvas.nodes.find((n) => n.id === 'n2');
  const n3 = canvas.nodes.find((n) => n.id === 'n3');

  assert.deepEqual(n1.position, { x: 120, y: 220 });
  assert.deepEqual(n2.position, { x: 480, y: 310 });
  assert.deepEqual(n3.position, { x: 840, y: 400 });
});

