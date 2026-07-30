"""add BrokerOS rate observations and stop metadata

Revision ID: 2f7d1c9a4e30
Revises: 1b4c4f0a2d91
Create Date: 2026-07-30 00:00:00

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "2f7d1c9a4e30"
down_revision: Union[str, Sequence[str], None] = "1b4c4f0a2d91"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("load_stops") as batch_op:
        batch_op.add_column(sa.Column("scheduled_date", sa.Date(), nullable=True))
        batch_op.add_column(sa.Column("source_location_id", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("location_name", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("source_sequence_value", sa.Numeric(12, 3), nullable=True))

    op.create_table(
        "load_rate_observations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("broker_id", sa.String(length=36), nullable=False),
        sa.Column("broker_source_id", sa.String(length=36), nullable=False),
        sa.Column("load_id", sa.String(length=36), nullable=False),
        sa.Column("ingestion_file_id", sa.String(length=36), nullable=False),
        sa.Column(
            "side",
            sa.Enum("bill", "pay", name="rate_side", native_enum=False, create_constraint=True),
            nullable=False,
        ),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("observation_number", sa.Integer(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["broker_id", "broker_source_id"],
            ["broker_sources.broker_id", "broker_sources.id"],
            name="fk_load_rate_observations_source",
        ),
        sa.ForeignKeyConstraint(
            ["broker_id", "broker_source_id", "load_id"],
            ["loads.broker_id", "loads.broker_source_id", "loads.id"],
            name="fk_load_rate_observations_load",
        ),
        sa.ForeignKeyConstraint(
            ["broker_id", "broker_source_id", "ingestion_file_id"],
            [
                "ingestion_files.broker_id",
                "ingestion_files.broker_source_id",
                "ingestion_files.id",
            ],
            name="fk_load_rate_observations_ingestion_file",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("broker_id", "id", name="uq_load_rate_observations_broker_id_id"),
        sa.UniqueConstraint(
            "load_id", "side", "observation_number", name="uq_load_rate_observations_sequence"
        ),
        sa.UniqueConstraint(
            "ingestion_file_id",
            "load_id",
            "side",
            name="uq_load_rate_observations_file_load_side",
        ),
    )
    _create_append_only_triggers()


def downgrade() -> None:
    _drop_append_only_triggers()
    op.drop_table("load_rate_observations")
    with op.batch_alter_table("load_stops") as batch_op:
        batch_op.drop_column("source_sequence_value")
        batch_op.drop_column("location_name")
        batch_op.drop_column("source_location_id")
        batch_op.drop_column("scheduled_date")


def _create_append_only_triggers() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute(
            """
            CREATE FUNCTION prevent_load_rate_observation_mutation() RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'load_rate_observations are append-only';
            END;
            $$ LANGUAGE plpgsql
            """
        )
        op.execute(
            """
            CREATE TRIGGER prevent_load_rate_observation_mutation
            BEFORE UPDATE OR DELETE ON load_rate_observations
            FOR EACH ROW EXECUTE FUNCTION prevent_load_rate_observation_mutation()
            """
        )
    elif dialect == "sqlite":
        op.execute(
            """
            CREATE TRIGGER prevent_load_rate_observation_update
            BEFORE UPDATE ON load_rate_observations
            BEGIN
                SELECT RAISE(ABORT, 'load_rate_observations are append-only');
            END
            """
        )
        op.execute(
            """
            CREATE TRIGGER prevent_load_rate_observation_delete
            BEFORE DELETE ON load_rate_observations
            BEGIN
                SELECT RAISE(ABORT, 'load_rate_observations are append-only');
            END
            """
        )


def _drop_append_only_triggers() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute("DROP TRIGGER prevent_load_rate_observation_mutation ON load_rate_observations")
        op.execute("DROP FUNCTION prevent_load_rate_observation_mutation()")
    elif dialect == "sqlite":
        op.execute("DROP TRIGGER prevent_load_rate_observation_update")
        op.execute("DROP TRIGGER prevent_load_rate_observation_delete")
