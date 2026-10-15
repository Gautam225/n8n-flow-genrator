/**
 * Type definitions for the n8n Workflow AI frontend application.
 */

export type AppRoute = 'workspace' | 'drafts' | 'settings';

export type AppTheme = 'light' | 'dark';

export interface ExamplePrompt {
  id: string;
  title: string;
  category: 'Scheduling' | 'Webhooks' | 'Data Sync' | 'Fault Tolerance';
  description: string;
  prompt: string;
}

export interface WorkflowDraft {
  id: string;
  name: string;
  prompt: string;
  status: 'draft' | 'validating' | 'preview_ready' | 'active' | 'rejected';
  createdAt: string;
  nodeCount: number;
}

export interface ProviderStatus {
  name: string;
  role: 'Primary' | 'Optional Fallback' | 'Engine Host';
  configured: boolean;
  statusText: string;
  details: string;
}
