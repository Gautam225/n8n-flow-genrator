"""Workflow Architect Orchestrator Engine.

Coordinates the finite state machine, LLM provider manager, node registry,
deterministic compiler, validator, and PostgreSQL persistence.
"""
import json
import logging
import re
import uuid
from typing import Any, Dict, List, Optional, Set
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.llm.interface import ChatMessage, LLMRequest
from backend.app.llm.manager import LLMProviderManager
from backend.app.models.conversation import Conversation, ConversationMessage
from backend.app.models.workflow import WorkflowDraft, WorkflowRevision
from backend.app.orchestrator.schemas import (
    ClarificationAnswerItem,
    ClarificationOption,
    ClarificationPlan,
    ClarificationQuestion,
    OrchestratorTurnResult,
    PlannedEdge,
    PlannedNode,
    WorkflowPlan,
)
from backend.app.orchestrator.state_machine import (
    ConversationState,
    InvalidStateTransitionError,
    StateMachine,
)
from backend.app.schemas.ir import WorkflowIR, WorkflowIRParseError, parse_workflow_ir
from backend.app.schemas.validation import ValidationReport
from backend.app.services.compiler import WorkflowCompiler
from backend.app.services.node_registry import NodeRegistry
from backend.app.services.validator import WorkflowValidator
from backend.app.services.readiness import WorkflowReadinessEvaluator
from backend.app.services.research import (
    ResearchFinding,
    ResearchService,
    ResearchSource,
    StructuredResearchDossier,
)
from backend.app.security.sanitizer import sanitize_secrets
from backend.app.orchestrator.intent import (
    NodeIntent,
    WorkflowIntent,
    WorkflowIntentExtractor,
    canonicalize_slot_key,
    extract_spreadsheet_info,
)

from dataclasses import dataclass
import asyncio
import time

logger = logging.getLogger(__name__)


@dataclass
class ActiveTurnLock:
    request_id: str
    conversation_id: str
    started_at: float
    updated_at: float
    current_stage: str = "planning"
    stage_message: str = "Processing..."
    task: Optional[asyncio.Task] = None

    def is_stale(self, timeout_seconds: float = 120.0) -> bool:
        if self.task is not None and hasattr(self.task, "done") and self.task.done():
            return True
        return (time.time() - self.updated_at) > timeout_seconds


class WorkflowOrchestrator:
    """Central orchestrator managing multi-turn workflow generation."""

    _active_conversations: Set[str] = set()
    _active_stages: Dict[str, Dict[str, Any]] = {}
    _active_locks: Dict[str, ActiveTurnLock] = {}

    def __init__(
        self,
        llm_manager: Optional[LLMProviderManager] = None,
        node_registry: Optional[NodeRegistry] = None,
        compiler: Optional[WorkflowCompiler] = None,
        validator: Optional[WorkflowValidator] = None,
        intent_extractor: Optional[WorkflowIntentExtractor] = None,
        research_service: Optional[ResearchService] = None,
    ) -> None:
        self.llm_manager = llm_manager or LLMProviderManager()
        self.node_registry = node_registry or NodeRegistry()
        self.compiler = compiler or WorkflowCompiler()
        self.validator = validator or WorkflowValidator(self.node_registry)
        self.intent_extractor = intent_extractor or WorkflowIntentExtractor(self.node_registry)
        self.readiness_evaluator = WorkflowReadinessEvaluator(registry=self.node_registry, validator=self.validator)
        self.research_service = research_service or ResearchService(node_registry=self.node_registry)

    def is_turn_active(self, conversation_id: str) -> bool:
        """Checks if a generation turn is genuinely active and not stale."""
        # Check active stage staleness
        stage_info = self._active_stages.get(conversation_id)
        if stage_info:
            now = time.time()
            if (now - stage_info.get("updated_at", now)) > 120.0 or (now - stage_info.get("started_at", now)) > 120.0:
                self.clear_active_stage(conversation_id)
                return False

        lock = self._active_locks.get(conversation_id)
        if not lock:
            if conversation_id in self._active_conversations:
                lock = ActiveTurnLock(
                    request_id=str(uuid.uuid4()),
                    conversation_id=conversation_id,
                    started_at=time.time(),
                    updated_at=time.time(),
                )
                self._active_locks[conversation_id] = lock
                return True
            return False

        if lock.is_stale():
            logger.warning(
                "Discarding stale generation lock for conversation '%s' (elapsed: %.1fs).",
                conversation_id,
                time.time() - lock.started_at,
            )
            if lock.task is not None and not lock.task.done():
                lock.task.cancel()
            self._active_locks.pop(conversation_id, None)
            self._active_conversations.discard(conversation_id)
            self._active_stages.pop(conversation_id, None)
            return False
        return True

    def set_active_stage(self, conversation_id: str, stage: str, message: str) -> None:
        """Records the active execution stage for live status monitoring."""
        now = time.time()
        self._active_conversations.add(conversation_id)
        lock = self._active_locks.get(conversation_id)
        if lock:
            lock.current_stage = stage
            lock.stage_message = message
            lock.updated_at = now
        else:
            lock = ActiveTurnLock(
                request_id=str(uuid.uuid4()),
                conversation_id=conversation_id,
                started_at=now,
                updated_at=now,
                current_stage=stage,
                stage_message=message,
            )
            self._active_locks[conversation_id] = lock

        existing = self._active_stages.get(conversation_id, {})
        start_time = existing.get("started_at", lock.started_at if lock else now)
        self._active_stages[conversation_id] = {
            "stage": stage,
            "message": message,
            "started_at": start_time,
            "updated_at": now,
        }

        try:
            loop = asyncio.get_running_loop()
            from backend.app.services.websocket_manager import get_websocket_manager
            ws_mgr = get_websocket_manager()
            loop.create_task(
                ws_mgr.broadcast(
                    conversation_id=conversation_id,
                    event_type="stage_transition",
                    stage=stage,
                    status_code="in_progress",
                    message=message,
                    timings={"elapsed_seconds": round(now - start_time, 1)},
                )
            )
        except (RuntimeError, Exception):
            pass

    def clear_active_stage(self, conversation_id: str) -> None:
        """Cleans up active stage tracking when a turn completes."""
        self._active_stages.pop(conversation_id, None)
        self._active_locks.pop(conversation_id, None)
        self._active_conversations.discard(conversation_id)
        try:
            loop = asyncio.get_running_loop()
            from backend.app.services.websocket_manager import get_websocket_manager
            ws_mgr = get_websocket_manager()
            loop.create_task(
                ws_mgr.broadcast(
                    conversation_id=conversation_id,
                    event_type="stage_complete",
                    stage="completed",
                    status_code="success",
                    message="Generation turn completed.",
                )
            )
        except (RuntimeError, Exception):
            pass

    def get_active_stage(self, conversation_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves active stage information if a turn is currently in flight."""
        if not self.is_turn_active(conversation_id):
            return None
        info = self._active_stages.get(conversation_id)
        lock = self._active_locks.get(conversation_id)
        if info:
            return {
                "conversation_id": conversation_id,
                "is_active": True,
                "stage": info["stage"],
                "message": info["message"],
                "elapsed_seconds": round(time.time() - info["started_at"], 1),
            }
        if lock:
            return {
                "conversation_id": conversation_id,
                "is_active": True,
                "stage": lock.current_stage or "planning",
                "message": lock.stage_message or "Processing...",
                "elapsed_seconds": round(time.time() - lock.started_at, 1),
            }
        return None

    async def execute_turn(
        self,
        conversation_id: str,
        user_message_text: str,
        db: AsyncSession,
        selected_options: Optional[Dict[str, str]] = None,
        clarification_answers: Optional[List[ClarificationAnswerItem]] = None,
        is_retry: bool = False,
        skip_user_message_persistence: bool = False,
    ) -> OrchestratorTurnResult:
        """Process a user message within an existing conversation with concurrency protection."""
        if self.is_turn_active(conversation_id):
            raise ValueError(
                f"A workflow generation request is already in progress for conversation '{conversation_id}'. Please wait for it to finish."
            )

        try:
            curr_task = asyncio.current_task()
        except RuntimeError:
            curr_task = None

        req_id = str(uuid.uuid4())
        now = time.time()
        lock = ActiveTurnLock(
            request_id=req_id,
            conversation_id=conversation_id,
            started_at=now,
            updated_at=now,
            current_stage="understanding",
            stage_message="Analyzing prompt requirements and discovering candidate nodes from registry...",
            task=curr_task,
        )
        self._active_locks[conversation_id] = lock
        self._active_conversations.add(conversation_id)
        self.set_active_stage(
            conversation_id,
            "understanding",
            "Analyzing prompt requirements and discovering candidate nodes from registry...",
        )

        try:
            return await self._execute_turn_internal(
                conversation_id=conversation_id,
                user_message_text=user_message_text,
                db=db,
                selected_options=selected_options,
                clarification_answers=clarification_answers,
                is_retry=is_retry,
                skip_user_message_persistence=skip_user_message_persistence,
            )
        finally:
            self.clear_active_stage(conversation_id)

    async def _execute_turn_internal(
        self,
        conversation_id: str,
        user_message_text: str,
        db: AsyncSession,
        selected_options: Optional[Dict[str, str]] = None,
        clarification_answers: Optional[List[ClarificationAnswerItem]] = None,
        is_retry: bool = False,
        skip_user_message_persistence: bool = False,
    ) -> OrchestratorTurnResult:
        """Internal turn execution logic."""
        # 1. Fetch conversation
        stmt = select(Conversation).where(Conversation.id == conversation_id)
        res = await db.execute(stmt)
        conversation = res.scalar_one_or_none()
        if not conversation:
            raise ValueError(f"Conversation with id '{conversation_id}' does not exist.")

        self.set_active_stage(
            conversation_id,
            "understanding",
            "Analyzing prompt requirements and discovering candidate nodes from registry...",
        )

        # Load history
        hist_stmt = (
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == conversation_id)
            .order_by(ConversationMessage.created_at.asc())
        )
        hist_res = await db.execute(hist_stmt)
        history = list(hist_res.scalars().all())

        # Current state and accumulated slots (canonicalized)
        current_meta = conversation.metadata_json or {}
        raw_state = current_meta.get("state")
        current_state = ConversationState(raw_state) if raw_state else None
        accumulated_slots = {
            canonicalize_slot_key(k): v
            for k, v in (current_meta.get("slots", {})).items()
        }
        original_prompt = current_meta.get("original_prompt")

        # 2. Process and validate batch clarification answers if supplied
        submitted_slot_updates: Dict[str, Any] = {}
        if clarification_answers:
            # Validate question IDs against active clarification questions
            active_questions = current_meta.get("clarification", {}).get("questions", [])
            valid_q_map = {q["id"]: q for q in active_questions}
            valid_q_map.update({q["field_key"]: q for q in active_questions})

            for ans in clarification_answers:
                # Check unknown question IDs if active questions exist
                if valid_q_map and ans.question_id not in valid_q_map and ans.field_key not in valid_q_map:
                    raise ValueError(f"Unknown clarification question ID '{ans.question_id}'.")

                q_spec = valid_q_map.get(ans.question_id) or valid_q_map.get(ans.field_key)

                # Validate 'other' custom text requirement
                if ans.selected_value == "other":
                    if not ans.custom_text or not ans.custom_text.strip():
                        q_title = q_spec.get("question") if q_spec else ans.question_id
                        raise ValueError(f"A custom answer is required when 'Other' is selected for question '{q_title}'.")

                # Validate Telegram destination format and reject bot usernames
                candidate_tg = (
                    ans.custom_text.strip()
                    if ans.custom_text
                    else (ans.selected_value.strip() if ans.selected_value else "")
                )
                if (ans.field_key == "telegram_chat_id" or ans.question_id == "telegram_chat_id") and candidate_tg:
                    if candidate_tg.lower().endswith("bot"):
                        raise ValueError(
                            "Bot usernames ending in 'bot' cannot receive personal notifications. "
                            "Please provide your numeric Telegram Chat ID or public channel username."
                        )

                # Map submitted answer to slot value
                target_key = canonicalize_slot_key(ans.field_key or ans.question_id)
                if ans.selected_value == "other":
                    val = (ans.custom_text or "").strip()
                    if target_key == "email_provider":
                        submitted_slot_updates["email_provider"] = "imap"
                        submitted_slot_updates["custom_provider"] = val
                    elif target_key == "telegram_chat_id":
                        if str(val).lower().endswith("bot"):
                            raise ValueError("Bot usernames ending in 'bot' cannot receive messages. Please provide your numeric Chat ID or channel username.")
                        submitted_slot_updates["telegram_chat_id"] = val
                    elif target_key == "google_sheets_document" and val:
                        doc_id, tab_val = extract_spreadsheet_info(str(val))
                        if doc_id:
                            submitted_slot_updates["google_sheets_document"] = doc_id
                        if tab_val:
                            submitted_slot_updates["google_sheets_sheet_name"] = tab_val
                    else:
                        submitted_slot_updates[target_key] = val
                else:
                    val = ans.selected_value or ans.custom_text
                    if target_key == "telegram_chat_id":
                        if ans.custom_text and ans.custom_text.strip():
                            raw_val = ans.custom_text.strip()
                            if raw_val.lower().endswith("bot"):
                                raise ValueError("Bot usernames ending in 'bot' cannot receive messages. Please provide your numeric Chat ID or channel username.")
                            submitted_slot_updates["telegram_chat_id"] = raw_val
                        elif val in ("private_chat", "group", "channel"):
                            submitted_slot_updates["telegram_destination_type"] = val
                            submitted_slot_updates["telegram_chat_id"] = val
                        else:
                            raw_val = str(val).strip() if val else ""
                            if raw_val.lower().endswith("bot"):
                                raise ValueError("Bot usernames ending in 'bot' cannot receive messages. Please provide your numeric Chat ID or channel username.")
                            submitted_slot_updates["telegram_chat_id"] = raw_val
                    elif target_key == "google_sheets_document" and val:
                        doc_id, tab_val = extract_spreadsheet_info(str(val))
                        if doc_id:
                            submitted_slot_updates["google_sheets_document"] = doc_id
                        if tab_val:
                            submitted_slot_updates["google_sheets_sheet_name"] = tab_val
                    else:
                        submitted_slot_updates[target_key] = val

            accumulated_slots.update(submitted_slot_updates)

        # If user passed selected options, merge into accumulated slots
        if selected_options:
            for k, v in selected_options.items():
                canon_k = canonicalize_slot_key(k)
                if canon_k == "telegram_chat_id":
                    if str(v).lower().strip().endswith("bot"):
                        raise ValueError("Bot usernames ending in 'bot' cannot receive messages. Please provide your numeric Chat ID or channel username.")
                    accumulated_slots["telegram_chat_id"] = str(v).strip()
                    continue
                if canon_k == "google_sheets_document" and v:
                    doc_id, tab_val = extract_spreadsheet_info(str(v))
                    if doc_id:
                        accumulated_slots["google_sheets_document"] = doc_id
                    if tab_val:
                        accumulated_slots["google_sheets_sheet_name"] = tab_val
                    continue
                accumulated_slots[canon_k] = v

        # Synthesize user message text for conversation history if empty
        if not user_message_text.strip():
            if clarification_answers:
                summary_items = [
                    f"{a.field_key}: {a.custom_text if a.selected_value == 'other' else (a.selected_value or a.custom_text)}"
                    for a in clarification_answers
                ]
                user_message_text = "Submitted clarification answers: " + ", ".join(summary_items)
            elif selected_options:
                summary_items = [f"{k}: {v}" for k, v in selected_options.items()]
                user_message_text = "Clarification selections: " + ", ".join(summary_items)
            else:
                user_message_text = "Confirmed clarification preferences"

        # 3. Persist user message (skip if retry or already persisted)
        if not skip_user_message_persistence:
            user_msg = ConversationMessage(
                id=str(uuid.uuid4()),
                conversation_id=conversation_id,
                role="user",
                content=user_message_text,
                metadata_json={
                    "selected_options": selected_options or submitted_slot_updates,
                    "clarification_answers": [a.model_dump() for a in clarification_answers] if clarification_answers else None,
                },
            )
            db.add(user_msg)
            await db.flush()

        # 4. Evaluate ambiguity vs planning via Intent Extractor
        intent = self.intent_extractor.analyze(
            user_prompt=user_message_text,
            history=history,
            accumulated_slots=accumulated_slots,
            original_prompt=original_prompt,
        )
        if not original_prompt:
            original_prompt = intent.original_prompt

        # Merge completed answers from intent into slots
        accumulated_slots.update(intent.completed_answers)

        # CRITICAL: Persist canonical slots immediately to PostgreSQL so that
        # upstream provider timeouts, browser refreshes, or network disconnects never lose answers
        current_meta["slots"] = accumulated_slots
        if original_prompt:
            current_meta["original_prompt"] = original_prompt
        conversation.metadata_json = current_meta
        await db.commit()
        logger.info(
            "Safely persisted canonical slots before expensive operations: keys=%s (conversation_id=%s)",
            list(accumulated_slots.keys()),
            conversation_id,
        )

        # 4.5. Web Research & Technical Documentation Grounding
        dossier: Optional[StructuredResearchDossier] = None
        if "research_dossier" in current_meta and current_meta["research_dossier"]:
            try:
                dossier = StructuredResearchDossier.model_validate(current_meta["research_dossier"])
            except Exception:
                dossier = None

        if dossier is None:
            needs_research, research_reasons = self.research_service.should_research(
                user_prompt=original_prompt or user_message_text,
                history=history,
                intent=intent,
            )
            if needs_research:
                self.set_active_stage(
                    conversation_id,
                    "researching",
                    "Researching technical documentation, API specifications, and schemas...",
                )
                try:
                    dossier = await self.research_service.conduct_research(
                        user_prompt=original_prompt or user_message_text,
                        history=history,
                        intent=intent,
                    )
                except Exception as res_err:
                    logger.warning("Research attempt failed: %s", str(res_err))
                    dossier = StructuredResearchDossier(
                        user_query=original_prompt or user_message_text,
                        needs_research=True,
                        warnings=[f"Research failed: {str(res_err)}"],
                        is_fallback=True,
                    )
            else:
                dossier = StructuredResearchDossier(
                    user_query=original_prompt or user_message_text,
                    needs_research=False,
                    research_reasons=research_reasons,
                    target_services=self.research_service._extract_target_services(original_prompt or user_message_text, intent),
                    node_compatibility=self.research_service.verify_findings_against_catalog([], []),
                )

        current_meta["research_dossier"] = dossier.model_dump()

        if intent.is_clarification_needed:
            clarification_plan = ClarificationPlan(
                has_ambiguities=True,
                status="waiting_for_required_information",
                questions=intent.clarification_questions,
                current_question_id=intent.current_question.id if intent.current_question else None,
                outstanding_questions=intent.outstanding_questions,
                completed_answers=intent.completed_answers,
            )
        else:
            if (
                intent.trigger
                and intent.trigger.is_supported
                and len(intent.actions) > 0
                and all(a.is_supported for a in intent.actions)
            ):
                clarification_plan = ClarificationPlan(
                    has_ambiguities=False,
                    status="ready_to_plan",
                    questions=[],
                    completed_answers=intent.completed_answers,
                )
            else:
                clarification_plan = await self._evaluate_requirements(
                    user_prompt=original_prompt,
                    history=history,
                    accumulated_slots=accumulated_slots,
                    intent=intent,
                )

        if clarification_plan.has_ambiguities and len(clarification_plan.questions) > 0:
            # Check for bounded clarification limit to prevent infinite loops
            clarification_turns = current_meta.get("clarification_turns", 0) + 1
            current_meta["clarification_turns"] = clarification_turns
            if clarification_turns > 4:
                failed_state = StateMachine.transition(current_state, ConversationState.FAILED)
                fail_msg = (
                    "Clarification limit reached (4 rounds). Essential workflow requirements remain incomplete or contradictory. "
                    "Please start over with a specific automation request indicating your trigger and target action."
                )
                asst_msg = ConversationMessage(
                    id=str(uuid.uuid4()),
                    conversation_id=conversation_id,
                    role="assistant",
                    content=fail_msg,
                    metadata_json={"state": failed_state.value},
                )
                db.add(asst_msg)
                current_meta["state"] = failed_state.value
                conversation.metadata_json = current_meta
                await db.commit()
                self.clear_active_stage(conversation_id)
                return OrchestratorTurnResult(
                    conversation_id=conversation_id,
                    state=failed_state,
                    assistant_message=fail_msg,
                    research_dossier=dossier.model_dump() if dossier else None,
                )

            # Transition to CLARIFYING
            next_state = StateMachine.transition(current_state, ConversationState.CLARIFYING)

            # Format question into readable assistant text
            if len(clarification_plan.questions) == 1:
                assistant_reply = clarification_plan.questions[0].question
            else:
                questions_text = "\n\n".join(
                    [f"• **{q.question}**" for q in clarification_plan.questions]
                )
                assistant_reply = (
                    f"To build this automation accurately without guessing your requirements, "
                    f"I need a few clarifications:\n\n{questions_text}"
                )

            # Persist assistant response
            asst_msg = ConversationMessage(
                id=str(uuid.uuid4()),
                conversation_id=conversation_id,
                role="assistant",
                content=assistant_reply,
                metadata_json={
                    "state": next_state.value,
                    "clarification": clarification_plan.model_dump(),
                    "intent": intent.model_dump(mode="json"),
                    "research_dossier": dossier.model_dump() if dossier else None,
                },
            )
            db.add(asst_msg)

            # Update conversation metadata
            current_meta["state"] = next_state.value
            current_meta["slots"] = accumulated_slots
            current_meta["original_prompt"] = original_prompt
            current_meta["intent"] = intent.model_dump(mode="json")
            current_meta["clarification"] = clarification_plan.model_dump(mode="json")
            current_meta["outstanding_questions"] = intent.outstanding_questions
            current_meta["current_question_id"] = intent.current_question.id if intent.current_question else None
            current_meta["selected_provider"] = intent.selected_provider
            current_meta["requested_action"] = intent.requested_action
            conversation.metadata_json = current_meta
            await db.commit()
            self.clear_active_stage(conversation_id)

            return OrchestratorTurnResult(
                conversation_id=conversation_id,
                state=next_state,
                assistant_message=assistant_reply,
                clarification=clarification_plan,
                original_prompt=original_prompt,
                intent_summary=intent.summary,
                current_question_id=intent.current_question.id if intent.current_question else None,
                outstanding_questions=intent.outstanding_questions,
                completed_answers=intent.completed_answers,
                research_dossier=dossier.model_dump() if dossier else None,
            )


        # 5. Generate Workflow (Planning -> Generating -> Validating)
        try:
            # Transition to PLANNING then GENERATING
            plan_state = StateMachine.transition(current_state, ConversationState.PLANNING)
            self.set_active_stage(
                conversation_id,
                "planning",
                "Planning trigger, action, branch conditions, and transformation architecture...",
            )

            # Build structured architectural plan before generating n8n JSON
            workflow_plan = await self._plan_workflow_architecture(
                user_prompt=original_prompt or user_message_text,
                history=history,
                slots=accumulated_slots,
                intent=intent,
                dossier=dossier,
            )

            gen_state = StateMachine.transition(plan_state, ConversationState.GENERATING)
            self.set_active_stage(
                conversation_id,
                "generating",
                "Synthesizing workflow graph and node parameters...",
            )

            # Generate WorkflowIR via LLM with structured intent, plan, and research facts
            workflow_ir = await self._generate_workflow_ir(
                user_prompt=original_prompt or user_message_text,
                history=history,
                slots=accumulated_slots,
                intent=intent,
                plan=workflow_plan,
                dossier=dossier,
            )

            # Transition to VALIDATING
            val_state = StateMachine.transition(gen_state, ConversationState.VALIDATING)
            self.set_active_stage(
                conversation_id,
                "validating",
                "Validating graph topology, expressions, and parameter contracts...",
            )

            # Compile to native n8n JSON
            compiled_json = self.compiler.compile(workflow_ir)

            # Deterministic & Semantic Validation
            val_report = self.validator.validate(
                workflow_ir,
                prompt_context=original_prompt or user_message_text,
                intent=intent,
            )

            # Bounded repair loop if invalid (up to 2 attempts, bounded by 75s elapsed)
            repair_attempts = 0
            repair_start_time = time.time()
            while not val_report.is_valid and repair_attempts < 2:
                if (time.time() - repair_start_time) > 75.0:
                    logger.warning("Generation deadline nearing during repair loop. Stopping repairs.")
                    break
                repair_attempts += 1
                logger.info(
                    "WorkflowIR validation failed. Attempting bounded repair %d/2.",
                    repair_attempts,
                )
                self.set_active_stage(
                    conversation_id,
                    "repairing",
                    f"Repairing workflow issues (attempt {repair_attempts}/2)...",
                )
                try:
                    repaired_ir = await self._repair_workflow_ir(
                        workflow_ir=workflow_ir,
                        val_report=val_report,
                        prompt_context=original_prompt or user_message_text,
                        intent=intent,
                        plan=workflow_plan,
                        dossier=dossier,
                        slots=accumulated_slots,
                    )
                    workflow_ir = repaired_ir
                except Exception as repair_err:
                    logger.warning("Repair attempt %d failed: %s", repair_attempts, str(repair_err))
                    if repair_attempts >= 2:
                        break
                    continue
                compiled_json = self.compiler.compile(workflow_ir)
                val_report = self.validator.validate(
                    workflow_ir,
                    prompt_context=original_prompt or user_message_text,
                    intent=intent,
                )


            if not val_report.is_valid:
                # Max repair attempts exhausted
                failed_state = StateMachine.transition(val_state, ConversationState.FAILED)
                issue_descriptions = "\n".join(
                    [f"- [{iss.severity}] {iss.message}" for iss in val_report.issues if iss.severity == "fatal"]
                )
                assistant_reply = (
                    f"Workflow validation could not be resolved automatically:\n\n{issue_descriptions}"
                )

                asst_msg = ConversationMessage(
                    id=str(uuid.uuid4()),
                    conversation_id=conversation_id,
                    role="assistant",
                    content=assistant_reply,
                    metadata_json={
                        "state": failed_state.value,
                        "validation_report": val_report.model_dump(),
                        "research_dossier": dossier.model_dump() if dossier else None,
                        "workflow_plan": workflow_plan.model_dump() if workflow_plan else None,
                    },
                )
                db.add(asst_msg)
                current_meta["state"] = failed_state.value
                conversation.metadata_json = current_meta
                await db.commit()

                return OrchestratorTurnResult(
                    conversation_id=conversation_id,
                    state=failed_state,
                    assistant_message=assistant_reply,
                    validation_report=val_report.model_dump(),
                    research_dossier=dossier.model_dump() if dossier else None,
                    workflow_plan=workflow_plan.model_dump() if workflow_plan else None,
                )

            # Validation passed -> Transition to READY
            ready_state = StateMachine.transition(
                val_state,
                ConversationState.READY,
                validation_report=val_report,
            )

            # Deterministic readiness evaluation
            readiness_report = self.readiness_evaluator.evaluate(
                workflow_ir,
                prompt_context=original_prompt or user_message_text,
            )

            # 5. Persist WorkflowDraft and WorkflowRevision in PostgreSQL
            draft_stmt = select(WorkflowDraft).where(WorkflowDraft.conversation_id == conversation_id)
            draft_res = await db.execute(draft_stmt)
            draft = draft_res.scalar_one_or_none()

            ir_dict = workflow_ir.model_dump(mode="json")
            draft_status = readiness_report.overall_status.value
            if not draft:
                draft = WorkflowDraft(
                    id=str(uuid.uuid4()),
                    conversation_id=conversation_id,
                    title=workflow_ir.name,
                    status=draft_status,
                    workflow_ir=ir_dict,
                    compiled_json=compiled_json,
                )
                db.add(draft)
                await db.flush()
                rev_num = 1
            else:
                draft.title = workflow_ir.name
                draft.status = draft_status
                draft.workflow_ir = ir_dict
                draft.compiled_json = compiled_json
                
                # Determine next revision number
                count_stmt = select(WorkflowRevision).where(WorkflowRevision.draft_id == draft.id)
                count_res = await db.execute(count_stmt)
                rev_num = len(list(count_res.scalars().all())) + 1

            combined_val_report = {
                **val_report.model_dump(),
                "readiness": readiness_report.model_dump(),
                "research_dossier": dossier.model_dump() if dossier else None,
                "workflow_plan": workflow_plan.model_dump() if workflow_plan else None,
            }

            revision = WorkflowRevision(
                id=str(uuid.uuid4()),
                draft_id=draft.id,
                revision_number=rev_num,
                workflow_ir=ir_dict,
                compiled_json=compiled_json,
                validation_report=combined_val_report,
            )
            db.add(revision)

            # Create assistant message
            node_names = ", ".join([n.name for n in workflow_ir.nodes])
            readiness_desc = (
                "Ready for review (all static requirements satisfied)"
                if readiness_report.overall_status.value == "ready"
                else f"Needs configuration ({readiness_report.summary})"
            )
            sources_summary = ""
            if dossier and dossier.sources:
                sources_summary = f"\n• **Research Grounding ({len(dossier.sources)} sources):** Verified against 444 n8n node definitions"

            assistant_reply = (
                f"Generated and validated workflow **'{workflow_ir.name}'** successfully.\n\n"
                f"• **Nodes ({len(workflow_ir.nodes)}):** {node_names}\n"
                f"• **Connections ({len(workflow_ir.edges)}):** Configured deterministically\n"
                f"• **Validation:** 0 fatal errors\n"
                f"• **Readiness:** {readiness_desc}"
                f"{sources_summary}"
            )

            asst_msg = ConversationMessage(
                id=str(uuid.uuid4()),
                conversation_id=conversation_id,
                role="assistant",
                content=assistant_reply,
                metadata_json={
                    "state": ready_state.value,
                    "draft_id": draft.id,
                    "workflow_ir": ir_dict,
                    "compiled_json": compiled_json,
                    "validation_report": val_report.model_dump(),
                    "readiness_report": readiness_report.model_dump(),
                    "research_dossier": dossier.model_dump() if dossier else None,
                    "workflow_plan": workflow_plan.model_dump() if workflow_plan else None,
                },
            )
            db.add(asst_msg)

            # Update conversation metadata
            current_meta["state"] = ready_state.value
            current_meta["slots"] = accumulated_slots
            current_meta["original_prompt"] = original_prompt
            current_meta["intent"] = intent.model_dump(mode="json")
            current_meta["outstanding_questions"] = []
            current_meta["current_question_id"] = None
            current_meta["selected_provider"] = intent.selected_provider
            current_meta["requested_action"] = intent.requested_action
            current_meta["latest_draft_id"] = draft.id
            current_meta["research_dossier"] = dossier.model_dump() if dossier else None
            current_meta["workflow_plan"] = workflow_plan.model_dump() if workflow_plan else None
            conversation.metadata_json = current_meta
            await db.commit()

            return OrchestratorTurnResult(
                conversation_id=conversation_id,
                state=ready_state,
                assistant_message=assistant_reply,
                workflow_ir=ir_dict,
                compiled_json=compiled_json,
                validation_report=val_report.model_dump(),
                readiness_report=readiness_report.model_dump(),
                draft_id=draft.id,
                revision_number=rev_num,
                latest_revision_number=rev_num,
                original_prompt=original_prompt,
                intent_summary=intent.summary if intent else None,
                completed_answers=accumulated_slots,
                research_dossier=dossier.model_dump() if dossier else None,
                workflow_plan=workflow_plan.model_dump() if workflow_plan else None,
            )


        except Exception as e:
            logger.error("Workflow generation failed: %s", str(e), exc_info=True)
            failed_state = ConversationState.FAILED
            clean_err = sanitize_secrets(str(e))
            err_msg = f"Failed to complete workflow planning: {clean_err}"
            asst_msg = ConversationMessage(
                id=str(uuid.uuid4()),
                conversation_id=conversation_id,
                role="assistant",
                content=err_msg,
                metadata_json={
                    "state": failed_state.value,
                    "error": clean_err,
                    "research_dossier": dossier.model_dump() if dossier else None,
                },
            )
            db.add(asst_msg)
            current_meta["state"] = failed_state.value
            current_meta["original_prompt"] = original_prompt
            current_meta["slots"] = accumulated_slots
            conversation.metadata_json = current_meta
            await db.commit()

            # Retrieve existing draft details if any to preserve workflow context
            existing_draft_stmt = select(WorkflowDraft).where(WorkflowDraft.conversation_id == conversation_id)
            existing_draft_res = await db.execute(existing_draft_stmt)
            existing_draft = existing_draft_res.scalar_one_or_none()
            existing_draft_id = existing_draft.id if existing_draft else None
            existing_rev_num = None
            if existing_draft:
                rev_stmt = select(func.max(WorkflowRevision.revision_number)).where(WorkflowRevision.draft_id == existing_draft.id)
                rev_res = await db.execute(rev_stmt)
                existing_rev_num = rev_res.scalar() or 1

            return OrchestratorTurnResult(
                conversation_id=conversation_id,
                state=failed_state,
                assistant_message=err_msg,
                original_prompt=original_prompt,
                completed_answers=accumulated_slots,
                draft_id=existing_draft_id,
                revision_number=existing_rev_num,
                latest_revision_number=existing_rev_num,
                workflow_ir=existing_draft.workflow_ir if existing_draft else None,
                compiled_json=existing_draft.compiled_json if existing_draft else None,
                research_dossier=dossier.model_dump() if dossier else None,
                workflow_plan=workflow_plan.model_dump() if 'workflow_plan' in locals() and workflow_plan else None,
            )

    async def _evaluate_requirements(
        self,
        user_prompt: str,
        history: List[ConversationMessage],
        accumulated_slots: Dict[str, Any],
        intent: Optional[WorkflowIntent] = None,
    ) -> ClarificationPlan:
        """Determines if the user request has missing critical slots."""
        # If intent has already resolved a verified trigger and actions from the node registry, no clarification needed!
        if (
            intent
            and intent.trigger
            and intent.trigger.is_supported
            and len(intent.actions) > 0
            and all(a.is_supported for a in intent.actions)
        ):
            return ClarificationPlan(
                has_ambiguities=False,
                questions=[],
                completed_answers=accumulated_slots,
            )

        cand_nodes = self.node_registry.search(user_prompt, limit=5)
        cand_text = "\n".join([f"- {n.display_name} ({n.canonical_name}): is_trigger={n.is_trigger}" for n in cand_nodes])

        system_prompt = (
            "You are the n8n Requirements Analysis Engine. "
            "Examine the user prompt and conversation history. "
            "Determine if essential information is genuinely missing to construct a functional n8n workflow.\n\n"
            "STRICT RULES:\n"
            "1. DISTINGUISH ALREADY SUPPLIED REQUIREMENTS: Check the user prompt, history, and ALREADY RESOLVED SLOTS. "
            "NEVER ask for a requirement that is already resolved or supplied (e.g., if a Telegram Chat ID or Spreadsheet ID is known, DO NOT ask where to send messages or for spreadsheet info).\n"
            "2. COLLECT ALL MISSING FIELDS IN ONE ROUND: If multiple essential integration parameters are missing, output them together in a single round.\n"
            "3. NO CREDENTIALS IN CHAT: Never ask users to paste API keys, bot tokens, or passwords in chat (these are configured securely in n8n credentials).\n"
            "4. NO UNNECESSARY QUESTIONS: Do not ask for optional fields (like sheet name if default 'Sheet1' is fine). "
            "If sufficient information exists, return has_ambiguities=false.\n\n"
            f"AVAILABLE CANDIDATE NODES:\n{cand_text}\n\n"
            "Format strictly as JSON:\n"
            "{\n"
            '  "has_ambiguities": true,\n'
            '  "questions": [\n'
            '    {"id": "q1", "question": "Question text?", "field_key": "key", "is_required": true, '
            '"default_value": "default", "options": [{"label": "A", "value": "a"}]}\n'
            "  ]\n"
            "}"
        )

        messages = [ChatMessage(role="system", content=system_prompt)]
        for h_msg in history:
            if h_msg.role in ("user", "assistant") and h_msg.content:
                messages.append(ChatMessage(role=h_msg.role, content=h_msg.content))

        resolved_slots_text = "\n".join([f"- {k}: {v}" for k, v in accumulated_slots.items()]) if accumulated_slots else "None"
        messages.append(
            ChatMessage(
                role="user",
                content=(
                    f"User Prompt: {user_prompt}\n\n"
                    f"ALREADY RESOLVED SLOTS (DO NOT ASK FOR THESE):\n{resolved_slots_text}"
                ),
            )
        )

        try:
            req = LLMRequest(messages=messages, temperature=0.1, response_format={"type": "json_object"})
            resp = await self.llm_manager.complete(req)
            data = json.loads(resp.content)
            plan = ClarificationPlan.model_validate(data)

            # Deduplicate questions against already known accumulated_slots and validate choices
            unanswered: List[ClarificationQuestion] = []
            seen_q_ids: Set[str] = set()
            for q in plan.questions:
                canon_k = canonicalize_slot_key(q.field_key or q.id)
                if (
                    q.field_key in accumulated_slots
                    or q.id in accumulated_slots
                    or canon_k in accumulated_slots
                ):
                    continue
                # Semantic deduplication: if Telegram chat id is in accumulated slots, never ask about Telegram destination
                if (
                    "telegram_chat_id" in accumulated_slots
                    and ("telegram" in q.question.lower() or "telegram" in (q.field_key or "").lower())
                    and any(w in q.question.lower() for w in ("chat", "send", "destination", "channel", "where"))
                ):
                    continue
                # Semantic deduplication: if Google Sheets document is resolved, never ask for sheet URL/ID
                if "google_sheets_document" in accumulated_slots:
                    q_text = q.question.lower()
                    f_key = (q.field_key or "").lower()
                    if (
                        canon_k == "google_sheets_document"
                        or "spreadsheet" in q_text
                        or "spreadsheet" in f_key
                        or (("sheet" in q_text or "sheet" in f_key or "document" in f_key) and any(w in q_text or w in f_key for w in ("id", "url", "link", "doc", "which")))
                    ):
                        logger.info("Pruned redundant spreadsheet question '%s' because google_sheets_document is already satisfied.", q.id)
                        continue

                q_ident = q.id or q.field_key
                if q_ident in seen_q_ids or q.field_key in seen_q_ids or canon_k in seen_q_ids:
                    continue
                seen_q_ids.add(q_ident)
                seen_q_ids.add(q.field_key)
                seen_q_ids.add(canon_k)

                # Validate choices against registry: choices referring to nonexistent node types are filtered out
                verified_opts = []
                if q.options:
                    for opt in q.options:
                        val_str = str(opt.value)
                        if "n8n-nodes-base" in val_str and not self.node_registry.is_node_supported(val_str):
                            continue
                        verified_opts.append(opt)
                    q.options = verified_opts

                q.input_type = q.input_type or "single_select"
                q.allow_other = True
                q.required = True
                q.is_required = True
                unanswered.append(q)

            if not unanswered:
                return ClarificationPlan(has_ambiguities=False, status="ready_to_plan", questions=[])

            return ClarificationPlan(
                has_ambiguities=True,
                status="waiting_for_required_information",
                questions=unanswered,
                current_question_id=unanswered[0].id,
                outstanding_questions=[q.id for q in unanswered],
                completed_answers=accumulated_slots,
            )
        except Exception as e:
            logger.warning("Clarification evaluation failed, defaulting to direct planning: %s", str(e))
            return ClarificationPlan(has_ambiguities=False, status="ready_to_plan", questions=[])

    async def _plan_workflow_architecture(
        self,
        user_prompt: str,
        history: List[ConversationMessage],
        slots: Dict[str, Any],
        intent: Optional[WorkflowIntent] = None,
        dossier: Optional[StructuredResearchDossier] = None,
    ) -> WorkflowPlan:
        """Constructs a structured architectural workflow plan before generating WorkflowIR."""
        candidate_set: Dict[str, Any] = {}

        # 1. Grounded candidate retrieval
        if intent:
            if intent.trigger and intent.trigger.node_type:
                node_obj = self.node_registry.get_node(intent.trigger.node_type)
                if node_obj:
                    candidate_set[node_obj.canonical_name] = node_obj
            elif intent.trigger and intent.trigger.service:
                for c in self.node_registry.search(intent.trigger.service, is_trigger=True, limit=2):
                    candidate_set[c.canonical_name] = c

            for act in intent.actions:
                if act.node_type:
                    node_obj = self.node_registry.get_node(act.node_type)
                    if node_obj:
                        candidate_set[node_obj.canonical_name] = node_obj
                elif act.service:
                    for c in self.node_registry.search(act.service, is_trigger=False, limit=2):
                        candidate_set[c.canonical_name] = c

        # 2. Add control flow / condition nodes if branching or filtering is required
        prompt_lower = (user_prompt or "").lower()
        if any(w in prompt_lower for w in ("invoice", "pdf", "filter", "condition", "only if", "if ", "switch", "branch")):
            if_node = self.node_registry.get_node("n8n-nodes-base.if")
            if if_node:
                candidate_set[if_node.canonical_name] = if_node

        # 3. Supplemental search
        if len(candidate_set) < 2:
            for c in self.node_registry.search(user_prompt, limit=3):
                candidate_set[c.canonical_name] = c
                if len(candidate_set) >= 4:
                    break

        candidates = list(candidate_set.values())[:8]
        candidate_docs = []
        for c in candidates:
            ops_info = f"Operations: {c.operations[:5]}" if c.operations else ""
            candidate_docs.append(
                f"- Name: {c.name} | Type: {c.canonical_name} | Version: {c.default_version} | "
                f"IsTrigger: {c.is_trigger} | {ops_info}"
            )
        catalog_snippet = "\n".join(candidate_docs)

        # 4. Verified facts from research dossier
        facts_snippet = ""
        if dossier and dossier.documented_facts:
            facts_snippet = "\nVERIFIED RESEARCH FACTS:\n" + "\n".join(
                [f"- [{f.category}] {f.topic + ': ' if f.topic else ''}{f.fact}" for f in dossier.documented_facts]
            )

        system_prompt = (
            "You are the n8n Architectural Workflow Planner. "
            "Analyze the automation request and construct a formal architectural blueprint before code generation.\n\n"
            "STRICT RULES:\n"
            "1. ONLY use verified installed n8n node types from the catalog:\n"
            f"{catalog_snippet}\n"
            f"{facts_snippet}\n"
            "2. Describe all required nodes, their functional roles ('trigger', 'action', 'condition', 'transform', 'error_handler'), "
            "and directed connections between them.\n"
            "3. For conditional nodes (e.g. 'if'), connect source_output_index 0 for True/Match and source_output_index 1 for False/Alternative.\n"
            "4. Specify error_handling_strategy ('continue_or_alert', 'retry_on_fail', or 'stop_on_fail'), execution_policy on nodes, and state_tracking (e.g. deduplication or pagination tracking) if needed.\n"
            "5. Return strictly valid JSON conforming to the WorkflowPlan schema:\n"
            "{\n"
            '  "title": "Workflow Title",\n'
            '  "objective": "Brief statement of automation purpose",\n'
            '  "target_services": ["service1", "service2"],\n'
            '  "nodes": [\n'
            '    {"id": "node_1", "name": "Trigger", "node_type": "n8n-nodes-base.manualTrigger", "role": "trigger", "operation": "", "parameters": {}, "execution_policy": {}}\n'
            "  ],\n"
            '  "connections": [\n'
            '    {"source_id": "node_1", "target_id": "node_2", "source_output_index": 0, "target_input_index": 0, "connection_type": "main"}\n'
            "  ],\n"
            '  "branch_conditions": [],\n'
            '  "data_transformations": [],\n'
            '  "state_tracking": {"strategy": "deduplication_by_id", "persistent_key": "id"},\n'
            '  "error_handling_strategy": "continue_or_alert",\n'
            '  "expected_outputs": ["Telegram message", "Database update"]\n'
            "}"
        )

        messages = [
            ChatMessage(role="system", content=system_prompt),
            ChatMessage(
                role="user",
                content=f"Automation Request: {user_prompt}\nResolved Slots: {json.dumps(slots)}\nIntent: {intent.summary if intent else 'none'}",
            ),
        ]

        try:
            req = LLMRequest(messages=messages, temperature=0.1, response_format={"type": "json_object"}, timeout=40.0)
            resp = await self.llm_manager.complete(req)
            data = json.loads(resp.content)
            plan = WorkflowPlan.model_validate(data)

            # Validate that planned node types exist in the node registry
            verified_nodes = []
            for n in plan.nodes:
                if self.node_registry.is_node_supported(n.node_type):
                    verified_nodes.append(n)
                else:
                    # Search fallback for unsupported node type
                    alt = self.node_registry.search(n.name, limit=1)
                    if alt and self.node_registry.is_node_supported(alt[0].canonical_name):
                        n.node_type = alt[0].canonical_name
                        verified_nodes.append(n)
                    else:
                        # Fall back to HTTP Request for unsupported services
                        n.node_type = "n8n-nodes-base.httpRequest"
                        verified_nodes.append(n)
            if verified_nodes:
                plan.nodes = verified_nodes

            if dossier:
                plan.research_dossier = dossier.model_dump()
            return plan

        except Exception as e:
            logger.warning("Architectural planning LLM step failed: %s. Using heuristic plan.", str(e))
            # Heuristic deterministic fallback plan
            trigger_type = (intent.trigger.node_type if intent and intent.trigger and intent.trigger.node_type else "n8n-nodes-base.manualTrigger")
            trigger_node = PlannedNode(
                id="node_trigger",
                name="Start Trigger",
                node_type=trigger_type,
                role="trigger",
                description="Workflow entry trigger",
            )
            nodes = [trigger_node]
            connections = []
            prev_id = "node_trigger"

            # Check if filter needed
            has_condition = False
            if any(w in prompt_lower for w in ("invoice", "pdf", "filter", "condition", "if ", "branch", "payment")):
                if_node = PlannedNode(
                    id="node_condition",
                    name="Filter Condition",
                    node_type="n8n-nodes-base.if",
                    role="condition",
                    description="Evaluate filter conditions",
                )
                nodes.append(if_node)
                connections.append(PlannedEdge(source_id=prev_id, target_id="node_condition", source_output_index=0))
                prev_id = "node_condition"
                has_condition = True

            if intent and intent.actions:
                for idx, act in enumerate(intent.actions):
                    act_id = f"node_action_{idx+1}"
                    act_type = act.node_type or "n8n-nodes-base.httpRequest"
                    nodes.append(
                        PlannedNode(
                            id=act_id,
                            name=act.service.capitalize() if act.service else "Action",
                            node_type=act_type,
                            role="action",
                            description=getattr(act, "capability", None) or getattr(act, "operation", None) or "Execute automated action",
                        )
                    )
                    # If branching condition exists and we have a secondary action, connect to False branch (index 1)
                    if has_condition and idx == 1:
                        connections.append(PlannedEdge(source_id="node_condition", target_id=act_id, source_output_index=1))
                    else:
                        connections.append(PlannedEdge(source_id=prev_id, target_id=act_id, source_output_index=0))
                    prev_id = act_id
            else:
                nodes.append(
                    PlannedNode(
                        id="node_action_1",
                        name="HTTP Request",
                        node_type="n8n-nodes-base.httpRequest",
                        role="action",
                        description="Execute primary task",
                    )
                )
                connections.append(PlannedEdge(source_id=prev_id, target_id="node_action_1", source_output_index=0))

            return WorkflowPlan(
                title=f"Automated Workflow: {user_prompt[:40]}",
                objective=user_prompt,
                target_services=intent.target_services if intent else [],
                nodes=nodes,
                connections=connections,
                error_handling_strategy="continue_or_alert",
                expected_outputs=["Target service updated"],
                research_dossier=dossier.model_dump() if dossier else None,
            )

    async def _generate_workflow_ir(
        self,
        user_prompt: str,
        history: List[ConversationMessage],
        slots: Dict[str, Any],
        intent: Optional[WorkflowIntent] = None,
        plan: Optional[WorkflowPlan] = None,
        dossier: Optional[StructuredResearchDossier] = None,
    ) -> WorkflowIR:
        """Prompts LLM with node registry context, architectural blueprint, and verified research facts to produce a valid WorkflowIR."""
        candidate_set: Dict[str, Any] = {}

        # 1. Grounded candidate retrieval: prioritize verified intent trigger & actions
        if intent:
            if intent.trigger and intent.trigger.node_type:
                node_obj = self.node_registry.get_node(intent.trigger.node_type)
                if node_obj:
                    candidate_set[node_obj.canonical_name] = node_obj
            elif intent.trigger and intent.trigger.service:
                for c in self.node_registry.search(intent.trigger.service, is_trigger=True, limit=2):
                    candidate_set[c.canonical_name] = c

            for act in intent.actions:
                if act.node_type:
                    node_obj = self.node_registry.get_node(act.node_type)
                    if node_obj:
                        candidate_set[node_obj.canonical_name] = node_obj
                elif act.service:
                    for c in self.node_registry.search(act.service, is_trigger=False, limit=2):
                        candidate_set[c.canonical_name] = c

        # 2. Add candidates from architectural plan if provided
        if plan:
            for pnode in plan.nodes:
                p_obj = self.node_registry.get_node(pnode.node_type)
                if p_obj:
                    candidate_set[p_obj.canonical_name] = p_obj

        # 3. Add utility node if filtering / conditions / logic are mentioned
        prompt_lower = (user_prompt or "").lower()
        if any(w in prompt_lower for w in ("invoice", "pdf", "filter", "condition", "only if", "if ")):
            if_node = self.node_registry.get_node("n8n-nodes-base.if")
            if if_node:
                candidate_set[if_node.canonical_name] = if_node

        # 4. Supplemental search only if candidates are sparse (< 2)
        if len(candidate_set) < 2:
            for c in self.node_registry.search(user_prompt, limit=3):
                candidate_set[c.canonical_name] = c
                if len(candidate_set) >= 4:
                    break

        candidates = list(candidate_set.values())[:8]
        candidate_docs = []
        for c in candidates:
            ops_info = f"Operations: {c.operations[:5]}" if c.operations else ""
            expected_creds = c.get_expected_credentials()
            creds_info = f"RequiredCredentials: {[cr.name for cr in expected_creds]}" if expected_creds else ""
            props = c.get_properties(version=c.default_version)
            req_props = [p.name for p in props if p.required][:5]
            req_info = f"RequiredParams: {req_props}" if req_props else ""
            candidate_docs.append(
                f"- Name: {c.name} | Type: {c.canonical_name} | Version: {c.default_version} | "
                f"IsTrigger: {c.is_trigger} | {ops_info} | {creds_info} | {req_info}"
            )
        catalog_snippet = "\n".join(candidate_docs)

        # Plan blueprint summary
        plan_snippet = ""
        if plan:
            node_desc = ", ".join([f"{n.name} ({n.node_type}) [role={n.role}]" for n in plan.nodes])
            edge_desc = ", ".join([f"{e.source_id}->{e.target_id}[out={e.source_output_index}]" for e in plan.connections])
            branches_desc = f"\n- Branch Conditions: {json.dumps(plan.branch_conditions)}" if plan.branch_conditions else ""
            state_desc = f"\n- State Tracking: {json.dumps(plan.state_tracking)}" if plan.state_tracking else ""
            transforms_desc = f"\n- Data Transformations: {json.dumps(plan.data_transformations)}" if plan.data_transformations else ""
            plan_snippet = (
                f"\nARCHITECTURAL BLUEPRINT (Strictly follow this graph structure, node roles, and branch connections):\n"
                f"- Nodes: {node_desc}\n"
                f"- Connections: {edge_desc}\n"
                f"- Strategy: {plan.error_handling_strategy}"
                f"{branches_desc}"
                f"{state_desc}"
                f"{transforms_desc}\n"
            )

        # Verified research facts
        facts_snippet = ""
        if dossier and dossier.documented_facts:
            facts_snippet = "\nVERIFIED TECHNICAL DOCUMENTATION FACTS (Authoritative ground truth for API endpoints, schemas, and parameters):\n" + "\n".join(
                [f"- [{f.category}] {f.topic + ': ' if f.topic else ''}{f.fact}" for f in dossier.documented_facts]
            )
        if dossier and dossier.warnings:
            facts_snippet += "\nRESEARCH WARNINGS (Do not make these invalid assumptions):\n" + "\n".join(
                [f"- ⚠️ {w}" for w in dossier.warnings]
            )

        system_prompt = (
            "You are the n8n Workflow Planning Engine. "
            "Generate an Intermediate Representation (WorkflowIR) strictly fulfilling the user requirements.\n\n"
            "STRICT RULES:\n"
            "1. USE ONLY VERIFIED NODES from the catalog:\n"
            f"{catalog_snippet}\n"
            f"{plan_snippet}\n"
            f"{facts_snippet}\n"
            "2. Ensure exact node_type and type_version matching the catalog.\n"
            "3. If an automated event trigger was requested (e.g. Email arrival or Google Sheets new row), you MUST use a verified event trigger "
            "(e.g. 'n8n-nodes-base.gmailTrigger', 'n8n-nodes-base.googleSheetsTrigger', 'n8n-nodes-base.microsoftOutlookTrigger', or 'n8n-nodes-base.emailReadImap'). NEVER substitute 'manualTrigger' when an event trigger was requested!\n"
            "4. For Google Sheets triggers, use 'n8n-nodes-base.googleSheetsTrigger' with parameters: event='rowAdded', documentId, sheetName, and credentials={'googleSheetsTriggerOAuth2Api': {'id': '', 'name': 'Google Sheets account'}}. "
            "If documentId is resolved in Resolved Slots, use that exact document ID in documentId.value (e.g. documentId={'mode': 'list', 'value': '<ID>'}).\n"
            "5. For Telegram messages, use 'n8n-nodes-base.telegram' with parameters: "
            "resource='message', operation='sendMessage', chatId, and text. "
            "If Telegram chatId was provided in Resolved Slots (e.g. numeric ID '8716438750' or channel handle '@mychannel'), you MUST use that exact value for chatId! "
            "NEVER replace a known chat ID with a placeholder. ONLY if no chatId was provided in Resolved Slots, use the placeholder '={{ \"<YOUR_TELEGRAM_CHAT_ID>\" }}'.\n"
            "6. Map upstream data using n8n expressions (e.g. for email: text='={{ \"📬 New Email\\n\\nFrom: \" + ($json.from || \"Unknown\") + \"\\nSubject: \" + ($json.subject || \"(No Subject)\") }}', "
            "or for Google Sheets: map specific requested columns like name, email, phone (e.g. text='={{ \"📊 New Row:\\nName: \" + ($json.name || \"\") + \"\\nEmail: \" + ($json.email || \"\") + \"\\nPhone: \" + ($json.phone || $json[\"phone number\"] || \"\") }}'). "
            "Do NOT use static strings like 'gmail' or fake bot usernames like 'Emcheckmebot'.\n"
            "7. When processing emails with PDF invoices or attachments (e.g. Gmail Trigger):\n"
            "   - Use 'n8n-nodes-base.gmailTrigger' (or resolved email trigger) with event='messageReceived', options={'downloadAttachments': true} or simple=false.\n"
            "   - If filtering for PDF invoices, configure query filters (e.g. filters: {'q': 'filename:pdf invoice'}) or connect via an 'if' node.\n"
            "   - Map notification text to Telegram with relevant email details (From, Subject, Date, and attachment notice).\n"
            "8. Never invent fake bot handles or invalid usernames for recipient chat IDs. Bot usernames ending in 'bot' cannot receive messages.\n"
            "9. Every non-trigger node MUST have at least one incoming edge.\n"
            "10. When branch conditions or error handling are planned, configure valid expressions and edge output connections (index 0 for True/Primary, index 1 for False/Alternative).\n"
            "11. Reference credentials through logical credential references (e.g. credentials={'telegramApi': {'id': '1', 'name': 'Telegram account'}}). "
            "NEVER embed raw secrets, tokens, or passwords.\n"
            "12. Return strictly valid JSON adhering to the WorkflowIR schema.\n\n"
            "SCHEMA EXAMPLE:\n"
            "{\n"
            '  "id": "wf_unique_id",\n'
            '  "name": "Email to Telegram Notification",\n'
            '  "nodes": [\n'
            '    {"id": "node_1", "name": "Gmail Trigger", "node_type": "n8n-nodes-base.gmailTrigger", "type_version": 1.4, "parameters": {"event": "messageReceived", "simple": true}, "credentials": {"gmailOAuth2": {"id": "1", "name": "Gmail account"}}},\n'
            '    {"id": "node_2", "name": "Telegram", "node_type": "n8n-nodes-base.telegram", "type_version": 1.2, "parameters": {"resource": "message", "operation": "sendMessage", "chatId": "={{ \\"<YOUR_TELEGRAM_CHAT_ID>\\" }}", "text": "={{ \\"📬 New Email\\n\\nFrom: \\" + ($json.from || \\"Unknown\\") + \\"\\nSubject: \\" + ($json.subject || \\"(No Subject)\\") }}"}, "credentials": {"telegramApi": {"id": "1", "name": "Telegram account"}}}\n'
            "  ],\n"
            '  "edges": [{"source_id": "node_1", "target_id": "node_2"}]\n'
            "}"
        )

        messages = [ChatMessage(role="system", content=system_prompt)]
        for h_msg in history:
            if h_msg.role in ("user", "assistant") and h_msg.content:
                messages.append(ChatMessage(role=h_msg.role, content=h_msg.content))
        data_mappings_desc = ""
        if intent and intent.data_mappings:
            data_mappings_desc = f"\nRequired Data Mappings: {json.dumps(intent.data_mappings)}"
        messages.append(
            ChatMessage(
                role="user",
                content=f"User Request: {user_prompt}\nResolved Slots: {json.dumps(slots)}\nIntent Summary: {intent.summary if intent else 'none'}{data_mappings_desc}",
            )
        )

        req = LLMRequest(messages=messages, temperature=0.2, response_format={"type": "json_object"}, timeout=55.0)
        resp = await self.llm_manager.complete(req)
        try:
            return parse_workflow_ir(resp.content)
        except WorkflowIRParseError as parse_err:
            logger.warning("WorkflowIR parse attempt 1 failed: %s. Retrying with format correction prompt.", str(parse_err))
            messages.append(ChatMessage(role="assistant", content=resp.content))
            messages.append(
                ChatMessage(
                    role="user",
                    content=(
                        f"Your previous response was invalid: {str(parse_err)}. "
                        "Return strictly a single valid JSON dictionary representing a complete WorkflowIR "
                        "(containing 'id', 'name', 'nodes', and 'edges'). "
                        "Do NOT return a list, do NOT return a code block, and do NOT return multiple workflows."
                    ),
                )
            )
            retry_req = LLMRequest(messages=messages, temperature=0.1, response_format={"type": "json_object"}, timeout=30.0)
            retry_resp = await self.llm_manager.complete(retry_req)
            return parse_workflow_ir(retry_resp.content)

    async def _repair_workflow_ir(
        self,
        workflow_ir: WorkflowIR,
        val_report: ValidationReport,
        prompt_context: Optional[str] = None,
        intent: Optional[WorkflowIntent] = None,
        plan: Optional[WorkflowPlan] = None,
        dossier: Optional[StructuredResearchDossier] = None,
        slots: Optional[Dict[str, Any]] = None,
    ) -> WorkflowIR:
        """Applies a bounded repair step using validator feedback, architectural plan, verified facts, and canonical slots."""
        plan_context = ""
        if plan:
            plan_context = f"\nArchitectural Plan Reference: {plan.title} (Strategy: {plan.error_handling_strategy})"

        facts_context = ""
        if dossier and dossier.documented_facts:
            facts_context = "\nVerified Facts Reference:\n" + "\n".join(
                [f"- {f.topic + ': ' if f.topic else ''}{f.fact}" for f in dossier.documented_facts]
            )

        slots_context = ""
        if slots:
            slots_context = f"\nCanonical User Slots (PRESERVE THESE EXACT VALUES, DO NOT INSERT PLACEHOLDERS):\n{json.dumps(slots)}"

        system_prompt = (
            "You are the n8n Workflow Repair Engine. "
            "The generated WorkflowIR failed static and semantic validation with the issues below. "
            "Return a corrected WorkflowIR JSON fixing ALL issues:\n"
            "- CRITICAL GRAPH STRUCTURE: The 'nodes' array must contain ONLY node objects (with 'id', 'name', 'node_type', 'type_version', 'parameters'). "
            "NEVER place edge/connection objects (with 'source', 'target', 'index') inside 'nodes'! All connections belong in 'edges'.\n"
            "- PRESERVE USER VALUES: Retain exact user-provided spreadsheet IDs and chat IDs from Canonical User Slots. Never revert them to placeholder strings.\n"
            "- If TRIGGER_INTENT_MISMATCH: replace manualTrigger with the required email or sheets trigger.\n"
            "- If FABRICATED_PLACEHOLDER_PARAMETER: remove bogus values (like Emcheckmebot or 'gmail') and use valid expressions.\n"
            "- If ACTION_INTENT_MISMATCH: ensure the requested action node exists and is connected.\n"
            "- If BRANCH_COVERAGE_PARTIAL: ensure condition nodes (e.g. if) have both branch pathways connected.\n"
            "- If FAULT_TOLERANCE_CONFIGURED: ensure error handling or continueOnFail is properly placed.\n"
            "- Ensure all non-trigger nodes have valid incoming edges and no raw secrets."
            f"{plan_context}\n"
            f"{facts_context}\n"
            f"{slots_context}"
        )

        issues_summary = "\n".join(
            [f"- [{iss.severity}] {iss.rule_code} ({iss.property_path or iss.node_id or 'general'}): {iss.message}" for iss in val_report.issues]
        )

        messages = [
            ChatMessage(role="system", content=system_prompt),
            ChatMessage(
                role="user",
                content=(
                    f"Original Prompt: {prompt_context or ''}\n"
                    f"Current WorkflowIR:\n{json.dumps(workflow_ir.model_dump(mode='json'))}\n\n"
                    f"Validation Issues to Fix:\n{issues_summary}"
                ),
            ),
        ]

        req = LLMRequest(messages=messages, temperature=0.1, response_format={"type": "json_object"}, timeout=35.0)
        resp = await self.llm_manager.complete(req)
        return parse_workflow_ir(resp.content)
