from __future__ import annotations

from datetime import date

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.core.db import get_db
from app.main import app
from app.models.models import PlanningSettings
from app.schemas.order_proposal import OrderProposalResponse
from app.services import order_explanation
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


def _setup_basic_article_with_deficit(db_session, code: str = "EXPL-A-1"):
    article = create_article(db_session, code=code)

    size_s = create_size(db_session, label=f"S-{code}", sort_order=1)
    color = create_color(db_session, inner_code=f"EXPL-C1-{code}")
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

    wb_sku = f"SKU-{code}"
    target_date = date.today()
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


def test_build_order_explanation_for_article_rejects_unknown_article_with_structured_detail(db_session):
    with pytest.raises(HTTPException) as exc:
        order_explanation.build_order_explanation_for_article(
            db=db_session,
            article_id=999999999,
        )

    assert exc.value.status_code == 404
    assert exc.value.detail == {
        "code": "article_not_found",
        "message": "Article not found",
        "article_id": 999999999,
        "field": "article_id",
        "field_metadata": {
            "description": "Requested article identifier",
            "type": "int",
        },
        "next_steps": ["use_existing_article_id"],
    }


def test_build_order_explanation_for_article_scopes_legacy_proposal_to_requested_article(
    db_session,
    monkeypatch,
):
    article, _color = _setup_basic_article_with_deficit(db_session)
    captured: dict[str, object] = {}

    def fake_generate_order_proposal(*, db, target_date, explanation, article_ids=None):
        captured["db"] = db
        captured["target_date"] = target_date
        captured["explanation"] = explanation
        captured["article_ids"] = article_ids
        return OrderProposalResponse(
            target_date=target_date,
            items=[],
            global_explanation=None,
        )

    monkeypatch.setattr(
        order_explanation,
        "generate_order_proposal",
        fake_generate_order_proposal,
    )

    explanation = order_explanation.build_order_explanation_for_article(
        db=db_session,
        article_id=article.id,
    )

    assert explanation.article_id == article.id
    assert explanation.reasons == []
    assert captured["db"] is db_session
    assert captured["explanation"] is True
    assert captured["article_ids"] == [article.id]


def test_build_order_explanation_portfolio_reuses_shared_scoped_proposal_for_requested_articles(
    db_session,
    monkeypatch,
):
    article_a, _color_a = _setup_basic_article_with_deficit(db_session, code="EXPL-SHARED-A")
    article_b, _color_b = _setup_basic_article_with_deficit(db_session, code="EXPL-SHARED-B")
    calls: list[dict[str, object]] = []

    def fake_generate_order_proposal(*, db, target_date, explanation, article_ids=None):
        calls.append(
            {
                "db": db,
                "target_date": target_date,
                "explanation": explanation,
                "article_ids": article_ids,
            }
        )
        return OrderProposalResponse(
            target_date=target_date,
            items=[],
            global_explanation=None,
        )

    monkeypatch.setattr(
        order_explanation,
        "generate_order_proposal",
        fake_generate_order_proposal,
    )

    portfolio = order_explanation.build_order_explanation_portfolio(
        db=db_session,
        article_ids=[article_a.id, article_b.id, article_a.id],
    )

    assert {item.article_id for item in portfolio} == {article_a.id, article_b.id}
    assert all(item.reasons == [] for item in portfolio)
    assert len(calls) == 1
    assert calls[0]["db"] is db_session
    assert calls[0]["explanation"] is True
    assert calls[0]["article_ids"] == [article_a.id, article_b.id]


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


def test_filtering_by_article_ids_skips_unknown_article_ids(client, db_session):
    article_active, _color_active = _setup_basic_article_with_deficit(db_session)

    response = client.get(
        "/api/v1/planning/order-explanation-portfolio",
        params={"article_ids": [article_active.id, 999999999]},
    )
    assert response.status_code == 200, response.text

    body = response.json()
    ids = {item["article_id"] for item in body["items"]}
    assert ids == {article_active.id}
