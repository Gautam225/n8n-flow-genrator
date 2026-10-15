"""Unit tests for the Conversation State Machine and transition invariants."""
import pytest

from backend.app.orchestrator.state_machine import (
    ConversationState,
    InvalidStateTransitionError,
    StateMachine,
)
from backend.app.schemas.validation import (
    ValidationIssue,
    ValidationIssueSeverity,
    ValidationReport,
)


def test_valid_state_transitions():
    """Verify standard happy-path transitions succeed."""
    # 1. Initial turn to planning
    s1 = StateMachine.transition(None, ConversationState.PLANNING)
    assert s1 == ConversationState.PLANNING

    # 2. Initial turn to clarifying
    s2 = StateMachine.transition(None, ConversationState.CLARIFYING)
    assert s2 == ConversationState.CLARIFYING

    # 3. Clarifying to planning
    s3 = StateMachine.transition(ConversationState.CLARIFYING, ConversationState.PLANNING)
    assert s3 == ConversationState.PLANNING

    # 4. Planning to generating
    s4 = StateMachine.transition(ConversationState.PLANNING, ConversationState.GENERATING)
    assert s4 == ConversationState.GENERATING

    # 5. Generating to validating
    s5 = StateMachine.transition(ConversationState.GENERATING, ConversationState.VALIDATING)
    assert s5 == ConversationState.VALIDATING

    # 6. Validating to ready (with valid report)
    valid_report = ValidationReport(is_valid=True, issues=[])
    s6 = StateMachine.transition(
        ConversationState.VALIDATING,
        ConversationState.READY,
        validation_report=valid_report,
    )
    assert s6 == ConversationState.READY

    # 7. Ready back to planning for modification
    s7 = StateMachine.transition(ConversationState.READY, ConversationState.PLANNING)
    assert s7 == ConversationState.PLANNING


def test_invalid_state_transitions_raise_error():
    """Verify unauthorized transitions are strictly rejected."""
    # Cannot jump from None to READY
    with pytest.raises(InvalidStateTransitionError):
        StateMachine.transition(None, ConversationState.READY)

    # Cannot jump from PLANNING directly to READY
    with pytest.raises(InvalidStateTransitionError):
        StateMachine.transition(ConversationState.PLANNING, ConversationState.READY)

    # Cannot jump from GENERATING directly to READY
    with pytest.raises(InvalidStateTransitionError):
        StateMachine.transition(ConversationState.GENERATING, ConversationState.READY)

    # Cannot jump from CLARIFYING directly to VALIDATING
    with pytest.raises(InvalidStateTransitionError):
        StateMachine.transition(ConversationState.CLARIFYING, ConversationState.VALIDATING)


def test_transition_to_ready_requires_valid_report():
    """Strict invariant: Never mark ready unless deterministic validation succeeds."""
    # 1. Missing report
    with pytest.raises(InvalidStateTransitionError, match="must be present and report is_valid=True"):
        StateMachine.transition(ConversationState.VALIDATING, ConversationState.READY, validation_report=None)

    # 2. Invalid report with fatal issues
    invalid_report = ValidationReport(
        is_valid=False,
        issues=[
            ValidationIssue(
                severity=ValidationIssueSeverity.FATAL,
                rule_code="NODE_TYPE_UNKNOWN",
                message="Unknown node type 'fake.node'",
            )
        ],
    )
    with pytest.raises(InvalidStateTransitionError, match="must be present and report is_valid=True"):
        StateMachine.transition(
            ConversationState.VALIDATING,
            ConversationState.READY,
            validation_report=invalid_report,
        )
