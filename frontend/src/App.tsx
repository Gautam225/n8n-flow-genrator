import { useState, useEffect, useRef } from 'react';
import type { AppRoute, AppTheme } from './types';
import { LeftNavRail } from './components/layout/LeftNavRail';
import { PromptInput } from './components/workspace/PromptInput';
import { ExamplePrompts } from './components/workspace/ExamplePrompts';
import { ReservedWorkflowStage, type StageState } from './components/workspace/ReservedWorkflowStage';
import { DraftsView } from './components/drafts/DraftsView';
import { SettingsView } from './components/settings/SettingsView';
import {
  createConversation,
  sendMessage,
  retryConversation,
  getConversation,
  getConversationStatus,
  createGenerationWebSocket,
  getLLMStatus,
  type OrchestratorTurnResult,
  type LLMStatusData,
  type ClarificationAnswerItem,
} from './api/conversations';

export function App() {
  // Theme management with persistence (Default: light)
  const [theme, setTheme] = useState<AppTheme>(() => {
    const saved = localStorage.getItem('n8n_studio_theme');
    return saved === 'dark' ? 'dark' : 'light';
  });

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('n8n_studio_theme', theme);
  }, [theme]);

  const toggleTheme = () => {
    setTheme((prev) => (prev === 'light' ? 'dark' : 'light'));
  };

  // Route management with hash synchronization
  const [currentRoute, setCurrentRoute] = useState<AppRoute>(() => {
    const hash = window.location.hash.replace(/^#\/?/, '');
    if (hash === 'drafts') return 'drafts';
    if (hash === 'settings') return 'settings';
    return 'workspace';
  });

  useEffect(() => {
    const handleHashChange = () => {
      const hash = window.location.hash.replace(/^#\/?/, '');
      if (hash === 'drafts') setCurrentRoute('drafts');
      else if (hash === 'settings') setCurrentRoute('settings');
      else setCurrentRoute('workspace');
    };

    window.addEventListener('hashchange', handleHashChange);
    return () => window.removeEventListener('hashchange', handleHashChange);
  }, []);

  const handleRouteChange = (route: AppRoute) => {
    setCurrentRoute(route);
    window.location.hash = route === 'workspace' ? '' : `#/${route}`;
  };

  // Workflow prompt and conversation state
  const [promptText, setPromptText] = useState('');
  const [submittedPrompt, setSubmittedPrompt] = useState<string | null>(null);
  const [stageState, setStageState] = useState<StageState>('idle');
  const [currentConversationId, setCurrentConversationId] = useState<string | null>(null);
  const [turnResult, setTurnResult] = useState<OrchestratorTurnResult | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Real backend stage tracking
  const [backendStage, setBackendStage] = useState<string | null>(null);
  const [backendStatusMessage, setBackendStatusMessage] = useState<string | null>(null);
  const [elapsedSeconds, setElapsedSeconds] = useState<number | null>(null);
  const activeControllerRef = useRef<AbortController | null>(null);
  const activePollRef = useRef<any>(null);
  const activeWsCleanupRef = useRef<(() => void) | null>(null);
  const activeTrackingConvIdRef = useRef<string | null>(null);
  const currentConversationIdRef = useRef<string | null>(null);

  useEffect(() => {
    currentConversationIdRef.current = currentConversationId;
    // Persist active conversation across page refreshes
    if (currentConversationId) {
      localStorage.setItem('n8n_active_conversation_id', currentConversationId);
    } else {
      localStorage.removeItem('n8n_active_conversation_id');
    }
  }, [currentConversationId]);

  useEffect(() => {
    return () => {
      stopLiveTracking();
      if (activeControllerRef.current) {
        activeControllerRef.current.abort();
      }
    };
  }, []);

  const stopLiveTracking = () => {
    if (activeWsCleanupRef.current) {
      activeWsCleanupRef.current();
      activeWsCleanupRef.current = null;
    }
    if (activePollRef.current) {
      clearInterval(activePollRef.current);
      activePollRef.current = null;
    }
    activeTrackingConvIdRef.current = null;
    setBackendStage(null);
    setBackendStatusMessage(null);
    setElapsedSeconds(null);
  };

  const mapBackendStageToStageState = (stage?: string | null): StageState | null => {
    if (!stage) return null;
    switch (stage) {
      case 'understanding':
      case 'discovering_nodes':
        return 'understanding';
      case 'researching':
        return 'researching';
      case 'planning':
        return 'planning';
      case 'generating':
        return 'generating';
      case 'validating':
        return 'validating';
      case 'repairing':
      case 'building':
        return 'building';
      case 'clarifying':
        return 'clarifying';
      case 'ready':
        return 'ready';
      case 'failed':
        return 'failed';
      default:
        return null;
    }
  };

  const startLiveTracking = (convId: string) => {
    stopLiveTracking();
    activeTrackingConvIdRef.current = convId;

    const hydrateFromConversation = async () => {
      try {
        const detail = await getConversation(convId);
        if (currentConversationIdRef.current !== convId) return;

        if (detail.latest_draft && detail.latest_draft.workflow_ir) {
          const restoredIR = { ...detail.latest_draft.workflow_ir };
          if (detail.latest_draft.title) {
            restoredIR.name = detail.latest_draft.title;
          }
          const latestRevNum = detail.latest_draft.latest_revision_number || 1;
          setTurnResult({
            conversation_id: detail.id,
            state: 'ready',
            assistant_message:
              detail.messages.filter((m) => m.role === 'assistant').pop()?.content ||
              `Restored draft revision ${latestRevNum}.`,
            workflow_ir: restoredIR,
            compiled_json: detail.latest_draft.compiled_json,
            validation_report: detail.latest_draft.validation_report,
            research_dossier: detail.research_dossier,
            workflow_plan: detail.workflow_plan,
          });
          setStageState('ready');
        } else if (detail.clarification && (detail.clarification.questions?.length ?? 0) > 0) {
          setTurnResult({
            conversation_id: detail.id,
            state: 'clarifying',
            assistant_message:
              detail.messages.filter((m) => m.role === 'assistant').pop()?.content ||
              'Please clarify your requirements.',
            clarification: detail.clarification,
            current_question_id: detail.current_question_id,
            outstanding_questions: detail.outstanding_questions,
          });
          setStageState('clarifying');
        } else {
          setStageState('idle');
        }
      } catch {
        setStageState('ready');
      }
    };

    // 1. Subscribe to real-time WebSocket lifecycle events
    try {
      activeWsCleanupRef.current = createGenerationWebSocket(convId, (event) => {
        if (activeTrackingConvIdRef.current !== convId) return;
        if (event.event_type === 'stage_transition') {
          setBackendStage(event.stage);
          setBackendStatusMessage(event.message || null);
          if (event.timings && typeof event.timings.elapsed_seconds === 'number') {
            setElapsedSeconds(event.timings.elapsed_seconds);
          }
          const mapped = mapBackendStageToStageState(event.stage);
          if (mapped) setStageState(mapped);
        } else if (event.event_type === 'stage_complete') {
          stopLiveTracking();
          submittingRef.current = false;
          setIsSubmitting(false);
          hydrateFromConversation();
        }
      });
    } catch {
      // Polling fallback handles gracefully
    }

    // 2. Resilient polling fallback (every 1200ms)
    const interval = setInterval(async () => {
      if (activeTrackingConvIdRef.current !== convId) {
        clearInterval(interval);
        return;
      }
      try {
        const status = await getConversationStatus(convId);
        if (activeTrackingConvIdRef.current !== convId) {
          clearInterval(interval);
          return;
        }

        if (status && status.is_active) {
          setBackendStage(status.stage);
          setBackendStatusMessage(status.message || null);
          if (typeof status.elapsed_seconds === 'number') {
            setElapsedSeconds(status.elapsed_seconds);
          }
          const mapped = mapBackendStageToStageState(status.stage);
          if (mapped) setStageState(mapped);
        } else if (status && !status.is_active) {
          // Backend generation has finished, failed, or paused
          stopLiveTracking();
          submittingRef.current = false;
          setIsSubmitting(false);

          if (status.stage === 'failed') {
            setStageState('failed');
            setErrorMessage(status.message || 'Workflow generation failed.');
          } else {
            hydrateFromConversation();
          }
        }
      } catch {
        // Silently ignore transient status polling errors while request is in flight
      }
    }, 1200);
    activePollRef.current = interval;
  };

  const handleNewWorkflow = () => {
    if (activeControllerRef.current) {
      activeControllerRef.current.abort();
    }
    stopLiveTracking();
    submittingRef.current = false;
    setIsSubmitting(false);
    setPromptText('');
    setSubmittedPrompt(null);
    setStageState('idle');
    setCurrentConversationId(null);
    setTurnResult(null);
    setErrorMessage(null);
    localStorage.removeItem('n8n_active_conversation_id');
    handleRouteChange('workspace');
    setTimeout(() => {
      const textarea = document.getElementById('automation-prompt');
      if (textarea) textarea.focus();
    }, 50);
  };

  const handleSelectPrompt = (selectedText: string) => {
    if (activeControllerRef.current) {
      activeControllerRef.current.abort();
    }
    stopLiveTracking();
    submittingRef.current = false;
    setIsSubmitting(false);
    setPromptText(selectedText);
    setStageState('idle');
    setSubmittedPrompt(null);
    setTurnResult(null);
    setErrorMessage(null);
    handleRouteChange('workspace');
    setTimeout(() => {
      const textarea = document.getElementById('automation-prompt');
      if (textarea) {
        textarea.focus();
        textarea.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }
    }, 50);
  };

  const [isSubmitting, setIsSubmitting] = useState(false);
  const submittingRef = useRef(false);
  const TIMEOUT_MS = 95000;

  const handleSubmitPrompt = async (text: string) => {
    if (submittingRef.current || isSubmitting) return;
    submittingRef.current = true;
    setIsSubmitting(true);
    setSubmittedPrompt(text);
    setStageState('understanding');
    setErrorMessage(null);

    const clientConvId = (typeof crypto !== 'undefined' && crypto.randomUUID) ? crypto.randomUUID() : `conv-${Date.now()}`;
    setCurrentConversationId(clientConvId);

    const controller = new AbortController();
    activeControllerRef.current = controller;
    const timeoutId = setTimeout(() => {
      controller.abort();
    }, TIMEOUT_MS);

    startLiveTracking(clientConvId);

    try {
      const res = await createConversation(undefined, text, controller.signal, clientConvId);
      clearTimeout(timeoutId);
      stopLiveTracking();
      setCurrentConversationId(res.conversation_id);
      if (res.turn_result) {
        setTurnResult(res.turn_result);
        setStageState(res.turn_result.state as StageState);
      } else {
        setStageState('building');
      }
    } catch (err: any) {
      clearTimeout(timeoutId);
      if (clientConvId) {
        try {
          const liveStatus = await getConversationStatus(clientConvId);
          if (liveStatus && liveStatus.is_active) {
            setBackendStage(liveStatus.stage);
            setBackendStatusMessage(
              liveStatus.message || 'Workflow synthesis is still processing on the server. Reconnecting to live progress...'
            );
            startLiveTracking(clientConvId);
            return;
          }
        } catch {
          // Status polling fallback handled below
        }
      }
      stopLiveTracking();
      if (err.name === 'AbortError') {
        setStageState('timed_out');
        setErrorMessage('The request timed out while generating the workflow. The AI provider took longer than expected to respond.');
      } else {
        setErrorMessage(err.message || 'Failed to start automation conversation.');
        setStageState('failed');
      }
    } finally {
      if (!activeTrackingConvIdRef.current) {
        submittingRef.current = false;
        setIsSubmitting(false);
      }
      activeControllerRef.current = null;
    }
  };

  const handleAnswerClarification = async (
    answerText: string,
    selectedOptions?: Record<string, string>,
    clarificationAnswers?: ClarificationAnswerItem[]
  ) => {
    if (!currentConversationId || submittingRef.current || isSubmitting) return;
    submittingRef.current = true;
    setIsSubmitting(true);
    const hasMoreQuestions = (turnResult?.outstanding_questions && turnResult.outstanding_questions.length > 1) ?? false;
    setStageState(hasMoreQuestions ? 'saving_answer' : 'building');
    setErrorMessage(null);

    const controller = new AbortController();
    activeControllerRef.current = controller;
    const timeoutId = setTimeout(() => {
      controller.abort();
    }, TIMEOUT_MS);

    startLiveTracking(currentConversationId);

    try {
      const res = await sendMessage(
        currentConversationId,
        answerText,
        selectedOptions,
        controller.signal,
        clarificationAnswers
      );
      clearTimeout(timeoutId);
      stopLiveTracking();
      setTurnResult(res);
      setStageState(res.state as StageState);
    } catch (err: any) {
      clearTimeout(timeoutId);
      if (currentConversationId) {
        try {
          const liveStatus = await getConversationStatus(currentConversationId);
          if (liveStatus && liveStatus.is_active) {
            setBackendStage(liveStatus.stage);
            setBackendStatusMessage(
              liveStatus.message || 'Workflow synthesis is still processing on the server. Reconnecting to live progress...'
            );
            startLiveTracking(currentConversationId);
            return;
          }
        } catch {
          // Status polling fallback handled below
        }
      }
      stopLiveTracking();
      if (err.name === 'AbortError') {
        setStageState('timed_out');
        setErrorMessage('The request timed out while building the workflow. The AI provider took longer than expected to respond.');
      } else {
        setErrorMessage(err.message || 'Failed to send clarification answer.');
        setStageState('failed');
      }
    } finally {
      if (!activeTrackingConvIdRef.current) {
        submittingRef.current = false;
        setIsSubmitting(false);
      }
      activeControllerRef.current = null;
    }
  };

  const handleRetry = async () => {
    if (submittingRef.current || isSubmitting) return;
    if (currentConversationId) {
      // 1. Verify whether a real generation request for this conversation is still running
      try {
        const liveStatus = await getConversationStatus(currentConversationId);
        if (liveStatus && liveStatus.is_active) {
          // Genuinely running on backend. Do not dispatch a duplicate request.
          submittingRef.current = true;
          setIsSubmitting(true);
          setErrorMessage(null);
          setBackendStage(liveStatus.stage);
          setBackendStatusMessage(
            liveStatus.message || 'Workflow generation is currently in progress. Resuming live tracking...'
          );
          if (typeof liveStatus.elapsed_seconds === 'number') {
            setElapsedSeconds(liveStatus.elapsed_seconds);
          }
          setStageState((liveStatus.stage as StageState) || 'building');
          startLiveTracking(currentConversationId);
          return;
        }
      } catch {
        // Status check non-fatal; continue to retry execution
      }

      // 2. Previous request failed or lock confirmed released/stale. Allow new generation request to start.
      submittingRef.current = true;
      setIsSubmitting(true);
      setStageState('building');
      setErrorMessage(null);

      const controller = new AbortController();
      activeControllerRef.current = controller;
      const timeoutId = setTimeout(() => {
        controller.abort();
      }, TIMEOUT_MS);

      startLiveTracking(currentConversationId);

      try {
        const res = await retryConversation(currentConversationId, controller.signal);
        clearTimeout(timeoutId);
        stopLiveTracking();
        setTurnResult(res);
        setStageState(res.state as StageState);
      } catch (err: any) {
        clearTimeout(timeoutId);
        // If 409 conflict returned because another request is in progress
        if (err.message && err.message.includes('already in progress')) {
          try {
            const liveStatus = await getConversationStatus(currentConversationId);
            if (liveStatus && liveStatus.is_active) {
              submittingRef.current = true;
              setIsSubmitting(true);
              setBackendStage(liveStatus.stage);
              setBackendStatusMessage(liveStatus.message || 'Workflow generation is in progress...');
              if (typeof liveStatus.elapsed_seconds === 'number') {
                setElapsedSeconds(liveStatus.elapsed_seconds);
              }
              setStageState((liveStatus.stage as StageState) || 'building');
              startLiveTracking(currentConversationId);
              return;
            }
          } catch {
            // pass
          }
        }

        // Check if backend generation attempt is still active
        try {
          const liveStatus = await getConversationStatus(currentConversationId);
          if (liveStatus && liveStatus.is_active) {
            setBackendStage(liveStatus.stage);
            setBackendStatusMessage(
              liveStatus.message || 'Workflow synthesis is still processing on the server. Reconnecting to live progress...'
            );
            startLiveTracking(currentConversationId);
            return;
          }
        } catch {
          // Status polling fallback handled below
        }

        stopLiveTracking();
        if (err.name === 'AbortError') {
          setStageState('timed_out');
          setErrorMessage('The retry request timed out. Please try again.');
        } else {
          setErrorMessage(err.message || 'Retry failed.');
          setStageState('failed');
        }
      } finally {
        if (!activeTrackingConvIdRef.current) {
          submittingRef.current = false;
          setIsSubmitting(false);
        }
        activeControllerRef.current = null;
      }
    } else if (submittedPrompt) {
      handleSubmitPrompt(submittedPrompt);
    }
  };

  const openingConvIdRef = useRef<string | null>(null);

  const handleSelectPastConversation = async (conversationId: string) => {
    openingConvIdRef.current = conversationId;
    if (activeControllerRef.current) {
      activeControllerRef.current.abort();
    }
    stopLiveTracking();
    submittingRef.current = false;
    setIsSubmitting(false);
    setErrorMessage(null);
    setTurnResult(null); // Clear previous workflow state so stale nodes are never rendered
    setStageState('loading');
    handleRouteChange('workspace');

    try {
      const detail = await getConversation(conversationId);
      if (openingConvIdRef.current !== conversationId) return;

      setCurrentConversationId(detail.id);

      // Restore original prompt or user message
      const promptVal =
        detail.original_prompt ||
        detail.messages.find((m) => m.role === 'user')?.content ||
        detail.title;
      setSubmittedPrompt(promptVal);
      setPromptText(promptVal);

      // Check if an active turn is currently in flight on the backend for this conversation
      let isActiveOnBackend = false;
      try {
        const liveStatus = await getConversationStatus(conversationId);
        if (openingConvIdRef.current !== conversationId) return;
        if (liveStatus && liveStatus.is_active) {
          isActiveOnBackend = true;
          submittingRef.current = true;
          setIsSubmitting(true);
          setBackendStage(liveStatus.stage);
          setBackendStatusMessage(liveStatus.message || null);
          if (typeof liveStatus.elapsed_seconds === 'number') {
            setElapsedSeconds(liveStatus.elapsed_seconds);
          }
          setStageState(liveStatus.stage as StageState);
          startLiveTracking(conversationId);
        }
      } catch {
        // Status polling error is non-fatal; continue restoring saved state
      }

      if (isActiveOnBackend) return;

      // Restore saved workflow draft if available
      if (detail.latest_draft && detail.latest_draft.workflow_ir) {
        const latestRevNum = detail.latest_draft.latest_revision_number || 1;
        const restoredIR = { ...detail.latest_draft.workflow_ir };
        if (detail.latest_draft.title) {
          restoredIR.name = detail.latest_draft.title;
        }

        setTurnResult({
          conversation_id: detail.id,
          state: 'ready',
          assistant_message: `Restored draft revision ${latestRevNum}.`,
          workflow_ir: restoredIR,
          compiled_json: detail.latest_draft.compiled_json,
          validation_report: detail.latest_draft.validation_report,
          draft_id: detail.latest_draft.id,
          revision_number: latestRevNum,
          latest_revision_number: latestRevNum,
          original_prompt: detail.original_prompt,
          completed_answers: detail.slots,
          research_dossier: detail.research_dossier,
          workflow_plan: detail.workflow_plan,
        });
        setStageState('ready');
      } else if (detail.state === 'clarifying' && detail.clarification) {
        const lastAsst = [...detail.messages].reverse().find((m) => m.role === 'assistant');
        setTurnResult({
          conversation_id: detail.id,
          state: 'clarifying',
          assistant_message: lastAsst?.content || 'Please clarify your requirements.',
          clarification: detail.clarification,
          original_prompt: detail.original_prompt,
          current_question_id: detail.current_question_id,
          outstanding_questions: detail.outstanding_questions,
          completed_answers: detail.slots,
        });
        setStageState('clarifying');
      } else if (detail.state === 'failed') {
        const lastAsst = [...detail.messages].reverse().find((m) => m.role === 'assistant');
        setTurnResult({
          conversation_id: detail.id,
          state: 'failed',
          assistant_message: lastAsst?.content || 'Workflow generation failed.',
          original_prompt: detail.original_prompt,
          completed_answers: detail.slots,
        });
        setErrorMessage(lastAsst?.content || 'Workflow generation failed.');
        setStageState('failed');
      } else {
        // Saved conversation with no generated draft
        setTurnResult({
          conversation_id: detail.id,
          state: 'no_draft' as any,
          assistant_message: 'No generated workflow draft found for this conversation.',
          original_prompt: detail.original_prompt,
          completed_answers: detail.slots,
        });
        setStageState('no_draft');
      }
    } catch (err: any) {
      if (openingConvIdRef.current !== conversationId) return;
      setErrorMessage(err.message || 'Could not load saved workflow from database.');
      setStageState('failed');
    }
  };

  // AI provider status for subtle notice
  const [providerWarning, setProviderWarning] = useState<string | null>(null);

  useEffect(() => {
    let isMounted = true;
    getLLMStatus()
      .then((status: LLMStatusData) => {
        if (isMounted && !status.is_primary_configured) {
          setProviderWarning('AI provider is not configured. Open Settings to configure your API key.');
        }
      })
      .catch(() => {
        // Backend offline or unreachable
      });
    return () => {
      isMounted = false;
    };
  }, []);

  // On page load, restore the last active conversation from localStorage so a
  // browser refresh doesn't lose progress (draft, clarification, or in-flight generation).
  useEffect(() => {
    const savedId = localStorage.getItem('n8n_active_conversation_id');
    if (savedId) {
      handleSelectPastConversation(savedId);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []); // intentionally run once on mount only

  const hasActiveWorkflow = Boolean(turnResult?.workflow_ir && stageState === 'ready');

  return (
    <div style={{ height: '100vh', width: '100vw', display: 'flex', overflow: 'hidden' }}>
      <LeftNavRail
        currentRoute={currentRoute}
        onRouteChange={handleRouteChange}
        onNewWorkflow={handleNewWorkflow}
        theme={theme}
        onToggleTheme={toggleTheme}
      />

      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden', minWidth: 0 }}>
        {currentRoute === 'workspace' && (
          <div style={{ flex: 1, height: '100%', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
            {hasActiveWorkflow ? (
              <div style={{ flex: 1, height: '100%', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
                <ReservedWorkflowStage
                  stageState={stageState}
                  activePrompt={submittedPrompt || undefined}
                  turnResult={turnResult}
                  errorMessage={errorMessage}
                  onAnswerClarification={handleAnswerClarification}
                  onRetry={handleRetry}
                  isSubmitting={isSubmitting}
                  onBackToDrafts={() => handleRouteChange('drafts')}
                  onSubmitPrompt={handleSubmitPrompt}
                  onRevisionSaved={(saved) => {
                    if (turnResult) {
                      setTurnResult({
                        ...turnResult,
                        revision_number: saved.revision_number,
                        latest_revision_number: saved.revision_number,
                        workflow_ir: saved.workflow_ir || turnResult.workflow_ir,
                        compiled_json: saved.compiled_json ?? turnResult.compiled_json,
                        validation_report: saved.validation_report || turnResult.validation_report,
                      });
                    }
                  }}
                  onStartOver={handleNewWorkflow}
                />
              </div>
            ) : stageState === 'idle' ? (
              <div style={{ flex: 1, overflowY: 'auto', padding: '32px 24px' }}>
                <div className="workspace-header" style={{ textAlign: 'center', margin: '16px auto 32px', maxWidth: '640px' }}>
                  <h1 className="workspace-title" style={{ fontSize: '28px', marginBottom: '10px' }}>
                    What would you like to automate?
                  </h1>
                  <p className="workspace-subtitle" style={{ margin: '0 auto', fontSize: '14px' }}>
                    Describe your automation in plain language. The assistant will clarify any missing details and generate an executable n8n workflow.
                  </p>
                </div>

                <div style={{ maxWidth: '800px', margin: '0 auto' }}>
                  <PromptInput
                    promptText={promptText}
                    onPromptChange={setPromptText}
                    onSubmit={handleSubmitPrompt}
                    submittedState="idle"
                    isLoading={isSubmitting}
                    onReset={handleNewWorkflow}
                    providerWarning={providerWarning}
                  />

                  <ExamplePrompts onSelectPrompt={handleSelectPrompt} />
                </div>
              </div>
            ) : (
              <div style={{ flex: 1, overflowY: 'auto', padding: '32px 24px' }}>
                <div style={{ maxWidth: '800px', margin: '0 auto' }}>
                  <ReservedWorkflowStage
                    stageState={stageState}
                    activePrompt={submittedPrompt || undefined}
                    turnResult={turnResult}
                    errorMessage={errorMessage}
                    backendStage={backendStage}
                    backendStatusMessage={backendStatusMessage}
                    elapsedSeconds={elapsedSeconds}
                    onAnswerClarification={handleAnswerClarification}
                    onRetry={handleRetry}
                    isSubmitting={isSubmitting}
                    onBackToDrafts={() => handleRouteChange('drafts')}
                    onSubmitPrompt={handleSubmitPrompt}
                    onRevisionSaved={(saved) => {
                      if (turnResult) {
                        setTurnResult({
                          ...turnResult,
                          revision_number: saved.revision_number,
                          latest_revision_number: saved.revision_number,
                          workflow_ir: saved.workflow_ir || turnResult.workflow_ir,
                          compiled_json: saved.compiled_json ?? turnResult.compiled_json,
                          validation_report: saved.validation_report || turnResult.validation_report,
                        });
                      }
                    }}
                    onStartOver={handleNewWorkflow}
                  />
                </div>
              </div>
            )}
          </div>
        )}

        {currentRoute === 'drafts' && (
          <div style={{ flex: 1, overflowY: 'auto', padding: '24px 32px' }}>
            <DraftsView
              onNewWorkflow={handleNewWorkflow}
              onSelectConversation={handleSelectPastConversation}
            />
          </div>
        )}

        {currentRoute === 'settings' && (
          <div style={{ flex: 1, overflowY: 'auto', padding: '24px 32px' }}>
            <SettingsView theme={theme} onThemeChange={setTheme} />
          </div>
        )}
      </div>
    </div>
  );
}

export default App;
