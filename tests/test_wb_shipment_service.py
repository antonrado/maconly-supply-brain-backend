from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.models.models import (
    WbShipment,
    WbShipmentItem,
    Warehouse,
    StockBalance,
)
from app.schemas.wb_shipment import WbShipmentCreate
from app.schemas.wb_replenishment import WbReplenishmentRequest
from app.services.wb_replenishment import compute_replenishment
from app.services.wb_shipment import create_wb_shipment_from_proposal
from tests.test_utils import (
    add_wb_sales,
    add_wb_stock,
    create_article,
    create_color,
    create_size,
    create_sku,
    create_wb_mapping,
)


def _setup_article_for_replenishment(db_session: Session):
    article = create_article(db_session, code="SHIP-SVC-A")
    color = create_color(db_session, inner_code="C-SHIP-A")
    size = create_size(db_session, label="SZ-SHIP-A", sort_order=1)
    sku = create_sku(db_session, article, color, size)

    wb_sku = "SKU-SHIP-SVC-A"
    create_wb_mapping(db_session, article, wb_sku=wb_sku)

    target_date = date(2025, 1, 31)
    add_wb_sales(db_session, wb_sku=wb_sku, day=target_date, sales_qty=10)
    add_wb_stock(
        db_session,
        wb_sku=wb_sku,
        stock_qty=5,
        warehouse_id=1,
        warehouse_name="MSK",
    )

    # Add NSK stock so that replenishment can happen
    from datetime import datetime, timezone

    wh = Warehouse(code="NSK-SHIP", name="NSK-SHIP", type="internal")
    db_session.add(wh)
    db_session.flush()

    sb = StockBalance(
        sku_unit_id=sku.id,
        warehouse_id=wh.id,
        quantity=100,
        updated_at=datetime.now(timezone.utc),
    )
    db_session.add(sb)
    db_session.flush()

    return article, sku, wb_sku, target_date


def test_create_wb_shipment_from_proposal_copies_replenishment_items(db_session):
    """Service should create draft shipment, items mirror replenishment items.

    All flags and quantities from WbReplenishmentItem must be copied, and
    final_qty must equal recommended_qty for each item.
    """

    article, sku, wb_sku, target_date = _setup_article_for_replenishment(db_session)

    payload = WbShipmentCreate(
        target_date=target_date,
        wb_arrival_date=target_date,
        target_coverage_days=30,
        min_coverage_days=7,
        replenishment_strategy="normal",
        zero_sales_policy="ignore",
        max_coverage_days_after=60,
        max_replenishment_per_article=None,
        article_ids=None,
        explanation=True,
        comment="Test shipment from proposal",
    )

    expected_request = WbReplenishmentRequest(
        target_date=payload.target_date,
        wb_arrival_date=payload.wb_arrival_date,
        target_coverage_days=payload.target_coverage_days,
        min_coverage_days=payload.min_coverage_days,
        replenishment_strategy=payload.replenishment_strategy,
        zero_sales_policy=payload.zero_sales_policy,
        max_coverage_days_after=payload.max_coverage_days_after,
        max_replenishment_per_article=payload.max_replenishment_per_article,
        article_ids=payload.article_ids,
        explanation=payload.explanation,
    )
    expected_items = compute_replenishment(db_session, expected_request)

    shipment = create_wb_shipment_from_proposal(db_session, payload)

    assert isinstance(shipment, WbShipment)
    assert shipment.status == "draft"
    assert shipment.target_date == target_date
    assert shipment.wb_arrival_date == target_date
    assert shipment.comment == "Test shipment from proposal"
    assert shipment.strategy == payload.replenishment_strategy
    assert shipment.zero_sales_policy == payload.zero_sales_policy
    assert shipment.target_coverage_days == payload.target_coverage_days
    assert shipment.min_coverage_days == payload.min_coverage_days
    assert shipment.max_coverage_days_after == payload.max_coverage_days_after

    items_db = (
        db_session.query(WbShipmentItem)
        .filter(WbShipmentItem.shipment_id == shipment.id)
        .all()
    )

    assert len(items_db) == len(expected_items)

    def map_db(items):
        m = {}
        for it in items:
            key = (it.article_id, it.color_id, it.size_id)
            m[key] = it
        return m

    def map_expected(items):
        m = {}
        for it in items:
            key = (it.article_id, it.color_id, it.size_id)
            m[key] = it
        return m

    db_map = map_db(items_db)
    exp_map = map_expected(expected_items)

    assert set(db_map.keys()) == set(exp_map.keys())

    for key, exp in exp_map.items():
        db_it = db_map[key]
        assert db_it.recommended_qty == exp.recommended_qty
        assert db_it.final_qty == exp.recommended_qty
        assert db_it.nsk_stock_available == exp.nsk_stock_available
        assert db_it.oos_risk_before == exp.oos_risk_before
        assert db_it.oos_risk_after == exp.oos_risk_after
        assert db_it.limited_by_nsk_stock == exp.limited_by_nsk_stock
        assert db_it.limited_by_max_coverage == exp.limited_by_max_coverage
        assert db_it.ignored_due_to_zero_sales == exp.ignored_due_to_zero_sales
        assert db_it.below_min_coverage_threshold == exp.below_min_coverage_threshold
        assert db_it.article_total_deficit == exp.article_total_deficit
        assert db_it.article_total_recommended == exp.article_total_recommended
        assert db_it.explanation == exp.explanation
