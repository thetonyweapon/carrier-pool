"""add durable ingestion jobs

Revision ID: c8d5e3f7a102
Revises: b7c4e2d9f601
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c8d5e3f7a102"
down_revision: Union[str, None] = "b7c4e2d9f601"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ingestion_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("broker_id", sa.String(length=36), nullable=False),
        sa.Column("broker_source_id", sa.String(length=36), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("file_path", sa.String(length=2048), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "queued",
                "processing",
                "succeeded",
                "retry_wait",
                "dead_letter",
                name="ingestion_job_status",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_owner", sa.String(length=255), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_class", sa.String(length=255), nullable=True),
        sa.Column("error_message", sa.String(length=2000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["broker_id", "broker_source_id"],
            ["broker_sources.broker_id", "broker_sources.id"],
            name="fk_ingestion_jobs_source",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("attempt_count >= 0", name="ck_ingestion_jobs_attempt_nonnegative"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "broker_source_id", "filename", name="uq_ingestion_jobs_source_filename"
        ),
    )
    op.create_index(
        "ix_ingestion_jobs_status_available",
        "ingestion_jobs",
        ["status", "available_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_ingestion_jobs_status_available", table_name="ingestion_jobs")
    op.drop_table("ingestion_jobs")
