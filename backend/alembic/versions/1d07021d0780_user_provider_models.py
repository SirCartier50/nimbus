"""user provider models

Revision ID: 1d07021d0780
Revises: daea0e3f7f91
Create Date: 2026-08-03 01:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '1d07021d0780'
down_revision: Union[str, Sequence[str], None] = 'daea0e3f7f91'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """{provider_name: model_id} — per-user model override (Settings > Model
    Configurations). Plain JSONB, not encrypted: a model id isn't a secret,
    unlike provider_keys_enc on the same table."""
    op.add_column(
        'user_settings',
        sa.Column('provider_models', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('user_settings', 'provider_models')
