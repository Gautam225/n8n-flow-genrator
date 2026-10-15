# Database Change Log

All database schema migrations are tracked here with rationale and affected entities.

## 2026-10-12 — Migration 0001_initial_schema
- Changed:
  - Created table `conversations` with columns `id`, `title`, `metadata_json`, `created_at`, `updated_at`.
  - Created table `conversation_messages` with columns `id`, `conversation_id`, `role`, `content`, `metadata_json`, `created_at` and index `ix_conversation_messages_conversation_id`.
  - Created table `workflow_drafts` with columns `id`, `conversation_id`, `title`, `status`, `workflow_ir`, `compiled_json`, `created_at`, `updated_at` and index `ix_workflow_drafts_conversation_id`.
  - Created table `workflow_revisions` with columns `id`, `draft_id`, `revision_number`, `workflow_ir`, `compiled_json`, `validation_report`, `created_at`, index `ix_workflow_revisions_draft_id`, and unique constraint `uq_draft_revision_number`.
- Reason: Foundational persistence schema for multi-turn conversations, workflow IR drafts, and revision history.

## 2026-10-15 — Tavily Research Persistent Caching
- Changed: Added `research_cache` table (columns: `cache_key`, `query`, `result_json`, `expires_at`, `created_at`) with index on `cache_key` and automatic TTL expiration.
- Reason: Persistent caching and deduplication of Tavily web search and page extraction results across workflow turns, preventing redundant external API calls and rate limits.

