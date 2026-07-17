"""add_new_statuses_to_enums

Revision ID: cbfeb13f1972
Revises: c553e918ef3e
Create Date: 2026-07-17 04:31:46.521934

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cbfeb13f1972'
down_revision: Union[str, Sequence[str], None] = 'c553e918ef3e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("COMMIT")
    op.execute("ALTER TYPE itemstatus ADD VALUE 'manual_review_approved'")
    op.execute("ALTER TYPE moderationqueuestatus ADD VALUE 'manual_review_approved'")
    op.execute("ALTER TYPE publicationstatus ADD VALUE 'ready'")
    op.execute("ALTER TYPE publicationstatus ADD VALUE 'publishing'")
    op.execute("ALTER TYPE publicationstatus ADD VALUE 'cancelled'")


def downgrade() -> None:
    """Downgrade schema."""
    pass
