from __future__ import annotations

from datetime import date

import pytest

from app.services.wb_manager import compute_manager_stats, OBSERVATION_WINDOW_DAYS
from tests.test_utils import (
    add_wb_sales,
    add_wb_stock,
    create_article,
    create_color,
    create_size,
    create_sku,
    create_wb_mapping,
)


def _create_article_with_skus(session, code: str, colors: int = 2, sizes: int = 2):
    article = create_article(session, code=code)
    color_objs = [create_color(session, inner_code=f"C-{code}-{i}") for i in range(colors)]
    size_objs = [create_size(session, label=f"SZ-{code}-{j}", sort_order=j) for j in range(sizes)]
    for c in color_objs:
        for s in size_objs:
            create_sku(session, article, c, s)
    return article


def test_compute_manager_stats_basic_case(db_session):
    target_date = date(2025, 1, 31)
    article = _create_article_with_skus(db_session, code="MGR-BASE")
    wb_sku = "SKU-MGR-BASE"
    create_wb_mapping(db_session, article, wb_sku=wb_sku)

    # Sales: 10 units on target_date and 2 previous days
    for offset in range(3):
        day = target_date.replace(day=target_date.day - offset)
        add_wb_sales(db_session, wb_sku=wb_sku, day=day, sales_qty=10)

    # Stock: two warehouses
    add_wb_stock(db_session, wb_sku=wb_sku, stock_qty=5, warehouse_id=1, warehouse_name="MSK")
    add_wb_stock(db_session, wb_sku=wb_sku, stock_qty=15, warehouse_id=2, warehouse_name="KZN")

    stats = compute_manager_stats(db_session, target_date=target_date)
    # 2 colors * 2 sizes = 4 SKUs
    assert len(stats) == 4

    s = stats[0]
    assert s.article_id == article.id
    assert s.article_code == article.code
    assert s.wb_sku == wb_sku

    assert s.observation_window_days == OBSERVATION_WINDOW_DAYS
    assert s.sales_1d == 10
    assert s.sales_7d == 30
    assert s.sales_30d == 30

    assert s.avg_daily_sales_30d == pytest.approx(30 / 30.0)
    assert s.forecast_7d == pytest.approx((30 / 30.0) * 7)
    assert s.forecast_30d == pytest.approx((30 / 30.0) * 30)

    assert s.wb_stock_total == 20
    by_wh = {(w.warehouse_id, w.warehouse_name): w.stock_qty for w in s.wb_stock_by_warehouse}
    assert by_wh[(1, "MSK")] == 5
    assert by_wh[(2, "KZN")] == 15

    assert s.coverage_days == pytest.approx(20 / (30 / 30.0))
    assert s.oos_risk_level == "green"


def test_compute_manager_stats_no_wb_mapping(db_session):
    target_date = date(2025, 1, 31)
    article = _create_article_with_skus(db_session, code="MGR-NO-MAP", colors=1, sizes=1)

    stats = compute_manager_stats(db_session, target_date=target_date, article_ids=[article.id])
    assert len(stats) == 1
    s = stats[0]

    assert s.wb_sku is None
    assert s.sales_1d == 0
    assert s.sales_7d == 0
    assert s.sales_30d == 0
    assert s.wb_stock_total == 0
    assert s.avg_daily_sales_30d == 0.0
    assert s.coverage_days == 0.0
    assert s.oos_risk_level == "green"
    assert s.explanation is not None
    assert "No WB SKU mapping" in s.explanation


def test_compute_manager_stats_zero_sales_but_stock(db_session):
    target_date = date(2025, 1, 31)
    article = _create_article_with_skus(db_session, code="MGR-STOCK-ONLY", colors=1, sizes=1)
    wb_sku = "SKU-MGR-STOCK-ONLY"
    create_wb_mapping(db_session, article, wb_sku=wb_sku)

    # Stock but no sales
    add_wb_stock(db_session, wb_sku=wb_sku, stock_qty=10, warehouse_id=1, warehouse_name="MSK")

    stats = compute_manager_stats(db_session, target_date=target_date, article_ids=[article.id])
    s = stats[0]

    assert s.sales_30d == 0
    assert s.avg_daily_sales_30d == 0.0
    assert s.wb_stock_total == 10
    assert s.coverage_days == 9999.0
    assert s.oos_risk_level == "green"


def test_compute_manager_stats_high_oos_risk_red(db_session):
    target_date = date(2025, 1, 31)
    article = _create_article_with_skus(db_session, code="MGR-RED", colors=1, sizes=1)
    wb_sku = "SKU-MGR-RED"
    create_wb_mapping(db_session, article, wb_sku=wb_sku)

    # Sales: total 30 over 30-day window -> avg_daily_sales_30d = 1.0
    for offset in range(3):
        day = target_date.replace(day=target_date.day - offset)
        add_wb_sales(db_session, wb_sku=wb_sku, day=day, sales_qty=10)

    # Very low stock to get coverage_days < 3
    add_wb_stock(db_session, wb_sku=wb_sku, stock_qty=2, warehouse_id=1, warehouse_name="MSK")

    stats = compute_manager_stats(db_session, target_date=target_date, article_ids=[article.id])
    s = stats[0]

    assert s.avg_daily_sales_30d == pytest.approx(1.0)
    assert s.coverage_days == pytest.approx(2.0)
    assert s.oos_risk_level == "red"


def test_compute_manager_stats_yellow_risk(db_session):
    target_date = date(2025, 1, 31)
    article = _create_article_with_skus(db_session, code="MGR-YELLOW", colors=1, sizes=1)
    wb_sku = "SKU-MGR-YELLOW"
    create_wb_mapping(db_session, article, wb_sku=wb_sku)

    # Sales: total 30 over 30-day window -> avg_daily_sales_30d = 1.0
    for offset in range(3):
        day = target_date.replace(day=target_date.day - offset)
        add_wb_sales(db_session, wb_sku=wb_sku, day=day, sales_qty=10)

    # Stock so that coverage_days between 3 and 7 (e.g., 5)
    add_wb_stock(db_session, wb_sku=wb_sku, stock_qty=5, warehouse_id=1, warehouse_name="MSK")

    stats = compute_manager_stats(db_session, target_date=target_date, article_ids=[article.id])
    s = stats[0]

    assert s.avg_daily_sales_30d == pytest.approx(1.0)
    assert 3.0 <= s.coverage_days <= 7.0
    assert s.oos_risk_level == "yellow"
