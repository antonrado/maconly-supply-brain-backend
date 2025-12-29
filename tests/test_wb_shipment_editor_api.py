from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.db import get_db
from app.models.models import WbShipment, WbShipmentItem


@pytest.fixture
def client(db_session):
    def _get_db_override():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = _get_db_override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _create_shipment_with_items(
    db_session,
    *,
    status: str = "draft",
    final_qty_values: list[int] | None = None,
    oos_risks: list[str] | None = None,
) -> tuple[WbShipment, list[WbShipmentItem]]:
    now = datetime.now(timezone.utc)
    shipment = WbShipment(
        status=status,
        target_date=date(2025, 1, 1),
        wb_arrival_date=date(2025, 1, 2),
        comment="Agg test",
        created_at=now,
        updated_at=now,
        strategy="normal",
        zero_sales_policy="ignore",
        target_coverage_days=30,
        min_coverage_days=7,
        max_coverage_days_after=60,
        max_replenishment_per_article=None,
    )
    db_session.add(shipment)
    db_session.flush()

    final_qty_values = final_qty_values or [10]
    oos_risks = oos_risks or ["green"]

    items: list[WbShipmentItem] = []
    for idx, final_qty in enumerate(final_qty_values):
        risk = oos_risks[min(idx, len(oos_risks) - 1)]
        item = WbShipmentItem(
            shipment_id=shipment.id,
            article_id=1,
            color_id=1,
            size_id=1,
            wb_sku=None,
            recommended_qty=final_qty,
            final_qty=final_qty,
            nsk_stock_available=100,
            oos_risk_before=risk,
            oos_risk_after=risk,
            limited_by_nsk_stock=False,
            limited_by_max_coverage=False,
            ignored_due_to_zero_sales=False,
            below_min_coverage_threshold=False,
            article_total_deficit=0,
            article_total_recommended=0,
            explanation=None,
        )
        db_session.add(item)
        items.append(item)

    db_session.commit()
    return shipment, items


def test_shipment_aggregates_happy_path(client, db_session):
    shipment, items = _create_shipment_with_items(
        db_session,
        final_qty_values=[10, 20, 30],
        oos_risks=["red", "yellow", "green"],
    )

    resp = client.get(f"/api/v1/wb/manager/shipment/{shipment.id}/aggregates")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["shipment_id"] == shipment.id
    assert body["status"] == shipment.status
    assert body["total_items"] == len(items)
    assert body["total_final_qty"] == sum(i.final_qty for i in items)
    assert body["red_risk_count"] == 1
    assert body["yellow_risk_count"] == 1


def test_shipment_aggregates_not_found(client):
    resp = client.get("/api/v1/wb/manager/shipment/999999/aggregates")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "WbShipment not found"


def test_shipment_item_summary_happy_path(client, db_session):
    shipment, items = _create_shipment_with_items(db_session)
    item = items[0]

    resp = client.get(
        f"/api/v1/wb/manager/shipment/{shipment.id}/items/{item.id}/summary",
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["item_id"] == item.id
    assert body["shipment_id"] == shipment.id
    assert body["article_id"] == item.article_id
    assert body["recommended_qty"] == item.recommended_qty
    assert body["final_qty"] == item.final_qty
    assert body["nsk_stock_available"] == item.nsk_stock_available
    assert body["oos_risk_before"] == item.oos_risk_before
    assert body["oos_risk_after"] == item.oos_risk_after
    assert body["limited_by_nsk_stock"] == item.limited_by_nsk_stock
    assert body["limited_by_max_coverage"] == item.limited_by_max_coverage
    assert body["ignored_due_to_zero_sales"] == item.ignored_due_to_zero_sales
    assert body["below_min_coverage_threshold"] == item.below_min_coverage_threshold
    assert body["article_total_deficit"] == item.article_total_deficit
    assert body["article_total_recommended"] == item.article_total_recommended
    assert body["explanation"] == item.explanation


def test_shipment_item_summary_item_not_in_shipment(client, db_session):
    shipment1, items1 = _create_shipment_with_items(db_session)
    shipment2, _ = _create_shipment_with_items(db_session)
    item = items1[0]

    resp = client.get(
        f"/api/v1/wb/manager/shipment/{shipment2.id}/items/{item.id}/summary",
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "WbShipmentItem not found"


def test_shipment_item_summary_shipment_not_found(client, db_session):
    shipment, items = _create_shipment_with_items(db_session)
    item = items[0]

    resp = client.get(
        f"/api/v1/wb/manager/shipment/999999/items/{item.id}/summary",
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "WbShipment not found"


def test_shipment_status_list_basic(client):
    resp = client.get("/api/v1/wb/manager/shipment/status-list")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert "statuses" in body
    assert body["statuses"] == ["draft", "approved", "shipped", "cancelled"]


def test_patch_shipment_item_final_qty_exceeds_nsk_stock(client, db_session):
    now = datetime.now(timezone.utc)
    shipment = WbShipment(
        status="draft",
        target_date=date(2025, 1, 1),
        wb_arrival_date=date(2025, 1, 2),
        comment="NSK validation",
        created_at=now,
        updated_at=now,
        strategy="normal",
        zero_sales_policy="ignore",
        target_coverage_days=30,
        min_coverage_days=7,
        max_coverage_days_after=60,
        max_replenishment_per_article=None,
    )
    db_session.add(shipment)
    db_session.flush()

    item = WbShipmentItem(
        shipment_id=shipment.id,
        article_id=1,
        color_id=1,
        size_id=1,
        wb_sku=None,
        recommended_qty=20,
        final_qty=20,
        nsk_stock_available=50,
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
    db_session.commit()

    resp = client.patch(
        f"/api/v1/wb/manager/shipment/{shipment.id}/items/{item.id}",
        json={"final_qty": 60},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "final_qty exceeds available NSC stock"


def test_patch_shipment_item_final_qty_valid_change(client, db_session):
    now = datetime.now(timezone.utc)
    shipment = WbShipment(
        status="draft",
        target_date=date(2025, 1, 1),
        wb_arrival_date=date(2025, 1, 2),
        comment="NSK validation ok",
        created_at=now,
        updated_at=now,
        strategy="normal",
        zero_sales_policy="ignore",
        target_coverage_days=30,
        min_coverage_days=7,
        max_coverage_days_after=60,
        max_replenishment_per_article=None,
    )
    db_session.add(shipment)
    db_session.flush()

    item = WbShipmentItem(
        shipment_id=shipment.id,
        article_id=1,
        color_id=1,
        size_id=1,
        wb_sku=None,
        recommended_qty=20,
        final_qty=20,
        nsk_stock_available=50,
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
    db_session.commit()

    resp = client.patch(
        f"/api/v1/wb/manager/shipment/{shipment.id}/items/{item.id}",
        json={"final_qty": 50},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    patched_item = next(i for i in body["items"] if i["id"] == item.id)
    assert patched_item["final_qty"] == 50
