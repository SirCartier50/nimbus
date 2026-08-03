"""user provider api keys

Revision ID: daea0e3f7f91
Revises: c41d8f0a92b7
Create Date: 2026-08-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'daea0e3f7f91'
down_revision: Union[str, Sequence[str], None] = 'c41d8f0a92b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """{provider_name: fernet_ciphertext} for a user's own LLM provider keys —
    unlike aws_role_arn/aws_external_id on this same table, these ARE secrets,
    so they're Fernet-encrypted (see utils/secret_box.py) rather than stored
    as-is."""
    op.add_column(
        'user_settings',
        sa.Column('provider_keys_enc', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('user_settings', 'provider_keys_enc')
