"""add Telegram moderation queue binding and update receipts

Revision ID: e7f8a9b0c1d2
Revises: d9e4f8a1b2c3
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "e7f8a9b0c1d2"
down_revision: Union[str, Sequence[str], None] = "d9e4f8a1b2c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("moderation_queue", sa.Column("telegram_chat_id", sa.BigInteger(), nullable=True))
    op.add_column("moderation_queue", sa.Column("telegram_message_id", sa.Integer(), nullable=True))
    op.add_column("moderation_queue", sa.Column("telegram_dispatch_started_at", sa.DateTime(timezone=True), nullable=True))
    op.create_unique_constraint("uq_moderation_queue_telegram_message", "moderation_queue", ["telegram_chat_id", "telegram_message_id"])
    op.create_table(
        "telegram_moderation_update_receipts",
        sa.Column("update_id", sa.BigInteger(), primary_key=True),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=True),
        sa.Column("moderation_queue_id", sa.Integer(), sa.ForeignKey("moderation_queue.id", ondelete="SET NULL"), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_telegram_moderation_update_receipts_telegram_user_id", "telegram_moderation_update_receipts", ["telegram_user_id"])
    op.create_index("ix_telegram_moderation_update_receipts_moderation_queue_id", "telegram_moderation_update_receipts", ["moderation_queue_id"])
    op.create_table(
        "telegram_moderation_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("moderation_queue_id", sa.Integer(), sa.ForeignKey("moderation_queue.id", ondelete="CASCADE"), nullable=False),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("telegram_message_id", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("telegram_chat_id", "telegram_message_id", name="uq_telegram_moderation_messages_chat_message"),
    )
    op.create_index("ix_telegram_moderation_messages_queue_active", "telegram_moderation_messages", ["moderation_queue_id", "is_active"])


def downgrade() -> None:
    op.drop_index("ix_telegram_moderation_messages_queue_active", table_name="telegram_moderation_messages")
    op.drop_table("telegram_moderation_messages")
    op.drop_index("ix_telegram_moderation_update_receipts_moderation_queue_id", table_name="telegram_moderation_update_receipts")
    op.drop_index("ix_telegram_moderation_update_receipts_telegram_user_id", table_name="telegram_moderation_update_receipts")
    op.drop_table("telegram_moderation_update_receipts")
    op.drop_constraint("uq_moderation_queue_telegram_message", "moderation_queue", type_="unique")
    op.drop_column("moderation_queue", "telegram_dispatch_started_at")
    op.drop_column("moderation_queue", "telegram_message_id")
    op.drop_column("moderation_queue", "telegram_chat_id")
