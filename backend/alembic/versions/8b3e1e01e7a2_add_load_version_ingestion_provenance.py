"""add load version ingestion provenance

Revision ID: 8b3e1e01e7a2
Revises: 3cd64c705778
Create Date: 2026-07-28 00:00:00

"""

import hashlib
from typing import Sequence, Union
from uuid import NAMESPACE_URL, uuid5

import sqlalchemy as sa

from alembic import op

revision: str = "8b3e1e01e7a2"
down_revision: Union[str, Sequence[str], None] = "3cd64c705778"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LEGACY_FILENAME_PREFIX = "__carrier_pool_legacy_load_version__"
LEGACY_PROVENANCE_MARKER = "carrier-pool migration 8b3e1e01e7a2 legacy provenance"


def upgrade() -> None:
    with op.batch_alter_table("ingestion_files") as batch_op:
        batch_op.create_unique_constraint(
            "uq_ingestion_files_broker_source_id_id",
            ["broker_id", "broker_source_id", "id"],
        )

    _ensure_load_source_identity_unique_constraint()

    with op.batch_alter_table("load_versions") as batch_op:
        batch_op.add_column(sa.Column("broker_source_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("ingestion_file_id", sa.String(length=36), nullable=True))

    _backfill_legacy_provenance()

    with op.batch_alter_table("load_versions") as batch_op:
        batch_op.drop_constraint("fk_load_versions_load", type_="foreignkey")
        batch_op.alter_column("broker_source_id", nullable=False)
        batch_op.alter_column("ingestion_file_id", nullable=False)
        batch_op.create_foreign_key(
            "fk_load_versions_load",
            "loads",
            ["broker_id", "broker_source_id", "load_id"],
            ["broker_id", "broker_source_id", "id"],
            ondelete="CASCADE",
        )
        batch_op.create_foreign_key(
            "fk_load_versions_ingestion_file",
            "ingestion_files",
            ["broker_id", "broker_source_id", "ingestion_file_id"],
            ["broker_id", "broker_source_id", "id"],
        )


def _ensure_load_source_identity_unique_constraint() -> None:
    """Repair databases created before the composite load constraint existed."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    expected_columns = {"broker_id", "broker_source_id", "id"}
    existing_constraints = inspector.get_unique_constraints("loads")
    if any(
        set(constraint["column_names"]) == expected_columns for constraint in existing_constraints
    ):
        return

    with op.batch_alter_table("loads") as batch_op:
        batch_op.create_unique_constraint(
            "uq_loads_broker_source_id_id",
            ["broker_id", "broker_source_id", "id"],
        )


def _backfill_legacy_provenance() -> None:
    bind = op.get_bind()
    load_versions = sa.table(
        "load_versions",
        sa.column("id", sa.String),
        sa.column("broker_id", sa.String),
        sa.column("load_id", sa.String),
        sa.column("observed_at", sa.DateTime(timezone=True)),
        sa.column("broker_source_id", sa.String),
        sa.column("ingestion_file_id", sa.String),
    )
    loads = sa.table(
        "loads",
        sa.column("id", sa.String),
        sa.column("broker_id", sa.String),
        sa.column("broker_source_id", sa.String),
    )
    ingestion_files = sa.table(
        "ingestion_files",
        sa.column("id", sa.String),
        sa.column("broker_id", sa.String),
        sa.column("broker_source_id", sa.String),
        sa.column("filename", sa.String),
        sa.column("checksum", sa.String),
        sa.column("synced_at", sa.DateTime(timezone=True)),
        sa.column("status", sa.String),
        sa.column("processed_at", sa.DateTime(timezone=True)),
        sa.column("error_message", sa.String),
    )
    orphaned_versions = bind.execute(
        sa.select(sa.func.count())
        .select_from(
            load_versions.outerjoin(
                loads,
                sa.and_(
                    load_versions.c.broker_id == loads.c.broker_id,
                    load_versions.c.load_id == loads.c.id,
                    loads.c.broker_source_id.isnot(None),
                ),
            )
        )
        .where(loads.c.id.is_(None))
    ).scalar_one()
    if orphaned_versions:
        raise RuntimeError(
            f"Cannot migrate {orphaned_versions} load_versions rows with no matching load; "
            "fix data before upgrading"
        )
    legacy_versions = (
        bind.execute(
            sa.select(
                load_versions.c.id,
                load_versions.c.broker_id,
                load_versions.c.observed_at,
                loads.c.broker_source_id,
            ).join(
                loads,
                sa.and_(
                    load_versions.c.broker_id == loads.c.broker_id,
                    load_versions.c.load_id == loads.c.id,
                    loads.c.broker_source_id.isnot(None),
                ),
            )
        )
        .mappings()
        .all()
    )

    for version in legacy_versions:
        ingestion_file_id, filename = _next_legacy_file_identity(ingestion_files, version, bind)
        checksum = hashlib.sha256(filename.encode()).hexdigest()
        bind.execute(
            sa.insert(ingestion_files).values(
                id=ingestion_file_id,
                broker_id=version["broker_id"],
                broker_source_id=version["broker_source_id"],
                filename=filename,
                checksum=checksum,
                synced_at=version["observed_at"],
                status="succeeded",
                processed_at=version["observed_at"],
                error_message=LEGACY_PROVENANCE_MARKER,
            )
        )
        bind.execute(
            sa.update(load_versions)
            .where(load_versions.c.id == version["id"])
            .values(
                broker_source_id=version["broker_source_id"],
                ingestion_file_id=ingestion_file_id,
            )
        )


def _next_legacy_file_identity(ingestion_files, version, bind):
    max_attempts = 1000
    for attempt in range(max_attempts):
        suffix = "" if attempt == 0 else f"-{attempt}"
        ingestion_file_id = str(
            uuid5(NAMESPACE_URL, f"carrier-pool:legacy:{version['id']}:{attempt}")
        )
        filename = f"{LEGACY_FILENAME_PREFIX}{version['id']}{suffix}.json"
        collision = bind.execute(
            sa.select(ingestion_files.c.id).where(
                sa.or_(
                    ingestion_files.c.id == ingestion_file_id,
                    sa.and_(
                        ingestion_files.c.broker_source_id == version["broker_source_id"],
                        ingestion_files.c.filename == filename,
                    ),
                )
            )
        ).first()
        if collision is None:
            return ingestion_file_id, filename
    raise RuntimeError(
        f"Could not generate a unique legacy file identity for "
        f"version {version['id']} after {max_attempts} attempts"
    )


def downgrade() -> None:
    with op.batch_alter_table("load_versions") as batch_op:
        batch_op.drop_constraint("fk_load_versions_ingestion_file", type_="foreignkey")
        batch_op.drop_constraint("fk_load_versions_load", type_="foreignkey")
        batch_op.drop_column("ingestion_file_id")
        batch_op.drop_column("broker_source_id")
        batch_op.create_foreign_key(
            "fk_load_versions_load",
            "loads",
            ["broker_id", "load_id"],
            ["broker_id", "id"],
            ondelete="CASCADE",
        )

    op.get_bind().execute(
        sa.text("DELETE FROM ingestion_files WHERE error_message = :legacy_provenance_marker"),
        {"legacy_provenance_marker": LEGACY_PROVENANCE_MARKER},
    )

    with op.batch_alter_table("ingestion_files") as batch_op:
        batch_op.drop_constraint("uq_ingestion_files_broker_source_id_id", type_="unique")
