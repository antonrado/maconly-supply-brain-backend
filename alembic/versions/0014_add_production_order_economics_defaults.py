"""add production-order economics defaults

Revision ID: 0014
Revises: 0013
Create Date: 2026-02-26 01:05:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "article_planning_settings",
        sa.Column("production_order_production_cost_per_unit", sa.Float(), nullable=True),
    )
    op.add_column(
        "article_planning_settings",
        sa.Column("production_order_logistics_cost_per_unit", sa.Float(), nullable=True),
    )
    op.add_column(
        "article_planning_settings",
        sa.Column("production_order_wb_commission_percent_main", sa.Float(), nullable=True),
    )
    op.add_column(
        "article_planning_settings",
        sa.Column("production_order_wb_commission_percent_assorti", sa.Float(), nullable=True),
    )
    op.add_column(
        "article_planning_settings",
        sa.Column("production_order_average_realized_price_main", sa.Float(), nullable=True),
    )
    op.add_column(
        "article_planning_settings",
        sa.Column("production_order_average_realized_price_assorti", sa.Float(), nullable=True),
    )
    op.add_column(
        "article_planning_settings",
        sa.Column("production_order_available_capital", sa.Float(), nullable=True),
    )

    op.add_column(
        "global_planning_settings",
        sa.Column("default_production_order_production_cost_per_unit", sa.Float(), nullable=True),
    )
    op.add_column(
        "global_planning_settings",
        sa.Column("default_production_order_logistics_cost_per_unit", sa.Float(), nullable=True),
    )
    op.add_column(
        "global_planning_settings",
        sa.Column("default_production_order_wb_commission_percent_main", sa.Float(), nullable=True),
    )
    op.add_column(
        "global_planning_settings",
        sa.Column("default_production_order_wb_commission_percent_assorti", sa.Float(), nullable=True),
    )
    op.add_column(
        "global_planning_settings",
        sa.Column("default_production_order_average_realized_price_main", sa.Float(), nullable=True),
    )
    op.add_column(
        "global_planning_settings",
        sa.Column("default_production_order_average_realized_price_assorti", sa.Float(), nullable=True),
    )
    op.add_column(
        "global_planning_settings",
        sa.Column("default_production_order_available_capital", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("global_planning_settings", "default_production_order_available_capital")
    op.drop_column("global_planning_settings", "default_production_order_average_realized_price_assorti")
    op.drop_column("global_planning_settings", "default_production_order_average_realized_price_main")
    op.drop_column("global_planning_settings", "default_production_order_wb_commission_percent_assorti")
    op.drop_column("global_planning_settings", "default_production_order_wb_commission_percent_main")
    op.drop_column("global_planning_settings", "default_production_order_logistics_cost_per_unit")
    op.drop_column("global_planning_settings", "default_production_order_production_cost_per_unit")

    op.drop_column("article_planning_settings", "production_order_available_capital")
    op.drop_column("article_planning_settings", "production_order_average_realized_price_assorti")
    op.drop_column("article_planning_settings", "production_order_average_realized_price_main")
    op.drop_column("article_planning_settings", "production_order_wb_commission_percent_assorti")
    op.drop_column("article_planning_settings", "production_order_wb_commission_percent_main")
    op.drop_column("article_planning_settings", "production_order_logistics_cost_per_unit")
    op.drop_column("article_planning_settings", "production_order_production_cost_per_unit")
