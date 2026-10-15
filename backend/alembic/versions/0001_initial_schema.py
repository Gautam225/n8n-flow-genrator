"""Initial schema: conversations, messages, workflow drafts, revisions

Revision ID: 0001_initial_schema
Revises: 
Create Date: 2026-10-12 14:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0001_initial_schema'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. conversations
    op.create_table(
        'conversations',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False, server_default='Untitled Conversation'),
        sa.Column('metadata_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_conversations')),
    )

    # 2. conversation_messages
    op.create_table(
        'conversation_messages',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('conversation_id', sa.String(length=36), nullable=False),
        sa.Column('role', sa.String(length=50), nullable=False, comment='Message role: user, assistant, system, tool'),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('metadata_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], name=op.f('fk_conversation_messages_conversation_id_conversations'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_conversation_messages')),
    )
    op.create_index(op.f('ix_conversation_messages_conversation_id'), 'conversation_messages', ['conversation_id'], unique=False)

    # 3. workflow_drafts
    op.create_table(
        'workflow_drafts',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('conversation_id', sa.String(length=36), nullable=True),
        sa.Column('title', sa.String(length=255), nullable=False, server_default='Untitled Workflow'),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='draft', comment='Workflow status: draft, validating, valid, invalid, compiled, deployed'),
        sa.Column('workflow_ir', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='Serialized WorkflowIR schema dictionary'),
        sa.Column('compiled_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='Compiled native n8n workflow structure JSON'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], name=op.f('fk_workflow_drafts_conversation_id_conversations'), ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_workflow_drafts')),
    )
    op.create_index(op.f('ix_workflow_drafts_conversation_id'), 'workflow_drafts', ['conversation_id'], unique=False)

    # 4. workflow_revisions
    op.create_table(
        'workflow_revisions',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('draft_id', sa.String(length=36), nullable=False),
        sa.Column('revision_number', sa.Integer(), nullable=False),
        sa.Column('workflow_ir', postgresql.JSONB(astext_type=sa.Text()), nullable=False, comment='Snapshot of WorkflowIR for this revision'),
        sa.Column('compiled_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='Compiled n8n native JSON if compiled during this revision'),
        sa.Column('validation_report', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='Validation report summary snapshot'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['draft_id'], ['workflow_drafts.id'], name=op.f('fk_workflow_revisions_draft_id_workflow_drafts'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_workflow_revisions')),
        sa.UniqueConstraint('draft_id', 'revision_number', name='uq_draft_revision_number'),
    )
    op.create_index(op.f('ix_workflow_revisions_draft_id'), 'workflow_revisions', ['draft_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_workflow_revisions_draft_id'), table_name='workflow_revisions')
    op.drop_table('workflow_revisions')

    op.drop_index(op.f('ix_workflow_drafts_conversation_id'), table_name='workflow_drafts')
    op.drop_table('workflow_drafts')

    op.drop_index(op.f('ix_conversation_messages_conversation_id'), table_name='conversation_messages')
    op.drop_table('conversation_messages')

    op.drop_table('conversations')
