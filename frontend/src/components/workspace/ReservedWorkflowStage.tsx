import React, { useState, useEffect, useMemo } from 'react';
import { Button } from '../ui/Button';
import {
  HelpCircle,
  AlertTriangle,
  Send,
  RotateCcw,
  Sparkles,
  MessageSquare,
  Check,
  Clock,
  Edit2,
  X,
  ArrowLeft,
  Globe,
} from 'lucide-react';
import type { ClarificationAnswerItem, ClarificationQuestion, OrchestratorTurnResult } from '../../api/conversations';
import { WorkflowCanvas } from '../canvas/WorkflowCanvas';
import { MarkdownRenderer } from '../common/MarkdownRenderer';
import { OrbitLoader } from '../common/OrbitLoader';

export type StageState =
  | 'idle'
  | 'loading'
  | 'understanding'
  | 'researching'
  | 'checking'
  | 'saving_answer'
  | 'clarifying'
  | 'building'
  | 'validating'
  | 'ready'
  | 'failed'
  | 'timed_out'
  | 'planning'
  | 'generating'
  | 'no_draft';

interface ReservedWorkflowStageProps {
  stageState: StageState;
  activePrompt?: string;
  turnResult?: OrchestratorTurnResult | null;
  errorMessage?: string | null;
  backendStage?: string | null;
  backendStatusMessage?: string | null;
  elapsedSeconds?: number | null;
  onAnswerClarification?: (
    answerText: string,
    selectedOptions?: Record<string, string>,
    clarificationAnswers?: ClarificationAnswerItem[]
  ) => void;
  onRetry?: () => void;
  onRevisionSaved?: (savedRevision: any) => void;
  onStartOver?: () => void;
  onBackToDrafts?: () => void;
  onSubmitPrompt?: (prompt: string) => void;
  isSubmitting?: boolean;
}

export const ReservedWorkflowStage: React.FC<ReservedWorkflowStageProps> = ({
  stageState,
  activePrompt,
  turnResult,
  errorMessage,
  backendStage,
  backendStatusMessage,
  elapsedSeconds,
  onAnswerClarification,
  onRetry,
  onRevisionSaved,
  onStartOver,
  onBackToDrafts,
  onSubmitPrompt,
  isSubmitting = false,
}) => {
  const [selectedAnswers, setSelectedAnswers] = useState<Record<string, string>>({});
  const [customAnswers, setCustomAnswers] = useState<Record<string, string>>({});
  const [showOtherInput, setShowOtherInput] = useState<Record<string, boolean>>({});
  const [freeformInstructions, setFreeformInstructions] = useState('');
  const [formErrors, setFormErrors] = useState<Record<string, string>>({});
  const [editingSlot, setEditingSlot] = useState<string | null>(null);
  const [editSlotValue, setEditSlotValue] = useState('');
  const [localPending, setLocalPending] = useState(false);

  const [lastTrackedKey, setLastTrackedKey] = useState<string>(`${stageState}_${turnResult?.conversation_id || ''}`);

  const currentKey = `${stageState}_${turnResult?.conversation_id || ''}`;
  if (lastTrackedKey !== currentKey) {
    setLastTrackedKey(currentKey);
    setLocalPending(false);
  }

  // Authoritative deduplicated questions list by stable question ID
  const uniqueQuestions: ClarificationQuestion[] = useMemo(() => {
    const rawQuestions = turnResult?.clarification?.questions || [];
    const seen = new Set<string>();
    const res: ClarificationQuestion[] = [];
    rawQuestions.forEach((q) => {
      const key = q.id || q.field_key;
      if (!seen.has(key)) {
        seen.add(key);
        res.push(q);
      }
    });
    return res;
  }, [turnResult?.clarification?.questions]);

  // Global sequential question numbering across all groups
  const questionNumberMap = useMemo(() => {
    const map = new Map<string, number>();
    uniqueQuestions.forEach((q, idx) => {
      map.set(q.id, idx + 1);
    });
    return map;
  }, [uniqueQuestions]);

  // Pre-fill answers from turnResult while preserving existing user input
  useEffect(() => {
    if (uniqueQuestions.length === 0) return;
    setSelectedAnswers((prev) => {
      const next = { ...prev };
      uniqueQuestions.forEach((q) => {
        if (!next[q.id]) {
          const preVal =
            q.current_value ||
            q.default_value ||
            turnResult?.completed_answers?.[q.field_key] ||
            turnResult?.completed_answers?.[q.id];
          if (preVal && typeof preVal === 'string') {
            const hasOpt = q.options?.some((o) => o.value === preVal);
            if (hasOpt) {
              next[q.id] = preVal;
            }
          }
        }
      });
      return next;
    });

    setCustomAnswers((prev) => {
      const next = { ...prev };
      uniqueQuestions.forEach((q) => {
        if (!next[q.id]) {
          const preVal =
            q.current_value ||
            q.default_value ||
            turnResult?.completed_answers?.[q.field_key] ||
            turnResult?.completed_answers?.[q.id];
          if (preVal && typeof preVal === 'string') {
            const hasOpt = q.options?.some((o) => o.value === preVal);
            if (!hasOpt) {
              next[q.id] = preVal;
            }
          }
        }
      });
      return next;
    });
  }, [uniqueQuestions, turnResult?.completed_answers]);

  const handleOptionSelect = (questionId: string, optValue: string) => {
    if (isSubmitting || localPending) return;

    // Clear any previous error on this question
    setFormErrors((prev) => {
      const next = { ...prev };
      delete next[questionId];
      return next;
    });

    setSelectedAnswers((prev) => ({
      ...prev,
      [questionId]: optValue,
    }));

    if (optValue === 'other') {
      setShowOtherInput((prev) => ({ ...prev, [questionId]: true }));
    } else {
      setShowOtherInput((prev) => ({ ...prev, [questionId]: false }));
    }
  };

  const handleSubmitBatchAnswers = (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!onAnswerClarification || isSubmitting || localPending) return;

    const questions = uniqueQuestions;
    const errors: Record<string, string> = {};
    const clarificationAnswers: ClarificationAnswerItem[] = [];
    const selectedOptionsMap: Record<string, string> = {};

    for (const q of questions) {
      const selVal = selectedAnswers[q.id];
      const customTxt = (customAnswers[q.id] || '').trim();
      const isReq = q.required ?? q.is_required ?? true;

      // 1. Required check
      if (isReq && !selVal && !customTxt) {
        errors[q.id] = `Please provide an answer for "${q.question}".`;
        continue;
      }

      // 2. 'Other' custom text check
      if (selVal === 'other' && !customTxt) {
        errors[q.id] = 'Please enter your custom answer.';
        continue;
      }

      const effectiveVal = selVal === 'other' ? customTxt : (customTxt || selVal || '');

      // 3. Format and semantic validation derived from validation_rules and input_type
      const rules = q.validation_rules || {};

      if (rules.reject_pattern && effectiveVal) {
        try {
          const regex = new RegExp(rules.reject_pattern, 'i');
          if (regex.test(effectiveVal)) {
            errors[q.id] =
              rules.reject_message ||
              "Bot usernames ending in 'bot' cannot receive personal notifications. Enter your numeric Chat ID or channel username.";
            continue;
          }
        } catch {
          // ignore invalid regex pattern
        }
      }

      if (rules.pattern && effectiveVal) {
        try {
          const regex = new RegExp(rules.pattern);
          if (!regex.test(effectiveVal)) {
            errors[q.id] = rules.pattern_message || `Please provide a valid format for "${q.question}".`;
            continue;
          }
        } catch {
          // ignore invalid regex pattern
        }
      }

      if ((rules.format === 'url_or_id' || q.input_type === 'url') && effectiveVal) {
        const isUrl = /^https?:\/\/.+/i.test(effectiveVal);
        const isAlphanumericId = /^[a-zA-Z0-9-_]{10,}$/.test(effectiveVal);
        if (!isUrl && !isAlphanumericId) {
          errors[q.id] = 'Please enter a valid spreadsheet URL (e.g. https://docs.google.com/spreadsheets/d/...) or ID.';
          continue;
        }
      }

      if (rules.format === 'telegram_destination' && effectiveVal) {
        if (effectiveVal.toLowerCase().endsWith('bot')) {
          errors[q.id] = "Bot usernames ending in 'bot' cannot receive personal notifications. Enter your numeric Chat ID or channel username.";
          continue;
        }
        const isChatId =
          /^-?\d{5,15}$/.test(effectiveVal) ||
          /^@[a-zA-Z0-9_]{4,32}$/.test(effectiveVal) ||
          ['private_chat', 'group', 'channel'].includes(effectiveVal);
        if (!isChatId) {
          errors[q.id] = 'Please enter a valid numeric Chat ID (e.g. 123456789) or public channel username (@mychannel).';
          continue;
        }
      }

      clarificationAnswers.push({
        question_id: q.id,
        field_key: q.field_key,
        selected_value: selVal || (customTxt ? 'other' : undefined),
        custom_text: customTxt || undefined,
      });

      if (effectiveVal) {
        if (selVal === 'other' && q.field_key === 'email_provider') {
          selectedOptionsMap['email_provider'] = 'imap';
          selectedOptionsMap['custom_provider'] = customTxt;
        } else {
          selectedOptionsMap[q.field_key] = effectiveVal;
        }
      }
    }

    if (Object.keys(errors).length > 0) {
      setFormErrors(errors);
      return;
    }

    setLocalPending(true);
    setFormErrors({});

    const summaryParts: string[] = [];
    questions.forEach((q) => {
      const opt = q.options?.find((o) => o.value === selectedAnswers[q.id]);
      const displayVal = selectedAnswers[q.id] === 'other'
        ? customAnswers[q.id]
        : (customAnswers[q.id] || opt?.label || selectedAnswers[q.id]);
      if (displayVal) {
        summaryParts.push(`${q.question}: ${displayVal}`);
      }
    });
    if (freeformInstructions.trim()) {
      summaryParts.push(freeformInstructions.trim());
    }

    const fullSummaryText = summaryParts.join('; ') || 'Confirmed clarification preferences';
    onAnswerClarification(fullSummaryText, selectedOptionsMap, clarificationAnswers);
  };

  const handleSaveEditedSlot = (slotKey: string, newValue: string) => {
    if (isSubmitting || localPending || !onAnswerClarification) return;
    const clean = newValue.trim();
    if (!clean) return;

    setLocalPending(true);
    setEditingSlot(null);
    onAnswerClarification(clean, { [slotKey]: clean });
  };

  if (stageState === 'idle') {
    return null;
  }

  // Strictly separate active workflow generation from fetching a saved draft
  const isGeneratingPhase = [
    'understanding',
    'researching',
    'checking',
    'saving_answer',
    'building',
    'validating',
    'planning',
    'generating',
  ].includes(stageState) || (isSubmitting && stageState !== 'loading');

  const effectiveStage = backendStage || stageState;

  const getLifecycleTitle = () => {
    switch (effectiveStage) {
      case 'understanding':
        return 'Understanding Requirements...';
      case 'researching':
        return 'Researching Technical Docs & APIs...';
      case 'checking':
        return 'Checking Required Parameters...';
      case 'saving_answer':
        return 'Saving Requirements...';
      case 'discovering_nodes':
      case 'node_discovery':
        return 'Discovering Installed Nodes...';
      case 'planning':
        return 'Planning Workflow Architecture...';
      case 'building':
      case 'generating':
        return 'Synthesizing Workflow...';
      case 'validating':
        return 'Validating Node Contracts & Graph...';
      default:
        return 'Processing Workflow...';
    }
  };

  const getLifecycleDescription = () => {
    switch (effectiveStage) {
      case 'understanding':
        return 'Analyzing request intent, triggers, data mappings, and credentials.';
      case 'researching':
        return 'Retrieving official API endpoints, parameters, and payloads via Tavily.';
      case 'checking':
        return 'Determining which inputs require clarification based on installed node definitions.';
      case 'saving_answer':
        return 'Saving your preferences and verifying graph compatibility.';
      case 'discovering_nodes':
      case 'node_discovery':
        return 'Searching installed node catalog for compatible trigger and action nodes.';
      case 'planning':
        return 'Designing trigger, actions, branch conditions, and transformation architecture.';
      case 'building':
      case 'generating':
        return 'Constructing Workflow IR and compiling nodes from verified schemas.';
      case 'validating':
        return 'Running structural linting, connection verification, and readiness checks.';
      default:
        return 'Executing turn without simulated delays.';
    }
  };

  const getStageLabel = (stage: string) => {
    switch (stage) {
      case 'understanding':
        return 'Understanding';
      case 'researching':
        return 'Web Research';
      case 'discovering_nodes':
      case 'node_discovery':
        return 'Node Discovery';
      case 'planning':
        return 'Architectural Planning';
      case 'generating':
      case 'building':
        return 'Workflow Synthesis';
      case 'validating':
        return 'Validation';
      case 'clarifying':
        return 'Clarification';
      case 'ready':
        return 'Ready for Review';
      default:
        return 'Processing';
    }
  };

  return (
    <div
      className="workflow-stage-container"
      style={{
        width: '100%',
        height: stageState === 'ready' ? '100%' : undefined,
        flex: stageState === 'ready' ? 1 : undefined,
        display: stageState === 'ready' ? 'flex' : undefined,
        flexDirection: stageState === 'ready' ? 'column' : undefined,
      }}
    >
      {/* 1. Loading Saved Draft State (Distinct from active generation) */}
      {stageState === 'loading' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px', alignItems: 'center', padding: '48px 24px' }}>
          <div
            className="card"
            style={{
              width: '100%',
              maxWidth: '560px',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              padding: '40px 24px',
              gap: '16px',
              textAlign: 'center',
            }}
          >
            <div style={{ position: 'relative', display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}>
              <OrbitLoader size="md" color="var(--brand-primary)" ariaLabel="Loading Saved Workflow..." />
            </div>

            <div>
              <h3 style={{ fontSize: '16px', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '6px' }}>
                Loading Saved Workflow...
              </h3>
              <p style={{ fontSize: '13px', color: 'var(--text-secondary)', margin: 0, lineHeight: 1.5 }}>
                Restoring workflow draft and revision history from PostgreSQL.
              </p>
            </div>
          </div>
        </div>
      )}

      {/* 2. Active Workflow Generation Phase (Only when actively running/generating) */}
      {isGeneratingPhase && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px', alignItems: 'center' }}>
          {/* Read-Only Context: User Request */}
          {activePrompt && (
            <div
              style={{
                width: '100%',
                maxWidth: '680px',
                backgroundColor: 'var(--bg-surface)',
                border: '1px solid var(--border-subtle)',
                borderRadius: 'var(--radius-md)',
                padding: '14px 18px',
                textAlign: 'left',
                boxShadow: 'var(--shadow-sm)',
              }}
            >
              <div
                style={{
                  fontSize: '11px',
                  fontWeight: 600,
                  color: 'var(--text-tertiary)',
                  textTransform: 'uppercase',
                  letterSpacing: '0.04em',
                  marginBottom: '4px',
                }}
              >
                Original Request
              </div>
              <div style={{ fontSize: '13px', color: 'var(--text-primary)', lineHeight: 1.5 }}>
                {activePrompt}
              </div>
            </div>
          )}

          <div
            className="card"
            style={{
              width: '100%',
              maxWidth: '680px',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              padding: '36px 24px',
              gap: '16px',
              textAlign: 'center',
            }}
          >
            <div style={{ position: 'relative', display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}>
              <OrbitLoader size="lg" color="var(--brand-primary)" ariaLabel="Processing automation request..." />
            </div>

            <div>
              <h3 style={{ fontSize: '16px', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '6px' }}>
                {getLifecycleTitle()}
              </h3>
              <p style={{ fontSize: '13px', color: 'var(--text-secondary)', maxWidth: '480px', margin: '0 auto', lineHeight: 1.5 }}>
                {backendStatusMessage || getLifecycleDescription()}
              </p>
            </div>

            {/* Stage Badge based on actual reported state */}
            <div
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '8px',
                padding: '5px 14px',
                borderRadius: 'var(--radius-full)',
                backgroundColor: 'var(--bg-surface-subtle)',
                border: '1px solid var(--border-subtle)',
                fontSize: '12px',
                color: 'var(--text-secondary)',
              }}
            >
              <span style={{ width: '7px', height: '7px', borderRadius: '50%', backgroundColor: 'var(--brand-primary)' }} />
              <span>
                Stage: <strong>{getStageLabel(effectiveStage)}</strong>
              </span>
            </div>

            {/* Reassurance for longer processing without fabricated percentage */}
            {typeof elapsedSeconds === 'number' && elapsedSeconds > 10 && (
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px',
                  fontSize: '12px',
                  color: 'var(--text-tertiary)',
                  marginTop: '4px',
                }}
              >
                <Clock size={12} />
                <span>Working on complex graph reasoning ({Math.round(elapsedSeconds)}s elapsed). Please hold on...</span>
              </div>
            )}
          </div>
        </div>
      )}

      {/* 2. Conversational Clarification State */}
      {stageState === 'clarifying' && turnResult && (
        <div
          className="card"
          style={{
            display: 'flex',
            flexDirection: 'column',
            gap: '20px',
            padding: '24px',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <HelpCircle size={18} style={{ color: 'var(--brand-primary)' }} />
              <h2 style={{ fontSize: '15px', fontWeight: 600, color: 'var(--text-primary)', margin: 0 }}>
                Clarification Needed
              </h2>
            </div>
            {onStartOver && (
              <Button
                variant="ghost"
                size="sm"
                onClick={onStartOver}
                icon={<RotateCcw size={13} />}
                disabled={isSubmitting || localPending}
              >
                Start over
              </Button>
            )}
          </div>

          {/* Conversation Bubble: User's Original Request */}
          {activePrompt && (
            <div
              style={{
                backgroundColor: 'var(--bg-surface-subtle)',
                border: '1px solid var(--border-subtle)',
                borderRadius: 'var(--radius-md)',
                padding: '12px 16px',
              }}
            >
              <div
                style={{
                  fontSize: '11px',
                  fontWeight: 600,
                  color: 'var(--text-tertiary)',
                  textTransform: 'uppercase',
                  letterSpacing: '0.04em',
                  marginBottom: '4px',
                }}
              >
                Your Request
              </div>
              <div style={{ fontSize: '13px', color: 'var(--text-primary)', lineHeight: 1.5 }}>
                {activePrompt}
              </div>
            </div>
          )}

          {/* Tavily Research Grounding Banner */}
          {turnResult?.research_dossier && !turnResult.research_dossier.is_fallback && turnResult.research_dossier.sources && turnResult.research_dossier.sources.length > 0 && (
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
                padding: '10px 14px',
                borderRadius: 'var(--radius-md)',
                backgroundColor: 'rgba(59, 130, 246, 0.08)',
                border: '1px solid rgba(59, 130, 246, 0.25)',
                fontSize: '12px',
                color: 'var(--text-secondary)',
              }}
            >
              <Globe size={15} style={{ color: 'var(--state-info, #3B82F6)', flexShrink: 0 }} />
              <span>
                <strong>Tavily Research Grounding:</strong> Consulted {turnResult.research_dossier.sources.length} authoritative documentation source(s) verified against 444 installed n8n node definitions.
              </span>
            </div>
          )}

          {/* Tavily Research Limitation / Fallback Notice */}
          {turnResult?.research_dossier && (turnResult.research_dossier.is_fallback || (turnResult.research_dossier.needs_research && (!turnResult.research_dossier.sources || turnResult.research_dossier.sources.length === 0) && (turnResult.research_dossier.warnings?.length ?? 0) > 0)) && (
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
                padding: '10px 14px',
                borderRadius: 'var(--radius-md)',
                backgroundColor: 'rgba(239, 68, 68, 0.08)',
                border: '1px solid rgba(239, 68, 68, 0.25)',
                fontSize: '12px',
                color: 'var(--text-secondary)',
              }}
            >
              <AlertTriangle size={15} style={{ color: 'var(--state-error, #EF4444)', flexShrink: 0 }} />
              <span>
                <strong>Research Fallback:</strong> External documentation search was unavailable ({turnResult.research_dossier.warnings?.[0] || 'API key unconfigured or query limitation'}). Planning proceeded using installed node definitions only.
              </span>
            </div>
          )}

          {/* Conversation Bubble: Assistant's Question with proper Markdown rendering */}
          <div
            style={{
              backgroundColor: 'rgba(234, 88, 12, 0.04)',
              border: '1px solid rgba(234, 88, 12, 0.25)',
              borderRadius: 'var(--radius-md)',
              padding: '14px 16px',
            }}
          >
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                fontSize: '11px',
                fontWeight: 600,
                color: 'var(--brand-primary)',
                textTransform: 'uppercase',
                letterSpacing: '0.04em',
                marginBottom: '8px',
              }}
            >
              <MessageSquare size={13} />
              <span>Assistant Question</span>
            </div>
            <MarkdownRenderer content={turnResult.assistant_message} />
          </div>

          {/* Answered Requirements (Read-only history with correction ability) */}
          {turnResult.completed_answers && Object.keys(turnResult.completed_answers).length > 0 && (
            <div
              style={{
                display: 'flex',
                flexDirection: 'column',
                gap: '8px',
                padding: '12px 16px',
                backgroundColor: 'var(--bg-surface-subtle)',
                borderRadius: 'var(--radius-md)',
                border: '1px solid var(--border-subtle)',
              }}
            >
              <span style={{ fontSize: '11px', fontWeight: 600, color: 'var(--text-tertiary)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                Answered Requirements
              </span>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                {Object.entries(turnResult.completed_answers).map(([k, v]) => (
                  <div
                    key={k}
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: '8px',
                      padding: '4px 10px',
                      backgroundColor: 'var(--bg-app)',
                      borderRadius: 'var(--radius-sm)',
                      border: '1px solid var(--border-default)',
                      fontSize: '12px',
                    }}
                  >
                    <Check size={12} style={{ color: 'var(--state-success)' }} />
                    <span>
                      <strong style={{ fontWeight: 600 }}>
                        {k === 'email_provider' ? 'Email Service' : k === 'telegram_chat_id' ? 'Telegram Destination' : k}:
                      </strong>{' '}
                      {String(v)}
                    </span>
                    <button
                      type="button"
                      onClick={() => {
                        setEditingSlot(editingSlot === k ? null : k);
                        setEditSlotValue(String(v));
                      }}
                      disabled={isSubmitting || localPending}
                      style={{
                        background: 'none',
                        border: 'none',
                        color: 'var(--brand-primary)',
                        cursor: 'pointer',
                        fontSize: '11px',
                        textDecoration: 'underline',
                        padding: '0 2px',
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: '2px',
                      }}
                      title={`Change ${k}`}
                    >
                      <Edit2 size={10} />
                      <span>Change</span>
                    </button>
                  </div>
                ))}
              </div>

              {/* Inline Editor for Changing a Previous Answer */}
              {editingSlot && (
                <div
                  style={{
                    marginTop: '8px',
                    padding: '12px',
                    backgroundColor: 'var(--bg-app)',
                    borderRadius: 'var(--radius-sm)',
                    border: '1px solid var(--border-default)',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '10px',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-primary)' }}>
                      Update value for {editingSlot}:
                    </span>
                    <button
                      type="button"
                      onClick={() => setEditingSlot(null)}
                      style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-tertiary)' }}
                    >
                      <X size={14} />
                    </button>
                  </div>
                  <div style={{ display: 'flex', gap: '8px' }}>
                    <input
                      type="text"
                      value={editSlotValue}
                      onChange={(e) => setEditSlotValue(e.target.value)}
                      placeholder={`Enter new value for ${editingSlot}...`}
                      disabled={isSubmitting || localPending}
                      style={{
                        flex: 1,
                        padding: '6px 10px',
                        fontSize: '13px',
                        borderRadius: 'var(--radius-sm)',
                        border: '1px solid var(--border-default)',
                        backgroundColor: 'var(--bg-surface-subtle)',
                        color: 'var(--text-primary)',
                      }}
                      autoFocus
                    />
                    <Button
                      type="button"
                      variant="primary"
                      size="sm"
                      onClick={() => handleSaveEditedSlot(editingSlot, editSlotValue)}
                      disabled={isSubmitting || localPending || !editSlotValue.trim()}
                    >
                      Update
                    </Button>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* 3. Structured Batch Clarification Form */}
          {uniqueQuestions.length > 0 && (
            <form
              onSubmit={handleSubmitBatchAnswers}
              style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}
            >
              {(() => {
                const groups: Record<string, ClarificationQuestion[]> = {};
                uniqueQuestions.forEach((q) => {
                  const grp = q.group || 'Workflow Requirements';
                  if (!groups[grp]) groups[grp] = [];
                  groups[grp].push(q);
                });

                return Object.entries(groups).map(([groupTitle, groupQuestions]) => (
                  <div key={groupTitle} className="clarification-group-card">
                    <div className="clarification-group-header">
                      <h3 className="clarification-group-title">{groupTitle}</h3>
                    </div>

                    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                      {groupQuestions.map((q, qIdx) => {
                        const globalNum = questionNumberMap.get(q.id) ?? (qIdx + 1);
                        const hasError = !!formErrors[q.id];
                        const isSelect = q.input_type === 'single_select' && q.options && q.options.length > 0;
                        const isUrl = q.input_type === 'url';
                        const isNumber = q.input_type === 'number';
                        const isBoolean = q.input_type === 'boolean';

                        return (
                          <div
                            key={q.id}
                            id={`clarification-question-${q.id}`}
                            style={{
                              padding: '16px',
                              backgroundColor: 'var(--bg-surface-subtle)',
                              borderRadius: 'var(--radius-md)',
                              border: hasError ? '1px solid var(--state-error)' : '1px solid var(--border-subtle)',
                              display: 'flex',
                              flexDirection: 'column',
                              gap: '10px',
                            }}
                          >
                            {/* Question Title & Requirement Status */}
                            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                <span
                                  style={{
                                    fontSize: '11px',
                                    fontWeight: 700,
                                    padding: '2px 6px',
                                    borderRadius: 'var(--radius-sm)',
                                    backgroundColor: 'rgba(234, 88, 12, 0.12)',
                                    color: 'var(--brand-primary)',
                                  }}
                                >
                                  Q{globalNum}
                                </span>
                                <h4 style={{ fontSize: '14px', fontWeight: 600, color: 'var(--text-primary)', margin: 0 }}>
                                  {q.question}
                                </h4>
                              </div>
                              {!q.required && !q.is_required ? (
                                <span style={{ fontSize: '11px', color: 'var(--text-tertiary)' }}>(Optional)</span>
                              ) : (
                                <span style={{ fontSize: '11px', color: 'var(--brand-primary)', fontWeight: 600 }}>* Required</span>
                              )}
                            </div>

                            {/* Help Text / Clear Guidance */}
                            {q.help_text && (
                              <p style={{ fontSize: '12px', color: 'var(--text-secondary)', margin: 0, lineHeight: 1.45 }}>
                                {q.help_text}
                              </p>
                            )}

                            {/* 1. Single Select Options */}
                            {isSelect && (
                              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                                {q.options!.map((opt) => {
                                  const isSelected = selectedAnswers[q.id] === opt.value;
                                  return (
                                    <button
                                      key={opt.value}
                                      type="button"
                                      id={`option-${q.id}-${opt.value}`}
                                      className={`btn btn-sm ${isSelected ? 'btn-primary' : 'btn-secondary'}`}
                                      onClick={() => handleOptionSelect(q.id, opt.value)}
                                      title={opt.description || opt.label}
                                      disabled={isSubmitting || localPending}
                                      style={{
                                        borderRadius: 'var(--radius-sm)',
                                        padding: '8px 16px',
                                        fontSize: '13px',
                                        fontWeight: isSelected ? 600 : 500,
                                        cursor: isSubmitting || localPending ? 'not-allowed' : 'pointer',
                                        border: isSelected ? '1px solid var(--brand-primary)' : '1px solid var(--border-default)',
                                      }}
                                    >
                                      {opt.label}
                                    </button>
                                  );
                                })}
                              </div>
                            )}

                            {/* 2. Text / URL / Number Controls */}
                            {(!isSelect || selectedAnswers[q.id] === 'other' || showOtherInput[q.id]) && !isBoolean && (
                              <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                                {isSelect && (
                                  <label
                                    htmlFor={`other-input-${q.id}`}
                                    style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-primary)' }}
                                  >
                                    Custom Answer (Required)
                                  </label>
                                )}
                                <input
                                  type={isUrl ? 'url' : isNumber ? 'number' : 'text'}
                                  id={isSelect ? `other-input-${q.id}` : `text-input-${q.id}`}
                                  value={customAnswers[q.id] || ''}
                                  onChange={(e) => {
                                    const val = e.target.value;
                                    setCustomAnswers((prev) => ({ ...prev, [q.id]: val }));
                                    if (val.trim()) {
                                      setFormErrors((prev) => {
                                        const next = { ...prev };
                                        delete next[q.id];
                                        return next;
                                      });
                                    }
                                  }}
                                  placeholder={q.placeholder || (isUrl ? 'https://...' : 'Enter your answer...')}
                                  disabled={isSubmitting || localPending}
                                  style={{
                                    padding: '8px 12px',
                                    fontSize: '13px',
                                    borderRadius: 'var(--radius-sm)',
                                    border: hasError ? '1px solid var(--state-error)' : '1px solid var(--border-default)',
                                    backgroundColor: 'var(--bg-app)',
                                    color: 'var(--text-primary)',
                                    width: '100%',
                                    outline: 'none',
                                  }}
                                />
                              </div>
                            )}

                            {/* 3. Boolean Controls */}
                            {isBoolean && (
                              <div style={{ display: 'flex', gap: '8px' }}>
                                {['true', 'false'].map((boolVal) => {
                                  const isSelected = selectedAnswers[q.id] === boolVal;
                                  return (
                                    <button
                                      key={boolVal}
                                      type="button"
                                      className={`btn btn-sm ${isSelected ? 'btn-primary' : 'btn-secondary'}`}
                                      onClick={() => handleOptionSelect(q.id, boolVal)}
                                      disabled={isSubmitting || localPending}
                                      style={{ minWidth: '80px' }}
                                    >
                                      {boolVal === 'true' ? 'Yes' : 'No'}
                                    </button>
                                  );
                                })}
                              </div>
                            )}

                            {/* 4. Clickable Examples Derived Dynamically */}
                            {q.examples && q.examples.length > 0 && (
                              <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '6px', marginTop: '2px' }}>
                                <span style={{ fontSize: '11px', color: 'var(--text-tertiary)' }}>Examples:</span>
                                {q.examples.map((ex) => (
                                  <button
                                    key={ex}
                                    type="button"
                                    className="clarification-example-pill"
                                    onClick={() => {
                                      setCustomAnswers((prev) => ({ ...prev, [q.id]: ex }));
                                      setFormErrors((prev) => {
                                        const next = { ...prev };
                                        delete next[q.id];
                                        return next;
                                      });
                                    }}
                                    title={`Click to use: ${ex}`}
                                  >
                                    {ex}
                                  </button>
                                ))}
                              </div>
                            )}

                            {/* 5. Inline Field-Specific Error */}
                            {hasError && (
                              <div
                                id={`error-${q.id}`}
                                className="clarification-field-error"
                                style={{ marginTop: '2px' }}
                              >
                                <AlertTriangle size={13} />
                                <span>{formErrors[q.id]}</span>
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                ));
              })()}

              {/* Free-form Additional Guidance (Optional) */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                <label style={{ fontSize: '12px', color: 'var(--text-tertiary)' }}>
                  Additional specifications or instructions (Optional)
                </label>
                <input
                  type="text"
                  id="freeform-clarification-input"
                  value={freeformInstructions}
                  onChange={(e) => setFreeformInstructions(e.target.value)}
                  placeholder="e.g. Only forward emails from billing@company.com with urgent priority"
                  disabled={isSubmitting || localPending}
                  style={{
                    padding: '8px 12px',
                    fontSize: '13px',
                    borderRadius: 'var(--radius-sm)',
                    border: '1px solid var(--border-default)',
                    backgroundColor: 'var(--bg-app)',
                    color: 'var(--text-primary)',
                  }}
                />
              </div>

              {/* Single Submit answers Button */}
              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '12px', alignItems: 'center', paddingTop: '8px' }}>
                <Button
                  type="submit"
                  id="submit-clarification-answers-btn"
                  variant="primary"
                  size="md"
                  icon={isSubmitting || localPending ? <OrbitLoader size="inline" color="currentColor" /> : <Send size={14} />}
                  disabled={isSubmitting || localPending}
                >
                  {isSubmitting || localPending ? 'Submitting answers...' : 'Submit answers'}
                </Button>
              </div>
            </form>
          )}
        </div>
      )}

      {/* 3. Generated Workflow Ready State */}
      {stageState === 'ready' && turnResult && turnResult.workflow_ir && (
        <div style={{ width: '100%', height: '100%', flex: 1, display: 'flex', flexDirection: 'column' }}>
          <WorkflowCanvas
            workflow={turnResult.workflow_ir as any}
            conversationId={turnResult.conversation_id}
            baseRevisionNumber={turnResult.latest_revision_number || turnResult.revision_number || 1}
            isValid={turnResult.validation_report?.is_valid ?? true}
            onRevisionSaved={onRevisionSaved}
            researchDossier={turnResult.research_dossier}
            workflowPlan={turnResult.workflow_plan}
          />
        </div>
      )}

      {/* 4. Failed or Timed Out State */}
      {(stageState === 'failed' || stageState === 'timed_out') && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          {(activePrompt || turnResult?.original_prompt) && (
            <div
              style={{
                backgroundColor: 'var(--bg-surface-subtle)',
                border: '1px solid var(--border-subtle)',
                borderRadius: 'var(--radius-md)',
                padding: '12px 16px',
              }}
            >
              <div
                style={{
                  fontSize: '11px',
                  fontWeight: 600,
                  color: 'var(--text-tertiary)',
                  textTransform: 'uppercase',
                  letterSpacing: '0.04em',
                  marginBottom: '4px',
                }}
              >
                Your Request
              </div>
              <div style={{ fontSize: '13px', color: 'var(--text-primary)', lineHeight: 1.5 }}>
                {activePrompt || turnResult?.original_prompt}
              </div>
            </div>
          )}

          <div
            className="card"
            style={{
              border: '1px solid var(--state-error)',
              padding: '24px',
              display: 'flex',
              flexDirection: 'column',
              gap: '14px',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--state-error)' }}>
              {stageState === 'timed_out' ? <Clock size={18} /> : <AlertTriangle size={18} />}
              <h3 style={{ fontSize: '15px', fontWeight: 600, margin: 0 }}>
                {stageState === 'timed_out' ? 'Request Timed Out' : 'Workflow Generation Issue'}
              </h3>
            </div>

            <div style={{ fontSize: '13px', color: 'var(--text-secondary)', margin: 0, lineHeight: 1.5 }}>
              <MarkdownRenderer content={errorMessage || turnResult?.assistant_message || 'Could not complete workflow generation. Please verify provider connectivity and try again.'} />
            </div>

            <div style={{ display: 'flex', gap: '10px', marginTop: '6px' }}>
              {onRetry && (
                <Button
                  variant="primary"
                  size="sm"
                  onClick={onRetry}
                  icon={<RotateCcw size={13} />}
                  disabled={isSubmitting || localPending}
                >
                  Retry generation
                </Button>
              )}
              {onStartOver && (
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={onStartOver}
                  icon={<Sparkles size={13} />}
                  disabled={isSubmitting || localPending}
                >
                  Start over
                </Button>
              )}
              {onBackToDrafts && (
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={onBackToDrafts}
                  icon={<ArrowLeft size={13} />}
                  disabled={isSubmitting || localPending}
                >
                  Back to My Workflows
                </Button>
              )}
            </div>
          </div>
        </div>
      )}

      {/* 4. Saved Conversation with No Draft State */}
      {stageState === 'no_draft' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px', maxWidth: '680px', margin: '0 auto', padding: '24px 0' }}>
          {activePrompt && (
            <div
              style={{
                backgroundColor: 'var(--bg-surface-subtle)',
                border: '1px solid var(--border-subtle)',
                borderRadius: 'var(--radius-md)',
                padding: '12px 16px',
              }}
            >
              <div
                style={{
                  fontSize: '11px',
                  fontWeight: 600,
                  color: 'var(--text-tertiary)',
                  textTransform: 'uppercase',
                  letterSpacing: '0.04em',
                  marginBottom: '4px',
                }}
              >
                Saved Request
              </div>
              <div style={{ fontSize: '13px', color: 'var(--text-primary)', lineHeight: 1.5 }}>
                {activePrompt}
              </div>
            </div>
          )}

          <div className="card" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '14px' }}>
            <h3 style={{ fontSize: '15px', fontWeight: 600, margin: 0, color: 'var(--text-primary)' }}>
              No Saved Workflow Draft Found
            </h3>
            <p style={{ fontSize: '13px', color: 'var(--text-secondary)', margin: 0, lineHeight: 1.5 }}>
              This conversation does not currently have a generated workflow draft in PostgreSQL. You can generate one now from the saved request or return to your workflows.
            </p>
            <div style={{ display: 'flex', gap: '10px', marginTop: '6px' }}>
              {activePrompt && onSubmitPrompt && (
                <Button variant="primary" size="sm" onClick={() => onSubmitPrompt(activePrompt)} icon={<Sparkles size={13} />}>
                  Generate workflow
                </Button>
              )}
              {onBackToDrafts && (
                <Button variant="secondary" size="sm" onClick={onBackToDrafts} icon={<ArrowLeft size={13} />}>
                  Back to My Workflows
                </Button>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
