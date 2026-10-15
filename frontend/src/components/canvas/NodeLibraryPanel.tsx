import React, { useState, useEffect, useCallback } from 'react';
import {
  Search,
  X,
  AlertCircle,
  Plus,
  Layers,
} from 'lucide-react';
import { OrbitLoader } from '../common/OrbitLoader';
import { searchNodes, type NodeCatalogItem } from '../../api/conversations';
import { getNodeIcon, formatShortNodeType } from './nodeIconHelper';

interface NodeLibraryPanelProps {
  onSelectNodeToAdd: (nodeDef: NodeCatalogItem) => void;
  onClose: () => void;
}

type CategoryTab = 'all' | 'triggers' | 'actions' | 'logic' | 'data';

export const NodeLibraryPanel: React.FC<NodeLibraryPanelProps> = ({
  onSelectNodeToAdd,
  onClose,
}) => {
  const [query, setQuery] = useState('');
  const [category, setCategory] = useState<CategoryTab>('all');
  const [nodes, setNodes] = useState<NodeCatalogItem[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const fetchNodes = useCallback(async (q: string, cat: CategoryTab) => {
    setIsLoading(true);
    setErrorMessage(null);
    try {
      const isTrigger = cat === 'triggers' ? true : cat === 'actions' ? false : undefined;
      const catParam = cat === 'logic' ? 'transform' : cat === 'data' ? 'input' : undefined;
      const results = await searchNodes(q, catParam, isTrigger, 50);
      setNodes(results);
    } catch (err: any) {
      setErrorMessage(err.message || 'Failed to load node catalog.');
      setNodes([]);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    const timer = setTimeout(() => {
      fetchNodes(query, category);
    }, 200);
    return () => clearTimeout(timer);
  }, [query, category, fetchNodes]);

  return (
    <aside
      className="node-library-panel"
      role="region"
      aria-label="Node Library"
      style={{
        width: '380px',
        maxWidth: '100%',
        backgroundColor: 'var(--bg-surface)',
        borderLeft: '1px solid var(--border-default)',
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        overflowY: 'hidden',
        color: 'var(--text-primary)',
        boxShadow: 'var(--shadow-lg)',
        zIndex: 10,
      }}
    >
      {/* Header */}
      <div
        style={{
          padding: '16px',
          borderBottom: '1px solid var(--border-subtle)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <Layers size={16} style={{ color: 'var(--brand-primary)' }} />
          <h2 style={{ fontSize: '14px', fontWeight: 600, color: 'var(--text-primary)', margin: 0 }}>
            Node Library
          </h2>
        </div>
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          onClick={onClose}
          aria-label="Close Node Library"
          style={{ padding: '6px', color: 'var(--text-secondary)' }}
        >
          <X size={16} />
        </button>
      </div>

      {/* Search Input */}
      <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border-subtle)' }}>
        <div
          style={{
            position: 'relative',
            display: 'flex',
            alignItems: 'center',
          }}
        >
          <Search
            size={14}
            style={{
              position: 'absolute',
              left: '10px',
              color: 'var(--text-tertiary)',
              pointerEvents: 'none',
            }}
          />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search verified n8n nodes..."
            aria-label="Search nodes"
            style={{
              width: '100%',
              padding: '7px 10px 7px 32px',
              fontSize: '13px',
              backgroundColor: 'var(--bg-surface-subtle)',
              border: '1px solid var(--border-default)',
              borderRadius: 'var(--radius-sm)',
              color: 'var(--text-primary)',
            }}
            autoFocus
          />
          {query && (
            <button
              type="button"
              onClick={() => setQuery('')}
              style={{
                position: 'absolute',
                right: '8px',
                background: 'transparent',
                border: 'none',
                color: 'var(--text-tertiary)',
                cursor: 'pointer',
                padding: '2px',
              }}
            >
              <X size={12} />
            </button>
          )}
        </div>

        {/* Category Filter Pills */}
        <div
          style={{
            display: 'flex',
            flexWrap: 'wrap',
            gap: '6px',
            marginTop: '10px',
          }}
        >
          {[
            { id: 'all', label: 'All' },
            { id: 'triggers', label: 'Triggers' },
            { id: 'actions', label: 'Actions' },
            { id: 'logic', label: 'Logic' },
            { id: 'data', label: 'Data' },
          ].map((tab) => {
            const isActive = category === tab.id;
            return (
              <button
                key={tab.id}
                type="button"
                onClick={() => setCategory(tab.id as CategoryTab)}
                style={{
                  fontSize: '11px',
                  fontWeight: isActive ? 600 : 500,
                  padding: '3px 8px',
                  borderRadius: 'var(--radius-sm)',
                  border: isActive
                    ? '1px solid var(--brand-primary)'
                    : '1px solid var(--border-default)',
                  backgroundColor: isActive
                    ? 'var(--brand-primary-subtle)'
                    : 'transparent',
                  color: isActive
                    ? 'var(--brand-primary)'
                    : 'var(--text-secondary)',
                  cursor: 'pointer',
                }}
              >
                {tab.label}
              </button>
            );
          })}
        </div>
      </div>

      {/* Nodes List */}
      <div
        style={{
          flex: 1,
          overflowY: 'auto',
          padding: '12px 16px',
          display: 'flex',
          flexDirection: 'column',
          gap: '8px',
        }}
      >
        {isLoading && (
          <div
            style={{
              padding: '32px 16px',
              display: 'flex',
              justifyContent: 'center',
            }}
          >
            <OrbitLoader
              size="sm"
              label="Searching verified nodes..."
              labelPosition="bottom"
              center
            />
          </div>
        )}

        {errorMessage && (
          <div
            style={{
              padding: '12px',
              borderRadius: 'var(--radius-sm)',
              backgroundColor: 'var(--state-error-subtle)',
              border: '1px solid var(--state-error)',
              color: 'var(--state-error)',
              fontSize: '12px',
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
            }}
          >
            <AlertCircle size={14} />
            <span>{errorMessage}</span>
          </div>
        )}

        {!isLoading && !errorMessage && nodes.length === 0 && (
          <div
            style={{
              padding: '32px 16px',
              textAlign: 'center',
              color: 'var(--text-tertiary)',
              fontSize: '13px',
            }}
          >
            No verified nodes found matching &quot;{query}&quot;.
          </div>
        )}

        {!isLoading &&
          nodes.map((n) => (
            <div
              key={n.canonical_name}
              role="button"
              tabIndex={0}
              onClick={() => onSelectNodeToAdd(n)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  onSelectNodeToAdd(n);
                }
              }}
              style={{
                padding: '10px 12px',
                backgroundColor: 'var(--bg-surface-subtle)',
                border: '1px solid var(--border-default)',
                borderRadius: 'var(--radius-sm)',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'flex-start',
                gap: '10px',
                transition: 'border-color 0.15s ease, background-color 0.15s ease',
              }}
              className="node-library-item"
            >
              <div
                style={{
                  width: '28px',
                  height: '28px',
                  borderRadius: 'var(--radius-sm)',
                  backgroundColor: 'var(--bg-surface)',
                  border: '1px solid var(--border-subtle)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  flexShrink: 0,
                  marginTop: '2px',
                }}
              >
                {getNodeIcon(n.canonical_name, 15)}
              </div>

              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '6px' }}>
                  <span
                    style={{
                      fontSize: '13px',
                      fontWeight: 600,
                      color: 'var(--text-primary)',
                      whiteSpace: 'nowrap',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                    }}
                  >
                    {n.display_name}
                  </span>

                  <span
                    style={{
                      fontSize: '10px',
                      fontWeight: 600,
                      padding: '1px 5px',
                      borderRadius: 'var(--radius-sm)',
                      backgroundColor: n.is_trigger
                        ? 'rgba(234, 88, 12, 0.12)'
                        : 'var(--bg-surface)',
                      color: n.is_trigger
                        ? 'var(--brand-primary)'
                        : 'var(--text-tertiary)',
                      border: '1px solid var(--border-subtle)',
                      textTransform: 'uppercase',
                    }}
                  >
                    {n.is_trigger ? 'Trigger' : 'Action'}
                  </span>
                </div>

                <div
                  style={{
                    fontSize: '11px',
                    color: 'var(--text-secondary)',
                    marginTop: '2px',
                    lineHeight: 1.35,
                    display: '-webkit-box',
                    WebkitLineClamp: 2,
                    WebkitBoxOrient: 'vertical',
                    overflow: 'hidden',
                  }}
                  title={n.description}
                >
                  {n.description || formatShortNodeType(n.canonical_name)}
                </div>
              </div>

              <div style={{ flexShrink: 0, alignSelf: 'center', color: 'var(--text-tertiary)' }}>
                <Plus size={14} />
              </div>
            </div>
          ))}
      </div>
    </aside>
  );
};
