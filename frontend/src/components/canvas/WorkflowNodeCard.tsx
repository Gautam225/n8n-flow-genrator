import React, { memo } from 'react';
import { Handle, Position, type NodeProps, type Node } from '@xyflow/react';
import type { IRNode } from '../../types/workflow';
import { getNodeIcon, formatShortNodeType } from './nodeIconHelper';
import { AlertCircle } from 'lucide-react';

export const WorkflowNodeCard: React.FC<NodeProps<Node<IRNode>>> = memo(({ data, selected }) => {
  const isBranching = (data.node_type || '').toLowerCase().includes('if');
  const isTrigger =
    (data.node_type || '').toLowerCase().includes('trigger') ||
    (data.node_type || '').toLowerCase().includes('webhook');

  // Check for unresolved placeholders in parameters
  const hasUnconfiguredParams = Object.values(data.parameters || {}).some(
    (val) => typeof val === 'string' && val.includes('<YOUR_')
  );

  return (
    <div
      className={`node-card-wrapper ${selected ? 'selected' : ''}`}
      style={{
        width: '230px',
        backgroundColor: 'var(--bg-surface)',
        border: selected
          ? '1.5px solid var(--brand-primary)'
          : hasUnconfiguredParams
          ? '1px solid var(--state-warning)'
          : '1px solid var(--border-default)',
        borderRadius: 'var(--radius-md)',
        boxShadow: selected
          ? '0 0 0 2px rgba(234, 88, 12, 0.25), var(--shadow-md)'
          : 'var(--shadow-sm)',
        color: 'var(--text-primary)',
        cursor: 'pointer',
        position: 'relative',
        transition: 'border-color 0.15s ease, box-shadow 0.15s ease',
        userSelect: 'none',
      }}
      tabIndex={0}
      role="button"
      aria-label={`${data.name} node (${data.node_type})`}
    >
      {/* Target input handle (Left) - Not needed on triggers */}
      {!isTrigger && (
        <Handle
          type="target"
          position={Position.Left}
          id="input-0"
          style={{
            width: '8px',
            height: '8px',
            background: 'var(--border-focused)',
            border: '2px solid var(--bg-surface)',
            borderRadius: '2px',
          }}
          title="Input connection"
        />
      )}

      {/* Card Content Header */}
      <div
        className="node-card-drag-handle"
        style={{
          padding: '10px 12px',
          display: 'flex',
          alignItems: 'center',
          gap: '10px',
        }}
      >
        <div
          style={{
            width: '28px',
            height: '28px',
            borderRadius: 'var(--radius-sm)',
            backgroundColor: 'var(--bg-surface-subtle)',
            border: '1px solid var(--border-subtle)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            flexShrink: 0,
          }}
        >
          {getNodeIcon(data.node_type, 15)}
        </div>

        <div style={{ flex: 1, minWidth: 0 }}>
          <div
            style={{
              fontSize: '13px',
              fontWeight: 600,
              color: 'var(--text-primary)',
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              lineHeight: 1.2,
            }}
            title={data.name}
          >
            {data.name}
          </div>
          <div
            style={{
              fontSize: '11px',
              color: 'var(--text-secondary)',
              fontFamily: 'var(--font-mono)',
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              marginTop: '3px',
            }}
            title={data.node_type}
          >
            {data.operation || formatShortNodeType(data.node_type)}
          </div>
        </div>

        <div style={{ flexShrink: 0, display: 'flex', alignItems: 'center', gap: '4px' }}>
          {hasUnconfiguredParams && (
            <span title="Node has unconfigured parameters or placeholders" style={{ color: 'var(--state-warning)' }}>
              <AlertCircle size={13} />
            </span>
          )}

          <span
            style={{
              fontSize: '10px',
              fontWeight: 600,
              padding: '2px 5px',
              borderRadius: 'var(--radius-sm)',
              backgroundColor: data.disabled
                ? 'var(--bg-surface-subtle)'
                : 'var(--state-success-subtle)',
              color: data.disabled
                ? 'var(--text-tertiary)'
                : 'var(--state-success)',
              fontFamily: 'var(--font-mono)',
              border: '1px solid var(--border-subtle)',
            }}
          >
            {data.disabled ? 'OFF' : `v${data.type_version || 1}`}
          </span>
        </div>
      </div>

      {/* Output Handles */}
      {isBranching ? (
        <>
          {/* Branch 0: True */}
          <Handle
            type="source"
            position={Position.Right}
            id="output-0"
            style={{
              top: '30%',
              width: '8px',
              height: '8px',
              background: 'var(--state-success)',
              border: '2px solid var(--bg-surface)',
              borderRadius: '2px',
            }}
            title="True branch (output 0)"
          />
          {/* Branch 1: False */}
          <Handle
            type="source"
            position={Position.Right}
            id="output-1"
            style={{
              top: '70%',
              width: '8px',
              height: '8px',
              background: 'var(--state-error)',
              border: '2px solid var(--bg-surface)',
              borderRadius: '2px',
            }}
            title="False branch (output 1)"
          />
        </>
      ) : (
        <Handle
          type="source"
          position={Position.Right}
          id="output-0"
          style={{
            width: '8px',
            height: '8px',
            background: 'var(--border-focused)',
            border: '2px solid var(--bg-surface)',
            borderRadius: '2px',
          }}
          title="Main output (output 0)"
        />
      )}

      {/* Error Output Handle (Bottom) */}
      <Handle
        type="source"
        position={Position.Bottom}
        id="error"
        style={{
          width: '8px',
          height: '8px',
          background: 'var(--state-error)',
          border: '2px solid var(--bg-surface)',
          borderRadius: '2px',
        }}
        title="Error output (error branch)"
      />
    </div>
  );
});

WorkflowNodeCard.displayName = 'WorkflowNodeCard';
