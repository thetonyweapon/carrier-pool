"""add broker-scoped carrier identities

Revision ID: 1b4c4f0a2d91
Revises: 8b3e1e01e7a2
Create Date: 2026-07-29 00:00:00

"""

import re
from typing import Optional, Sequence, Union
from uuid import NAMESPACE_URL, uuid5

import sqlalchemy as sa

from alembic import op

revision: str = "1b4c4f0a2d91"
down_revision: Union[str, Sequence[str], None] = "8b3e1e01e7a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "carrier_identities",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("broker_id", sa.String(length=36), nullable=False),
        sa.Column("normalized_mc_number", sa.String(length=32), nullable=True),
        sa.Column("normalized_dot_number", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["broker_id"], ["brokers.id"], name="fk_carrier_identities_broker", ondelete="CASCADE"
        ),
        sa.CheckConstraint(
            "normalized_mc_number IS NOT NULL OR normalized_dot_number IS NOT NULL",
            name="ck_carrier_identities_has_identifier",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("broker_id", "id", name="uq_carrier_identities_broker_id"),
        sa.UniqueConstraint("broker_id", "normalized_mc_number", name="uq_carrier_identities_mc"),
        sa.UniqueConstraint("broker_id", "normalized_dot_number", name="uq_carrier_identities_dot"),
    )
    with op.batch_alter_table("carriers") as batch_op:
        batch_op.add_column(sa.Column("carrier_identity_id", sa.String(length=36), nullable=True))

    _backfill_carrier_identities()

    with op.batch_alter_table("carriers") as batch_op:
        batch_op.create_foreign_key(
            "fk_carriers_identity",
            "carrier_identities",
            ["broker_id", "carrier_identity_id"],
            ["broker_id", "id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("carriers") as batch_op:
        batch_op.drop_constraint("fk_carriers_identity", type_="foreignkey")
        batch_op.drop_column("carrier_identity_id")
    op.drop_table("carrier_identities")


def _normalize(value: Optional[str], prefix: str) -> Optional[str]:
    if value is None:
        return None
    normalized = re.sub(r"[\s-]", "", str(value)).upper()
    if normalized.startswith(prefix):
        normalized = normalized[len(prefix) :]
    if not normalized.isdigit():
        return None
    normalized = normalized.lstrip("0")
    return normalized or None


def _backfill_carrier_identities() -> None:
    connection = op.get_bind()
    carriers = connection.execute(
        sa.text(
            """
            SELECT id, broker_id, mc_number, dot_number
            FROM carriers
            ORDER BY broker_id, id
            """
        )
    ).mappings()
    identities = {}
    for carrier in carriers:
        mc = _normalize(carrier["mc_number"], "MC")
        dot = _normalize(carrier["dot_number"], "DOT")
        if mc is None and dot is None:
            continue
        matches = []
        if mc is not None:
            match = identities.get((carrier["broker_id"], "mc", mc))
            if match is not None:
                matches.append(match)
        if dot is not None:
            match = identities.get((carrier["broker_id"], "dot", dot))
            if match is not None and match not in matches:
                matches.append(match)
        if len(matches) > 1:
            raise RuntimeError(
                f"Carrier identity conflict during migration for carrier {carrier['id']}"
            )
        if matches:
            identity = matches[0]
            if identity["mc"] not in (None, mc) or identity["dot"] not in (None, dot):
                raise RuntimeError(
                    f"Carrier identity conflict during migration for carrier {carrier['id']}"
                )
            if identity["mc"] is None and mc is not None:
                identity["mc"] = mc
                connection.execute(
                    sa.text(
                        "UPDATE carrier_identities SET normalized_mc_number = :value WHERE id = :id"
                    ),
                    {"value": mc, "id": identity["id"]},
                )
                identities[(carrier["broker_id"], "mc", mc)] = identity
            if identity["dot"] is None and dot is not None:
                identity["dot"] = dot
                connection.execute(
                    sa.text(
                        "UPDATE carrier_identities SET normalized_dot_number = :value "
                        "WHERE id = :id"
                    ),
                    {"value": dot, "id": identity["id"]},
                )
                identities[(carrier["broker_id"], "dot", dot)] = identity
        else:
            identity = {
                "id": str(
                    uuid5(
                        NAMESPACE_URL,
                        f"carrier-pool:carrier-identity:{carrier['broker_id']}:{mc}:{dot}",
                    )
                ),
                "broker_id": carrier["broker_id"],
                "mc": mc,
                "dot": dot,
            }
            connection.execute(
                sa.text(
                    """
                    INSERT INTO carrier_identities (
                        id, broker_id, normalized_mc_number, normalized_dot_number,
                        created_at, updated_at
                    ) VALUES (
                        :id, :broker_id, :mc, :dot, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                    )
                    """
                ),
                {"id": identity["id"], "broker_id": identity["broker_id"], "mc": mc, "dot": dot},
            )
        if mc is not None:
            identities[(carrier["broker_id"], "mc", mc)] = identity
        if dot is not None:
            identities[(carrier["broker_id"], "dot", dot)] = identity
        connection.execute(
            sa.text(
                "UPDATE carriers SET carrier_identity_id = :identity_id WHERE id = :carrier_id"
            ),
            {"identity_id": identity["id"], "carrier_id": carrier["id"]},
        )
