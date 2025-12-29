from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.db import get_db
from app.models.models import (
    Article,
    BundleRecipe,
    BundleType,
    StockBalance,
    Warehouse,
)
from tests.test_utils import (
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


def _setup_article_with_bundles(db_session):
    article = create_article(db_session, code="BND-SNAP-1")

    size = create_size(db_session, label="S", sort_order=1)
    color_a = create_color(db_session, inner_code="C-A")
    color_b = create_color(db_session, inner_code="C-B")

    sku_a = create_sku(db_session, article, color_a, size)
    sku_b = create_sku(db_session, article, color_b, size)

    # NSC warehouse
    wh = Warehouse(code="NSK-1", name="NSK", type="internal")
    db_session.add(wh)
    db_session.flush()

    # NSC single stock: bottleneck on color B
    now = datetime.now(timezone.utc)
    db_session.add_all(
        [
            StockBalance(
                sku_unit_id=sku_a.id,
                warehouse_id=wh.id,
                quantity=10,
                updated_at=now,
            ),
            StockBalance(
                sku_unit_id=sku_b.id,
                warehouse_id=wh.id,
                quantity=5,
                updated_at=now,
            ),
        ]
    )

    # Bundle types 4/5/6 packs
    bt4 = BundleType(code="4pack", name="4pack")
    bt5 = BundleType(code="5pack", name="5pack")
    bt6 = BundleType(code="6pack", name="6pack")
    db_session.add_all([bt4, bt5, bt6])
    db_session.flush()

    # Recipes: each bundle type requires both colors for a given size
    for bt in (bt4, bt5, bt6):
        db_session.add_all(
            [
                BundleRecipe(
                    article_id=article.id,
                    bundle_type_id=bt.id,
                    color_id=color_a.id,
                    position=1,
                ),
                BundleRecipe(
                    article_id=article.id,
                    bundle_type_id=bt.id,
                    color_id=color_b.id,
                    position=2,
                ),
            ]
        )

    # WB bundle stock via mappings
    # 4pack: 2 bundles on WB, 5pack: 10 bundles, 6pack: 0 bundles
    mapping_4 = create_wb_mapping(
        db_session,
        article,
        wb_sku="WB-SKU-4",
        bundle_type_id=bt4.id,
        size_id=size.id,
    )
    mapping_5 = create_wb_mapping(
        db_session,
        article,
        wb_sku="WB-SKU-5",
        bundle_type_id=bt5.id,
        size_id=size.id,
    )
    mapping_6 = create_wb_mapping(
        db_session,
        article,
        wb_sku="WB-SKU-6",
        bundle_type_id=bt6.id,
        size_id=size.id,
    )

    add_wb_stock(db_session, wb_sku=mapping_4.wb_sku, stock_qty=2)
    add_wb_stock(db_session, wb_sku=mapping_5.wb_sku, stock_qty=10)
    add_wb_stock(db_session, wb_sku=mapping_6.wb_sku, stock_qty=0)

    db_session.commit()
    return article


def test_article_bundle_snapshot_happy_path(client, db_session):
    article = _setup_article_with_bundles(db_session)

    resp = client.get(
        "/api/v1/planning/article-bundle-snapshot",
        params={"article_id": article.id},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["article_id"] == article.id
    assert body["article_code"] == article.code

    # NSK single stock reflects both colors and correct quantities
    nsk_stock = body["nsk_single_sku_stock"]
    stock_map = {(row["color_id"], row["size_id"]): row["quantity"] for row in nsk_stock}
    assert len(stock_map) == 2
    assert sorted(stock_map.values()) == [5, 10]

    # WB bundle stock has entries for all three bundle types
    wb_stock = body["wb_bundle_stock"]
    assert {row["bundle_type_name"] for row in wb_stock} == {"4pack", "5pack", "6pack"}

    # Bundle coverage contains entries for 4/5/6 packs
    coverage = body["bundle_coverage"]
    by_type = {c["bundle_type_name"]: c for c in coverage}
    assert set(by_type.keys()) == {"4pack", "5pack", "6pack"}

    # Potential bundles from singles are limited by the bottleneck (qty=5 of color B)
    for name in ("4pack", "5pack", "6pack"):
        assert by_type[name]["potential_bundles_from_singles"] == 5

    # WB ready bundles reflect WB stock
    assert by_type["4pack"]["wb_ready_bundles"] == 2
    assert by_type["5pack"]["wb_ready_bundles"] == 10
    assert by_type["6pack"]["wb_ready_bundles"] == 0

    # NSC bundles are not modeled yet
    for name in by_type:
        assert by_type[name]["nsk_ready_bundles"] == 0
        assert "avg_daily_sales" in by_type[name]
        assert "days_of_cover" in by_type[name]
        assert "observation_window_days" in by_type[name]


def test_article_bundle_snapshot_article_not_found(client):
    resp = client.get(
        "/api/v1/planning/article-bundle-snapshot",
        params={"article_id": 999999},
    )
    assert resp.status_code == 404
    body = resp.json()
    assert body["detail"] == "Article not found"


def test_article_bundle_snapshot_no_bundle_recipes(client, db_session):
    # Article with singles but without any bundle recipes
    article = create_article(db_session, code="BND-NO-RECIPE")
    size = create_size(db_session, label="S", sort_order=1)
    color = create_color(db_session, inner_code="C-ONLY")
    sku = create_sku(db_session, article, color, size)

    wh = Warehouse(code="NSK-2", name="NSK", type="internal")
    db_session.add(wh)
    db_session.flush()

    now = datetime.now(timezone.utc)
    db_session.add(
        StockBalance(
            sku_unit_id=sku.id,
            warehouse_id=wh.id,
            quantity=7,
            updated_at=now,
        )
    )
    db_session.commit()

    resp = client.get(
        "/api/v1/planning/article-bundle-snapshot",
        params={"article_id": article.id},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # NSK singles are present, but there are no bundle recipes, so coverage is empty
    assert body["nsk_single_sku_stock"]
    assert body["bundle_coverage"] == []


def test_article_bundle_snapshot_zero_sales(client, db_session):
    article = _setup_article_with_bundles(db_session)

    resp = client.get(
        "/api/v1/planning/article-bundle-snapshot",
        params={"article_id": article.id},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    coverage = body["bundle_coverage"]
    by_type = {c["bundle_type_name"]: c for c in coverage}
    # For all bundle types with no sales data we expect zero avg_daily_sales and None days_of_cover
    for name in ("4pack", "5pack", "6pack"):
        entry = by_type[name]
        assert entry["avg_daily_sales"] == 0.0
        assert entry["days_of_cover"] is None


def _setup_article_with_bundles_and_sales(db_session):
    article = create_article(db_session, code="BND-SALES-1")

    size = create_size(db_session, label="S-SALES", sort_order=1)
    color_a = create_color(db_session, inner_code="C-A-SALES")
    color_b = create_color(db_session, inner_code="C-B-SALES")

    sku_a = create_sku(db_session, article, color_a, size)
    sku_b = create_sku(db_session, article, color_b, size)

    # NSC warehouse with stock allowing 40 bundles (bottleneck color B)
    wh = Warehouse(code="NSK-SALES", name="NSK", type="internal")
    db_session.add(wh)
    db_session.flush()

    now = datetime.now(timezone.utc)
    db_session.add_all(
        [
            StockBalance(
                sku_unit_id=sku_a.id,
                warehouse_id=wh.id,
                quantity=100,
                updated_at=now,
            ),
            StockBalance(
                sku_unit_id=sku_b.id,
                warehouse_id=wh.id,
                quantity=40,
                updated_at=now,
            ),
        ]
    )

    bt = BundleType(code="4pack-sales", name="4pack-sales")
    db_session.add(bt)
    db_session.flush()

    # Recipe requires both colors
    db_session.add_all(
        [
            BundleRecipe(
                article_id=article.id,
                bundle_type_id=bt.id,
                color_id=color_a.id,
                position=1,
            ),
            BundleRecipe(
                article_id=article.id,
                bundle_type_id=bt.id,
                color_id=color_b.id,
                position=2,
            ),
        ]
    )

    mapping = create_wb_mapping(
        db_session,
        article,
        wb_sku="WB-SKU-SALES",
        bundle_type_id=bt.id,
        size_id=size.id,
    )

    # WB stock is not important for sales stats, but we add a placeholder
    add_wb_stock(db_session, wb_sku=mapping.wb_sku, stock_qty=0)

    # Add WB sales: 10 consecutive days, 2 units per day => total 20
    base_day = date(2025, 1, 1)
    for i in range(10):
        add_wb_sales(
            db_session,
            wb_sku=mapping.wb_sku,
            day=base_day + timedelta(days=i),
            sales_qty=2,
        )

    db_session.commit()
    # Capacity from singles for this bundle type should be 40 (bottleneck color B)
    return article, bt, 40


def test_article_bundle_snapshot_sales_and_coverage(client, db_session):
    article, bundle_type, expected_total = _setup_article_with_bundles_and_sales(db_session)

    resp = client.get(
        "/api/v1/planning/article-bundle-snapshot",
        params={"article_id": article.id},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    coverage = body["bundle_coverage"]
    by_type_id = {c["bundle_type_id"]: c for c in coverage}
    entry = by_type_id[bundle_type.id]

    # Total available bundles equals capacity from singles (WB stock is zero here)
    assert entry["total_available_bundles"] == expected_total

    # Average daily sales: 20 units over 10 days => 2.0 per day
    assert entry["avg_daily_sales"] == pytest.approx(2.0)

    # Days of cover: total_available_bundles / avg_daily_sales => 40 / 2 = 20
    assert entry["days_of_cover"] == pytest.approx(20.0)

    # Observation window is fixed for now
    assert entry["observation_window_days"] == 30
