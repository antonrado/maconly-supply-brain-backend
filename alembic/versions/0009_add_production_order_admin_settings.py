"""add production-order admin settings tables

Revision ID: 0009
Revises: 0008
Create Date: 2026-02-24 22:35:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "production_order_size_weight_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "article_id",
            sa.Integer(),
            sa.ForeignKey("article.id"),
            nullable=False,
        ),
        sa.Column(
            "size_id",
            sa.Integer(),
            sa.ForeignKey("size.id"),
            nullable=False,
        ),
        sa.Column(
            "weight",
            sa.Float(),
            nullable=False,
            server_default=sa.text("1.0"),
        ),
        sa.UniqueConstraint(
            "article_id",
            "size_id",
            name="uq_po_size_weight_article_size",
        ),
    )

    op.create_table(
        "production_order_elastic_bindings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "article_id",
            sa.Integer(),
            sa.ForeignKey("article.id"),
            nullable=False,
        ),
        sa.Column(
            "elastic_type_id",
            sa.Integer(),
            sa.ForeignKey("elastic_type.id"),
            nullable=False,
        ),
        sa.Column(
            "color_id",
            sa.Integer(),
            sa.ForeignKey("color.id"),
            nullable=True,
        ),
        sa.Column(
            "sku_unit_id",
            sa.Integer(),
            sa.ForeignKey("sku_unit.id"),
            nullable=True,
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.UniqueConstraint(
            "article_id",
            "elastic_type_id",
            "color_id",
            "sku_unit_id",
            name="uq_po_elastic_binding_scope",
        ),
    )

    op.create_table(
        "production_order_in_flight_defaults",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "article_id",
            sa.Integer(),
            sa.ForeignKey("article.id"),
            nullable=False,
        ),
        sa.Column(
            "color_id",
            sa.Integer(),
            sa.ForeignKey("color.id"),
            nullable=False,
        ),
        sa.Column(
            "size_id",
            sa.Integer(),
            sa.ForeignKey("size.id"),
            nullable=False,
        ),
        sa.Column(
            "qty",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "eta_days",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "stage",
            sa.String(length=50),
            nullable=False,
            server_default=sa.text("'other'"),
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.UniqueConstraint(
            "article_id",
            "color_id",
            "size_id",
            "stage",
            "eta_days",
            name="uq_po_in_flight_default_scope",
        ),
    )


def downgrade() -> None:
    op.drop_table("production_order_in_flight_defaults")
    op.drop_table("production_order_elastic_bindings")
    op.drop_table("production_order_size_weight_settings")
