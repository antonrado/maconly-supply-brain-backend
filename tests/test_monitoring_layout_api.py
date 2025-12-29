from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.monitoring_metrics import get_all_metrics, get_timeseries_metrics


ALLOWED_ENDPOINTS = {
    "/api/v1/planning/monitoring/status",
    "/api/v1/planning/monitoring/snapshot",
    "/api/v1/planning/monitoring/timeseries",
    "/api/v1/planning/monitoring/risk-focus",
}


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_monitoring_layout_basic_happy_path(client):
    resp = client.get("/api/v1/planning/monitoring/layout")
    assert resp.status_code == 200, resp.text

    body = resp.json()
    sections = body["sections"]
    assert isinstance(sections, list)
    assert len(sections) > 0

    tile_ids: set[str] = set()

    for section in sections:
        assert isinstance(section["id"], str) and section["id"]
        assert isinstance(section["title"], str) and section["title"]

        tiles = section["tiles"]
        assert isinstance(tiles, list)
        assert len(tiles) > 0

        for tile in tiles:
            tile_id = tile["id"]
            assert isinstance(tile_id, str) and tile_id
            assert tile_id not in tile_ids
            tile_ids.add(tile_id)

            assert isinstance(tile["title"], str)
            assert isinstance(tile["description"], str)
            assert tile["type"] in {"counter", "timeseries", "table_link"}
            assert tile["source_endpoint"] in ALLOWED_ENDPOINTS


def test_monitoring_layout_metrics_exist_in_catalog(client):
    resp = client.get("/api/v1/planning/monitoring/layout")
    assert resp.status_code == 200, resp.text

    body = resp.json()
    sections = body["sections"]

    used_metrics: set[str] = set()

    for section in sections:
        for tile in section["tiles"]:
            primary = tile["primary_metric"]
            if primary is not None:
                used_metrics.add(primary)

            secondary = tile["secondary_metrics"]
            if secondary:
                used_metrics.update(secondary)

    all_metrics = get_all_metrics()
    assert used_metrics.issubset(all_metrics)


def test_monitoring_layout_timeseries_tiles_use_timeseries_metrics(client):
    resp = client.get("/api/v1/planning/monitoring/layout")
    assert resp.status_code == 200, resp.text

    body = resp.json()
    sections = body["sections"]

    timeseries_used: set[str] = set()

    for section in sections:
        for tile in section["tiles"]:
            if tile["type"] != "timeseries":
                continue

            primary = tile["primary_metric"]
            if primary is not None:
                timeseries_used.add(primary)

            secondary = tile["secondary_metrics"]
            if secondary:
                timeseries_used.update(secondary)

    timeseries_metrics = get_timeseries_metrics()
    assert timeseries_used.issubset(timeseries_metrics)
