"""add explicit assorti flag to bundle type

Revision ID: 0011
Revises: 0010
Create Date: 2026-02-25 15:32:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "bundle_type",
        sa.Column(
            "is_assorti",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )

    # Transitional backfill to preserve previous behavior for existing rows.
    op.execute(
        sa.text(
            """
            UPDATE bundle_type
            SET is_assorti = TRUE
            WHERE LOWER(code) LIKE '%assorti%'
               OR LOWER(name) LIKE '%assorti%'
               OR LOWER(code) LIKE '%ассорти%'
               OR LOWER(name) LIKE '%ассорти%'
            """
        )
    )

    op.alter_column("bundle_type", "is_assorti", server_default=None)


def downgrade() -> None:
    op.drop_column("bundle_type", "is_assorti")
