from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.db import get_db
from app.models.models import BundleType, StockBalance, Warehouse
from tests.test_utils import (
    add_wb_sales,
    add_wb_stock,
    create_article,
    create_color,
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


def _create_article_bundle_with_planning_and_sales(
    db_session,
    *,
    code: str,
    total_available_bundles: int,
    sales_per_day: int,
    num_sales_days: int,
    is_active: bool = True,
):
    article = create_article(db_session, code=code)

    size = create_size(db_session, label=f"SZ-{code}", sort_order=1)
    color = create_color(db_session, inner_code=f"C-{code}")
    sku = create_sku(db_session, article, color, size)

    # Planning settings thresholds
    create_planning_settings(
        db_session,
        article,
        is_active=is_active,
        safety_stock_days=7,
        alert_threshold_days=14,
    )

    # NSC warehouse and stock defining capacity from singles
    wh = Warehouse(code=f"NSK-{code}", name="NSK", type="internal")
    db_session.add(wh)
    db_session.flush()

    now = datetime.now(timezone.utc)
    db_session.add(
        StockBalance(
            sku_unit_id=sku.id,
            warehouse_id=wh.id,
            quantity=total_available_bundles,
            updated_at=now,
        )
    )

    # Single bundle type per article
    bt = BundleType(code=f"BT-{code}", name=f"BT-{code}")
    db_session.add(bt)
    db_session.flush()

    # Recipe uses single color
    from app.models.models import BundleRecipe

    db_session.add(
        BundleRecipe(
            article_id=article.id,
            bundle_type_id=bt.id,
            color_id=color.id,
            position=1,
        )
    )

    mapping = create_wb_mapping(
        db_session,
        article,
        wb_sku=f"WB-{code}",
        bundle_type_id=bt.id,
        size_id=size.id,
    )

    # WB stock is not important for risk classification in these tests
    add_wb_stock(db_session, wb_sku=mapping.wb_sku, stock_qty=0)

    # WB sales: contiguous block of days with fixed sales_per_day
    if num_sales_days > 0:
        base_day = date(2025, 1, 1)
        for i in range(num_sales_days):
            add_wb_sales(
                db_session,
                wb_sku=mapping.wb_sku,
                day=base_day + timedelta(days=i),
                sales_qty=sales_per_day,
            )

    db_session.commit()
    return article, bt


def test_bundle_risk_portfolio_levels(client, db_session):
    # safety=7, alert=14, overstock=42
    # avg_daily_sales = 2.0 for all; we vary total_available_bundles
    # critical: days_of_cover <= 7 -> total=8 (8/2=4)
    a_crit, _ = _create_article_bundle_with_planning_and_sales(
        db_session,
        code="RISK-CRIT",
        total_available_bundles=8,
        sales_per_day=2,
        num_sales_days=10,
    )
    # warning: 7 < days <= 14 -> total=20 (20/2=10)
    a_warn, _ = _create_article_bundle_with_planning_and_sales(
        db_session,
        code="RISK-WARN",
        total_available_bundles=20,
        sales_per_day=2,
        num_sales_days=10,
    )
    # ok: 14 < days < 42 -> total=30 (30/2=15)
    a_ok, _ = _create_article_bundle_with_planning_and_sales(
        db_session,
        code="RISK-OK",
        total_available_bundles=30,
        sales_per_day=2,
        num_sales_days=10,
    )
    # overstock: days >= 42 -> total=100 (100/2=50)
    a_over, _ = _create_article_bundle_with_planning_and_sales(
        db_session,
        code="RISK-OVER",
        total_available_bundles=100,
        sales_per_day=2,
        num_sales_days=10,
    )

    resp = client.get("/api/v1/planning/bundle-risk-portfolio")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    items = body["items"]
    by_article = {e["article_code"]: e for e in items}

    assert by_article[a_crit.code]["risk_level"] == "critical"
    assert by_article[a_warn.code]["risk_level"] == "warning"
    assert by_article[a_ok.code]["risk_level"] == "ok"
    assert by_article[a_over.code]["risk_level"] == "overstock"

    # Check thresholds are exposed
    entry_ok = by_article[a_ok.code]
    assert entry_ok["safety_stock_days"] == 7
    assert entry_ok["alert_threshold_days"] == 14
    assert entry_ok["overstock_threshold_days"] == 42


def test_bundle_risk_portfolio_zero_sales_overstock(client, db_session):
    # Article with stock and zero avg_daily_sales should be treated as overstock
    article, _ = _create_article_bundle_with_planning_and_sales(
        db_session,
        code="RISK-ZERO",
        total_available_bundles=50,
        sales_per_day=0,
        num_sales_days=10,
    )

    resp = client.get("/api/v1/planning/bundle-risk-portfolio")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    items = body["items"]
    by_article = {e["article_code"]: e for e in items}
    entry = by_article[article.code]

    assert entry["total_available_bundles"] == 50
    assert entry["avg_daily_sales"] == 0.0
    assert entry["risk_level"] == "overstock"


def test_bundle_risk_portfolio_filters_article_ids_and_is_active(client, db_session):
    # First article is active, second is inactive in PlanningSettings
    a_active, _ = _create_article_bundle_with_planning_and_sales(
        db_session,
        code="RISK-ACTIVE",
        total_available_bundles=20,
        sales_per_day=2,
        num_sales_days=5,
        is_active=True,
    )
    a_inactive, _ = _create_article_bundle_with_planning_and_sales(
        db_session,
        code="RISK-INACTIVE",
        total_available_bundles=20,
        sales_per_day=2,
        num_sales_days=5,
        is_active=False,
    )

    # Without article_ids only active article should appear
    resp_all = client.get("/api/v1/planning/bundle-risk-portfolio")
    assert resp_all.status_code == 200, resp_all.text
    items_all = resp_all.json()["items"]
    codes_all = {e["article_code"] for e in items_all}
    assert a_active.code in codes_all
    assert a_inactive.code not in codes_all

    # With article_ids only the requested article should be returned,
    # even if it is inactive in PlanningSettings
    resp_filtered = client.get(
        "/api/v1/planning/bundle-risk-portfolio",
        params={"article_ids": [a_inactive.id]},
    )
    assert resp_filtered.status_code == 200, resp_filtered.text
    items_filtered = resp_filtered.json()["items"]
    codes_filtered = {e["article_code"] for e in items_filtered}
    assert codes_filtered == {a_inactive.code}
