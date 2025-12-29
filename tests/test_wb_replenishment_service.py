from __future__ import annotations

from datetime import date

import pytest

from app.services.wb_replenishment import compute_replenishment
from app.services.wb_manager import OBSERVATION_WINDOW_DAYS
from tests.test_utils import (
    add_wb_sales,
    add_wb_stock,
    create_article,
    create_color,
    create_size,
    create_sku,
    create_wb_mapping,
)
from app.models.models import StockBalance, Warehouse, SkuUnit


def _create_basic_article_with_stock(db_session, code: str):
    article = create_article(db_session, code=code)
    color = create_color(db_session, inner_code=f"C-{code}")
    size = create_size(db_session, label=f"SZ-{code}", sort_order=1)
    sku = create_sku(db_session, article, color, size)
    return article, sku


def _add_nsk_stock(db_session, sku: SkuUnit, qty: int):
    wh = Warehouse(code="NSK", name="NSK", type="internal")
    db_session.add(wh)
    db_session.flush()
    sb = StockBalance(sku_unit_id=sku.id, warehouse_id=wh.id, quantity=qty)
    from datetime import datetime, timezone

    sb.updated_at = datetime.now(timezone.utc)
    db_session.add(sb)
    db_session.flush()


def test_replenishment_basic_normal_strategy(db_session):
    from app.schemas.wb_replenishment import WbReplenishmentRequest

    target_date = date(2025, 1, 31)
    article, sku = _create_basic_article_with_stock(db_session, code="REPL-NORMAL")
    wb_sku = "SKU-REPL-NORMAL"
    create_wb_mapping(db_session, article, wb_sku=wb_sku)

    # WB: 30 units sold over 3 days, 10 units in stock
    for offset in range(3):
        day = target_date.replace(day=target_date.day - offset)
        add_wb_sales(db_session, wb_sku=wb_sku, day=day, sales_qty=10)
    add_wb_stock(db_session, wb_sku=wb_sku, stock_qty=10, warehouse_id=1, warehouse_name="MSK")

    # NSK: 100 units available
    _add_nsk_stock(db_session, sku, qty=100)

    payload = WbReplenishmentRequest(
        target_date=target_date,
        wb_arrival_date=target_date,
        target_coverage_days=30,
        replenishment_strategy="normal",
    )

    items = compute_replenishment(db_session, payload)
    assert items
    item = items[0]

    assert item.recommended_qty > 0
    assert item.coverage_after_transfer > item.coverage_days_current
    assert not item.limited_by_nsk_stock
    assert not item.limited_by_max_coverage


def test_replenishment_strategies_compare(db_session):
    from app.schemas.wb_replenishment import WbReplenishmentRequest

    target_date = date(2025, 1, 31)
    article, sku = _create_basic_article_with_stock(db_session, code="REPL-STRAT")
    wb_sku = "SKU-REPL-STRAT"
    create_wb_mapping(db_session, article, wb_sku=wb_sku)

    for offset in range(3):
        day = target_date.replace(day=target_date.day - offset)
        add_wb_sales(db_session, wb_sku=wb_sku, day=day, sales_qty=10)
    add_wb_stock(db_session, wb_sku=wb_sku, stock_qty=10, warehouse_id=1, warehouse_name="MSK")
    _add_nsk_stock(db_session, sku, qty=1000)

    aggressive = compute_replenishment(
        db_session,
        WbReplenishmentRequest(
            target_date=target_date,
            wb_arrival_date=target_date,
            target_coverage_days=30,
            replenishment_strategy="aggressive",
        ),
    )[0].recommended_qty

    normal = compute_replenishment(
        db_session,
        WbReplenishmentRequest(
            target_date=target_date,
            wb_arrival_date=target_date,
            target_coverage_days=30,
            replenishment_strategy="normal",
        ),
    )[0].recommended_qty

    conservative = compute_replenishment(
        db_session,
        WbReplenishmentRequest(
            target_date=target_date,
            wb_arrival_date=target_date,
            target_coverage_days=30,
            replenishment_strategy="conservative",
        ),
    )[0].recommended_qty

    assert aggressive >= normal >= conservative


def test_replenishment_limited_by_nsk_stock(db_session):
    from app.schemas.wb_replenishment import WbReplenishmentRequest

    target_date = date(2025, 1, 31)
    article, sku = _create_basic_article_with_stock(db_session, code="REPL-NSK")
    wb_sku = "SKU-REPL-NSK"
    create_wb_mapping(db_session, article, wb_sku=wb_sku)

    for offset in range(3):
        day = target_date.replace(day=target_date.day - offset)
        add_wb_sales(db_session, wb_sku=wb_sku, day=day, sales_qty=50)
    add_wb_stock(db_session, wb_sku=wb_sku, stock_qty=0, warehouse_id=1, warehouse_name="MSK")

    _add_nsk_stock(db_session, sku, qty=10)

    payload = WbReplenishmentRequest(
        target_date=target_date,
        wb_arrival_date=target_date,
        target_coverage_days=60,
        replenishment_strategy="aggressive",
    )

    item = compute_replenishment(db_session, payload)[0]
    assert item.recommended_qty == 10
    assert item.limited_by_nsk_stock


def test_replenishment_limited_by_max_coverage(db_session):
    from app.schemas.wb_replenishment import WbReplenishmentRequest

    target_date = date(2025, 1, 31)
    article, sku = _create_basic_article_with_stock(db_session, code="REPL-COVER")
    wb_sku = "SKU-REPL-COVER"
    create_wb_mapping(db_session, article, wb_sku=wb_sku)

    # Stable sales, huge NSK stock, low WB stock
    for offset in range(3):
        day = target_date.replace(day=target_date.day - offset)
        add_wb_sales(db_session, wb_sku=wb_sku, day=day, sales_qty=10)
    add_wb_stock(db_session, wb_sku=wb_sku, stock_qty=0, warehouse_id=1, warehouse_name="MSK")
    _add_nsk_stock(db_session, sku, qty=10000)

    payload = WbReplenishmentRequest(
        target_date=target_date,
        wb_arrival_date=target_date,
        target_coverage_days=120,
        max_coverage_days_after=30,
        replenishment_strategy="aggressive",
    )

    item = compute_replenishment(db_session, payload)[0]
    assert item.coverage_after_transfer <= pytest.approx(30, rel=0.1)
    assert item.limited_by_max_coverage


def test_zero_sales_policy_variants(db_session):
    from app.schemas.wb_replenishment import WbReplenishmentRequest

    target_date = date(2025, 1, 31)
    article, sku = _create_basic_article_with_stock(db_session, code="REPL-ZERO")
    wb_sku = "SKU-REPL-ZERO"
    create_wb_mapping(db_session, article, wb_sku=wb_sku)

    # No sales, some stock on WB and NSK
    add_wb_stock(db_session, wb_sku=wb_sku, stock_qty=10, warehouse_id=1, warehouse_name="MSK")
    _add_nsk_stock(db_session, sku, qty=100)

    ignore_item = compute_replenishment(
        db_session,
        WbReplenishmentRequest(
            target_date=target_date,
            wb_arrival_date=target_date,
            zero_sales_policy="ignore",
        ),
    )[0]
    assert ignore_item.recommended_qty == 0
    assert ignore_item.ignored_due_to_zero_sales

    keep_item = compute_replenishment(
        db_session,
        WbReplenishmentRequest(
            target_date=target_date,
            wb_arrival_date=target_date,
            zero_sales_policy="keep",
        ),
    )[0]
    assert keep_item.recommended_qty == 0
    assert not keep_item.ignored_due_to_zero_sales


def test_min_coverage_flag(db_session):
    from app.schemas.wb_replenishment import WbReplenishmentRequest

    target_date = date(2025, 1, 31)
    article, sku = _create_basic_article_with_stock(db_session, code="REPL-MIN-COV")
    wb_sku = "SKU-REPL-MIN-COV"
    create_wb_mapping(db_session, article, wb_sku=wb_sku)

    # No stock on WB, some sales to make coverage low
    add_wb_sales(db_session, wb_sku=wb_sku, day=target_date, sales_qty=10)
    _add_nsk_stock(db_session, sku, qty=100)

    payload = WbReplenishmentRequest(
        target_date=target_date,
        wb_arrival_date=target_date,
        min_coverage_days=5,
    )
    item = compute_replenishment(db_session, payload)[0]
    assert item.below_min_coverage_threshold
