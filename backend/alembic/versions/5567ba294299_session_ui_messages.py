"""session ui_messages

Revision ID: 5567ba294299
Revises: ea490f2064bf
Create Date: 2026-07-04 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '5567ba294299'
down_revision: Union[str, Sequence[str], None] = 'ea490f2064bf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add the frontend-rendered message transcript, separate from `history` (the
    raw agent-loop format), so switching to a past session can re-render it."""
    op.add_column(
        'sessions',
        sa.Column('ui_messages', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='[]'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('sessions', 'ui_messages')
