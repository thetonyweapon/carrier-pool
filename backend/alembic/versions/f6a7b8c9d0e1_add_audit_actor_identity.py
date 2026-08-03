"""record immutable actor subjects on authorization audit rows

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for table, column in (
        ("shared_pool_policies", "changed_by_subject"),
        ("shared_pool_policy_events", "changed_by_subject"),
        ("shared_pool_query_audits", "actor_subject"),
        ("shared_pool_query_audits", "request_id"),
        ("platform_assignments", "actor_subject"),
        ("platform_assignment_events", "actor_subject"),
    ):
        op.add_column(
            table,
            sa.Column(
                column,
                sa.String(length=255 if column != "request_id" else 128),
                nullable=False,
                server_default="legacy",
            ),
        )


def downgrade() -> None:
    for table, column in (
        ("platform_assignment_events", "actor_subject"),
        ("platform_assignments", "actor_subject"),
        ("shared_pool_query_audits", "request_id"),
        ("shared_pool_query_audits", "actor_subject"),
        ("shared_pool_policy_events", "changed_by_subject"),
        ("shared_pool_policies", "changed_by_subject"),
    ):
        op.drop_column(table, column)
