"""Conversation REST API endpoints managing conversation lifecycle and turn execution."""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import logging
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.session import get_db, get_session_factory
from backend.app.models.conversation import Conversation, ConversationMessage
from backend.app.models.workflow import WorkflowDraft, WorkflowRevision
from backend.app.orchestrator.engine import WorkflowOrchestrator
from backend.app.orchestrator.schemas import (
    BatchClarificationSubmission,
    ClarificationAnswerItem,
    OrchestratorTurnResult,
)
from backend.app.orchestrator.state_machine import ConversationState
from backend.app.schemas.ir import WorkflowIR, parse_workflow_ir
from backend.app.schemas.readiness import CredentialVerificationState, SafeSimulationResult, WorkflowReadinessReport
from backend.app.security.auth import UserContext, authenticate_websocket, get_current_user, verify_conversation_ownership
from backend.app.services.websocket_manager import get_websocket_manager
from backend.app.services.compiler import WorkflowCompiler
from backend.app.services.n8n_client import (
    N8nClient,
    N8nConnectionState,
    N8nDeploymentError,
    N8nDeploymentTimeoutError,
)
from backend.app.services.node_registry import NodeRegistry
from backend.app.services.readiness import WorkflowReadinessEvaluator
from backend.app.services.validator import WorkflowValidator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/conversations", tags=["conversations"])


# --- Request & Response Schemas ---

class DeployWorkflowRequest(BaseModel):
    expected_revision_number: Optional[int] = None
    idempotency_token: Optional[str] = None


class DeployWorkflowResponse(BaseModel):
    success: bool
    workflow_id: Optional[str] = None
    workflow_name: Optional[str] = None
    workflow_url: Optional[str] = None
    is_active: bool = False
    revision_number: int
    message: str


class WorkflowReadinessRequest(BaseModel):
    workflow_ir: Optional[Dict[str, Any]] = None


class WorkflowSimulateRequest(BaseModel):
    workflow_ir: Optional[Dict[str, Any]] = None


class CreateConversationRequest(BaseModel):
    id: Optional[str] = Field(default=None, description="Optional client-generated conversation ID")
    title: Optional[str] = Field(default=None, max_length=255)
    initial_prompt: Optional[str] = Field(default=None, max_length=10000)


class RenameConversationRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)


class SendMessageRequest(BaseModel):
    content: Optional[str] = Field(default="", max_length=10000)
    selected_options: Optional[Dict[str, str]] = None
    clarification_answers: Optional[List[ClarificationAnswerItem]] = None


class MessageResponse(BaseModel):
    id: str
    role: str
    content: str
    metadata_json: Optional[Dict[str, Any]] = None
    created_at: datetime


class ConversationSummaryResponse(BaseModel):
    id: str
    title: str
    state: str
    created_at: datetime
    updated_at: datetime
    message_count: int = 0
    latest_draft_id: Optional[str] = None


class ConversationDetailResponse(BaseModel):
    id: str
    title: str
    state: str
    created_at: datetime
    updated_at: datetime
    messages: List[MessageResponse]
    slots: Dict[str, Any] = Field(default_factory=dict)
    latest_draft: Optional[Dict[str, Any]] = None
    original_prompt: Optional[str] = None
    intent: Optional[Dict[str, Any]] = None
    clarification: Optional[Dict[str, Any]] = None
    current_question_id: Optional[str] = None
    outstanding_questions: List[str] = Field(default_factory=list)
    research_dossier: Optional[Dict[str, Any]] = None
    workflow_plan: Optional[Dict[str, Any]] = None



class ConversationStatusResponse(BaseModel):
    conversation_id: str
    is_active: bool
    stage: str
    message: Optional[str] = None
    elapsed_seconds: Optional[float] = None
    generation_id: Optional[str] = None
    timings: Optional[Dict[str, float]] = None
    slots: Optional[Dict[str, Any]] = None


class ValidateWorkflowRequest(BaseModel):
    workflow_ir: Dict[str, Any]


class ValidateWorkflowResponse(BaseModel):
    is_valid: bool
    validation_report: Dict[str, Any]
    compiled_json: Optional[Dict[str, Any]] = None


class SaveDraftRevisionRequest(BaseModel):
    workflow_ir: Dict[str, Any]
    expected_revision_number: Optional[int] = None
    title: Optional[str] = None


class SaveDraftRevisionResponse(BaseModel):
    draft_id: str
    revision_id: str
    revision_number: int
    title: str
    status: str
    is_valid: bool
    validation_report: Dict[str, Any]
    compiled_json: Optional[Dict[str, Any]] = None
    created_at: datetime


class RevisionSummaryResponse(BaseModel):
    id: str
    revision_number: int
    created_at: datetime
    is_valid: bool
    node_count: int
    edge_count: int


class RevisionDetailResponse(BaseModel):
    id: str
    draft_id: str
    revision_number: int
    workflow_ir: Dict[str, Any]
    compiled_json: Optional[Dict[str, Any]] = None
    validation_report: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime] = Field(default_factory=lambda: datetime.now(timezone.utc))


# --- Dependencies ---

_global_orchestrator: Optional[WorkflowOrchestrator] = None


def get_orchestrator() -> WorkflowOrchestrator:
    global _global_orchestrator
    if _global_orchestrator is None:
        _global_orchestrator = WorkflowOrchestrator()
    return _global_orchestrator


def get_compiler() -> WorkflowCompiler:
    return WorkflowCompiler()


def get_node_registry() -> NodeRegistry:
    return NodeRegistry()


def get_validator(registry: NodeRegistry = Depends(get_node_registry)) -> WorkflowValidator:
    return WorkflowValidator(registry=registry)


def get_readiness_evaluator(
    registry: NodeRegistry = Depends(get_node_registry),
    validator: WorkflowValidator = Depends(get_validator),
) -> WorkflowReadinessEvaluator:
    return WorkflowReadinessEvaluator(registry=registry, validator=validator)


# --- Endpoints ---

@router.post("", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
async def create_conversation(
    payload: CreateConversationRequest,
    db: AsyncSession = Depends(get_db),
    orchestrator: WorkflowOrchestrator = Depends(get_orchestrator),
    current_user: UserContext = Depends(get_current_user),
):
    """Create a new conversation, saving initial prompt before turn execution."""
    title = payload.title.strip() if payload.title and payload.title.strip() else "New Automation"
    conv_id = payload.id.strip() if payload.id and payload.id.strip() else str(uuid.uuid4())
    initial_prompt = payload.initial_prompt.strip() if payload.initial_prompt and payload.initial_prompt.strip() else None

    conv = Conversation(
        id=conv_id,
        title=title,
        metadata_json={
            "state": ConversationState.PLANNING.value,
            "slots": {},
            "original_prompt": initial_prompt,
            "user_id": current_user.user_id,
        },
    )
    db.add(conv)

    # Persist the initial user message immediately before turn processing begins
    if initial_prompt:
        user_msg = ConversationMessage(
            id=str(uuid.uuid4()),
            conversation_id=conv_id,
            role="user",
            content=initial_prompt,
            metadata_json={"is_initial_prompt": True},
        )
        db.add(user_msg)

    await db.commit()
    await db.refresh(conv)

    # If initial prompt is supplied, run the first turn (skip duplicate message persistence)
    turn_result = None
    if initial_prompt:
        turn_result = await orchestrator.execute_turn(
            conversation_id=conv_id,
            user_message_text=initial_prompt,
            db=db,
            skip_user_message_persistence=True,
        )

    return {
        "conversation_id": conv_id,
        "title": conv.title,
        "state": (turn_result.state.value if turn_result else ConversationState.PLANNING.value),
        "created_at": conv.created_at.isoformat(),
        "turn_result": turn_result.model_dump() if turn_result else None,
    }


@router.get("", response_model=List[ConversationSummaryResponse])
async def list_conversations(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    orchestrator: WorkflowOrchestrator = Depends(get_orchestrator),
    current_user: UserContext = Depends(get_current_user),
):
    """List conversations ordered by most recently updated with user isolation."""
    stmt = (
        select(Conversation)
        .order_by(desc(Conversation.updated_at))
        .limit(limit)
        .offset(offset)
    )
    res = await db.execute(stmt)
    conversations = list(res.scalars().all())

    summaries = []
    for c in conversations:
        meta = c.metadata_json or {}
        owner_id = meta.get("user_id")

        # Isolate conversations between users
        if owner_id and owner_id != current_user.user_id:
            continue
        if owner_id is None and current_user.user_id != "local_user":
            continue

        # Count messages
        msg_stmt = select(ConversationMessage.id).where(ConversationMessage.conversation_id == c.id)
        msg_res = await db.execute(msg_stmt)
        msg_count = len(list(msg_res.scalars().all()))

        active_info = orchestrator.get_active_stage(c.id) if orchestrator and hasattr(orchestrator, "get_active_stage") else None
        if isinstance(active_info, dict) and isinstance(active_info.get("stage"), str):
            conv_state = active_info["stage"]
        else:
            raw_state = meta.get("state")
            conv_state = raw_state if isinstance(raw_state, str) else "planning"
            if meta.get("latest_draft_id") and (not conv_state or conv_state in ("planning", "building", "generating", "validating")):
                conv_state = "ready"
            elif not conv_state:
                conv_state = "planning"

        summaries.append(
            ConversationSummaryResponse(
                id=c.id,
                title=c.title,
                state=conv_state,
                created_at=c.created_at,
                updated_at=c.updated_at,
                message_count=msg_count,
                latest_draft_id=meta.get("latest_draft_id"),
            )
        )
    return summaries


@router.get("/{conversation_id}", response_model=ConversationDetailResponse)
async def get_conversation(
    conversation_id: str,
    db: AsyncSession = Depends(get_db),
    orchestrator: WorkflowOrchestrator = Depends(get_orchestrator),
    current_user: UserContext = Depends(get_current_user),
):
    """Retrieve full conversation history, current state, and attached workflow draft."""
    stmt = select(Conversation).where(Conversation.id == conversation_id)
    res = await db.execute(stmt)
    conv = res.scalar_one_or_none()
    if not conv:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conversation '{conversation_id}' not found.",
        )
    verify_conversation_ownership(conv, current_user)

    # Messages
    msg_stmt = (
        select(ConversationMessage)
        .where(ConversationMessage.conversation_id == conversation_id)
        .order_by(ConversationMessage.created_at.asc())
    )
    msg_res = await db.execute(msg_stmt)
    messages = list(msg_res.scalars().all())

    # Latest draft
    draft_stmt = select(WorkflowDraft).where(WorkflowDraft.conversation_id == conversation_id)
    draft_res = await db.execute(draft_stmt)
    draft = draft_res.scalar_one_or_none()

    meta = conv.metadata_json or {}

    latest_draft_dict = None
    if draft:
        rev_stmt = (
            select(WorkflowRevision)
            .where(WorkflowRevision.draft_id == draft.id)
            .order_by(WorkflowRevision.revision_number.desc())
        )
        rev_res = await db.execute(rev_stmt)
        latest_rev = rev_res.scalars().first()
        latest_rev_num = latest_rev.revision_number if latest_rev else 1

        latest_draft_dict = {
            "id": draft.id,
            "title": draft.title,
            "status": draft.status,
            "workflow_ir": (latest_rev.workflow_ir if latest_rev and latest_rev.workflow_ir else draft.workflow_ir),
            "compiled_json": (latest_rev.compiled_json if latest_rev and latest_rev.compiled_json else draft.compiled_json),
            "validation_report": (latest_rev.validation_report if latest_rev else None),
            "latest_revision_number": latest_rev_num,
            "created_at": draft.created_at.isoformat(),
            "updated_at": draft.updated_at.isoformat(),
        }

    clarification_data = None
    if messages:
        last_asst = next((m for m in reversed(messages) if m.role == "assistant"), None)
        if last_asst and last_asst.metadata_json:
            clarification_data = last_asst.metadata_json.get("clarification")

    active_info = orchestrator.get_active_stage(conversation_id) if orchestrator and hasattr(orchestrator, "get_active_stage") else None
    if isinstance(active_info, dict) and isinstance(active_info.get("stage"), str):
        conv_state = active_info["stage"]
    else:
        raw_state = meta.get("state")
        conv_state = raw_state if isinstance(raw_state, str) else "planning"
        if draft and draft.workflow_ir and draft.status != "invalid" and conv_state not in ("clarifying", "failed"):
            if not conv_state or conv_state in ("planning", "building", "generating", "validating"):
                conv_state = "ready"
        elif not conv_state:
            conv_state = "planning"

    return ConversationDetailResponse(
        id=conv.id,
        title=conv.title,
        state=conv_state,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        messages=[
            MessageResponse(
                id=m.id,
                role=m.role,
                content=m.content,
                metadata_json=m.metadata_json,
                created_at=m.created_at,
            )
            for m in messages
        ],
        slots=meta.get("slots", {}),
        latest_draft=latest_draft_dict,
        original_prompt=meta.get("original_prompt"),
        intent=meta.get("intent"),
        clarification=clarification_data,
        current_question_id=meta.get("current_question_id"),
        outstanding_questions=meta.get("outstanding_questions", []),
        research_dossier=meta.get("research_dossier"),
        workflow_plan=meta.get("workflow_plan"),
    )


@router.get("/{conversation_id}/status", response_model=ConversationStatusResponse)
async def get_conversation_status(
    conversation_id: str,
    db: AsyncSession = Depends(get_db),
    orchestrator: WorkflowOrchestrator = Depends(get_orchestrator),
    current_user: UserContext = Depends(get_current_user),
):
    """Returns live execution status and stage information for the conversation."""
    # Fetch conversation and verify ownership first
    stmt = select(Conversation).where(Conversation.id == conversation_id)
    res = await db.execute(stmt)
    conv = res.scalar_one_or_none()
    if not conv:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conversation '{conversation_id}' not found.",
        )
    verify_conversation_ownership(conv, current_user)

    # Check in-flight orchestrator stage after verifying ownership
    meta = conv.metadata_json or {}
    active_info = orchestrator.get_active_stage(conversation_id) if orchestrator and hasattr(orchestrator, "get_active_stage") else None
    if isinstance(active_info, dict) and active_info.get("is_active"):
        active_info["slots"] = meta.get("slots", {})
        return ConversationStatusResponse(**active_info)

    raw_state = meta.get("state")

    # Check draft to report accurate idle or completed state instead of fabricating 'planning'
    draft_stmt = select(WorkflowDraft).where(WorkflowDraft.conversation_id == conversation_id)
    draft_res = await db.execute(draft_stmt)
    draft = draft_res.scalar_one_or_none()

    if draft and draft.workflow_ir and draft.status != "invalid" and raw_state not in ("clarifying", "failed"):
        state_val = "ready"
    elif raw_state in ("clarifying", "failed"):
        state_val = raw_state
    elif draft and draft.workflow_ir:
        state_val = "ready"
    elif raw_state:
        state_val = raw_state
    else:
        state_val = "idle"

    return ConversationStatusResponse(
        conversation_id=conversation_id,
        is_active=False,
        stage=state_val,
        message=None,
        elapsed_seconds=None,
        slots=meta.get("slots", {}),
    )


@router.websocket("/{conversation_id}/progress/ws")
async def generation_progress_ws(
    websocket: WebSocket,
    conversation_id: str,
):
    """Real-time WebSocket event subscription for generation lifecycle transitions."""
    user = await authenticate_websocket(websocket)
    session_factory = get_session_factory()
    async with session_factory() as db:
        stmt = select(Conversation).where(Conversation.id == conversation_id)
        res = await db.execute(stmt)
        conv = res.scalar_one_or_none()
        if not conv:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        try:
            verify_conversation_ownership(conv, user)
        except HTTPException:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

    ws_manager = get_websocket_manager()
    await ws_manager.connect(conversation_id, user.user_id, websocket)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.debug("WebSocket connection terminated for %s: %s", conversation_id, str(e))
    finally:
        await ws_manager.disconnect(conversation_id, websocket)



@router.post("/{conversation_id}/messages", response_model=OrchestratorTurnResult)
async def send_message(
    conversation_id: str,
    payload: SendMessageRequest,
    db: AsyncSession = Depends(get_db),
    orchestrator: WorkflowOrchestrator = Depends(get_orchestrator),
    current_user: UserContext = Depends(get_current_user),
):
    """Post a user message or clarification answer and execute an orchestrator turn."""
    clean_text = (payload.content or "").strip()
    if not clean_text and not payload.selected_options and not payload.clarification_answers:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Message content or clarification answers must be provided.",
        )

    conv_stmt = select(Conversation).where(Conversation.id == conversation_id)
    conv_res = await db.execute(conv_stmt)
    conv = conv_res.scalar_one_or_none()
    if not conv:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conversation '{conversation_id}' not found.",
        )
    verify_conversation_ownership(conv, current_user)

    try:
        kwargs = {}
        if payload.clarification_answers is not None:
            kwargs["clarification_answers"] = payload.clarification_answers

        result = await orchestrator.execute_turn(
            conversation_id=conversation_id,
            user_message_text=clean_text,
            db=db,
            selected_options=payload.selected_options,
            **kwargs,
        )
        return result
    except ValueError as ve:
        err_msg = str(ve)
        if "already in progress" in err_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=err_msg,
            )
        if "not exist" in err_msg.lower() or "not found" in err_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=err_msg,
            )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=err_msg,
        )


@router.post("/{conversation_id}/clarification/answers", response_model=OrchestratorTurnResult)
async def submit_batch_clarification_answers(
    conversation_id: str,
    payload: BatchClarificationSubmission,
    db: AsyncSession = Depends(get_db),
    orchestrator: WorkflowOrchestrator = Depends(get_orchestrator),
    current_user: UserContext = Depends(get_current_user),
):
    """Submit batch clarification answers for all outstanding questions in one transaction."""
    send_req = SendMessageRequest(
        content=payload.free_form_text or "",
        clarification_answers=payload.answers,
    )
    return await send_message(
        conversation_id=conversation_id,
        payload=send_req,
        db=db,
        orchestrator=orchestrator,
        current_user=current_user,
    )


@router.post("/{conversation_id}/retry", response_model=OrchestratorTurnResult)
async def retry_conversation(
    conversation_id: str,
    db: AsyncSession = Depends(get_db),
    orchestrator: WorkflowOrchestrator = Depends(get_orchestrator),
    current_user: UserContext = Depends(get_current_user),
):
    """Retries workflow generation for a failed turn without duplicating messages or conversations."""
    conv_stmt = select(Conversation).where(Conversation.id == conversation_id)
    conv_res = await db.execute(conv_stmt)
    conv = conv_res.scalar_one_or_none()
    if not conv:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conversation '{conversation_id}' not found.",
        )
    verify_conversation_ownership(conv, current_user)

    meta = conv.metadata_json or {}
    original_prompt = meta.get("original_prompt")
    if not original_prompt:
        msg_stmt = (
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == conversation_id, ConversationMessage.role == "user")
            .order_by(ConversationMessage.created_at.asc())
        )
        msg_res = await db.execute(msg_stmt)
        first_user_msg = msg_res.scalars().first()
        if first_user_msg:
            original_prompt = first_user_msg.content

    if not original_prompt:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Cannot retry: No prompt or user request found for this conversation.",
        )

    # 1. Concurrency guard: verify if a real generation request is genuinely running
    if (
        orchestrator
        and hasattr(orchestrator, "is_turn_active")
        and orchestrator.is_turn_active(conversation_id) is True
    ):
        active_info = orchestrator.get_active_stage(conversation_id) or {}
        stage = active_info.get("stage", "processing")
        elapsed = active_info.get("elapsed_seconds", 0)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"A workflow generation request is already in progress for conversation '{conversation_id}'. "
                f"Please wait for it to finish (stage: '{stage}', {elapsed}s elapsed)."
            ),
        )

    # Transition state back to planning
    meta["state"] = ConversationState.PLANNING.value
    conv.metadata_json = meta
    await db.commit()

    try:
        return await orchestrator.execute_turn(
            conversation_id=conversation_id,
            user_message_text=original_prompt,
            db=db,
            is_retry=True,
            skip_user_message_persistence=True,
        )
    except ValueError as ve:
        err_msg = str(ve)
        if "already in progress" in err_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=err_msg,
            )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=err_msg,
        )


@router.patch("/{conversation_id}", response_model=Dict[str, str])
async def rename_conversation(
    conversation_id: str,
    payload: RenameConversationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    """Rename conversation title."""
    stmt = select(Conversation).where(Conversation.id == conversation_id)
    res = await db.execute(stmt)
    conv = res.scalar_one_or_none()
    if not conv:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conversation '{conversation_id}' not found.",
        )
    verify_conversation_ownership(conv, current_user)

    conv.title = payload.title.strip()
    await db.commit()
    return {"id": conv.id, "title": conv.title}


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    """Delete a conversation, cascading deletion to messages, drafts, and revisions."""
    stmt = select(Conversation).where(Conversation.id == conversation_id)
    res = await db.execute(stmt)
    conv = res.scalar_one_or_none()
    if not conv:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conversation '{conversation_id}' not found.",
        )
    verify_conversation_ownership(conv, current_user)

    await db.delete(conv)
    await db.commit()
    return None


# --- Draft Revision & Validation Endpoints (Phase 5B) ---

@router.post("/{conversation_id}/draft/validate", response_model=ValidateWorkflowResponse)
async def validate_draft(
    conversation_id: str,
    payload: ValidateWorkflowRequest,
    db: AsyncSession = Depends(get_db),
    validator: WorkflowValidator = Depends(get_validator),
    compiler: WorkflowCompiler = Depends(get_compiler),
    current_user: UserContext = Depends(get_current_user),
):
    """Validate a candidate workflow IR without modifying the database."""
    conv_stmt = select(Conversation).where(Conversation.id == conversation_id)
    conv_res = await db.execute(conv_stmt)
    conv = conv_res.scalar_one_or_none()
    if not conv:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conversation '{conversation_id}' not found.",
        )
    verify_conversation_ownership(conv, current_user)

    try:
        workflow_ir = WorkflowIR(**payload.workflow_ir)
    except Exception as exc:
        return ValidateWorkflowResponse(
            is_valid=False,
            validation_report={
                "is_valid": False,
                "issues": [
                    {
                        "severity": "fatal",
                        "rule_code": "STRUCTURAL_IR_ERROR",
                        "message": str(exc),
                    }
                ],
            },
            compiled_json=None,
        )

    val_report = validator.validate(workflow_ir)
    compiled_json = None
    if val_report.is_valid:
        try:
            compiled_json = compiler.compile(workflow_ir)
        except Exception:
            compiled_json = None

    return ValidateWorkflowResponse(
        is_valid=val_report.is_valid,
        validation_report=val_report.model_dump(),
        compiled_json=compiled_json,
    )


@router.post(
    "/{conversation_id}/draft/revisions",
    response_model=SaveDraftRevisionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def save_draft_revision(
    conversation_id: str,
    payload: SaveDraftRevisionRequest,
    db: AsyncSession = Depends(get_db),
    validator: WorkflowValidator = Depends(get_validator),
    compiler: WorkflowCompiler = Depends(get_compiler),
    evaluator: Optional[WorkflowReadinessEvaluator] = Depends(get_readiness_evaluator),
    current_user: UserContext = Depends(get_current_user),
):
    """Save an edited workflow IR as a new PostgreSQL draft revision with concurrency protection."""
    active_evaluator = evaluator if isinstance(evaluator, WorkflowReadinessEvaluator) else WorkflowReadinessEvaluator(registry=validator.registry, validator=validator)

    # 1. Fetch conversation
    conv_stmt = select(Conversation).where(Conversation.id == conversation_id)
    conv_res = await db.execute(conv_stmt)
    conv = conv_res.scalar_one_or_none()
    if not conv:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conversation '{conversation_id}' not found.",
        )
    verify_conversation_ownership(conv, current_user)

    # 2. Acquire lock on WorkflowDraft to serialize concurrent revision creation
    draft_stmt = (
        select(WorkflowDraft)
        .where(WorkflowDraft.conversation_id == conversation_id)
        .with_for_update()
    )
    draft_res = await db.execute(draft_stmt)
    draft = draft_res.scalar_one_or_none()

    if not draft:
        draft_id = str(uuid.uuid4())
        draft = WorkflowDraft(
            id=draft_id,
            conversation_id=conversation_id,
            title=payload.title or "Edited Automation",
            status="draft",
        )
        db.add(draft)
        await db.flush()

    # 3. Query current maximum revision number
    rev_stmt = (
        select(func.max(WorkflowRevision.revision_number))
        .where(WorkflowRevision.draft_id == draft.id)
    )
    rev_res = await db.execute(rev_stmt)
    current_max_rev = rev_res.scalar() or 0

    # 4. Check for stale revision conflict (Optimistic Concurrency Control)
    if payload.expected_revision_number is not None and payload.expected_revision_number != current_max_rev:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Stale revision conflict: current revision is {current_max_rev}, "
                f"expected {payload.expected_revision_number}."
            ),
        )

    # 5. Parse and structurally validate WorkflowIR
    try:
        workflow_ir = WorkflowIR(**payload.workflow_ir)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Structural IR validation error: {str(exc)}",
        )

    # 6. Run deterministic schema validation and readiness evaluation
    val_report = validator.validate(workflow_ir)
    readiness_report = active_evaluator.evaluate(workflow_ir)

    compiled_json = None
    if val_report.is_valid:
        try:
            compiled_json = compiler.compile(workflow_ir)
            status_str = "ready"
        except Exception:
            status_str = "invalid"
    else:
        status_str = "invalid"

    # Invariant: Invalid or unconfigured drafts must never be marked ready
    meta = conv.metadata_json or {}
    if status_str == "ready":
        meta["state"] = "ready"
    else:
        if meta.get("state") == "ready":
            meta["state"] = "validating"
    conv.metadata_json = meta

    # 7. Increment revision number and persist WorkflowRevision
    new_rev_number = current_max_rev + 1
    rev_id = str(uuid.uuid4())
    ir_dict = workflow_ir.model_dump(mode="json")

    revision = WorkflowRevision(
        id=rev_id,
        draft_id=draft.id,
        revision_number=new_rev_number,
        workflow_ir=ir_dict,
        compiled_json=compiled_json,
        validation_report=val_report.model_dump(),
    )
    db.add(revision)

    # 8. Update WorkflowDraft
    draft.title = payload.title.strip() if payload.title and payload.title.strip() else (workflow_ir.name or draft.title)
    draft.status = status_str
    draft.workflow_ir = ir_dict
    draft.compiled_json = compiled_json

    await db.commit()
    await db.refresh(revision)
    await db.refresh(draft)

    return SaveDraftRevisionResponse(
        draft_id=draft.id,
        revision_id=revision.id,
        revision_number=new_rev_number,
        title=draft.title,
        status=draft.status,
        is_valid=val_report.is_valid,
        validation_report=val_report.model_dump(),
        compiled_json=compiled_json,
        created_at=revision.created_at or datetime.now(timezone.utc),
    )


@router.get("/{conversation_id}/draft/revisions", response_model=List[RevisionSummaryResponse])
async def list_draft_revisions(
    conversation_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    """List all revisions for the conversation's workflow draft."""
    draft_stmt = select(WorkflowDraft).where(WorkflowDraft.conversation_id == conversation_id)
    draft_res = await db.execute(draft_stmt)
    draft = draft_res.scalar_one_or_none()
    if not draft:
        return []

    conv_stmt = select(Conversation).where(Conversation.id == conversation_id)
    conv_res = await db.execute(conv_stmt)
    conv = conv_res.scalar_one_or_none()
    if conv:
        verify_conversation_ownership(conv, current_user)

    stmt = (
        select(WorkflowRevision)
        .where(WorkflowRevision.draft_id == draft.id)
        .order_by(desc(WorkflowRevision.revision_number))
    )
    res = await db.execute(stmt)
    revisions = list(res.scalars().all())

    summaries = []
    for r in revisions:
        rep = r.validation_report or {}
        is_val = rep.get("is_valid", False)
        wf_nodes = (r.workflow_ir or {}).get("nodes", [])
        wf_edges = (r.workflow_ir or {}).get("edges", [])
        summaries.append(
            RevisionSummaryResponse(
                id=r.id,
                revision_number=r.revision_number,
                created_at=r.created_at or datetime.now(timezone.utc),
                is_valid=is_val,
                node_count=len(wf_nodes),
                edge_count=len(wf_edges),
            )
        )
    return summaries


@router.get("/{conversation_id}/draft/revisions/{revision_identifier}", response_model=RevisionDetailResponse)
async def get_draft_revision(
    conversation_id: str,
    revision_identifier: str,
    db: AsyncSession = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    """Retrieve details and IR for a specific draft revision (by ID or revision number)."""
    draft_stmt = select(WorkflowDraft).where(WorkflowDraft.conversation_id == conversation_id)
    draft_res = await db.execute(draft_stmt)
    draft = draft_res.scalar_one_or_none()
    if not draft:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No draft found for conversation '{conversation_id}'.",
        )

    conv_stmt = select(Conversation).where(Conversation.id == conversation_id)
    conv_res = await db.execute(conv_stmt)
    conv = conv_res.scalar_one_or_none()
    if conv:
        verify_conversation_ownership(conv, current_user)

    if revision_identifier.isdigit():
        stmt = (
            select(WorkflowRevision)
            .where(
                WorkflowRevision.draft_id == draft.id,
                WorkflowRevision.revision_number == int(revision_identifier),
            )
        )
    else:
        stmt = (
            select(WorkflowRevision)
            .where(
                WorkflowRevision.draft_id == draft.id,
                WorkflowRevision.id == revision_identifier,
            )
        )

    res = await db.execute(stmt)
    rev = res.scalar_one_or_none()
    if not rev:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Revision '{revision_identifier}' not found for draft '{draft.id}'.",
        )

    return RevisionDetailResponse(
        id=rev.id,
        draft_id=rev.draft_id,
        revision_number=rev.revision_number,
        workflow_ir=rev.workflow_ir,
        compiled_json=rev.compiled_json,
        validation_report=rev.validation_report,
        created_at=rev.created_at or datetime.now(timezone.utc),
    )


@router.get("/nodes/search")
async def search_nodes(
    q: str = Query(default="", description="Search query string"),
    category: Optional[str] = Query(default=None, description="Group category filter"),
    is_trigger: Optional[bool] = Query(default=None, description="Filter triggers or actions"),
    limit: int = Query(default=60, ge=1, le=200, description="Max results"),
    node_registry: NodeRegistry = Depends(get_node_registry),
    current_user: UserContext = Depends(get_current_user),
):
    """Search verified n8n nodes from the node registry."""
    results = node_registry.search(
        query=q,
        category=category,
        is_trigger=is_trigger,
        limit=limit,
    )
    return [
        {
            "name": n.name,
            "canonical_name": n.canonical_name,
            "display_name": n.display_name,
            "description": n.description,
            "group": n.group,
            "is_trigger": n.is_trigger,
            "default_version": n.default_version,
            "supported_versions": n.supported_versions,
            "inputs": n.inputs if isinstance(n.inputs, list) else [],
            "outputs": n.outputs if isinstance(n.outputs, list) else [],
            "credentials": [c.model_dump() for c in n.credentials],
            "operations": n.operations,
            "resources": n.resources,
        }
        for n in results
    ]


@router.get("/nodes/definition/{node_type:path}")
async def get_node_definition(
    node_type: str,
    node_registry: NodeRegistry = Depends(get_node_registry),
    current_user: UserContext = Depends(get_current_user),
):
    """Retrieve schema definition and properties for an n8n node type from the registry."""
    node_def = node_registry.get_node(node_type)
    if not node_def:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Node type '{node_type}' not found in registry.",
        )
    return {
        "name": node_def.name,
        "canonical_name": node_def.canonical_name,
        "display_name": node_def.display_name,
        "description": node_def.description,
        "default_version": node_def.default_version,
        "supported_versions": node_def.supported_versions,
        "credentials": [c.model_dump() for c in node_def.credentials],
        "expected_credentials": [c.model_dump() for c in node_def.get_expected_credentials()],
        "properties": [p.model_dump() for p in node_def.properties],
    }


@router.post("/{conversation_id}/draft/readiness", response_model=Dict[str, Any])
async def evaluate_draft_readiness(
    conversation_id: str,
    payload: Optional[WorkflowReadinessRequest] = None,
    db: AsyncSession = Depends(get_db),
    evaluator: WorkflowReadinessEvaluator = Depends(get_readiness_evaluator),
    current_user: UserContext = Depends(get_current_user),
):
    """Evaluate workflow readiness, credential prerequisites, and safe test plan."""
    conv_stmt = select(Conversation).where(Conversation.id == conversation_id)
    conv_res = await db.execute(conv_stmt)
    conv = conv_res.scalar_one_or_none()
    if not conv:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conversation '{conversation_id}' not found.",
        )
    verify_conversation_ownership(conv, current_user)

    wf_ir_dict = payload.workflow_ir if payload and payload.workflow_ir else None
    if not wf_ir_dict:
        stmt = select(WorkflowDraft).where(WorkflowDraft.conversation_id == conversation_id)
        res = await db.execute(stmt)
        draft = res.scalar_one_or_none()
        if not draft or not draft.workflow_ir:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No workflow draft found for conversation '{conversation_id}'.",
            )
        wf_ir_dict = draft.workflow_ir

    try:
        wf = parse_workflow_ir(wf_ir_dict)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid workflow IR structure: {str(exc)}",
        )

    meta = conv.metadata_json or {}
    prompt_context = meta.get("original_prompt")

    available_creds = None
    try:
        async with N8nClient() as n8n_client:
            available_creds = await n8n_client.get_credentials()
    except Exception:
        available_creds = None

    report = evaluator.evaluate(wf, prompt_context=prompt_context, available_n8n_credentials=available_creds)
    return report.model_dump()


@router.post("/{conversation_id}/draft/simulate", response_model=Dict[str, Any])
async def simulate_draft_dry_run(
    conversation_id: str,
    payload: Optional[WorkflowSimulateRequest] = None,
    db: AsyncSession = Depends(get_db),
    evaluator: WorkflowReadinessEvaluator = Depends(get_readiness_evaluator),
    current_user: UserContext = Depends(get_current_user),
):
    """Execute a safe, deterministic, non-mutating static simulation dry-run."""
    conv_stmt = select(Conversation).where(Conversation.id == conversation_id)
    conv_res = await db.execute(conv_stmt)
    conv = conv_res.scalar_one_or_none()
    if not conv:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conversation '{conversation_id}' not found.",
        )
    verify_conversation_ownership(conv, current_user)

    wf_ir_dict = payload.workflow_ir if payload and payload.workflow_ir else None
    if not wf_ir_dict:
        stmt = select(WorkflowDraft).where(WorkflowDraft.conversation_id == conversation_id)
        res = await db.execute(stmt)
        draft = res.scalar_one_or_none()
        if not draft or not draft.workflow_ir:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No workflow draft found for conversation '{conversation_id}'.",
            )
        wf_ir_dict = draft.workflow_ir

    try:
        wf = parse_workflow_ir(wf_ir_dict)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid workflow IR structure: {str(exc)}",
        )

    sim_result = evaluator.simulate_dry_run(wf)
    return sim_result.model_dump()


@router.post("/{conversation_id}/draft/deploy", response_model=DeployWorkflowResponse)
async def deploy_draft_workflow(
    conversation_id: str,
    payload: Optional[DeployWorkflowRequest] = None,
    db: AsyncSession = Depends(get_db),
    evaluator: WorkflowReadinessEvaluator = Depends(get_readiness_evaluator),
    compiler: WorkflowCompiler = Depends(get_compiler),
    current_user: UserContext = Depends(get_current_user),
):
    """Deploy the exact saved draft revision to the connected n8n instance as an inactive workflow.

    Enforces human approval gate, pre-deployment parameter validation, optimistic concurrency,
    and duplicate protection. Workflows are always deployed with active=False.
    """
    # 1. Fetch conversation and verify ownership
    conv_stmt = select(Conversation).where(Conversation.id == conversation_id)
    conv_res = await db.execute(conv_stmt)
    conv = conv_res.scalar_one_or_none()
    if not conv:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conversation '{conversation_id}' not found.",
        )
    verify_conversation_ownership(conv, current_user)

    # 2. Acquire lock on WorkflowDraft to serialize deployment requests
    draft_stmt = (
        select(WorkflowDraft)
        .where(WorkflowDraft.conversation_id == conversation_id)
        .with_for_update()
    )
    draft_res = await db.execute(draft_stmt)
    draft = draft_res.scalar_one_or_none()
    if not draft:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No workflow draft found for conversation '{conversation_id}'.",
        )

    # 3. Retrieve latest persisted revision
    rev_stmt = (
        select(WorkflowRevision)
        .where(WorkflowRevision.draft_id == draft.id)
        .order_by(desc(WorkflowRevision.revision_number))
    )
    latest_rev = (await db.execute(rev_stmt)).scalars().first()
    if not latest_rev:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Draft has no saved revisions. Please save a revision before deploying.",
        )

    # 4. Optimistic concurrency check: exact revision being approved must match latest revision
    if payload and payload.expected_revision_number is not None:
        if latest_rev.revision_number != payload.expected_revision_number:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Stale revision conflict: current saved revision is {latest_rev.revision_number}, "
                    f"expected {payload.expected_revision_number}. Please reload and save the latest revision before deploying."
                ),
            )

    # 5. Duplicate submission / Idempotency protection
    meta = conv.metadata_json or {}
    existing_dep = meta.get("deployment")
    if existing_dep and isinstance(existing_dep, dict):
        token_matches = (
            payload
            and payload.idempotency_token
            and existing_dep.get("idempotency_token") == payload.idempotency_token
        )
        same_revision_deployed = (
            draft.status == "deployed"
            and existing_dep.get("revision_number") == latest_rev.revision_number
            and existing_dep.get("workflow_id")
        )
        if token_matches or same_revision_deployed:
            return DeployWorkflowResponse(
                success=True,
                workflow_id=existing_dep.get("workflow_id"),
                workflow_name=existing_dep.get("workflow_name"),
                workflow_url=existing_dep.get("workflow_url"),
                is_active=False,
                revision_number=latest_rev.revision_number,
                message="Workflow was already deployed for this revision.",
            )

    # 6. Revalidate the exact revision immediately before making the write request
    try:
        wf = parse_workflow_ir(latest_rev.workflow_ir)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Saved revision contains invalid workflow IR: {str(exc)}",
        )

    readiness = evaluator.evaluate(wf)
    if not readiness.is_structure_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Workflow failed structural validation and cannot be deployed.",
        )
    if not readiness.is_configuration_complete:
        missing_str = ", ".join(readiness.unresolved_configuration) if readiness.unresolved_configuration else "Required parameters missing"
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Deployment blocked: workflow contains unconfigured required parameters: {missing_str}.",
        )
    if not readiness.is_deployment_ready:
        missing_creds = [c.credential_type for c in readiness.credentials if c.verification_state == CredentialVerificationState.MISSING]
        missing_desc = f"Missing credentials: {', '.join(missing_creds)}" if missing_creds else "Unresolved configuration or credentials"
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Deployment blocked: workflow is not deploy-ready ({missing_desc}).",
        )

    # 7. Check connectivity and compatibility with n8n instance
    async with N8nClient() as n8n_client:
        conn_res = await n8n_client.check_connection()
        if conn_res.status != N8nConnectionState.CONNECTED:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Target n8n instance is not connected: {conn_res.message}",
            )

        # 8. Compile workflow to native n8n schema
        try:
            compiled_json = compiler.compile(wf)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Workflow compilation failed: {str(exc)}",
            )

        # 9. Create workflow in n8n via POST /api/v1/workflows (enforced inactive)
        try:
            creation = await n8n_client.create_workflow(compiled_json)
        except N8nDeploymentTimeoutError as te:
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail=te.message,
            )
        except N8nDeploymentError as de:
            status_code = de.status_code if de.status_code in (400, 401, 403, 502, 503) else status.HTTP_502_BAD_GATEWAY
            raise HTTPException(
                status_code=status_code,
                detail=de.message,
            )

    # 10. Persist deployment state
    draft.status = "deployed"
    draft.compiled_json = compiled_json
    meta["deployment"] = {
        "workflow_id": creation.workflow_id,
        "workflow_name": creation.workflow_name,
        "workflow_url": creation.workflow_url,
        "revision_number": latest_rev.revision_number,
        "idempotency_token": payload.idempotency_token if payload else None,
        "deployed_at": datetime.now(timezone.utc).isoformat(),
        "is_active": creation.is_active,
    }
    conv.metadata_json = meta

    await db.commit()
    await db.refresh(draft)

    return DeployWorkflowResponse(
        success=True,
        workflow_id=creation.workflow_id,
        workflow_name=creation.workflow_name,
        workflow_url=creation.workflow_url,
        is_active=creation.is_active,
        revision_number=latest_rev.revision_number,
        message=f"Workflow successfully created in n8n as inactive (ID: {creation.workflow_id}).",
    )
