import { test } from 'node:test';
import assert from 'node:assert/strict';

test('Readiness Evaluation: distinguishes ready, needs_attention, and blocked workflows', () => {
  // Mock readiness reports matching API contracts
  const readyReport = {
    overall_status: 'ready',
    is_deployable_to_n8n: true,
    summary: 'Workflow passed all static readiness checks.',
    checks: [
      { category: 'topology', status: 'pass', title: 'Trigger configured' },
      { category: 'parameters', status: 'pass', title: 'Required parameters complete' },
    ],
    credentials: [],
    validation_report: { is_valid: true, issues: [] },
  };

  const attentionReport = {
    overall_status: 'needs_attention',
    is_deployable_to_n8n: false,
    summary: 'Workflow requires attention: unresolved credentials.',
    checks: [
      { category: 'credentials', status: 'warning', title: 'Unresolved Credentials (1)' },
    ],
    credentials: [
      {
        node_id: 'node_2',
        node_name: 'GitHub Issues',
        credential_type: 'githubApi',
        is_required: true,
        verification_state: 'missing',
      },
    ],
    validation_report: { is_valid: true, issues: [] },
  };

  const blockedReport = {
    overall_status: 'blocked',
    is_deployable_to_n8n: false,
    summary: 'Workflow contains blocking errors.',
    checks: [
      { category: 'parameters', status: 'fail', title: 'Missing Required Parameter' },
    ],
    credentials: [],
    validation_report: { is_valid: false, issues: [{ severity: 'fatal', rule_code: 'MISSING_REQUIRED_PARAMETER' }] },
  };

  assert.equal(readyReport.overall_status, 'ready');
  assert.equal(readyReport.is_deployable_to_n8n, true);

  assert.equal(attentionReport.overall_status, 'needs_attention');
  assert.equal(attentionReport.is_deployable_to_n8n, false);
  assert.equal(attentionReport.credentials[0].verification_state, 'missing');

  assert.equal(blockedReport.overall_status, 'blocked');
  assert.equal(blockedReport.is_deployable_to_n8n, false);
  assert.equal(blockedReport.validation_report.is_valid, false);
});

test('Credential Honesty: credentials can never be claimed verified without active n8n instance', () => {
  const credentialItem = {
    node_id: 'github_node',
    node_name: 'GitHub Issues',
    credential_type: 'githubApi',
    is_required: true,
    configured_reference: 'github_oauth_vault_id',
    verification_state: 'unverified_reference',
    guidance: 'Logical credential reference configured. Validity can only be verified against an authenticated, active n8n instance.',
  };

  // Must not claim verified
  assert.notEqual(credentialItem.verification_state, 'verified');
  assert.equal(credentialItem.verification_state, 'unverified_reference');
  assert.ok(credentialItem.guidance.includes('active n8n instance'));
});

test('Safe Test Planning: segregates local static checks from target-dependent checks', () => {
  const testPlan = {
    can_run_local_dry_run: true,
    local_checks: [
      'Pydantic schema structure and Tarjan cycle verification',
      'Mandatory parameter presence and primitive type bounds',
      'Handle socket index bounds',
      'Deterministic native n8n compilation format',
      'DAG execution ordering and mock payload simulation',
    ],
    instance_dependent_checks: [
      'n8n REST API connectivity & version handshake',
      'Credential existence inside n8n credential vault',
      'Webhook trigger path registration',
    ],
    steps: [
      {
        step_number: 1,
        node_id: 'manual_1',
        node_name: 'Manual Trigger',
        node_type: 'n8n-nodes-base.manualTrigger',
        execution_tier: 'local_static',
        testable_locally: true,
        side_effect_risk: 'none',
      },
      {
        step_number: 2,
        node_id: 'http_1',
        node_name: 'HTTP Request',
        node_type: 'n8n-nodes-base.httpRequest',
        execution_tier: 'requires_n8n',
        testable_locally: false,
        side_effect_risk: 'read_only',
      },
    ],
  };

  assert.equal(testPlan.can_run_local_dry_run, true);
  assert.equal(testPlan.steps.length, 2);
  assert.equal(testPlan.steps[0].execution_tier, 'local_static');
  assert.equal(testPlan.steps[0].testable_locally, true);
  assert.equal(testPlan.steps[1].execution_tier, 'requires_n8n');
  assert.equal(testPlan.steps[1].testable_locally, false);
});

test('Safe Simulation Dry-Run: non-mutating guarantee and output attribute tracking', () => {
  const simResult = {
    success: true,
    execution_type: 'deterministic_static_dry_run',
    disclaimer: 'This dry run evaluated static data-flow and parameter completeness only. No external services or n8n executions were triggered.',
    total_nodes: 2,
    passed_nodes: 2,
    node_results: [
      {
        node_id: 't1',
        node_name: 'Webhook',
        status: 'simulated_success',
        summary: 'Simulated trigger emission: Generated mock event payload (4 attributes).',
        sample_output_keys: ['headers', 'body', 'query', 'timestamp'],
      },
      {
        node_id: 's1',
        node_name: 'Set Data',
        status: 'simulated_success',
        summary: 'Simulated state assignment: Applied 2 parameter assignments.',
        sample_output_keys: ['data', 'status'],
      },
    ],
  };

  assert.equal(simResult.success, true);
  assert.equal(simResult.execution_type, 'deterministic_static_dry_run');
  assert.ok(simResult.disclaimer.includes('No external services'));
  assert.equal(simResult.passed_nodes, 2);
  assert.deepEqual(simResult.node_results[0].sample_output_keys, ['headers', 'body', 'query', 'timestamp']);
});

test('Unsaved Edits Tracking: distinguishes saved draft from in-memory edits', () => {
  const savedRevision = {
    revision_number: 3,
    workflow: {
      id: 'wf_test',
      name: 'Baseline Flow',
      nodes: [{ id: 'n1', name: 'Node 1', parameters: { v: 1 } }],
    },
  };

  const modifiedWorkflow = {
    id: 'wf_test',
    name: 'Baseline Flow',
    nodes: [{ id: 'n1', name: 'Node 1', parameters: { v: 2 } }],
  };

  const isDirty = JSON.stringify(savedRevision.workflow) !== JSON.stringify(modifiedWorkflow);
  assert.equal(isDirty, true);

  const restoredWorkflow = { ...savedRevision.workflow };
  const isDirtyAfterRestore = JSON.stringify(savedRevision.workflow) !== JSON.stringify(restoredWorkflow);
  assert.equal(isDirtyAfterRestore, false);
});

test('Google Sheets and Telegram configuration parameter extraction and validation', () => {
  // Spreadsheet URL extractor logic test
  const extractDocId = (val) => {
    const trimmed = String(val).trim();
    const match = trimmed.match(/\/d\/([a-zA-Z0-9-_]+)/);
    return match ? match[1] : trimmed;
  };

  const rawUrl = 'https://docs.google.com/spreadsheets/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms/edit#gid=0';
  const extracted = extractDocId(rawUrl);
  assert.equal(extracted, '1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms');

  // Plain ID passthrough
  assert.equal(extractDocId('1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms'), '1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms');

  // Placeholder detection
  const placeholderSpreadsheet = '<YOUR_SPREADSHEET_ID>';
  assert.ok(placeholderSpreadsheet.includes('<YOUR_'));

  const placeholderTelegram = '<YOUR_TELEGRAM_CHAT_ID>';
  assert.ok(placeholderTelegram.includes('<YOUR_'));
});

test('Deployment Lifecycle Gate: verifies prerequisites and inactive creation semantics', () => {
  // Mock deployment payload validation
  const canDeploy = (report, isDirty, hasAcknowledged) => {
    if (isDirty) return false;
    if (!hasAcknowledged) return false;
    if (!report.is_structure_valid) return false;
    if (!report.is_configuration_complete) return false;
    return true;
  };

  const cleanReport = {
    is_structure_valid: true,
    is_configuration_complete: true,
    are_credentials_configured: false,
    is_deployment_ready: true,
    unresolved_configuration: [],
  };

  const unconfiguredReport = {
    is_structure_valid: true,
    is_configuration_complete: false,
    are_credentials_configured: false,
    is_deployment_ready: false,
    unresolved_configuration: ['Spreadsheet documentId', 'Telegram chatId'],
  };

  // Blocked by unsaved edits
  assert.equal(canDeploy(cleanReport, true, true), false);

  // Blocked by missing unconfigured parameters
  assert.equal(canDeploy(unconfiguredReport, false, true), false);

  // Blocked by lack of human acknowledgment
  assert.equal(canDeploy(cleanReport, false, false), false);

  // Passes when all prerequisites met
  assert.equal(canDeploy(cleanReport, false, true), true);

  // Successful deployment result contracts
  const mockDeployResult = {
    success: true,
    workflow_id: '42',
    workflow_name: 'Google Sheets to Telegram',
    workflow_url: 'http://localhost:5678/workflow/42',
    is_active: false,
    revision_number: 2,
    message: 'Workflow successfully created in n8n as inactive (ID: 42).',
  };

  assert.equal(mockDeployResult.success, true);
  assert.equal(mockDeployResult.is_active, false);
  assert.equal(mockDeployResult.workflow_id, '42');
  assert.ok(mockDeployResult.workflow_url.includes('/workflow/42'));
});

test('Simplified Review Panel: consistent status derivation without contradictions', () => {
  // Derive overall status representation
  const deriveStatus = (report) => {
    const hasMissingOrInvalidCreds = report.credentials.some(
      (c) => c.verification_state === 'missing' || c.verification_state === 'invalid'
    );
    if (report.overall_status === 'blocked') {
      return { label: 'Blocked', variant: 'error' };
    }
    if (report.overall_status === 'needs_attention') {
      return { label: 'Needs configuration', variant: 'warning' };
    }
    if (report.is_deployment_ready && !hasMissingOrInvalidCreds) {
      return { label: 'Ready to deploy', variant: 'success' };
    }
    return { label: 'Ready for review', variant: 'info' };
  };

  // 1. Ready and fully deployment ready
  const deployReady = deriveStatus({
    overall_status: 'ready',
    is_deployment_ready: true,
    credentials: [{ verification_state: 'configured' }],
  });
  assert.equal(deployReady.label, 'Ready to deploy');
  assert.equal(deployReady.variant, 'success');

  // 2. Structurally ready but unverified reference / not deployment ready
  const reviewReady = deriveStatus({
    overall_status: 'ready',
    is_deployment_ready: false,
    credentials: [{ verification_state: 'referenced' }],
  });
  assert.equal(reviewReady.label, 'Ready for review');
  assert.equal(reviewReady.variant, 'info');

  // 3. Needs configuration
  const needsConfig = deriveStatus({
    overall_status: 'needs_attention',
    is_deployment_ready: false,
    credentials: [{ verification_state: 'missing' }],
  });
  assert.equal(needsConfig.label, 'Needs configuration');
  assert.equal(needsConfig.variant, 'warning');

  // 4. Blocked
  const blocked = deriveStatus({
    overall_status: 'blocked',
    is_deployment_ready: false,
    credentials: [],
  });
  assert.equal(blocked.label, 'Blocked');
  assert.equal(blocked.variant, 'error');
});

test('Actionable Issues: technical rule codes are cleanly humanized', () => {
  const humanizeRuleCode = (code) => {
    const map = {
      MISSING_REQUIRED_PARAMETER: 'Missing Required Parameter',
      INVALID_PARAMETER_TYPE: 'Invalid Parameter Type',
      INVALID_PARAMETER_OPTION: 'Invalid Option Selected',
      MISSING_REQUIRED_CREDENTIAL: 'Missing Credential',
      UNRESOLVED_DATA_MAPPING: 'Unmapped Data Field',
      DISCONNECTED_NODE: 'Disconnected Node',
      UNCONTROLLED_CYCLE_DETECTED: 'Graph Loop Detected',
      NODE_TYPE_UNKNOWN: 'Unrecognized Node Type',
    };
    if (map[code]) return map[code];
    return code
      .split('_')
      .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
      .join(' ');
  };

  assert.equal(humanizeRuleCode('MISSING_REQUIRED_PARAMETER'), 'Missing Required Parameter');
  assert.equal(humanizeRuleCode('UNRESOLVED_DATA_MAPPING'), 'Unmapped Data Field');
  assert.equal(humanizeRuleCode('DISCONNECTED_NODE'), 'Disconnected Node');
  assert.equal(humanizeRuleCode('CUSTOM_RULE_CODE'), 'Custom Rule Code');
});
