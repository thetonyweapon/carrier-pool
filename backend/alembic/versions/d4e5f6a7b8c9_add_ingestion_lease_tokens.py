"""add ingestion lease fencing tokens

Revision ID: d4e5f6a7b8c9
Revises: e7f3a9b1c204
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "e7f3a9b1c204"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("ingestion_jobs", sa.Column("lease_token", sa.String(length=36), nullable=True))


def downgrade() -> None:
    op.drop_column("ingestion_jobs", "lease_token")
