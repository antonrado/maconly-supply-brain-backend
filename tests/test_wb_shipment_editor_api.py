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


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _parse_json_datetime(value: str) -> datetime:
    if value.endswith("Z"):
        value = f"{value[:-1]}+00:00"
    return _normalize_datetime(datetime.fromisoformat(value))


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

    assert set(body.keys()) == {
        "shipment_id",
        "status",
        "created_at",
        "updated_at",
        "total_items",
        "total_final_qty",
        "red_risk_count",
        "yellow_risk_count",
    }
    assert body["shipment_id"] == shipment.id
    assert body["status"] == shipment.status
    assert body["total_items"] == len(items)
    assert body["total_final_qty"] == sum(i.final_qty for i in items)
    assert body["red_risk_count"] == 1
    assert body["yellow_risk_count"] == 1
    assert _parse_json_datetime(body["created_at"]) == _normalize_datetime(shipment.created_at)
    assert _parse_json_datetime(body["updated_at"]) == _normalize_datetime(shipment.updated_at)


def test_shipment_aggregates_not_found(client):
    resp = client.get("/api/v1/wb/manager/shipment/999999/aggregates")
    assert resp.status_code == 404
    assert resp.json()["detail"] == {
        "code": "wb_shipment_not_found",
        "message": "WbShipment not found",
        "shipment_id": 999999,
        "field": "shipment_id",
        "field_metadata": {
            "description": "Requested WB shipment identifier",
            "type": "int",
        },
        "next_steps": ["use_existing_wb_shipment_id"],
    }


def test_shipment_item_summary_happy_path(client, db_session):
    shipment, items = _create_shipment_with_items(db_session)
    item = items[0]

    resp = client.get(
        f"/api/v1/wb/manager/shipment/{shipment.id}/items/{item.id}/summary",
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body == {
        "item_id": item.id,
        "shipment_id": shipment.id,
        "article_id": item.article_id,
        "color_id": item.color_id,
        "size_id": item.size_id,
        "wb_sku": item.wb_sku,
        "recommended_qty": item.recommended_qty,
        "final_qty": item.final_qty,
        "nsk_stock_available": item.nsk_stock_available,
        "oos_risk_before": item.oos_risk_before,
        "oos_risk_after": item.oos_risk_after,
        "limited_by_nsk_stock": item.limited_by_nsk_stock,
        "limited_by_max_coverage": item.limited_by_max_coverage,
        "ignored_due_to_zero_sales": item.ignored_due_to_zero_sales,
        "below_min_coverage_threshold": item.below_min_coverage_threshold,
        "article_total_deficit": item.article_total_deficit,
        "article_total_recommended": item.article_total_recommended,
        "explanation": item.explanation,
    }


def test_shipment_item_summary_item_not_in_shipment(client, db_session):
    shipment1, items1 = _create_shipment_with_items(db_session)
    shipment2, _ = _create_shipment_with_items(db_session)
    item = items1[0]

    resp = client.get(
        f"/api/v1/wb/manager/shipment/{shipment2.id}/items/{item.id}/summary",
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == {
        "code": "wb_shipment_item_not_found",
        "message": "WbShipmentItem not found",
        "shipment_id": shipment2.id,
        "item_id": item.id,
        "field": "item_id",
        "field_metadata": {
            "description": "Requested WB shipment item identifier within shipment scope",
            "type": "int",
        },
        "next_steps": ["use_existing_wb_shipment_item_id"],
    }


def test_shipment_item_summary_shipment_not_found(client, db_session):
    shipment, items = _create_shipment_with_items(db_session)
    item = items[0]

    resp = client.get(
        f"/api/v1/wb/manager/shipment/999999/items/{item.id}/summary",
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == {
        "code": "wb_shipment_not_found",
        "message": "WbShipment not found",
        "shipment_id": 999999,
        "field": "shipment_id",
        "field_metadata": {
            "description": "Requested WB shipment identifier",
            "type": "int",
        },
        "next_steps": ["use_existing_wb_shipment_id"],
    }


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
    assert resp.json()["detail"] == {
        "code": "wb_shipment_item_final_qty_exceeds_stock",
        "message": "final_qty exceeds available NSC stock",
        "shipment_id": shipment.id,
        "item_id": item.id,
        "final_qty": 60,
        "nsk_stock_available": 50,
        "field": "final_qty",
        "field_metadata": {
            "description": "Requested final shipment quantity",
            "type": "int",
        },
        "next_steps": ["use_final_qty_not_greater_than_nsk_stock_available"],
    }


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
