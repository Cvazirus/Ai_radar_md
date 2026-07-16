"""add_pipeline_runs

Revision ID: c553e918ef3e
Revises: 8e9af22c2b49
Create Date: 2026-07-16 20:40:55.476069

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c553e918ef3e'
down_revision: Union[str, Sequence[str], None] = '8e9af22c2b49'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create enum type first conditionally
    op.execute("DO $$ BEGIN CREATE TYPE pipelinerunstatus AS ENUM('pending', 'running', 'completed', 'failed', 'cancelled'); EXCEPTION WHEN duplicate_object THEN null; END $$;")

    op.create_table('pipeline_runs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('run_id', sa.String(length=255), nullable=False),
    sa.Column('status', postgresql.ENUM('pending', 'running', 'completed', 'failed', 'cancelled', name='pipelinerunstatus', create_type=False), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('current_step', sa.String(length=100), nullable=True),
    sa.Column('items_total', sa.Integer(), nullable=False),
    sa.Column('items_processed', sa.Integer(), nullable=False),
    sa.Column('items_failed', sa.Integer(), nullable=False),
    sa.Column('duration_ms', sa.Integer(), nullable=True),
    sa.Column('summary', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('run_id')
    )


def downgrade() -> None:
    op.drop_table('pipeline_runs')
    op.execute("DROP TYPE IF EXISTS pipelinerunstatus")
