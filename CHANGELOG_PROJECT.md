# Project Change Log

## .gitignore
- 2026-10-12: Added Git ignore rules excluding .env files, local SQLite databases, caches, and node_modules.
- 2026-10-12: Added exclusion for root /data/ directory for local SQLite database while preserving backend/app/data/.

## .env.example
- 2026-10-12: Updated template environment file with placeholders for 4 OpenRouter keys, Groq fallback key, and timeout/retry settings.
- 2026-10-12: Updated recommended DATABASE_URL to sqlite+aiosqlite:///./data/workflow_ai.db.
- 2026-10-12: Updated DATABASE_URL example to PostgreSQL asyncpg driver per architectural standard.
- 2026-10-12: Updated N8N_API_KEY placeholder to empty string and documented safe setup instructions.
- 2026-10-12: Updated DATABASE_URL database name to n8n_workflow_ai.
- 2026-10-13: Updated default OPENROUTER_MODEL to nvidia/nemotron-3-super-120b-a12b:free and fallback models to verified active OpenRouter free models.
- 2026-10-15: Added Tavily Web Research configuration section with placeholders for TAVILY_API_KEY, TAVILY_BASE_URL, search depth, timeout, retries, and cache TTL settings.

## backend/requirements.txt
- 2026-10-12: Added minimal backend dependencies (pydantic, pydantic-settings, httpx, pytest, pytest-asyncio).
- 2026-10-12: Added fastapi and uvicorn dependencies for REST API server.
- 2026-10-12: Added sqlalchemy, asyncpg, and alembic persistence dependencies.

## backend/app/config.py
- 2026-10-12: Implemented N8NSettings and AppSettings with URL scheme/netloc SSRF validation and environment defaults.
- 2026-10-12: Implemented DatabaseSettings with mandatory PostgreSQL URL validation and password masking.
- 2026-10-13: Added defensive SSRF cloud metadata and link-local checks to N8NSettings, and security/rate-limiting/auth configuration options to AppSettings.
- 2026-10-13: Hardened SSRF validation for IPv6 link-local (fe80::/10), cloud metadata hostnames, and fixed ValueError scoping.
- 2026-10-15: Added ResearchSettings with TAVILY_API_KEY, URL validation, search depth, timeout, retry, and cache TTL configuration.

## docs/llm-provider-strategy.md
- 2026-10-12: Updated strategy document detailing OpenRouter primary 4-key pool, Groq optional fallback, provider manager, circuit breakers, and draft preservation rules.
- 2026-10-13: Updated Section 4 model routing with nvidia/nemotron-3-super-120b-a12b:free, immediate fallback on ModelUnavailableError, and Groq trigger on model retirement.

## docs/mcp-evaluation.md
- 2026-10-12: Added comparative research and evaluation of native n8n MCP, czlonkowski/n8n-mcp, and recommended hybrid integration strategy with OpenRouter integration.

## docs/architecture.md
- 2026-10-12: Updated system architecture specification, ADR-05, and Mermaid diagram to include OpenRouter primary and Groq optional fallback.
- 2026-10-13: Updated Section 3.1 detailing prompt clause splitting, prompt-grounded provider resolution, and candidate discovery via NodeRegistry.

## docs/agent-design.md
- 2026-10-12: Added central Workflow Architect agent specification, FSM lifecycle, OpenRouter LLM integration, clarification engine, anti-hallucination prompts, and typed contracts.
- 2026-10-13: Updated Section 4 detailing clause splitting, prompt-grounded provider resolution, accumulated slot deduplication, and node-grounded evaluation fast-path.

## docs/workflow-representation.md
- 2026-10-12: Added Intermediate Representation (IR) schema, complex workflow primitives, and deterministic compiler algorithms.
- 2026-10-12: Documented verified n8n 2.42.6 node registry provenance, 444 indexed node definitions, and schema-aware validation rules.

## docs/security.md
- 2026-10-12: Added security policies, OpenRouter and Groq secret isolation and token redaction (gsk_...), execution sandboxing, and human approval gates.
- 2026-10-12: Added Section 2.4 detailing n8n REST API client isolation, X-N8N-API-KEY header containment, SSRF URL validation, and sanitized status reporting.
- 2026-10-12: Added Section 2.5 detailing PostgreSQL persistence isolation, credential sanitization, and lazy engine lifecycle.
- 2026-10-13: Added Section 6 documenting Phase 6 security controls: authentication, user isolation, defensive middlewares, SSRF prevention, and sandbox rules.
- 2026-10-13: Added Section 7 documenting Phase 7A security audit findings and verified hardening controls.

## docs/frontend-design-system.md
- 2026-10-12: Added permanent design system rules, color tokens, typography, component specifications, and prohibited visual patterns.
- 2026-10-13: Documented simplified navigation (Create, My Workflows, Settings), screen architecture, and honest draft descriptions.

## docs/testing-strategy.md
- 2026-10-12: Added 5-tier testing hierarchy, LLM provider layer test specifications (OpenRouter + Groq fallback), and complex workflow scenario test suites.

## docs/implementation-roadmap.md
- 2026-10-12: Updated roadmap marking Phase 2A (IR schemas) and Phase 2B (LLM provider layer) as completed.
- 2026-10-12: Updated Phase 2C to completed with 61 total passing unit tests across compiler, validator, and registry.
- 2026-10-12: Added Phase 3A completion for production-quality React/TypeScript frontend studio shell.
- 2026-10-12: Marked Phase 3B completed with secure read-only n8n REST client, sanitized status endpoint, and interactive Settings view.
- 2026-10-12: Marked Phase 4A completed with PostgreSQL async models, lazy engine session factory, Alembic migration 0001, and DATABASE_CHANGES log.
- 2026-10-12: Marked Phase 4B completed with Conversation REST API, explicit FSM state machine, LLM Orchestrator, draft revision persistence, and frontend integration.
- 2026-10-12: Marked Phase 5A completed with interactive React Flow visual canvas, custom node cards, and accessible node inspector.
- 2026-10-12: Marked Phase 5B completed with safe canvas editing, parameter modification, undo/redo, discard, draft revision persistence, and optimistic concurrency guards.
- 2026-10-13: Marked Phase 6 completed with 119 backend and 23 frontend passing tests, zero secret leakage, and static sandbox controls.
- 2026-10-13: Marked Phase 7A completed (testing design and security audit), and Phase 7B planned pending approval.
- 2026-10-13: Documented Workflow Intent Understanding, Clarification & Complete Graph Generation completion with 141 backend passing tests.
- 2026-10-13: Documented Workflow Clarification Logic and Multi-Turn State Management completion with 139 unit tests and 4 integration tests.
- 2026-10-13: Documented Workflow Clarification Engine and Question UI Fix completion with 148 backend passing tests and 35 frontend passing tests, and Batch Clarification Flow milestone with 152 backend and 40 frontend passing tests.
- 2026-10-13: Documented Dynamic Workflow Intent, Clarification State and Node-Driven Generation milestone with 157 backend and 40 frontend passing tests.
- 2026-10-13: Documented Dynamic Clarification Logic and Multi-Turn Requirements Deduplication milestone with 163 backend and 40 frontend passing tests.



## backend/app/schemas/ir.py
- 2026-10-12: Implemented Pydantic v2 WorkflowIR, IRNode, IREdge, WorkflowSettings, NodeExecutionPolicy, NodePosition, and topological Tarjan cycle validator.
- 2026-10-13: Added parse_workflow_ir parsing boundary and WorkflowIRParseError normalizing single-item lists, dict-wrapped workflows, and markdown blocks while strictly rejecting empty lists, multi-workflow lists, node lists, and malformed structures.

## backend/app/schemas/__init__.py
- 2026-10-13: Exported parse_workflow_ir and WorkflowIRParseError in schemas package.

## backend/app/schemas/validation.py
- 2026-10-12: Implemented ValidationIssue, ValidationIssueSeverity, and ValidationReport contracts.
- 2026-10-12: Added checks_skipped tracking to ValidationReport to distinguish fully validated workflows from partial evaluations.
- 2026-10-14: Added standardized category and resolved_category property to ValidationIssue for actionable, categorized diagnostics.

## backend/app/llm/exceptions.py
- 2026-10-12: Implemented typed LLM exception hierarchy with AllProvidersUnavailableError and preserved draft support.
- 2026-10-14: Added error category to AllProvidersUnavailableError for sanitized failure classification.

## backend/app/llm/interface.py
- 2026-10-12: Implemented provider-independent LLMClientInterface, ChatMessage, LLMRequest, LLMResponse, and TokenUsage contracts.

## backend/app/llm/config.py
- 2026-10-12: Implemented LLMSettings supporting 4 OpenRouter keys, Groq fallback, model catalogs, and operational limits.
- 2026-10-13: Updated default OPENROUTER_MODEL to nvidia/nemotron-3-super-120b-a12b:free and fallback models to verified active free OpenRouter models.
- 2026-10-14: Resolved .env from project root, updated default OPENROUTER_MODEL to nvidia/nemotron-3-super-120b-a12b:free, and configured GROQ_FALLBACK_MODELS.
- 2026-10-14: Configured LLM_REQUEST_TIMEOUT=55.0s, LLM_MAX_RETRIES=2, and TOTAL_GENERATION_DEADLINE=95.0s for consistent bounded synthesis.

## backend/app/llm/openrouter.py
- 2026-10-12: Implemented OpenRouterClient with 4-key pool management, per-key cooldowns, circuit breakers, bounded retries with jitter, and secret masking.
- 2026-10-13: Enhanced fallback model cascade on TimeoutError/ProviderUnavailableError, and skipped key rotation on ModelUnavailableError.
- 2026-10-14: Differentiated upstream provider 429 errors from account rate limits to trigger immediate model fallback without key slot cooldown.
- 2026-10-14: Enforced TOTAL_GENERATION_DEADLINE (95s) in complete(), fast-failed ReadTimeout without retrying the same stalled model, fast-failed HTTP 429 with Retry-After > 8s, and fast-failed HTTP 502/503/504 errors to fallback models immediately.

## backend/app/llm/groq.py
- 2026-10-12: Implemented optional GroqClient fallback adhering to normalized contracts with cooldown handling.
- 2026-10-14: Added dynamic model fallback cascade iterating primary and GROQ_FALLBACK_MODELS on model errors.
- 2026-10-14: Enforced TOTAL_GENERATION_DEADLINE (95s), fast-failed ReadTimeout without retrying stalled model, and fast-failed HTTP 502/503/504 and long rate limits to fallback models.

## backend/app/llm/manager.py
- 2026-10-12: Implemented LLMProviderManager orchestrating OpenRouter primary, conditional Groq fallback, and draft preservation on failure.
- 2026-10-13: Added ModelUnavailableError to qualifies_for_fallback so provider cascades to Groq if all OpenRouter models are unavailable.
- 2026-10-14: Allowed Groq fallback on OpenRouter authentication failures and categorized provider outages.
- 2026-10-14: Enforced remaining deadline check before Groq fallback (< 12s raises clean TimeoutError) and passed remaining deadline as bounded timeout.

## backend/app/data/node_catalog.json
- 2026-10-12: Seeded verified node definitions for 444 n8n nodes extracted from n8n-nodes-base in running n8n 2.42.6 container.

## backend/app/services/__init__.py
- 2026-10-12: Created services package exposing NodeRegistry, WorkflowCompiler, compile_workflow, WorkflowValidator, and validate_workflow.
- 2026-10-12: Exported N8nClient, N8nConnectionState, and N8nStatusResponse.
- 2026-10-12: Exported WorkflowReadinessEvaluator and evaluate_readiness.

## backend/app/services/n8n_client.py
- 2026-10-12: Implemented N8nClient with authenticated read-only connectivity checks, SSRF URL validation, and secret sanitization.
- 2026-10-14: Implemented safe, read-only get_credentials method extracting credential metadata (id, name, type) without exposing secrets.

## backend/app/services/node_registry.py
- 2026-10-12: Implemented NodeRegistry service with indexing by canonical and short names, version checking, required parameters, and relevance-scored search.
- 2026-10-12: Fixed missing Tuple import from typing for search method type hints.
- 2026-10-13: Enhanced search scoring with tokenized keyword matching, stop words, domain synonyms (email, telegram, notifications), and trigger/action intent alignment.
- 2026-10-14: Added get_expected_credentials method on NodeDefinition resolving alternative and operation-specific credentials (e.g. googleSheetsTriggerOAuth2Api vs googleApi) according to active parameters and node catalog.
- 2026-10-14: Corrected httpRequest credential expectations so unauthenticated HTTP requests do not require httpSslAuth.

## backend/app/services/compiler.py
- 2026-10-12: Implemented WorkflowCompiler converting WorkflowIR to native n8n JSON with 2D coordinate calculation, branching, parallel fan-out/in, loops, and error connections.
- 2026-10-14: Normalized node.credentials dict and string entries into standard n8n credential reference objects with id.

## backend/app/services/validator.py
- 2026-10-12: Implemented schema-aware WorkflowValidator enforcing node existence, version compatibility, required parameters, enum options, types, credentials, and socket bounds.
- 2026-10-13: Added Tier 3 restricted node validation (FATAL_RESTRICTED_NODE) for command execution/SSH/filesystem and Code node sandboxing (RESTRICTED_CODE_SANDBOX).
- 2026-10-13: Normalized restricted node type validation (case-insensitive short/canonical names) and enhanced Code node sandbox with escape sequence decoding.
- 2026-10-13: Added semantic consistency validation checking trigger intent mismatches, action intent mismatches, fabricated bot placeholders, and upstream data expression mappings.
- 2026-10-13: Added microsoftOutlookTrigger to recognized automated email triggers in semantic validation.
- 2026-10-13: Strengthened semantic validation to dynamically enforce event triggers (Google Sheets Trigger, Email triggers) over manualTrigger and validate upstream event expressions across integrations.
- 2026-10-13: Enforced dynamic trigger node type checking against intent.trigger.node_type to catch generic manualTrigger substitutions for any automated trigger node.
- 2026-10-14: Added is_property_visible display_options evaluation, resolved multi-property name collisions in node catalogs, enforced operation-specific required parameter validation, and added upstream data mapping semantic checks.
- 2026-10-14: Updated required credential validation to use node_def.get_expected_credentials, preventing false-positive MISSING_REQUIRED_CREDENTIAL errors on alternative authentication modes.
- 2026-10-15: Added expression syntax validation, condition node branch coverage check, and fault-tolerance error path verification.

## backend/app/api/v1/integrations.py
- 2026-10-12: Implemented GET /api/v1/integrations/n8n/status returning sanitized connection categories and safe human guidance.
- 2026-10-13: Integrated get_current_user security dependency to status endpoint for credential enforcement.
- 2026-10-13: Added GET /integrations/llm/status and POST /integrations/llm/test endpoints for live LLM connection validation and health diagnostics.
- 2026-10-14: Added GET /api/v1/integrations/n8n/credentials endpoint returning safe credential summaries from connected n8n.

## backend/app/main.py
- 2026-10-12: Implemented FastAPI application entrypoint with CORS middleware for local frontend studio and healthcheck.
- 2026-10-12: Mounted conversations REST router under /api/v1/conversations and configured CORS methods (GET, POST, PATCH, DELETE, OPTIONS).
- 2026-10-13: Added PayloadSizeLimitMiddleware, RateLimiterMiddleware, SecurityHeadersMiddleware, and sanitized global unhandled exception handler.

## frontend/package.json
- 2026-10-12: Initialized React 19 + TypeScript + Vite frontend project with lucide-react and built-in Node test runner script.
- 2026-10-12: Added @xyflow/react dependency and updated test script to run interaction and canvas test suites.
- 2026-10-12: Added canvas_editing.test.mjs to test script runner.
- 2026-10-12: Added review_readiness.test.mjs to test script runner.
- 2026-10-14: Added open_workflow.test.mjs and reliability_fixes.test.mjs to test script runner.

## frontend/public/favicon.svg
- 2026-10-12: Replaced template asset with custom SVG automation glyph mark (logic node + circuit loop) adhering to product identity.

## frontend/vite.config.ts
- 2026-10-12: Added development and preview proxy routing /api requests to local backend on port 8000.

## frontend/src/index.css
- 2026-10-12: Implemented complete production design system with dual light/dark themes, n8n industrial orange accents, rectangular modest-radius buttons, zero gradients, and reduced-motion support.
- 2026-10-12: Added status callout box styling, timestamp metadata, and studio-spin animation keyframes.
- 2026-10-12: Added standard line-clamp property to .example-snippet alongside -webkit-line-clamp.
- 2026-10-12: Added styles for interactive workflow canvas, node card focus states, node inspector panel, and React Flow control overrides.
- 2026-10-14: Added navigation rail styling, node library item hover states, and React Flow edge/handle selection styles.
- 2026-10-14: Fixed spinner animation reliability by removing transform-box: fill-box and setting transform-origin: center center; added accessible studio-pulse fallback for prefers-reduced-motion; added styling for clarification question groups and field errors.

## frontend/src/App.tsx
- 2026-10-12: Implemented main studio application shell coordinating hash routing, theme persistence, prompt state, example pre-fill, and reserved pipeline tracker.
- 2026-10-12: Integrated live conversation orchestrator API, dynamic pipeline stages, clarification submission, and draft restoration.
- 2026-10-12: Wired onRevisionSaved handler to synchronize persisted canvas revisions and compiled JSON into turnResult state.
- 2026-10-13: Streamlined workspace layout into single-action Create screen and post-generation Workflow Editor, added silent LLM health verification.
- 2026-10-13: Added 7-stage lifecycle state management, 45s bounded request timeout with AbortController, and duplicate-safe retry.
- 2026-10-13: Updated handleAnswerClarification to support saving_answer stage and updated handleSelectPastConversation to restore active clarification state upon page reload.
- 2026-10-13: Updated handleAnswerClarification to forward batch clarification answers to sendMessage client.
- 2026-10-14: Rebuilt application shell layout to integrate LeftNavRail and render full-page workflow editor when ready.
- 2026-10-14: Added submission ref lock preventing concurrent double-clicks, wired retryConversation to reuse conversation ID, and hid prompt input during non-idle workflow stages.
- 2026-10-14: Replaced fake timer progression with real-time backend stage polling (getConversationStatus) with abort cleanup and navigation cancellation; passed live backend stage and elapsed seconds to workspace stage.
- 2026-10-14: Restored saved workflow IR, draft revision, title, and canvas immediately in idle 'ready' state when opened from My Workflows without re-triggering generation; added opening ID guard and stale state clearance.
- 2026-10-14: Added terminal state reconciliation in live tracking, stopping polling and restoring draft or clarification on completion/failure; updated handleRetry to verify active generation before resubmitting and seamlessly resume live tracking if running; added active conversation tracking guard and unmount cleanup.
- 2026-10-14: Increased TIMEOUT_MS to 95000ms aligned with backend generation deadline, implemented seamless live-tracking reconnection when client connection drops or times out while backend generation is active, and prevented resetting isSubmitting until live tracking finishes.

## frontend/src/components/layout/Header.tsx
- 2026-10-13: Simplified main navigation to Create, My Workflows, and Settings, removed redundant Studio badge.

## frontend/src/components/settings/SettingsView.tsx
- 2026-10-12: Connected live n8n connection checker with rectangular button, badge mappings, detailed callout box, and honest offline handling.
- 2026-10-13: Updated status checks to send getAuthHeaders.
- 2026-10-13: Added live LLM provider status indicator, active model display, and Test LLM Connection button with latency and error diagnostics.
- 2026-10-13: Grouped settings into 4 clear sections: AI Provider & Model, n8n Connection, Authentication & Local Access, and Diagnostics & Preferences.

## frontend/tests/interaction.test.mjs
- 2026-10-12: Added 4 automated unit tests verifying example prompts catalog (em dash compliance), input validation, route parsing, and theme toggling.
- 2026-10-12: Added 3 unit tests verifying connection status badge mappings, honest offline state, and secret redaction (7 total passing).
- 2026-10-13: Added test cases verifying simplified 3-tab navigation, user-facing readiness badge labels, local draft honest descriptions, and Create screen primary button contract.
- 2026-10-13: Added test cases for 4 clarification choices (Gmail/Outlook/IMAP/Other), 7 lifecycle states, retry preservation, and Telegram chat ID format validation (15 tests passing).
- 2026-10-13: Added automated tests for multi-turn clarification sequence one question at a time and page refresh state restoration (33 total passing).
- 2026-10-13: Added tests for bot handle rejection (@Emcheckmebot), Markdown cleaning/unescaping, and double-click debounce protection (35 tests passing).
- 2026-10-13: Added automated tests for option selection without turn advancement, Other custom text requirement, single-action batch answer submission, bot username rejection, and answered question deduplication (40 tests passing).

## tests/unit/test_n8n_client.py
- 2026-10-12: Implemented 12 unit tests covering authenticated connection, missing key, invalid key, timeout, refusal, 500 error, URL validation, and secret redaction.

## tests/unit/test_workflow_ir.py
- 2026-10-12: Implemented comprehensive unit tests for WorkflowIR covering linear flows, branching, parallel fan-out/fan-in, duplicate checks, missing references, supported loops, and uncontrolled cycles.
- 2026-10-13: Added regression tests for parse_workflow_ir validating dicts, instances, single-item lists, markdown codeblocks, and strictly rejecting empty lists, multi-workflow lists, node lists, malformed JSON, and missing fields (28 tests passing).

## tests/unit/test_llm_provider.py
- 2026-10-12: Implemented 15 automated unit tests with mocked HTTP transports covering OpenRouter success, Groq fallback, retries, cooldowns, 401/402 handling, and draft preservation.
- 2026-10-13: Added regression unit tests for model fallback cascades, Groq fallback on ModelUnavailableError, env parsing, and health test endpoints.

## tests/unit/test_node_registry.py
- 2026-10-12: Added 8 unit tests for NodeRegistry covering provenance, canonical/short lookup, version checks, operation support, required parameters, search, and mocks.

## tests/unit/test_compiler.py
- 2026-10-12: Added 11 unit tests for WorkflowCompiler covering linear flow, If branching, fan-out/in, error connections, loops, determinism, policies, settings, duplicate names, and native n8n validation.
- 2026-10-12: Handled Docker execution timeouts and subprocess errors gracefully in native structure validation integration test.

## tests/unit/test_validator.py
- 2026-10-12: Added 10 unit tests for WorkflowValidator covering valid flows, unknown nodes, unsupported versions, missing parameters, enum options, expressions, unsupported ops, insecure credentials, and loops.

## backend/app/db/base.py
- 2026-10-12: Defined SQLAlchemy 2.0 DeclarativeBase for persistence entities.

## backend/app/db/session.py
- 2026-10-12: Implemented lazy async engine, sessionmaker, get_db dependency, and sanitized check_database_connection.

## backend/app/db/__init__.py
- 2026-10-12: Exported Base, session lifecycle functions, and database connectivity checker.

## backend/app/models/conversation.py
- 2026-10-12: Implemented Conversation and ConversationMessage models with JSONB metadata and CASCADE constraints.
- 2026-10-12: Added TYPE_CHECKING import for WorkflowDraft to resolve type hint references.

## backend/app/models/workflow.py
- 2026-10-12: Implemented WorkflowDraft and WorkflowRevision models with JSONB IR/compiled columns and revision uniqueness constraints.
- 2026-10-12: Added TYPE_CHECKING import for Conversation to resolve type hint references.

## backend/app/models/__init__.py
- 2026-10-12: Exported Conversation, ConversationMessage, WorkflowDraft, and WorkflowRevision.

## alembic.ini
- 2026-10-12: Configured Alembic migration environment with asyncpg URL resolution and logging formatters.

## backend/alembic/env.py
- 2026-10-12: Implemented async online migration runner linking Base.metadata and DatabaseSettings with password masking.

## backend/alembic/script.py.mako
- 2026-10-12: Added migration template file for Alembic version generation.

## backend/alembic/versions/0001_initial_schema.py
- 2026-10-12: Created initial non-destructive migration creating conversations, messages, workflow_drafts, and workflow_revisions.

## DATABASE_CHANGES.md
- 2026-10-12: Initialized migration log tracking 0001_initial_schema table definitions and indexes.
- 2026-10-15: Documented research_cache table creation with key indexing and expires_at TTL column.

## tests/unit/test_models.py
- 2026-10-12: Added 7 unit tests verifying model definitions, constraints, WorkflowIR JSONB serialization, and URL validation/masking.

## tests/integration/test_database.py
- 2026-10-12: Added PostgreSQL integration tests with safe connectivity diagnostics and conditional skip handling.

## backend/app/orchestrator/state_machine.py
- 2026-10-12: Implemented ConversationState enum, transition matrix, and StateMachine with validation report invariant.
- 2026-10-13: Added transition from None (initial state) to FAILED to safely handle immediate terminal failures.

## backend/app/orchestrator/schemas.py
- 2026-10-12: Implemented ClarificationOption, ClarificationQuestion, ClarificationPlan, and OrchestratorTurnResult typed contracts.
- 2026-10-13: Added input_type, help_text, and placeholder to ClarificationQuestion, and multi-turn state tracking fields (original_prompt, intent_summary, current_question_id, outstanding_questions, completed_answers) to ClarificationPlan and OrchestratorTurnResult.
- 2026-10-13: Added input_type, allow_other, and required to ClarificationQuestion, and added ClarificationAnswerItem and BatchClarificationSubmission contracts for structured batch clarification.
- 2026-10-14: Added readiness_report to OrchestratorTurnResult to carry evaluated readiness and categorized issues to the frontend.
- 2026-10-15: Added PlannedNode, PlannedEdge, and WorkflowPlan architectural blueprint schemas; added research_dossier and workflow_plan to OrchestratorTurnResult.

## backend/app/orchestrator/engine.py
- 2026-10-12: Implemented WorkflowOrchestrator managing requirements evaluation, IR synthesis, bounded repair loop, and draft persistence.
- 2026-10-13: Wrapped LLM planning and clarification error messages and response metadata with secret sanitization.
- 2026-10-13: Integrated WorkflowIntentExtractor for deterministic slot analysis, multi-turn history context preservation, rich node catalog retrieval, and bounded repair loop semantic validation.
- 2026-10-13: Added Outlook and IMAP prompt guidance and strict non-invented Telegram parameter constraints in workflow generation.
- 2026-10-13: Enhanced execute_turn to persist original_prompt, intent, slots, and outstanding questions in PostgreSQL conversation metadata, and passed original_prompt context to workflow generation and validator.
- 2026-10-13: Enhanced execute_turn to validate and merge batch clarification answers into accumulated slots, deduplicated questions in _evaluate_requirements to prevent repeating answered fields, and formatted multi-question assistant messages.
- 2026-10-13: Added bounded clarification limit (4 turns) preventing infinite loops, grounded requirements analysis and generation with candidate nodes from NodeRegistry, and filtered proposed choices referencing nonexistent node types.
- 2026-10-13: Fixed Telegram category slot population to prevent repeated chat ID prompts, and added intent-grounded fast-path in _evaluate_requirements bypassing LLM when trigger and actions are supported in NodeRegistry.
- 2026-10-13: Replaced direct WorkflowIR.model_validate calls with parse_workflow_ir in generation and repair paths, added bounded format-correction retry for WorkflowIRParseError, and wrapped repair loop to safely catch parsing failures.
- 2026-10-14: Added active conversation concurrency lock, skip_user_message_persistence for retries, and preserved original prompt and draft metadata on failure.
- 2026-10-14: Implemented real-time stage tracking (understanding, planning, generating, validating) via thread-safe global stage tracker, and added Google Sheets URL-to-ID extraction during batch answer normalization.
- 2026-10-14: Integrated WorkflowReadinessEvaluator into generation turn, set draft.status to readiness overall_status, populated readiness_report on turn result and message metadata, documented operation-specific required properties for candidate nodes, grounded data mappings in user prompts, and added stale stage auto-cleanup.
- 2026-10-14: Updated candidate node documentation with expected credentials and added Google Sheets Trigger OAuth2 credential structure rule in workflow generation system prompt.
- 2026-10-14: Implemented ActiveTurnLock with request_id, timestamps, and 120s staleness timeout; enforced turn cleanup in finally blocks across success, cancellations, and exceptions; deduplicated clarification questions in _evaluate_requirements by question ID and field key.
- 2026-10-14: Grounded candidate node selection on verified trigger and action nodes to avoid prompt bloat, added PDF invoice attachment and filtering guidance, bounded repair loop to 2 attempts and 75s elapsed time, and passed 55s timeout to LLM requests.
- 2026-10-15: Integrated Tavily research into workflow generation pipeline with catalog verification, architectural planning, heuristic fallback, and grounded multi-branch repair loop.
- 2026-10-15: Hardened architectural planning with 8-candidate retrieval, HTTP Request fallback for unsupported nodes, multi-branch conditional routing in heuristic fallback, and grounded prompt inclusion of branch conditions and state tracking.

## backend/app/orchestrator/__init__.py
- 2026-10-12: Created orchestrator package exporting WorkflowOrchestrator, ConversationState, and typed schemas.
- 2026-10-13: Exported WorkflowIntent, NodeIntent, and WorkflowIntentExtractor in orchestrator package.

## backend/app/api/v1/conversations.py
- 2026-10-12: Implemented REST endpoints for conversation CRUD, message turns, title renaming, and deletion.
- 2026-10-12: Added draft validation, revision persistence with row-level locks and optimistic concurrency (HTTP 409 on stale edits), revision history list/detail endpoints, and node definition lookup.
- 2026-10-12: Added draft readiness evaluation (POST /draft/readiness) and safe deterministic simulation dry-run (POST /draft/simulate) endpoints.
- 2026-10-13: Integrated UserContext dependency, per-user conversation scoping, and verify_conversation_ownership checks returning 403 on cross-user tampering.
- 2026-10-13: Added original_prompt to create_conversation metadata, and exposed original_prompt, intent, clarification, current_question_id, and outstanding_questions in ConversationDetailResponse for state reload.
- 2026-10-13: Extended SendMessageRequest with clarification_answers, backward-compatible kwargs dispatch, and added POST /conversations/{id}/clarification/answers endpoint for batch answer submissions.
- 2026-10-13: Replaced direct WorkflowIR.model_validate with parse_workflow_ir in readiness evaluation and simulation endpoints.
- 2026-10-14: Added GET /nodes/search endpoint to query verified nodes from NodeRegistry with query, category, and trigger filters.
- 2026-10-14: Persisted initial user message before executing turn, added 409 Conflict concurrency handler, and implemented POST /api/v1/conversations/{id}/retry endpoint.
- 2026-10-14: Added GET /api/v1/conversations/{conversation_id}/status endpoint exposing live backend generation stage, elapsed time, and honest status messages; exposed singleton orchestrator instance.
- 2026-10-14: Enforced verify_conversation_ownership in GET /status and propagated original_prompt context in POST /draft/readiness for semantic validation.
- 2026-10-14: Extended draft readiness evaluation with live n8n credential lookup, exposed expected_credentials in node definition endpoint, and blocked deployment when not deployment-ready.
- 2026-10-14: Enhanced get_conversation and list_conversations to restore true latest saved WorkflowRevision and return idle 'ready' state when a valid draft exists and no turn is active; updated GET /status to report honest non-planning stages when idle; guarded retry_conversation against concurrent turns and avoided premature state mutation.
- 2026-10-15: Exposed research_dossier and workflow_plan in ConversationDetailResponse and populated from latest draft metadata.

## frontend/src/api/conversations.ts
- 2026-10-12: Implemented frontend API client for conversations, message turns, drafts, and clarification submissions.
- 2026-10-12: Added typed client methods for validateWorkflowDraft, saveDraftRevision, listDraftRevisions, getDraftRevision, and getNodeDefinition.
- 2026-10-12: Added typed client methods and schemas for getWorkflowReadiness and simulateWorkflowDryRun.
- 2026-10-13: Added getAuthHeaders helper propagating X-User-Id and X-API-Key from session storage across all API requests.
- 2026-10-13: Added getLLMStatus and testLLMConnection API methods for frontend LLM health checks.
- 2026-10-13: Added optional AbortSignal parameter to createConversation and sendMessage for bounded request timeouts.
- 2026-10-13: Extended TypeScript interfaces for ClarificationQuestion, ClarificationPlan, OrchestratorTurnResult, and ConversationDetail with multi-turn intent tracking fields.
- 2026-10-13: Added ClarificationAnswerItem interface, updated ClarificationQuestion with allow_other and required, and updated sendMessage to send batch clarification answers.
- 2026-10-14: Added NodeCatalogItem interface and searchNodes API client for querying verified n8n nodes.
- 2026-10-14: Added retryConversation API method.
- 2026-10-14: Added ConversationStatusResponse interface and getConversationStatus API client method.
- 2026-10-14: Added readiness_report to OrchestratorTurnResult and category field to ValidationIssue in TypeScript API definitions.
- 2026-10-14: Added N8nCredentialSummary interface, getN8nCredentials API client, and expected_credentials field on NodeSchemaDefinition.
- 2026-10-15: Added TypeScript interfaces for ResearchSourceItem, ResearchFindingItem, StructuredResearchDossier, PlannedNodeItem, PlannedEdgeItem, WorkflowPlanItem, and extended OrchestratorTurnResult.

## frontend/src/components/workspace/PromptInput.tsx
- 2026-10-12: Updated PromptInput with loading spinner, disabled input during generation, and real session status feedback.
- 2026-10-13: Redesigned input with primary "Generate workflow" button, subtle AI provider warning notice, and removed redundant technical banners.

## frontend/src/components/workspace/ReservedWorkflowStage.tsx
- 2026-10-12: Enhanced stage component with interactive clarification question forms, validated workflow preview, node grid, and JSON inspector.
- 2026-10-12: Integrated WorkflowCanvas with view mode switcher between Interactive Canvas, Node Catalog, and compiled n8n JSON.
- 2026-10-12: Wired conversationId and onRevisionSaved callback to WorkflowCanvas.
- 2026-10-12: Added Review & Readiness stage view tab embedding WorkflowReviewPanel.
- 2026-10-13: Streamlined into a clean conversational clarification dialogue and direct canvas host, eliminating the 5-step checklist and redundant tabs.
- 2026-10-13: Implemented 7-stage generation lifecycle progress card, direct option answer submission, and custom Other email input form.
- 2026-10-13: Added saving_answer lifecycle state, completed answers summary badge, and dedicated secure Telegram configuration form with masked Bot Token n8n guidance and validated Chat ID input.
- 2026-10-13: Integrated MarkdownRenderer for assistant messages/questions/errors, rectangular option buttons with active states, working Other input with placeholder, inline answer correction/editing, and submission debouncing.
- 2026-10-14: Updated container to flex-grow and fill 100% height when in ready state for full-page workflow editor.
- 2026-10-13: Refactored into unified batch clarification form rendering all questions together, option selection without turn advancement, required Other custom answer, and single Submit answers button.
- 2026-10-13: Added dynamic free-text input rendering for clarification questions without predefined options.
- 2026-10-13: Added dynamic slot editor allowing users to modify any previously confirmed requirement without hardcoded field limits.
- 2026-10-14: Added read-only original request card display on failed and timed-out workflow stages.
- 2026-10-14: Replaced hardcoded Telegram branch with dynamic schema-driven form rendering grouped by workflow step/service; rendered controls by input_type (single_select, url, number, boolean, text); added client-side dynamic validation; updated loading state to display read-only user request context, reliable spinner, reduced-motion indicator, and real backend stage without fake progress counters.
- 2026-10-14: Decoupled saved workflow loading state from active generation stages; added dedicated 'Loading Saved Workflow...' card and 'no_draft' fallback card with explicit generation and return actions.
- 2026-10-14: Deduplicated clarification questions by ID/field_key, assigned global sequential numbering (Q1, Q2...) across all sections, and preserved pre-filled answers across refreshes.
- 2026-10-15: Added researching lifecycle state, compact Tavily Research Grounding banner, and forwarded research dossier and workflow plan to canvas.

## frontend/src/components/drafts/DraftsView.tsx
- 2026-10-12: Connected DraftsView to real PostgreSQL conversations with live count, restore into workspace, and deletion.
- 2026-10-13: Renamed to My Workflows, honestly labeled drafts as local PostgreSQL drafts without claiming live deployment to n8n.

## tests/unit/test_state_machine.py
- 2026-10-12: Added 3 unit tests verifying state transitions, invalid transition rejections, and validation report guards.

## tests/unit/test_orchestrator.py
- 2026-10-12: Added 3 unit tests covering clarification flow, workflow generation flow, and provider outage safety.
- 2026-10-14: Added unit tests for concurrency guard, failure metadata preservation, and skip_user_message_persistence (5 tests passing).

## tests/integration/test_conversations_api.py
- 2026-10-12: Added 3 PostgreSQL integration tests for conversation CRUD, message turn execution with orchestrator, and validation safety.
- 2026-10-12: Added PostgreSQL integration test for sequential draft revision persistence and optimistic concurrency 409 conflict detection.
- 2026-10-12: Added PostgreSQL integration tests for draft readiness evaluation and deterministic static dry-run simulation endpoints.
- 2026-10-14: Added integration tests for POST /retry endpoint and 409 Conflict concurrency handling.

## frontend/src/types/workflow.ts
- 2026-10-12: Implemented frontend type definitions for WorkflowIR, IRNode, and IREdge matching backend schemas.

## frontend/src/components/canvas/workflowCanvasAdapter.ts
- 2026-10-12: Implemented deterministic adapter mapping WorkflowIR to @xyflow/react nodes and edges with topological fallback layout and branching edge handles.

## frontend/src/components/canvas/WorkflowNodeCard.tsx
- 2026-10-12: Implemented custom workflow node card with integration icons, branch/error handles, selection styling, and keyboard accessibility.
- 2026-10-12: Added dedicated error socket handle for connecting explicit error pathways.
- 2026-10-14: Standardized node cards with shared nodeIconHelper, design system color tokens, and unconfigured parameter warning indicator.

## frontend/src/components/canvas/NodeInspector.tsx
- 2026-10-12: Implemented accessible node inspector panel with parameter inspector, execution policies, credential references, connection topology, and raw JSON viewer.
- 2026-10-12: Added interactive display label and parameter editing, parameter addition/deletion, execution policy toggles, connection disconnect buttons, and immutable field indicators.
- 2026-10-13: Simplified inspector layout with human-readable purpose, clear credentials notice, clean parameter list, and tucked execution policies and raw JSON into a collapsible advanced section.
- 2026-10-13: Added dedicated secure Telegram configuration card with real-time Chat ID format validation and masked Bot Token n8n setup guidance.
- 2026-10-14: Added top mode navigation bar (← Back to Library) and bottom Delete node action cascading to incident connections.
- 2026-10-14: Replaced raw secret inputs with dynamic credential control supporting n8n credential selection dropdown, ID input, status badge, and setup guidance.


## frontend/src/components/canvas/WorkflowCanvas.tsx
- 2026-10-12: Implemented interactive visual canvas using @xyflow/react with pan, zoom, fit-view controls, dark minimap, and inspector toggle.
- 2026-10-12: Added node dragging/repositioning, handle connecting, edge deletion, undo/redo history, discard edits, save draft revision with conflict handling, and revision history modal with restore.
- 2026-10-12: Added Review toolbar action and modal integrating WorkflowReviewPanel for in-canvas readiness assessment.
- 2026-10-14: Redesigned into full-page editor with slim top toolbar (editable name, breadcrumb, save status, undo/redo, test run, review), dotted canvas, bottom floating toolbar, and docked dual-mode right panel.
- 2026-10-14: Wrapped review modal in centered backdrop overlay matching history modal.
- 2026-10-15: Forwarded researchDossier and workflowPlan props to WorkflowReviewPanel.

## frontend/tests/canvas.test.mjs
- 2026-10-12: Added 6 automated unit tests verifying workflow mapping, branching, error edges, fallback DAG coordinates, empty/null safety, dangling edge filtering, and optional field preservation.

## tests/unit/test_draft_revisions.py
- 2026-10-12: Added 6 unit tests covering draft validation, revision creation, sequential numbering, 409 stale revision conflict prevention, validation failure ready guard, revision retrieval, and node definition endpoint.
- 2026-10-14: Updated configured_ir in readiness test with valid credential references to match deployment readiness requirements.

## frontend/tests/canvas_editing.test.mjs
- 2026-10-12: Added 5 unit tests verifying parameter editing, connection addition/deletion, undo/redo/discard operations, dangling edge tolerance, and optimistic concurrency conflicts.
- 2026-10-14: Added automated tests verifying node library insertion, cascade edge deletion, and workflow renaming with undo/redo.

## backend/app/schemas/readiness.py
- 2026-10-12: Defined Pydantic contracts for workflow readiness status, discrete check items, credential state tracking, safe test plan, and simulation results.
- 2026-10-14: Added REFERENCED, CONFIGURED, VERIFIED, and INVALID states to CredentialVerificationState enum.

## backend/app/services/readiness.py
- 2026-10-12: Implemented WorkflowReadinessEvaluator providing schema checks, honest credential tracking, safe test planning, and deterministic non-mutating dry-runs.
- 2026-10-13: Propagated prompt context to validator during evaluate() so semantic consistency issues surface in readiness reports and prevent invalid ready states.
- 2026-10-14: Evaluated 5 discrete credential verification states against connected n8n instance credentials, and strictly enforced is_deployment_ready = False when required credentials are missing or invalid.

## tests/unit/test_readiness.py
- 2026-10-12: Added 6 unit tests covering valid workflow readiness, missing parameter blocks, credential honesty, orphan/trigger warnings, and safe simulation dry-runs.
- 2026-10-14: Supplied required issueNumber parameter to github issue.get test node ensuring parameter completeness for credential isolation testing.

## frontend/src/components/canvas/WorkflowReviewPanel.tsx
- 2026-10-12: Implemented WorkflowReviewPanel presenting readiness checks, zero-trust credential notice, safe test plan, deterministic dry-run runner, and human approval deployment gate.
- 2026-10-13: Mapped readiness status to Ready for review, Needs configuration, and Blocked, and added explicit 5-tier concept separation breakdown.
- 2026-10-14: Fixed deployment readiness badge to show Blocked when credentials are missing or invalid, updated credentials badge with distinct missing/configured/referenced counts, and disabled deploy button when not deploy-ready.
- 2026-10-14: Redesigned review panel with simplified overall status, 5-point essential checks summary checklist, humanized actionable issues, compact credential summary table, expandable technical diagnostics, and copy JSON control.
- 2026-10-15: Added Research Grounding tab displaying consulted documentation sources, authority badges, verified facts, catalog compatibility, and architectural blueprint.

## frontend/tests/review_readiness.test.mjs
- 2026-10-12: Added 5 unit tests verifying readiness classification, credential honesty, safe test planning separation, simulation disclaimer, and dirty edit tracking.
- 2026-10-14: Added unit tests verifying unified readiness status derivation without contradiction and humanization of technical rule codes.

## backend/app/security/__init__.py
- 2026-10-13: Created security package exporting SecretSanitizer, UserContext, get_current_user, and defensive middlewares.

## backend/app/security/sanitizer.py
- 2026-10-13: Implemented SecretSanitizer scrubbing API keys, Bearer tokens, DB credentials, PEM keys, and dynamic secrets.
- 2026-10-13: Added generic URL credential masking across schemes, Basic auth headers, and standalone JWT redaction.
- 2026-10-13: Added Telegram bot token pattern to SecretSanitizer redaction patterns.

## backend/app/security/auth.py
- 2026-10-13: Implemented UserContext, get_current_user authentication dependency, and verify_conversation_ownership authorization guard.
- 2026-10-13: Restricted local_trust mode to loopback callers (403 on remote) and added fail-safe validation when STUDIO_API_KEY is empty under AUTH_ENFORCED.

## backend/app/security/middleware.py
- 2026-10-13: Implemented PayloadSizeLimitMiddleware (2MB), RateLimiterMiddleware (120 req/min), and SecurityHeadersMiddleware.
- 2026-10-13: Added streaming/chunked payload counting with ExceptionGroup unwrapping, and bounded RateLimiterMiddleware memory (MAX_TRACKED_IPS = 10000) with asyncio.Lock.

## tests/unit/test_security_hardening.py
- 2026-10-13: Added 15 automated security unit tests covering secret sanitization, auth, user isolation, SSRF, rate limiting, and sandbox rules.
- 2026-10-13: Added 8 regression unit tests for Phase 7A security audit fixes (23 tests total passing).

## docs/phase-7-testing-design.md
- 2026-10-13: Created Phase 7 controlled workflow testing design and safety architecture document defining 5 testing stages and test-only execution path requirements.

## backend/app/orchestrator/intent.py
- 2026-10-13: Created structured WorkflowIntent contracts and deterministic WorkflowIntentExtractor for trigger/action analysis, slot extraction, and clarification generation.
- 2026-10-13: Added Outlook and IMAP/Other trigger mappings, updated clarification question, and non-invented Telegram chat ID handling.
- 2026-10-13: Implemented deterministic multi-turn intent tracking, preserving original prompt across turns, asking one relevant question at a time (email provider then Telegram chat ID), and handling provider mind-changes without losing other answers.
- 2026-10-13: Standardized clarification question to 'Which email service should trigger the workflow?' with Gmail, Outlook, IMAP / Custom Email, and Other options; added is_valid_telegram_chat_id strictly rejecting bot usernames; mapped custom providers to IMAP; and enhanced generate_clarification_questions to return all outstanding missing questions simultaneously for batch answering.
- 2026-10-13: Decoupled service taxonomy to flexible NodeIntent (service_name, capability, operation, is_supported), added dynamic NodeRegistry candidate lookup, extensible SEMANTIC_TRIGGER_ALIASES, honest unsupported service clarification, and preposition extraction.
- 2026-10-13: Added split_prompt_clauses isolating trigger text from action text to prevent action email keywords from triggering email clarification; resolved explicit email providers (Gmail, Outlook, IMAP) directly from natural language; expanded SEMANTIC_TRIGGER_ALIASES for natural schedule phrases; and filtered out any question whose field exists in accumulated_slots or completed_answers.
- 2026-10-13: Added VALID_TELEGRAM_DESTINATIONS allowing private_chat, group, and channel in is_valid_telegram_chat_id so category selections are preserved in slots without question repetition, gated email_provider extraction on email context, and mapped category selections to sanitized placeholder expressions.
- 2026-10-14: Enhanced dynamic requirement analysis to extract spreadsheet document URLs/IDs (casing-preserved), sheet tabs, and data column mappings (sheets.name, sheets.email, sheets.phone); configured consolidated clarification schemas (ClarificationQuestion) with groups, input types (url, single_select), and validation rules.
- 2026-10-14: Fixed Telegram message expression formatting for mapped spreadsheet column data (name, email, phone).
- 2026-10-14: Deduplicated clarification questions in WorkflowIntentExtractor using seen question IDs and field keys to ensure single authoritative question instances across trigger and action evaluations.
- 2026-10-15: Added target_services property aggregating services from trigger and action intents.

## tests/unit/test_intent_planner.py
- 2026-10-13: Added 8 unit and regression tests for email-to-Telegram clarification, multi-turn resumption, semantic validation, credential honesty, and complex branching.
- 2026-10-13: Added 5 regression tests for IMAP trigger generation, Outlook trigger generation, non-invented chat ID, bot token redaction, and no-loop clarification resumption (13 tests passing).
- 2026-10-13: Added multi-turn sequential clarification regression test verifying Turn 2 asks for Telegram Chat ID and Turn 3 finishes to READY, and verified provider mind-changes with chat ID preservation (14 tests passing).
- 2026-10-13: Added regression tests for Telegram bot username rejection as numeric chat IDs and custom provider mapping to IMAP (16 tests passing).
- 2026-10-13: Added batch clarification regression tests verifying simultaneous question generation, batch answer submission proceeding to ready, rejection of empty other and bot usernames, and answered question deduplication (20 tests passing).
- 2026-10-13: Added regression tests for non-email event triggers (Google Sheets to Telegram), honest unsupported service handling, candidate node filtering against NodeRegistry, bounded clarification loop prevention, and semantic manual trigger rejection (25 tests passing).
- 2026-10-13: Added 5 regression tests verifying explicit Gmail avoids email provider question, Google Sheets trigger avoids email question, schedule keywords identify schedule trigger rather than email, webhook-to-Slack avoids unrelated trigger questions, and action-clause email mentions are not confused with trigger email intent (30 tests passing).
- 2026-10-13: Added regression tests for orchestrator list-wrapped single workflow normalization, repair loop list-wrapped normalization, and Telegram category selection persistence without question repetition (33 tests passing).

## frontend/src/components/common/MarkdownRenderer.tsx
- 2026-10-13: Implemented safe React Markdown renderer unescaping LLM backslashes, parsing headings, bold text, lists, and code blocks while blocking raw HTML and unsafe URI schemes.

## frontend/src/components/layout/LeftNavRail.tsx
- 2026-10-14: Implemented narrow vertical navigation rail with app brand icon, section navigation (Create, My Workflows, Settings), accessible tooltips, and theme toggle.

## frontend/src/components/canvas/NodeLibraryPanel.tsx
- 2026-10-14: Implemented searchable node library panel querying verified nodes from NodeRegistry with categories (Triggers, Actions, Logic, Data) and click-to-add action.

## frontend/src/components/canvas/nodeIconHelper.tsx
- 2026-10-14: Created shared nodeIconHelper and formatShortNodeType for consistent icon rendering across node cards, library items, and inspector.

## tests/unit/test_node_search.py
- 2026-10-14: Added 3 unit tests verifying /nodes/search endpoint query matching, is_trigger filtering, and response schema.

## tests/unit/test_phase2_dynamic_clarification.py
- 2026-10-14: Added 6 unit tests covering dynamic requirements discovery, Google Sheets to Telegram column extraction, supplied answer deduplication, conditional requirements, answer validation error reporting, and node registry candidate grounding.

## tests/unit/test_phase3_workflow_generation.py
- 2026-10-14: Added 6 focused unit tests covering Google Sheets to Telegram end-to-end generation, If branching compilation, fan-out multi-action layout, operation-specific parameter validation, actionable issue categories, and conversation status isolation.
- 2026-10-14: Updated readiness credential count assertion for Google Sheets Trigger and Telegram to exactly 2 required credentials.

## tests/unit/test_credentials_and_readiness.py
- 2026-10-14: Added 10 unit tests verifying operation-specific credential resolution, validator accuracy without duplicate googleApi requirements, 5 credential states, readiness consistency, compiler normalization, and safe n8n client metadata extraction.

## frontend/tests/open_workflow.test.mjs
- 2026-10-14: Added 10 targeted automated unit tests verifying saved workflow restoration, zero generation calls on Open, draft revision preservation, loading vs generation separation, and route safety.

## tests/unit/test_reliability_clarification_retry.py
- 2026-10-14: Added 6 unit tests verifying clarification question deduplication, stable unique IDs, stale lock timeout recovery, independent conversation execution, and lock release upon LLM provider failure.

## frontend/tests/reliability_fixes.test.mjs
- 2026-10-14: Added 13 automated frontend tests verifying clarification question deduplication, global sequential numbering across sections, answer pre-fill preservation, SVG spinner transform origin, reduced-motion pulse fallback, live tracking terminal reconciliation, retry concurrency guards, TIMEOUT_MS 95000 alignment, client timeout reconnection, and draft recovery.

## tests/unit/test_workflow_synthesis_timeout.py
- 2026-10-14: Added 6 unit tests verifying successful synthesis, fast-fail on ReadTimeout without retrying stalled model, HTTP 502 fast-fail to fallback model, overall deadline exhaustion, OpenRouter-to-Groq fallback, and bounded candidate selection.

## backend/app/services/research/exceptions.py
- 2026-10-15: Implemented typed research exception hierarchy with TavilyClientError, TavilyAuthError, TavilyRateLimitError, TavilyTimeoutError, and TavilyUnavailableError.

## backend/app/services/research/schemas.py
- 2026-10-15: Implemented ResearchSource, ResearchUsage, NormalizedResearchResult, ResearchFinding, and StructuredResearchDossier schemas.

## backend/app/services/research/validator.py
- 2026-10-15: Implemented ResearchSourceValidator with SSRF prevention, domain authority classification, prompt injection sanitization, version hint extraction, and URL deduplication.

## backend/app/services/research/cache.py
- 2026-10-15: Implemented ResearchCacheInterface, MemoryResearchCache (LRU with TTL), and PostgresResearchCache with automatic memory fallback.

## backend/app/services/research/client.py
- 2026-10-15: Implemented TavilyResearchClient supporting search and extract APIs with bounded retries, exponential backoff, timeouts, and response normalization.

## backend/app/services/research/service.py
- 2026-10-15: Implemented ResearchService orchestrating selective research decisions, targeted query generation, catalog verification, and fact extraction.
- 2026-10-15: Hardened keyword pattern matching for paginated variants, enhanced custom service name extraction from prompts, normalized multi-word catalog lookups, and added HMAC webhook verification fact extraction.

## backend/app/services/research/__init__.py
- 2026-10-15: Exported research client, service, cache, validator, exceptions, and schemas.

## tests/unit/test_tavily_research.py
- 2026-10-15: Added 14 unit tests covering search, extract, rate limit backoff, timeout, SSRF protection, prompt injection neutralization, LRU/TTL cache, and research decision logic.

## tests/unit/test_research_workflow_planning.py
- 2026-10-15: Added 11 unit tests verifying complex multi-branching conditions, skipping research for built-in nodes, unsupported node HTTP fallback, graceful failure handling, multi-branch edge connections, and Scenarios A through F (order monitoring, PDF invoice processing with error retry, pagination with rate limits, custom REST API integration, missing config clarification, and Tavily failure honesty).

## backend/app/services/n8n_client.py
- 2026-10-15: Explicitly enforced "active": False in the create_workflow REST API payload, ensuring generated workflows deployed to n8n remain strictly inactive drafts until human activation.

## frontend/src/App.tsx
- 2026-10-15: Resolved defect in draft restoration by preserving research_dossier and workflow_plan when reopening saved conversations and navigating via direct route.

## frontend/src/components/canvas/WorkflowReviewPanel.tsx
- 2026-10-15: Enhanced Research Grounding tab with honest lifecycle status computation (distinguishing completed, partial, fallback/failed, and skipped catalog grounding), safe URL protocol validation, domain authority badges, relevance scoring, version hints, visual separation of verified technical facts from inferred assumptions and unresolved setup actions, and comprehensive architectural blueprint display.
- 2026-10-15: Replaced all scattered Loader2 and animated spinning indicators with the unified OrbitLoader component across readiness status, dry-run simulation, readiness checks loading, and n8n deployment approval modal.

## frontend/src/components/workspace/ReservedWorkflowStage.tsx
- 2026-10-15: Added honest research fallback notice in clarification and stage view when external web research is unavailable or unconfigured, preventing false verification claims.
- 2026-10-15: Replaced Loader2 spinners with OrbitLoader for saved workflow restoration, active workflow generation, and clarification answer submission.

## frontend/package.json
- 2026-10-15: Added tests/phase3_grounding_ui.test.mjs to frontend test runner script.
- 2026-10-15: Added tests/orbit_loader.test.mjs to frontend test runner script.

## frontend/tests/phase3_grounding_ui.test.mjs
- 2026-10-15: Added 6 automated frontend unit tests verifying honest research status computation, safe URL filtering, separation of verified facts from assumptions/unresolved items, draft reopening preservation, and deployment safety gating.

## tests/unit/test_phase3_readiness_and_safety.py
- 2026-10-15: Added 8 comprehensive Phase 3 backend unit tests verifying malformed URL sanitization, graceful fallback on Tavily unavailability, plan/IR/compiler topological consistency, unknown node detection, missing credential blocking, inactive deployment payload enforcement, generation lock cleanup, and distinction between static validity and live execution.

## frontend/src/components/common/OrbitLoader.tsx
- 2026-10-15: Created reusable, accessible, lightweight OrbitLoader component with responsive sizing (inline 14px, xs 16px, sm 20px, md 32px, lg 48px), brand theme color integration, dual orbital satellite physics, ARIA live region status semantics, and screen-reader utilities.

## frontend/src/index.css
- 2026-10-15: Added OrbitLoader layout classes, clockwise/counter-clockwise orbital rotation keyframes, breathing core pulse, accessible sr-only utility class, and reduced-motion fallback pulse.

## frontend/src/components/workspace/PromptInput.tsx
- 2026-10-15: Replaced spinning Loader2 icon in the workflow generation submit button with unified OrbitLoader inline indicator.

## frontend/src/components/settings/SettingsView.tsx
- 2026-10-15: Replaced Loader2 and spinning RefreshCw indicators with OrbitLoader for n8n connection checks and LLM provider latency testing.

## frontend/src/components/drafts/DraftsView.tsx
- 2026-10-15: Replaced spinning Loader2 with OrbitLoader for persisted drafts loading and added inline loader during draft deletion.

## frontend/src/components/canvas/WorkflowCanvas.tsx
- 2026-10-15: Replaced Loader2 spinners with OrbitLoader for draft revision save actions and revision history modal loading.
- 2026-10-15: Fixed canvas node jumping bug by collecting rendered positions from React Flow nodes state during onNodesChange so un-dragged nodes never collapse to default coordinates, added explicit Auto-layout button in top toolbar, and ensured reopening saved drafts restores exact saved positions.

## frontend/src/components/canvas/NodeLibraryPanel.tsx
- 2026-10-15: Replaced Loader2 spinner with centered OrbitLoader during verified node search queries.

## frontend/tests/orbit_loader.test.mjs
- 2026-10-15: Added automated tests verifying OrbitLoader accessibility contracts, orbital structural hierarchies, CSS keyframes, reduced-motion compatibility, and clean removal of legacy Loader2 references across all frontend components.

## frontend/src/components/canvas/workflowCanvasAdapter.ts
- 2026-10-15: Fixed critical layout bug where hasExplicitPositions caused fallbackLayout to become an empty map when one node was dragged, collapsing all other nodes onto (100, 150); exported computeFallbackLayout and ensured fallbackLayout is always available for any node lacking explicit coordinates.

## backend/app/orchestrator/schemas.py
- 2026-10-15: Added status and source fields to ClarificationQuestion and status field to ClarificationPlan (supporting "ready_to_plan", "waiting_for_required_information", and "blocked_by_invalid_configuration") to provide a canonical stopping condition.

## backend/app/orchestrator/intent.py
- 2026-10-15: Implemented CANONICAL_SLOT_SYNONYMS mapping equivalent slot variations (chat_id, target_chat_id, spreadsheet_id, etc.) to canonical keys; added robust Telegram Chat ID extraction supporting positive/negative numeric IDs and channel handles; added natural language answer extraction across all historical conversation turns; batched missing fields into a single clarification round; and prevented duplicate question generation against canonical slots and completed answers.

## backend/app/orchestrator/engine.py
- 2026-10-15: Canonicalized and strictly validated submitted clarification answers and selected options, rejecting invalid bot usernames ending in 'bot' and normalizing Google Sheets URLs to document IDs; persisted canonical clarification plan in conversation metadata_json across turns and page reloads; hardened _evaluate_requirements system prompt to distinguish resolved from missing requirements and filter duplicate questions semantically; updated _generate_workflow_ir prompt rules to strictly bind resolved slots into node parameters rather than inserting placeholder strings; and bypassed LLM clarification evaluation when trigger and actions are already supported.

## tests/unit/test_reliability_clarification_retry.py
- 2026-10-15: Added targeted unit tests verifying Telegram chat ID extraction from initial requests without re-asking, natural language answer extraction across conversation history, multiple missing integration field batching, bot username rejection, and canonical synonym normalization.

## frontend/tests/canvas_editing.test.mjs
- 2026-10-15: Added automated tests verifying that dragging a single node preserves other nodes' fallback coordinates without overlapping or collapsing to default coordinates, and that saved explicit node coordinates are faithfully restored when reopening draft revisions.
