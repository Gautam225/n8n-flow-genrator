/**
 * Conversation & Workflow Orchestrator API client for Phase 4B / 5 / 6.
 * Incorporates authenticated session headers and user isolation.
 */

export interface ClarificationOption {
  label: string;
  value: string;
  description?: string;
}

export interface ClarificationQuestion {
  id: string;
  question: string;
  field_key: string;
  group?: string;
  step_number?: number;
  input_type?: string;
  allow_other?: boolean;
  required?: boolean;
  is_required?: boolean;
  default_value?: string;
  options?: ClarificationOption[];
  help_text?: string;
  placeholder?: string;
  examples?: string[];
  validation_rules?: Record<string, any>;
  depends_on?: Record<string, any>;
  current_value?: string;
  error_message?: string;
}

export interface ClarificationAnswerItem {
  question_id: string;
  field_key: string;
  selected_value?: string;
  custom_text?: string;
}

export interface ClarificationPlan {
  has_ambiguities: boolean;
  questions: ClarificationQuestion[];
  current_question_id?: string;
  outstanding_questions?: string[];
  completed_answers?: Record<string, any>;
  field_errors?: Record<string, string>;
}

export interface ResearchSourceItem {
  url: string;
  title: string;
  domain_authority: 'official_docs' | 'community' | 'generic_web';
  published_date?: string | null;
  extracted_at?: string;
  snippet?: string;
  version_hint?: string | null;
  relevance_score: number;
}

export interface ResearchFindingItem {
  topic: string;
  category: string;
  fact: string;
  source_url?: string | null;
  is_verified_in_catalog: boolean;
  n8n_node_type?: string | null;
}

export interface StructuredResearchDossier {
  user_query: string;
  needs_research: boolean;
  research_reasons: string[];
  target_services: string[];
  queries_executed: string[];
  sources: ResearchSourceItem[];
  documented_facts: ResearchFindingItem[];
  assumptions: string[];
  unresolved_questions: string[];
  node_compatibility: Record<string, any>;
  usage?: {
    queries_count: number;
    pages_extracted: number;
    total_tokens?: number;
    duration_ms: number;
    cache_hits: number;
  };
  warnings: string[];
  is_fallback?: boolean;
}

export interface PlannedNodeItem {
  id: string;
  name: string;
  node_type: string;
  role: string;
  operation?: string | null;
  credential_type?: string | null;
  description?: string;
  parameters?: Record<string, any>;
  execution_policy?: Record<string, any>;
}

export interface PlannedEdgeItem {
  source_id: string;
  target_id: string;
  source_output_index?: number;
  target_input_index?: number;
  connection_type?: string;
  condition_desc?: string | null;
}

export interface WorkflowPlanItem {
  title: string;
  objective: string;
  target_services: string[];
  nodes: PlannedNodeItem[];
  connections: PlannedEdgeItem[];
  branch_conditions?: Array<Record<string, any>>;
  data_transformations?: Array<Record<string, any>>;
  state_tracking?: Record<string, any> | null;
  error_handling_strategy: string;
  expected_outputs: string[];
  research_dossier?: StructuredResearchDossier | null;
}

export interface OrchestratorTurnResult {
  conversation_id: string;
  state: 'clarifying' | 'planning' | 'generating' | 'validating' | 'ready' | 'failed' | 'researching';
  assistant_message: string;
  clarification?: ClarificationPlan | null;
  workflow_ir?: Record<string, any> | null;
  compiled_json?: Record<string, any> | null;
  validation_report?: {
    is_valid: boolean;
    issues: Array<{
      severity: string;
      rule_code: string;
      node_id?: string;
      message: string;
      category?: string;
      suggested_fix?: string;
    }>;
  } | null;
  readiness_report?: any;
  draft_id?: string | null;
  revision_number?: number | null;
  latest_revision_number?: number | null;
  original_prompt?: string;
  intent_summary?: string;
  current_question_id?: string;
  outstanding_questions?: string[];
  completed_answers?: Record<string, any>;
  field_errors?: Record<string, string>;
  research_dossier?: StructuredResearchDossier | null;
  workflow_plan?: WorkflowPlanItem | null;
}

export interface ConversationSummary {
  id: string;
  title: string;
  state: string;
  created_at: string;
  updated_at: string;
  message_count: number;
  latest_draft_id?: string | null;
}

export interface MessageItem {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  created_at: string;
  metadata_json?: Record<string, any> | null;
}

export interface ConversationDetail {
  id: string;
  title: string;
  state: string;
  created_at: string;
  updated_at: string;
  messages: MessageItem[];
  slots: Record<string, any>;
  latest_draft?: Record<string, any> | null;
  original_prompt?: string;
  intent?: Record<string, any>;
  clarification?: ClarificationPlan | null;
  current_question_id?: string;
  outstanding_questions?: string[];
  research_dossier?: StructuredResearchDossier | null;
  workflow_plan?: WorkflowPlanItem | null;
}


/**
 * Builds request headers including user isolation and API credentials if present.
 */
export function getAuthHeaders(additionalHeaders: Record<string, string> = {}): Record<string, string> {
  const headers: Record<string, string> = {
    Accept: 'application/json',
    ...additionalHeaders,
  };
  const userId = localStorage.getItem('studio_user_id');
  if (userId) {
    headers['X-User-Id'] = userId;
  }
  const apiKey = localStorage.getItem('studio_api_key');
  if (apiKey) {
    headers['X-API-Key'] = apiKey;
  }
  return headers;
}

export async function createConversation(
  title?: string,
  initialPrompt?: string,
  signal?: AbortSignal,
  id?: string
): Promise<{
  conversation_id: string;
  title: string;
  state: string;
  created_at: string;
  turn_result?: OrchestratorTurnResult | null;
}> {
  const response = await fetch('/api/v1/conversations', {
    method: 'POST',
    headers: getAuthHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({
      id: id || undefined,
      title: title || undefined,
      initial_prompt: initialPrompt || undefined,
    }),
    signal,
  });

  if (!response.ok) {
    const errorBody = await response.json().catch(() => ({}));
    throw new Error(errorBody.detail || `HTTP Error ${response.status}`);
  }

  return response.json();
}

export async function listConversations(limit = 50, offset = 0): Promise<ConversationSummary[]> {
  const response = await fetch(`/api/v1/conversations?limit=${limit}&offset=${offset}`, {
    headers: getAuthHeaders(),
  });

  if (!response.ok) {
    const errorBody = await response.json().catch(() => ({}));
    throw new Error(errorBody.detail || `HTTP Error ${response.status}`);
  }

  return response.json();
}

export async function getConversation(conversationId: string): Promise<ConversationDetail> {
  const response = await fetch(`/api/v1/conversations/${conversationId}`, {
    headers: getAuthHeaders(),
  });

  if (!response.ok) {
    const errorBody = await response.json().catch(() => ({}));
    throw new Error(errorBody.detail || `HTTP Error ${response.status}`);
  }

  return response.json();
}

export async function sendMessage(
  conversationId: string,
  content: string,
  selectedOptions?: Record<string, string>,
  signal?: AbortSignal,
  clarificationAnswers?: ClarificationAnswerItem[]
): Promise<OrchestratorTurnResult> {
  const response = await fetch(`/api/v1/conversations/${conversationId}/messages`, {
    method: 'POST',
    headers: getAuthHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({
      content,
      selected_options: selectedOptions || undefined,
      clarification_answers: clarificationAnswers || undefined,
    }),
    signal,
  });

  if (!response.ok) {
    const errorBody = await response.json().catch(() => ({}));
    throw new Error(errorBody.detail || `HTTP Error ${response.status}`);
  }

  return response.json();
}

export async function retryConversation(
  conversationId: string,
  signal?: AbortSignal
): Promise<OrchestratorTurnResult> {
  const response = await fetch(`/api/v1/conversations/${conversationId}/retry`, {
    method: 'POST',
    headers: getAuthHeaders({ 'Content-Type': 'application/json' }),
    signal,
  });

  if (!response.ok) {
    const errorBody = await response.json().catch(() => ({}));
    throw new Error(errorBody.detail || `HTTP Error ${response.status}`);
  }

  return response.json();
}

export async function renameConversation(conversationId: string, title: string): Promise<ConversationSummary> {
  const response = await fetch(`/api/v1/conversations/${conversationId}`, {
    method: 'PATCH',
    headers: getAuthHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ title }),
  });

  if (!response.ok) {
    const errorBody = await response.json().catch(() => ({}));
    throw new Error(errorBody.detail || `HTTP Error ${response.status}`);
  }

  return response.json();
}

export async function deleteConversation(conversationId: string): Promise<void> {
  const response = await fetch(`/api/v1/conversations/${conversationId}`, {
    method: 'DELETE',
    headers: getAuthHeaders(),
  });

  if (!response.ok && response.status !== 204) {
    const errorBody = await response.json().catch(() => ({}));
    throw new Error(errorBody.detail || `HTTP Error ${response.status}`);
  }
}

export interface ValidationReportResult {
  is_valid: boolean;
  issues: Array<{
    severity: string;
    rule_code: string;
    node_id?: string;
    message: string;
  }>;
}

export interface ValidateDraftResult {
  is_valid: boolean;
  validation_report: ValidationReportResult;
  compiled_json?: Record<string, any> | null;
}

export interface SavedRevisionResult {
  draft_id: string;
  revision_id: string;
  revision_number: number;
  title: string;
  status: string;
  is_valid: boolean;
  validation_report: ValidationReportResult;
  compiled_json?: Record<string, any> | null;
  created_at: string;
}

export interface RevisionSummary {
  id: string;
  revision_number: number;
  created_at: string;
  is_valid: boolean;
  node_count: number;
  edge_count: number;
}

export interface RevisionDetail {
  id: string;
  draft_id: string;
  revision_number: number;
  workflow_ir: Record<string, any>;
  compiled_json?: Record<string, any> | null;
  validation_report?: ValidationReportResult | null;
  created_at: string;
}

export interface NodeSchemaDefinition {
  name: string;
  canonical_name: string;
  display_name: string;
  description: string;
  default_version: number;
  supported_versions: number[];
  credentials?: Array<{
    name: string;
    required: boolean;
    display_options?: any;
  }>;
  expected_credentials?: Array<{
    name: string;
    required: boolean;
    display_options?: any;
  }>;
  properties: Array<{
    name: string;
    display_name: string;
    type: string;
    default?: any;
    required: boolean;
    description?: string;
    options?: Array<{ name: string; value: any; description?: string }>;
  }>;
}

export async function validateWorkflowDraft(
  conversationId: string,
  workflowIr: Record<string, any>
): Promise<ValidateDraftResult> {
  const response = await fetch(`/api/v1/conversations/${conversationId}/draft/validate`, {
    method: 'POST',
    headers: getAuthHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ workflow_ir: workflowIr }),
  });

  if (!response.ok) {
    const errorBody = await response.json().catch(() => ({}));
    throw new Error(errorBody.detail || `HTTP Error ${response.status}`);
  }

  return response.json();
}

export async function saveDraftRevision(
  conversationId: string,
  workflowIr: Record<string, any>,
  expectedRevisionNumber?: number,
  title?: string
): Promise<SavedRevisionResult> {
  const response = await fetch(`/api/v1/conversations/${conversationId}/draft/revisions`, {
    method: 'POST',
    headers: getAuthHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({
      workflow_ir: workflowIr,
      expected_revision_number: expectedRevisionNumber,
      title: title || undefined,
    }),
  });

  if (!response.ok) {
    const errorBody = await response.json().catch(() => ({}));
    const err = new Error(errorBody.detail || `HTTP Error ${response.status}`);
    (err as any).status = response.status;
    throw err;
  }

  return response.json();
}

export async function listDraftRevisions(conversationId: string): Promise<RevisionSummary[]> {
  const response = await fetch(`/api/v1/conversations/${conversationId}/draft/revisions`, {
    headers: getAuthHeaders(),
  });

  if (!response.ok) {
    const errorBody = await response.json().catch(() => ({}));
    throw new Error(errorBody.detail || `HTTP Error ${response.status}`);
  }

  return response.json();
}

export async function getDraftRevision(
  conversationId: string,
  revisionIdentifier: string | number
): Promise<RevisionDetail> {
  const response = await fetch(`/api/v1/conversations/${conversationId}/draft/revisions/${revisionIdentifier}`, {
    headers: getAuthHeaders(),
  });

  if (!response.ok) {
    const errorBody = await response.json().catch(() => ({}));
    throw new Error(errorBody.detail || `HTTP Error ${response.status}`);
  }

  return response.json();
}

export async function getNodeDefinition(nodeType: string): Promise<NodeSchemaDefinition> {
  const response = await fetch(`/api/v1/conversations/nodes/definition/${encodeURIComponent(nodeType)}`, {
    headers: getAuthHeaders(),
  });

  if (!response.ok) {
    const errorBody = await response.json().catch(() => ({}));
    throw new Error(errorBody.detail || `HTTP Error ${response.status}`);
  }

  return response.json();
}

// --- Phase 5C: Workflow Review, Readiness & Safe Test Planning ---

export interface ReadinessCheckItem {
  category: 'topology' | 'parameters' | 'credentials' | 'node_support' | 'execution_safety';
  status: 'pass' | 'warning' | 'fail' | 'info';
  title: string;
  detail: string;
  node_id?: string;
  node_name?: string;
  actionable_recommendation?: string;
}

export interface CredentialReadinessItem {
  node_id: string;
  node_name: string;
  credential_type: string;
  is_required: boolean;
  configured_reference?: string | null;
  verification_state:
  | 'missing'
  | 'referenced'
  | 'unverified_reference'
  | 'configured'
  | 'verified'
  | 'invalid'
  | 'insecure_literal'
  | 'not_required';
  guidance: string;
}

export interface SafeTestPlanStep {
  step_number: number;
  node_id: string;
  node_name: string;
  node_type: string;
  execution_tier: 'local_static' | 'requires_n8n' | 'requires_external_service';
  testable_locally: boolean;
  prerequisites: string[];
  side_effect_risk: 'none' | 'read_only' | 'external_mutation';
}

export interface SafeTestPlan {
  can_run_local_dry_run: boolean;
  steps: SafeTestPlanStep[];
  local_checks: string[];
  instance_dependent_checks: string[];
}

export interface WorkflowReadinessReport {
  overall_status: 'ready' | 'needs_attention' | 'blocked';
  is_deployable_to_n8n: boolean;
  is_structure_valid?: boolean;
  is_configuration_complete?: boolean;
  are_credentials_configured?: boolean;
  is_deployment_ready?: boolean;
  is_deployed?: boolean;
  unresolved_configuration?: string[];
  summary: string;
  checks: ReadinessCheckItem[];
  credentials: CredentialReadinessItem[];
  test_plan: SafeTestPlan;
  validation_report: {
    is_valid: boolean;
    issues: Array<{
      severity: string;
      rule_code: string;
      node_id?: string;
      message: string;
      suggested_fix?: string;
      property_path?: string;
    }>;
  };
}

export interface DeployWorkflowResult {
  success: boolean;
  workflow_id: string;
  workflow_name: string;
  workflow_url?: string | null;
  is_active: boolean;
  revision_number: number;
  message: string;
}

export async function deployWorkflowDraft(
  conversationId: string,
  expectedRevisionNumber?: number,
  idempotencyToken?: string
): Promise<DeployWorkflowResult> {
  const response = await fetch(`/api/v1/conversations/${conversationId}/draft/deploy`, {
    method: 'POST',
    headers: getAuthHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({
      expected_revision_number: expectedRevisionNumber,
      idempotency_token: idempotencyToken,
    }),
  });

  if (!response.ok) {
    const errorBody = await response.json().catch(() => ({}));
    const err = new Error(errorBody.detail || `HTTP Error ${response.status}`);
    (err as any).status = response.status;
    throw err;
  }

  return response.json();
}

export interface SimulationNodeResult {
  node_id: string;
  node_name: string;
  status: string;
  summary: string;
  sample_output_keys: string[];
}

export interface SafeSimulationResult {
  success: boolean;
  execution_type: string;
  disclaimer: string;
  total_nodes: number;
  passed_nodes: number;
  node_results: SimulationNodeResult[];
  completed_at: string;
}

export async function getWorkflowReadiness(
  conversationId: string,
  workflowIr?: Record<string, any>
): Promise<WorkflowReadinessReport> {
  const response = await fetch(`/api/v1/conversations/${conversationId}/draft/readiness`, {
    method: 'POST',
    headers: getAuthHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ workflow_ir: workflowIr }),
  });

  if (!response.ok) {
    const errorBody = await response.json().catch(() => ({}));
    throw new Error(errorBody.detail || `HTTP Error ${response.status}`);
  }

  return response.json();
}

export async function simulateWorkflowDryRun(
  conversationId: string,
  workflowIr?: Record<string, any>
): Promise<SafeSimulationResult> {
  const response = await fetch(`/api/v1/conversations/${conversationId}/draft/simulate`, {
    method: 'POST',
    headers: getAuthHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ workflow_ir: workflowIr }),
  });

  if (!response.ok) {
    const errorBody = await response.json().catch(() => ({}));
    throw new Error(errorBody.detail || `HTTP Error ${response.status}`);
  }

  return response.json();
}

export interface LLMStatusData {
  primary_provider: string;
  primary_model: string;
  fallback_models: string[];
  is_primary_configured: boolean;
  healthy_keys_count: number;
  total_keys_count: number;
  fallback_provider?: string | null;
  fallback_model?: string | null;
  is_fallback_configured: boolean;
  status_summary: string;
}

export interface LLMTestData {
  status: 'connected' | 'model_unavailable' | 'rate_limited' | 'unauthorized' | 'insufficient_credits' | 'timeout' | 'error';
  provider: string;
  model: string;
  latency_sec: number;
  message: string;
  supports_structured_json: boolean;
}

export async function getLLMStatus(): Promise<LLMStatusData> {
  const response = await fetch('/api/v1/integrations/llm/status', {
    headers: getAuthHeaders(),
  });
  if (!response.ok) {
    const errorBody = await response.json().catch(() => ({}));
    throw new Error(errorBody.detail || `HTTP Error ${response.status}`);
  }
  return response.json();
}

export async function testLLMConnection(): Promise<LLMTestData> {
  const response = await fetch('/api/v1/integrations/llm/test', {
    method: 'POST',
    headers: getAuthHeaders({ 'Content-Type': 'application/json' }),
  });
  if (!response.ok) {
    const errorBody = await response.json().catch(() => ({}));
    throw new Error(errorBody.detail || `HTTP Error ${response.status}`);
  }
  return response.json();
}

export interface NodeCatalogItem {
  name: string;
  canonical_name: string;
  display_name: string;
  description: string;
  group: string[];
  is_trigger: boolean;
  default_version: number;
  supported_versions: number[];
  inputs: any[];
  outputs: any[];
  credentials: Array<{ name: string; required: boolean }>;
  operations: string[];
  resources: string[];
}

export interface NodeDefinitionDetail extends NodeCatalogItem {
  properties: Array<{
    name: string;
    display_name: string;
    type: string;
    default?: any;
    required: boolean;
    description?: string;
    options?: Array<{ name: string; value: any; description?: string }>;
    display_options?: Record<string, any>;
  }>;
}

export async function searchNodes(
  query: string = '',
  category?: string,
  isTrigger?: boolean,
  limit: number = 60
): Promise<NodeCatalogItem[]> {
  const params = new URLSearchParams();
  if (query) params.append('q', query);
  if (category && category !== 'all') params.append('category', category);
  if (isTrigger !== undefined) params.append('is_trigger', String(isTrigger));
  if (limit) params.append('limit', String(limit));

  const response = await fetch(`/api/v1/conversations/nodes/search?${params.toString()}`, {
    headers: getAuthHeaders(),
  });
  if (!response.ok) {
    const errorBody = await response.json().catch(() => ({}));
    throw new Error(errorBody.detail || `HTTP Error ${response.status}`);
  }
  return response.json();
}


export interface ConversationStatusResponse {
  conversation_id: string;
  is_active: boolean;
  stage: string;
  message?: string | null;
  elapsed_seconds?: number | null;
  generation_id?: string | null;
  timings?: Record<string, number> | null;
  slots?: Record<string, any> | null;
}

export function createGenerationWebSocket(
  conversationId: string,
  onEvent: (event: any) => void
): () => void {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const url = `${protocol}//${window.location.host}/api/v1/conversations/${conversationId}/progress/ws`;
  let ws: WebSocket | null = null;
  let pingInterval: any = null;

  try {
    ws = new WebSocket(url);
    ws.onmessage = (event) => {
      try {
        if (event.data === 'pong') return;
        const data = JSON.parse(event.data);
        onEvent(data);
      } catch {
        // ignore parse error
      }
    };
    ws.onopen = () => {
      pingInterval = setInterval(() => {
        if (ws && ws.readyState === WebSocket.OPEN) {
          ws.send('ping');
        }
      }, 10000);
    };
    ws.onerror = () => {
      // Fallback polling handles this seamlessly
    };
    ws.onclose = () => {
      if (pingInterval) clearInterval(pingInterval);
    };
  } catch {
    // Fallback polling handles this seamlessly
  }

  return () => {
    if (pingInterval) clearInterval(pingInterval);
    if (ws) {
      try {
        ws.close();
      } catch {
        // ignore
      }
      ws = null;
    }
  };
}

export async function getConversationStatus(
  conversationId: string,
  signal?: AbortSignal
): Promise<ConversationStatusResponse> {
  const response = await fetch(`/api/v1/conversations/${conversationId}/status`, {
    headers: getAuthHeaders(),
    signal,
  });
  if (!response.ok) {
    const errorBody = await response.json().catch(() => ({}));
    throw new Error(errorBody.detail || `HTTP Error ${response.status}`);
  }
  return response.json();
}

export interface N8nCredentialSummary {
  id: string;
  name: string;
  type: string;
  created_at?: string;
  updated_at?: string;
}

export async function getN8nCredentials(): Promise<N8nCredentialSummary[]> {
  try {
    const response = await fetch('/api/v1/integrations/n8n/credentials', {
      headers: getAuthHeaders(),
    });
    if (!response.ok) return [];
    return response.json();
  } catch {
    return [];
  }
}


