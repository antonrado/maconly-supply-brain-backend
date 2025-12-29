"""add purchase order models

Revision ID: 0004
Revises: 0003
Create Date: 2025-11-22 00:10:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "purchase_order",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=False),
        sa.Column("comment", sa.String(length=1000), nullable=True),
        sa.Column("external_ref", sa.String(length=255), nullable=True),
    )

    op.create_table(
        "purchase_order_item",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("purchase_order_id", sa.Integer(), sa.ForeignKey("purchase_order.id"), nullable=False),
        sa.Column("article_id", sa.Integer(), sa.ForeignKey("article.id"), nullable=False),
        sa.Column("color_id", sa.Integer(), sa.ForeignKey("color.id"), nullable=False),
        sa.Column("size_id", sa.Integer(), sa.ForeignKey("size.id"), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False, server_default="auto"),
        sa.Column("notes", sa.String(length=1000), nullable=True),
        sa.UniqueConstraint(
            "purchase_order_id",
            "article_id",
            "color_id",
            "size_id",
            name="uq_po_item_po_article_color_size",
        ),
    )


def downgrade() -> None:
    op.drop_table("purchase_order_item")
    op.drop_table("purchase_order")
