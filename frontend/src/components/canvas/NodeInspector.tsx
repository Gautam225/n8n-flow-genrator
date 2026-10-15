import React, { useEffect, useState } from 'react';
import type { IRNode, IREdge } from '../../types/workflow';
import {
  X,
  Sliders,
  Settings,
  GitBranch,
  KeyRound,
  Copy,
  Check,
  Plus,
  Trash2,
  ChevronDown,
  ChevronRight,
  ArrowLeft,
} from 'lucide-react';
import { Button } from '../ui/Button';
import { getN8nCredentials, getNodeDefinition, type N8nCredentialSummary } from '../../api/conversations';

interface NodeInspectorProps {
  node: IRNode | null;
  edges: IREdge[];
  allNodes?: IRNode[];
  onClose: () => void;
  onUpdateNode?: (updated: IRNode) => void;
  onDeleteNode?: (nodeId: string) => void;
  onDeleteEdge?: (sourceId: string, targetId: string, sourceOutputIndex?: number, targetInputIndex?: number) => void;
  onSwitchToLibrary?: () => void;
  isReadOnly?: boolean;
}

export const NodeInspector: React.FC<NodeInspectorProps> = ({
  node,
  edges,
  allNodes = [],
  onClose,
  onUpdateNode,
  onDeleteNode,
  onDeleteEdge,
  onSwitchToLibrary,
  isReadOnly = false,
}) => {
  const [copiedJson, setCopiedJson] = useState(false);
  const [newParamKey, setNewParamKey] = useState('');
  const [newParamVal, setNewParamVal] = useState('');
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [n8nCredentials, setN8nCredentials] = useState<N8nCredentialSummary[]>([]);
  const [nodeDef, setNodeDef] = useState<any>(null);

  useEffect(() => {
    let isMounted = true;
    getN8nCredentials().then((creds) => {
      if (isMounted) setN8nCredentials(creds || []);
    });
    return () => {
      isMounted = false;
    };
  }, []);

  useEffect(() => {
    let isMounted = true;
    if (node?.node_type) {
      getNodeDefinition(node.node_type).then((def) => {
        if (isMounted) setNodeDef(def);
      });
    } else {
      setNodeDef(null);
    }
    return () => {
      isMounted = false;
    };
  }, [node?.node_type]);

  const isTelegramNode = Boolean(
    node?.node_type?.toLowerCase().includes('telegram') ||
    node?.name?.toLowerCase().includes('telegram')
  );

  const isGoogleSheetsNode = Boolean(
    node?.node_type?.toLowerCase().includes('googlesheets') ||
    node?.name?.toLowerCase().includes('google sheets') ||
    node?.name?.toLowerCase().includes('sheets')
  );

  const [prevNodeId, setPrevNodeId] = useState(node?.id);
  const [telegramChatId, setTelegramChatId] = useState(() => {
    const current = String(node?.parameters?.chatId || '');
    return current.includes('<YOUR_TELEGRAM_CHAT_ID>') ? '' : current;
  });
  const [telegramChatIdSaved, setTelegramChatIdSaved] = useState(false);

  const [googleDocId, setGoogleDocId] = useState(() => {
    const current = String(node?.parameters?.documentId || node?.parameters?.sheetId || '');
    return current.includes('<YOUR_') ? '' : current;
  });
  const [googleSheetName, setGoogleSheetName] = useState(() => {
    const current = String(node?.parameters?.sheetName || '');
    return current.includes('<YOUR_') ? '' : current;
  });
  const [googleConfigSaved, setGoogleConfigSaved] = useState(false);

  const extractDocId = (val: string): string => {
    const trimmed = val.trim();
    const match = trimmed.match(/\/d\/([a-zA-Z0-9-_]+)/);
    return match ? match[1] : trimmed;
  };

  if (node?.id !== prevNodeId) {
    setPrevNodeId(node?.id);
    const currentChat = String(node?.parameters?.chatId || '');
    setTelegramChatId(currentChat.includes('<YOUR_TELEGRAM_CHAT_ID>') ? '' : currentChat);
    const currentDoc = String(node?.parameters?.documentId || node?.parameters?.sheetId || '');
    setGoogleDocId(currentDoc.includes('<YOUR_') ? '' : currentDoc);
    const currentSheet = String(node?.parameters?.sheetName || '');
    setGoogleSheetName(currentSheet.includes('<YOUR_') ? '' : currentSheet);
  }

  // Close on Escape key press
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  if (!node) return null;

  // Filter incoming and outgoing connections
  const incomingEdges = edges.filter((e) => e.target_id === node.id);
  const outgoingEdges = edges.filter((e) => e.source_id === node.id);

  const handleCopyJson = () => {
    navigator.clipboard.writeText(JSON.stringify(node, null, 2));
    setCopiedJson(true);
    setTimeout(() => setCopiedJson(false), 2000);
  };

  const handleNameChange = (newName: string) => {
    if (!onUpdateNode || isReadOnly) return;
    onUpdateNode({ ...node, name: newName });
  };

  const handleParamChange = (paramKey: string, rawVal: string) => {
    if (!onUpdateNode || isReadOnly) return;
    let parsed: any = rawVal;
    if (rawVal === 'true') parsed = true;
    else if (rawVal === 'false') parsed = false;
    else if (!isNaN(Number(rawVal)) && rawVal.trim() !== '') parsed = Number(rawVal);
    else if (rawVal.startsWith('{') || rawVal.startsWith('[')) {
      try {
        parsed = JSON.parse(rawVal);
      } catch {
        parsed = rawVal;
      }
    }

    const nextParams = { ...node.parameters, [paramKey]: parsed };
    onUpdateNode({ ...node, parameters: nextParams });
  };

  const handleRemoveParam = (paramKey: string) => {
    if (!onUpdateNode || isReadOnly) return;
    const nextParams = { ...node.parameters };
    delete nextParams[paramKey];
    onUpdateNode({ ...node, parameters: nextParams });
  };

  const handleAddParam = (e: React.FormEvent) => {
    e.preventDefault();
    if (!onUpdateNode || isReadOnly || !newParamKey.trim()) return;
    const key = newParamKey.trim();
    let val: any = newParamVal;
    if (newParamVal === 'true') val = true;
    else if (newParamVal === 'false') val = false;
    else if (!isNaN(Number(newParamVal)) && newParamVal.trim() !== '') val = Number(newParamVal);
    else if (newParamVal.startsWith('{') || newParamVal.startsWith('[')) {
      try {
        val = JSON.parse(newParamVal);
      } catch {
        val = newParamVal;
      }
    }

    const nextParams = { ...node.parameters, [key]: val };
    onUpdateNode({ ...node, parameters: nextParams });
    setNewParamKey('');
    setNewParamVal('');
  };

  const handlePolicyChange = (field: string, val: any) => {
    if (!onUpdateNode || isReadOnly) return;
    const currentPolicy = node.execution_policy || {
      continue_on_fail: false,
      retry_on_fail: false,
      max_tries: 3,
      wait_between_tries: 1000,
    };
    const nextPolicy = { ...currentPolicy, [field]: val };
    onUpdateNode({ ...node, execution_policy: nextPolicy });
  };

  const getNodeNameById = (id: string) => {
    const found = allNodes.find((n) => n.id === id);
    return found ? found.name : id;
  };

  // Derive human-friendly purpose
  const getFriendlyRole = () => {
    const lowerType = (node.node_type || '').toLowerCase();
    if (lowerType.includes('trigger') || lowerType.includes('webhook')) {
      return 'Trigger node that initiates the workflow when an event occurs.';
    }
    if (lowerType.includes('if') || lowerType.includes('switch') || lowerType.includes('filter')) {
      return 'Conditional logic node that routes data along different paths.';
    }
    if (lowerType.includes('mail') || lowerType.includes('slack') || lowerType.includes('telegram') || lowerType.includes('discord')) {
      return 'Notification / messaging node.';
    }
    if (lowerType.includes('sheet') || lowerType.includes('postgres') || lowerType.includes('database')) {
      return 'Data storage / persistence node.';
    }
    return 'Action node performing automation task.';
  };

  // Detect if credentials needed
  const requiresCredentials = Boolean(
    (node.credentials && Object.keys(node.credentials).length > 0) ||
    node.node_type?.includes('slack') ||
    node.node_type?.includes('telegram') ||
    node.node_type?.includes('gmail') ||
    node.node_type?.includes('github') ||
    node.node_type?.includes('google')
  );

  const renderCredentialControl = (credType: string, credDisplayName: string, setupInstructions: string) => {
    const rawVal = node?.credentials?.[credType];
    const currentId = typeof rawVal === 'object' && rawVal ? String(rawVal.id || '') : (typeof rawVal === 'string' ? rawVal : '');
    const currentName = typeof rawVal === 'object' && rawVal ? String(rawVal.name || '') : '';

    const matchingN8nCreds = n8nCredentials.filter((c) => c.type === credType);
    const isConfiguredInN8n = matchingN8nCreds.some((c) => c.id === currentId);
    const isInvalidId = Boolean(currentId && n8nCredentials.length > 0 && !isConfiguredInN8n);
    const isMissing = !currentId && !rawVal;

    let statusVariant = 'info';
    let statusText = 'Referenced (Unverified)';
    if (isMissing) {
      statusVariant = 'error';
      statusText = 'Missing';
    } else if (isInvalidId) {
      statusVariant = 'error';
      statusText = 'Invalid ID';
    } else if (isConfiguredInN8n) {
      statusVariant = 'success';
      statusText = 'Configured in n8n';
    }

    return (
      <div
        key={credType}
        style={{
          display: 'flex',
          flexDirection: 'column',
          gap: '8px',
          padding: '10px 12px',
          backgroundColor: 'var(--bg-surface-elevated, #1F2937)',
          border: '1px solid var(--border-subtle)',
          borderRadius: 'var(--radius-sm)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <KeyRound size={13} style={{ color: 'var(--brand-primary)' }} />
            <span style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-primary)' }}>{credDisplayName}</span>
          </div>
          <span
            style={{
              fontSize: '10px',
              fontWeight: 600,
              padding: '2px 6px',
              borderRadius: 'var(--radius-xs, 3px)',
              backgroundColor:
                statusVariant === 'success'
                  ? 'rgba(34, 197, 94, 0.15)'
                  : statusVariant === 'error'
                    ? 'rgba(239, 68, 68, 0.15)'
                    : 'rgba(59, 130, 246, 0.15)',
              color:
                statusVariant === 'success'
                  ? 'var(--state-success, #22C55E)'
                  : statusVariant === 'error'
                    ? 'var(--state-danger, #EF4444)'
                    : 'var(--brand-primary, #3B82F6)',
            }}
          >
            {statusText}
          </span>
        </div>

        {matchingN8nCreds.length > 0 ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
            <label style={{ fontSize: '11px', color: 'var(--text-tertiary)' }}>Select credential from connected n8n:</label>
            <select
              value={currentId || ''}
              disabled={isReadOnly}
              onChange={(e) => {
                const selectedId = e.target.value;
                const matched = matchingN8nCreds.find((c) => c.id === selectedId);
                const updated = {
                  ...(node.credentials || {}),
                };
                if (selectedId) {
                  updated[credType] = { id: selectedId, name: matched?.name || credDisplayName };
                } else {
                  delete updated[credType];
                }
                onUpdateNode?.({ ...node, credentials: updated });
              }}
              style={{
                padding: '6px 8px',
                fontSize: '12px',
                backgroundColor: 'var(--bg-app)',
                border: '1px solid var(--border-default)',
                borderRadius: 'var(--radius-sm)',
                color: 'var(--text-primary)',
              }}
            >
              <option value="">-- Select an existing credential --</option>
              {matchingN8nCreds.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name} (ID: {c.id})
                </option>
              ))}
            </select>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
            <label style={{ fontSize: '11px', color: 'var(--text-tertiary)' }}>Credential Reference ID in n8n:</label>
            <input
              type="text"
              placeholder="e.g. 1 or my-cred-id"
              value={currentId || ''}
              disabled={isReadOnly}
              onChange={(e) => {
                const val = e.target.value.trim();
                const updated = {
                  ...(node.credentials || {}),
                };
                if (val) {
                  updated[credType] = { id: val, name: currentName || credDisplayName };
                } else {
                  delete updated[credType];
                }
                onUpdateNode?.({ ...node, credentials: updated });
              }}
              style={{
                padding: '5px 8px',
                fontSize: '12px',
                backgroundColor: 'var(--bg-app)',
                border: '1px solid var(--border-default)',
                borderRadius: 'var(--radius-sm)',
                color: 'var(--text-primary)',
              }}
            />
          </div>
        )}

        <div style={{ fontSize: '11px', color: 'var(--text-secondary)', lineHeight: 1.4 }}>
          {setupInstructions}
        </div>
      </div>
    );
  };

  return (
    <aside
      className="node-inspector-panel"
      role="region"
      aria-label={`Inspector for ${node.name}`}
      style={{
        width: '380px',
        maxWidth: '100%',
        backgroundColor: 'var(--bg-surface)',
        borderLeft: '1px solid var(--border-default)',
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        overflowY: 'auto',
        color: 'var(--text-primary)',
        boxShadow: 'var(--shadow-lg)',
        zIndex: 10,
      }}
    >
      {/* Top Panel Mode Navigation Bar */}
      <div
        style={{
          padding: '10px 16px',
          borderBottom: '1px solid var(--border-subtle)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          backgroundColor: 'var(--bg-surface-subtle)',
        }}
      >
        {onSwitchToLibrary ? (
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={onSwitchToLibrary}
            style={{ fontSize: '12px', padding: '3px 8px', display: 'flex', alignItems: 'center', gap: '5px', color: 'var(--brand-primary)' }}
          >
            <ArrowLeft size={13} />
            <span>Node Library</span>
          </button>
        ) : (
          <span style={{ fontSize: '11px', fontWeight: 600, color: 'var(--text-tertiary)', textTransform: 'uppercase' }}>
            Node Properties
          </span>
        )}

        <button
          type="button"
          className="btn btn-ghost btn-sm"
          onClick={onClose}
          aria-label="Close Inspector"
          style={{ padding: '4px', color: 'var(--text-secondary)' }}
        >
          <X size={15} />
        </button>
      </div>

      {/* Header */}
      <div
        style={{
          padding: '16px',
          borderBottom: '1px solid var(--border-subtle)',
          display: 'flex',
          alignItems: 'flex-start',
          justifyContent: 'space-between',
          gap: '12px',
        }}
      >
        <div style={{ flex: 1, minWidth: 0 }}>
          <label
            htmlFor="node-name-input"
            style={{ fontSize: '11px', fontWeight: 600, color: 'var(--text-tertiary)', textTransform: 'uppercase' }}
          >
            Node Name
          </label>
          <input
            id="node-name-input"
            type="text"
            value={node.name}
            disabled={isReadOnly}
            onChange={(e) => handleNameChange(e.target.value)}
            style={{
              width: '100%',
              padding: '6px 10px',
              fontSize: '14px',
              fontWeight: 600,
              color: 'var(--text-primary)',
              backgroundColor: isReadOnly ? 'transparent' : 'var(--bg-surface-subtle)',
              border: isReadOnly ? '1px solid transparent' : '1px solid var(--border-default)',
              borderRadius: 'var(--radius-sm)',
              marginTop: '4px',
            }}
            placeholder="Node display name..."
          />
          <div
            style={{
              fontSize: '12px',
              color: 'var(--text-secondary)',
              marginTop: '6px',
              lineHeight: 1.4,
            }}
          >
            {getFriendlyRole()}
          </div>
        </div>
      </div>

      {/* Main Content Area */}
      <div style={{ flex: 1, padding: '16px', display: 'flex', flexDirection: 'column', gap: '20px', overflowY: 'auto' }}>
        {/* General Credentials Section */}
        {requiresCredentials && !isTelegramNode && !isGoogleSheetsNode && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <KeyRound size={14} style={{ color: 'var(--brand-primary)' }} />
              <span style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-primary)' }}>
                Node Credentials
              </span>
            </div>
            {(() => {
              const expectedList = nodeDef?.expected_credentials || nodeDef?.credentials || [];
              const credTypes = expectedList.length > 0
                ? expectedList.map((c: any) => c.name)
                : Object.keys(node.credentials || {});
              if (credTypes.length === 0) {
                return (
                  <div style={{ fontSize: '12px', color: 'var(--text-secondary)', padding: '8px 10px', backgroundColor: 'var(--bg-surface-subtle)', borderRadius: 'var(--radius-sm)' }}>
                    This node connects to an external service. When deployed to n8n, configure its credentials in your n8n workspace.
                  </div>
                );
              }
              return credTypes.map((ctype: string) => {
                return renderCredentialControl(ctype, ctype, `Configure '${ctype}' in n8n under Credentials → New Credential → '${ctype}'.`);
              });
            })()}
          </div>
        )}

        {/* Dedicated Secure Telegram Configuration Card */}
        {isTelegramNode && (
          <div
            style={{
              padding: '14px',
              backgroundColor: 'rgba(234, 88, 12, 0.04)',
              border: '1px solid rgba(234, 88, 12, 0.3)',
              borderRadius: 'var(--radius-sm)',
              display: 'flex',
              flexDirection: 'column',
              gap: '12px',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <span style={{ fontSize: '13px', fontWeight: 600, color: 'var(--brand-primary)' }}>
                Telegram Configuration
              </span>
              <span style={{ fontSize: '11px', color: 'var(--text-tertiary)', fontFamily: 'var(--font-mono)' }}>
                sendMessage
              </span>
            </div>

            {/* 1. Telegram Chat ID (Workflow Parameter) */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              <label htmlFor="telegram-chat-id-input" style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-primary)' }}>
                Telegram Chat ID (Workflow Parameter)
              </label>
              <div style={{ display: 'flex', gap: '6px' }}>
                <input
                  id="telegram-chat-id-input"
                  type="text"
                  value={telegramChatId}
                  onChange={(e) => setTelegramChatId(e.target.value)}
                  placeholder="e.g. 123456789 or @mychannel"
                  disabled={isReadOnly}
                  style={{
                    flex: 1,
                    padding: '6px 10px',
                    fontSize: '13px',
                    backgroundColor: 'var(--bg-app)',
                    border: '1px solid var(--border-default)',
                    borderRadius: 'var(--radius-sm)',
                    color: 'var(--text-primary)',
                  }}
                />
                {!isReadOnly && (
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    onClick={() => {
                      const clean = telegramChatId.trim();
                      handleParamChange('chatId', clean || "={{ '<YOUR_TELEGRAM_CHAT_ID>' }}");
                      setTelegramChatIdSaved(true);
                      setTimeout(() => setTelegramChatIdSaved(false), 2000);
                    }}
                    style={{ fontSize: '12px' }}
                  >
                    {telegramChatIdSaved ? 'Saved' : 'Apply'}
                  </button>
                )}
              </div>
              <div style={{ fontSize: '11px', color: 'var(--text-tertiary)', lineHeight: 1.4 }}>
                Numeric ID (e.g. 123456789) or public channel @handle.
                <br />
                <span style={{ fontStyle: 'italic' }}>
                  Syntax validation verifies format only; it does not confirm the chat exists or that the bot can send messages.
                </span>
              </div>
            </div>

            {/* 2. Telegram Bot Token Credential */}
            <div style={{ paddingTop: '8px', borderTop: '1px solid var(--border-subtle)' }}>
              {renderCredentialControl(
                'telegramApi',
                'Telegram API',
                'Private secret issued by @BotFather. Enter your bot token in your n8n workspace under Credentials → New Credential → Telegram API.'
              )}
            </div>
          </div>
        )}

        {/* Dedicated Google Sheets Configuration Card */}
        {isGoogleSheetsNode && (
          <div
            style={{
              padding: '14px',
              backgroundColor: 'rgba(234, 88, 12, 0.04)',
              border: '1px solid rgba(234, 88, 12, 0.3)',
              borderRadius: 'var(--radius-sm)',
              display: 'flex',
              flexDirection: 'column',
              gap: '12px',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <span style={{ fontSize: '13px', fontWeight: 600, color: 'var(--brand-primary)' }}>
                Google Sheets Configuration
              </span>
              <span style={{ fontSize: '11px', color: 'var(--text-tertiary)', fontFamily: 'var(--font-mono)' }}>
                {node.node_type?.split('.').pop() || 'googleSheets'}
              </span>
            </div>

            {/* 1. Document / Spreadsheet ID */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              <label htmlFor="google-doc-id-input" style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-primary)' }}>
                Spreadsheet ID or URL (Required)
              </label>
              <div style={{ display: 'flex', gap: '6px' }}>
                <input
                  id="google-doc-id-input"
                  type="text"
                  value={googleDocId}
                  onChange={(e) => setGoogleDocId(e.target.value)}
                  placeholder="Paste Spreadsheet ID or full Google Sheet URL"
                  disabled={isReadOnly}
                  style={{
                    flex: 1,
                    padding: '6px 10px',
                    fontSize: '13px',
                    backgroundColor: 'var(--bg-app)',
                    border: '1px solid var(--border-default)',
                    borderRadius: 'var(--radius-sm)',
                    color: 'var(--text-primary)',
                  }}
                />
                {!isReadOnly && (
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    onClick={() => {
                      const extracted = extractDocId(googleDocId);
                      setGoogleDocId(extracted);
                      const cleanSheet = googleSheetName.trim() || 'Sheet1';
                      if (onUpdateNode) {
                        onUpdateNode({
                          ...node,
                          parameters: {
                            ...node.parameters,
                            documentId: extracted || "={{ '<YOUR_SPREADSHEET_ID>' }}",
                            sheetName: cleanSheet,
                          },
                        });
                      }
                      setGoogleConfigSaved(true);
                      setTimeout(() => setGoogleConfigSaved(false), 2000);
                    }}
                    style={{ fontSize: '12px' }}
                  >
                    {googleConfigSaved ? 'Saved' : 'Apply'}
                  </button>
                )}
              </div>
              <div style={{ fontSize: '11px', color: 'var(--text-tertiary)', lineHeight: 1.4 }}>
                Found in your Google Sheet URL: <code>docs.google.com/spreadsheets/d/<strong>SPREADSHEET_ID</strong>/edit</code>. You can paste the full URL; the ID will be automatically extracted.
              </div>
            </div>

            {/* 2. Sheet / Tab Name */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              <label htmlFor="google-sheet-name-input" style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-primary)' }}>
                Sheet / Tab Name
              </label>
              <input
                id="google-sheet-name-input"
                type="text"
                value={googleSheetName}
                onChange={(e) => setGoogleSheetName(e.target.value)}
                placeholder="e.g. Sheet1"
                disabled={isReadOnly}
                style={{
                  padding: '6px 10px',
                  fontSize: '13px',
                  backgroundColor: 'var(--bg-app)',
                  border: '1px solid var(--border-default)',
                  borderRadius: 'var(--radius-sm)',
                  color: 'var(--text-primary)',
                }}
              />
              <div style={{ fontSize: '11px', color: 'var(--text-tertiary)', lineHeight: 1.4 }}>
                The name of the tab in your spreadsheet (defaults to <strong>Sheet1</strong>).
              </div>
            </div>

            {/* 3. Google Sheets Credential */}
            <div style={{ paddingTop: '8px', borderTop: '1px solid var(--border-subtle)' }}>
              {(() => {
                const isServiceAccount = node?.parameters?.authentication === 'serviceAccount';
                const sheetsCredType = isServiceAccount
                  ? 'googleApi'
                  : node?.node_type?.includes('Trigger')
                    ? 'googleSheetsTriggerOAuth2Api'
                    : 'googleSheetsOAuth2Api';
                const sheetsCredTitle = isServiceAccount
                  ? 'Google Service Account API'
                  : node?.node_type?.includes('Trigger')
                    ? 'Google Sheets Trigger OAuth2 API'
                    : 'Google Sheets OAuth2 API';
                const sheetsGuidance = isServiceAccount
                  ? 'Upload your Google Service Account key JSON in your n8n workspace under Credentials → New Credential → Google API.'
                  : `Connect your Google account via OAuth2 in your n8n workspace under Credentials → New Credential → ${sheetsCredTitle}.`;
                return renderCredentialControl(sheetsCredType, sheetsCredTitle, sheetsGuidance);
              })()}
            </div>
          </div>
        )}

        {/* Parameters Section */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <Sliders size={14} style={{ color: 'var(--brand-primary)' }} />

            <span style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-primary)' }}>
              Parameters ({Object.keys(node.parameters || {}).length})
            </span>
          </div>

          {node.parameters && Object.keys(node.parameters).length > 0 ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {Object.entries(node.parameters).map(([key, val]) => (
                <div
                  key={key}
                  style={{
                    padding: '8px 10px',
                    backgroundColor: 'var(--bg-surface-subtle)',
                    border: '1px solid var(--border-subtle)',
                    borderRadius: 'var(--radius-sm)',
                  }}
                >
                  <div
                    style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                      marginBottom: '4px',
                    }}
                  >
                    <span
                      style={{
                        fontSize: '12px',
                        fontWeight: 600,
                        color: 'var(--text-primary)',
                      }}
                    >
                      {key}
                    </span>
                    {!isReadOnly && (
                      <button
                        type="button"
                        onClick={() => handleRemoveParam(key)}
                        title={`Remove parameter '${key}'`}
                        style={{
                          background: 'transparent',
                          border: 'none',
                          color: 'var(--text-tertiary)',
                          cursor: 'pointer',
                          padding: '2px',
                        }}
                      >
                        <Trash2 size={12} />
                      </button>
                    )}
                  </div>

                  {typeof val === 'boolean' ? (
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginTop: '4px' }}>
                      <input
                        type="checkbox"
                        checked={val}
                        disabled={isReadOnly}
                        onChange={(e) => handleParamChange(key, e.target.checked ? 'true' : 'false')}
                        id={`param-check-${key}`}
                      />
                      <label htmlFor={`param-check-${key}`} style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
                        {val ? 'Enabled' : 'Disabled'}
                      </label>
                    </div>
                  ) : (
                    <input
                      type="text"
                      value={typeof val === 'object' && val !== null ? JSON.stringify(val) : String(val)}
                      disabled={isReadOnly}
                      onChange={(e) => handleParamChange(key, e.target.value)}
                      style={{
                        width: '100%',
                        padding: '5px 8px',
                        fontSize: '12px',
                        backgroundColor: 'var(--bg-app)',
                        border: '1px solid var(--border-default)',
                        borderRadius: 'var(--radius-sm)',
                        color: 'var(--text-primary)',
                      }}
                    />
                  )}
                </div>
              ))}
            </div>
          ) : (
            <div style={{ fontSize: '12px', color: 'var(--text-tertiary)', fontStyle: 'italic' }}>
              No parameters configured for this node.
            </div>
          )}

          {/* Add Parameter */}
          {!isReadOnly && (
            <form
              onSubmit={handleAddParam}
              style={{
                display: 'flex',
                flexDirection: 'column',
                gap: '8px',
                marginTop: '4px',
                padding: '10px',
                backgroundColor: 'var(--bg-surface-subtle)',
                border: '1px dashed var(--border-default)',
                borderRadius: 'var(--radius-sm)',
              }}
            >
              <div style={{ fontSize: '11px', fontWeight: 600, color: 'var(--text-secondary)' }}>
                Add Custom Parameter
              </div>
              <div style={{ display: 'flex', gap: '6px' }}>
                <input
                  type="text"
                  placeholder="Key"
                  value={newParamKey}
                  onChange={(e) => setNewParamKey(e.target.value)}
                  style={{
                    flex: 1,
                    padding: '4px 8px',
                    fontSize: '12px',
                    backgroundColor: 'var(--bg-app)',
                    border: '1px solid var(--border-default)',
                    borderRadius: 'var(--radius-sm)',
                    color: 'var(--text-primary)',
                  }}
                />
                <input
                  type="text"
                  placeholder="Value"
                  value={newParamVal}
                  onChange={(e) => setNewParamVal(e.target.value)}
                  style={{
                    flex: 1,
                    padding: '4px 8px',
                    fontSize: '12px',
                    backgroundColor: 'var(--bg-app)',
                    border: '1px solid var(--border-default)',
                    borderRadius: 'var(--radius-sm)',
                    color: 'var(--text-primary)',
                  }}
                />
              </div>
              <Button
                type="submit"
                variant="secondary"
                size="sm"
                disabled={!newParamKey.trim()}
                icon={<Plus size={12} />}
              >
                Add
              </Button>
            </form>
          )}
        </div>

        {/* Connections Section */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <GitBranch size={14} style={{ color: 'var(--brand-primary)' }} />
            <span style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-primary)' }}>
              Connections
            </span>
          </div>

          <div style={{ fontSize: '12px', display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <div style={{ color: 'var(--text-secondary)', fontWeight: 600, fontSize: '11px' }}>
              Incoming ({incomingEdges.length}):
            </div>
            {incomingEdges.length > 0 ? (
              incomingEdges.map((e, idx) => (
                <div
                  key={idx}
                  style={{
                    padding: '6px 8px',
                    backgroundColor: 'var(--bg-surface-subtle)',
                    borderRadius: 'var(--radius-sm)',
                    fontSize: '12px',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                  }}
                >
                  <span>From: <strong>{getNodeNameById(e.source_id)}</strong></span>
                  {!isReadOnly && onDeleteEdge && (
                    <button
                      type="button"
                      onClick={() => onDeleteEdge(e.source_id, e.target_id, e.source_output_index, e.target_input_index)}
                      title="Disconnect"
                      style={{
                        background: 'transparent',
                        border: 'none',
                        color: 'var(--state-error)',
                        cursor: 'pointer',
                        padding: '2px',
                      }}
                    >
                      <Trash2 size={12} />
                    </button>
                  )}
                </div>
              ))
            ) : (
              <span style={{ color: 'var(--text-tertiary)', fontStyle: 'italic', fontSize: '11px' }}>
                First step / trigger node.
              </span>
            )}

            <div style={{ color: 'var(--text-secondary)', fontWeight: 600, fontSize: '11px', marginTop: '4px' }}>
              Outgoing ({outgoingEdges.length}):
            </div>
            {outgoingEdges.length > 0 ? (
              outgoingEdges.map((e, idx) => (
                <div
                  key={idx}
                  style={{
                    padding: '6px 8px',
                    backgroundColor: 'var(--bg-surface-subtle)',
                    borderRadius: 'var(--radius-sm)',
                    fontSize: '12px',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                  }}
                >
                  <span>To: <strong>{getNodeNameById(e.target_id)}</strong></span>
                  {!isReadOnly && onDeleteEdge && (
                    <button
                      type="button"
                      onClick={() => onDeleteEdge(e.source_id, e.target_id, e.source_output_index, e.target_input_index)}
                      title="Disconnect"
                      style={{
                        background: 'transparent',
                        border: 'none',
                        color: 'var(--state-error)',
                        cursor: 'pointer',
                        padding: '2px',
                      }}
                    >
                      <Trash2 size={12} />
                    </button>
                  )}
                </div>
              ))
            ) : (
              <span style={{ color: 'var(--text-tertiary)', fontStyle: 'italic', fontSize: '11px' }}>
                Final step in path.
              </span>
            )}
          </div>
        </div>

        {/* Collapsible Advanced Settings Section */}
        <div
          style={{
            borderTop: '1px solid var(--border-subtle)',
            paddingTop: '12px',
            marginTop: '4px',
          }}
        >
          <button
            type="button"
            onClick={() => setShowAdvanced((prev) => !prev)}
            style={{
              width: '100%',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              background: 'transparent',
              border: 'none',
              padding: '6px 0',
              cursor: 'pointer',
              color: 'var(--text-secondary)',
              fontSize: '12px',
              fontWeight: 600,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <Settings size={13} />
              <span>Advanced Details &amp; Policies</span>
            </div>
            {showAdvanced ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          </button>

          {showAdvanced && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '14px', marginTop: '10px' }}>
              {/* Technical identifiers */}
              <div
                style={{
                  backgroundColor: 'var(--bg-surface-subtle)',
                  borderRadius: 'var(--radius-sm)',
                  padding: '8px 10px',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '4px',
                  fontSize: '11px',
                  fontFamily: 'var(--font-mono)',
                  color: 'var(--text-secondary)',
                }}
              >
                <div>ID: {node.id}</div>
                <div>Type: {node.node_type}</div>
                <div>Version: v{node.type_version || 1}</div>
              </div>

              {/* Execution Policies */}
              <div
                style={{
                  backgroundColor: 'var(--bg-surface-subtle)',
                  borderRadius: 'var(--radius-sm)',
                  padding: '10px 12px',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '10px',
                  fontSize: '12px',
                }}
              >
                <div style={{ fontWeight: 600, color: 'var(--text-primary)', fontSize: '12px' }}>
                  Execution Policies
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <label htmlFor="policy-continue-fail" style={{ color: 'var(--text-secondary)', cursor: 'pointer' }}>
                    Continue on Fail
                  </label>
                  <input
                    id="policy-continue-fail"
                    type="checkbox"
                    disabled={isReadOnly}
                    checked={node.execution_policy?.continue_on_fail ?? false}
                    onChange={(e) => handlePolicyChange('continue_on_fail', e.target.checked)}
                  />
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <label htmlFor="policy-retry-fail" style={{ color: 'var(--text-secondary)', cursor: 'pointer' }}>
                    Retry on Fail
                  </label>
                  <input
                    id="policy-retry-fail"
                    type="checkbox"
                    disabled={isReadOnly}
                    checked={node.execution_policy?.retry_on_fail ?? false}
                    onChange={(e) => handlePolicyChange('retry_on_fail', e.target.checked)}
                  />
                </div>
              </div>

              {/* Raw JSON inspection */}
              <div>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '6px' }}>
                  <span style={{ fontSize: '11px', fontWeight: 600, color: 'var(--text-secondary)' }}>
                    Raw Node JSON
                  </span>
                  <button
                    type="button"
                    onClick={handleCopyJson}
                    className="btn btn-secondary btn-sm"
                    style={{ fontSize: '11px', padding: '3px 8px' }}
                  >
                    {copiedJson ? <Check size={11} /> : <Copy size={11} />}
                    <span>{copiedJson ? 'Copied' : 'Copy'}</span>
                  </button>
                </div>
                <pre
                  style={{
                    backgroundColor: 'var(--bg-app)',
                    border: '1px solid var(--border-subtle)',
                    borderRadius: 'var(--radius-sm)',
                    padding: '8px',
                    fontSize: '11px',
                    fontFamily: 'var(--font-mono)',
                    color: 'var(--text-secondary)',
                    maxHeight: '160px',
                    overflowY: 'auto',
                    margin: 0,
                  }}
                >
                  {JSON.stringify(node, null, 2)}
                </pre>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Bottom Node Actions (Delete Node) */}
      {!isReadOnly && onDeleteNode && (
        <div
          style={{
            padding: '12px 16px',
            borderTop: '1px solid var(--border-subtle)',
            backgroundColor: 'var(--bg-surface-subtle)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <span style={{ fontSize: '11px', color: 'var(--text-tertiary)', fontFamily: 'var(--font-mono)' }}>
            {node.id}
          </span>
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={() => onDeleteNode(node.id)}
            style={{
              color: 'var(--state-error)',
              fontSize: '12px',
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              padding: '4px 8px',
            }}
          >
            <Trash2 size={13} />
            <span>Delete node</span>
          </button>
        </div>
      )}
    </aside>
  );
};
