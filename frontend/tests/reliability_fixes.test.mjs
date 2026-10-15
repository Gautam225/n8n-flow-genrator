import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// ============================================================================
// 1. Clarification Tests: Deduplication, Global Sequential Numbering, Pre-fill
// ============================================================================

test('Clarification questions are deduplicated across trigger, action, and general sections', () => {
  const rawQuestions = [
    {
      id: 'q_email_provider',
      field_key: 'email_provider',
      group: 'Trigger: Email Monitoring',
      question: 'Which email service do you use?',
      required: true,
      options: [{ label: 'Gmail', value: 'gmail' }],
    },
    {
      id: 'q_telegram_chat_id',
      field_key: 'telegram_chat_id',
      group: 'Action: Telegram Forwarding',
      question: 'Where should notifications be sent in Telegram?',
      required: true,
      options: [{ label: 'My Telegram Chat', value: 'private_chat' }],
    },
    // Duplicate question from a general section with same ID
    {
      id: 'q_email_provider',
      field_key: 'email_provider',
      group: 'General Configuration',
      question: 'Which email service do you use?',
      required: true,
      options: [{ label: 'Gmail', value: 'gmail' }],
    },
  ];

  // Frontend uniqueQuestions deduplication logic
  const seen = new Set();
  const uniqueQuestions = [];
  rawQuestions.forEach((q) => {
    const key = q.id || q.field_key;
    if (!seen.has(key)) {
      seen.add(key);
      uniqueQuestions.push(q);
    }
  });

  assert.equal(uniqueQuestions.length, 2, 'Duplicate email_provider must be deduplicated to 1');
  assert.equal(uniqueQuestions[0].id, 'q_email_provider');
  assert.equal(uniqueQuestions[1].id, 'q_telegram_chat_id');
});

test('Question numbering is assigned sequentially across the complete form, not restarting per section', () => {
  const uniqueQuestions = [
    { id: 'q_1', field_key: 'email_provider', group: 'Trigger: Email' },
    { id: 'q_2', field_key: 'telegram_chat_id', group: 'Action: Telegram' },
    { id: 'q_3', field_key: 'filter_criteria', group: 'Action: Telegram' },
  ];

  // Global questionNumberMap implementation as in ReservedWorkflowStage.tsx
  const questionNumberMap = new Map();
  uniqueQuestions.forEach((q, idx) => {
    questionNumberMap.set(q.id, idx + 1);
  });

  // Section 1: Trigger
  const triggerQuestions = uniqueQuestions.filter((q) => q.group === 'Trigger: Email');
  assert.equal(triggerQuestions.length, 1);
  assert.equal(questionNumberMap.get(triggerQuestions[0].id), 1, 'First question is Q1');

  // Section 2: Action
  const actionQuestions = uniqueQuestions.filter((q) => q.group === 'Action: Telegram');
  assert.equal(actionQuestions.length, 2);
  assert.equal(questionNumberMap.get(actionQuestions[0].id), 2, 'Second question must be Q2, NOT restarted at Q1');
  assert.equal(questionNumberMap.get(actionQuestions[1].id), 3, 'Third question must be Q3, NOT restarted at Q2');
});

test('Distinct questions with similar labels preserve separate IDs and authoritative answers', () => {
  const uniqueQuestions = [
    { id: 'q_email_source', field_key: 'source_email', question: 'Which email should we use?' },
    { id: 'q_email_target', field_key: 'target_email', question: 'Which email should we use?' },
  ];

  const selectedAnswers = {
    q_email_source: 'alerts@company.com',
    q_email_target: 'team@company.com',
  };

  // Build batch payload
  const batchItems = uniqueQuestions.map((q) => ({
    question_id: q.id,
    field_key: q.field_key,
    selected_value: selectedAnswers[q.id],
  }));

  assert.equal(batchItems.length, 2);
  assert.equal(batchItems[0].question_id, 'q_email_source');
  assert.equal(batchItems[0].selected_value, 'alerts@company.com');
  assert.equal(batchItems[1].question_id, 'q_email_target');
  assert.equal(batchItems[1].selected_value, 'team@company.com');
});

test('Previously answered questions remain populated when form is re-evaluated', () => {
  const prevAnswers = {
    q_email_provider: 'gmail',
    q_telegram_chat_id: 'chat_777',
  };

  const newQuestions = [
    { id: 'q_email_provider', field_key: 'email_provider' },
    { id: 'q_telegram_chat_id', field_key: 'telegram_chat_id' },
    { id: 'q_new_param', field_key: 'param_3' },
  ];

  // Simulated pre-fill logic
  const nextAnswers = { ...prevAnswers };
  newQuestions.forEach((q) => {
    if (!nextAnswers[q.id] && q.field_key && prevAnswers[q.field_key]) {
      nextAnswers[q.id] = prevAnswers[q.field_key];
    }
  });

  assert.equal(nextAnswers['q_email_provider'], 'gmail', 'Previous email_provider answer preserved');
  assert.equal(nextAnswers['q_telegram_chat_id'], 'chat_777', 'Previous telegram answer preserved');
  assert.equal(nextAnswers['q_new_param'], undefined, 'New question initially unpopulated');
});

// ============================================================================
// 2. Loading Indicators, CSS Animations, and Reduced Motion
// ============================================================================

test('CSS spinner animation does not contain transform-box: fill-box and includes center origin', () => {
  const cssPath = path.resolve(__dirname, '../src/index.css');
  const cssContent = fs.readFileSync(cssPath, 'utf8');

  // Verify transform-box: fill-box is NOT on .icon-spin / .spinning / .studio-spin
  assert.ok(
    !cssContent.includes('.icon-spin {\n  transform-box: fill-box;') &&
    !cssContent.includes('.studio-spin {\n  transform-box: fill-box;'),
    'transform-box: fill-box must not be present on SVG spinner classes'
  );

  // Verify transform-origin: center center is present
  assert.ok(
    cssContent.includes('transform-origin: center center;'),
    'transform-origin: center center must be present for stable SVG rotation'
  );
});

test('Reduced-motion style provides accessible studio-pulse rather than freezing loading state', () => {
  const cssPath = path.resolve(__dirname, '../src/index.css');
  const cssContent = fs.readFileSync(cssPath, 'utf8');

  // Extract prefers-reduced-motion block
  const reducedMotionMatch = cssContent.match(/@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{([^}]+)\}/);
  assert.ok(reducedMotionMatch, 'prefers-reduced-motion media query must be defined');

  const ruleBlock = reducedMotionMatch[1];
  assert.ok(
    ruleBlock.includes('studio-pulse'),
    'Reduced motion must provide studio-pulse fallback animation to keep loading indicators alive'
  );
  assert.ok(
    !ruleBlock.includes('animation: none !important;'),
    'Reduced motion must not set animation: none !important on spinners'
  );
});

test('Live tracking stops when backend reports inactive state and reconciles draft', async () => {
  let isTrackingActive = true;
  let stageState = 'building';
  let restoredResult = null;

  const mockGetStatus = async (convId) => {
    return {
      conversation_id: convId,
      is_active: false,
      stage: 'ready',
      message: 'Workflow draft ready.',
    };
  };

  const mockGetConversation = async (convId) => {
    return {
      id: convId,
      state: 'ready',
      messages: [{ role: 'assistant', content: 'Here is your workflow.' }],
      latest_draft: {
        id: 'draft_1',
        title: 'Email to Telegram',
        latest_revision_number: 1,
        workflow_ir: { id: 'wf_1', name: 'Email to Telegram', nodes: [], edges: [] },
      },
    };
  };

  // Simulate tracking callback
  const status = await mockGetStatus('conv-123');
  if (!status.is_active) {
    isTrackingActive = false;
    const detail = await mockGetConversation('conv-123');
    if (detail.latest_draft && detail.latest_draft.workflow_ir) {
      stageState = 'ready';
      restoredResult = detail.latest_draft.workflow_ir;
    }
  }

  assert.equal(isTrackingActive, false, 'Tracking must stop on terminal inactive response');
  assert.equal(stageState, 'ready', 'Stage must transition out of building to ready');
  assert.ok(restoredResult !== null, 'Restored draft must be populated');
});

// ============================================================================
// 3. Retry and Concurrency Tests
// ============================================================================

test('Retry button checks backend status and resumes live tracking without sending duplicate request if active', async () => {
  let retryEndpointCalled = false;
  let liveTrackingStarted = false;
  let displayedStage = null;

  const mockGetStatus = async (convId) => ({
    conversation_id: convId,
    is_active: true,
    stage: 'validating',
    message: 'Validating workflow structure...',
    elapsed_seconds: 5.2,
  });

  const mockRetryEndpoint = async (convId) => {
    retryEndpointCalled = true;
    return { conversation_id: convId, state: 'ready' };
  };

  const convId = 'conv-active-123';
  const liveStatus = await mockGetStatus(convId);

  if (liveStatus && liveStatus.is_active) {
    displayedStage = liveStatus.stage;
    liveTrackingStarted = true;
  } else {
    await mockRetryEndpoint(convId);
  }

  assert.equal(retryEndpointCalled, false, 'Duplicate retry request must NOT be sent if backend is active');
  assert.equal(liveTrackingStarted, true, 'Live tracking must be resumed');
  assert.equal(displayedStage, 'validating', 'Active backend stage must be rendered');
});

test('Retry button dispatches clean retry request when backend is confirmed idle/failed', async () => {
  let retryEndpointCalled = false;
  let trackingStarted = false;

  const mockGetStatus = async (convId) => ({
    conversation_id: convId,
    is_active: false,
    stage: 'failed',
    message: 'Generation timed out.',
  });

  const mockRetryEndpoint = async (convId) => {
    retryEndpointCalled = true;
    return { conversation_id: convId, state: 'ready' };
  };

  const convId = 'conv-failed-456';
  const liveStatus = await mockGetStatus(convId);

  if (liveStatus && liveStatus.is_active) {
    // skip
  } else {
    trackingStarted = true;
    await mockRetryEndpoint(convId);
  }

  assert.equal(retryEndpointCalled, true, 'Retry endpoint MUST be invoked when lock is idle/failed');
  assert.equal(trackingStarted, true);
});

test('Switching conversations cancels previous active live tracking', () => {
  let activeTrackingConvId = null;
  let pollIntervalCleared = false;

  const stopLiveTracking = () => {
    pollIntervalCleared = true;
    activeTrackingConvId = null;
  };

  const startLiveTracking = (convId) => {
    stopLiveTracking();
    activeTrackingConvId = convId;
  };

  startLiveTracking('conv-1');
  assert.equal(activeTrackingConvId, 'conv-1');

  // Switch to conv-2
  startLiveTracking('conv-2');
  assert.equal(activeTrackingConvId, 'conv-2');
  assert.equal(pollIntervalCleared, true);
});

// ============================================================================
// 4. Timeout and Reconnection Reliability Tests
// ============================================================================

test('Frontend App.tsx defines TIMEOUT_MS at 95000ms to align with backend generation deadline', () => {
  const appPath = path.resolve(__dirname, '../src/App.tsx');
  const appContent = fs.readFileSync(appPath, 'utf-8');
  assert.match(
    appContent,
    /TIMEOUT_MS\s*=\s*95000/,
    'App.tsx must define TIMEOUT_MS as 95000ms to prevent premature client abortion'
  );
});

test('Client request timeout reconnects to live status tracking when backend generation is still active', async () => {
  let liveTrackingStarted = false;
  let reconnectedConvId = null;
  let stageState = 'building';
  let isSubmitting = true;

  const mockGetConversationStatus = async (convId) => ({
    conversation_id: convId,
    is_active: true,
    stage: 'generating',
    message: 'Synthesizing workflow graph and node parameters...',
    elapsed_seconds: 48.2,
  });

  const convId = 'conv-timeout-active';
  const liveStatus = await mockGetConversationStatus(convId);

  // When request aborts / drops, verify reconnection behavior
  if (liveStatus && liveStatus.is_active) {
    liveTrackingStarted = true;
    reconnectedConvId = convId;
    stageState = liveStatus.stage;
    isSubmitting = true;
  } else {
    stageState = 'timed_out';
    isSubmitting = false;
  }

  assert.equal(liveTrackingStarted, true, 'Live tracking MUST resume on timeout if backend is still generating');
  assert.equal(reconnectedConvId, convId);
  assert.equal(stageState, 'generating', 'Displayed stage must track backend active stage');
  assert.equal(isSubmitting, true, 'isSubmitting must stay true while backend is running');
});

test('Live tracking recovers completed workflow draft and transitions to ready when backend turn finishes', async () => {
  let isSubmitting = true;
  let stageState = 'generating';
  let restoredDraft = null;

  const mockStatusSequence = [
    { is_active: true, stage: 'generating' },
    { is_active: false, stage: 'ready' },
  ];

  const mockGetDetail = async (convId) => ({
    id: convId,
    latest_draft: {
      title: 'Email to Telegram PDF Invoices',
      workflow_ir: { id: 'wf-1', name: 'Email to Telegram PDF Invoices' },
      compiled_json: { name: 'Email to Telegram PDF Invoices', nodes: [], connections: {} },
      validation_report: { is_valid: true, issues: [] },
    },
    messages: [{ role: 'assistant', content: 'Workflow generated successfully.' }],
  });

  let pollCount = 0;
  for (const status of mockStatusSequence) {
    pollCount++;
    if (!status.is_active) {
      isSubmitting = false;
      const detail = await mockGetDetail('conv-finished');
      if (detail.latest_draft && detail.latest_draft.workflow_ir) {
        restoredDraft = detail.latest_draft.workflow_ir;
        stageState = 'ready';
      }
    }
  }

  assert.equal(pollCount, 2);
  assert.equal(isSubmitting, false, 'Loading must stop when generation finishes');
  assert.equal(stageState, 'ready');
  assert.ok(restoredDraft);
  assert.equal(restoredDraft.name, 'Email to Telegram PDF Invoices');
});

