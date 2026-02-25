"""add assorti fallback mapping defaults for production-order

Revision ID: 0012
Revises: 0011
Create Date: 2026-02-25 16:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "article_planning_settings",
        sa.Column(
            "production_order_assorti_bundle_type_ids",
            sa.Text(),
            nullable=True,
        ),
    )
    op.add_column(
        "global_planning_settings",
        sa.Column(
            "default_production_order_assorti_bundle_type_ids",
            sa.Text(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column(
        "global_planning_settings",
        "default_production_order_assorti_bundle_type_ids",
    )
    op.drop_column(
        "article_planning_settings",
        "production_order_assorti_bundle_type_ids",
    )
