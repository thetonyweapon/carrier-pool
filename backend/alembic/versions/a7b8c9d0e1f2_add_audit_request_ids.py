"""record request IDs on authorization mutation events

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for table in ("shared_pool_policy_events", "platform_assignment_events"):
        op.add_column(
            table,
            sa.Column("request_id", sa.String(length=128), nullable=False, server_default="legacy"),
        )


def downgrade() -> None:
    for table in ("platform_assignment_events", "shared_pool_policy_events"):
        op.drop_column(table, "request_id")
