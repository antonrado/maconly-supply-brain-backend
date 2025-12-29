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
        "comment": "Test shipment from proposal",
    }

    resp = client.post(
        "/api/v1/wb/manager/shipment/from-proposal",
        json=payload,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()

    assert body["status"] == "draft"
    assert body["target_date"] == target_date.isoformat()
    assert body["wb_arrival_date"] == target_date.isoformat()
    assert body["comment"] == "Test shipment from proposal"
    assert body["items"]

    shipment_id = body["id"]
    items = body["items"]
    assert items[0]["final_qty"] == items[0]["recommended_qty"]

    items_db = (
        db_session.query(WbShipmentItem)
        .filter(WbShipmentItem.shipment_id == shipment_id)
        .all()
    )
    assert len(items_db) == len(items)


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
    assert {s["status"] for s in body_all} == {"draft", "approved"}

    # By status
    resp_draft = client.get("/api/v1/wb/manager/shipment/", params={"status": "draft"})
    assert {s["status"] for s in resp_draft.json()} == {"draft"}

    # By article_id
    resp_article1 = client.get(
        "/api/v1/wb/manager/shipment/",
        params={"article_id": article1.id},
    )
    assert resp_article1.status_code == 200
    body_a1 = resp_article1.json()
    assert body_a1
    assert {s["id"] for s in body_a1} == {s1.id}

    # By date range
    resp_date = client.get(
        "/api/v1/wb/manager/shipment/",
        params={"date_from": "2025-01-02", "date_to": "2025-01-02"},
    )
    body_date = resp_date.json()
    assert {s["id"] for s in body_date} == {s2.id}


def test_get_shipment_by_id(client, db_session):
    now = datetime.now(timezone.utc)
    shipment = WbShipment(
        status="draft",
        target_date=date(2025, 1, 1),
        wb_arrival_date=date(2025, 1, 1),
        comment="Test get",
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

    resp_ok = client.get(f"/api/v1/wb/manager/shipment/{shipment.id}")
    assert resp_ok.status_code == 200
    body = resp_ok.json()
    assert body["id"] == shipment.id
    assert body["comment"] == "Test get"

    resp_404 = client.get("/api/v1/wb/manager/shipment/999999")
    assert resp_404.status_code == 404


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
    old_updated_at = resp_before.json()["updated_at"]

    # Valid comment update
    resp = client.patch(
        f"/api/v1/wb/manager/shipment/{shipment.id}",
        json={"comment": "Updated by test"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["comment"] == "Updated by test"
    assert body["updated_at"] != old_updated_at

    # Invalid status value
    resp_bad = client.patch(
        f"/api/v1/wb/manager/shipment/{shipment.id}",
        json={"status": "weird"},
    )
    assert resp_bad.status_code == 400
    assert "Invalid status" in resp_bad.json().get("detail", "")


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

    patch_payload = {"final_qty": 999, "explanation": "Manual adjustment"}

    # Successful patch in draft status
    resp_patch = client.patch(
        f"/api/v1/wb/manager/shipment/{shipment_id}/items/{item_id}",
        json=patch_payload,
    )
    assert resp_patch.status_code == 200
    shipment_after = resp_patch.json()
    patched_item = next(i for i in shipment_after["items"] if i["id"] == item_id)
    assert patched_item["final_qty"] == 999
    assert patched_item["explanation"] == "Manual adjustment"
    assert shipment_after["updated_at"] != old_updated_at

    # 404 for non-existing shipment
    resp_order_404 = client.patch(
        "/api/v1/wb/manager/shipment/999999/items/1",
        json=patch_payload,
    )
    assert resp_order_404.status_code == 404

    # 404 for non-existing item in existing draft shipment
    resp_item_404 = client.patch(
        f"/api/v1/wb/manager/shipment/{shipment_id}/items/999999",
        json=patch_payload,
    )
    assert resp_item_404.status_code == 404

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
    assert "Cannot modify items of a non-draft shipment" in resp_forbidden.json().get(
        "detail", ""
    )


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
	assert h["id"] == shipment.id
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
	body = resp.json()
	assert "Invalid sort_by" in body.get("detail", "")


def test_shipment_headers_invalid_sort_dir(client):
	resp = client.get(
		"/api/v1/wb/manager/shipment/headers",
		params={"sort_dir": "sideways"},
	)
	assert resp.status_code == 400
	body = resp.json()
	assert "Invalid sort_dir" in body.get("detail", "")


def test_shipment_preset_no_history(client, db_session):
	target_date = "2025-02-01"

	resp = client.get(
		"/api/v1/wb/manager/shipment/preset",
		params={"target_date": target_date},
	)
	assert resp.status_code == 200, resp.text
	body = resp.json()

	assert body["target_date"] == target_date
	assert body["suggested_wb_arrival_date"] == "2025-02-08"

	assert body["suggested_strategy"] == "normal"
	assert body["suggested_zero_sales_policy"] == "ignore"
	assert body["suggested_target_coverage_days"] == 30
	assert body["suggested_min_coverage_days"] == 7
	assert body["suggested_max_coverage_days_after"] == 60
	assert body["suggested_max_replenishment_per_article"] is None

	assert body["recent_shipments"] == []
	assert body["avg_total_final_qty_last3"] is None
	assert body["last_shipment_total_final_qty"] is None
	assert "No non-cancelled WB shipments found" in body["explanation"]


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

	_make_shipment(
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

	assert body["suggested_strategy"] == "aggressive"
	assert body["suggested_zero_sales_policy"] == "keep"
	assert body["suggested_target_coverage_days"] == 45
	assert body["suggested_min_coverage_days"] == 10
	assert body["suggested_max_coverage_days_after"] == 90
	assert body["suggested_max_replenishment_per_article"] == 123

	assert body["suggested_wb_arrival_date"] == "2025-02-08"

	recent = body["recent_shipments"]
	assert recent
	assert recent[0]["id"] == latest.id
	assert recent[0]["total_final_qty"] == 200
	assert recent[0]["total_items"] == 1

	assert body["last_shipment_total_final_qty"] == 200


def test_shipment_preset_required_param(client):
	resp = client.get("/api/v1/wb/manager/shipment/preset")
	assert resp.status_code == 422
