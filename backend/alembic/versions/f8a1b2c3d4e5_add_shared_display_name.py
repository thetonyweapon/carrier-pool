"""add explicitly approved shared carrier names

Revision ID: f8a1b2c3d4e5
Revises: a7b8c9d0e1f2
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "f8a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "carrier_identities",
        sa.Column("shared_display_name", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("carrier_identities", "shared_display_name")
