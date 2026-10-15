import React, { useState, useEffect } from 'react';
import { Badge } from '../ui/Badge';
import { Button } from '../ui/Button';
import {
  ShieldAlert,
  CheckCircle2,
  AlertTriangle,
  Play,
  Lock,
  Terminal,
  X,
  FileCheck2,
  ExternalLink,
  Server,
  Copy,
  Check,
  Info,
  Globe,
  HelpCircle,
} from 'lucide-react';
import { OrbitLoader } from '../common/OrbitLoader';
import type { WorkflowIR } from '../../types/workflow';
import {
  getWorkflowReadiness,
  simulateWorkflowDryRun,
  deployWorkflowDraft,
  type WorkflowReadinessReport,
  type SafeSimulationResult,
  type DeployWorkflowResult,
  type StructuredResearchDossier,
  type WorkflowPlanItem,
} from '../../api/conversations';

interface WorkflowReviewPanelProps {
  workflow: WorkflowIR;
  conversationId?: string | null;
  currentRevisionNumber: number;
  isDirty: boolean;
  compiledJson?: Record<string, any> | null;
  onClose?: () => void;
  onSaveRevision?: () => void;
  onDeployed?: (result: DeployWorkflowResult) => void;
  researchDossier?: StructuredResearchDossier | null;
  workflowPlan?: WorkflowPlanItem | null;
}

/** Humanizes raw technical rule codes into readable titles */
function humanizeRuleCode(code: string): string {
  const map: Record<string, string> = {
    MISSING_REQUIRED_PARAMETER: 'Missing Required Parameter',
    INVALID_PARAMETER_TYPE: 'Invalid Parameter Type',
    INVALID_PARAMETER_OPTION: 'Invalid Option Selected',
    MISSING_REQUIRED_CREDENTIAL: 'Missing Credential',
    UNRESOLVED_DATA_MAPPING: 'Unmapped Data Field',
    DISCONNECTED_NODE: 'Disconnected Node',
    UNCONTROLLED_CYCLE_DETECTED: 'Graph Loop Detected',
    CONTROLLED_LOOP_DETECTED: 'Controlled Loop',
    NODE_TYPE_UNKNOWN: 'Unrecognized Node Type',
    NODE_VERSION_UNSUPPORTED: 'Unsupported Node Version',
    RESTRICTED_NODE: 'Restricted Node Detected',
  };
  if (map[code]) return map[code];
  return code
    .split('_')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
    .join(' ');
}

export const WorkflowReviewPanel: React.FC<WorkflowReviewPanelProps> = ({
  workflow,
  conversationId,
  currentRevisionNumber,
  isDirty,
  compiledJson,
  onClose,
  onSaveRevision,
  onDeployed,
  researchDossier,
  workflowPlan,
}) => {
  const [activeTab, setActiveTab] = useState<'readiness' | 'test_plan' | 'simulation' | 'research' | 'json'>('readiness');
  const [report, setReport] = useState<WorkflowReadinessReport | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const activeDossier = researchDossier || (report?.validation_report as any)?.research_dossier || null;
  const activePlan = workflowPlan || (report?.validation_report as any)?.workflow_plan || null;

  // Simulation state
  const [isSimulating, setIsSimulating] = useState(false);
  const [simResult, setSimResult] = useState<SafeSimulationResult | null>(null);
  const [simError, setSimError] = useState<string | null>(null);

  // Deployment state
  const [showApprovalModal, setShowApprovalModal] = useState(false);
  const [isDeploying, setIsDeploying] = useState(false);
  const [deployResult, setDeployResult] = useState<DeployWorkflowResult | null>(null);
  const [deployError, setDeployError] = useState<string | null>(null);
  const [hasAcknowledgedInactive, setHasAcknowledgedInactive] = useState(false);

  // Copy JSON feedback state
  const [isCopiedJson, setIsCopiedJson] = useState(false);

  // Load readiness report
  useEffect(() => {
    let isMounted = true;
    async function loadReadiness() {
      if (!conversationId) return;
      setIsLoading(true);
      setError(null);
      try {
        const res = await getWorkflowReadiness(conversationId, workflow);
        if (isMounted) {
          setReport(res);
        }
      } catch (err: any) {
        if (isMounted) {
          setError(err.message || 'Failed to load readiness assessment');
        }
      } finally {
        if (isMounted) {
          setIsLoading(false);
        }
      }
    }

    loadReadiness();
    return () => {
      isMounted = false;
    };
  }, [conversationId, workflow]);

  // Execute safe static dry run simulation
  const handleRunSimulation = async () => {
    if (!conversationId) return;
    setIsSimulating(true);
    setSimError(null);
    try {
      const res = await simulateWorkflowDryRun(conversationId, workflow);
      setSimResult(res);
      setActiveTab('simulation');
    } catch (err: any) {
      setSimError(err.message || 'Dry-run simulation failed');
    } finally {
      setIsSimulating(false);
    }
  };

  const handleCopyJson = async () => {
    try {
      const text = JSON.stringify(compiledJson || workflow, null, 2);
      await navigator.clipboard.writeText(text);
      setIsCopiedJson(true);
      setTimeout(() => setIsCopiedJson(false), 2000);
    } catch {
      // Fallback
      setIsCopiedJson(false);
    }
  };

  // Derive unified overall status from backend data
  const hasMissingOrInvalidCreds =
    report?.credentials?.some(
      (c) => c.verification_state === 'missing' || c.verification_state === 'invalid'
    ) ?? false;

  const getOverallStatusDetails = () => {
    if (!report) {
      return {
        label: 'Evaluating...',
        variant: 'neutral' as const,
        headline: 'Evaluating Workflow Readiness',
        description: 'Analyzing graph structure, required parameters, and credential references...',
        icon: <OrbitLoader size="xs" color="var(--brand-primary, #EA580C)" ariaLabel="Evaluating Workflow Readiness..." />,
      };
    }

    if (report.overall_status === 'blocked') {
      return {
        label: 'Blocked',
        variant: 'error' as const,
        headline: 'Workflow Blocked',
        description: report.summary || 'Critical errors must be resolved before this workflow can be tested or deployed.',
        icon: <ShieldAlert size={20} style={{ color: 'var(--state-error, #EF4444)' }} />,
      };
    }

    if (report.overall_status === 'needs_attention') {
      return {
        label: 'Needs configuration',
        variant: 'warning' as const,
        headline: 'Needs Configuration',
        description: report.summary || 'Required node settings or credentials must be configured before deploying.',
        icon: <AlertTriangle size={20} style={{ color: 'var(--state-warning, #F59E0B)' }} />,
      };
    }

    // Ready status
    if (report.is_deployment_ready && !hasMissingOrInvalidCreds) {
      return {
        label: 'Ready to deploy',
        variant: 'success' as const,
        headline: 'Ready to Deploy',
        description: report.summary || 'All structural checks, required parameters, and credential configurations are satisfied.',
        icon: <CheckCircle2 size={20} style={{ color: 'var(--state-success, #10B981)' }} />,
      };
    }

    return {
      label: 'Ready for review',
      variant: 'info' as const,
      headline: 'Ready for Review',
      description: report.summary || 'The workflow passed structural graph checks, but requires user review before deployment.',
      icon: <CheckCircle2 size={20} style={{ color: 'var(--state-info, #3B82F6)' }} />,
    };
  };

  const statusDetails = getOverallStatusDetails();

  const getResearchStatusDetails = () => {
    if (!activeDossier) {
      return {
        status: 'not_required' as const,
        label: 'Installed Node Catalog Authority',
        variant: 'neutral' as const,
        headline: 'Installed Node Catalog Grounding',
        description: 'Standard built-in node definitions (n8n v2.42.6) provided complete technical specifications. External web research was not required.',
        icon: <Server size={18} style={{ color: 'var(--state-info, #3B82F6)' }} />,
      };
    }

    if (!activeDossier.needs_research) {
      return {
        status: 'skipped' as const,
        label: 'Local Node Catalog Authority',
        variant: 'neutral' as const,
        headline: 'Installed Node Catalog Grounding',
        description: activeDossier.research_reasons?.[0] || 'Local node catalog and built-in definitions are sufficient for this workflow.',
        icon: <CheckCircle2 size={18} style={{ color: 'var(--state-success, #10B981)' }} />,
      };
    }

    const hasSources = (activeDossier.sources?.length ?? 0) > 0;
    const hasWarnings = (activeDossier.warnings?.length ?? 0) > 0;
    const isFailed = Boolean(
      activeDossier.is_fallback ||
      (!hasSources && (hasWarnings || activeDossier.needs_research))
    );

    if (isFailed) {
      return {
        status: 'failed' as const,
        label: 'Research Failed (Catalog Fallback)',
        variant: 'error' as const,
        headline: 'External Documentation Research Failed',
        description: 'Web research could not be completed (e.g. unconfigured API key or network limitation). The workflow was planned using installed node definitions only. Verification is not claimed for external APIs.',
        icon: <ShieldAlert size={18} style={{ color: 'var(--state-error, #EF4444)' }} />,
      };
    }

    if (hasWarnings) {
      return {
        status: 'partially_completed' as const,
        label: 'Partially Researched',
        variant: 'warning' as const,
        headline: 'Partially Researched with Limitations',
        description: 'External documentation was consulted, but some query limitations or service warnings occurred. Review the warnings below.',
        icon: <AlertTriangle size={18} style={{ color: 'var(--state-warning, #F59E0B)' }} />,
      };
    }

    return {
      status: 'completed' as const,
      label: 'Web Research Grounded',
      variant: 'success' as const,
      headline: 'Documentation Grounded via Tavily',
      description: 'External API documentation was retrieved via Tavily, sanitized against prompt injection, and verified against 444 installed local node definitions.',
      icon: <CheckCircle2 size={18} style={{ color: 'var(--state-success, #10B981)' }} />,
    };
  };

  const researchStatusDetails = getResearchStatusDetails();

  // Status checks for the 5-point essential summary
  const isStructureValid = report ? (report.is_structure_valid ?? report.validation_report.is_valid) : true;
  const isConfigComplete = report ? (report.is_configuration_complete ?? true) : true;
  const missingCredsCount = report ? report.credentials.filter((c) => c.verification_state === 'missing').length : 0;
  const invalidCredsCount = report ? report.credentials.filter((c) => c.verification_state === 'invalid').length : 0;
  const configuredCredsCount = report
    ? report.credentials.filter((c) => c.verification_state === 'configured' || c.verification_state === 'verified').length
    : 0;

  return (
    <div
      style={{
        backgroundColor: 'var(--bg-surface, #111827)',
        border: '1px solid var(--border-default, #374151)',
        borderRadius: 'var(--radius-md, 6px)',
        overflow: 'hidden',
        display: 'flex',
        flexDirection: 'column',
        boxShadow: 'var(--shadow-xl)',
        fontFamily: 'var(--font-sans)',
        maxHeight: '90vh',
        width: '100%',
      }}
    >
      {/* 1. Panel Header */}
      <div
        style={{
          padding: '16px 20px',
          borderBottom: '1px solid var(--border-subtle, #1F2937)',
          backgroundColor: 'var(--bg-surface-elevated, #1A2234)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexWrap: 'wrap',
          gap: '12px',
          flexShrink: 0,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', minWidth: 0 }}>
          <div
            style={{
              width: '34px',
              height: '34px',
              backgroundColor: 'rgba(234, 88, 12, 0.12)',
              border: '1px solid var(--brand-primary, #EA580C)',
              borderRadius: 'var(--radius-sm, 4px)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: 'var(--brand-primary, #EA580C)',
              flexShrink: 0,
            }}
          >
            <FileCheck2 size={18} />
          </div>
          <div style={{ minWidth: 0 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
              <h2 style={{ fontSize: '16px', fontWeight: 600, color: 'var(--text-primary, #F9FAFB)', margin: 0 }}>
                Workflow Review &amp; Readiness
              </h2>
              <Badge variant={statusDetails.variant}>{statusDetails.label}</Badge>
            </div>
            <div
              style={{
                fontSize: '13px',
                color: 'var(--text-secondary, #9CA3AF)',
                marginTop: '3px',
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
                flexWrap: 'wrap',
              }}
            >
              <span style={{ fontWeight: 500, color: 'var(--text-primary)' }}>{workflow.name || 'Untitled Workflow'}</span>
              <span>•</span>
              <span style={{ fontFamily: 'var(--font-mono)' }}>Revision #{currentRevisionNumber}</span>
              {isDirty && (
                <>
                  <span>•</span>
                  <span style={{ color: 'var(--state-warning, #F59E0B)', fontWeight: 600 }}>Unsaved Local Edits</span>
                </>
              )}
            </div>
          </div>
        </div>

        {/* Header Action Controls */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexShrink: 0 }}>
          {isDirty && onSaveRevision && (
            <button
              type="button"
              className="btn btn-primary btn-sm"
              onClick={onSaveRevision}
              style={{ fontSize: '13px', padding: '6px 12px' }}
            >
              Save Revision
            </button>
          )}

          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={handleRunSimulation}
            disabled={isSimulating}
            style={{ fontSize: '13px', padding: '6px 12px', display: 'flex', alignItems: 'center', gap: '6px' }}
            title="Run non-mutating local dry-run simulation"
          >
            {isSimulating ? <OrbitLoader size="inline" color="currentColor" /> : <Play size={14} />}
            <span>Run Dry-Run</span>
          </button>

          <Button
            variant="primary"
            size="sm"
            onClick={() => {
              setDeployError(null);
              setShowApprovalModal(true);
            }}
            disabled={
              !(report?.is_deployment_ready ?? false) ||
              hasMissingOrInvalidCreds ||
              isDirty
            }
            style={{ fontSize: '13px', padding: '6px 14px', display: 'flex', alignItems: 'center', gap: '6px' }}
            title={
              isDirty
                ? 'Save your revision before deploying'
                : hasMissingOrInvalidCreds
                ? 'Resolve missing or invalid credentials before deploying'
                : 'Deploy workflow to connected n8n instance'
            }
          >
            <Lock size={14} />
            <span>Deploy to n8n</span>
          </Button>

          {onClose && (
            <button
              type="button"
              onClick={onClose}
              style={{
                background: 'transparent',
                border: 'none',
                color: 'var(--text-tertiary, #9CA3AF)',
                cursor: 'pointer',
                padding: '6px',
                borderRadius: 'var(--radius-sm)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
              title="Close Review Panel"
              aria-label="Close"
            >
              <X size={18} />
            </button>
          )}
        </div>
      </div>

      {/* 2. Simplified Tab Navigation */}
      <div
        style={{
          display: 'flex',
          borderBottom: '1px solid var(--border-subtle, #1F2937)',
          backgroundColor: 'var(--bg-surface, #111827)',
          padding: '0 20px',
          gap: '12px',
          flexShrink: 0,
        }}
      >
        <button
          type="button"
          onClick={() => setActiveTab('readiness')}
          style={{
            padding: '12px 14px',
            fontSize: '14px',
            fontWeight: 500,
            background: 'none',
            border: 'none',
            borderBottom: activeTab === 'readiness' ? '2px solid var(--brand-primary, #EA580C)' : '2px solid transparent',
            color: activeTab === 'readiness' ? 'var(--text-primary, #F9FAFB)' : 'var(--text-secondary, #9CA3AF)',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
          }}
        >
          <span>Readiness Checks</span>
          {report && (
            <span
              style={{
                fontSize: '11px',
                padding: '1px 6px',
                borderRadius: '10px',
                backgroundColor:
                  report.overall_status === 'ready'
                    ? 'rgba(16, 185, 129, 0.15)'
                    : 'rgba(245, 158, 11, 0.15)',
                color:
                  report.overall_status === 'ready'
                    ? 'var(--state-success, #10B981)'
                    : 'var(--state-warning, #F59E0B)',
                fontWeight: 600,
              }}
            >
              {report.validation_report.issues.length === 0 ? '✓' : report.validation_report.issues.length}
            </span>
          )}
        </button>

        <button
          type="button"
          onClick={() => setActiveTab('test_plan')}
          style={{
            padding: '12px 14px',
            fontSize: '14px',
            fontWeight: 500,
            background: 'none',
            border: 'none',
            borderBottom: activeTab === 'test_plan' ? '2px solid var(--brand-primary, #EA580C)' : '2px solid transparent',
            color: activeTab === 'test_plan' ? 'var(--text-primary, #F9FAFB)' : 'var(--text-secondary, #9CA3AF)',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
          }}
        >
          <span>Safe Test Plan</span>
          {report && (
            <span
              style={{
                fontSize: '11px',
                padding: '1px 6px',
                borderRadius: '10px',
                backgroundColor: 'var(--bg-surface-elevated)',
                color: 'var(--text-secondary)',
              }}
            >
              {report.test_plan.steps.length} steps
            </span>
          )}
        </button>

        <button
          type="button"
          onClick={() => setActiveTab('simulation')}
          style={{
            padding: '12px 14px',
            fontSize: '14px',
            fontWeight: 500,
            background: 'none',
            border: 'none',
            borderBottom: activeTab === 'simulation' ? '2px solid var(--brand-primary, #EA580C)' : '2px solid transparent',
            color: activeTab === 'simulation' ? 'var(--text-primary, #F9FAFB)' : 'var(--text-secondary, #9CA3AF)',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
          }}
        >
          <span>Simulation Results</span>
          {simResult && (
            <span style={{ fontSize: '12px' }}>{simResult.success ? '✓' : '⚠️'}</span>
          )}
        </button>

        <button
          type="button"
          onClick={() => setActiveTab('research')}
          style={{
            padding: '12px 14px',
            fontSize: '14px',
            fontWeight: 500,
            background: 'none',
            border: 'none',
            borderBottom: activeTab === 'research' ? '2px solid var(--brand-primary, #EA580C)' : '2px solid transparent',
            color: activeTab === 'research' ? 'var(--text-primary, #F9FAFB)' : 'var(--text-secondary, #9CA3AF)',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
          }}
        >
          <Globe size={15} />
          <span>Research Grounding</span>
          {activeDossier && (
            <span
              style={{
                fontSize: '11px',
                padding: '1px 6px',
                borderRadius: '10px',
                backgroundColor:
                  activeDossier.is_fallback
                    ? 'rgba(239, 68, 68, 0.15)'
                    : (activeDossier.sources?.length ?? 0) > 0
                    ? 'rgba(59, 130, 246, 0.15)'
                    : 'rgba(156, 163, 175, 0.15)',
                color:
                  activeDossier.is_fallback
                    ? 'var(--state-error, #EF4444)'
                    : (activeDossier.sources?.length ?? 0) > 0
                    ? 'var(--state-info, #3B82F6)'
                    : 'var(--text-secondary, #9CA3AF)',
                fontWeight: 600,
              }}
            >
              {activeDossier.is_fallback
                ? 'Fallback'
                : (activeDossier.sources?.length ?? 0) > 0
                ? activeDossier.sources.length
                : 'Catalog'}
            </span>
          )}
        </button>

        <button
          type="button"
          onClick={() => setActiveTab('json')}
          style={{
            padding: '12px 14px',
            fontSize: '14px',
            fontWeight: 500,
            background: 'none',
            border: 'none',
            borderBottom: activeTab === 'json' ? '2px solid var(--brand-primary, #EA580C)' : '2px solid transparent',
            color: activeTab === 'json' ? 'var(--text-primary, #F9FAFB)' : 'var(--text-secondary, #9CA3AF)',
            cursor: 'pointer',
          }}
        >
          Compiled n8n JSON
        </button>
      </div>

      {/* 3. Main Content Area */}
      <div style={{ padding: '20px', flex: 1, overflowY: 'auto' }}>
        {isLoading && (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '48px' }}>
            <OrbitLoader
              size="md"
              label="Evaluating workflow readiness..."
              labelPosition="bottom"
              center
            />
          </div>
        )}

        {error && (
          <div
            style={{
              padding: '12px 16px',
              backgroundColor: 'var(--state-error-subtle, #7F1D1D)',
              color: 'var(--state-error, #EF4444)',
              border: '1px solid var(--state-error, #EF4444)',
              borderRadius: 'var(--radius-sm, 4px)',
              fontSize: '14px',
              marginBottom: '16px',
            }}
          >
            {error}
          </div>
        )}

        {/* ------------------------------------------------------------- */}
        {/* TAB 1: READINESS CHECKS (SIMPLIFIED HIERARCHY)               */}
        {/* ------------------------------------------------------------- */}
        {!isLoading && activeTab === 'readiness' && report && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
            {/* A. Overall Status Callout */}
            <div
              style={{
                padding: '16px 18px',
                backgroundColor:
                  statusDetails.variant === 'success'
                    ? 'rgba(16, 185, 129, 0.08)'
                    : statusDetails.variant === 'warning'
                    ? 'rgba(245, 158, 11, 0.08)'
                    : statusDetails.variant === 'error'
                    ? 'rgba(239, 68, 68, 0.08)'
                    : 'rgba(59, 130, 246, 0.08)',
                border: `1px solid ${
                  statusDetails.variant === 'success'
                    ? 'var(--state-success, #10B981)'
                    : statusDetails.variant === 'warning'
                    ? 'var(--state-warning, #F59E0B)'
                    : statusDetails.variant === 'error'
                    ? 'var(--state-error, #EF4444)'
                    : 'var(--state-info, #3B82F6)'
                }`,
                borderRadius: 'var(--radius-sm, 4px)',
                display: 'flex',
                alignItems: 'flex-start',
                gap: '14px',
              }}
            >
              <div style={{ marginTop: '2px', flexShrink: 0 }}>{statusDetails.icon}</div>
              <div style={{ flex: 1 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
                  <h3 style={{ fontSize: '15px', fontWeight: 600, color: 'var(--text-primary)', margin: 0 }}>
                    {statusDetails.headline}
                  </h3>
                  <Badge variant={statusDetails.variant}>{statusDetails.label}</Badge>
                </div>
                <div style={{ fontSize: '14px', color: 'var(--text-secondary)', marginTop: '4px', lineHeight: 1.5 }}>
                  {statusDetails.description}
                </div>
                <div style={{ fontSize: '13px', color: 'var(--text-tertiary)', marginTop: '6px' }}>
                  {workflow.nodes?.length || 0} nodes • {workflow.edges?.length || 0} connections • n8n 2.42.6 compatibility
                </div>
              </div>
            </div>

            {/* B. Essential Checks Summary (Compact Checklist) */}
            <div>
              <h4 style={{ fontSize: '14px', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '10px' }}>
                Readiness Summary
              </h4>
              <div
                style={{
                  backgroundColor: 'var(--bg-surface-elevated, #1A2234)',
                  border: '1px solid var(--border-subtle, #1F2937)',
                  borderRadius: 'var(--radius-sm, 4px)',
                  padding: '12px 16px',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '12px',
                }}
              >
                {/* 1. Structure */}
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px' }}>
                  <span style={{ fontSize: '14px', color: 'var(--text-primary)' }}>1. Workflow Structure</span>
                  <span
                    style={{
                      fontSize: '13px',
                      fontWeight: 600,
                      display: 'flex',
                      alignItems: 'center',
                      gap: '6px',
                      color: isStructureValid ? 'var(--state-success, #10B981)' : 'var(--state-error, #EF4444)',
                    }}
                  >
                    {isStructureValid ? <CheckCircle2 size={16} /> : <AlertTriangle size={16} />}
                    {isStructureValid ? 'Valid graph structure' : 'Structural errors detected'}
                  </span>
                </div>

                {/* 2. Configuration */}
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px' }}>
                  <span style={{ fontSize: '14px', color: 'var(--text-primary)' }}>2. Required Parameters</span>
                  <span
                    style={{
                      fontSize: '13px',
                      fontWeight: 600,
                      display: 'flex',
                      alignItems: 'center',
                      gap: '6px',
                      color: isConfigComplete ? 'var(--state-success, #10B981)' : 'var(--state-warning, #F59E0B)',
                    }}
                  >
                    {isConfigComplete ? <CheckCircle2 size={16} /> : <AlertTriangle size={16} />}
                    {isConfigComplete
                      ? 'All mandatory settings configured'
                      : `${report.unresolved_configuration?.length || 1} parameter(s) require input`}
                  </span>
                </div>

                {/* 3. Credentials */}
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px' }}>
                  <span style={{ fontSize: '14px', color: 'var(--text-primary)' }}>3. External Credentials</span>
                  <span
                    style={{
                      fontSize: '13px',
                      fontWeight: 600,
                      display: 'flex',
                      alignItems: 'center',
                      gap: '6px',
                      color:
                        report.credentials.length === 0
                          ? 'var(--text-secondary)'
                          : missingCredsCount > 0 || invalidCredsCount > 0
                          ? 'var(--state-error, #EF4444)'
                          : configuredCredsCount > 0
                          ? 'var(--state-success, #10B981)'
                          : 'var(--state-info, #3B82F6)',
                    }}
                  >
                    {report.credentials.length === 0 ? (
                      '✓ No credentials required'
                    ) : missingCredsCount > 0 ? (
                      <>
                        <AlertTriangle size={16} />
                        <span>{missingCredsCount} credential(s) missing</span>
                      </>
                    ) : invalidCredsCount > 0 ? (
                      <>
                        <AlertTriangle size={16} />
                        <span>Invalid credential reference</span>
                      </>
                    ) : configuredCredsCount === report.credentials.length ? (
                      <>
                        <CheckCircle2 size={16} />
                        <span>Configured in n8n</span>
                      </>
                    ) : (
                      <>
                        <Info size={16} />
                        <span>{report.credentials.length} referenced (pending check)</span>
                      </>
                    )}
                  </span>
                </div>

                {/* 4. Test Status */}
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px' }}>
                  <span style={{ fontSize: '14px', color: 'var(--text-primary)' }}>4. Static Dry-Run Simulation</span>
                  <span
                    style={{
                      fontSize: '13px',
                      fontWeight: 600,
                      display: 'flex',
                      alignItems: 'center',
                      gap: '6px',
                      color: simResult
                        ? simResult.success
                          ? 'var(--state-success, #10B981)'
                          : 'var(--state-warning, #F59E0B)'
                        : 'var(--text-tertiary)',
                    }}
                  >
                    {simResult ? (
                      simResult.success ? (
                        <>
                          <CheckCircle2 size={16} />
                          <span>Passed ({simResult.passed_nodes}/{simResult.total_nodes} nodes)</span>
                        </>
                      ) : (
                        <>
                          <AlertTriangle size={16} />
                          <span>Issues reported</span>
                        </>
                      )
                    ) : (
                      'Not executed yet'
                    )}
                  </span>
                </div>

                {/* 5. Deployment Status */}
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px' }}>
                  <span style={{ fontSize: '14px', color: 'var(--text-primary)' }}>5. Deployment Gate</span>
                  <span
                    style={{
                      fontSize: '13px',
                      fontWeight: 600,
                      display: 'flex',
                      alignItems: 'center',
                      gap: '6px',
                      color: deployResult
                        ? 'var(--state-success, #10B981)'
                        : report.is_deployment_ready && !hasMissingOrInvalidCreds
                        ? 'var(--state-success, #10B981)'
                        : 'var(--state-warning, #F59E0B)',
                    }}
                  >
                    {deployResult ? (
                      <>
                        <CheckCircle2 size={16} />
                        <span>Deployed to n8n (ID: #{deployResult.workflow_id})</span>
                      </>
                    ) : report.is_deployment_ready && !hasMissingOrInvalidCreds ? (
                      <>
                        <CheckCircle2 size={16} />
                        <span>Ready for deployment approval</span>
                      </>
                    ) : (
                      <>
                        <Lock size={15} />
                        <span>Blocked (Resolve issues before deploying)</span>
                      </>
                    )}
                  </span>
                </div>
              </div>
            </div>

            {/* C. Actionable Issues List */}
            <div>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '10px' }}>
                <h4 style={{ fontSize: '14px', fontWeight: 600, color: 'var(--text-primary)', margin: 0 }}>
                  Actionable Issues ({report.validation_report.issues.length})
                </h4>
              </div>

              {report.validation_report.issues.length === 0 ? (
                <div
                  style={{
                    padding: '14px 16px',
                    backgroundColor: 'rgba(16, 185, 129, 0.08)',
                    border: '1px solid rgba(16, 185, 129, 0.3)',
                    borderRadius: 'var(--radius-sm, 4px)',
                    fontSize: '14px',
                    color: 'var(--state-success, #10B981)',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '8px',
                  }}
                >
                  <CheckCircle2 size={16} />
                  <span>All structural, typing, and configuration checks passed without issues.</span>
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  {report.validation_report.issues.map((issue, idx) => {
                    const humanTitle = humanizeRuleCode(issue.rule_code);
                    const isFatal = issue.severity === 'fatal';
                    return (
                      <div
                        key={idx}
                        style={{
                          padding: '12px 14px',
                          backgroundColor: 'var(--bg-surface-elevated, #1A2234)',
                          border: `1px solid ${isFatal ? 'rgba(239, 68, 68, 0.3)' : 'var(--border-subtle, #1F2937)'}`,
                          borderRadius: 'var(--radius-sm, 4px)',
                          display: 'flex',
                          flexDirection: 'column',
                          gap: '6px',
                        }}
                      >
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px' }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                            <Badge variant={isFatal ? 'error' : issue.severity === 'warning' ? 'warning' : 'info'}>
                              {issue.severity.toUpperCase()}
                            </Badge>
                            <span style={{ fontSize: '14px', fontWeight: 600, color: 'var(--text-primary)' }}>
                              {humanTitle}
                            </span>
                          </div>
                          {issue.node_id && (
                            <span
                              style={{
                                fontSize: '12px',
                                color: 'var(--text-tertiary)',
                                fontFamily: 'var(--font-mono)',
                                backgroundColor: 'var(--bg-app)',
                                padding: '2px 6px',
                                borderRadius: 'var(--radius-sm)',
                              }}
                            >
                              Node: {issue.node_id}
                            </span>
                          )}
                        </div>

                        <div style={{ fontSize: '13px', color: 'var(--text-secondary)', lineHeight: 1.4 }}>
                          {issue.message}
                        </div>

                        {issue.suggested_fix && (
                          <div
                            style={{
                              fontSize: '13px',
                              color: 'var(--brand-primary, #EA580C)',
                              backgroundColor: 'rgba(234, 88, 12, 0.08)',
                              padding: '6px 10px',
                              borderRadius: 'var(--radius-sm)',
                              marginTop: '2px',
                            }}
                          >
                            <strong>Next step:</strong> {issue.suggested_fix}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>

            {/* D. Credential Summary (Compact & Honest) */}
            <div>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '10px' }}>
                <h4 style={{ fontSize: '14px', fontWeight: 600, color: 'var(--text-primary)', margin: 0 }}>
                  Required Credentials ({report.credentials.length})
                </h4>
                <span style={{ fontSize: '12px', color: 'var(--text-tertiary)' }}>
                  Zero-Trust: Checked against connected n8n instance
                </span>
              </div>

              {report.credentials.length === 0 ? (
                <div
                  style={{
                    padding: '12px 14px',
                    backgroundColor: 'var(--bg-surface-elevated)',
                    border: '1px solid var(--border-subtle)',
                    borderRadius: 'var(--radius-sm)',
                    fontSize: '13px',
                    color: 'var(--text-secondary)',
                  }}
                >
                  ✓ No external service credentials are required for this workflow.
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  {report.credentials.map((cred, idx) => {
                    const isMissingOrInvalid =
                      cred.verification_state === 'missing' || cred.verification_state === 'invalid';
                    const isConfigured =
                      cred.verification_state === 'configured' || cred.verification_state === 'verified';

                    return (
                      <div
                        key={idx}
                        style={{
                          padding: '12px 14px',
                          backgroundColor: 'var(--bg-surface-elevated)',
                          border: '1px solid var(--border-subtle)',
                          borderRadius: 'var(--radius-sm)',
                          display: 'flex',
                          flexDirection: 'column',
                          gap: '6px',
                        }}
                      >
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '10px' }}>
                          <span style={{ fontSize: '14px', fontWeight: 600, color: 'var(--text-primary)' }}>
                            {cred.node_name} • <span style={{ fontFamily: 'var(--font-mono)', fontSize: '13px' }}>{cred.credential_type}</span>
                          </span>
                          <Badge
                            variant={
                              isMissingOrInvalid
                                ? 'error'
                                : cred.verification_state === 'insecure_literal'
                                ? 'warning'
                                : isConfigured
                                ? 'success'
                                : 'info'
                            }
                          >
                            {cred.verification_state === 'configured'
                              ? 'Configured in n8n'
                              : cred.verification_state === 'verified'
                              ? 'Verified'
                              : cred.verification_state === 'invalid'
                              ? 'Invalid ID'
                              : cred.verification_state === 'referenced' || cred.verification_state === 'unverified_reference'
                              ? 'Referenced (Pending check)'
                              : cred.verification_state === 'missing'
                              ? 'Missing'
                              : cred.verification_state === 'insecure_literal'
                              ? 'Insecure literal secret'
                              : 'Not required'}
                          </Badge>
                        </div>

                        <div style={{ fontSize: '13px', color: 'var(--text-secondary)', lineHeight: 1.4 }}>
                          {cred.guidance}
                        </div>

                        {cred.configured_reference && (
                          <div style={{ fontSize: '12px', fontFamily: 'var(--font-mono)', color: 'var(--text-tertiary)' }}>
                            Reference: {cred.configured_reference}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>

            {/* E. Advanced Technical Details (Expandable) */}
            <details
              style={{
                backgroundColor: 'var(--bg-surface-elevated, #1A2234)',
                border: '1px solid var(--border-subtle, #1F2937)',
                borderRadius: 'var(--radius-sm, 4px)',
                padding: '12px 14px',
              }}
            >
              <summary
                style={{
                  fontSize: '13px',
                  fontWeight: 600,
                  color: 'var(--text-secondary)',
                  cursor: 'pointer',
                  userSelect: 'none',
                }}
              >
                Advanced Diagnostic Checks ({report.checks.length} system rules)
              </summary>
              <div style={{ marginTop: '12px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                {report.checks.map((chk, idx) => (
                  <div
                    key={idx}
                    style={{
                      padding: '8px 10px',
                      backgroundColor: 'var(--bg-app)',
                      border: '1px solid var(--border-subtle)',
                      borderRadius: 'var(--radius-sm)',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '4px',
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                      <span style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-primary)' }}>
                        {chk.title}
                      </span>
                      <Badge variant={chk.status === 'pass' ? 'success' : chk.status === 'fail' ? 'error' : 'warning'}>
                        {chk.status.toUpperCase()}
                      </Badge>
                    </div>
                    <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>{chk.detail}</div>
                    {chk.actionable_recommendation && (
                      <div style={{ fontSize: '12px', color: 'var(--brand-primary)' }}>
                        Recommendation: {chk.actionable_recommendation}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </details>
          </div>
        )}

        {/* ------------------------------------------------------------- */}
        {/* TAB 2: SAFE TEST PLAN                                         */}
        {/* ------------------------------------------------------------- */}
        {!isLoading && activeTab === 'test_plan' && report && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            <div
              style={{
                padding: '12px 16px',
                backgroundColor: 'rgba(59, 130, 246, 0.08)',
                border: '1px solid rgba(59, 130, 246, 0.25)',
                borderRadius: 'var(--radius-sm)',
                fontSize: '13px',
                color: 'var(--text-secondary)',
                lineHeight: 1.5,
              }}
            >
              <strong>Safe Non-Mutating Testing:</strong> Local static checks evaluate DAG schema, parameters, and expressions without calling external services. Checks requiring n8n execution or third-party credentials run only when deployed.
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '12px' }}>
              <div
                style={{
                  padding: '12px 14px',
                  backgroundColor: 'var(--bg-surface-elevated)',
                  border: '1px solid var(--border-subtle)',
                  borderRadius: 'var(--radius-sm)',
                }}
              >
                <div style={{ fontSize: '13px', fontWeight: 600, color: 'var(--state-success, #10B981)', marginBottom: '8px' }}>
                  ✓ Local Static Checks (Available Now)
                </div>
                <ul style={{ paddingLeft: '18px', margin: 0, fontSize: '12px', color: 'var(--text-secondary)', lineHeight: 1.6 }}>
                  {report.test_plan.local_checks.map((item, idx) => (
                    <li key={idx}>{item}</li>
                  ))}
                </ul>
              </div>

              <div
                style={{
                  padding: '12px 14px',
                  backgroundColor: 'var(--bg-surface-elevated)',
                  border: '1px solid var(--border-subtle)',
                  borderRadius: 'var(--radius-sm)',
                }}
              >
                <div style={{ fontSize: '13px', fontWeight: 600, color: 'var(--state-warning, #F59E0B)', marginBottom: '8px' }}>
                  ⚙ Target n8n Dependent Checks
                </div>
                <ul style={{ paddingLeft: '18px', margin: 0, fontSize: '12px', color: 'var(--text-secondary)', lineHeight: 1.6 }}>
                  {report.test_plan.instance_dependent_checks.map((item, idx) => (
                    <li key={idx}>{item}</li>
                  ))}
                </ul>
              </div>
            </div>

            <div>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '10px' }}>
                <h4 style={{ fontSize: '14px', fontWeight: 600, color: 'var(--text-primary)', margin: 0 }}>
                  Topological Execution Sequence ({report.test_plan.steps.length} nodes)
                </h4>
                <span style={{ fontSize: '12px', color: 'var(--text-tertiary)' }}>
                  Proposed execution order for validation
                </span>
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                {report.test_plan.steps.map((step) => (
                  <div
                    key={step.node_id}
                    style={{
                      padding: '10px 14px',
                      backgroundColor: 'var(--bg-surface-elevated)',
                      border: '1px solid var(--border-subtle)',
                      borderRadius: 'var(--radius-sm)',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      gap: '12px',
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: '10px', minWidth: 0 }}>
                      <span
                        style={{
                          fontSize: '12px',
                          fontFamily: 'var(--font-mono)',
                          color: 'var(--brand-primary)',
                          fontWeight: 600,
                          width: '28px',
                          flexShrink: 0,
                        }}
                      >
                        #{step.step_number}
                      </span>
                      <div style={{ minWidth: 0 }}>
                        <div style={{ fontSize: '14px', fontWeight: 600, color: 'var(--text-primary)' }}>
                          {step.node_name}
                        </div>
                        <div style={{ fontSize: '12px', color: 'var(--text-tertiary)', fontFamily: 'var(--font-mono)' }}>
                          {step.node_type}
                        </div>
                      </div>
                    </div>

                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexShrink: 0 }}>
                      <Badge variant={step.testable_locally ? 'success' : 'neutral'}>
                        {step.execution_tier === 'local_static' ? 'Local Static' : 'Requires n8n'}
                      </Badge>
                      <Badge variant={step.side_effect_risk === 'none' ? 'neutral' : step.side_effect_risk === 'read_only' ? 'info' : 'warning'}>
                        Risk: {step.side_effect_risk}
                      </Badge>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* ------------------------------------------------------------- */}
        {/* TAB 3: SIMULATION RESULTS                                     */}
        {/* ------------------------------------------------------------- */}
        {!isLoading && activeTab === 'simulation' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div>
                <h3 style={{ fontSize: '15px', fontWeight: 600, color: 'var(--text-primary)', margin: 0 }}>
                  Deterministic Static Simulation
                </h3>
                <p style={{ fontSize: '13px', color: 'var(--text-secondary)', margin: '3px 0 0 0' }}>
                  Simulates data-flow ordering and parameter completeness using mock data without external side effects.
                </p>
              </div>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={handleRunSimulation}
                disabled={isSimulating}
                style={{ fontSize: '13px', display: 'flex', alignItems: 'center', gap: '6px' }}
              >
                {isSimulating ? <OrbitLoader size="inline" color="currentColor" /> : <Play size={14} />}
                <span>{simResult ? 'Re-run Simulation' : 'Start Dry-Run'}</span>
              </button>
            </div>

            {simError && (
              <div
                style={{
                  padding: '12px 14px',
                  backgroundColor: 'var(--state-error-subtle)',
                  color: 'var(--state-error)',
                  borderRadius: 'var(--radius-sm)',
                  fontSize: '13px',
                }}
              >
                {simError}
              </div>
            )}

            {!simResult && !isSimulating && (
              <div
                style={{
                  padding: '36px 20px',
                  textAlign: 'center',
                  backgroundColor: 'var(--bg-surface-elevated)',
                  border: '1px dashed var(--border-default)',
                  borderRadius: 'var(--radius-sm)',
                }}
              >
                <Terminal size={28} style={{ color: 'var(--text-tertiary)', margin: '0 auto 10px auto' }} />
                <div style={{ fontSize: '14px', fontWeight: 600, color: 'var(--text-primary)' }}>
                  No simulation executed yet for this draft revision
                </div>
                <p style={{ fontSize: '13px', color: 'var(--text-secondary)', maxWidth: '420px', margin: '6px auto 16px auto', lineHeight: 1.5 }}>
                  Execute a deterministic static dry-run to verify mock payload propagation and node output key generation through the graph.
                </p>
                <Button variant="primary" size="sm" onClick={handleRunSimulation}>
                  Start Safe Dry-Run
                </Button>
              </div>
            )}

            {simResult && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                {/* Disclaimer */}
                <div
                  style={{
                    padding: '12px 14px',
                    backgroundColor: 'rgba(234, 88, 12, 0.08)',
                    border: '1px solid rgba(234, 88, 12, 0.25)',
                    borderRadius: 'var(--radius-sm)',
                    fontSize: '13px',
                    color: 'var(--brand-primary)',
                    lineHeight: 1.4,
                  }}
                >
                  <strong>Safety Guarantee:</strong> {simResult.disclaimer}
                </div>

                {/* Metrics Header */}
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    padding: '12px 16px',
                    backgroundColor: 'var(--bg-surface-elevated)',
                    border: '1px solid var(--border-subtle)',
                    borderRadius: 'var(--radius-sm)',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <Badge variant={simResult.success ? 'success' : 'error'}>
                      {simResult.success ? 'SIMULATION PASSED' : 'SIMULATION BLOCKED'}
                    </Badge>
                    <span style={{ fontSize: '13px', color: 'var(--text-primary)' }}>
                      {simResult.passed_nodes} / {simResult.total_nodes} nodes simulated successfully
                    </span>
                  </div>
                  <span style={{ fontSize: '12px', fontFamily: 'var(--font-mono)', color: 'var(--text-tertiary)' }}>
                    Type: {simResult.execution_type}
                  </span>
                </div>

                {/* Step Results */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  {simResult.node_results.map((res, idx) => (
                    <div
                      key={res.node_id}
                      style={{
                        padding: '12px 14px',
                        backgroundColor: 'var(--bg-surface-elevated)',
                        border: '1px solid var(--border-subtle)',
                        borderRadius: 'var(--radius-sm)',
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                        <span style={{ fontSize: '14px', fontWeight: 600, color: 'var(--text-primary)' }}>
                          Step {idx + 1}: {res.node_name}
                        </span>
                        <Badge variant={res.status === 'simulated_success' ? 'success' : 'error'}>
                          {res.status === 'simulated_success' ? 'Simulated' : 'Blocked'}
                        </Badge>
                      </div>
                      <div style={{ fontSize: '13px', color: 'var(--text-secondary)', marginTop: '4px' }}>
                        {res.summary}
                      </div>
                      {res.sample_output_keys.length > 0 && (
                        <div style={{ marginTop: '8px', fontSize: '12px', color: 'var(--text-tertiary)', display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'wrap' }}>
                          <span>Sample Outputs:</span>
                          {res.sample_output_keys.map((k) => (
                            <span
                              key={k}
                              style={{
                                fontFamily: 'var(--font-mono)',
                                backgroundColor: 'var(--bg-app)',
                                padding: '2px 6px',
                                borderRadius: 'var(--radius-sm)',
                                color: 'var(--text-primary)',
                                fontSize: '11px',
                              }}
                            >
                              {k}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* ------------------------------------------------------------- */}
        {/* TAB 4: RESEARCH GROUNDING                                     */}
        {/* ------------------------------------------------------------- */}
        {!isLoading && activeTab === 'research' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            {/* 1. Research Status Callout Banner */}
            <div
              style={{
                padding: '16px 18px',
                backgroundColor:
                  researchStatusDetails.variant === 'success'
                    ? 'rgba(16, 185, 129, 0.08)'
                    : researchStatusDetails.variant === 'warning'
                    ? 'rgba(245, 158, 11, 0.08)'
                    : researchStatusDetails.variant === 'error'
                    ? 'rgba(239, 68, 68, 0.08)'
                    : 'rgba(59, 130, 246, 0.08)',
                border: `1px solid ${
                  researchStatusDetails.variant === 'success'
                    ? 'var(--state-success, #10B981)'
                    : researchStatusDetails.variant === 'warning'
                    ? 'var(--state-warning, #F59E0B)'
                    : researchStatusDetails.variant === 'error'
                    ? 'var(--state-error, #EF4444)'
                    : 'var(--state-info, #3B82F6)'
                }`,
                borderRadius: 'var(--radius-sm, 4px)',
                display: 'flex',
                alignItems: 'flex-start',
                gap: '14px',
              }}
            >
              <div style={{ marginTop: '2px', flexShrink: 0 }}>{researchStatusDetails.icon}</div>
              <div style={{ flex: 1 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
                  <h3 style={{ fontSize: '15px', fontWeight: 600, color: 'var(--text-primary)', margin: 0 }}>
                    {researchStatusDetails.headline}
                  </h3>
                  <Badge variant={researchStatusDetails.variant}>{researchStatusDetails.label}</Badge>
                </div>
                <p style={{ fontSize: '13px', color: 'var(--text-secondary)', margin: '6px 0 0', lineHeight: 1.5 }}>
                  {researchStatusDetails.description}
                </p>
              </div>
            </div>

            {/* 2. Target Services */}
            {activeDossier && activeDossier.target_services && activeDossier.target_services.length > 0 && (
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                <span style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-tertiary)' }}>Target Services:</span>
                {activeDossier.target_services.map((svc: string) => (
                  <span
                    key={svc}
                    style={{
                      fontSize: '12px',
                      padding: '2px 8px',
                      borderRadius: 'var(--radius-sm)',
                      backgroundColor: 'rgba(234, 88, 12, 0.12)',
                      color: 'var(--brand-primary)',
                      fontWeight: 500,
                    }}
                  >
                    {svc}
                  </span>
                ))}
              </div>
            )}

            {/* 3. Consulted Sources (with safe clickable links and authority/relevance info) */}
            {activeDossier && activeDossier.sources && activeDossier.sources.length > 0 && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                <span style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-primary)' }}>
                  Authoritative Sources Consulted ({activeDossier.sources.length})
                </span>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  {activeDossier.sources.map((src: any, idx: number) => {
                    const isSafeUrl = Boolean(src.url && /^https?:\/\//i.test(src.url));
                    const authorityLabel =
                      src.domain_authority === 'official_docs'
                        ? 'Official Documentation'
                        : src.domain_authority === 'community'
                        ? 'Community Reference'
                        : 'Web Reference';

                    return (
                      <div
                        key={src.url || idx}
                        style={{
                          padding: '12px 14px',
                          backgroundColor: 'var(--bg-app, #0B0F17)',
                          border: '1px solid var(--border-subtle, #1F2937)',
                          borderRadius: 'var(--radius-sm, 4px)',
                          display: 'flex',
                          flexDirection: 'column',
                          gap: '6px',
                        }}
                      >
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '8px' }}>
                          {isSafeUrl ? (
                            <a
                              href={src.url}
                              target="_blank"
                              rel="noopener noreferrer"
                              style={{
                                fontSize: '13px',
                                fontWeight: 600,
                                color: 'var(--state-info, #3B82F6)',
                                textDecoration: 'none',
                                display: 'inline-flex',
                                alignItems: 'center',
                                gap: '4px',
                              }}
                            >
                              <span>{src.title || src.url}</span>
                              <ExternalLink size={12} />
                            </a>
                          ) : (
                            <span style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-primary)' }}>
                              {src.title || src.url || 'Documentation Reference'}
                            </span>
                          )}

                          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                            <span
                              style={{
                                fontSize: '11px',
                                padding: '2px 6px',
                                borderRadius: '4px',
                                fontWeight: 500,
                                backgroundColor:
                                  src.domain_authority === 'official_docs'
                                    ? 'rgba(16, 185, 129, 0.15)'
                                    : 'rgba(156, 163, 175, 0.15)',
                                color:
                                  src.domain_authority === 'official_docs'
                                    ? 'var(--state-success, #10B981)'
                                    : 'var(--text-secondary, #9CA3AF)',
                              }}
                            >
                              {authorityLabel}
                            </span>
                            {typeof src.relevance_score === 'number' && src.relevance_score > 0 && (
                              <span
                                style={{
                                  fontSize: '11px',
                                  padding: '2px 6px',
                                  borderRadius: '4px',
                                  backgroundColor: 'rgba(59, 130, 246, 0.12)',
                                  color: 'var(--state-info, #3B82F6)',
                                  fontWeight: 500,
                                }}
                              >
                                Relevance: {Math.round(src.relevance_score * 100)}%
                              </span>
                            )}
                            {src.version_hint && (
                              <span
                                style={{
                                  fontSize: '11px',
                                  padding: '2px 6px',
                                  borderRadius: '4px',
                                  backgroundColor: 'var(--bg-surface-elevated)',
                                  color: 'var(--text-tertiary)',
                                  fontFamily: 'var(--font-mono)',
                                }}
                              >
                                v{src.version_hint}
                              </span>
                            )}
                          </div>
                        </div>
                        {src.snippet && (
                          <p style={{ fontSize: '12px', color: 'var(--text-secondary)', margin: 0, lineHeight: 1.4 }}>
                            {src.snippet}
                          </p>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {/* 4. Verified Technical Facts & Requirements */}
            {activeDossier && activeDossier.documented_facts && activeDossier.documented_facts.length > 0 && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                <span style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-primary)' }}>
                  Verified Technical Facts &amp; Requirements ({activeDossier.documented_facts.length})
                </span>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                  {activeDossier.documented_facts.map((fact: any, idx: number) => (
                    <div
                      key={idx}
                      style={{
                        padding: '10px 12px',
                        backgroundColor: 'var(--bg-app)',
                        border: '1px solid var(--border-subtle)',
                        borderRadius: 'var(--radius-sm)',
                        display: 'flex',
                        alignItems: 'flex-start',
                        gap: '8px',
                      }}
                    >
                      <CheckCircle2 size={16} style={{ color: 'var(--state-success)', flexShrink: 0, marginTop: '2px' }} />
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '2px', flex: 1 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                          {fact.topic && (
                            <span style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-primary)' }}>
                              {fact.topic}
                            </span>
                          )}
                          <span style={{ fontSize: '11px', color: 'var(--text-tertiary)', textTransform: 'uppercase' }}>
                            [{fact.category}]
                          </span>
                          {fact.n8n_node_type && (
                            <span style={{ fontSize: '11px', color: 'var(--brand-primary)', fontFamily: 'var(--font-mono)' }}>
                              Verified in catalog: ({fact.n8n_node_type})
                            </span>
                          )}
                        </div>
                        <span style={{ fontSize: '12px', color: 'var(--text-secondary)', lineHeight: 1.4 }}>
                          {fact.fact}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* 5. Inferred Architectural Assumptions (Separated from verified facts) */}
            {activeDossier && activeDossier.assumptions && activeDossier.assumptions.length > 0 && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                <span style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-primary)' }}>
                  Inferred Architectural Assumptions ({activeDossier.assumptions.length})
                </span>
                <div
                  style={{
                    padding: '12px 14px',
                    backgroundColor: 'rgba(59, 130, 246, 0.06)',
                    border: '1px solid rgba(59, 130, 246, 0.25)',
                    borderRadius: 'var(--radius-sm)',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '6px',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '2px' }}>
                    <HelpCircle size={15} style={{ color: 'var(--state-info, #3B82F6)' }} />
                    <span style={{ fontSize: '12px', fontWeight: 600, color: 'var(--state-info, #3B82F6)' }}>
                      Assumptions made where documentation did not specify exact parameter defaults:
                    </span>
                  </div>
                  {activeDossier.assumptions.map((item: string, idx: number) => (
                    <div key={idx} style={{ fontSize: '12px', color: 'var(--text-secondary)', lineHeight: 1.4, paddingLeft: '20px' }}>
                      • {item}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* 6. Unresolved Requirements & Setup Items (Separated from verified facts) */}
            {activeDossier && activeDossier.unresolved_questions && activeDossier.unresolved_questions.length > 0 && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                <span style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-primary)' }}>
                  Unresolved Requirements &amp; Setup Actions ({activeDossier.unresolved_questions.length})
                </span>
                <div
                  style={{
                    padding: '12px 14px',
                    backgroundColor: 'rgba(245, 158, 11, 0.08)',
                    border: '1px solid var(--state-warning, #F59E0B)',
                    borderRadius: 'var(--radius-sm)',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '6px',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '2px' }}>
                    <AlertTriangle size={15} style={{ color: 'var(--state-warning, #F59E0B)' }} />
                    <span style={{ fontSize: '12px', fontWeight: 600, color: 'var(--state-warning, #F59E0B)' }}>
                      The following requirements require manual credentials or user configuration:
                    </span>
                  </div>
                  {activeDossier.unresolved_questions.map((q: string, idx: number) => (
                    <div key={idx} style={{ fontSize: '12px', color: 'var(--text-secondary)', lineHeight: 1.4, paddingLeft: '20px' }}>
                      • {q}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* 7. Research Limitations & Fallbacks */}
            {activeDossier && activeDossier.warnings && activeDossier.warnings.length > 0 && (
              <div
                style={{
                  padding: '12px 14px',
                  backgroundColor: 'rgba(245, 158, 11, 0.08)',
                  border: '1px solid var(--state-warning, #F59E0B)',
                  borderRadius: 'var(--radius-sm)',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '4px',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <AlertTriangle size={14} style={{ color: 'var(--state-warning, #F59E0B)' }} />
                  <span style={{ fontSize: '12px', fontWeight: 600, color: 'var(--state-warning)' }}>
                    Research Limitations &amp; Fallbacks
                  </span>
                </div>
                {activeDossier.warnings.map((w: string, idx: number) => (
                  <span key={idx} style={{ fontSize: '12px', color: 'var(--text-secondary)', paddingLeft: '20px' }}>
                    • {w}
                  </span>
                ))}
              </div>
            )}

            {/* 8. Architectural Blueprint (Matching generated workflow) */}
            {activePlan && (
              <div
                style={{
                  padding: '16px',
                  backgroundColor: 'var(--bg-app)',
                  border: '1px solid var(--border-subtle)',
                  borderRadius: 'var(--radius-sm)',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '12px',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '8px' }}>
                  <span style={{ fontSize: '14px', fontWeight: 600, color: 'var(--text-primary)' }}>
                    Architectural Blueprint ({activePlan.title || 'Workflow Architecture'})
                  </span>
                  <Badge variant="info">Grounded Blueprint</Badge>
                </div>

                <div style={{ fontSize: '12px', color: 'var(--text-secondary)', display: 'flex', flexDirection: 'column', gap: '6px' }}>
                  <div><strong>Objective:</strong> {activePlan.objective}</div>
                  <div><strong>Fault Tolerance Strategy:</strong> {activePlan.error_handling_strategy}</div>
                </div>

                {/* Planned Nodes List */}
                {activePlan.nodes && activePlan.nodes.length > 0 && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', marginTop: '4px' }}>
                    <span style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-tertiary)' }}>
                      Planned Nodes ({activePlan.nodes.length}):
                    </span>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))', gap: '8px' }}>
                      {activePlan.nodes.map((node: any, idx: number) => (
                        <div
                          key={node.id || idx}
                          style={{
                            padding: '10px 12px',
                            backgroundColor: 'var(--bg-surface-elevated)',
                            border: '1px solid var(--border-subtle)',
                            borderRadius: 'var(--radius-sm)',
                            display: 'flex',
                            flexDirection: 'column',
                            gap: '4px',
                          }}
                        >
                          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '6px' }}>
                            <span style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-primary)' }}>{node.name}</span>
                            <span
                              style={{
                                fontSize: '10px',
                                textTransform: 'uppercase',
                                padding: '1px 5px',
                                borderRadius: '3px',
                                backgroundColor: 'rgba(234, 88, 12, 0.15)',
                                color: 'var(--brand-primary)',
                                fontWeight: 600,
                              }}
                            >
                              {node.role}
                            </span>
                          </div>
                          <span style={{ fontSize: '11px', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)' }}>
                            {node.node_type}
                          </span>
                          {node.operation && (
                            <span style={{ fontSize: '11px', color: 'var(--text-tertiary)' }}>
                              Op: <em>{node.operation}</em>
                            </span>
                          )}
                          {node.credential_type && (
                            <span style={{ fontSize: '11px', color: 'var(--state-warning)' }}>
                              Cred: {node.credential_type}
                            </span>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Planned Connections / Data Flow */}
                {activePlan.connections && activePlan.connections.length > 0 && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', marginTop: '4px' }}>
                    <span style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-tertiary)' }}>
                      Planned Graph Flow ({activePlan.connections.length} edges):
                    </span>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                      {activePlan.connections.map((edge: any, idx: number) => {
                        const srcNode = activePlan.nodes?.find((n: any) => n.id === edge.source_id);
                        const tgtNode = activePlan.nodes?.find((n: any) => n.id === edge.target_id);
                        const srcName = srcNode?.name || edge.source_id;
                        const tgtName = tgtNode?.name || edge.target_id;
                        return (
                          <div
                            key={idx}
                            style={{
                              fontSize: '11px',
                              color: 'var(--text-secondary)',
                              display: 'flex',
                              alignItems: 'center',
                              gap: '6px',
                              fontFamily: 'var(--font-mono)',
                            }}
                          >
                            <span style={{ color: 'var(--text-primary)' }}>{srcName}</span>
                            <span style={{ color: 'var(--brand-primary)' }}>→</span>
                            <span style={{ color: 'var(--text-primary)' }}>{tgtName}</span>
                            {edge.condition_desc && (
                              <span style={{ color: 'var(--text-tertiary)', fontStyle: 'italic' }}>
                                ({edge.condition_desc})
                              </span>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* 9. Graceful fallback for older drafts */}
            {!activeDossier && !activePlan && (
              <div style={{ textAlign: 'center', padding: '36px 16px', color: 'var(--text-secondary)', fontSize: '13px' }}>
                No external web research dossier or architectural blueprint is stored with this draft. Installed built-in node definitions (n8n v2.42.6) were used.
              </div>
            )}
          </div>
        )}

        {/* ------------------------------------------------------------- */}
        {/* TAB 5: COMPILED N8N JSON                                      */}
        {/* ------------------------------------------------------------- */}
        {!isLoading && activeTab === 'json' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '8px' }}>
              <span style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>
                Native n8n workflow definition compiled from canonical IR schema (v2.42.6):
              </span>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={handleCopyJson}
                style={{ fontSize: '12px', padding: '4px 10px', display: 'flex', alignItems: 'center', gap: '6px' }}
              >
                {isCopiedJson ? <Check size={13} style={{ color: 'var(--state-success)' }} /> : <Copy size={13} />}
                <span>{isCopiedJson ? 'Copied to clipboard' : 'Copy JSON'}</span>
              </button>
            </div>
            <pre
              style={{
                backgroundColor: 'var(--bg-code, #0B0F17)',
                color: 'var(--text-code, #E2E8F0)',
                fontFamily: 'var(--font-mono, monospace)',
                fontSize: '12px',
                padding: '16px',
                borderRadius: 'var(--radius-sm, 4px)',
                maxHeight: '440px',
                overflowY: 'auto',
                border: '1px solid var(--border-subtle, #1F2937)',
                lineHeight: 1.5,
              }}
            >
              {JSON.stringify(compiledJson || workflow, null, 2)}
            </pre>
          </div>
        )}
      </div>

      {/* 4. Real n8n Deployment Modal */}
      {showApprovalModal && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            zIndex: 100,
            backgroundColor: 'rgba(11, 15, 23, 0.85)',
            backdropFilter: 'blur(4px)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '20px',
          }}
        >
          <div
            style={{
              width: '540px',
              maxWidth: '100%',
              backgroundColor: 'var(--bg-surface, #111827)',
              border: '1px solid var(--border-default, #374151)',
              borderRadius: 'var(--radius-md, 6px)',
              boxShadow: 'var(--shadow-xl)',
              overflow: 'hidden',
            }}
          >
            {/* Modal Header */}
            <div
              style={{
                padding: '16px 20px',
                borderBottom: '1px solid var(--border-subtle)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <Server size={18} style={{ color: 'var(--brand-primary, #EA580C)' }} />
                <span style={{ fontSize: '15px', fontWeight: 600, color: 'var(--text-primary)' }}>
                  {deployResult ? 'Deployment Confirmed' : 'Deploy Workflow to n8n'}
                </span>
              </div>
              <button
                type="button"
                onClick={() => {
                  setShowApprovalModal(false);
                  setDeployError(null);
                }}
                style={{ background: 'transparent', border: 'none', color: 'var(--text-tertiary)', cursor: 'pointer' }}
                aria-label="Close"
              >
                <X size={16} />
              </button>
            </div>

            {/* Modal Body */}
            <div style={{ padding: '20px', display: 'flex', flexDirection: 'column', gap: '14px' }}>
              {deployResult ? (
                /* SUCCESS STATE */
                <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
                  <div
                    style={{
                      padding: '14px 16px',
                      backgroundColor: 'rgba(16, 185, 129, 0.08)',
                      border: '1px solid var(--state-success, #10B981)',
                      borderRadius: 'var(--radius-sm)',
                      display: 'flex',
                      alignItems: 'flex-start',
                      gap: '12px',
                    }}
                  >
                    <CheckCircle2 size={20} style={{ color: 'var(--state-success)', marginTop: '2px', flexShrink: 0 }} />
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                      <div style={{ fontSize: '14px', fontWeight: 600, color: 'var(--text-primary)' }}>
                        Workflow Created in n8n (Inactive)
                      </div>
                      <div style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>
                        The workflow was successfully created on your local n8n instance.
                      </div>
                    </div>
                  </div>

                  <div
                    style={{
                      padding: '12px 14px',
                      backgroundColor: 'var(--bg-surface-elevated)',
                      border: '1px solid var(--border-subtle)',
                      borderRadius: 'var(--radius-sm)',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '8px',
                      fontSize: '13px',
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span style={{ color: 'var(--text-tertiary)' }}>Workflow Name:</span>
                      <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{deployResult.workflow_name}</span>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span style={{ color: 'var(--text-tertiary)' }}>n8n Workflow ID:</span>
                      <span style={{ fontWeight: 600, fontFamily: 'var(--font-mono)', color: 'var(--brand-primary)' }}>
                        {deployResult.workflow_id}
                      </span>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span style={{ color: 'var(--text-tertiary)' }}>Revision Deployed:</span>
                      <span style={{ color: 'var(--text-primary)' }}>#{deployResult.revision_number}</span>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span style={{ color: 'var(--text-tertiary)' }}>Execution State:</span>
                      <span style={{ color: 'var(--state-warning)', fontWeight: 600 }}>Inactive (active: false)</span>
                    </div>
                  </div>

                  <div
                    style={{
                      padding: '10px 12px',
                      backgroundColor: 'rgba(245, 158, 11, 0.08)',
                      border: '1px solid rgba(245, 158, 11, 0.3)',
                      borderRadius: 'var(--radius-sm)',
                      fontSize: '12px',
                      color: 'var(--text-secondary)',
                      lineHeight: 1.4,
                    }}
                  >
                    <strong>Safety Notice:</strong> Workflows are created as inactive. Review credentials and trigger parameters in n8n before activating.
                  </div>
                </div>
              ) : (
                /* PRE-DEPLOYMENT APPROVAL FORM */
                <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                  <div
                    style={{
                      padding: '12px 14px',
                      backgroundColor: 'var(--bg-surface-elevated)',
                      border: '1px solid var(--border-subtle)',
                      borderRadius: 'var(--radius-sm)',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '8px',
                      fontSize: '13px',
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span style={{ color: 'var(--text-tertiary)' }}>Workflow Name:</span>
                      <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{workflow.name || 'Untitled Automation'}</span>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span style={{ color: 'var(--text-tertiary)' }}>Target n8n Instance:</span>
                      <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-primary)' }}>http://localhost:5678</span>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span style={{ color: 'var(--text-tertiary)' }}>Saved Revision:</span>
                      <span style={{ color: 'var(--text-primary)' }}>Revision #{currentRevisionNumber}</span>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span style={{ color: 'var(--text-tertiary)' }}>Initial Execution State:</span>
                      <span style={{ color: 'var(--state-warning)', fontWeight: 600 }}>Inactive (Safe)</span>
                    </div>
                  </div>

                  {/* Unsaved Edits Warning */}
                  {isDirty && (
                    <div
                      style={{
                        padding: '10px 12px',
                        backgroundColor: 'rgba(239, 68, 68, 0.08)',
                        border: '1px solid var(--state-error)',
                        borderRadius: 'var(--radius-sm)',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        gap: '8px',
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                        <AlertTriangle size={15} style={{ color: 'var(--state-error)' }} />
                        <span style={{ fontSize: '13px', color: 'var(--state-error)', fontWeight: 600 }}>
                          Unsaved changes detected
                        </span>
                      </div>
                      {onSaveRevision && (
                        <button
                          type="button"
                          className="btn btn-secondary btn-sm"
                          onClick={() => {
                            onSaveRevision();
                            setShowApprovalModal(false);
                          }}
                          style={{ fontSize: '12px', padding: '4px 8px' }}
                        >
                          Save Revision First
                        </button>
                      )}
                    </div>
                  )}

                  {/* Missing Configuration Warning */}
                  {report && (!report.is_configuration_complete || (report.unresolved_configuration && report.unresolved_configuration.length > 0)) && (
                    <div
                      style={{
                        padding: '10px 12px',
                        backgroundColor: 'rgba(245, 158, 11, 0.08)',
                        border: '1px solid var(--state-warning)',
                        borderRadius: 'var(--radius-sm)',
                        display: 'flex',
                        flexDirection: 'column',
                        gap: '4px',
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                        <AlertTriangle size={15} style={{ color: 'var(--state-warning)' }} />
                        <span style={{ fontSize: '13px', color: 'var(--state-warning)', fontWeight: 600 }}>
                          Missing Required Configuration
                        </span>
                      </div>
                      <div style={{ fontSize: '12px', color: 'var(--text-secondary)', lineHeight: 1.4 }}>
                        The following parameters must be configured before deployment:
                      </div>
                      <ul style={{ margin: '4px 0 0', paddingLeft: '18px', fontSize: '12px', color: 'var(--text-primary)' }}>
                        {report.unresolved_configuration?.map((item, idx) => (
                          <li key={idx}>{item}</li>
                        )) || <li>Unconfigured node parameters</li>}
                      </ul>
                    </div>
                  )}

                  {/* Deployment Error Notice */}
                  {deployError && (
                    <div
                      style={{
                        padding: '10px 12px',
                        backgroundColor: 'rgba(239, 68, 68, 0.08)',
                        border: '1px solid var(--state-error)',
                        borderRadius: 'var(--radius-sm)',
                        fontSize: '13px',
                        color: 'var(--state-error)',
                        lineHeight: 1.4,
                      }}
                    >
                      <strong>Deployment Failed:</strong> {deployError}
                    </div>
                  )}

                  {/* Safety Notice */}
                  <div style={{ fontSize: '12px', color: 'var(--text-secondary)', lineHeight: 1.4 }}>
                    • Credentials for external services must be configured in n8n.
                    <br />
                    • The workflow will be created as <strong>inactive</strong> and will not execute until explicitly activated in n8n.
                  </div>

                  {/* Acknowledgment Checkbox */}
                  <label
                    style={{
                      display: 'flex',
                      alignItems: 'flex-start',
                      gap: '10px',
                      padding: '10px 12px',
                      backgroundColor: 'var(--bg-surface-elevated)',
                      border: '1px solid var(--border-subtle)',
                      borderRadius: 'var(--radius-sm)',
                      cursor: 'pointer',
                    }}
                  >
                    <input
                      type="checkbox"
                      checked={hasAcknowledgedInactive}
                      onChange={(e) => setHasAcknowledgedInactive(e.target.checked)}
                      style={{ marginTop: '2px' }}
                    />
                    <span style={{ fontSize: '12px', color: 'var(--text-primary)', lineHeight: 1.4 }}>
                      I confirm that I have reviewed the configuration. I understand that creating the workflow creates it as inactive and does not trigger live runs.
                    </span>
                  </label>
                </div>
              )}
            </div>

            {/* Modal Footer */}
            <div
              style={{
                padding: '14px 20px',
                borderTop: '1px solid var(--border-subtle)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'flex-end',
                gap: '10px',
              }}
            >
              {deployResult ? (
                <>
                  <a
                    href={deployResult.workflow_url || `http://localhost:5678/workflow/${deployResult.workflow_id}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="btn btn-secondary btn-sm"
                    style={{ display: 'flex', alignItems: 'center', gap: '6px', textDecoration: 'none', fontSize: '13px' }}
                  >
                    <ExternalLink size={14} />
                    <span>Open in n8n</span>
                  </a>
                  <Button
                    variant="primary"
                    size="sm"
                    onClick={() => {
                      setShowApprovalModal(false);
                      setDeployResult(null);
                      if (onClose) onClose();
                    }}
                  >
                    Done
                  </Button>
                </>
              ) : (
                <>
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    onClick={() => {
                      setShowApprovalModal(false);
                      setDeployError(null);
                    }}
                    disabled={isDeploying}
                    style={{ fontSize: '13px' }}
                  >
                    Cancel
                  </button>
                  <Button
                    variant="primary"
                    size="sm"
                    disabled={
                      isDeploying ||
                      isDirty ||
                      !hasAcknowledgedInactive ||
                      !(report?.is_deployment_ready ?? false) ||
                      hasMissingOrInvalidCreds
                    }
                    onClick={async () => {
                      if (!conversationId || isDeploying) return;
                      setIsDeploying(true);
                      setDeployError(null);
                      try {
                        const token = `deploy-${conversationId}-${currentRevisionNumber}-${Date.now()}`;
                        const res = await deployWorkflowDraft(conversationId, currentRevisionNumber, token);
                        setDeployResult(res);
                        if (onDeployed) {
                          onDeployed(res);
                        }
                      } catch (err: any) {
                        setDeployError(err.message || 'Workflow deployment failed.');
                      } finally {
                        setIsDeploying(false);
                      }
                    }}
                  >
                    {isDeploying ? (
                      <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                        <OrbitLoader size="inline" color="currentColor" />
                        <span>Deploying to n8n...</span>
                      </span>
                    ) : (
                      'Confirm & Deploy to n8n'
                    )}
                  </Button>
                </>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
