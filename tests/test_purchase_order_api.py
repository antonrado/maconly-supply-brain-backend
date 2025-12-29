from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.db import get_db
from app.models.models import PurchaseOrder, PurchaseOrderItem
from tests.test_utils import (
    add_wb_sales,
    add_wb_stock,
    create_article,
    create_article_planning_settings,
    create_color,
    create_global_planning_settings,
    create_planning_settings,
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


def _setup_article_with_non_zero_proposal(db_session):
    article = create_article(db_session, code="PO-api-A")
    size = create_size(db_session, label="S", sort_order=1)
    color = create_color(db_session, inner_code="C-api-A")
    create_sku(db_session, article, color, size)

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

    wb_sku = "SKU-PO-api-A"
    create_wb_mapping(db_session, article, wb_sku=wb_sku)
    target_date = date(2025, 1, 31)
    add_wb_sales(db_session, wb_sku=wb_sku, day=target_date, sales_qty=10)
    add_wb_stock(db_session, wb_sku=wb_sku, stock_qty=0)

    return article, target_date


def test_create_from_proposal_endpoint(client, db_session):
    """POST /purchase-order/from-proposal creates draft PO with items from proposal."""
    article, target_date = _setup_article_with_non_zero_proposal(db_session)

    payload = {
        "target_date": target_date.isoformat(),
        "comment": "Test PO from proposal",
        "explanation": True,
    }
    resp = client.post("/api/v1/purchase-order/from-proposal", json=payload)
    assert resp.status_code == 201, resp.text
    body = resp.json()

    assert body["status"] == "draft"
    assert body["target_date"] == target_date.isoformat()
    assert body["comment"] == "Test PO from proposal"
    assert body["items"]

    # Ensure items exist in DB and match response length
    order_id = body["id"]
    items_db = (
        db_session.query(PurchaseOrderItem)
        .filter(PurchaseOrderItem.purchase_order_id == order_id)
        .all()
    )
    assert len(items_db) == len(body["items"])


def test_list_purchase_orders_with_status_filter(client, db_session):
    """GET /purchase-order/ supports filtering by status."""
    now = datetime.now(timezone.utc)
    po_draft = PurchaseOrder(
        status="draft",
        target_date=date(2025, 1, 1),
        comment=None,
        external_ref=None,
        created_at=now,
        updated_at=now,
    )
    po_approved = PurchaseOrder(
        status="approved",
        target_date=date(2025, 1, 2),
        comment=None,
        external_ref=None,
        created_at=now,
        updated_at=now,
    )
    db_session.add_all([po_draft, po_approved])
    db_session.commit()

    resp_all = client.get("/api/v1/purchase-order/")
    assert resp_all.status_code == 200
    body_all = resp_all.json()
    assert {o["status"] for o in body_all} == {"draft", "approved"}

    resp_draft = client.get("/api/v1/purchase-order/", params={"status": "draft"})
    body_draft = resp_draft.json()
    assert {o["status"] for o in body_draft} == {"draft"}

    resp_approved = client.get("/api/v1/purchase-order/", params={"status": "approved"})
    body_approved = resp_approved.json()
    assert {o["status"] for o in body_approved} == {"approved"}


def test_get_purchase_order_by_id(client, db_session):
    now = datetime.now(timezone.utc)
    po = PurchaseOrder(
        status="draft",
        target_date=date(2025, 1, 1),
        comment="Test get",
        external_ref=None,
        created_at=now,
        updated_at=now,
    )
    db_session.add(po)
    db_session.commit()

    resp_ok = client.get(f"/api/v1/purchase-order/{po.id}")
    assert resp_ok.status_code == 200
    body = resp_ok.json()
    assert body["id"] == po.id
    assert body["comment"] == "Test get"

    resp_404 = client.get("/api/v1/purchase-order/999999")
    assert resp_404.status_code == 404


def test_patch_purchase_order_status_and_fields(client, db_session):
    now = datetime.now(timezone.utc)
    po = PurchaseOrder(
        status="draft",
        target_date=date(2025, 1, 1),
        comment=None,
        external_ref=None,
        created_at=now,
        updated_at=now,
    )
    db_session.add(po)
    db_session.commit()

    payload = {
        "status": "approved",
        "comment": "Approved by test",
        "external_ref": "PO-123",
    }
    resp = client.patch(f"/api/v1/purchase-order/{po.id}", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "approved"
    assert body["comment"] == "Approved by test"
    assert body["external_ref"] == "PO-123"

    # Invalid status
    resp_bad = client.patch(
        f"/api/v1/purchase-order/{po.id}",
        json={"status": "something-weird"},
    )
    assert resp_bad.status_code == 400
    assert "Invalid status" in resp_bad.json().get("detail", "")


def test_allowed_status_transitions(client, db_session):
    now = datetime.now(timezone.utc)
    po = PurchaseOrder(
        status="draft",
        target_date=date(2025, 1, 1),
        comment=None,
        external_ref=None,
        created_at=now,
        updated_at=now,
    )
    db_session.add(po)
    db_session.commit()

    # draft -> approved
    resp_approved = client.patch(
        f"/api/v1/purchase-order/{po.id}", json={"status": "approved"}
    )
    assert resp_approved.status_code == 200
    body_approved = resp_approved.json()
    assert body_approved["status"] == "approved"

    # approved -> cancelled
    resp_cancelled = client.patch(
        f"/api/v1/purchase-order/{po.id}", json={"status": "cancelled"}
    )
    assert resp_cancelled.status_code == 200
    body_cancelled = resp_cancelled.json()
    assert body_cancelled["status"] == "cancelled"


def test_invalid_status_transitions(client, db_session):
    now = datetime.now(timezone.utc)
    po_approved = PurchaseOrder(
        status="approved",
        target_date=date(2025, 1, 1),
        comment=None,
        external_ref=None,
        created_at=now,
        updated_at=now,
    )
    po_cancelled = PurchaseOrder(
        status="cancelled",
        target_date=date(2025, 1, 2),
        comment=None,
        external_ref=None,
        created_at=now,
        updated_at=now,
    )
    db_session.add_all([po_approved, po_cancelled])
    db_session.commit()

    # approved -> draft is forbidden
    resp_back_to_draft = client.patch(
        f"/api/v1/purchase-order/{po_approved.id}", json={"status": "draft"}
    )
    assert resp_back_to_draft.status_code == 400
    assert "Invalid status transition" in resp_back_to_draft.json().get("detail", "")

    # cancelled -> approved is forbidden
    resp_cancelled_to_approved = client.patch(
        f"/api/v1/purchase-order/{po_cancelled.id}", json={"status": "approved"}
    )
    assert resp_cancelled_to_approved.status_code == 400
    assert "Invalid status transition" in resp_cancelled_to_approved.json().get("detail", "")

    # cancelled -> draft is forbidden
    resp_cancelled_to_draft = client.patch(
        f"/api/v1/purchase-order/{po_cancelled.id}", json={"status": "draft"}
    )
    assert resp_cancelled_to_draft.status_code == 400
    assert "Invalid status transition" in resp_cancelled_to_draft.json().get("detail", "")


def test_purchase_order_updated_at_changes_on_patch(client, db_session):
    now = datetime.now(timezone.utc)
    po = PurchaseOrder(
        status="draft",
        target_date=date(2025, 1, 1),
        comment=None,
        external_ref=None,
        created_at=now,
        updated_at=now,
    )
    db_session.add(po)
    db_session.commit()

    resp_before = client.get(f"/api/v1/purchase-order/{po.id}")
    assert resp_before.status_code == 200
    old_updated_at = resp_before.json()["updated_at"]

    resp_patch = client.patch(
        f"/api/v1/purchase-order/{po.id}", json={"comment": "Updated by test"}
    )
    assert resp_patch.status_code == 200
    body = resp_patch.json()
    assert body["comment"] == "Updated by test"
    new_updated_at = body["updated_at"]
    assert new_updated_at != old_updated_at


def test_patch_purchase_order_item_respects_status_and_updates_timestamp(client, db_session):
    """PATCH /purchase-order/{id}/items/{item_id} allowed only in draft and updates updated_at."""
    # Prepare a real PO with items via API
    article, target_date = _setup_article_with_non_zero_proposal(db_session)
    resp_create = client.post(
        "/api/v1/purchase-order/from-proposal",
        json={
            "target_date": target_date.isoformat(),
            "comment": "For item patch",
            "explanation": True,
        },
    )
    assert resp_create.status_code == 201
    order = resp_create.json()
    order_id = order["id"]
    assert order["items"], "Expected items in created PO"
    item_id = order["items"][0]["id"]
    old_updated_at = order["updated_at"]

    patch_payload = {"quantity": 999, "notes": "Manual adjustment in test"}

    # Successful patch in draft status
    resp_patch = client.patch(
        f"/api/v1/purchase-order/{order_id}/items/{item_id}",
        json=patch_payload,
    )
    assert resp_patch.status_code == 200
    order_after = resp_patch.json()
    patched_item = next(i for i in order_after["items"] if i["id"] == item_id)
    assert patched_item["quantity"] == 999
    assert patched_item["notes"] == "Manual adjustment in test"
    new_updated_at = order_after["updated_at"]
    assert new_updated_at != old_updated_at

    # 404 for non-existing order (status check happens after order lookup)
    resp_order_404 = client.patch(
        "/api/v1/purchase-order/999999/items/1",
        json=patch_payload,
    )
    assert resp_order_404.status_code == 404

    # 404 for non-existing item in existing draft order
    resp_item_404 = client.patch(
        f"/api/v1/purchase-order/{order_id}/items/999999",
        json=patch_payload,
    )
    assert resp_item_404.status_code == 404

    # Change status to approved
    resp_status = client.patch(
        f"/api/v1/purchase-order/{order_id}", json={"status": "approved"}
    )
    assert resp_status.status_code == 200

    # Further attempts to patch items must fail with 400
    resp_forbidden = client.patch(
        f"/api/v1/purchase-order/{order_id}/items/{item_id}",
        json=patch_payload,
    )
    assert resp_forbidden.status_code == 400
    assert "Cannot modify items of a non-draft purchase order" in resp_forbidden.json().get(
        "detail", ""
    )
