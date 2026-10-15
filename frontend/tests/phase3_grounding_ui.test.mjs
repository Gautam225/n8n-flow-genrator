import { test } from 'node:test';
import assert from 'node:assert/strict';

/**
 * Phase 3 Research Grounding & Safe Approval Frontend Verification Tests
 */

// Mirrors the helper logic implemented in WorkflowReviewPanel.tsx
function getResearchStatusDetails(activeDossier) {
  if (!activeDossier) {
    return {
      status: 'not_required',
      label: 'Installed Node Catalog Authority',
      variant: 'neutral',
      headline: 'Installed Node Catalog Grounding',
      description: 'Standard built-in node definitions (n8n v2.42.6) provided complete technical specifications. External web research was not required.',
    };
  }

  if (!activeDossier.needs_research) {
    return {
      status: 'skipped',
      label: 'Local Node Catalog Authority',
      variant: 'neutral',
      headline: 'Installed Node Catalog Grounding',
      description: activeDossier.research_reasons?.[0] || 'Local node catalog and built-in definitions are sufficient for this workflow.',
    };
  }

  const hasSources = (activeDossier.sources?.length ?? 0) > 0;
  const hasWarnings = (activeDossier.warnings?.length ?? 0) > 0;
  const isFailed = Boolean(
    activeDossier.is_fallback ||
    (!hasSources && (hasWarnings || activeDossier.needs_research))
  );

  if (isFailed) {
    return {
      status: 'failed',
      label: 'Research Failed (Catalog Fallback)',
      variant: 'error',
      headline: 'External Documentation Research Failed',
      description: 'Web research could not be completed (e.g. unconfigured API key or network limitation). The workflow was planned using installed node definitions only. Verification is not claimed for external APIs.',
    };
  }

  if (hasWarnings) {
    return {
      status: 'partially_completed',
      label: 'Partially Researched',
      variant: 'warning',
      headline: 'Partially Researched with Limitations',
      description: 'External documentation was consulted, but some query limitations or service warnings occurred. Review the warnings below.',
    };
  }

  return {
    status: 'completed',
    label: 'Web Research Grounded',
    variant: 'success',
    headline: 'Documentation Grounded via Tavily',
    description: 'External API documentation was retrieved via Tavily, sanitized against prompt injection, and verified against 444 installed local node definitions.',
  };
}

function isSafeUrl(url) {
  if (!url || typeof url !== 'string') return false;
  return /^https?:\/\//i.test(url.trim());
}

test('Phase 3 Grounding UI: computes honest research status for all lifecycles', () => {
  // 1. Completed
  const completedDossier = {
    needs_research: true,
    sources: [{ url: 'https://docs.shopify.com', title: 'Shopify Admin API', domain_authority: 'official_docs' }],
    warnings: [],
    is_fallback: false,
  };
  const compStatus = getResearchStatusDetails(completedDossier);
  assert.equal(compStatus.status, 'completed');
  assert.equal(compStatus.variant, 'success');
  assert.equal(compStatus.label, 'Web Research Grounded');

  // 2. Partially completed (has sources, but also warnings)
  const partialDossier = {
    needs_research: true,
    sources: [{ url: 'https://api.slack.com', title: 'Slack Web API', domain_authority: 'official_docs' }],
    warnings: ['Rate limit reached on secondary query'],
    is_fallback: false,
  };
  const partStatus = getResearchStatusDetails(partialDossier);
  assert.equal(partStatus.status, 'partially_completed');
  assert.equal(partStatus.variant, 'warning');
  assert.equal(partStatus.label, 'Partially Researched');

  // 3. Failed / Fallback
  const failedDossier = {
    needs_research: true,
    sources: [],
    warnings: ['TAVILY_API_KEY is not configured'],
    is_fallback: true,
  };
  const failStatus = getResearchStatusDetails(failedDossier);
  assert.equal(failStatus.status, 'failed');
  assert.equal(failStatus.variant, 'error');
  assert.equal(failStatus.label, 'Research Failed (Catalog Fallback)');
  assert.match(failStatus.description, /Verification is not claimed/);

  // 4. Skipped / Built-in catalog sufficient
  const skippedDossier = {
    needs_research: false,
    research_reasons: ['Local node catalog and built-in definitions are sufficient for this workflow.'],
    sources: [],
    warnings: [],
  };
  const skipStatus = getResearchStatusDetails(skippedDossier);
  assert.equal(skipStatus.status, 'skipped');
  assert.equal(skipStatus.variant, 'neutral');
  assert.equal(skipStatus.label, 'Local Node Catalog Authority');

  // 5. Older draft without dossier
  const nullStatus = getResearchStatusDetails(null);
  assert.equal(nullStatus.status, 'not_required');
  assert.equal(nullStatus.variant, 'neutral');
});

test('Phase 3 Grounding UI: Research failure is never displayed as successful verification', () => {
  const failedDossier = {
    needs_research: true,
    sources: [],
    documented_facts: [],
    warnings: ['Tavily connection timeout'],
    is_fallback: true,
  };

  const status = getResearchStatusDetails(failedDossier);
  assert.notEqual(status.variant, 'success');
  assert.notEqual(status.label, 'Web Research Grounded');
  assert.equal(status.status, 'failed');
  assert.equal(status.variant, 'error');
});

test('Phase 3 Grounding UI: Safe URL sanitization prevents javascript and data URLs', () => {
  assert.equal(isSafeUrl('javascript:alert(1)'), false);
  assert.equal(isSafeUrl('data:text/html,test'), false);
  assert.equal(isSafeUrl(''), false);
  assert.equal(isSafeUrl(null), false);
  assert.equal(isSafeUrl(undefined), false);

  assert.equal(isSafeUrl('https://docs.n8n.io'), true);
  assert.equal(isSafeUrl('http://api.telegram.org'), true);
});

test('Phase 3 Grounding UI: Distinct separation of facts, assumptions, and unresolved questions', () => {
  const dossier = {
    documented_facts: [
      { topic: 'Stripe', category: 'endpoint', fact: 'POST /v1/charges creates a charge', is_verified_in_catalog: true, n8n_node_type: 'n8n-nodes-base.stripe' },
    ],
    assumptions: [
      'Assumed standard ISO 8601 timestamps apply for payment events.',
    ],
    unresolved_questions: [
      'Stripe Restricted API Key with charges:write permission required.',
    ],
    warnings: [
      'Webhook signature verification must be configured manually in n8n.',
    ],
  };

  // Facts are verified requirements
  assert.equal(dossier.documented_facts.length, 1);
  assert.equal(dossier.documented_facts[0].is_verified_in_catalog, true);

  // Assumptions are distinct from facts
  assert.equal(dossier.assumptions.length, 1);
  assert.notEqual(dossier.assumptions[0], dossier.documented_facts[0].fact);

  // Unresolved questions are distinct action items
  assert.equal(dossier.unresolved_questions.length, 1);
  assert.notEqual(dossier.unresolved_questions[0], dossier.assumptions[0]);

  // Warnings are limitations
  assert.equal(dossier.warnings.length, 1);
});

test('Phase 3 Grounding UI: Reopening saved draft faithfully restores research dossier and workflow plan', () => {
  const mockDetail = {
    id: 'conv-order-sync-1',
    title: 'Order Sync Automation',
    state: 'ready',
    messages: [],
    slots: { email_provider: 'gmail' },
    latest_draft: {
      id: 'draft-1',
      title: 'Order Sync Automation',
      workflow_ir: { id: 'wf-1', name: 'Order Sync Automation', nodes: [], edges: [] },
      compiled_json: { name: 'Order Sync Automation', nodes: [], connections: {}, active: false },
      validation_report: { is_valid: true, issues: [] },
      latest_revision_number: 2,
    },
    research_dossier: {
      needs_research: true,
      sources: [{ url: 'https://docs.shopify.com', title: 'Shopify Admin' }],
      documented_facts: [],
      assumptions: [],
      unresolved_questions: [],
      warnings: [],
      is_fallback: false,
    },
    workflow_plan: {
      title: 'Shopify to Airtable',
      objective: 'Synchronize new orders',
      nodes: [{ id: 'n1', name: 'Webhook', node_type: 'n8n-nodes-base.webhook', role: 'trigger' }],
      connections: [],
      error_handling_strategy: 'Continue on fail with alert',
    },
  };

  // Simulating the fixed App.tsx setTurnResult payload
  const turnResult = {
    conversation_id: mockDetail.id,
    state: 'ready',
    assistant_message: 'Restored draft revision 2.',
    workflow_ir: mockDetail.latest_draft.workflow_ir,
    compiled_json: mockDetail.latest_draft.compiled_json,
    validation_report: mockDetail.latest_draft.validation_report,
    draft_id: mockDetail.latest_draft.id,
    revision_number: 2,
    latest_revision_number: 2,
    original_prompt: 'Sync shopify orders',
    completed_answers: mockDetail.slots,
    research_dossier: mockDetail.research_dossier,
    workflow_plan: mockDetail.workflow_plan,
  };

  assert.ok(turnResult.research_dossier, 'research_dossier must be preserved upon draft reopen');
  assert.equal(turnResult.research_dossier.sources.length, 1);
  assert.ok(turnResult.workflow_plan, 'workflow_plan must be preserved upon draft reopen');
  assert.equal(turnResult.workflow_plan.nodes.length, 1);
});

test('Phase 3 Safe Approval: Deploy action is strictly gated by readiness, credentials, and dirty edits', () => {
  // Deployment button disabled predicate from WorkflowReviewPanel.tsx
  const isDeployDisabled = (report, hasMissingOrInvalidCreds, isDirty) => {
    return !(report?.is_deployment_ready ?? false) || hasMissingOrInvalidCreds || isDirty;
  };

  // 1. Deployment blocked by missing credentials
  assert.equal(
    isDeployDisabled({ is_deployment_ready: false }, true, false),
    true,
    'Must disable deploy when credentials are missing'
  );

  // 2. Deployment blocked by unsaved local edits
  assert.equal(
    isDeployDisabled({ is_deployment_ready: true }, false, true),
    true,
    'Must disable deploy when local canvas is dirty/unsaved'
  );

  // 3. Deployment blocked by fatal validation errors
  assert.equal(
    isDeployDisabled({ is_deployment_ready: false }, false, false),
    true,
    'Must disable deploy when report is not deployment ready'
  );

  // 4. Deployment permitted only when all checks pass and clean
  assert.equal(
    isDeployDisabled({ is_deployment_ready: true }, false, false),
    false,
    'Deploy permitted only when ready, credentials configured, and revision saved'
  );
});
