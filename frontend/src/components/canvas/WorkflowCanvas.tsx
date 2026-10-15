import React, { useState, useEffect, useMemo, useCallback } from 'react';
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  BackgroundVariant,
  useNodesState,
  useEdgesState,
  useReactFlow,
  ReactFlowProvider,
  type Node,
  type Edge,
  type NodeMouseHandler,
  type Connection,
  type NodeChange,
  type NodePositionChange,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';

import type { WorkflowIR, IRNode, IREdge } from '../../types/workflow';
import { mapWorkflowIRToCanvas, computeFallbackLayout } from './workflowCanvasAdapter';
import { WorkflowNodeCard } from './WorkflowNodeCard';
import { NodeInspector } from './NodeInspector';
import { NodeLibraryPanel } from './NodeLibraryPanel';
import { OrbitLoader } from '../common/OrbitLoader';
import { Button } from '../ui/Button';
import {
  CircleDashed,
  Undo2,
  Redo2,
  RotateCcw,
  Save,
  History,
  AlertTriangle,
  CheckCircle2,
  X,
  FileCheck2,
  Plus,
  Play,
  Hand,
  MousePointer,
  ZoomIn,
  ZoomOut,
  Maximize2,
  ChevronRight,
  LayoutGrid,
} from 'lucide-react';
import { WorkflowReviewPanel } from './WorkflowReviewPanel';
import {
  saveDraftRevision,
  listDraftRevisions,
  getDraftRevision,
  type RevisionSummary,
  type SavedRevisionResult,
  type NodeCatalogItem,
} from '../../api/conversations';

interface WorkflowCanvasProps {
  workflow?: WorkflowIR | null;
  conversationId?: string | null;
  baseRevisionNumber?: number;
  isValid?: boolean;
  onSelectNode?: (node: IRNode | null) => void;
  onRevisionSaved?: (savedRevision: SavedRevisionResult) => void;
  isReadOnly?: boolean;
  researchDossier?: any | null;
  workflowPlan?: any | null;
}

const WorkflowCanvasInner: React.FC<WorkflowCanvasProps> = ({
  workflow: initialWorkflow,
  conversationId,
  baseRevisionNumber = 1,
  isValid = true,
  onSelectNode,
  onRevisionSaved,
  isReadOnly = false,
  researchDossier,
  workflowPlan,
}) => {
  const { zoomIn, zoomOut, fitView } = useReactFlow();

  // Local workflow state with undo/redo
  const [currentWorkflow, setCurrentWorkflow] = useState<WorkflowIR | null>(initialWorkflow || null);
  const [savedWorkflow, setSavedWorkflow] = useState<WorkflowIR | null>(initialWorkflow || null);
  const [historyPast, setHistoryPast] = useState<WorkflowIR[]>([]);
  const [historyFuture, setHistoryFuture] = useState<WorkflowIR[]>([]);

  // Revision state
  const [currentRevNumber, setCurrentRevNumber] = useState<number>(baseRevisionNumber);
  const [isSaving, setIsSaving] = useState(false);
  const [saveStatus, setSaveStatus] = useState<{ type: 'success' | 'error' | 'warning'; message: string } | null>(null);

  // Revisions history modal
  const [showHistoryModal, setShowHistoryModal] = useState(false);
  const [revisionsList, setRevisionsList] = useState<RevisionSummary[]>([]);
  const [isLoadingHistory, setIsLoadingHistory] = useState(false);

  // Review & Readiness modal
  const [showReviewModal, setShowReviewModal] = useState(false);

  // Live validation state
  const [localIssues, setLocalIssues] = useState<Array<{ message: string; severity?: string; rule_code?: string }>>([]);

  // Node selection & right panel mode
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [rightPanelMode, setRightPanelMode] = useState<'none' | 'library' | 'properties'>('none');

  // Canvas interaction mode: select vs pan
  const [isPanMode, setIsPanMode] = useState<boolean>(false);

  // Synchronize state when new initialWorkflow or baseRevisionNumber prop arrives
  const [prevPropWorkflow, setPrevPropWorkflow] = useState(initialWorkflow);
  const [prevBaseRev, setPrevBaseRev] = useState(baseRevisionNumber);

  if (initialWorkflow !== prevPropWorkflow) {
    setPrevPropWorkflow(initialWorkflow);
    if (initialWorkflow) {
      setCurrentWorkflow(initialWorkflow);
      setSavedWorkflow(initialWorkflow);
      setHistoryPast([]);
      setHistoryFuture([]);
      setCurrentRevNumber(baseRevisionNumber);
      setLocalIssues([]);
    }
  }

  if (baseRevisionNumber !== prevBaseRev) {
    setPrevBaseRev(baseRevisionNumber);
    setCurrentRevNumber(baseRevisionNumber);
  }

  // Convert workflow IR to React Flow nodes and edges
  const canvasData = useMemo(() => mapWorkflowIRToCanvas(currentWorkflow), [currentWorkflow]);

  const [nodes, setNodes, onNodesChange] = useNodesState<Node<IRNode>>(canvasData.nodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(canvasData.edges);

  useEffect(() => {
    setNodes(canvasData.nodes);
    setEdges(canvasData.edges);
  }, [canvasData, setNodes, setEdges]);

  // Selected node object
  const selectedNode = useMemo(() => {
    if (!selectedNodeId || !currentWorkflow || !currentWorkflow.nodes) return null;
    return currentWorkflow.nodes.find((n) => n.id === selectedNodeId) || null;
  }, [selectedNodeId, currentWorkflow]);

  // Keep right panel in sync with node selection
  useEffect(() => {
    if (selectedNode) {
      setRightPanelMode('properties');
    }
  }, [selectedNode]);

  // Check if draft has unsaved local modifications
  const isDirty = useMemo(() => {
    if (!currentWorkflow || !savedWorkflow) return false;
    return JSON.stringify(currentWorkflow) !== JSON.stringify(savedWorkflow);
  }, [currentWorkflow, savedWorkflow]);

  // Push edit to history stack
  const pushEdit = useCallback(
    (nextWorkflow: WorkflowIR) => {
      if (!currentWorkflow) return;
      setHistoryPast((prev) => [...prev.slice(-25), currentWorkflow]);
      setHistoryFuture([]);
      setCurrentWorkflow(nextWorkflow);
      setSaveStatus(null);
    },
    [currentWorkflow]
  );

  // Undo edit
  const handleUndo = useCallback(() => {
    if (historyPast.length === 0 || !currentWorkflow) return;
    const previous = historyPast[historyPast.length - 1];
    setHistoryPast((prev) => prev.slice(0, -1));
    setHistoryFuture((prev) => [currentWorkflow, ...prev]);
    setCurrentWorkflow(previous);
  }, [historyPast, currentWorkflow]);

  // Redo edit
  const handleRedo = useCallback(() => {
    if (historyFuture.length === 0 || !currentWorkflow) return;
    const next = historyFuture[0];
    setHistoryFuture((prev) => prev.slice(1));
    setHistoryPast((prev) => [...prev, currentWorkflow]);
    setCurrentWorkflow(next);
  }, [historyFuture, currentWorkflow]);

  // Discard all unsaved edits and restore latest saved revision
  const handleDiscard = useCallback(() => {
    if (!savedWorkflow) return;
    setCurrentWorkflow(savedWorkflow);
    setHistoryPast([]);
    setHistoryFuture([]);
    setSaveStatus({ type: 'warning', message: 'Unsaved edits discarded. Restored saved revision.' });
    setTimeout(() => setSaveStatus(null), 3500);
  }, [savedWorkflow]);

  // Keyboard shortcuts (Ctrl+Z, Ctrl+Y, Ctrl+Shift+Z)
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'z') {
        if (e.shiftKey) {
          e.preventDefault();
          handleRedo();
        } else {
          e.preventDefault();
          handleUndo();
        }
      } else if ((e.ctrlKey || e.metaKey) && e.key === 'y') {
        e.preventDefault();
        handleRedo();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [handleUndo, handleRedo]);

  // Handle node position changes after dragging stops
  const handleNodesChange = useCallback(
    (changes: NodeChange<Node<IRNode>>[]) => {
      onNodesChange(changes);
      const positionChanges = changes.filter(
        (c): c is NodePositionChange => c.type === 'position' && !!c.position && !c.dragging
      );
      if (positionChanges.length > 0 && currentWorkflow) {
        // Collect current known coordinates from flow canvas nodes to avoid resetting un-dragged nodes
        const currentPosMap = new Map<string, { x: number; y: number }>();
        nodes.forEach((flowNode) => {
          if (flowNode.position) {
            currentPosMap.set(flowNode.id, flowNode.position);
          }
        });

        const nextNodes = currentWorkflow.nodes.map((n) => {
          const match = positionChanges.find((c) => c.id === n.id);
          if (match && match.position) {
            return { ...n, position: { x: Math.round(match.position.x), y: Math.round(match.position.y) } };
          }
          if (n.position && (n.position.x !== 0 || n.position.y !== 0)) {
            return n;
          }
          const existingPos = currentPosMap.get(n.id);
          if (existingPos) {
            return { ...n, position: { x: Math.round(existingPos.x), y: Math.round(existingPos.y) } };
          }
          return n;
        });
        pushEdit({ ...currentWorkflow, nodes: nextNodes });
      }
    },
    [onNodesChange, currentWorkflow, pushEdit, nodes]
  );

  // Explicit Auto-Layout triggered by user
  const handleAutoLayout = useCallback(() => {
    if (!currentWorkflow || !currentWorkflow.nodes || currentWorkflow.nodes.length === 0) return;
    const layoutMap = computeFallbackLayout(currentWorkflow.nodes, currentWorkflow.edges || []);
    const nextNodes = currentWorkflow.nodes.map((n) => {
      const pos = layoutMap.get(n.id);
      return pos ? { ...n, position: { x: Math.round(pos.x), y: Math.round(pos.y) } } : n;
    });
    pushEdit({ ...currentWorkflow, nodes: nextNodes });
    setTimeout(() => {
      fitView({ padding: 0.2, duration: 300 });
    }, 50);
  }, [currentWorkflow, pushEdit, fitView]);

  // Handle new connection created by dragging between handles
  const handleConnect = useCallback(
    (connection: Connection) => {
      if (!currentWorkflow || !connection.source || !connection.target) return;
      if (connection.source === connection.target) return;

      const isError = connection.sourceHandle === 'error';
      let sourceOutputIndex = 0;
      if (!isError && connection.sourceHandle) {
        const match = connection.sourceHandle.match(/output-(\d+)/);
        if (match) sourceOutputIndex = parseInt(match[1], 10);
      }

      let targetInputIndex = 0;
      if (connection.targetHandle) {
        const match = connection.targetHandle.match(/input-(\d+)/);
        if (match) targetInputIndex = parseInt(match[1], 10);
      }

      // Check if connection already exists
      const exists = (currentWorkflow.edges || []).some(
        (e) =>
          e.source_id === connection.source &&
          e.target_id === connection.target &&
          (e.connection_type || 'main') === (isError ? 'error' : 'main') &&
          (e.source_output_index || 0) === sourceOutputIndex &&
          (e.target_input_index || 0) === targetInputIndex
      );
      if (exists) return;

      const newEdge: IREdge = {
        source_id: connection.source,
        target_id: connection.target,
        connection_type: isError ? 'error' : 'main',
        source_output_index: sourceOutputIndex,
        target_input_index: targetInputIndex,
      };

      pushEdit({
        ...currentWorkflow,
        edges: [...(currentWorkflow.edges || []), newEdge],
      });
    },
    [currentWorkflow, pushEdit]
  );

  // Remove edge
  const handleDeleteEdge = useCallback(
    (sourceId: string, targetId: string, sourceOutputIndex?: number, targetInputIndex?: number) => {
      if (!currentWorkflow) return;
      const nextEdges = (currentWorkflow.edges || []).filter((e) => {
        const matchSource = e.source_id === sourceId;
        const matchTarget = e.target_id === targetId;
        const matchOut = sourceOutputIndex === undefined || (e.source_output_index || 0) === sourceOutputIndex;
        const matchIn = targetInputIndex === undefined || (e.target_input_index || 0) === targetInputIndex;
        return !(matchSource && matchTarget && matchOut && matchIn);
      });
      pushEdit({ ...currentWorkflow, edges: nextEdges });
    },
    [currentWorkflow, pushEdit]
  );

  // Delete edges selected on canvas
  const handleEdgesDelete = useCallback(
    (edgesToDelete: Edge[]) => {
      if (!currentWorkflow) return;
      const deleteKeys = new Set(edgesToDelete.map((e) => `${e.source}->${e.target}`));
      const nextEdges = (currentWorkflow.edges || []).filter(
        (e) => !deleteKeys.has(`${e.source_id}->${e.target_id}`)
      );
      pushEdit({ ...currentWorkflow, edges: nextEdges });
    },
    [currentWorkflow, pushEdit]
  );

  // Update node properties (display name, parameters, execution policies)
  const handleUpdateNode = useCallback(
    (updatedNode: IRNode) => {
      if (!currentWorkflow) return;
      const nextNodes = currentWorkflow.nodes.map((n) => (n.id === updatedNode.id ? updatedNode : n));
      pushEdit({ ...currentWorkflow, nodes: nextNodes });
    },
    [currentWorkflow, pushEdit]
  );

  // Delete an existing node from the workflow
  const handleDeleteNode = useCallback(
    (nodeId: string) => {
      if (!currentWorkflow || isReadOnly) return;
      const nextNodes = (currentWorkflow.nodes || []).filter((n) => n.id !== nodeId);
      const nextEdges = (currentWorkflow.edges || []).filter(
        (e) => e.source_id !== nodeId && e.target_id !== nodeId
      );
      pushEdit({ ...currentWorkflow, nodes: nextNodes, edges: nextEdges });
      setSelectedNodeId(null);
      if (onSelectNode) onSelectNode(null);
      setRightPanelMode('none');
    },
    [currentWorkflow, isReadOnly, onSelectNode, pushEdit]
  );

  // Add a verified node from NodeLibraryPanel
  const handleAddNodeFromLibrary = useCallback(
    (nodeDef: NodeCatalogItem) => {
      if (!currentWorkflow || isReadOnly) return;

      // Calculate intelligent position
      const existingCount = currentWorkflow.nodes?.length || 0;
      let posX = 250;
      let posY = 250;

      if (existingCount > 0) {
        const lastNode = currentWorkflow.nodes[existingCount - 1];
        posX = (lastNode.position?.x || 250) + 280;
        posY = lastNode.position?.y || 250;
      }

      // Generate unique node ID
      const sanitizedName = (nodeDef.name || 'node').toLowerCase().replace(/[^a-z0-9_]/g, '');
      const uniqueSuffix = Date.now().toString(36).slice(-4);
      const nodeId = `${sanitizedName}_${uniqueSuffix}`;

      const newNode: IRNode = {
        id: nodeId,
        name: nodeDef.display_name || nodeDef.name,
        node_type: nodeDef.canonical_name,
        type_version: nodeDef.default_version || 1,
        position: { x: posX, y: posY },
        parameters: {},
        credentials: {},
        disabled: false,
        execution_policy: {
          continue_on_fail: false,
          retry_on_fail: false,
          max_tries: 3,
          wait_between_tries: 1000,
        },
      };

      const nextNodes = [...(currentWorkflow.nodes || []), newNode];

      // Auto-connect if there was a previous node and this is an action node
      let nextEdges = [...(currentWorkflow.edges || [])];
      if (existingCount > 0 && !nodeDef.is_trigger) {
        const lastNode = currentWorkflow.nodes[existingCount - 1];
        // Connect last node output to this node input if not already connected
        const hasOut = nextEdges.some((e) => e.source_id === lastNode.id && (e.source_output_index || 0) === 0);
        if (!hasOut) {
          nextEdges.push({
            source_id: lastNode.id,
            target_id: nodeId,
            connection_type: 'main',
            source_output_index: 0,
            target_input_index: 0,
          });
        }
      }

      pushEdit({ ...currentWorkflow, nodes: nextNodes, edges: nextEdges });

      // Automatically select the new node and open its properties panel
      setSelectedNodeId(nodeId);
      if (onSelectNode) onSelectNode(newNode);
      setRightPanelMode('properties');
    },
    [currentWorkflow, isReadOnly, onSelectNode, pushEdit]
  );

  // Save current workflow as a new PostgreSQL draft revision
  const handleSaveRevision = async () => {
    if (!currentWorkflow || !conversationId || isSaving) return;
    setIsSaving(true);
    setSaveStatus(null);

    try {
      const res = await saveDraftRevision(
        conversationId,
        currentWorkflow,
        currentRevNumber,
        currentWorkflow.name
      );

      setSavedWorkflow(currentWorkflow);
      setCurrentRevNumber(res.revision_number);

      if (res.is_valid) {
        setSaveStatus({
          type: 'success',
          message: `Saved revision #${res.revision_number}. Schema validated successfully.`,
        });
        setLocalIssues([]);
      } else {
        setSaveStatus({
          type: 'warning',
          message: `Saved revision #${res.revision_number} with validation errors. (Cannot be marked ready until resolved).`,
        });
        setLocalIssues(res.validation_report?.issues || []);
      }

      if (onRevisionSaved) {
        onRevisionSaved(res);
      }
    } catch (err: any) {
      if (err.status === 409) {
        try {
          const latestList = await listDraftRevisions(conversationId);
          if (latestList && latestList.length > 0) {
            const latestRevNum = latestList[0].revision_number;
            setCurrentRevNumber(latestRevNum);
            setSaveStatus({
              type: 'error',
              message: `Stale revision conflict: The draft is currently at revision #${latestRevNum}. Your local canvas edits are preserved. Click "Save Revision" to save as revision #${latestRevNum + 1}, or open History to reload.`,
            });
          } else {
            setSaveStatus({
              type: 'error',
              message: err.message || 'Stale revision conflict: Another revision was saved concurrently.',
            });
          }
        } catch {
          setSaveStatus({
            type: 'error',
            message: err.message || 'Stale revision conflict: Another revision was saved concurrently.',
          });
        }
      } else {
        setSaveStatus({
          type: 'error',
          message: err.message || 'Failed to persist draft revision.',
        });
      }
    } finally {
      setIsSaving(false);
    }
  };

  // Open Revisions History modal
  const handleOpenHistory = async () => {
    if (!conversationId) return;
    setShowHistoryModal(true);
    setIsLoadingHistory(true);
    try {
      const list = await listDraftRevisions(conversationId);
      setRevisionsList(list);
    } catch {
      setRevisionsList([]);
    } finally {
      setIsLoadingHistory(false);
    }
  };

  // Restore a specific past revision
  const handleRestoreRevision = async (revNumber: number) => {
    if (!conversationId) return;
    try {
      const detail = await getDraftRevision(conversationId, revNumber);
      if (detail.workflow_ir) {
        setCurrentWorkflow(detail.workflow_ir as WorkflowIR);
        setSavedWorkflow(detail.workflow_ir as WorkflowIR);
        setHistoryPast([]);
        setHistoryFuture([]);
        setCurrentRevNumber(detail.revision_number);
        setShowHistoryModal(false);
        setSaveStatus({
          type: 'success',
          message: `Restored revision #${detail.revision_number} from database history.`,
        });
        setTimeout(() => setSaveStatus(null), 3500);
      }
    } catch (err: any) {
      setSaveStatus({ type: 'error', message: err.message || 'Failed to restore revision.' });
    }
  };

  // Node registration for React Flow
  const nodeTypes = useMemo(() => ({ n8nNode: WorkflowNodeCard }), []);

  const handleNodeClick: NodeMouseHandler = useCallback(
    (_event, node) => {
      setSelectedNodeId(node.id);
      setRightPanelMode('properties');
      if (onSelectNode) {
        const found = currentWorkflow?.nodes?.find((n) => n.id === node.id) || null;
        onSelectNode(found);
      }
    },
    [currentWorkflow, onSelectNode]
  );

  const handlePaneClick = useCallback(() => {
    setSelectedNodeId(null);
    if (onSelectNode) onSelectNode(null);
  }, [onSelectNode]);

  const handleCloseInspector = useCallback(() => {
    setSelectedNodeId(null);
    setRightPanelMode('none');
    if (onSelectNode) onSelectNode(null);
  }, [onSelectNode]);

  if (!currentWorkflow) {
    return (
      <div
        className="canvas-container empty"
        style={{
          height: '100%',
          minHeight: '480px',
          backgroundColor: 'var(--bg-app)',
          border: '1px solid var(--border-default)',
          borderRadius: 'var(--radius-md)',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          gap: '12px',
          padding: '24px',
          color: 'var(--text-secondary)',
        }}
      >
        <CircleDashed size={36} style={{ color: 'var(--border-focused)' }} />
        <div style={{ fontSize: '14px', fontWeight: 600, color: 'var(--text-primary)' }}>
          No workflow to display
        </div>
      </div>
    );
  }

  const isWorkflowEmpty = !currentWorkflow.nodes || currentWorkflow.nodes.length === 0;

  return (
    <div
      className="workflow-editor-fullpage"
      style={{
        position: 'relative',
        width: '100%',
        height: '100%',
        minHeight: '620px',
        backgroundColor: 'var(--bg-app)',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
      }}
    >
      {/* 1. Slim Horizontal Top Toolbar */}
      <header
        className="workflow-editor-topbar"
        style={{
          height: '52px',
          backgroundColor: 'var(--bg-surface)',
          borderBottom: '1px solid var(--border-default)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '0 16px',
          zIndex: 15,
          flexShrink: 0,
        }}
      >
        {/* Left: Breadcrumb & Editable Workflow Name */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', minWidth: 0 }}>
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              fontSize: '13px',
              color: 'var(--text-secondary)',
              whiteSpace: 'nowrap',
            }}
          >
            <span>Workflows</span>
            <ChevronRight size={14} style={{ color: 'var(--text-tertiary)' }} />
          </div>

          <input
            type="text"
            value={currentWorkflow.name}
            disabled={isReadOnly}
            onChange={(e) => {
              if (currentWorkflow && !isReadOnly) {
                pushEdit({ ...currentWorkflow, name: e.target.value });
              }
            }}
            placeholder="Workflow name..."
            aria-label="Workflow Name"
            style={{
              fontSize: '14px',
              fontWeight: 600,
              color: 'var(--text-primary)',
              backgroundColor: 'transparent',
              border: '1px solid transparent',
              borderRadius: 'var(--radius-sm)',
              padding: '4px 8px',
              maxWidth: '280px',
              transition: 'border-color 0.15s ease',
            }}
            onFocus={(e) => {
              e.target.style.backgroundColor = 'var(--bg-surface-subtle)';
              e.target.style.borderColor = 'var(--border-default)';
            }}
            onBlur={(e) => {
              e.target.style.backgroundColor = 'transparent';
              e.target.style.borderColor = 'transparent';
            }}
          />

          {/* Save Status Indicator */}
          <div
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '6px',
              padding: '3px 8px',
              borderRadius: 'var(--radius-sm)',
              fontSize: '11px',
              fontWeight: 500,
              backgroundColor: isDirty ? 'rgba(217, 119, 6, 0.10)' : 'rgba(5, 150, 105, 0.10)',
              color: isDirty ? 'var(--state-warning)' : 'var(--state-success)',
              border: `1px solid ${isDirty ? 'rgba(217, 119, 6, 0.25)' : 'rgba(5, 150, 105, 0.25)'}`,
            }}
          >
            <span
              style={{
                width: '6px',
                height: '6px',
                borderRadius: '50%',
                backgroundColor: isDirty ? 'var(--state-warning)' : 'var(--state-success)',
                display: 'inline-block',
              }}
            />
            <span>{isDirty ? 'Unsaved changes' : `Saved (rev #${currentRevNumber})`}</span>
          </div>

          {/* Validation Status Badge */}
          <span
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '4px',
              padding: '2px 7px',
              borderRadius: 'var(--radius-sm)',
              fontSize: '11px',
              fontWeight: 600,
              backgroundColor: isValid && localIssues.length === 0 ? 'var(--state-success-subtle)' : 'var(--state-warning-subtle)',
              color: isValid && localIssues.length === 0 ? 'var(--state-success)' : 'var(--state-warning)',
              border: `1px solid ${isValid && localIssues.length === 0 ? 'var(--state-success)' : 'var(--state-warning)'}`,
            }}
          >
            {isValid && localIssues.length === 0 ? 'Validated' : `${localIssues.length || 1} Issue(s)`}
          </span>
        </div>

        {/* Right: Controls & Actions */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          {/* Undo Button */}
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={handleUndo}
            disabled={historyPast.length === 0 || isReadOnly}
            title="Undo (Ctrl+Z)"
            aria-label="Undo edit"
            style={{ padding: '5px 8px' }}
          >
            <Undo2 size={14} />
          </button>

          {/* Redo Button */}
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={handleRedo}
            disabled={historyFuture.length === 0 || isReadOnly}
            title="Redo (Ctrl+Y)"
            aria-label="Redo edit"
            style={{ padding: '5px 8px' }}
          >
            <Redo2 size={14} />
          </button>

          {/* Explicit Auto-Layout Button */}
          {!isReadOnly && (
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={handleAutoLayout}
              title="Rearrange nodes into an organized auto-layout"
              aria-label="Auto-layout nodes"
              style={{ padding: '5px 8px', display: 'flex', alignItems: 'center', gap: '5px' }}
            >
              <LayoutGrid size={13} />
              <span style={{ fontSize: '12px' }}>Auto-layout</span>
            </button>
          )}

          {/* Discard Edits Button */}
          {isDirty && !isReadOnly && (
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={handleDiscard}
              title="Discard unsaved changes and restore saved revision"
              style={{ padding: '5px 8px', color: 'var(--state-warning)' }}
            >
              <RotateCcw size={13} />
              <span style={{ fontSize: '12px' }}>Discard</span>
            </button>
          )}

          {/* Save Draft Revision Button */}
          {conversationId && !isReadOnly && (
            <Button
              variant="secondary"
              size="sm"
              disabled={isSaving || !isDirty}
              onClick={handleSaveRevision}
              icon={isSaving ? <OrbitLoader size="inline" color="currentColor" /> : <Save size={13} />}
            >
              {isSaving ? 'Saving...' : 'Save'}
            </Button>
          )}

          {/* Test Run Control (Honest Read-Only Execution Notice) */}
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            disabled
            title="Live execution engine is read-only; use simulation test plan in Review & Deploy."
            style={{
              padding: '5px 10px',
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              opacity: 0.6,
              cursor: 'not-allowed',
            }}
          >
            <Play size={13} />
            <span style={{ fontSize: '12px' }}>Test run</span>
          </button>

          {/* Revisions History Button */}
          {conversationId && (
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={handleOpenHistory}
              title="View revision history and restore points"
              style={{ padding: '5px 8px' }}
            >
              <History size={14} />
            </button>
          )}

          {/* Review & Deploy (Publish) Control */}
          <Button
            variant="primary"
            size="sm"
            onClick={() => setShowReviewModal(true)}
            icon={<FileCheck2 size={14} />}
            title="Review workflow readiness and deploy"
          >
            <span>Review</span>
          </Button>
        </div>
      </header>

      {/* Floating Save Status Callout */}
      {saveStatus && (
        <div
          style={{
            position: 'absolute',
            top: '64px',
            left: '20px',
            zIndex: 20,
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            backgroundColor:
              saveStatus.type === 'success'
                ? 'var(--state-success-subtle)'
                : saveStatus.type === 'warning'
                ? 'var(--state-warning-subtle)'
                : 'var(--state-error-subtle)',
            color:
              saveStatus.type === 'success'
                ? 'var(--state-success)'
                : saveStatus.type === 'warning'
                ? 'var(--state-warning)'
                : 'var(--state-error)',
            border: `1px solid ${
              saveStatus.type === 'success'
                ? 'var(--state-success)'
                : saveStatus.type === 'warning'
                ? 'var(--state-warning)'
                : 'var(--state-error)'
            }`,
            borderRadius: 'var(--radius-sm)',
            padding: '8px 12px',
            fontSize: '12px',
            maxWidth: '540px',
            boxShadow: 'var(--shadow-md)',
          }}
        >
          {saveStatus.type === 'success' ? <CheckCircle2 size={14} /> : <AlertTriangle size={14} />}
          <span style={{ flex: 1 }}>{saveStatus.message}</span>
          <button
            type="button"
            onClick={() => setSaveStatus(null)}
            style={{ background: 'transparent', border: 'none', color: 'inherit', cursor: 'pointer', padding: '2px' }}
          >
            <X size={12} />
          </button>
        </div>
      )}

      {/* 2. Main Middle Workspace Area (Canvas + Docked Right Panel) */}
      <div style={{ flex: 1, display: 'flex', position: 'relative', overflow: 'hidden' }}>
        {/* Main Canvas Area */}
        <main
          style={{
            flex: 1,
            height: '100%',
            position: 'relative',
            backgroundColor: 'var(--bg-app)',
          }}
        >
          {isWorkflowEmpty ? (
            <div
              style={{
                height: '100%',
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '16px',
                padding: '24px',
                color: 'var(--text-secondary)',
              }}
            >
              <CircleDashed size={42} style={{ color: 'var(--border-focused)' }} />
              <div style={{ textAlign: 'center' }}>
                <h3 style={{ fontSize: '15px', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '4px' }}>
                  Workflow canvas is empty
                </h3>
                <p style={{ fontSize: '13px', color: 'var(--text-secondary)', maxWidth: '400px', margin: '0 auto 16px' }}>
                  Add your first trigger or action node from the node library to start building your automation.
                </p>
                <Button
                  variant="primary"
                  size="md"
                  onClick={() => setRightPanelMode('library')}
                  icon={<Plus size={15} />}
                >
                  Add node
                </Button>
              </div>
            </div>
          ) : (
            <ReactFlow
              nodes={nodes}
              edges={edges}
              onNodesChange={handleNodesChange}
              onEdgesChange={onEdgesChange}
              onConnect={handleConnect}
              onEdgesDelete={handleEdgesDelete}
              onNodeClick={handleNodeClick}
              onPaneClick={handlePaneClick}
              nodeTypes={nodeTypes}
              fitView
              fitViewOptions={{ padding: 0.2 }}
              minZoom={0.2}
              maxZoom={2.0}
              panOnDrag={isPanMode}
              selectionOnDrag={!isPanMode}
              nodesDraggable={!isReadOnly}
              nodesConnectable={!isReadOnly}
              elementsSelectable={true}
              proOptions={{ hideAttribution: true }}
              aria-label="Interactive Workflow Visual Canvas"
            >
              {/* Subtle Dotted Grid Background */}
              <Background
                variant={BackgroundVariant.Dots}
                gap={20}
                size={1.2}
                color="var(--border-default)"
              />

              {/* Standard Zoom Controls in bottom left */}
              <Controls
                showInteractive={false}
                position="bottom-left"
                style={{
                  backgroundColor: 'var(--bg-surface)',
                  border: '1px solid var(--border-default)',
                  borderRadius: 'var(--radius-sm)',
                  overflow: 'hidden',
                }}
              />

              {/* MiniMap in bottom right */}
              <MiniMap
                position="bottom-right"
                nodeColor="var(--border-focused)"
                maskColor="rgba(11, 15, 23, 0.75)"
                style={{
                  backgroundColor: 'var(--bg-surface)',
                  border: '1px solid var(--border-default)',
                  borderRadius: 'var(--radius-sm)',
                  width: 140,
                  height: 90,
                }}
              />
            </ReactFlow>
          )}

          {/* 3. Floating Bottom Canvas Toolbar */}
          <nav
            className="canvas-bottom-toolbar"
            aria-label="Canvas shortcuts toolbar"
            style={{
              position: 'absolute',
              bottom: '20px',
              left: '50%',
              transform: 'translateX(-50%)',
              zIndex: 10,
              backgroundColor: 'var(--bg-surface)',
              border: '1px solid var(--border-default)',
              borderRadius: 'var(--radius-md)',
              boxShadow: 'var(--shadow-lg)',
              padding: '5px 8px',
              display: 'flex',
              alignItems: 'center',
              gap: '4px',
            }}
          >
            {/* Pointer / Select Mode Toggle */}
            <button
              type="button"
              className={`btn btn-sm ${!isPanMode ? 'btn-primary' : 'btn-ghost'}`}
              onClick={() => setIsPanMode(false)}
              title="Select / Pointer Mode (V)"
              aria-label="Pointer mode"
              style={{ padding: '5px 8px' }}
            >
              <MousePointer size={14} />
            </button>

            {/* Hand / Pan Mode Toggle */}
            <button
              type="button"
              className={`btn btn-sm ${isPanMode ? 'btn-primary' : 'btn-ghost'}`}
              onClick={() => setIsPanMode(true)}
              title="Hand / Pan Canvas Mode (H)"
              aria-label="Hand pan mode"
              style={{ padding: '5px 8px' }}
            >
              <Hand size={14} />
            </button>

            <div style={{ width: '1px', height: '18px', backgroundColor: 'var(--border-subtle)', margin: '0 4px' }} />

            {/* Add Node Button */}
            <button
              type="button"
              className={`btn btn-sm ${rightPanelMode === 'library' ? 'btn-primary' : 'btn-secondary'}`}
              onClick={() => setRightPanelMode((prev) => (prev === 'library' ? 'none' : 'library'))}
              title="Add node to workflow"
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '5px',
                padding: '5px 10px',
                fontSize: '12px',
                fontWeight: 600,
              }}
            >
              <Plus size={14} />
              <span>Add node</span>
            </button>

            <div style={{ width: '1px', height: '18px', backgroundColor: 'var(--border-subtle)', margin: '0 4px' }} />

            {/* Zoom In Button */}
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={() => zoomIn()}
              title="Zoom In"
              aria-label="Zoom in"
              style={{ padding: '5px 8px' }}
            >
              <ZoomIn size={14} />
            </button>

            {/* Zoom Out Button */}
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={() => zoomOut()}
              title="Zoom Out"
              aria-label="Zoom out"
              style={{ padding: '5px 8px' }}
            >
              <ZoomOut size={14} />
            </button>

            {/* Fit View Button */}
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={() => fitView({ padding: 0.2 })}
              title="Fit View to All Nodes"
              aria-label="Fit view"
              style={{ padding: '5px 8px' }}
            >
              <Maximize2 size={14} />
            </button>

            <div style={{ width: '1px', height: '18px', backgroundColor: 'var(--border-subtle)', margin: '0 4px' }} />

            {/* Review Button */}
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={() => setShowReviewModal(true)}
              title="Open Workflow Review"
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '4px',
                padding: '5px 8px',
                fontSize: '12px',
              }}
            >
              <FileCheck2 size={13} />
              <span>Review</span>
            </button>
          </nav>
        </main>

        {/* 4. Docked Right-Side Panel: Dual Mode (Library vs Properties) */}
        {rightPanelMode === 'library' && (
          <NodeLibraryPanel
            onSelectNodeToAdd={handleAddNodeFromLibrary}
            onClose={() => setRightPanelMode('none')}
          />
        )}

        {rightPanelMode === 'properties' && selectedNode && (
          <NodeInspector
            node={selectedNode}
            allNodes={currentWorkflow.nodes}
            edges={currentWorkflow.edges || []}
            onClose={handleCloseInspector}
            onUpdateNode={handleUpdateNode}
            onDeleteNode={handleDeleteNode}
            onDeleteEdge={handleDeleteEdge}
            onSwitchToLibrary={() => setRightPanelMode('library')}
            isReadOnly={isReadOnly}
          />
        )}
      </div>

      {/* Revisions History Modal */}
      {showHistoryModal && (
        <div
          style={{
            position: 'absolute',
            inset: 0,
            zIndex: 30,
            backgroundColor: 'rgba(11, 15, 23, 0.80)',
            backdropFilter: 'blur(4px)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '24px',
          }}
        >
          <div
            style={{
              width: '480px',
              maxWidth: '100%',
              backgroundColor: 'var(--bg-surface)',
              border: '1px solid var(--border-default)',
              borderRadius: 'var(--radius-md)',
              boxShadow: 'var(--shadow-xl)',
              overflow: 'hidden',
              display: 'flex',
              flexDirection: 'column',
              maxHeight: '80vh',
            }}
          >
            {/* Header */}
            <div
              style={{
                padding: '14px 16px',
                borderBottom: '1px solid var(--border-subtle)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <History size={16} style={{ color: 'var(--brand-primary)' }} />
                <span style={{ fontSize: '14px', fontWeight: 600, color: 'var(--text-primary)' }}>
                  Draft Revision History
                </span>
              </div>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => setShowHistoryModal(false)}
                style={{ padding: '4px', color: 'var(--text-secondary)' }}
              >
                <X size={16} />
              </button>
            </div>

            {/* List */}
            <div style={{ flex: 1, overflowY: 'auto', padding: '12px 16px' }}>
              {isLoadingHistory ? (
                <div style={{ padding: '32px 0', textAlign: 'center' }}>
                  <OrbitLoader
                    size="sm"
                    label="Loading revision log..."
                    labelPosition="bottom"
                    center
                  />
                </div>
              ) : revisionsList.length === 0 ? (
                <div style={{ padding: '24px 0', textAlign: 'center', color: 'var(--text-tertiary)', fontSize: '13px' }}>
                  No saved revisions found for this draft yet.
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  {revisionsList.map((rev) => {
                    const isCurrent = rev.revision_number === currentRevNumber;
                    return (
                      <div
                        key={rev.revision_number}
                        style={{
                          padding: '10px 12px',
                          borderRadius: 'var(--radius-sm)',
                          border: isCurrent
                            ? '1.5px solid var(--brand-primary)'
                            : '1px solid var(--border-default)',
                          backgroundColor: isCurrent
                            ? 'var(--brand-primary-subtle)'
                            : 'var(--bg-surface-subtle)',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'space-between',
                          gap: '12px',
                        }}
                      >
                        <div style={{ flex: 1 }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                            <span style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-primary)' }}>
                              Revision #{rev.revision_number}
                            </span>
                            {isCurrent && (
                              <span
                                style={{
                                  fontSize: '10px',
                                  fontWeight: 600,
                                  padding: '1px 5px',
                                  borderRadius: 'var(--radius-sm)',
                                  backgroundColor: 'var(--brand-primary)',
                                  color: '#FFFFFF',
                                }}
                              >
                                Current
                              </span>
                            )}
                          </div>
                          <div style={{ fontSize: '11px', color: 'var(--text-tertiary)', marginTop: '2px' }}>
                            {rev.created_at ? new Date(rev.created_at).toLocaleString() : 'Timestamp unavailable'} •{' '}
                            {rev.node_count} nodes
                          </div>
                        </div>

                        {!isCurrent && (
                          <button
                            type="button"
                            className="btn btn-secondary btn-sm"
                            onClick={() => handleRestoreRevision(rev.revision_number)}
                            style={{ fontSize: '12px', padding: '4px 8px' }}
                          >
                            Restore
                          </button>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Review & Readiness Assessment Modal */}
      {showReviewModal && conversationId && currentWorkflow && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            zIndex: 100,
            backgroundColor: 'rgba(0, 0, 0, 0.65)',
            backdropFilter: 'blur(2px)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '24px',
          }}
          onClick={(e) => {
            if (e.target === e.currentTarget) setShowReviewModal(false);
          }}
        >
          <div
            style={{
              width: '920px',
              maxWidth: '95vw',
              maxHeight: '90vh',
              display: 'flex',
              flexDirection: 'column',
              overflow: 'hidden',
              borderRadius: 'var(--radius-md, 6px)',
              boxShadow: 'var(--shadow-xl)',
            }}
          >
            <WorkflowReviewPanel
              conversationId={conversationId}
              workflow={currentWorkflow}
              currentRevisionNumber={currentRevNumber}
              isDirty={isDirty}
              onSaveRevision={handleSaveRevision}
              onClose={() => setShowReviewModal(false)}
              researchDossier={researchDossier}
              workflowPlan={workflowPlan}
            />
          </div>
        </div>
      )}
    </div>
  );
};

export const WorkflowCanvas: React.FC<WorkflowCanvasProps> = (props) => {
  return (
    <ReactFlowProvider>
      <WorkflowCanvasInner {...props} />
    </ReactFlowProvider>
  );
};
