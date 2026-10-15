/**
 * Frontend types for Workflow Intermediate Representation (IR) and Canvas Mapping.
 * Strictly mirrors backend/app/schemas/ir.py.
 */

export interface NodePosition {
  x: number;
  y: number;
}

export interface NodeExecutionPolicy {
  continue_on_fail?: boolean;
  retry_on_fail?: boolean;
  max_tries?: number;
  wait_between_tries?: number;
}

export interface IRNode {
  [key: string]: unknown;
  id: string;
  name: string;
  node_type: string;
  type_version: number;
  description?: string;
  disabled?: boolean;
  notes?: string;
  operation?: string;
  parameters?: Record<string, any>;
  credentials?: Record<string, any>;
  execution_policy?: NodeExecutionPolicy;
  position?: NodePosition;
  metadata?: Record<string, any>;
}

export interface IREdge {
  source_id: string;
  target_id: string;
  connection_type?: 'main' | 'error';
  source_output_index?: number;
  target_input_index?: number;
  description?: string;
}

export interface WorkflowIR {
  id: string;
  name: string;
  description?: string;
  version?: number;
  settings?: Record<string, any>;
  nodes: IRNode[];
  edges: IREdge[];
}
