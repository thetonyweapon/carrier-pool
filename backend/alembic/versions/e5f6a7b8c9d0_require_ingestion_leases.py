"""require fencing data for processing ingestion jobs

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE ingestion_jobs
            SET status = 'retry_wait',
                lease_owner = NULL,
                lease_token = NULL,
                lease_expires_at = NULL
            WHERE status = 'processing'
              AND (lease_token IS NULL OR lease_expires_at IS NULL)
            """
        )
    )
    with op.batch_alter_table("ingestion_jobs", recreate="always") as batch_op:
        batch_op.create_check_constraint(
            "ck_ingestion_jobs_processing_lease_required",
            "status != 'processing' OR (lease_token IS NOT NULL AND lease_expires_at IS NOT NULL)",
        )


def downgrade() -> None:
    with op.batch_alter_table("ingestion_jobs", recreate="always") as batch_op:
        batch_op.drop_constraint("ck_ingestion_jobs_processing_lease_required", type_="check")
