"""add carrier recommendation history index

Revision ID: 4d9e7a1c2b30
Revises: 2f7d1c9a4e30
Create Date: 2026-07-30 00:00:00

"""

from typing import Sequence, Union

from alembic import op

revision: str = "4d9e7a1c2b30"
down_revision: Union[str, Sequence[str], None] = "2f7d1c9a4e30"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_loads_broker_status_synced",
        "loads",
        ["broker_id", "status", "last_synced_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_loads_broker_status_synced", table_name="loads")
