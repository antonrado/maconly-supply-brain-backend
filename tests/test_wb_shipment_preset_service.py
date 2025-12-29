from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from app.models.models import WbShipment, WbShipmentItem
from app.services.wb_shipment_preset import compute_shipment_preset


def _create_shipment(
    db_session,
    *,
    status: str = "approved",
    target_date: date,
    wb_arrival_date: date,
    created_at: datetime,
    strategy: str = "normal",
    zero_sales_policy: str = "ignore",
    target_coverage_days: int = 30,
    min_coverage_days: int = 7,
    max_coverage_days_after: int = 60,
    max_replenishment_per_article: int | None = None,
    total_final_qty: int | None = None,
) -> WbShipment:
    shipment = WbShipment(
        status=status,
        target_date=target_date,
        wb_arrival_date=wb_arrival_date,
        comment=None,
        created_at=created_at,
        updated_at=created_at,
        strategy=strategy,
        zero_sales_policy=zero_sales_policy,
        target_coverage_days=target_coverage_days,
        min_coverage_days=min_coverage_days,
        max_coverage_days_after=max_coverage_days_after,
        max_replenishment_per_article=max_replenishment_per_article,
    )
    db_session.add(shipment)
    db_session.flush()

    if total_final_qty is not None:
        item = WbShipmentItem(
            shipment_id=shipment.id,
            article_id=1,
            color_id=1,
            size_id=1,
            wb_sku=None,
            recommended_qty=total_final_qty,
            final_qty=total_final_qty,
            nsk_stock_available=0,
            oos_risk_before="green",
            oos_risk_after="green",
            limited_by_nsk_stock=False,
            limited_by_max_coverage=False,
            ignored_due_to_zero_sales=False,
            below_min_coverage_threshold=False,
            article_total_deficit=0,
            article_total_recommended=0,
            explanation=None,
        )
        db_session.add(item)

    return shipment


def test_wb_shipment_preset_no_history(db_session):
    target = date(2025, 2, 1)

    preset = compute_shipment_preset(db=db_session, target_date=target)

    assert preset.target_date == target
    # Default transit 7 days when no history
    assert preset.suggested_wb_arrival_date == date(2025, 2, 8)

    assert preset.suggested_strategy == "normal"
    assert preset.suggested_zero_sales_policy == "ignore"
    assert preset.suggested_target_coverage_days == 30
    assert preset.suggested_min_coverage_days == 7
    assert preset.suggested_max_coverage_days_after == 60
    assert preset.suggested_max_replenishment_per_article is None

    assert preset.recent_shipments == []
    assert preset.avg_total_final_qty_last3 is None
    assert preset.last_shipment_total_final_qty is None

    assert preset.explanation is not None
    assert "No non-cancelled WB shipments found" in preset.explanation


def test_wb_shipment_preset_single_shipment_history(db_session):
    base_created = datetime(2025, 1, 1, tzinfo=timezone.utc)
    base_target = date(2025, 1, 1)
    base_arrival = date(2025, 1, 8)  # transit = 7

    shipment = _create_shipment(
        db_session,
        status="approved",
        target_date=base_target,
        wb_arrival_date=base_arrival,
        created_at=base_created,
        strategy="aggressive",
        zero_sales_policy="keep",
        target_coverage_days=45,
        min_coverage_days=10,
        max_coverage_days_after=90,
        max_replenishment_per_article=123,
        total_final_qty=30,
    )
    db_session.commit()

    target = date(2025, 2, 1)
    preset = compute_shipment_preset(db=db_session, target_date=target)

    assert preset.suggested_strategy == "aggressive"
    assert preset.suggested_zero_sales_policy == "keep"
    assert preset.suggested_target_coverage_days == 45
    assert preset.suggested_min_coverage_days == 10
    assert preset.suggested_max_coverage_days_after == 90
    assert preset.suggested_max_replenishment_per_article == 123

    # Transit days should be reused (7 days)
    assert preset.suggested_wb_arrival_date == date(2025, 2, 8)

    assert len(preset.recent_shipments) == 1
    rh = preset.recent_shipments[0]
    assert rh.id == shipment.id
    assert rh.total_final_qty == 30
    assert rh.total_items == 1

    assert preset.last_shipment_total_final_qty == 30
    assert pytest.approx(preset.avg_total_final_qty_last3) == 30.0


def test_wb_shipment_preset_median_transit_days(db_session):
    now = datetime(2025, 1, 1, tzinfo=timezone.utc)

    # Transit 3 days
    _create_shipment(
        db_session,
        target_date=date(2025, 1, 1),
        wb_arrival_date=date(2025, 1, 4),
        created_at=now,
        total_final_qty=10,
    )
    # Transit 7 days
    _create_shipment(
        db_session,
        target_date=date(2025, 1, 2),
        wb_arrival_date=date(2025, 1, 9),
        created_at=now.replace(day=2),
        total_final_qty=20,
    )
    # Transit 10 days
    _create_shipment(
        db_session,
        target_date=date(2025, 1, 3),
        wb_arrival_date=date(2025, 1, 13),
        created_at=now.replace(day=3),
        total_final_qty=30,
    )
    db_session.commit()

    target = date(2025, 2, 1)
    preset = compute_shipment_preset(db=db_session, target_date=target)

    # Median of [3, 7, 10] is 7
    assert preset.suggested_wb_arrival_date == date(2025, 2, 8)


def test_wb_shipment_preset_strange_transit_days_fallback(db_session):
    now = datetime(2025, 1, 1, tzinfo=timezone.utc)

    # Transit 0 days (invalid)
    _create_shipment(
        db_session,
        target_date=date(2025, 1, 1),
        wb_arrival_date=date(2025, 1, 1),
        created_at=now,
        total_final_qty=10,
    )
    # Transit 25 days (invalid)
    _create_shipment(
        db_session,
        target_date=date(2025, 1, 1),
        wb_arrival_date=date(2025, 1, 26),
        created_at=now.replace(day=2),
        total_final_qty=20,
    )
    db_session.commit()

    target = date(2025, 2, 1)
    preset = compute_shipment_preset(db=db_session, target_date=target)

    # No valid transit_days in [1, 20] -> fallback to 7 days
    assert preset.suggested_wb_arrival_date == date(2025, 2, 8)


def test_wb_shipment_preset_volume_aggregates(db_session):
    now = datetime(2025, 1, 1, tzinfo=timezone.utc)

    # Three shipments with totals 100, 200, 300
    _create_shipment(
        db_session,
        target_date=date(2025, 1, 1),
        wb_arrival_date=date(2025, 1, 8),
        created_at=now,
        total_final_qty=100,
    )
    _create_shipment(
        db_session,
        target_date=date(2025, 1, 2),
        wb_arrival_date=date(2025, 1, 9),
        created_at=now.replace(day=2),
        total_final_qty=200,
    )
    latest = _create_shipment(
        db_session,
        target_date=date(2025, 1, 3),
        wb_arrival_date=date(2025, 1, 10),
        created_at=now.replace(day=3),
        total_final_qty=300,
    )
    db_session.commit()

    target = date(2025, 2, 1)
    preset = compute_shipment_preset(db=db_session, target_date=target)

    # Last shipment is the one with 300
    assert preset.last_shipment_total_final_qty == 300
    assert pytest.approx(preset.avg_total_final_qty_last3) == (100 + 200 + 300) / 3.0

    assert preset.recent_shipments
    assert preset.recent_shipments[0].id == latest.id
