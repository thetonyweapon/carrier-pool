"""add shared carrier pool policy and audit records

Revision ID: b7c4e2d9f601
Revises: 9a7c2d1e4f60
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "b7c4e2d9f601"
down_revision: Union[str, Sequence[str], None] = "9a7c2d1e4f60"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "shared_pool_policies",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("broker_id", sa.String(36), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("policy_revision", sa.Integer(), nullable=False),
        sa.Column("attribute_profile", sa.String(64), nullable=False),
        sa.Column("changed_by", sa.String(255), nullable=False),
        sa.Column("reason", sa.String(1000), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("policy_revision > 0", name="ck_shared_pool_policies_revision_positive"),
        sa.ForeignKeyConstraint(
            ["broker_id"], ["brokers.id"], name="fk_shared_pool_policies_broker", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("broker_id", name="uq_shared_pool_policies_broker"),
    )
    op.create_table(
        "shared_pool_policy_events",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("broker_id", sa.String(36), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("policy_revision", sa.Integer(), nullable=False),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column("attribute_profile", sa.String(64), nullable=False),
        sa.Column("changed_by", sa.String(255), nullable=False),
        sa.Column("reason", sa.String(1000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "policy_revision > 0", name="ck_shared_pool_policy_events_revision_positive"
        ),
        sa.ForeignKeyConstraint(
            ["broker_id"],
            ["brokers.id"],
            name="fk_shared_pool_policy_events_broker",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_shared_pool_policy_events_broker_created",
        "shared_pool_policy_events",
        ["broker_id", "created_at"],
    )
    op.create_table(
        "shared_pool_query_audits",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("broker_id", sa.String(36), nullable=False),
        sa.Column("load_id", sa.String(36), nullable=False),
        sa.Column("query_type", sa.String(32), nullable=False),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column("policy_revision", sa.Integer(), nullable=False),
        sa.Column("scoring_version", sa.String(64), nullable=False),
        sa.Column("normalization_version", sa.String(64), nullable=False),
        sa.Column("participant_scope_digest", sa.String(64), nullable=False),
        sa.Column("participant_count", sa.Integer(), nullable=False),
        sa.Column("result_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "policy_revision > 0", name="ck_shared_pool_query_audits_revision_positive"
        ),
        sa.CheckConstraint(
            "participant_count >= 0", name="ck_shared_pool_query_audits_participants_nonnegative"
        ),
        sa.CheckConstraint(
            "result_count >= 0", name="ck_shared_pool_query_audits_results_nonnegative"
        ),
        sa.ForeignKeyConstraint(
            ["broker_id"],
            ["brokers.id"],
            name="fk_shared_pool_query_audits_broker",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["broker_id", "load_id"],
            ["loads.broker_id", "loads.id"],
            name="fk_shared_pool_query_audits_load",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_shared_pool_query_audits_broker_created",
        "shared_pool_query_audits",
        ["broker_id", "created_at"],
    )
    _create_append_only_triggers()


def downgrade() -> None:
    _drop_append_only_triggers()
    op.drop_index(
        "ix_shared_pool_query_audits_broker_created", table_name="shared_pool_query_audits"
    )
    op.drop_table("shared_pool_query_audits")
    op.drop_index(
        "ix_shared_pool_policy_events_broker_created", table_name="shared_pool_policy_events"
    )
    op.drop_table("shared_pool_policy_events")
    op.drop_table("shared_pool_policies")


def _create_append_only_triggers() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        for table, function in (
            ("shared_pool_policy_events", "prevent_shared_pool_policy_event_mutation"),
            ("shared_pool_query_audits", "prevent_shared_pool_query_audit_mutation"),
        ):
            op.execute(
                f"""
                CREATE FUNCTION {function}() RETURNS trigger AS $$
                BEGIN
                    RAISE EXCEPTION '{table} are append-only';
                END;
                $$ LANGUAGE plpgsql
                """
            )
            op.execute(
                f"""
                CREATE TRIGGER {function}
                BEFORE UPDATE OR DELETE ON {table}
                FOR EACH ROW EXECUTE FUNCTION {function}()
                """
            )
    elif dialect == "sqlite":
        for table, prefix in (
            ("shared_pool_policy_events", "shared_pool_policy_event"),
            ("shared_pool_query_audits", "shared_pool_query_audit"),
        ):
            op.execute(
                f"""
                CREATE TRIGGER prevent_{prefix}_update
                BEFORE UPDATE ON {table}
                BEGIN
                    SELECT RAISE(ABORT, '{table} are append-only');
                END
                """
            )
            op.execute(
                f"""
                CREATE TRIGGER prevent_{prefix}_delete
                BEFORE DELETE ON {table}
                BEGIN
                    SELECT RAISE(ABORT, '{table} are append-only');
                END
                """
            )


def _drop_append_only_triggers() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        for table, function in (
            (
                "shared_pool_policy_events",
                "prevent_shared_pool_policy_event_mutation",
            ),
            (
                "shared_pool_query_audits",
                "prevent_shared_pool_query_audit_mutation",
            ),
        ):
            op.execute(f"DROP TRIGGER {function} ON {table}")
            op.execute(f"DROP FUNCTION {function}()")
    elif dialect == "sqlite":
        for trigger in (
            "prevent_shared_pool_policy_event_update",
            "prevent_shared_pool_policy_event_delete",
            "prevent_shared_pool_query_audit_update",
            "prevent_shared_pool_query_audit_delete",
        ):
            op.execute(f"DROP TRIGGER {trigger}")
