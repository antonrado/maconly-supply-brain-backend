"""add wb shipment models

Revision ID: 0005
Revises: 0004
Create Date: 2025-11-22 00:20:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "wb_shipment",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=False),
        sa.Column("wb_arrival_date", sa.Date(), nullable=False),
        sa.Column("comment", sa.String(length=1000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("strategy", sa.String(length=50), nullable=False),
        sa.Column("zero_sales_policy", sa.String(length=50), nullable=False),
        sa.Column("target_coverage_days", sa.Integer(), nullable=False),
        sa.Column("min_coverage_days", sa.Integer(), nullable=False),
        sa.Column("max_coverage_days_after", sa.Integer(), nullable=False),
        sa.Column("max_replenishment_per_article", sa.Integer(), nullable=True),
    )

    op.create_table(
        "wb_shipment_item",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("shipment_id", sa.Integer(), sa.ForeignKey("wb_shipment.id"), nullable=False),
        sa.Column("article_id", sa.Integer(), sa.ForeignKey("article.id"), nullable=False),
        sa.Column("color_id", sa.Integer(), sa.ForeignKey("color.id"), nullable=False),
        sa.Column("size_id", sa.Integer(), sa.ForeignKey("size.id"), nullable=False),
        sa.Column("wb_sku", sa.Text(), nullable=True),
        sa.Column("recommended_qty", sa.Integer(), nullable=False),
        sa.Column("final_qty", sa.Integer(), nullable=False),
        sa.Column("nsk_stock_available", sa.Integer(), nullable=False),
        sa.Column("oos_risk_before", sa.String(length=50), nullable=False),
        sa.Column("oos_risk_after", sa.String(length=50), nullable=False),
        sa.Column("limited_by_nsk_stock", sa.Boolean(), nullable=False),
        sa.Column("limited_by_max_coverage", sa.Boolean(), nullable=False),
        sa.Column("ignored_due_to_zero_sales", sa.Boolean(), nullable=False),
        sa.Column("below_min_coverage_threshold", sa.Boolean(), nullable=False),
        sa.Column("article_total_deficit", sa.Integer(), nullable=False),
        sa.Column("article_total_recommended", sa.Integer(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("wb_shipment_item")
    op.drop_table("wb_shipment")
