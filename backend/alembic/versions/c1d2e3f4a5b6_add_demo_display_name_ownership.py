"""track demo-owned shared display names

Revision ID: c1d2e3f4a5b6
Revises: f8a1b2c3d4e5
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, Sequence[str], None] = "f8a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "carrier_identities",
        sa.Column(
            "shared_display_name_bootstrap_owned",
            sa.Boolean(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("carrier_identities", "shared_display_name_bootstrap_owned")
