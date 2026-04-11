"""add production-order freshness defaults to article settings

Revision ID: 0010
Revises: 0009
Create Date: 2026-02-25 02:35:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "article_planning_settings",
        sa.Column(
            "production_order_freshness_sales_stale_after_days",
            sa.Integer(),
            nullable=True,
        ),
    )
    op.add_column(
        "article_planning_settings",
        sa.Column(
            "production_order_freshness_stock_stale_after_days",
            sa.Integer(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column(
        "article_planning_settings",
        "production_order_freshness_stock_stale_after_days",
    )
    op.drop_column(
        "article_planning_settings",
        "production_order_freshness_sales_stale_after_days",
    )
