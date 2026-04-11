"""add production-order layer proxy defaults

Revision ID: 0013
Revises: 0012
Create Date: 2026-02-25 17:30:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "article_planning_settings",
        sa.Column("production_order_layer3_stockout_boost_max", sa.Float(), nullable=True),
    )
    op.add_column(
        "article_planning_settings",
        sa.Column("production_order_layer3_overstock_dampen_max", sa.Float(), nullable=True),
    )
    op.add_column(
        "article_planning_settings",
        sa.Column(
            "production_order_layer5_unavoidable_stockout_risk_threshold",
            sa.Float(),
            nullable=True,
        ),
    )
    op.add_column(
        "article_planning_settings",
        sa.Column(
            "production_order_layer5_accelerate_production_risk_threshold",
            sa.Float(),
            nullable=True,
        ),
    )

    op.add_column(
        "global_planning_settings",
        sa.Column("default_production_order_layer3_stockout_boost_max", sa.Float(), nullable=True),
    )
    op.add_column(
        "global_planning_settings",
        sa.Column("default_production_order_layer3_overstock_dampen_max", sa.Float(), nullable=True),
    )
    op.add_column(
        "global_planning_settings",
        sa.Column(
            "default_production_order_layer5_unavoidable_stockout_risk_threshold",
            sa.Float(),
            nullable=True,
        ),
    )
    op.add_column(
        "global_planning_settings",
        sa.Column(
            "default_production_order_layer5_accelerate_production_risk_threshold",
            sa.Float(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column(
        "global_planning_settings",
        "default_production_order_layer5_accelerate_production_risk_threshold",
    )
    op.drop_column(
        "global_planning_settings",
        "default_production_order_layer5_unavoidable_stockout_risk_threshold",
    )
    op.drop_column(
        "global_planning_settings",
        "default_production_order_layer3_overstock_dampen_max",
    )
    op.drop_column(
        "global_planning_settings",
        "default_production_order_layer3_stockout_boost_max",
    )

    op.drop_column(
        "article_planning_settings",
        "production_order_layer5_accelerate_production_risk_threshold",
    )
    op.drop_column(
        "article_planning_settings",
        "production_order_layer5_unavoidable_stockout_risk_threshold",
    )
    op.drop_column(
        "article_planning_settings",
        "production_order_layer3_overstock_dampen_max",
    )
    op.drop_column(
        "article_planning_settings",
        "production_order_layer3_stockout_boost_max",
    )
