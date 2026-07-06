"""sts assume role credentials

Revision ID: ea490f2064bf
Revises: 7337195c7ea1
Create Date: 2026-07-04 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'ea490f2064bf'
down_revision: Union[str, Sequence[str], None] = '7337195c7ea1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Replace stored AWS access keys with STS AssumeRole (role_arn + external_id).
    Neither new column is a secret (an ARN is an identifier; AWS's guidance is that
    an external_id only needs to be unique, not encrypted), so no Fernet encryption
    applies here — unlike the columns being dropped."""
    op.add_column('user_settings', sa.Column('aws_role_arn', sa.String(), nullable=True))
    op.add_column('user_settings', sa.Column('aws_external_id', sa.String(), nullable=True))
    op.drop_column('user_settings', 'aws_access_key_id')
    op.drop_column('user_settings', 'aws_secret_access_key')


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column('user_settings', sa.Column('aws_secret_access_key', sa.String(), nullable=True))
    op.add_column('user_settings', sa.Column('aws_access_key_id', sa.String(), nullable=True))
    op.drop_column('user_settings', 'aws_external_id')
    op.drop_column('user_settings', 'aws_role_arn')
