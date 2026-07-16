"""rewrite item_analysis to v2 with history and input_hash

Revision ID: a1b2c3d4e5f6
Revises: 735b7119c26f
Create Date: 2026-07-16

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, ENUM

revision = 'a1b2c3d4e5f6'
down_revision = '735b7119c26f'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create enum type if not exists
    analysis_status = ENUM(
        'pending', 'running', 'success', 'failed', 'invalid_response', 'skipped',
        name='analysisstatus',
        create_type=False
    )
    analysis_status.create(op.get_bind(), checkfirst=True)

    # 1. Drop primary key constraint of item_id
    op.execute("ALTER TABLE item_analysis DROP CONSTRAINT IF EXISTS item_analysis_pkey CASCADE")

    # 2. Add id BIGSERIAL PRIMARY KEY
    op.execute("ALTER TABLE item_analysis ADD COLUMN id BIGSERIAL PRIMARY KEY")

    # 3. Add prompt_version, analysis_version, status, input_hash
    op.add_column('item_analysis', sa.Column('prompt_version', sa.String(length=50), nullable=False, server_default='legacy'))
    op.add_column('item_analysis', sa.Column('analysis_version', sa.String(length=50), nullable=False, server_default='1.0'))
    op.add_column('item_analysis', sa.Column('status', sa.Enum('pending', 'running', 'success', 'failed', 'invalid_response', 'skipped', name='analysisstatus'), nullable=False, server_default='success'))
    op.add_column('item_analysis', sa.Column('input_hash', sa.String(length=64), nullable=False, server_default='legacy'))

    # 4. Make existing columns nullable
    op.alter_column('item_analysis', 'category', nullable=True, existing_type=sa.Enum(name='categoryenum'))
    op.alter_column('item_analysis', 'summary_ru', nullable=True, existing_type=sa.Text())
    op.alter_column('item_analysis', 'is_primary_source', nullable=True, existing_type=sa.Boolean())
    op.alter_column('item_analysis', 'is_promotional', nullable=True, existing_type=sa.Boolean())

    # 5. Change Float to Numeric
    op.alter_column('item_analysis', 'total_score', type_=sa.Numeric(precision=5, scale=2), existing_type=sa.Float())
    op.alter_column('item_analysis', 'confidence', type_=sa.Numeric(precision=5, scale=4), existing_type=sa.Float())

    # 6. Add new columns
    op.add_column('item_analysis', sa.Column('is_actionable', sa.Boolean(), nullable=True))
    op.add_column('item_analysis', sa.Column('is_newsworthy', sa.Boolean(), nullable=True))
    op.add_column('item_analysis', sa.Column('source_claims', JSONB(), nullable=True))
    op.add_column('item_analysis', sa.Column('uncertainties', JSONB(), nullable=True))
    op.add_column('item_analysis', sa.Column('base_score', sa.Numeric(precision=5, scale=2), nullable=True))
    op.add_column('item_analysis', sa.Column('penalties', JSONB(), nullable=True))
    op.add_column('item_analysis', sa.Column('score_version', sa.String(length=50), nullable=True, server_default='1.0'))
    op.add_column('item_analysis', sa.Column('error_type', sa.String(length=50), nullable=True))
    op.add_column('item_analysis', sa.Column('error_message', sa.Text(), nullable=True))
    op.add_column('item_analysis', sa.Column('input_chars', sa.Integer(), nullable=True))
    op.add_column('item_analysis', sa.Column('response_chars', sa.Integer(), nullable=True))
    op.add_column('item_analysis', sa.Column('attempt_count', sa.Integer(), nullable=False, server_default='1'))
    op.add_column('item_analysis', sa.Column('started_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('item_analysis', sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('item_analysis', sa.Column('duration_ms', sa.Integer(), nullable=True))
    op.add_column('item_analysis', sa.Column('force_reason', sa.Text(), nullable=True))
    op.add_column('item_analysis', sa.Column('force_run', sa.Boolean(), nullable=False, server_default='false'))

    # 7. Migrate analyzed_at to started_at and finished_at
    op.execute("UPDATE item_analysis SET finished_at = analyzed_at, started_at = analyzed_at WHERE finished_at IS NULL")

    # 8. Drop analyzed_at and popularity_score
    op.drop_column('item_analysis', 'analyzed_at')
    op.drop_column('item_analysis', 'popularity_score')

    # 9. Create Indexes
    op.create_index('ix_item_analysis_item_id', 'item_analysis', ['item_id'])
    op.create_index('ix_item_analysis_status', 'item_analysis', ['status'])
    op.create_index('ix_item_analysis_input_hash', 'item_analysis', ['input_hash'])
    op.create_index('ix_item_analysis_created_at', 'item_analysis', ['created_at'])
    op.create_index('ix_item_analysis_model_name', 'item_analysis', ['model_name'])


def downgrade() -> None:
    # 1. Add analyzed_at and popularity_score back
    op.add_column('item_analysis', sa.Column('analyzed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True))
    op.add_column('item_analysis', sa.Column('popularity_score', sa.Integer(), nullable=True))

    # 2. Populate analyzed_at from finished_at
    op.execute("UPDATE item_analysis SET analyzed_at = finished_at WHERE finished_at IS NOT NULL")
    op.alter_column('item_analysis', 'analyzed_at', nullable=False)

    # 3. Drop indexes
    op.drop_index('ix_item_analysis_item_id', 'item_analysis')
    op.drop_index('ix_item_analysis_status', 'item_analysis')
    op.drop_index('ix_item_analysis_input_hash', 'item_analysis')
    op.drop_index('ix_item_analysis_created_at', 'item_analysis')
    op.drop_index('ix_item_analysis_model_name', 'item_analysis')

    # 4. Drop primary key constraint on id first
    op.execute("ALTER TABLE item_analysis DROP CONSTRAINT IF EXISTS item_analysis_pkey CASCADE")

    # 5. Drop new columns
    op.drop_column('item_analysis', 'id')
    op.drop_column('item_analysis', 'prompt_version')
    op.drop_column('item_analysis', 'analysis_version')
    op.drop_column('item_analysis', 'status')
    op.drop_column('item_analysis', 'input_hash')
    op.drop_column('item_analysis', 'is_actionable')
    op.drop_column('item_analysis', 'is_newsworthy')
    op.drop_column('item_analysis', 'source_claims')
    op.drop_column('item_analysis', 'uncertainties')
    op.drop_column('item_analysis', 'base_score')
    op.drop_column('item_analysis', 'penalties')
    op.drop_column('item_analysis', 'score_version')
    op.drop_column('item_analysis', 'error_type')
    op.drop_column('item_analysis', 'error_message')
    op.drop_column('item_analysis', 'input_chars')
    op.drop_column('item_analysis', 'response_chars')
    op.drop_column('item_analysis', 'attempt_count')
    op.drop_column('item_analysis', 'started_at')
    op.drop_column('item_analysis', 'finished_at')
    op.drop_column('item_analysis', 'duration_ms')
    op.drop_column('item_analysis', 'force_reason')
    op.drop_column('item_analysis', 'force_run')

    # 6. Restore PK constraint on item_id
    op.create_primary_key('item_analysis_pkey', 'item_analysis', ['item_id'])

    # 7. Make columns NOT NULL
    op.alter_column('item_analysis', 'category', nullable=False, existing_type=sa.Enum(name='categoryenum'))
    op.alter_column('item_analysis', 'summary_ru', nullable=False, existing_type=sa.Text())
    op.alter_column('item_analysis', 'is_primary_source', nullable=False, existing_type=sa.Boolean())
    op.alter_column('item_analysis', 'is_promotional', nullable=False, existing_type=sa.Boolean())

    # 8. Change Numeric back to Float
    op.alter_column('item_analysis', 'total_score', type_=sa.Float(), existing_type=sa.Numeric(precision=5, scale=2))
    op.alter_column('item_analysis', 'confidence', type_=sa.Float(), existing_type=sa.Numeric(precision=5, scale=4))

    # 9. Drop status enum
    op.execute("DROP TYPE IF EXISTS analysisstatus")
