"""add planning settings models

Revision ID: 0002
Revises: 0001
Create Date: 2025-11-22 00:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "article_planning_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "article_id",
            sa.Integer(),
            sa.ForeignKey("article.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "include_in_planning",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "priority",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("target_coverage_days", sa.Integer(), nullable=True),
        sa.Column("lead_time_days", sa.Integer(), nullable=True),
        sa.Column("service_level_percent", sa.Integer(), nullable=True),
    )

    op.create_table(
        "color_planning_settings",
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
        sa.Column("fabric_min_batch_qty", sa.Integer(), nullable=True),
        sa.UniqueConstraint(
            "article_id",
            "color_id",
            name="uq_color_planning_article_color",
        ),
    )

    op.create_table(
        "elastic_type",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(length=50), nullable=False, unique=True),
        sa.Column("name", sa.String(length=255), nullable=False),
    )

    op.create_table(
        "elastic_planning_settings",
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
        sa.Column("elastic_min_batch_qty", sa.Integer(), nullable=True),
        sa.UniqueConstraint(
            "article_id",
            "elastic_type_id",
            name="uq_elastic_planning_article_type",
        ),
    )

    op.create_table(
        "global_planning_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "default_target_coverage_days",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("60"),
        ),
        sa.Column(
            "default_lead_time_days",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("70"),
        ),
        sa.Column(
            "default_service_level_percent",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("90"),
        ),
        sa.Column(
            "default_fabric_min_batch_qty",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("7000"),
        ),
        sa.Column(
            "default_elastic_min_batch_qty",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("3000"),
        ),
    )

    op.create_table(
        "planning_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "article_id",
            sa.Integer(),
            sa.ForeignKey("article.id"),
            nullable=False,
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("min_fabric_batch", sa.Integer(), nullable=False),
        sa.Column("min_elastic_batch", sa.Integer(), nullable=False),
        sa.Column("alert_threshold_days", sa.Integer(), nullable=False),
        sa.Column("safety_stock_days", sa.Integer(), nullable=False),
        sa.Column("strictness", sa.Float(), nullable=False),
        sa.Column("notes", sa.String(length=500), nullable=True),
        sa.UniqueConstraint("article_id", name="uq_planning_settings_article"),
    )


def downgrade() -> None:
    op.drop_table("planning_settings")
    op.drop_table("global_planning_settings")
    op.drop_table("elastic_planning_settings")
    op.drop_table("elastic_type")
    op.drop_table("color_planning_settings")
    op.drop_table("article_planning_settings")
