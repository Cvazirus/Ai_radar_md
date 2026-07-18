"""add Telegram personal feedback tables

Revision ID: d9e4f8a1b2c3
Revises: cbfeb13f1972
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d9e4f8a1b2c3"
down_revision: Union[str, Sequence[str], None] = "cbfeb13f1972"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("publications", sa.Column("telegram_chat_id", sa.BigInteger(), nullable=True))
    op.create_index("ix_publications_telegram_chat_id", "publications", ["telegram_chat_id"])
    op.create_table(
        "user_feedback",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("publication_id", sa.Integer(), sa.ForeignKey("publications.item_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("reaction", sa.String(length=10), nullable=True),
        sa.Column("is_favorite", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_hidden", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("reaction IS NULL OR reaction IN ('like', 'dislike')", name="ck_user_feedback_reaction"),
        sa.UniqueConstraint("telegram_user_id", "publication_id", name="uq_user_feedback_user_publication"),
    )
    op.create_index("ix_user_feedback_telegram_user_id", "user_feedback", ["telegram_user_id"])
    op.create_index("ix_user_feedback_publication_id", "user_feedback", ["publication_id"])
    op.create_index("ix_user_feedback_reaction", "user_feedback", ["reaction"])
    op.create_table(
        "user_preferences",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("preference_type", sa.String(length=20), nullable=False),
        sa.Column("preference_key", sa.String(length=255), nullable=False),
        sa.Column("weight", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("positive_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("negative_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("preference_type IN ('topic', 'source', 'entity', 'content_type')", name="ck_user_preference_type"),
        sa.UniqueConstraint("telegram_user_id", "preference_type", "preference_key", name="uq_user_preference_user_type_key"),
    )
    op.create_index("ix_user_preferences_telegram_user_id", "user_preferences", ["telegram_user_id"])
    op.create_index("ix_user_preferences_preference_type", "user_preferences", ["preference_type"])
    op.create_index("ix_user_preferences_preference_key", "user_preferences", ["preference_key"])
    op.create_table(
        "telegram_update_receipts",
        sa.Column("update_id", sa.BigInteger(), primary_key=True),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=True),
        sa.Column("publication_id", sa.Integer(), sa.ForeignKey("publications.item_id", ondelete="SET NULL"), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_telegram_update_receipts_telegram_user_id", "telegram_update_receipts", ["telegram_user_id"])
    op.create_index("ix_telegram_update_receipts_publication_id", "telegram_update_receipts", ["publication_id"])


def downgrade() -> None:
    op.drop_index("ix_telegram_update_receipts_publication_id", table_name="telegram_update_receipts")
    op.drop_index("ix_telegram_update_receipts_telegram_user_id", table_name="telegram_update_receipts")
    op.drop_table("telegram_update_receipts")
    op.drop_index("ix_user_preferences_preference_key", table_name="user_preferences")
    op.drop_index("ix_user_preferences_preference_type", table_name="user_preferences")
    op.drop_index("ix_user_preferences_telegram_user_id", table_name="user_preferences")
    op.drop_table("user_preferences")
    op.drop_index("ix_user_feedback_reaction", table_name="user_feedback")
    op.drop_index("ix_user_feedback_publication_id", table_name="user_feedback")
    op.drop_index("ix_user_feedback_telegram_user_id", table_name="user_feedback")
    op.drop_table("user_feedback")
    op.drop_index("ix_publications_telegram_chat_id", table_name="publications")
    op.drop_column("publications", "telegram_chat_id")
