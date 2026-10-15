"""Typed contracts for clarification questions, plans, and orchestrator turn results."""
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from backend.app.orchestrator.state_machine import ConversationState


class ClarificationOption(BaseModel):
    """Selectable option for a clarification question."""

    label: str
    value: str
    description: Optional[str] = None


class ClarificationQuestion(BaseModel):
    """Structured question targeted at resolving missing requirements."""

    id: str
    question: str
    field_key: str
    group: Optional[str] = None  # Service or step name, e.g. "Trigger: Google Sheets", "Action: Telegram Alert"
    step_number: Optional[int] = None
    input_type: str = "single_select"  # "single_select", "multi_select", "text", "url", "number", "boolean"
    allow_other: bool = True
    required: bool = True
    is_required: bool = True  # backward compatibility
    default_value: Optional[str] = None
    options: Optional[List[ClarificationOption]] = None
    help_text: Optional[str] = None
    placeholder: Optional[str] = None
    examples: Optional[List[str]] = None
    validation_rules: Optional[Dict[str, Any]] = None  # e.g. {"format": "url"}, {"format": "telegram_chat_id"}
    depends_on: Optional[Dict[str, Any]] = None  # e.g. {"field": "trigger", "equals": "email"}
    current_value: Optional[str] = None
    error_message: Optional[str] = None
    status: Optional[str] = None  # "answered", "missing", "invalid", "ambiguous"
    source: Optional[str] = None  # "prompt", "conversation", "form", "default"


class ClarificationAnswerItem(BaseModel):
    """Submitted answer for a structured clarification question."""

    question_id: str
    field_key: str
    selected_value: Optional[str] = None
    custom_text: Optional[str] = None


class BatchClarificationSubmission(BaseModel):
    """Batch collection of answers submitted together in a single user turn."""

    answers: List[ClarificationAnswerItem] = Field(default_factory=list)
    free_form_text: Optional[str] = None


class ClarificationPlan(BaseModel):
    """Result of ambiguity evaluation."""

    has_ambiguities: bool
    status: str = "ready_to_plan"  # "ready_to_plan", "waiting_for_info", "waiting_for_clarification", "blocked_invalid", "blocked_unsupported"
    questions: List[ClarificationQuestion] = Field(default_factory=list)
    current_question_id: Optional[str] = None
    outstanding_questions: List[str] = Field(default_factory=list)
    completed_answers: Dict[str, Any] = Field(default_factory=dict)
    field_errors: Dict[str, str] = Field(default_factory=dict)


class PlannedNode(BaseModel):
    """Specification of an intended node in the planned workflow graph."""

    id: str
    name: str
    node_type: str
    role: str = "action"  # "trigger", "action", "condition", "transform", "error_handler"
    operation: Optional[str] = None
    credential_type: Optional[str] = None
    description: str = ""
    parameters: Dict[str, Any] = Field(default_factory=dict)
    execution_policy: Dict[str, Any] = Field(default_factory=dict)


class PlannedEdge(BaseModel):
    """Specification of a directed connection between planned nodes."""

    source_id: str
    target_id: str
    source_output_index: int = 0  # 0 for main/true, 1 for false/secondary
    target_input_index: int = 0
    connection_type: str = "main"  # "main" or "error"
    condition_desc: Optional[str] = None


class WorkflowPlan(BaseModel):
    """Structured architectural plan created before generating WorkflowIR."""

    title: str
    objective: str
    target_services: List[str] = Field(default_factory=list)
    nodes: List[PlannedNode] = Field(default_factory=list)
    connections: List[PlannedEdge] = Field(default_factory=list)
    branch_conditions: List[Dict[str, Any]] = Field(default_factory=list)
    data_transformations: List[Dict[str, Any]] = Field(default_factory=list)
    state_tracking: Optional[Dict[str, Any]] = None
    error_handling_strategy: str = "continue_or_alert"
    expected_outputs: List[str] = Field(default_factory=list)
    research_dossier: Optional[Dict[str, Any]] = None


class OrchestratorTurnResult(BaseModel):
    """Result returned after processing a user message turn."""

    conversation_id: str
    state: ConversationState
    assistant_message: str
    clarification: Optional[ClarificationPlan] = None
    workflow_ir: Optional[Dict[str, Any]] = None
    compiled_json: Optional[Dict[str, Any]] = None
    validation_report: Optional[Dict[str, Any]] = None
    readiness_report: Optional[Dict[str, Any]] = None
    draft_id: Optional[str] = None
    revision_number: Optional[int] = None
    latest_revision_number: Optional[int] = None
    original_prompt: Optional[str] = None
    intent_summary: Optional[str] = None
    current_question_id: Optional[str] = None
    outstanding_questions: List[str] = Field(default_factory=list)
    completed_answers: Dict[str, Any] = Field(default_factory=dict)
    field_errors: Dict[str, str] = Field(default_factory=dict)
    research_dossier: Optional[Dict[str, Any]] = None
    workflow_plan: Optional[Dict[str, Any]] = None


