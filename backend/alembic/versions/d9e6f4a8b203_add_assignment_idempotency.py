"""add assignment idempotency and append-only enforcement

Revision ID: d9e6f4a8b203
Revises: c8d5e3f7a102
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "d9e6f4a8b203"
down_revision: Union[str, None] = "c8d5e3f7a102"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("platform_assignment_events") as batch_op:
        batch_op.add_column(sa.Column("idempotency_key", sa.String(length=128), nullable=True))
        batch_op.create_unique_constraint(
            "uq_platform_assignment_events_idempotency",
            ["broker_id", "idempotency_key"],
        )
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute(
            """
            CREATE FUNCTION prevent_platform_assignment_event_mutation() RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'platform_assignment_events are append-only';
            END;
            $$ LANGUAGE plpgsql
            """
        )
        op.execute(
            """
            CREATE TRIGGER prevent_platform_assignment_event_mutation
            BEFORE UPDATE OR DELETE ON platform_assignment_events
            FOR EACH ROW EXECUTE FUNCTION prevent_platform_assignment_event_mutation()
            """
        )
    elif dialect == "sqlite":
        op.execute(
            """
            CREATE TRIGGER prevent_platform_assignment_event_update
            BEFORE UPDATE ON platform_assignment_events
            BEGIN
                SELECT RAISE(ABORT, 'platform_assignment_events are append-only');
            END
            """
        )
        op.execute(
            """
            CREATE TRIGGER prevent_platform_assignment_event_delete
            BEFORE DELETE ON platform_assignment_events
            BEGIN
                SELECT RAISE(ABORT, 'platform_assignment_events are append-only');
            END
            """
        )


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute(
            "DROP TRIGGER IF EXISTS prevent_platform_assignment_event_mutation "
            "ON platform_assignment_events"
        )
        op.execute("DROP FUNCTION IF EXISTS prevent_platform_assignment_event_mutation()")
    elif dialect == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS prevent_platform_assignment_event_update")
        op.execute("DROP TRIGGER IF EXISTS prevent_platform_assignment_event_delete")
    with op.batch_alter_table("platform_assignment_events") as batch_op:
        batch_op.drop_constraint("uq_platform_assignment_events_idempotency", type_="unique")
        batch_op.drop_column("idempotency_key")
