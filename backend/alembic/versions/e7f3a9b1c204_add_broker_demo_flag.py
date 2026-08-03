"""add broker demo flag

Revision ID: e7f3a9b1c204
Revises: d9e6f4a8b203
Create Date: 2026-08-03 00:00:00

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e7f3a9b1c204"
down_revision: Union[str, Sequence[str], None] = "d9e6f4a8b203"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "brokers",
        sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_column("brokers", "is_demo")
