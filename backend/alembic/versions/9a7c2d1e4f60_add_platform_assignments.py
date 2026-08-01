"""add current platform assignment overlays

Revision ID: 9a7c2d1e4f60
Revises: 4d9e7a1c2b30
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "9a7c2d1e4f60"
down_revision: Union[str, Sequence[str], None] = "4d9e7a1c2b30"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "platform_assignments",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("broker_id", sa.String(36), nullable=False),
        sa.Column("load_id", sa.String(36), nullable=False),
        sa.Column("carrier_id", sa.String(36), nullable=False),
        sa.Column("candidate_id", sa.String(255), nullable=True),
        sa.Column("assignment_version", sa.Integer(), nullable=False),
        sa.Column("demo_actor", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "assignment_version > 0", name="ck_platform_assignments_version_positive"
        ),
        sa.ForeignKeyConstraint(
            ["broker_id", "load_id"],
            ["loads.broker_id", "loads.id"],
            name="fk_platform_assignments_load",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["broker_id", "carrier_id"],
            ["carriers.broker_id", "carriers.id"],
            name="fk_platform_assignments_carrier",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("broker_id", "id", name="uq_platform_assignments_broker_id"),
        sa.UniqueConstraint("broker_id", "load_id", name="uq_platform_assignments_broker_load"),
    )
    op.create_index(
        "ix_platform_assignments_broker_carrier",
        "platform_assignments",
        ["broker_id", "carrier_id"],
    )
    op.create_table(
        "platform_assignment_events",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("broker_id", sa.String(36), nullable=False),
        sa.Column("assignment_id", sa.String(36), nullable=False),
        sa.Column("load_id", sa.String(36), nullable=False),
        sa.Column("carrier_id", sa.String(36), nullable=False),
        sa.Column("candidate_id", sa.String(255), nullable=True),
        sa.Column("assignment_version", sa.Integer(), nullable=False),
        sa.Column("demo_actor", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "assignment_version > 0", name="ck_platform_assignment_events_version_positive"
        ),
        sa.ForeignKeyConstraint(
            ["broker_id", "assignment_id"],
            ["platform_assignments.broker_id", "platform_assignments.id"],
            name="fk_platform_assignment_events_assignment",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["broker_id", "load_id"],
            ["loads.broker_id", "loads.id"],
            name="fk_platform_assignment_events_load",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["broker_id", "carrier_id"],
            ["carriers.broker_id", "carriers.id"],
            name="fk_platform_assignment_events_carrier",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("broker_id", "id", name="uq_platform_assignment_events_broker_id_id"),
    )
    op.create_index(
        "ix_platform_assignment_events_assignment_created",
        "platform_assignment_events",
        ["assignment_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_platform_assignment_events_assignment_created",
        table_name="platform_assignment_events",
    )
    op.drop_table("platform_assignment_events")
    op.drop_index("ix_platform_assignments_broker_carrier", table_name="platform_assignments")
    op.drop_table("platform_assignments")
