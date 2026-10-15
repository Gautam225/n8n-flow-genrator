"""Conversation State Machine defining explicit workflow generation lifecycle states."""
from enum import Enum
from typing import Dict, Optional, Set

from backend.app.schemas.validation import ValidationReport


class ConversationState(str, Enum):
    """Explicit states of the workflow architect conversation lifecycle."""

    CLARIFYING = "clarifying"
    PLANNING = "planning"
    GENERATING = "generating"
    VALIDATING = "validating"
    READY = "ready"
    FAILED = "failed"


class InvalidStateTransitionError(ValueError):
    """Raised when attempting an unauthorized or invalid state transition."""

    pass


class StateMachine:
    """Manages explicit conversation state transitions with strict invariants."""

    # Transition matrix defining permitted (from_state -> set of to_states)
    ALLOWED_TRANSITIONS: Dict[Optional[ConversationState], Set[ConversationState]] = {
        None: {ConversationState.CLARIFYING, ConversationState.PLANNING, ConversationState.FAILED},
        ConversationState.CLARIFYING: {
            ConversationState.CLARIFYING,
            ConversationState.PLANNING,
            ConversationState.FAILED,
        },
        ConversationState.PLANNING: {
            ConversationState.PLANNING,
            ConversationState.GENERATING,
            ConversationState.CLARIFYING,
            ConversationState.FAILED,
        },
        ConversationState.GENERATING: {
            ConversationState.VALIDATING,
            ConversationState.FAILED,
        },
        ConversationState.VALIDATING: {
            ConversationState.READY,
            ConversationState.FAILED,
            ConversationState.CLARIFYING,
        },
        ConversationState.READY: {
            ConversationState.PLANNING,
            ConversationState.CLARIFYING,
        },
        ConversationState.FAILED: {
            ConversationState.PLANNING,
            ConversationState.CLARIFYING,
        },
    }

    @classmethod
    def can_transition(
        cls,
        from_state: Optional[ConversationState],
        to_state: ConversationState,
    ) -> bool:
        """Checks if a transition between from_state and to_state is allowed."""
        allowed = cls.ALLOWED_TRANSITIONS.get(from_state, set())
        return to_state in allowed

    @classmethod
    def transition(
        cls,
        from_state: Optional[ConversationState],
        to_state: ConversationState,
        validation_report: Optional[ValidationReport] = None,
    ) -> ConversationState:
        """Transitions to to_state or raises InvalidStateTransitionError.

        Invariant: Never transition to READY unless deterministic validation succeeds.
        """
        if not cls.can_transition(from_state, to_state):
            from_desc = from_state.value if from_state else "INITIAL"
            raise InvalidStateTransitionError(
                f"Invalid transition from state '{from_desc}' to '{to_state.value}'."
            )

        if to_state == ConversationState.READY:
            if validation_report is None or not validation_report.is_valid:
                raise InvalidStateTransitionError(
                    "Cannot transition to 'ready': deterministic validation must be present and report is_valid=True."
                )

        return to_state
