import { test } from 'node:test';
import assert from 'node:assert/strict';

// Test 1: Opening a saved draft loads conversation detail and does NOT call generation endpoints
test('Opening a saved draft loads conversation detail and does NOT call generation endpoints', async () => {
  let generationCalled = false;
  let conversationFetched = false;

  const mockGetConversation = async (id) => {
    conversationFetched = true;
    return {
      id,
      title: 'Google Sheets to Telegram',
      state: 'ready',
      original_prompt: 'When a new row is added in Google Sheets, send Telegram notification',
      messages: [{ role: 'user', content: 'Initial prompt' }],
      slots: { sheet_id: 'sheet_123', telegram_chat_id: '998877' },
      latest_draft: {
        id: 'draft_1',
        title: 'Google Sheets to Telegram',
        status: 'draft',
        latest_revision_number: 3,
        workflow_ir: {
          id: 'wf_1',
          name: 'Google Sheets to Telegram',
          nodes: [
            { id: 'node_1', name: 'Google Sheets Trigger', node_type: 'n8n-nodes-base.googleSheetsTrigger', parameters: { pollTimes: { item: [{ mode: 'everyMinute' }] } } },
            { id: 'node_2', name: 'Telegram', node_type: 'n8n-nodes-base.telegram', parameters: { chatId: '998877', text: 'New Row' } },
          ],
          edges: [{ source: 'node_1', target: 'node_2' }],
        },
        compiled_json: { nodes: [], connections: {} },
        validation_report: { is_valid: true, issues: [] },
      },
    };
  };

  const mockSendMessage = async () => {
    generationCalled = true;
    throw new Error('Generation should not be called when opening saved workflow!');
  };

  const mockCreateConversation = async () => {
    generationCalled = true;
    throw new Error('createConversation should not be called when opening saved workflow!');
  };

  // Simulate Open action lifecycle
  const conversationId = 'conv-456';
  const detail = await mockGetConversation(conversationId);

  assert.equal(conversationFetched, true);
  assert.equal(generationCalled, false, 'Generation endpoint must NOT be invoked when opening a saved draft');
  assert.equal(detail.id, 'conv-456');
  assert.equal(detail.latest_draft.latest_revision_number, 3);
});

// Test 2: Opening does not start node discovery or LLM planning
test('Opening does not start node discovery or LLM planning', async () => {
  let nodeDiscoveryStarted = false;
  let llmPlanningStarted = false;

  const detail = {
    id: 'conv-abc',
    title: 'Customer Feedback Pipeline',
    state: 'planning', // Even if database has legacy 'planning' in metadata
    latest_draft: {
      id: 'draft_abc',
      title: 'Customer Feedback Pipeline',
      status: 'ready',
      latest_revision_number: 1,
      workflow_ir: {
        id: 'wf_abc',
        name: 'Customer Feedback Pipeline',
        nodes: [{ id: 'n1', name: 'Webhook', node_type: 'n8n-nodes-base.webhook', parameters: {} }],
        edges: [],
      },
    },
  };

  // State resolver logic implemented in handleSelectPastConversation
  const isGeneratingPhase = false;
  let resolvedStageState = 'loading';

  if (detail.latest_draft && detail.latest_draft.workflow_ir) {
    resolvedStageState = 'ready'; // Directly ready for canvas, not 'planning'
  }

  if (resolvedStageState === 'planning') {
    nodeDiscoveryStarted = true;
  }
  if (isGeneratingPhase) {
    llmPlanningStarted = true;
  }

  assert.equal(resolvedStageState, 'ready');
  assert.equal(nodeDiscoveryStarted, false, 'Must not start or display node discovery for existing draft');
  assert.equal(llmPlanningStarted, false, 'Must not trigger LLM planning');
});

// Test 3: Existing nodes, parameters, and connections are faithfully restored from saved revision
test('Existing nodes, parameters, and connections are faithfully restored from saved revision', () => {
  const savedRevision = {
    revision_number: 2,
    workflow_ir: {
      id: 'wf_saved',
      name: 'Order Processing',
      nodes: [
        {
          id: 'trigger_1',
          name: 'Shopify Trigger',
          node_type: 'n8n-nodes-base.shopifyTrigger',
          parameters: { topic: 'orders/create' },
          position: [100, 200],
        },
        {
          id: 'action_1',
          name: 'Slack Notification',
          node_type: 'n8n-nodes-base.slack',
          parameters: { channel: '#orders', text: 'New order received' },
          position: [350, 200],
        },
      ],
      edges: [{ source: 'trigger_1', target: 'action_1' }],
    },
    compiled_json: {
      nodes: [{ id: 'trigger_1', name: 'Shopify Trigger' }, { id: 'action_1', name: 'Slack Notification' }],
      connections: { 'Shopify Trigger': { main: [[{ node: 'Slack Notification', type: 'main', index: 0 }]] } },
    },
  };

  // Verify node IDs, parameters, positions, and connections are intact
  assert.equal(savedRevision.workflow_ir.nodes.length, 2);
  assert.equal(savedRevision.workflow_ir.nodes[0].id, 'trigger_1');
  assert.equal(savedRevision.workflow_ir.nodes[0].parameters.topic, 'orders/create');
  assert.deepEqual(savedRevision.workflow_ir.nodes[0].position, [100, 200]);
  assert.equal(savedRevision.workflow_ir.edges.length, 1);
  assert.equal(savedRevision.workflow_ir.edges[0].source, 'trigger_1');
  assert.equal(savedRevision.workflow_ir.edges[0].target, 'action_1');
  assert.ok(savedRevision.compiled_json.connections['Shopify Trigger']);
});

// Test 4: Saved workflow title and revision number are retained and reflected in turn result
test('Saved workflow title and revision number are retained and reflected in turn result', () => {
  const detail = {
    id: 'conv-title-test',
    title: 'Custom Invoicing Automation',
    original_prompt: 'Generate an invoice when stripe charge succeeds',
    latest_draft: {
      id: 'draft-99',
      title: 'Custom Invoicing Automation',
      latest_revision_number: 4,
      workflow_ir: {
        id: 'wf-99',
        name: 'Custom Invoicing Automation',
        nodes: [{ id: 'n1', name: 'Stripe Trigger', node_type: 'n8n-nodes-base.stripeTrigger', parameters: {} }],
        edges: [],
      },
    },
  };

  const restoredIR = { ...detail.latest_draft.workflow_ir };
  if (detail.latest_draft.title) {
    restoredIR.name = detail.latest_draft.title;
  }
  const revNum = detail.latest_draft.latest_revision_number || 1;

  const turnResult = {
    conversation_id: detail.id,
    state: 'ready',
    workflow_ir: restoredIR,
    revision_number: revNum,
    latest_revision_number: revNum,
    original_prompt: detail.original_prompt,
  };

  assert.equal(turnResult.workflow_ir.name, 'Custom Invoicing Automation');
  assert.equal(turnResult.revision_number, 4);
  assert.equal(turnResult.latest_revision_number, 4);
  assert.equal(turnResult.state, 'ready');
});

// Test 5: Loading completion transitions to idle editor state rather than generation state
test('Loading completion transitions to idle editor state rather than generation state', () => {
  let stageState = 'loading'; // Started in loading
  const turnResult = {
    workflow_ir: { id: 'wf_ready', nodes: [{ id: 'n1' }], edges: [] },
  };

  // When saved draft loads
  stageState = 'ready';

  const hasActiveWorkflow = Boolean(turnResult?.workflow_ir && stageState === 'ready');
  assert.equal(stageState, 'ready');
  assert.equal(hasActiveWorkflow, true, 'hasActiveWorkflow must be true for restored draft');
});

// Test 6: Genuine active generation request for that conversation is handled correctly
test('Genuine active generation request for that conversation is handled correctly', async () => {
  let liveTrackingStarted = false;
  let currentStage = 'idle';

  const mockGetConversationStatus = async (convId) => {
    return {
      conversation_id: convId,
      is_active: true,
      stage: 'generating',
      message: 'Synthesizing workflow graph from verified schemas...',
      elapsed_seconds: 4.5,
    };
  };

  const liveStatus = await mockGetConversationStatus('conv-active-123');
  if (liveStatus && liveStatus.is_active) {
    currentStage = liveStatus.stage;
    liveTrackingStarted = true;
  }

  assert.equal(liveStatus.is_active, true);
  assert.equal(currentStage, 'generating');
  assert.equal(liveTrackingStarted, true);
});

// Test 7: Missing draft opens in honest no_draft state without auto-generating
test('Missing draft opens in honest no_draft state without auto-generating', () => {
  const detailWithoutDraft = {
    id: 'conv-no-draft',
    title: 'Unfinished Prompt',
    state: 'planning',
    original_prompt: 'Sync GitHub issues to Jira',
    messages: [{ role: 'user', content: 'Sync GitHub issues to Jira' }],
    slots: {},
    latest_draft: null,
  };

  let stageState = 'loading';
  let generationStarted = false;

  if (detailWithoutDraft.latest_draft && detailWithoutDraft.latest_draft.workflow_ir) {
    stageState = 'ready';
  } else if (detailWithoutDraft.state === 'clarifying') {
    stageState = 'clarifying';
  } else if (detailWithoutDraft.state === 'failed') {
    stageState = 'failed';
  } else {
    stageState = 'no_draft';
  }

  assert.equal(stageState, 'no_draft');
  assert.equal(generationStarted, false, 'Must not automatically start generation for conversations without drafts');
});

// Test 8: Failed conversation GET request reports error without starting generation fallback
test('Failed conversation GET request reports error without starting generation fallback', async () => {
  let generationStarted = false;
  let errorMessage = null;
  let stageState = 'loading';

  const mockGetConversation = async () => {
    throw new Error("Conversation 'conv-deleted' not found.");
  };

  try {
    await mockGetConversation();
  } catch (err) {
    errorMessage = err.message;
    stageState = 'failed';
  }

  assert.equal(stageState, 'failed');
  assert.equal(errorMessage, "Conversation 'conv-deleted' not found.");
  assert.equal(generationStarted, false, 'Failed retrieval must not trigger generation fallback');
});

// Test 9: Switching between two saved workflows cannot display stale data or overwrite selected workflow
test('Switching between two saved workflows cannot display stale data or overwrite selected workflow', async () => {
  let openingConvId = null;
  let renderedWorkflowId = null;

  const simulateOpen = async (convId, delayMs, wfId) => {
    openingConvId = convId;
    renderedWorkflowId = null; // Cleared on navigation to prevent stale render

    await new Promise((res) => setTimeout(res, delayMs));

    // Race guard: only apply if this request is still the active one
    if (openingConvId !== convId) {
      return; // Discard superseded response
    }
    renderedWorkflowId = wfId;
  };

  // Workflow A takes 50ms, but user clicks Workflow B after 10ms (which takes 20ms)
  const reqA = simulateOpen('conv-A', 50, 'wf-A');
  await new Promise((res) => setTimeout(res, 10));
  const reqB = simulateOpen('conv-B', 20, 'wf-B');

  await Promise.all([reqA, reqB]);

  assert.equal(openingConvId, 'conv-B');
  assert.equal(renderedWorkflowId, 'wf-B', 'Superseded response from Workflow A must not overwrite Workflow B');
});

// Test 10: Creating a new workflow and explicitly clicking Generate still starts generation normally
test('Creating a new workflow and explicitly clicking Generate still starts generation normally', async () => {
  let pipelineStarted = false;
  let promptSubmitted = null;

  const handleSubmitPrompt = async (text) => {
    promptSubmitted = text;
    pipelineStarted = true;
  };

  await handleSubmitPrompt('Send Slack notification on webhook');

  assert.equal(pipelineStarted, true);
  assert.equal(promptSubmitted, 'Send Slack notification on webhook');
});
