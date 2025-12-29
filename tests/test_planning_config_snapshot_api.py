from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.db import get_db
from app.models.models import Article
from tests.test_utils import (
    create_article,
    create_article_planning_settings,
    create_color,
    create_color_planning_settings,
    create_elastic_planning_settings,
    create_global_planning_settings,
    create_planning_settings,
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


def _setup_full_planning_config(db_session):
    article = create_article(db_session, code="CFG-SNAP-1")

    # Global settings used by demand_engine
    create_global_planning_settings(
        db_session,
        default_target_coverage_days=10,
        default_lead_time_days=70,
        default_service_level_percent=90,
        default_fabric_min_batch_qty=7000,
        default_elastic_min_batch_qty=3000,
    )

    # Article planning settings (used + experimental fields)
    create_article_planning_settings(
        db_session,
        article,
        target_coverage_days=12,
        include_in_planning=True,
        priority=5,
        lead_time_days=30,
        service_level_percent=95,
    )

    # Main planning settings (used + experimental fields)
    create_planning_settings(
        db_session,
        article,
        is_active=True,
        min_fabric_batch=500,
        min_elastic_batch=500,
        alert_threshold_days=7,
        safety_stock_days=14,
        strictness=1.2,
        notes="test-notes",
    )

    # Color-level minima
    color = create_color(db_session, inner_code="CFG-COLOR-1")
    create_color_planning_settings(
        db_session,
        article=article,
        color=color,
        fabric_min_batch_qty=300,
    )

    # Elastic minima
    create_elastic_planning_settings(
        db_session,
        article=article,
        elastic_min_batch_qty=1000,
    )

    return article


def test_planning_config_snapshot_happy_path_single_article(client, db_session):
    article = _setup_full_planning_config(db_session)

    resp = client.get(
        "/api/v1/planning/config-snapshot",
        params={"article_id": article.id},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # Global settings
    gs = body["global_settings"]
    assert gs["default_target_coverage_days"] == 10
    assert "experimental" in gs

    # Single article snapshot
    articles = body["articles"]
    assert len(articles) == 1
    snap = articles[0]

    assert snap["article_id"] == article.id
    assert snap["article_code"] == article.code

    # Article-level planning settings
    aps = snap["article_planning_settings"]
    assert aps["target_coverage_days"] == 12
    assert aps["experimental"]["priority"] == 5
    assert aps["experimental"]["include_in_planning"] is True
    assert aps["experimental"]["lead_time_days"] == 30
    assert aps["experimental"]["service_level_percent"] == 95

    # Main planning settings
    ps = snap["planning_settings"]
    assert ps["is_active"] is True
    assert ps["min_fabric_batch"] == 500
    assert ps["min_elastic_batch"] == 500
    assert ps["strictness"] == pytest.approx(1.2)
    assert ps["experimental"]["alert_threshold_days"] == 7
    assert ps["experimental"]["safety_stock_days"] == 14
    assert ps["experimental"]["notes"] == "test-notes"

    # Color settings
    color_settings = snap["color_settings"]
    assert len(color_settings) == 1
    cs = color_settings[0]
    assert cs["color_id"] is not None
    assert cs["fabric_min_batch_qty"] == 300

    # Elastic settings
    elastic_settings = snap["elastic_settings"]
    assert len(elastic_settings) == 1
    es = elastic_settings[0]
    assert es["elastic_type_id"] > 0
    assert isinstance(es["elastic_type_name"], str) and es["elastic_type_name"]
    assert es["elastic_min_batch_qty"] == 1000


def test_planning_config_snapshot_article_not_found(client):
    resp = client.get(
        "/api/v1/planning/config-snapshot",
        params={"article_id": 999999},
    )
    assert resp.status_code == 404
    body = resp.json()
    assert body["detail"] == "Article not found"


def test_planning_config_snapshot_article_without_settings_returns_404(client, db_session):
    article = create_article(db_session, code="CFG-NO-SETTINGS")

    resp = client.get(
        "/api/v1/planning/config-snapshot",
        params={"article_id": article.id},
    )
    assert resp.status_code == 404
    body = resp.json()
    assert body["detail"] == "No planning settings found for this article"


def test_planning_config_snapshot_without_article_id_lists_active_planning_settings(client, db_session):
    # Global settings (optional but keeps behavior consistent with other tests)
    create_global_planning_settings(db_session)

    art_active = create_article(db_session, code="CFG-ACTIVE")
    art_inactive = create_article(db_session, code="CFG-INACTIVE")

    # Active planning settings
    create_planning_settings(
        db_session,
        art_active,
        is_active=True,
        min_fabric_batch=100,
        min_elastic_batch=100,
        strictness=1.0,
    )

    # Inactive planning settings
    create_planning_settings(
        db_session,
        art_inactive,
        is_active=False,
        min_fabric_batch=200,
        min_elastic_batch=200,
        strictness=1.0,
    )

    resp = client.get("/api/v1/planning/config-snapshot")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    ids = {a["article_id"] for a in body["articles"]}
    assert art_active.id in ids
    assert art_inactive.id not in ids
