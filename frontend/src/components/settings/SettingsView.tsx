import React, { useState, useEffect, useCallback } from 'react';
import { Badge } from '../ui/Badge';
import { Button } from '../ui/Button';
import type { AppTheme } from '../../types';
import {
  Server,
  Cpu,
  Database,
  Sun,
  Moon,
  RefreshCw,
  CheckCircle2,
  AlertTriangle,
  XCircle,
} from 'lucide-react';
import { OrbitLoader } from '../common/OrbitLoader';
import {
  getAuthHeaders,
  getLLMStatus,
  testLLMConnection,
  type LLMStatusData,
  type LLMTestData,
} from '../../api/conversations';

export type N8nConnectionState =
  | 'idle'
  | 'loading'
  | 'connected'
  | 'not_configured'
  | 'unauthorized'
  | 'unreachable'
  | 'backend_offline'
  | 'error';

export interface N8nStatusResponseData {
  status: 'connected' | 'not_configured' | 'unauthorized' | 'unreachable' | 'error';
  message: string;
}

interface SettingsViewProps {
  theme: AppTheme;
  onThemeChange: (theme: AppTheme) => void;
}

export const SettingsView: React.FC<SettingsViewProps> = ({
  theme,
  onThemeChange,
}) => {
  const [connectionState, setConnectionState] = useState<N8nConnectionState>('idle');
  const [statusMessage, setStatusMessage] = useState<string>(
    'Testing connectivity to n8n REST API...'
  );
  const [lastChecked, setLastChecked] = useState<string | null>(null);

  const [llmStatus, setLlmStatus] = useState<LLMStatusData | null>(null);
  const [isTestingLLM, setIsTestingLLM] = useState<boolean>(false);
  const [llmTestResult, setLlmTestResult] = useState<LLMTestData | null>(null);
  const [llmTestError, setLlmTestError] = useState<string | null>(null);

  const checkConnection = useCallback(async () => {
    setConnectionState('loading');
    setStatusMessage('Checking n8n instance connectivity and authentication...');
    try {
      const response = await fetch('/api/v1/integrations/n8n/status', {
        headers: getAuthHeaders(),
      });

      if (!response.ok) {
        setConnectionState('error');
        setStatusMessage(`Backend returned HTTP status ${response.status}. Verify server configuration.`);
        setLastChecked(new Date().toLocaleTimeString());
        return;
      }

      const data: N8nStatusResponseData = await response.json();
      setConnectionState(data.status);
      setStatusMessage(data.message);
      setLastChecked(new Date().toLocaleTimeString());
    } catch {
      setConnectionState('backend_offline');
      setStatusMessage(
        'FastAPI backend server is not running or unreachable at http://127.0.0.1:8000. Start it with uvicorn.'
      );
      setLastChecked(new Date().toLocaleTimeString());
    }
  }, []);

  useEffect(() => {
    let isMounted = true;

    async function loadInitialStatus() {
      try {
        const response = await fetch('/api/v1/integrations/n8n/status', {
          headers: getAuthHeaders(),
        });

        if (!isMounted) return;

        if (!response.ok) {
          setConnectionState('error');
          setStatusMessage(`Backend returned HTTP status ${response.status}. Verify server configuration.`);
          setLastChecked(new Date().toLocaleTimeString());
          return;
        }

        const data: N8nStatusResponseData = await response.json();
        if (!isMounted) return;
        setConnectionState(data.status);
        setStatusMessage(data.message);
        setLastChecked(new Date().toLocaleTimeString());
      } catch {
        if (!isMounted) return;
        setConnectionState('backend_offline');
        setStatusMessage(
          'FastAPI backend server is not running or unreachable at http://127.0.0.1:8000. Start it with uvicorn.'
        );
        setLastChecked(new Date().toLocaleTimeString());
      }

      try {
        const llmData = await getLLMStatus();
        if (isMounted) {
          setLlmStatus(llmData);
        }
      } catch {
        // Ignored if backend offline
      }
    }

    loadInitialStatus();

    return () => {
      isMounted = false;
    };
  }, []);

  const handleTestLLM = useCallback(async () => {
    setIsTestingLLM(true);
    setLlmTestError(null);
    setLlmTestResult(null);
    try {
      const res = await testLLMConnection();
      setLlmTestResult(res);
      const updatedStatus = await getLLMStatus().catch(() => null);
      if (updatedStatus) {
        setLlmStatus(updatedStatus);
      }
    } catch (err: any) {
      setLlmTestError(err.message || 'Failed to connect to LLM provider');
    } finally {
      setIsTestingLLM(false);
    }
  }, []);


  const renderStatusBadge = () => {
    switch (connectionState) {
      case 'loading':
        return <Badge variant="info">Checking...</Badge>;
      case 'connected':
        return <Badge variant="success">Connected & Authenticated</Badge>;
      case 'not_configured':
        return <Badge variant="warning">API Key Not Configured</Badge>;
      case 'unauthorized':
        return <Badge variant="error">Invalid / Unauthorized API Key</Badge>;
      case 'unreachable':
        return <Badge variant="error">Instance Unreachable</Badge>;
      case 'backend_offline':
        return <Badge variant="error">Backend Offline</Badge>;
      case 'error':
        return <Badge variant="error">Connection Error</Badge>;
      case 'idle':
      default:
        return <Badge variant="neutral">Not Checked</Badge>;
    }
  };

  const renderStatusIcon = () => {
    switch (connectionState) {
      case 'loading':
        return <OrbitLoader size="xs" color="var(--state-info)" ariaLabel="Checking connection..." />;
      case 'connected':
        return <CheckCircle2 size={16} color="var(--state-success)" />;
      case 'not_configured':
        return <AlertTriangle size={16} color="var(--state-warning)" />;
      case 'unauthorized':
      case 'unreachable':
      case 'backend_offline':
      case 'error':
        return <XCircle size={16} color="var(--state-error)" />;
      default:
        return <Server size={16} color="var(--text-tertiary)" />;
    }
  };

  return (
    <div>
      <div className="workspace-header">
        <h1 className="workspace-title">Settings</h1>
        <p className="workspace-subtitle">
          Configure AI providers, test n8n connectivity, review local access controls, and customize application preferences.
        </p>
      </div>

      <div className="settings-grid">
        {/* Section 1: AI Provider & Model */}
        <div className="settings-card">
          <div className="settings-card-header">
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <Cpu size={16} color="var(--brand-primary)" />
                <h2 className="settings-card-title">1. AI Provider &amp; Model</h2>
              </div>
              <Button
                variant="secondary"
                size="sm"
                onClick={handleTestLLM}
                disabled={isTestingLLM}
                icon={isTestingLLM ? <OrbitLoader size="inline" color="currentColor" /> : <RefreshCw size={13} />}
              >
                {isTestingLLM ? 'Testing Connection...' : 'Test LLM Connection'}
              </Button>
            </div>
            <p className="settings-card-desc">
              Provider routing uses a free-first hierarchy. Raw API keys are kept isolated on
              the backend and are never sent to the browser.
            </p>
          </div>

          <table className="status-table">
            <thead>
              <tr>
                <th>Provider</th>
                <th>Role</th>
                <th>Configured Model</th>
                <th>Architecture</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td style={{ fontWeight: 600 }}>OpenRouter</td>
                <td>Primary Provider</td>
                <td style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--brand-primary)' }}>
                  {llmStatus?.primary_model || 'nvidia/nemotron-3-super-120b-a12b:free'}
                </td>
                <td style={{ fontFamily: 'var(--font-mono)', fontSize: '12px' }}>
                  {llmStatus ? `${llmStatus.healthy_keys_count}/${llmStatus.total_keys_count} Healthy Keys` : '4-Key Pool'}
                </td>
                <td>
                  {llmStatus?.is_primary_configured ? (
                    <Badge variant="success">Configured &amp; Active</Badge>
                  ) : (
                    <Badge variant="neutral">Configured on Backend</Badge>
                  )}
                </td>
              </tr>
              <tr>
                <td style={{ fontWeight: 600 }}>Groq</td>
                <td>Optional Fallback</td>
                <td style={{ fontFamily: 'var(--font-mono)', fontSize: '11px' }}>
                  {llmStatus?.fallback_model || 'llama-3.3-70b-versatile'}
                </td>
                <td style={{ fontFamily: 'var(--font-mono)', fontSize: '12px' }}>
                  Single Key Fallback
                </td>
                <td>
                  {llmStatus?.is_fallback_configured ? (
                    <Badge variant="success">Active Fallback</Badge>
                  ) : (
                    <Badge variant="neutral">Optional / Unconfigured</Badge>
                  )}
                </td>
              </tr>
            </tbody>
          </table>

          {llmStatus?.fallback_models && llmStatus.fallback_models.length > 0 && (
            <div style={{ marginTop: '12px', fontSize: '12px', color: 'var(--text-secondary)' }}>
              <strong>Configured OpenRouter Fallbacks:</strong>{' '}
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px' }}>
                {llmStatus.fallback_models.join(', ')}
              </span>
            </div>
          )}

          {/* Live LLM Test Result Box */}
          {llmTestResult && (
            <div
              className="settings-connection-status-box"
              style={{ marginTop: '14px' }}
              role="status"
              aria-live="polite"
            >
              <div className="settings-connection-status-row">
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  {llmTestResult.status === 'connected' ? (
                    <CheckCircle2 size={16} color="var(--success-text)" />
                  ) : (
                    <AlertTriangle size={16} color="var(--warning-text)" />
                  )}
                  <span style={{ fontWeight: 600, fontSize: '13px', color: 'var(--text-primary)' }}>
                    {llmTestResult.status === 'connected' && 'Model Connection Verified'}
                    {llmTestResult.status === 'model_unavailable' && 'Model Unavailable on OpenRouter'}
                    {llmTestResult.status === 'rate_limited' && 'Provider Rate Limit Reached'}
                    {llmTestResult.status === 'unauthorized' && 'Invalid API Credentials'}
                    {llmTestResult.status === 'insufficient_credits' && 'Account Credits Exhausted'}
                    {llmTestResult.status === 'timeout' && 'Connection Timed Out'}
                    {llmTestResult.status === 'error' && 'Provider Error'}
                  </span>
                </div>
                <Badge
                  variant={
                    llmTestResult.status === 'connected'
                      ? 'success'
                      : llmTestResult.status === 'rate_limited'
                      ? 'warning'
                      : 'error'
                  }
                >
                  {llmTestResult.status.toUpperCase()} ({llmTestResult.latency_sec}s)
                </Badge>
              </div>
              <p className="settings-connection-detail-text">
                {llmTestResult.message}
              </p>
            </div>
          )}

          {llmTestError && (
            <div
              className="settings-connection-status-box"
              style={{ marginTop: '14px', borderColor: 'var(--error-border)' }}
              role="alert"
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <XCircle size={16} color="var(--error-text)" />
                <span style={{ fontWeight: 600, fontSize: '13px', color: 'var(--error-text)' }}>
                  Test Execution Failed
                </span>
              </div>
              <p className="settings-connection-detail-text" style={{ color: 'var(--error-text)' }}>
                {llmTestError}
              </p>
            </div>
          )}
        </div>

        {/* Section 2: n8n Connection */}
        <div className="settings-card">
          <div className="settings-card-header">
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <Server size={16} color="var(--brand-primary)" />
                <h2 className="settings-card-title" style={{ margin: 0 }}>2. n8n Connection</h2>
              </div>
              <Button
                id="btn-check-n8n"
                variant="secondary"
                size="sm"
                onClick={checkConnection}
                disabled={connectionState === 'loading'}
                icon={
                  connectionState === 'loading' ? (
                    <OrbitLoader size="inline" color="currentColor" />
                  ) : (
                    <RefreshCw size={13} />
                  )
                }
                aria-label="Check n8n connection"
              >
                {connectionState === 'loading' ? 'Checking...' : 'Check connection'}
              </Button>
            </div>
            <p className="settings-card-desc" style={{ marginTop: '6px' }}>
              Direct connection to the self-hosted n8n Community Edition running in Docker.
            </p>
          </div>

          <table className="status-table">
            <thead>
              <tr>
                <th>Parameter</th>
                <th>Configured Target</th>
                <th>Schema Coverage</th>
                <th>Connection Status</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td style={{ fontWeight: 600 }}>n8n Local Container</td>
                <td style={{ fontFamily: 'var(--font-mono)', fontSize: '12px' }}>
                  http://localhost:5678
                </td>
                <td style={{ fontFamily: 'var(--font-mono)', fontSize: '12px' }}>
                  444 Nodes (v2.42.6)
                </td>
                <td>
                  <div style={{ display: 'inline-flex', alignItems: 'center', gap: '6px' }}>
                    {renderStatusBadge()}
                  </div>
                </td>
              </tr>
            </tbody>
          </table>

          {/* Connection Detail Callout Box */}
          <div className="settings-connection-status-box" role="status" aria-live="polite">
            <div className="settings-connection-status-row">
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                {renderStatusIcon()}
                <span style={{ fontWeight: 600, fontSize: '13px', color: 'var(--text-primary)' }}>
                  {connectionState === 'connected' && 'n8n REST API Connected'}
                  {connectionState === 'not_configured' && 'API Key Missing in Environment'}
                  {connectionState === 'unauthorized' && 'Authentication Rejected'}
                  {connectionState === 'unreachable' && 'n8n Instance Unreachable'}
                  {connectionState === 'backend_offline' && 'Backend Server Offline'}
                  {connectionState === 'error' && 'Integration Error'}
                  {connectionState === 'loading' && 'Testing Connection...'}
                  {connectionState === 'idle' && 'Status Not Checked'}
                </span>
              </div>
              {lastChecked && (
                <span className="settings-connection-timestamp">
                  Checked at {lastChecked}
                </span>
              )}
            </div>

            <p className="settings-connection-detail-text">
              {statusMessage}
            </p>

            {connectionState === 'not_configured' && (
              <div
                style={{
                  fontSize: '12px',
                  color: 'var(--text-secondary)',
                  marginTop: '4px',
                  borderTop: '1px solid var(--border-subtle)',
                  paddingTop: '8px',
                }}
              >
                <strong>Setup Instructions:</strong> In your running n8n instance at{' '}
                <a
                  href="http://localhost:5678"
                  target="_blank"
                  rel="noreferrer"
                  style={{ color: 'var(--brand-primary)', textDecoration: 'underline' }}
                >
                  http://localhost:5678
                </a>
                , open Settings &gt; n8n API &gt; Create an API key. Copy the key and add{' '}
                <code>N8N_API_KEY=&lt;key&gt;</code> to your <code>.env</code> file, then click Check connection above.
              </div>
            )}

            {connectionState === 'backend_offline' && (
              <div
                style={{
                  fontSize: '12px',
                  color: 'var(--text-secondary)',
                  marginTop: '4px',
                  borderTop: '1px solid var(--border-subtle)',
                  paddingTop: '8px',
                }}
              >
                <strong>Backend Launch:</strong> Start the FastAPI server locally by running{' '}
                <code style={{ fontFamily: 'var(--font-mono)' }}>python -m uvicorn backend.app.main:app --port 8000</code> in your terminal.
              </div>
            )}

            {connectionState === 'unreachable' && (
              <div
                style={{
                  fontSize: '12px',
                  color: 'var(--text-secondary)',
                  marginTop: '4px',
                  borderTop: '1px solid var(--border-subtle)',
                  paddingTop: '8px',
                }}
              >
                <strong>Troubleshooting:</strong> Ensure the Docker container <code>n8n-local</code> is started and healthy in Docker Desktop.
              </div>
            )}
          </div>
        </div>

        {/* Section 3: Authentication & Local Access */}
        <div className="settings-card">
          <div className="settings-card-header">
            <h2 className="settings-card-title">3. Authentication &amp; Local Access</h2>
            <p className="settings-card-desc">
              Security boundaries and client access controls for local development.
            </p>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '12px',
                backgroundColor: 'var(--bg-surface-subtle)',
                borderRadius: 'var(--radius-md)',
                border: '1px solid var(--border-subtle)',
              }}
            >
              <div>
                <div style={{ fontWeight: 600, fontSize: '13px', color: 'var(--text-primary)' }}>
                  Local Trust Mode
                </div>
                <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
                  Single-user local development mode. User header defaults to <code>default-user</code>.
                </div>
              </div>
              <Badge variant="info">Active</Badge>
            </div>

            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '12px',
                backgroundColor: 'var(--bg-surface-subtle)',
                borderRadius: 'var(--radius-md)',
                border: '1px solid var(--border-subtle)',
              }}
            >
              <div>
                <div style={{ fontWeight: 600, fontSize: '13px', color: 'var(--text-primary)' }}>
                  Secret Storage &amp; Isolation
                </div>
                <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
                  API keys and tokens are stored backend-only in <code>.env</code> and are never displayed or transmitted to the browser.
                </div>
              </div>
              <Badge variant="success">Protected</Badge>
            </div>
          </div>
        </div>

        {/* Section 4: Diagnostics & Preferences */}
        <div className="settings-card">
          <div className="settings-card-header">
            <h2 className="settings-card-title">4. Diagnostics &amp; Appearance</h2>
            <p className="settings-card-desc">
              Database engine status and application interface preferences.
            </p>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '12px',
                backgroundColor: 'var(--bg-surface-subtle)',
                borderRadius: 'var(--radius-md)',
                border: '1px solid var(--border-subtle)',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <Database size={16} color="var(--brand-primary)" />
                <div>
                  <div style={{ fontWeight: 600, fontSize: '13px', color: 'var(--text-primary)' }}>
                    Database Storage
                  </div>
                  <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
                    PostgreSQL with async SQLAlchemy and Alembic migrations.
                  </div>
                </div>
              </div>
              <Badge variant="info">PostgreSQL</Badge>
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
              <Button
                variant={theme === 'light' ? 'primary' : 'secondary'}
                size="md"
                onClick={() => onThemeChange('light')}
                icon={<Sun size={14} />}
              >
                Light Theme
              </Button>
              <Button
                variant={theme === 'dark' ? 'primary' : 'secondary'}
                size="md"
                onClick={() => onThemeChange('dark')}
                icon={<Moon size={14} />}
              >
                Dark Theme
              </Button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
