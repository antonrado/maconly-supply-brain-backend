from __future__ import annotations

from collections import defaultdict
from datetime import date

import pytest

from app.schemas.order_proposal import OrderProposalResponse
from app.services.order_proposal import generate_order_proposal
from tests.test_utils import (
    add_wb_sales,
    add_wb_stock,
    create_article,
    create_article_planning_settings,
    create_color,
    create_color_planning_settings,
    create_elastic_planning_settings,
    create_global_planning_settings,
    create_planning_settings,
    create_size,
    create_sku,
    create_wb_mapping,
)


def _sum_by_article(items):
    total = defaultdict(int)
    for it in items:
        total[it.article_id] += it.quantity
    return total


def _sum_by_color(items):
    total = defaultdict(int)
    for it in items:
        total[(it.article_id, it.color_id)] += it.quantity
    return total


def _sum_by_color_and_size(items):
    total = defaultdict(int)
    for it in items:
        total[(it.article_id, it.color_id, it.size_id)] += it.quantity
    return total


class TestOrderProposal:
    def test_scenario_a_no_minima(self, db_session):
        """Scenario A: no minima, order is evenly distributed across all SKUs."""
        article = create_article(db_session, code="A-no-min")

        # Sizes and colors: 3 colors x 2 sizes = 6 SKUs
        size_s = create_size(db_session, label="S", sort_order=1)
        size_m = create_size(db_session, label="M", sort_order=2)

        colors = [
            create_color(db_session, inner_code="C1"),
            create_color(db_session, inner_code="C2"),
            create_color(db_session, inner_code="C3"),
        ]

        skus = []
        for color in colors:
            skus.append(create_sku(db_session, article, color, size_s))
            skus.append(create_sku(db_session, article, color, size_m))

        # Planning settings
        create_global_planning_settings(db_session)
        create_article_planning_settings(db_session, article, target_coverage_days=10)
        create_planning_settings(
            db_session,
            article,
            is_active=True,
            min_fabric_batch=0,
            min_elastic_batch=0,
            strictness=1.0,
        )

        # WB mapping & sales: 1 SKU, 1 day, 18 units -> deficit 180
        wb_sku = "SKU-A-no-min"
        create_wb_mapping(db_session, article, wb_sku=wb_sku)
        target_date = date(2025, 1, 31)
        add_wb_sales(db_session, wb_sku=wb_sku, day=target_date, sales_qty=18)
        add_wb_stock(db_session, wb_sku=wb_sku, stock_qty=0)

        resp: OrderProposalResponse = generate_order_proposal(
            db_session,
            target_date=target_date,
            explanation=True,
        )

        article_totals = _sum_by_article(resp.items)
        assert article_totals[article.id] == 180

        # Quantities for each SKU should be equal or differ by at most 1
        sku_qty = _sum_by_color_and_size(resp.items)
        quantities = [qty for (a_id, _c_id, _s_id), qty in sku_qty.items() if a_id == article.id]
        assert len(quantities) == len(skus)
        assert max(quantities) - min(quantities) <= 1

        assert resp.global_explanation is not None
        assert "Color minima applied" not in resp.global_explanation
        assert "Elastic minima applied" not in resp.global_explanation

    def test_scenario_b_color_minimum(self, db_session):
        """Scenario B: color-level fabric minima increases total for one color."""
        article = create_article(db_session, code="A-color-min")

        size_s = create_size(db_session, label="S", sort_order=1)
        size_m = create_size(db_session, label="M", sort_order=2)

        color_a = create_color(db_session, inner_code="CA")
        color_b = create_color(db_session, inner_code="CB")
        color_c = create_color(db_session, inner_code="CC")
        colors = [color_a, color_b, color_c]

        for color in colors:
            create_sku(db_session, article, color, size_s)
            create_sku(db_session, article, color, size_m)

        create_global_planning_settings(db_session)
        create_article_planning_settings(db_session, article, target_coverage_days=10)
        create_planning_settings(
            db_session,
            article,
            is_active=True,
            min_fabric_batch=0,
            min_elastic_batch=0,
            strictness=1.0,
        )

        # Color minima: color A must reach at least 200 units
        create_color_planning_settings(
            db_session,
            article=article,
            color=color_a,
            fabric_min_batch_qty=200,
        )

        wb_sku = "SKU-A-color-min"
        create_wb_mapping(db_session, article, wb_sku=wb_sku)
        target_date = date(2025, 1, 31)
        add_wb_sales(db_session, wb_sku=wb_sku, day=target_date, sales_qty=18)
        add_wb_stock(db_session, wb_sku=wb_sku, stock_qty=0)

        resp = generate_order_proposal(db_session, target_date=target_date, explanation=True)

        article_totals = _sum_by_article(resp.items)
        total_for_article = article_totals[article.id]
        assert total_for_article >= 180
        assert total_for_article >= 200

        by_color = _sum_by_color(resp.items)
        assert by_color[(article.id, color_a.id)] >= 200

        assert "Color minima applied" in (resp.global_explanation or "")
        assert f"color_id={color_a.id}" in (resp.global_explanation or "")

    def test_scenario_c_elastic_minimum(self, db_session):
        """Scenario C: elastic minimum raises total order above WB deficit."""
        article = create_article(db_session, code="A-elastic-min")

        size_s = create_size(db_session, label="S", sort_order=1)
        size_m = create_size(db_session, label="M", sort_order=2)

        color_a = create_color(db_session, inner_code="EA")
        color_b = create_color(db_session, inner_code="EB")
        color_c = create_color(db_session, inner_code="EC")
        colors = [color_a, color_b, color_c]

        for color in colors:
            create_sku(db_session, article, color, size_s)
            create_sku(db_session, article, color, size_m)

        create_global_planning_settings(db_session)
        create_article_planning_settings(db_session, article, target_coverage_days=20)
        create_planning_settings(
            db_session,
            article,
            is_active=True,
            min_fabric_batch=0,
            min_elastic_batch=0,
            strictness=1.0,
        )

        # Elastic minima: 500 units for the article
        create_elastic_planning_settings(db_session, article=article, elastic_min_batch_qty=500)

        # WB deficit: 300 (avg_daily_sales=15, coverage 20)
        wb_sku = "SKU-A-elastic-min"
        create_wb_mapping(db_session, article, wb_sku=wb_sku)
        target_date = date(2025, 1, 31)
        add_wb_sales(db_session, wb_sku=wb_sku, day=target_date, sales_qty=15)
        add_wb_stock(db_session, wb_sku=wb_sku, stock_qty=0)

        resp = generate_order_proposal(db_session, target_date=target_date, explanation=True)

        article_totals = _sum_by_article(resp.items)
        total_for_article = article_totals[article.id]

        # Total must be at least elastic_min_batch_qty
        assert total_for_article >= 500

        assert "Elastic minima applied" in (resp.global_explanation or "")
        assert "elastic_min_batch_qty=500" in (resp.global_explanation or "")

    def test_scenario_d_complex(self, db_session):
        """Scenario D: combined article, color and elastic minima with size ordering."""
        article = create_article(db_session, code="A-complex")

        # Sizes S < M < L
        size_s = create_size(db_session, label="S", sort_order=1)
        size_m = create_size(db_session, label="M", sort_order=2)
        size_l = create_size(db_session, label="L", sort_order=3)

        color_a = create_color(db_session, inner_code="CA")
        color_b = create_color(db_session, inner_code="CB")
        color_c = create_color(db_session, inner_code="CC")
        colors = [color_a, color_b, color_c]
        sizes = [size_s, size_m, size_l]

        for color in colors:
            for size in sizes:
                create_sku(db_session, article, color, size)

        # Planning
        create_global_planning_settings(db_session, default_target_coverage_days=60)
        create_article_planning_settings(db_session, article, target_coverage_days=10)
        create_planning_settings(
            db_session,
            article,
            is_active=True,
            min_fabric_batch=250,
            min_elastic_batch=300,
            strictness=1.2,
        )

        # Color minima: color A high, B low/zero, C none
        create_color_planning_settings(db_session, article, color_a, fabric_min_batch_qty=220)

        # Elastic minima: must bind after color minima
        create_elastic_planning_settings(db_session, article, elastic_min_batch_qty=600)

        # WB deficit: 200 (avg_daily_sales=20, horizon=10)
        wb_sku = "SKU-A-complex"
        create_wb_mapping(db_session, article, wb_sku=wb_sku)
        target_date = date(2025, 1, 31)
        add_wb_sales(db_session, wb_sku=wb_sku, day=target_date, sales_qty=20)
        add_wb_stock(db_session, wb_sku=wb_sku, stock_qty=0)

        resp = generate_order_proposal(db_session, target_date=target_date, explanation=True)

        # Totals per article and color
        article_totals = _sum_by_article(resp.items)
        by_color = _sum_by_color(resp.items)

        total_article = article_totals[article.id]

        # Should respect all minima and WB deficit * strictness
        assert total_article >= 600  # elastic_min_batch
        assert total_article >= 300  # article min elastic
        assert total_article >= int(200 * 1.2)  # deficit * strictness

        assert by_color[(article.id, color_a.id)] >= 220

        # Distribution inside each color: near-uniform over sizes, S>=M>=L and diff <= 1
        qty_map = _sum_by_color_and_size(resp.items)
        for color in colors:
            q_s = qty_map.get((article.id, color.id, size_s.id), 0)
            q_m = qty_map.get((article.id, color.id, size_m.id), 0)
            q_l = qty_map.get((article.id, color.id, size_l.id), 0)
            quantities = [q_s, q_m, q_l]
            if sum(quantities) == 0:
                continue
            assert max(quantities) - min(quantities) <= 1
            assert q_s >= q_m >= q_l

        ge = resp.global_explanation or ""
        assert "WB demand -> avg_daily_sales" in ge
        assert "Color minima applied" in ge
        assert "Elastic minima applied" in ge
