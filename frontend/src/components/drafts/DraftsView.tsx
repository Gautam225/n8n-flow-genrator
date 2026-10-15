import React, { useState, useEffect } from 'react';
import { History, Plus, ArrowRight, Trash2 } from 'lucide-react';
import { Button } from '../ui/Button';
import { Badge } from '../ui/Badge';
import { OrbitLoader } from '../common/OrbitLoader';
import { listConversations, deleteConversation, type ConversationSummary } from '../../api/conversations';

interface DraftsViewProps {
  onNewWorkflow: () => void;
  onSelectConversation?: (conversationId: string) => void;
}

export const DraftsView: React.FC<DraftsViewProps> = ({
  onNewWorkflow,
  onSelectConversation,
}) => {
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  useEffect(() => {
    let ignore = false;
    const load = async () => {
      try {
        const items = await listConversations();
        if (!ignore) setConversations(items);
      } catch (err: any) {
        if (!ignore) setError(err.message || 'Failed to fetch conversations from database.');
      } finally {
        if (!ignore) setLoading(false);
      }
    };
    load();
    return () => {
      ignore = true;
    };
  }, []);

  const handleDelete = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!confirm('Are you sure you want to delete this conversation and its revisions?')) return;
    setDeletingId(id);
    try {
      await deleteConversation(id);
      setConversations((prev) => prev.filter((c) => c.id !== id));
    } catch (err: any) {
      alert(`Delete failed: ${err.message}`);
    } finally {
      setDeletingId(null);
    }
  };

  const getStateBadge = (state: string) => {
    switch (state) {
      case 'ready':
        return <Badge variant="success">Ready</Badge>;
      case 'clarifying':
        return <Badge variant="warning">Clarifying</Badge>;
      case 'failed':
        return <Badge variant="error">Failed</Badge>;
      default:
        return <Badge variant="info">{state}</Badge>;
    }
  };

  return (
    <div>
      <div className="workspace-header">
        <h1 className="workspace-title">My Workflows</h1>
        <p className="workspace-subtitle">
          Locally saved workflow drafts stored in PostgreSQL. These drafts are stored locally and are not deployed or activated in n8n.
        </p>
      </div>

      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: '20px',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            style={{ fontWeight: 600 }}
          >
            Saved Drafts ({conversations.length})
          </button>
        </div>

        <Button
          variant="primary"
          size="sm"
          onClick={onNewWorkflow}
          icon={<Plus size={14} />}
        >
          Create workflow
        </Button>
      </div>

      {loading ? (
        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '48px 16px',
            gap: '12px',
          }}
        >
          <OrbitLoader
            size="md"
            label="Loading persisted workflows from PostgreSQL..."
            labelPosition="bottom"
          />
        </div>
      ) : error ? (
        <div
          className="feedback-banner warning"
          style={{ marginBottom: '24px' }}
        >
          <div><strong>Could not load drafts:</strong> {error}</div>
        </div>
      ) : conversations.length === 0 ? (
        <div className="empty-state">
          <History size={36} className="empty-icon" />
          <h2 className="empty-title">No saved workflows found</h2>
          <p className="empty-desc">
            Workflows generated in the Create tab are stored with full revision history in PostgreSQL.
            Start an automation prompt to generate your first draft.
          </p>
          <Button
            variant="secondary"
            size="md"
            onClick={onNewWorkflow}
            icon={<Plus size={14} />}
          >
            Create first workflow
          </Button>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
          {conversations.map((conv) => (
            <div
              key={conv.id}
              style={{
                backgroundColor: 'var(--bg-surface)',
                border: '1px solid var(--border-subtle)',
                borderRadius: 'var(--radius-md)',
                padding: '16px 20px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                transition: 'border-color 0.15s ease',
              }}
            >
              <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                  <span style={{ fontSize: '15px', fontWeight: 600, color: 'var(--text-primary)' }}>
                    {conv.title}
                  </span>
                  {getStateBadge(conv.state)}
                </div>
                <div style={{ fontSize: '12px', color: 'var(--text-tertiary)' }}>
                  Created {new Date(conv.created_at).toLocaleString()} • {conv.message_count} turn(s)
                </div>
              </div>

              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                {onSelectConversation && (
                  <Button
                    variant="secondary"
                    size="sm"
                    icon={<ArrowRight size={14} />}
                    onClick={() => onSelectConversation(conv.id)}
                  >
                    Open
                  </Button>
                )}
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={deletingId === conv.id}
                  icon={
                    deletingId === conv.id ? (
                      <OrbitLoader size="inline" color="currentColor" />
                    ) : (
                      <Trash2 size={14} style={{ color: 'var(--danger-text)' }} />
                    )
                  }
                  onClick={(e) => handleDelete(conv.id, e)}
                  title="Delete conversation"
                >
                  {deletingId === conv.id ? 'Deleting...' : 'Delete'}
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
