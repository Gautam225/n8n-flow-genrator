"""SQLAlchemy models for workflow drafts and revision history."""
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional
import uuid
from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base

if TYPE_CHECKING:
    from backend.app.models.conversation import Conversation



def generate_uuid() -> str:
    """Generate string UUID."""
    return str(uuid.uuid4())


class WorkflowDraft(Base):
    """Workflow draft representing an in-progress or completed generated workflow."""

    __tablename__ = "workflow_drafts"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=generate_uuid,
    )
    conversation_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        default="Untitled Workflow",
    )
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="draft",
        comment="Workflow status: draft, validating, valid, invalid, compiled, deployed",
    )
    workflow_ir: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
        comment="Serialized WorkflowIR schema dictionary",
    )
    compiled_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
        comment="Compiled native n8n workflow structure JSON",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    conversation: Mapped[Optional["Conversation"]] = relationship(
        "Conversation",
        back_populates="drafts",
    )
    revisions: Mapped[List["WorkflowRevision"]] = relationship(
        "WorkflowRevision",
        back_populates="draft",
        cascade="all, delete-orphan",
        order_by="WorkflowRevision.revision_number",
    )

    def __repr__(self) -> str:
        return f"<WorkflowDraft(id='{self.id}', title='{self.title}', status='{self.status}')>"


class WorkflowRevision(Base):
    """Immutable revision entry recording an iteration or repair of a workflow draft."""

    __tablename__ = "workflow_revisions"
    __table_args__ = (
        UniqueConstraint("draft_id", "revision_number", name="uq_draft_revision_number"),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=generate_uuid,
    )
    draft_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("workflow_drafts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    revision_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    workflow_ir: Mapped[Dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        comment="Snapshot of WorkflowIR for this revision",
    )
    compiled_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
        comment="Compiled n8n native JSON if compiled during this revision",
    )
    validation_report: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
        comment="Validation report summary snapshot",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationship
    draft: Mapped["WorkflowDraft"] = relationship(
        "WorkflowDraft",
        back_populates="revisions",
    )

    def __repr__(self) -> str:
        return f"<WorkflowRevision(id='{self.id}', draft_id='{self.draft_id}', rev={self.revision_number})>"
