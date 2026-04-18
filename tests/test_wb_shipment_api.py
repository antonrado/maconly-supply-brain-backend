from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.db import get_db
from app.models.models import (
    WbShipment,
    WbShipmentItem,
    Warehouse,
    StockBalance,
)
from tests.test_utils import (
    add_wb_sales,
    add_wb_stock,
    create_article,
    create_color,
    create_size,
    create_sku,
    create_wb_mapping,
)


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


def _setup_article_for_replenishment(db_session, code: str):
    article = create_article(db_session, code=code)
    color = create_color(db_session, inner_code=f"C-{code}")
    size = create_size(db_session, label=f"SZ-{code}", sort_order=1)
    sku = create_sku(db_session, article, color, size)

    wb_sku = f"SKU-{code}"
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

    # NSK stock
    wh = Warehouse(code=f"NSK-{code}", name="NSK", type="internal")
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

    return article, target_date


def test_shipment_status_list_endpoint(client):
    resp = client.get("/api/v1/wb/manager/shipment/status-list")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {
        "statuses": ["draft", "approved", "shipped", "cancelled"],
    }


def test_create_shipment_from_proposal_endpoint(client, db_session):
    """POST /wb/manager/shipment/from-proposal creates draft shipment with items from replenishment."""
    article, target_date = _setup_article_for_replenishment(
        db_session, code="SHIP-API-A"
    )

    payload = {
        "target_date": target_date.isoformat(),
        "wb_arrival_date": target_date.isoformat(),
        "target_coverage_days": 30,
        "min_coverage_days": 7,
        "replenishment_strategy": "normal",
        "zero_sales_policy": "ignore",
        "max_coverage_days_after": 60,
        "max_replenishment_per_article": 77,
        "comment": "Test shipment from proposal",
    }

    resp = client.post(
        "/api/v1/wb/manager/shipment/from-proposal",
        json=payload,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()

    assert set(body.keys()) == {
        "id",
        "status",
        "target_date",
        "wb_arrival_date",
        "comment",
        "strategy",
        "zero_sales_policy",
        "target_coverage_days",
        "min_coverage_days",
        "max_coverage_days_after",
        "max_replenishment_per_article",
        "created_at",
        "updated_at",
        "items",
    }
    assert body["status"] == "draft"
    assert body["target_date"] == target_date.isoformat()
    assert body["wb_arrival_date"] == target_date.isoformat()
    assert body["comment"] == "Test shipment from proposal"
    assert body["strategy"] == "normal"
    assert body["zero_sales_policy"] == "ignore"
    assert body["target_coverage_days"] == 30
    assert body["min_coverage_days"] == 7
    assert body["max_coverage_days_after"] == 60
    assert body["max_replenishment_per_article"] == 77
    assert body["items"]

    shipment_id = body["id"]
    shipment_db = (
        db_session.query(WbShipment)
        .filter(WbShipment.id == shipment_id)
        .first()
    )
    assert shipment_db is not None
    assert _parse_json_datetime(body["created_at"]) == _normalize_datetime(shipment_db.created_at)
    assert _parse_json_datetime(body["updated_at"]) == _normalize_datetime(shipment_db.updated_at)

    items = body["items"]
    assert {item["article_id"] for item in items} == {article.id}

    items_db = (
        db_session.query(WbShipmentItem)
        .filter(WbShipmentItem.shipment_id == shipment_id)
        .all()
    )
    assert len(items_db) == len(items)

    payload_map = {
        (item["article_id"], item["color_id"], item["size_id"]): item
        for item in items
    }
    db_map = {
        (item.article_id, item.color_id, item.size_id): item
        for item in items_db
    }
    assert set(payload_map.keys()) == set(db_map.keys())

    for key, payload_item in payload_map.items():
        db_item = db_map[key]
        assert set(payload_item.keys()) == {
            "id",
            "shipment_id",
            "article_id",
            "color_id",
            "size_id",
            "wb_sku",
            "recommended_qty",
            "final_qty",
            "nsk_stock_available",
            "oos_risk_before",
            "oos_risk_after",
            "limited_by_nsk_stock",
            "limited_by_max_coverage",
            "ignored_due_to_zero_sales",
            "below_min_coverage_threshold",
            "article_total_deficit",
            "article_total_recommended",
            "explanation",
        }
        assert payload_item["id"] == db_item.id
        assert payload_item["shipment_id"] == shipment_id
        assert payload_item["article_id"] == db_item.article_id
        assert payload_item["color_id"] == db_item.color_id
        assert payload_item["size_id"] == db_item.size_id
        assert payload_item["wb_sku"] == db_item.wb_sku
        assert payload_item["recommended_qty"] == db_item.recommended_qty
        assert payload_item["final_qty"] == db_item.final_qty
        assert payload_item["final_qty"] == payload_item["recommended_qty"]
        assert payload_item["nsk_stock_available"] == db_item.nsk_stock_available
        assert payload_item["oos_risk_before"] == db_item.oos_risk_before
        assert payload_item["oos_risk_after"] == db_item.oos_risk_after
        assert payload_item["limited_by_nsk_stock"] == db_item.limited_by_nsk_stock
        assert payload_item["limited_by_max_coverage"] == db_item.limited_by_max_coverage
        assert payload_item["ignored_due_to_zero_sales"] == db_item.ignored_due_to_zero_sales
        assert payload_item["below_min_coverage_threshold"] == db_item.below_min_coverage_threshold
        assert payload_item["article_total_deficit"] == db_item.article_total_deficit
        assert payload_item["article_total_recommended"] == db_item.article_total_recommended
        assert payload_item["explanation"] == db_item.explanation


def test_create_shipment_from_proposal_invalid_dates(client):
    payload = {
        "items": [],
        "target_date": "2025-01-31",
        "wb_arrival_date": "2025-01-01",
        "target_coverage_days": 30,
        "min_coverage_days": 7,
        "replenishment_strategy": "normal",
        "zero_sales_policy": "ignore",
        "max_coverage_days_after": 60,
        "comment": "invalid dates",
    }

    resp = client.post(
        "/api/v1/wb/manager/shipment/from-proposal",
        json=payload,
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"] == {
        "code": "wb_arrival_date_before_target_date",
        "message": "wb_arrival_date cannot be earlier than target_date",
        "field": "wb_arrival_date",
        "field_metadata": {
            "description": "Requested WB arrival date",
            "type": "date",
        },
        "target_date": "2025-01-31",
        "wb_arrival_date": "2025-01-01",
        "next_steps": ["use_wb_arrival_date_on_or_after_target_date"],
    }


def test_shipment_list_filters_by_status_and_article(client, db_session):
    """GET /wb/manager/shipment/ supports filters by status, article_id and date range."""
    # Prepare two articles and shipments
    article1 = create_article(db_session, code="SHIP-LIST-A1")
    article2 = create_article(db_session, code="SHIP-LIST-A2")
    color = create_color(db_session, inner_code="C-LIST")
    size = create_size(db_session, label="SZ-LIST", sort_order=1)

    now = datetime.now(timezone.utc)

    def _make_shipment(article, status, tgt_date):
        shipment = WbShipment(
            status=status,
            target_date=tgt_date,
            wb_arrival_date=tgt_date,
            comment=None,
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
            article_id=article.id,
            color_id=color.id,
            size_id=size.id,
            wb_sku=None,
            recommended_qty=10,
            final_qty=10,
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

    s1 = _make_shipment(article1, "draft", date(2025, 1, 1))
    s2 = _make_shipment(article2, "approved", date(2025, 1, 2))
    db_session.commit()

    # All shipments
    resp_all = client.get("/api/v1/wb/manager/shipment/")
    assert resp_all.status_code == 200
    body_all = resp_all.json()
    body_all_map = {payload["id"]: payload for payload in body_all}
    assert set(body_all_map.keys()) == {s1.id, s2.id}

    items_db = (
        db_session.query(WbShipmentItem)
        .filter(WbShipmentItem.shipment_id.in_([s1.id, s2.id]))
        .all()
    )
    items_by_shipment = {item.shipment_id: item for item in items_db}
    assert set(items_by_shipment.keys()) == {s1.id, s2.id}

    shipments_by_id = {s1.id: s1, s2.id: s2}
    for shipment_id, shipment in shipments_by_id.items():
        payload = body_all_map[shipment_id]
        assert set(payload.keys()) == {
            "id",
            "status",
            "target_date",
            "wb_arrival_date",
            "comment",
            "strategy",
            "zero_sales_policy",
            "target_coverage_days",
            "min_coverage_days",
            "max_coverage_days_after",
            "max_replenishment_per_article",
            "created_at",
            "updated_at",
            "items",
        }
        assert payload["id"] == shipment.id
        assert payload["status"] == shipment.status
        assert payload["target_date"] == shipment.target_date.isoformat()
        assert payload["wb_arrival_date"] == shipment.wb_arrival_date.isoformat()
        assert payload["comment"] == shipment.comment
        assert payload["strategy"] == shipment.strategy
        assert payload["zero_sales_policy"] == shipment.zero_sales_policy
        assert payload["target_coverage_days"] == shipment.target_coverage_days
        assert payload["min_coverage_days"] == shipment.min_coverage_days
        assert payload["max_coverage_days_after"] == shipment.max_coverage_days_after
        assert payload["max_replenishment_per_article"] == shipment.max_replenishment_per_article
        assert _parse_json_datetime(payload["created_at"]) == _normalize_datetime(shipment.created_at)
        assert _parse_json_datetime(payload["updated_at"]) == _normalize_datetime(shipment.updated_at)

        db_item = items_by_shipment[shipment_id]
        assert len(payload["items"]) == 1
        payload_item = payload["items"][0]
        assert set(payload_item.keys()) == {
            "id",
            "shipment_id",
            "article_id",
            "color_id",
            "size_id",
            "wb_sku",
            "recommended_qty",
            "final_qty",
            "nsk_stock_available",
            "oos_risk_before",
            "oos_risk_after",
            "limited_by_nsk_stock",
            "limited_by_max_coverage",
            "ignored_due_to_zero_sales",
            "below_min_coverage_threshold",
            "article_total_deficit",
            "article_total_recommended",
            "explanation",
        }
        assert payload_item == {
            "id": db_item.id,
            "shipment_id": shipment.id,
            "article_id": db_item.article_id,
            "color_id": db_item.color_id,
            "size_id": db_item.size_id,
            "wb_sku": db_item.wb_sku,
            "recommended_qty": db_item.recommended_qty,
            "final_qty": db_item.final_qty,
            "nsk_stock_available": db_item.nsk_stock_available,
            "oos_risk_before": db_item.oos_risk_before,
            "oos_risk_after": db_item.oos_risk_after,
            "limited_by_nsk_stock": db_item.limited_by_nsk_stock,
            "limited_by_max_coverage": db_item.limited_by_max_coverage,
            "ignored_due_to_zero_sales": db_item.ignored_due_to_zero_sales,
            "below_min_coverage_threshold": db_item.below_min_coverage_threshold,
            "article_total_deficit": db_item.article_total_deficit,
            "article_total_recommended": db_item.article_total_recommended,
            "explanation": db_item.explanation,
        }

    # By status
    resp_draft = client.get("/api/v1/wb/manager/shipment/", params={"status": "draft"})
    assert resp_draft.status_code == 200
    assert resp_draft.json() == [body_all_map[s1.id]]

    # By article_id
    resp_article1 = client.get(
        "/api/v1/wb/manager/shipment/",
        params={"article_id": article1.id},
    )
    assert resp_article1.status_code == 200
    body_a1 = resp_article1.json()
    assert body_a1 == [body_all_map[s1.id]]

    # By date range
    resp_date = client.get(
        "/api/v1/wb/manager/shipment/",
        params={"date_from": "2025-01-02", "date_to": "2025-01-02"},
    )
    assert resp_date.status_code == 200
    body_date = resp_date.json()
    assert body_date == [body_all_map[s2.id]]


def test_get_shipment_by_id(client, db_session):
    now = datetime.now(timezone.utc)
    shipment = WbShipment(
        status="draft",
        target_date=date(2025, 1, 1),
        wb_arrival_date=date(2025, 1, 1),
        comment="Test get",
        created_at=now,
        updated_at=now,
        strategy="aggressive",
        zero_sales_policy="keep",
        target_coverage_days=45,
        min_coverage_days=10,
        max_coverage_days_after=90,
        max_replenishment_per_article=123,
    )
    db_session.add(shipment)
    db_session.flush()

    item = WbShipmentItem(
        shipment_id=shipment.id,
        article_id=101,
        color_id=202,
        size_id=303,
        wb_sku="WB-SKU-GET-1",
        recommended_qty=12,
        final_qty=10,
        nsk_stock_available=50,
        oos_risk_before="red",
        oos_risk_after="yellow",
        limited_by_nsk_stock=True,
        limited_by_max_coverage=False,
        ignored_due_to_zero_sales=False,
        below_min_coverage_threshold=True,
        article_total_deficit=18,
        article_total_recommended=12,
        explanation="Manual shipment item note",
    )
    db_session.add(item)
    db_session.commit()

    resp_ok = client.get(f"/api/v1/wb/manager/shipment/{shipment.id}")
    assert resp_ok.status_code == 200
    body = resp_ok.json()
    assert set(body.keys()) == {
        "id",
        "status",
        "target_date",
        "wb_arrival_date",
        "comment",
        "strategy",
        "zero_sales_policy",
        "target_coverage_days",
        "min_coverage_days",
        "max_coverage_days_after",
        "max_replenishment_per_article",
        "created_at",
        "updated_at",
        "items",
    }
    assert body["id"] == shipment.id
    assert body["status"] == "draft"
    assert body["target_date"] == "2025-01-01"
    assert body["wb_arrival_date"] == "2025-01-01"
    assert body["comment"] == "Test get"
    assert body["strategy"] == "aggressive"
    assert body["zero_sales_policy"] == "keep"
    assert body["target_coverage_days"] == 45
    assert body["min_coverage_days"] == 10
    assert body["max_coverage_days_after"] == 90
    assert body["max_replenishment_per_article"] == 123
    assert _parse_json_datetime(body["created_at"]) == _normalize_datetime(shipment.created_at)
    assert _parse_json_datetime(body["updated_at"]) == _normalize_datetime(shipment.updated_at)

    assert len(body["items"]) == 1
    payload_item = body["items"][0]
    assert set(payload_item.keys()) == {
        "id",
        "shipment_id",
        "article_id",
        "color_id",
        "size_id",
        "wb_sku",
        "recommended_qty",
        "final_qty",
        "nsk_stock_available",
        "oos_risk_before",
        "oos_risk_after",
        "limited_by_nsk_stock",
        "limited_by_max_coverage",
        "ignored_due_to_zero_sales",
        "below_min_coverage_threshold",
        "article_total_deficit",
        "article_total_recommended",
        "explanation",
    }
    assert payload_item == {
        "id": item.id,
        "shipment_id": shipment.id,
        "article_id": 101,
        "color_id": 202,
        "size_id": 303,
        "wb_sku": "WB-SKU-GET-1",
        "recommended_qty": 12,
        "final_qty": 10,
        "nsk_stock_available": 50,
        "oos_risk_before": "red",
        "oos_risk_after": "yellow",
        "limited_by_nsk_stock": True,
        "limited_by_max_coverage": False,
        "ignored_due_to_zero_sales": False,
        "below_min_coverage_threshold": True,
        "article_total_deficit": 18,
        "article_total_recommended": 12,
        "explanation": "Manual shipment item note",
    }

    resp_404 = client.get("/api/v1/wb/manager/shipment/999999")
    assert resp_404.status_code == 404
    assert resp_404.json()["detail"] == {
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


def test_update_shipment_returns_structured_404_for_unknown_shipment(client):
    response = client.patch(
        "/api/v1/wb/manager/shipment/999999",
        json={"comment": "missing shipment"},
    )
    assert response.status_code == 404, response.text
    assert response.json()["detail"] == {
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


def test_get_shipment_item_summary_returns_structured_404_for_unknown_shipment(client):
    response = client.get("/api/v1/wb/manager/shipment/999999/items/1/summary")
    assert response.status_code == 404, response.text
    assert response.json()["detail"] == {
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


def test_get_shipment_item_summary_returns_structured_404_for_unknown_item(client, db_session):
    now = datetime.now(timezone.utc)
    shipment = WbShipment(
        status="draft",
        target_date=date(2025, 1, 1),
        wb_arrival_date=date(2025, 1, 1),
        comment="summary missing item",
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
    db_session.commit()

    response = client.get(f"/api/v1/wb/manager/shipment/{shipment.id}/items/999999/summary")
    assert response.status_code == 404, response.text
    assert response.json()["detail"] == {
        "code": "wb_shipment_item_not_found",
        "message": "WbShipmentItem not found",
        "shipment_id": shipment.id,
        "item_id": 999999,
        "field": "item_id",
        "field_metadata": {
            "description": "Requested WB shipment item identifier within shipment scope",
            "type": "int",
        },
        "next_steps": ["use_existing_wb_shipment_item_id"],
    }


def test_shipment_status_transitions_and_final_states(client, db_session):
    now = datetime.now(timezone.utc)
    shipment = WbShipment(
        status="draft",
        target_date=date(2025, 1, 1),
        wb_arrival_date=date(2025, 1, 1),
        comment=None,
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
    db_session.commit()

    # draft -> approved
    resp = client.patch(
        f"/api/v1/wb/manager/shipment/{shipment.id}",
        json={"status": "approved"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "approved"

    # approved -> shipped
    resp_shipped = client.patch(
        f"/api/v1/wb/manager/shipment/{shipment.id}",
        json={"status": "shipped"},
    )
    assert resp_shipped.status_code == 200
    assert resp_shipped.json()["status"] == "shipped"

    # shipped -> any other should fail
    for target in ["draft", "approved", "cancelled"]:
        resp_bad = client.patch(
            f"/api/v1/wb/manager/shipment/{shipment.id}",
            json={"status": target},
        )
        assert resp_bad.status_code == 400

    # Creating cancelled shipment and ensuring it is final
    shipment_cancelled = WbShipment(
        status="cancelled",
        target_date=date(2025, 1, 2),
        wb_arrival_date=date(2025, 1, 2),
        comment=None,
        created_at=now,
        updated_at=now,
        strategy="normal",
        zero_sales_policy="ignore",
        target_coverage_days=30,
        min_coverage_days=7,
        max_coverage_days_after=60,
        max_replenishment_per_article=None,
    )
    db_session.add(shipment_cancelled)
    db_session.commit()

    for target in ["draft", "approved", "shipped"]:
        resp_bad = client.patch(
            f"/api/v1/wb/manager/shipment/{shipment_cancelled.id}",
            json={"status": target},
        )
        assert resp_bad.status_code == 400


def test_shipment_status_invalid_and_comment_updates_timestamp(client, db_session):
    now = datetime.now(timezone.utc)
    shipment = WbShipment(
        status="draft",
        target_date=date(2025, 1, 1),
        wb_arrival_date=date(2025, 1, 1),
        comment=None,
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
    db_session.commit()

    resp_before = client.get(f"/api/v1/wb/manager/shipment/{shipment.id}")
    old_updated_at = _parse_json_datetime(resp_before.json()["updated_at"])

    # Valid comment update
    resp = client.patch(
        f"/api/v1/wb/manager/shipment/{shipment.id}",
        json={"comment": "Updated by test"},
    )
    assert resp.status_code == 200
    body = resp.json()
    shipment_db = (
        db_session.query(WbShipment)
        .filter(WbShipment.id == shipment.id)
        .first()
    )
    assert shipment_db is not None
    assert set(body.keys()) == {
        "id",
        "status",
        "target_date",
        "wb_arrival_date",
        "comment",
        "strategy",
        "zero_sales_policy",
        "target_coverage_days",
        "min_coverage_days",
        "max_coverage_days_after",
        "max_replenishment_per_article",
        "created_at",
        "updated_at",
        "items",
    }
    assert body["id"] == shipment_db.id
    assert body["status"] == shipment_db.status
    assert body["target_date"] == shipment_db.target_date.isoformat()
    assert body["wb_arrival_date"] == shipment_db.wb_arrival_date.isoformat()
    assert body["comment"] == "Updated by test"
    assert body["comment"] == shipment_db.comment
    assert body["strategy"] == shipment_db.strategy
    assert body["zero_sales_policy"] == shipment_db.zero_sales_policy
    assert body["target_coverage_days"] == shipment_db.target_coverage_days
    assert body["min_coverage_days"] == shipment_db.min_coverage_days
    assert body["max_coverage_days_after"] == shipment_db.max_coverage_days_after
    assert body["max_replenishment_per_article"] == shipment_db.max_replenishment_per_article
    assert _parse_json_datetime(body["created_at"]) == _normalize_datetime(shipment_db.created_at)
    assert _parse_json_datetime(body["updated_at"]) == _normalize_datetime(shipment_db.updated_at)
    assert _parse_json_datetime(body["updated_at"]) != old_updated_at
    assert body["items"] == []

    # Invalid status value
    resp_bad = client.patch(
        f"/api/v1/wb/manager/shipment/{shipment.id}",
        json={"status": "weird"},
    )
    assert resp_bad.status_code == 400
    assert resp_bad.json()["detail"] == {
        "code": "invalid_wb_shipment_status",
        "message": "Invalid status 'weird'",
        "shipment_id": shipment.id,
        "field": "status",
        "field_metadata": {
            "description": "Requested WB shipment status",
            "type": "string",
        },
        "status": "weird",
        "allowed_values": ["approved", "cancelled", "draft", "shipped"],
        "next_steps": ["use_supported_wb_shipment_status"],
    }


def test_update_shipment_returns_structured_400_for_invalid_status_transition(client, db_session):
    now = datetime.now(timezone.utc)
    shipment = WbShipment(
        status="approved",
        target_date=date(2025, 1, 1),
        wb_arrival_date=date(2025, 1, 1),
        comment=None,
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
    db_session.commit()

    response = client.patch(
        f"/api/v1/wb/manager/shipment/{shipment.id}",
        json={"status": "draft"},
    )
    assert response.status_code == 400, response.text
    assert response.json()["detail"] == {
        "code": "invalid_wb_shipment_status_transition",
        "message": "Invalid status transition from 'approved' to 'draft'",
        "shipment_id": shipment.id,
        "field": "status",
        "field_metadata": {
            "description": "Requested WB shipment status transition target",
            "type": "string",
        },
        "current_status": "approved",
        "target_status": "draft",
        "allowed_target_statuses": ["approved", "cancelled", "shipped"],
        "next_steps": ["use_allowed_wb_shipment_status_transition"],
    }


def test_update_shipment_returns_structured_400_for_final_status(client, db_session):
    now = datetime.now(timezone.utc)
    shipment = WbShipment(
        status="shipped",
        target_date=date(2025, 1, 1),
        wb_arrival_date=date(2025, 1, 1),
        comment=None,
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
    db_session.commit()

    response = client.patch(
        f"/api/v1/wb/manager/shipment/{shipment.id}",
        json={"comment": "blocked"},
    )
    assert response.status_code == 400, response.text
    assert response.json()["detail"] == {
        "code": "wb_shipment_final_status_locked",
        "message": "Cannot modify a shipment in final status",
        "shipment_id": shipment.id,
        "field": "status",
        "field_metadata": {
            "description": "Current WB shipment status blocking the requested mutation",
            "type": "string",
        },
        "status": "shipped",
        "next_steps": ["use_draft_or_approved_shipment_for_updates"],
    }


def test_shipment_item_editing_respects_status(client, db_session):
    """PATCH items allowed only in draft and updates shipment.updated_at."""
    # Create draft shipment via API to get real items
    article, target_date = _setup_article_for_replenishment(
        db_session, code="SHIP-API-ITEMS"
    )

    payload = {
        "target_date": target_date.isoformat(),
        "wb_arrival_date": target_date.isoformat(),
        "comment": "For item patch",
    }

    resp_create = client.post(
        "/api/v1/wb/manager/shipment/from-proposal",
        json=payload,
    )
    assert resp_create.status_code == 201, resp_create.text
    shipment = resp_create.json()
    shipment_id = shipment["id"]
    assert shipment["items"], "Expected items in created shipment"
    item_id = shipment["items"][0]["id"]
    old_updated_at = shipment["updated_at"]

    patch_payload = {"final_qty": 50, "explanation": "Manual adjustment"}

    # Successful patch in draft status
    resp_patch = client.patch(
        f"/api/v1/wb/manager/shipment/{shipment_id}/items/{item_id}",
        json=patch_payload,
    )
    assert resp_patch.status_code == 200
    shipment_after = resp_patch.json()
    patched_item = next(i for i in shipment_after["items"] if i["id"] == item_id)
    assert patched_item["final_qty"] == 50
    assert patched_item["explanation"] == "Manual adjustment"
    assert shipment_after["updated_at"] != old_updated_at

    # 404 for non-existing shipment
    resp_order_404 = client.patch(
        "/api/v1/wb/manager/shipment/999999/items/1",
        json=patch_payload,
    )
    assert resp_order_404.status_code == 404
    assert resp_order_404.json()["detail"] == {
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

    # 404 for non-existing item in existing draft shipment
    resp_item_404 = client.patch(
        f"/api/v1/wb/manager/shipment/{shipment_id}/items/999999",
        json=patch_payload,
    )
    assert resp_item_404.status_code == 404
    assert resp_item_404.json()["detail"] == {
        "code": "wb_shipment_item_not_found",
        "message": "WbShipmentItem not found",
        "shipment_id": shipment_id,
        "item_id": 999999,
        "field": "item_id",
        "field_metadata": {
            "description": "Requested WB shipment item identifier within shipment scope",
            "type": "int",
        },
        "next_steps": ["use_existing_wb_shipment_item_id"],
    }

    # Change status to approved
    resp_status = client.patch(
        f"/api/v1/wb/manager/shipment/{shipment_id}",
        json={"status": "approved"},
    )
    assert resp_status.status_code == 200

    # Further attempts to patch items must fail with 400
    resp_forbidden = client.patch(
        f"/api/v1/wb/manager/shipment/{shipment_id}/items/{item_id}",
        json=patch_payload,
    )
    assert resp_forbidden.status_code == 400
    assert resp_forbidden.json()["detail"] == {
        "code": "wb_shipment_item_non_draft_locked",
        "message": "Cannot modify items of a non-draft shipment",
        "shipment_id": shipment_id,
        "field": "status",
        "field_metadata": {
            "description": "Current WB shipment status blocking item updates",
            "type": "string",
        },
        "status": "approved",
        "next_steps": ["use_draft_shipment_for_item_updates"],
    }


def test_update_shipment_item_returns_structured_400_when_final_qty_exceeds_stock(client, db_session):
    article, target_date = _setup_article_for_replenishment(
        db_session, code="SHIP-API-STOCK-LIMIT"
    )

    payload = {
        "target_date": target_date.isoformat(),
        "wb_arrival_date": target_date.isoformat(),
        "comment": "stock limit",
    }

    resp_create = client.post(
        "/api/v1/wb/manager/shipment/from-proposal",
        json=payload,
    )
    assert resp_create.status_code == 201, resp_create.text
    shipment = resp_create.json()
    shipment_id = shipment["id"]
    item = shipment["items"][0]

    response = client.patch(
        f"/api/v1/wb/manager/shipment/{shipment_id}/items/{item['id']}",
        json={"final_qty": int(item["nsk_stock_available"]) + 1},
    )
    assert response.status_code == 400, response.text
    assert response.json()["detail"] == {
        "code": "wb_shipment_item_final_qty_exceeds_stock",
        "message": "final_qty exceeds available NSC stock",
        "shipment_id": shipment_id,
        "item_id": item["id"],
        "final_qty": int(item["nsk_stock_available"]) + 1,
        "nsk_stock_available": int(item["nsk_stock_available"]),
        "field": "final_qty",
        "field_metadata": {
            "description": "Requested final shipment quantity",
            "type": "int",
        },
        "next_steps": ["use_final_qty_not_greater_than_nsk_stock_available"],
    }


def test_shipment_headers_basic_aggregates(client, db_session):
	"""GET /shipment/headers returns aggregates per shipment without items list."""
	now = datetime.now(timezone.utc)
	shipment = WbShipment(
		status="draft",
		target_date=date(2025, 1, 1),
		wb_arrival_date=date(2025, 1, 2),
		comment="Header test",
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

	items = [
		WbShipmentItem(
			shipment_id=shipment.id,
			article_id=1,
			color_id=1,
			size_id=1,
			wb_sku=None,
			recommended_qty=10,
			final_qty=10,
			nsk_stock_available=0,
			oos_risk_before="red",
			oos_risk_after="red",
			limited_by_nsk_stock=False,
			limited_by_max_coverage=False,
			ignored_due_to_zero_sales=False,
			below_min_coverage_threshold=False,
			article_total_deficit=0,
			article_total_recommended=0,
			explanation=None,
		),
		WbShipmentItem(
			shipment_id=shipment.id,
			article_id=1,
			color_id=1,
			size_id=1,
			wb_sku=None,
			recommended_qty=20,
			final_qty=20,
			nsk_stock_available=0,
			oos_risk_before="yellow",
			oos_risk_after="yellow",
			limited_by_nsk_stock=False,
			limited_by_max_coverage=False,
			ignored_due_to_zero_sales=False,
			below_min_coverage_threshold=False,
			article_total_deficit=0,
			article_total_recommended=0,
			explanation=None,
		),
		WbShipmentItem(
			shipment_id=shipment.id,
			article_id=1,
			color_id=1,
			size_id=1,
			wb_sku=None,
			recommended_qty=30,
			final_qty=30,
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
		),
	]
	db_session.add_all(items)
	db_session.commit()

	resp = client.get("/api/v1/wb/manager/shipment/headers")
	assert resp.status_code == 200, resp.text
	body = resp.json()
	assert len(body) == 1
	h = body[0]
	assert set(h.keys()) == {
		"id",
		"status",
		"target_date",
		"wb_arrival_date",
		"comment",
		"created_at",
		"updated_at",
		"total_final_qty",
		"total_items",
		"red_risk_count",
		"yellow_risk_count",
	}
	assert h["id"] == shipment.id
	assert h["status"] == shipment.status
	assert h["target_date"] == "2025-01-01"
	assert h["wb_arrival_date"] == "2025-01-02"
	assert h["comment"] == "Header test"
	assert _parse_json_datetime(h["created_at"]) == _normalize_datetime(shipment.created_at)
	assert _parse_json_datetime(h["updated_at"]) == _normalize_datetime(shipment.updated_at)
	assert h["total_items"] == 3
	assert h["total_final_qty"] == 10 + 20 + 30
	assert h["red_risk_count"] == 1
	assert h["yellow_risk_count"] == 1
	assert "items" not in h


def test_shipment_headers_filter_by_status(client, db_session):
	now = datetime.now(timezone.utc)
	shipment_draft = WbShipment(
		status="draft",
		target_date=date(2025, 1, 1),
		wb_arrival_date=date(2025, 1, 1),
		comment=None,
		created_at=now,
		updated_at=now,
		strategy="normal",
		zero_sales_policy="ignore",
		target_coverage_days=30,
		min_coverage_days=7,
		max_coverage_days_after=60,
		max_replenishment_per_article=None,
	)
	shipment_approved = WbShipment(
		status="approved",
		target_date=date(2025, 1, 2),
		wb_arrival_date=date(2025, 1, 2),
		comment=None,
		created_at=now,
		updated_at=now,
		strategy="normal",
		zero_sales_policy="ignore",
		target_coverage_days=30,
		min_coverage_days=7,
		max_coverage_days_after=60,
		max_replenishment_per_article=None,
	)
	db_session.add_all([shipment_draft, shipment_approved])
	db_session.flush()

	for sh in [shipment_draft, shipment_approved]:
		item = WbShipmentItem(
			shipment_id=sh.id,
			article_id=1,
			color_id=1,
			size_id=1,
			wb_sku=None,
			recommended_qty=5,
			final_qty=5,
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

	db_session.commit()

	resp = client.get("/api/v1/wb/manager/shipment/headers", params={"status": "draft"})
	assert resp.status_code == 200
	body = resp.json()
	assert {h["id"] for h in body} == {shipment_draft.id}


def test_shipment_headers_filter_by_article_id(client, db_session):
	now = datetime.now(timezone.utc)
	shipment1 = WbShipment(
		status="draft",
		target_date=date(2025, 1, 1),
		wb_arrival_date=date(2025, 1, 1),
		comment=None,
		created_at=now,
		updated_at=now,
		strategy="normal",
		zero_sales_policy="ignore",
		target_coverage_days=30,
		min_coverage_days=7,
		max_coverage_days_after=60,
		max_replenishment_per_article=None,
	)
	shipment2 = WbShipment(
		status="draft",
		target_date=date(2025, 1, 2),
		wb_arrival_date=date(2025, 1, 2),
		comment=None,
		created_at=now,
		updated_at=now,
		strategy="normal",
		zero_sales_policy="ignore",
		target_coverage_days=30,
		min_coverage_days=7,
		max_coverage_days_after=60,
		max_replenishment_per_article=None,
	)
	db_session.add_all([shipment1, shipment2])
	db_session.flush()

	item1 = WbShipmentItem(
		shipment_id=shipment1.id,
		article_id=5,
		color_id=1,
		size_id=1,
		wb_sku=None,
		recommended_qty=5,
		final_qty=5,
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
	item2 = WbShipmentItem(
		shipment_id=shipment2.id,
		article_id=7,
		color_id=1,
		size_id=1,
		wb_sku=None,
		recommended_qty=5,
		final_qty=5,
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
	db_session.add_all([item1, item2])
	db_session.commit()

	resp = client.get(
		"/api/v1/wb/manager/shipment/headers",
		params={"article_id": 5},
	)
	assert resp.status_code == 200
	body = resp.json()
	assert {h["id"] for h in body} == {shipment1.id}


def test_shipment_headers_pagination_and_sorting(client, db_session):
	now = datetime.now(timezone.utc)
	shipments = []
	for i, day in enumerate([1, 2, 3], start=1):
		sh = WbShipment(
			status="draft",
			target_date=date(2025, 1, day),
			wb_arrival_date=date(2025, 1, day),
			comment=f"S{day}",
			created_at=now.replace(day=day),
			updated_at=now.replace(day=day),
			strategy="normal",
			zero_sales_policy="ignore",
			target_coverage_days=30,
			min_coverage_days=7,
			max_coverage_days_after=60,
			max_replenishment_per_article=None,
		)
		shipments.append(sh)
		db_session.add(sh)

	db_session.flush()

	for sh in shipments:
		item = WbShipmentItem(
			shipment_id=sh.id,
			article_id=1,
			color_id=1,
			size_id=1,
			wb_sku=None,
			recommended_qty=5,
			final_qty=5,
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

	db_session.commit()

	resp_page1 = client.get(
		"/api/v1/wb/manager/shipment/headers",
		params={"sort_by": "created_at", "sort_dir": "asc", "limit": 2, "offset": 0},
	)
	assert resp_page1.status_code == 200
	body1 = resp_page1.json()
	assert len(body1) == 2
	assert [h["comment"] for h in body1] == ["S1", "S2"]

	resp_page2 = client.get(
		"/api/v1/wb/manager/shipment/headers",
		params={"sort_by": "created_at", "sort_dir": "asc", "limit": 2, "offset": 2},
	)
	body2 = resp_page2.json()
	assert len(body2) == 1
	assert [h["comment"] for h in body2] == ["S3"]


def test_shipment_headers_invalid_sort_by(client):
	resp = client.get(
		"/api/v1/wb/manager/shipment/headers",
		params={"sort_by": "nonexistent_field"},
	)
	assert resp.status_code == 400
	assert resp.json()["detail"] == {
		"code": "invalid_sort_by",
		"message": "Invalid sort_by 'nonexistent_field'",
		"field": "sort_by",
		"field_metadata": {
			"description": "Shipment header sort field query parameter",
			"type": "string",
		},
		"sort_by": "nonexistent_field",
		"allowed_values": ["created_at", "id", "status", "target_date", "updated_at", "wb_arrival_date"],
		"next_steps": ["use_supported_shipment_sort_by"],
	}


def test_shipment_headers_invalid_sort_dir(client):
	resp = client.get(
		"/api/v1/wb/manager/shipment/headers",
		params={"sort_dir": "sideways"},
	)
	assert resp.status_code == 400
	assert resp.json()["detail"] == {
		"code": "invalid_sort_dir",
		"message": "Invalid sort_dir",
		"field": "sort_dir",
		"field_metadata": {
			"description": "Shipment header sort direction query parameter",
			"type": "Literal['asc','desc']",
		},
		"sort_dir": "sideways",
		"allowed_values": ["asc", "desc"],
		"next_steps": ["use_sort_dir_asc_or_desc"],
	}


def test_shipment_preset_no_history(client, db_session):
	target_date = "2025-02-01"

	resp = client.get(
		"/api/v1/wb/manager/shipment/preset",
		params={"target_date": target_date},
	)
	assert resp.status_code == 200, resp.text
	body = resp.json()

	assert body == {
		"target_date": target_date,
		"suggested_wb_arrival_date": "2025-02-08",
		"suggested_strategy": "normal",
		"suggested_zero_sales_policy": "ignore",
		"suggested_target_coverage_days": 30,
		"suggested_min_coverage_days": 7,
		"suggested_max_coverage_days_after": 60,
		"suggested_max_replenishment_per_article": None,
		"recent_shipments": [],
		"avg_total_final_qty_last3": None,
		"last_shipment_total_final_qty": None,
		"default_comment_template": "WB shipment for coverage ~30 days (ETA 2025-02-08)",
		"explanation": (
			"No non-cancelled WB shipments found. Used global defaults: "
			"strategy=normal, zero_sales_policy=ignore, target_coverage_days=30, "
			"min_coverage_days=7, max_coverage_days_after=60, transit_days=7."
		),
	}


def test_shipment_preset_with_history(client, db_session):
	now = datetime(2025, 1, 1, tzinfo=timezone.utc)

	def _make_shipment(
		status: str,
		target: date,
		arrival: date,
		created: datetime,
		total_final_qty: int,
	):
		shipment = WbShipment(
			status=status,
			target_date=target,
			wb_arrival_date=arrival,
			comment=None,
			created_at=created,
			updated_at=created,
			strategy="aggressive",
			zero_sales_policy="keep",
			target_coverage_days=45,
			min_coverage_days=10,
			max_coverage_days_after=90,
			max_replenishment_per_article=123,
		)
		db_session.add(shipment)
		db_session.flush()

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

	older = _make_shipment(
		status="approved",
		target=date(2025, 1, 1),
		arrival=date(2025, 1, 8),
		created=now,
		total_final_qty=100,
	)
	latest = _make_shipment(
		status="shipped",
		target=date(2025, 1, 2),
		arrival=date(2025, 1, 9),
		created=now.replace(day=2),
		total_final_qty=200,
	)
	db_session.commit()

	resp = client.get(
		"/api/v1/wb/manager/shipment/preset",
		params={"target_date": "2025-02-01"},
	)
	assert resp.status_code == 200, resp.text
	body = resp.json()

	assert set(body.keys()) == {
		"target_date",
		"suggested_wb_arrival_date",
		"suggested_strategy",
		"suggested_zero_sales_policy",
		"suggested_target_coverage_days",
		"suggested_min_coverage_days",
		"suggested_max_coverage_days_after",
		"suggested_max_replenishment_per_article",
		"recent_shipments",
		"avg_total_final_qty_last3",
		"last_shipment_total_final_qty",
		"default_comment_template",
		"explanation",
	}

	assert body["target_date"] == "2025-02-01"
	assert body["suggested_strategy"] == "aggressive"
	assert body["suggested_zero_sales_policy"] == "keep"
	assert body["suggested_target_coverage_days"] == 45
	assert body["suggested_min_coverage_days"] == 10
	assert body["suggested_max_coverage_days_after"] == 90
	assert body["suggested_max_replenishment_per_article"] == 123

	assert body["suggested_wb_arrival_date"] == "2025-02-08"
	assert body["avg_total_final_qty_last3"] == 150.0
	assert body["last_shipment_total_final_qty"] == 200
	assert body["default_comment_template"] == "WB shipment for coverage ~45 days (ETA 2025-02-08)"
	assert body["explanation"] == (
		f"Defaults derived from last non-cancelled shipment #{latest.id} "
		f"(created_at={latest.created_at.isoformat()}). "
		"transit_days≈7, "
		"strategy=aggressive, "
		"zero_sales_policy=keep, "
		"target_coverage_days=45, "
		"min_coverage_days=10, "
		"max_coverage_days_after=90."
	)

	recent = body["recent_shipments"]
	assert len(recent) == 2

	expected_recent = [
		(latest, "shipped", "2025-01-02", "2025-01-09", 200, 1),
		(older, "approved", "2025-01-01", "2025-01-08", 100, 1),
	]
	for payload_item, (shipment_obj, status_value, target_value, arrival_value, total_final_qty, total_items) in zip(recent, expected_recent):
		assert set(payload_item.keys()) == {
			"id",
			"status",
			"target_date",
			"wb_arrival_date",
			"created_at",
			"updated_at",
			"total_final_qty",
			"total_items",
		}
		assert payload_item["id"] == shipment_obj.id
		assert payload_item["status"] == status_value
		assert payload_item["target_date"] == target_value
		assert payload_item["wb_arrival_date"] == arrival_value
		assert payload_item["total_final_qty"] == total_final_qty
		assert payload_item["total_items"] == total_items
		assert _parse_json_datetime(payload_item["created_at"]) == _normalize_datetime(shipment_obj.created_at)
		assert _parse_json_datetime(payload_item["updated_at"]) == _normalize_datetime(shipment_obj.updated_at)


def test_shipment_preset_required_param(client):
	resp = client.get("/api/v1/wb/manager/shipment/preset")
	assert resp.status_code == 422
