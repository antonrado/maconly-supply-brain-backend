"""add core models

Revision ID: 0001
Revises: None
Create Date: 2025-11-21 00:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "article",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(length=50), nullable=False, unique=True),
        sa.Column("name", sa.String(length=255), nullable=True),
    )

    op.create_table(
        "color",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("pantone_code", sa.String(length=50), nullable=True),
        sa.Column("inner_code", sa.String(length=50), nullable=False, unique=True),
        sa.Column("description", sa.String(length=255), nullable=True),
    )

    op.create_table(
        "size",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("label", sa.String(length=50), nullable=False, unique=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )

    op.create_table(
        "bundle_type",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(length=50), nullable=False, unique=True),
        sa.Column("name", sa.String(length=100), nullable=False),
    )

    op.create_table(
        "warehouse",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(length=50), nullable=False, unique=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("type", sa.String(length=50), nullable=False),
    )

    op.create_table(
        "sku_unit",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("article_id", sa.Integer(), sa.ForeignKey("article.id"), nullable=False),
        sa.Column("color_id", sa.Integer(), sa.ForeignKey("color.id"), nullable=False),
        sa.Column("size_id", sa.Integer(), sa.ForeignKey("size.id"), nullable=False),
        sa.UniqueConstraint(
            "article_id",
            "color_id",
            "size_id",
            name="uq_sku_unit_article_color_size",
        ),
    )

    op.create_table(
        "bundle_recipe",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("article_id", sa.Integer(), sa.ForeignKey("article.id"), nullable=False),
        sa.Column("bundle_type_id", sa.Integer(), sa.ForeignKey("bundle_type.id"), nullable=False),
        sa.Column("color_id", sa.Integer(), sa.ForeignKey("color.id"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.UniqueConstraint(
            "article_id",
            "bundle_type_id",
            "color_id",
            name="uq_bundle_recipe_article_bundle_color",
        ),
        sa.UniqueConstraint(
            "article_id",
            "bundle_type_id",
            "position",
            name="uq_bundle_recipe_article_bundle_position",
        ),
    )

    op.create_table(
        "stock_balance",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sku_unit_id", sa.Integer(), sa.ForeignKey("sku_unit.id"), nullable=False),
        sa.Column("warehouse_id", sa.Integer(), sa.ForeignKey("warehouse.id"), nullable=False),
        sa.Column(
            "quantity",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "sku_unit_id",
            "warehouse_id",
            name="uq_stock_balance_sku_warehouse",
        ),
    )


def downgrade() -> None:
    op.drop_table("stock_balance")
    op.drop_table("bundle_recipe")
    op.drop_table("sku_unit")
    op.drop_table("warehouse")
    op.drop_table("bundle_type")
    op.drop_table("size")
    op.drop_table("color")
    op.drop_table("article")
