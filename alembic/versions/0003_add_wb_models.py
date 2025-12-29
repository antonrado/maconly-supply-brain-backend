"""add wb models (sales, stock, article mapping)

Revision ID: 0003
Revises: 0002
Create Date: 2025-11-22 00:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "wb_sales_daily",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("wb_sku", sa.Text(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("sales_qty", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("revenue", sa.Numeric(12, 2), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("wb_sku", "date", name="uq_wb_sales_daily_sku_date"),
    )

    op.create_table(
        "wb_stock",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("wb_sku", sa.Text(), nullable=False),
        sa.Column("warehouse_id", sa.Integer(), nullable=True),
        sa.Column("warehouse_name", sa.Text(), nullable=True),
        sa.Column("stock_qty", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("wb_sku", "warehouse_id", name="uq_wb_stock_sku_warehouse"),
    )

    op.create_table(
        "article_wb_mapping",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("article_id", sa.Integer(), sa.ForeignKey("article.id"), nullable=False),
        sa.Column("wb_sku", sa.Text(), nullable=False),
        sa.Column("bundle_type_id", sa.Integer(), nullable=True),
        sa.Column("color_id", sa.Integer(), nullable=True),
        sa.Column("size_id", sa.Integer(), nullable=True),
        sa.UniqueConstraint(
            "article_id",
            "wb_sku",
            name="uq_article_wb_mapping_article_sku",
        ),
    )


def downgrade() -> None:
    op.drop_table("article_wb_mapping")
    op.drop_table("wb_stock")
    op.drop_table("wb_sales_daily")
