"""Unit tests for database models, constraints, serialization, and settings."""
import uuid
import pytest
from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import JSONB

from backend.app.config import DatabaseSettings
from backend.app.db.base import Base
from backend.app.models.conversation import Conversation, ConversationMessage
from backend.app.models.workflow import WorkflowDraft, WorkflowRevision
from backend.app.schemas.ir import (
    WorkflowIR,
    IRNode,
    IREdge,
    NodePosition,
)


def test_conversation_model_definition():
    """Verify Conversation model schema, primary key, and table metadata."""
    mapper = inspect(Conversation)
    assert mapper.tables[0].name == "conversations"

    # Columns
    cols = {c.key: c for c in mapper.columns}
    assert "id" in cols
    assert cols["id"].primary_key is True
    assert "title" in cols
    assert cols["title"].nullable is False
    assert "created_at" in cols
    assert "updated_at" in cols
    assert "metadata_json" in cols

    # Relationships
    rel_names = {r.key for r in mapper.relationships}
    assert "messages" in rel_names
    assert "drafts" in rel_names


def test_conversation_message_model_definition():
    """Verify ConversationMessage model, foreign keys, and indexes."""
    mapper = inspect(ConversationMessage)
    assert mapper.tables[0].name == "conversation_messages"

    cols = {c.key: c for c in mapper.columns}
    assert "id" in cols
    assert "conversation_id" in cols
    assert cols["conversation_id"].nullable is False
    assert "role" in cols
    assert "content" in cols
    assert cols["content"].nullable is False
    assert "created_at" in cols

    # Foreign key
    fk = list(cols["conversation_id"].foreign_keys)[0]
    assert fk.target_fullname == "conversations.id"
    assert fk.ondelete == "CASCADE"


def test_workflow_draft_model_definition():
    """Verify WorkflowDraft model schema, relationships, and JSONB fields."""
    mapper = inspect(WorkflowDraft)
    assert mapper.tables[0].name == "workflow_drafts"

    cols = {c.key: c for c in mapper.columns}
    assert "id" in cols
    assert "conversation_id" in cols
    assert cols["conversation_id"].nullable is True
    assert "title" in cols
    assert "status" in cols
    assert "workflow_ir" in cols
    assert isinstance(cols["workflow_ir"].type, JSONB)
    assert "compiled_json" in cols
    assert isinstance(cols["compiled_json"].type, JSONB)

    # Relationship
    rel_names = {r.key for r in mapper.relationships}
    assert "revisions" in rel_names


def test_workflow_revision_constraints():
    """Verify WorkflowRevision table constraints and revision uniqueness."""
    mapper = inspect(WorkflowRevision)
    table = mapper.tables[0]
    assert table.name == "workflow_revisions"

    cols = {c.key: c for c in mapper.columns}
    assert "id" in cols
    assert "draft_id" in cols
    assert "revision_number" in cols
    assert cols["revision_number"].nullable is False
    assert "workflow_ir" in cols
    assert cols["workflow_ir"].nullable is False

    # Unique constraint on (draft_id, revision_number)
    unique_constraints = [c for c in table.constraints if hasattr(c, "columns") and len(c.columns) == 2]
    uq_col_names = [{col.name for col in c.columns} for c in unique_constraints]
    assert {"draft_id", "revision_number"} in uq_col_names


def test_workflow_ir_serialization_compatibility():
    """Verify WorkflowIR Pydantic schema serializes cleanly for JSONB persistence."""
    ir = WorkflowIR(
        id="wf_order_sync_1",
        name="Order Sync Flow",
        nodes=[
            IRNode(
                id="webhook_1",
                name="Webhook Trigger",
                node_type="n8n-nodes-base.webhook",
                type_version=2,
                position=NodePosition(x=100.0, y=200.0),
                parameters={"path": "orders", "httpMethod": "POST"},
            ),
            IRNode(
                id="slack_1",
                name="Send Slack Alert",
                node_type="n8n-nodes-base.slack",
                type_version=2.2,
                position=NodePosition(x=350.0, y=200.0),
                parameters={"channel": "#alerts"},
            ),
        ],
        edges=[
            IREdge(source_id="webhook_1", target_id="slack_1"),
        ],
    )

    # Serialization
    dumped = ir.model_dump(mode="json")
    assert isinstance(dumped, dict)
    assert dumped["name"] == "Order Sync Flow"
    assert len(dumped["nodes"]) == 2
    assert len(dumped["edges"]) == 1

    # Deserialization round-trip
    restored = WorkflowIR.model_validate(dumped)
    assert restored.name == ir.name
    assert restored.nodes[0].id == "webhook_1"


def test_database_settings_url_validation():
    """Verify DatabaseSettings enforces PostgreSQL and converts plain scheme to asyncpg."""
    # 1. postgresql+asyncpg accepted
    s1 = DatabaseSettings(DATABASE_URL="postgresql+asyncpg://usr:pw@localhost:5432/n8n_workflow_ai")
    assert s1.DATABASE_URL == "postgresql+asyncpg://usr:pw@localhost:5432/n8n_workflow_ai"

    # 2. plain postgresql converted to asyncpg
    s2 = DatabaseSettings(DATABASE_URL="postgresql://usr:pw@localhost:5432/n8n_workflow_ai")
    assert s2.DATABASE_URL == "postgresql+asyncpg://usr:pw@localhost:5432/n8n_workflow_ai"

    # 3. SQLite strictly rejected
    with pytest.raises(ValueError, match="PostgreSQL is mandatory"):
        DatabaseSettings(DATABASE_URL="sqlite:///./test.db")

    with pytest.raises(ValueError, match="PostgreSQL is mandatory"):
        DatabaseSettings(DATABASE_URL="sqlite+aiosqlite:///./test.db")


def test_database_settings_password_masking():
    """Verify get_masked_database_url never exposes plaintext database passwords."""
    secret_pass = "super_secret_db_pass_9999"
    s = DatabaseSettings(DATABASE_URL=f"postgresql+asyncpg://admin:{secret_pass}@localhost:5432/n8n_workflow_ai")

    masked = s.get_masked_database_url()
    assert secret_pass not in masked
    assert "admin:***@localhost:5432/n8n_workflow_ai" in masked
