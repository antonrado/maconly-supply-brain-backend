from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.core.db import get_db
from app.main import app
from app.models.models import PlanningSettings
from tests.test_utils import (
    add_wb_sales,
    add_wb_stock,
    create_article,
    create_article_planning_settings,
    create_color,
    create_color_planning_settings,
    create_elastic_planning_settings,
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


def _setup_basic_article_with_deficit(db_session):
    article = create_article(db_session, code="EXPL-A-1")

    size_s = create_size(db_session, label="S", sort_order=1)
    color = create_color(db_session, inner_code="EXPL-C1")
    create_sku(db_session, article, color, size_s)

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

    wb_sku = "SKU-EXPL-A-1"
    target_date = date(2025, 1, 31)
    create_wb_mapping(db_session, article, wb_sku=wb_sku)
    add_wb_sales(db_session, wb_sku=wb_sku, day=target_date, sales_qty=10)
    add_wb_stock(db_session, wb_sku=wb_sku, stock_qty=0)

    return article, color


def test_happy_path_no_minima(client, db_session):
    article, _color = _setup_basic_article_with_deficit(db_session)

    resp = client.get("/api/v1/planning/order-explanation-portfolio")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert "items" in body
    items = body["items"]
    assert items

    art_entry = next(it for it in items if it["article_id"] == article.id)
    reasons = art_entry["reasons"]
    assert reasons

    r0 = reasons[0]
    assert r0["base_deficit"] > 0
    assert r0["strictness"] == pytest.approx(1.0)
    assert r0["adjusted_deficit"] >= r0["base_deficit"]
    assert r0["final_order_qty"] > 0
    assert r0["limiting_constraint"] in ("strictness", "none")
    assert "base_deficit" in r0["explanation"]


def test_fabric_minimum_binds(client, db_session):
    article, _color = _setup_basic_article_with_deficit(db_session)

    ps = (
        db_session.query(PlanningSettings)
        .filter(PlanningSettings.article_id == article.id)
        .first()
    )
    assert ps is not None
    ps.min_fabric_batch = 1000
    db_session.commit()

    resp = client.get("/api/v1/planning/order-explanation-portfolio")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    items = body["items"]
    art_entry = next(it for it in items if it["article_id"] == article.id)
    reasons = art_entry["reasons"]
    r0 = reasons[0]

    assert r0["final_order_qty"] == 1000
    assert r0["limiting_constraint"] == "fabric_min_batch"


def test_elastic_minimum_binds(client, db_session):
    article, _color = _setup_basic_article_with_deficit(db_session)

    create_elastic_planning_settings(db_session, article=article, elastic_min_batch_qty=1500)

    resp = client.get("/api/v1/planning/order-explanation-portfolio")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    items = body["items"]
    art_entry = next(it for it in items if it["article_id"] == article.id)
    reasons = art_entry["reasons"]
    r0 = reasons[0]

    assert r0["final_order_qty"] >= 1500
    assert r0["limiting_constraint"] in ("elastic_min_batch", "none")


def test_color_minimum_binds(client, db_session):
    article, color = _setup_basic_article_with_deficit(db_session)
    create_color_planning_settings(
        db_session,
        article=article,
        color=color,
        fabric_min_batch_qty=2000,
    )

    resp = client.get("/api/v1/planning/order-explanation-portfolio")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    items = body["items"]
    art_entry = next(it for it in items if it["article_id"] == article.id)
    reasons = art_entry["reasons"]
    assert reasons

    # Находим объяснение по нужному цвету
    reason_for_color = next(r for r in reasons if r["color_id"] == color.id)

    assert reason_for_color["final_order_qty"] == 2000
    assert reason_for_color["limiting_constraint"] == "color_min_batch"


def test_filtering_by_article_ids_and_is_active(client, db_session):
    article_active, _color_active = _setup_basic_article_with_deficit(db_session)
    article_inactive = create_article(db_session, code="EXPL-INACTIVE")

    size_s = create_size(db_session, label="S2", sort_order=1)
    color = create_color(db_session, inner_code="EXPL-C3")
    create_sku(db_session, article_inactive, color, size_s)

    create_global_planning_settings(db_session)
    create_article_planning_settings(db_session, article_inactive, target_coverage_days=10)
    create_planning_settings(
        db_session,
        article_inactive,
        is_active=False,
        min_fabric_batch=0,
        min_elastic_batch=0,
        strictness=1.0,
    )

    resp_all = client.get("/api/v1/planning/order-explanation-portfolio")
    assert resp_all.status_code == 200, resp_all.text
    body_all = resp_all.json()

    ids_all = {it["article_id"] for it in body_all["items"]}
    assert article_active.id in ids_all
    assert article_inactive.id not in ids_all

    resp_filtered = client.get(
        "/api/v1/planning/order-explanation-portfolio",
        params={"article_ids": [article_inactive.id]},
    )
    assert resp_filtered.status_code == 200, resp_filtered.text
    body_filtered = resp_filtered.json()

    ids_filtered = {it["article_id"] for it in body_filtered["items"]}
    assert article_inactive.id in ids_filtered
