"""add_moderation_queue

Revision ID: 8e9af22c2b49
Revises: a1b2c3d4e5f6
Create Date: 2026-07-16 10:09:41.195086

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '8e9af22c2b49'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create Enum types in PostgreSQL
    moderation_queue_status = sa.Enum(
        'pending', 'in_review', 'approved', 'rejected', 'needs_revision', 'expired', 'cancelled',
        name='moderationqueuestatus'
    )
    moderation_queue_status.create(op.get_bind(), checkfirst=True)

    moderation_priority = sa.Enum(
        'low', 'normal', 'high', 'critical',
        name='moderationpriority'
    )
    moderation_priority.create(op.get_bind(), checkfirst=True)

    moderation_decision = sa.Enum(
        'archive', 'digest_candidate', 'manual_review', 'priority_review', 'blocked',
        name='moderationdecision'
    )
    moderation_decision.create(op.get_bind(), checkfirst=True)

    op.create_table('moderation_queue',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False, start=1, increment=1), nullable=False),
    sa.Column('item_id', sa.BigInteger(), nullable=False),
    sa.Column('analysis_id', sa.BigInteger(), nullable=False),
    sa.Column('queue_status', postgresql.ENUM('pending', 'in_review', 'approved', 'rejected', 'needs_revision', 'expired', 'cancelled', name='moderationqueuestatus', create_type=False), nullable=False),
    sa.Column('priority', postgresql.ENUM('low', 'normal', 'high', 'critical', name='moderationpriority', create_type=False), nullable=False),
    sa.Column('decision', postgresql.ENUM('archive', 'digest_candidate', 'manual_review', 'priority_review', 'blocked', name='moderationdecision', create_type=False), nullable=False),
    sa.Column('decision_score', sa.Numeric(precision=5, scale=2), nullable=True),
    sa.Column('decision_reasons', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('blocking_reasons', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('warnings', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('assigned_to', sa.String(length=255), nullable=True),
    sa.Column('reviewed_by', sa.String(length=255), nullable=True),
    sa.Column('review_notes', sa.Text(), nullable=True),
    sa.Column('queued_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('review_started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['analysis_id'], ['item_analysis.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['item_id'], ['items.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('analysis_id')
    )
    op.create_index('ix_moderation_queue_analysis_id', 'moderation_queue', ['analysis_id'], unique=False)
    op.create_index('ix_moderation_queue_decision', 'moderation_queue', ['decision'], unique=False)
    op.create_index('ix_moderation_queue_item_id', 'moderation_queue', ['item_id'], unique=False)
    op.create_index('ix_moderation_queue_priority', 'moderation_queue', ['priority'], unique=False)
    op.create_index('ix_moderation_queue_queue_status', 'moderation_queue', ['queue_status'], unique=False)
    op.create_index('ix_moderation_queue_queued_at', 'moderation_queue', ['queued_at'], unique=False)
    
    op.create_table('moderation_decision_log',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False, start=1, increment=1), nullable=False),
    sa.Column('queue_id', sa.BigInteger(), nullable=False),
    sa.Column('previous_status', postgresql.ENUM('pending', 'in_review', 'approved', 'rejected', 'needs_revision', 'expired', 'cancelled', name='moderationqueuestatus', create_type=False), nullable=True),
    sa.Column('new_status', postgresql.ENUM('pending', 'in_review', 'approved', 'rejected', 'needs_revision', 'expired', 'cancelled', name='moderationqueuestatus', create_type=False), nullable=False),
    sa.Column('action', sa.String(length=100), nullable=False),
    sa.Column('actor', sa.String(length=255), nullable=True),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['queue_id'], ['moderation_queue.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('moderation_decision_log')
    op.drop_index('ix_moderation_queue_queued_at', table_name='moderation_queue')
    op.drop_index('ix_moderation_queue_queue_status', table_name='moderation_queue')
    op.drop_index('ix_moderation_queue_priority', table_name='moderation_queue')
    op.drop_index('ix_moderation_queue_item_id', table_name='moderation_queue')
    op.drop_index('ix_moderation_queue_decision', table_name='moderation_queue')
    op.drop_index('ix_moderation_queue_analysis_id', table_name='moderation_queue')
    op.drop_table('moderation_queue')

    # Drop Enum types from PostgreSQL
    op.execute("DROP TYPE IF EXISTS moderationqueuestatus")
    op.execute("DROP TYPE IF EXISTS moderationpriority")
    op.execute("DROP TYPE IF EXISTS moderationdecision")
