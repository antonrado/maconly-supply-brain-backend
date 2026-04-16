from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.core.db import get_db
from app.main import app
from app.models.models import (
    Article,
    ArticleWbMapping,
    BundleRecipe,
    BundleType,
    Color,
    WbIntegrationAccount,
    WbSalesDaily,
    WbStock,
)
from app.services import wb_ingest


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


def test_wb_live_sales_sync_requires_active_account(client):
    response = client.post("/api/v1/wb/sales-daily/sync-live", json={})
    assert response.status_code == 400, response.text
    assert response.json()["detail"] == {
        "code": "no_active_wb_integration_account",
        "message": "No active WB integration account configured",
        "next_steps": ["create_or_activate_wb_integration_account"],
    }


def test_wb_live_sales_sync_rejects_unknown_active_account_id_with_structured_detail(client):
    response = client.post(
        "/api/v1/wb/sales-daily/sync-live",
        json={"account_id": 999999},
    )
    assert response.status_code == 400, response.text
    assert response.json()["detail"] == {
        "code": "wb_integration_account_not_found",
        "message": "Active WB integration account not found",
        "field": "account_id",
        "field_metadata": {
            "description": "WB integration account identifier",
            "type": "int",
        },
        "account_id": 999999,
        "next_steps": ["use_existing_active_wb_account_id"],
    }


def test_wb_live_sales_sync_rejects_empty_api_token_with_structured_detail(client, db_session):
    account = WbIntegrationAccount(
        name="WB Empty Token",
        supplier_id=None,
        api_token="   ",
        is_active=True,
    )
    db_session.add(account)
    db_session.commit()

    response = client.post(
        "/api/v1/wb/sales-daily/sync-live",
        json={"account_id": account.id},
    )
    assert response.status_code == 400, response.text
    assert response.json()["detail"] == {
        "code": "wb_integration_account_empty_api_token",
        "message": "WB integration account has empty api_token",
        "field": "api_token",
        "field_metadata": {
            "description": "WB integration account API token",
            "type": "string",
        },
        "account_id": account.id,
        "next_steps": ["set_wb_integration_account_api_token"],
    }


def test_wb_live_sales_sync_ingests_daily_rows(client, db_session, monkeypatch):
    account = WbIntegrationAccount(
        name="WB Test",
        supplier_id=None,
        api_token="token-1",
        is_active=True,
    )
    db_session.add(account)
    db_session.flush()

    pages = [
        [
            {
                "date": "2026-02-01T10:00:00",
                "lastChangeDate": "2026-02-01T12:00:00",
                "barcode": "WB-SKU-1",
                "saleID": "S1001",
                "finishedPrice": 100,
            },
            {
                "date": "2026-02-01T11:00:00",
                "lastChangeDate": "2026-02-01T12:00:00",
                "barcode": "WB-SKU-1",
                "saleID": "S1002",
                "finishedPrice": 120,
            },
            {
                "date": "2026-02-01T11:30:00",
                "lastChangeDate": "2026-02-01T12:00:00",
                "barcode": "WB-SKU-1",
                "saleID": "R1003",
                "finishedPrice": 55,
            },
        ],
        [],
    ]
    calls: list[dict[str, object]] = []

    def fake_wb_get_json_rows(*, path, token, params):
        calls.append({"path": path, "token": token, "params": params})
        return pages.pop(0)

    monkeypatch.setattr(wb_ingest, "_wb_get_json_rows", fake_wb_get_json_rows)

    response = client.post(
        "/api/v1/wb/sales-daily/sync-live",
        json={
            "account_id": account.id,
            "date_from": "2026-02-01T00:00:00Z",
            "max_pages": 5,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["account_id"] == account.id
    assert body["fetched_rows"] == 3
    assert body["inserted"] == 1
    assert body["updated"] == 0
    assert body["pages_requested"] == 5
    assert body["pages_with_data"] == 1

    assert len(calls) == 2
    assert calls[0]["path"] == wb_ingest.WB_REPORTS_SALES_PATH
    assert calls[0]["token"] == account.api_token
    assert calls[0]["params"]["flag"] == 0

    rows = db_session.query(WbSalesDaily).all()
    assert len(rows) == 1
    row = rows[0]
    assert row.wb_sku == "WB-SKU-1"
    assert row.sales_qty == 2
    assert float(row.revenue or 0.0) == 220.0


def test_wb_live_stock_sync_aggregates_warehouses(client, db_session, monkeypatch):
    account = WbIntegrationAccount(
        name="WB Stock Test",
        supplier_id=None,
        api_token="token-2",
        is_active=True,
    )
    db_session.add(account)
    db_session.flush()

    pages = [
        [
            {
                "lastChangeDate": "2026-02-03T09:00:00",
                "warehouseName": "WH-1",
                "barcode": "WB-SKU-2",
                "quantity": 3,
            },
            {
                "lastChangeDate": "2026-02-03T10:00:00",
                "warehouseName": "WH-2",
                "barcode": "WB-SKU-2",
                "quantity": "4",
            },
        ],
        [],
    ]

    def fake_wb_get_json_rows(*, path, token, params):
        return pages.pop(0)

    monkeypatch.setattr(wb_ingest, "_wb_get_json_rows", fake_wb_get_json_rows)

    response = client.post(
        "/api/v1/wb/stock/sync-live",
        json={
            "account_id": account.id,
            "date_from": "2026-02-01T00:00:00Z",
            "max_pages": 3,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["account_id"] == account.id
    assert body["fetched_rows"] == 2
    assert body["inserted"] == 1
    assert body["updated"] == 0
    assert body["pages_with_data"] == 1

    rows = db_session.query(WbStock).all()
    assert len(rows) == 1
    row = rows[0]
    assert row.wb_sku == "WB-SKU-2"
    assert row.warehouse_id is None
    assert row.warehouse_name == "WB_TOTAL"
    assert row.stock_qty == 7
    assert row.updated_at is not None


def test_wb_live_article_mapping_sync_matches_article_codes(client, db_session, monkeypatch):
    account = WbIntegrationAccount(
        name="WB Mapping Test",
        supplier_id=None,
        api_token="token-3",
        is_active=True,
    )
    article = Article(code="MC-001", name="Mapped article")
    db_session.add_all([account, article])
    db_session.flush()

    pages = [
        [
            {
                "lastChangeDate": "2026-02-03T09:00:00",
                "supplierArticle": "MC-001",
                "barcode": "WB-BAR-1",
            },
            {
                "lastChangeDate": "2026-02-03T10:00:00",
                "supplierArticle": "MC-404",
                "barcode": "WB-BAR-2",
            },
            {
                "lastChangeDate": "2026-02-03T10:00:00",
                "supplierArticle": "MC-001",
                "barcode": "WB-BAR-1",
            },
        ],
        [],
    ]

    def fake_wb_get_json_rows(*, path, token, params):
        return pages.pop(0)

    monkeypatch.setattr(wb_ingest, "_wb_get_json_rows", fake_wb_get_json_rows)

    response = client.post(
        "/api/v1/wb/article-mapping/sync-live",
        json={
            "account_id": account.id,
            "date_from": "2026-02-01T00:00:00Z",
            "max_pages": 5,
            "default_bundle_type_id": 10,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["account_id"] == account.id
    assert body["fetched_rows"] == 3
    assert body["candidate_pairs"] == 2
    assert body["matched_pairs"] == 1
    assert body["unmatched_pairs"] == 1
    assert body["exact_matched_pairs"] == 1
    assert body["normalized_matched_pairs"] == 0
    assert body["ambiguous_normalized_pairs"] == 0
    assert body["inserted"] == 1
    assert body["updated"] == 0
    assert body["pages_with_data"] == 1

    rows = db_session.query(ArticleWbMapping).all()
    assert len(rows) == 1
    row = rows[0]
    assert row.article_id == article.id
    assert row.wb_sku == "WB-BAR-1"
    assert row.bundle_type_id == 10


def test_wb_article_mapping_import_rejects_unknown_article_with_structured_detail(client):
    response = client.post(
        "/api/v1/wb/article-mapping/import",
        json={
            "items": [
                {
                    "article_id": 999999999,
                    "wb_sku": "WB-MISSING-ARTICLE",
                }
            ]
        },
    )
    assert response.status_code == 400, response.text
    assert response.json()["detail"] == {
        "code": "wb_mapping_article_not_found",
        "message": "Referenced article_id does not exist",
        "field": "article_id",
        "field_metadata": {
            "description": "Article identifier in article-to-WB mapping import payload",
            "type": "int",
        },
        "article_id": 999999999,
        "wb_sku": "WB-MISSING-ARTICLE",
        "next_steps": ["use_existing_article_id"],
    }


def test_wb_live_article_mapping_sync_uses_normalized_match(client, db_session, monkeypatch):
    account = WbIntegrationAccount(
        name="WB Mapping Normalized",
        supplier_id=None,
        api_token="token-4",
        is_active=True,
    )
    article = Article(code="AB 12-34", name="Normalized article")
    db_session.add_all([account, article])
    db_session.flush()

    pages = [
        [
            {
                "lastChangeDate": "2026-02-03T11:00:00",
                "supplierArticle": "ab1234",
                "barcode": "WB-NORM-1",
            }
        ],
        [],
    ]

    def fake_wb_get_json_rows(*, path, token, params):
        return pages.pop(0)

    monkeypatch.setattr(wb_ingest, "_wb_get_json_rows", fake_wb_get_json_rows)

    response = client.post(
        "/api/v1/wb/article-mapping/sync-live",
        json={
            "account_id": account.id,
            "max_pages": 3,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["candidate_pairs"] == 1
    assert body["matched_pairs"] == 1
    assert body["unmatched_pairs"] == 0
    assert body["exact_matched_pairs"] == 0
    assert body["normalized_matched_pairs"] == 1
    assert body["ambiguous_normalized_pairs"] == 0
    assert body["inserted"] == 1

    row = db_session.query(ArticleWbMapping).one()
    assert row.article_id == article.id
    assert row.wb_sku == "WB-NORM-1"


def test_wb_live_article_mapping_discover_returns_match_hints(client, db_session, monkeypatch):
    account = WbIntegrationAccount(
        name="WB Mapping Discover",
        supplier_id=None,
        api_token="token-5",
        is_active=True,
    )
    article_exact = Article(code="MC-010", name="Exact")
    article_norm = Article(code="ZX 77", name="Normalized")
    db_session.add_all([account, article_exact, article_norm])
    db_session.flush()

    pages = [
        [
            {
                "lastChangeDate": "2026-02-04T10:00:00",
                "supplierArticle": "MC-010",
                "barcode": "WB-DISC-1",
            },
            {
                "lastChangeDate": "2026-02-04T10:00:00",
                "supplierArticle": "zx77",
                "barcode": "WB-DISC-2",
            },
            {
                "lastChangeDate": "2026-02-04T10:00:00",
                "supplierArticle": "UNMATCHED",
                "barcode": "WB-DISC-3",
            },
            {
                "lastChangeDate": "2026-02-04T10:00:00",
                "supplierArticle": "MC-010",
                "barcode": "WB-DISC-4",
            },
        ],
        [],
    ]

    def fake_wb_get_json_rows(*, path, token, params):
        return pages.pop(0)

    monkeypatch.setattr(wb_ingest, "_wb_get_json_rows", fake_wb_get_json_rows)

    response = client.post(
        "/api/v1/wb/article-mapping/discover-live",
        json={
            "account_id": account.id,
            "max_pages": 2,
            "limit": 10,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["account_id"] == account.id
    assert body["fetched_rows"] == 4
    assert body["unique_supplier_articles"] == 3
    assert body["matched_supplier_articles"] == 2
    assert body["unmatched_supplier_articles"] == 1
    assert body["ambiguous_supplier_articles"] == 0

    items = {row["supplier_article"]: row for row in body["items"]}
    assert items["MC-010"]["rows"] == 2
    assert items["MC-010"]["unique_wb_skus"] == 2
    assert items["MC-010"]["match_source"] == "exact"
    assert items["MC-010"]["matched_article_id"] == article_exact.id

    assert items["zx77"]["match_source"] == "normalized"
    assert items["zx77"]["matched_article_id"] == article_norm.id

    assert items["UNMATCHED"]["match_source"] == "none"
    assert items["UNMATCHED"]["matched_article_id"] is None


def test_wb_live_article_bootstrap_dry_run_reports_changes(client, db_session, monkeypatch):
    account = WbIntegrationAccount(
        name="WB Bootstrap Dry",
        supplier_id=None,
        api_token="token-6",
        is_active=True,
    )
    existing_article = Article(code="EXIST-1", name="Existing")
    db_session.add_all([account, existing_article])
    db_session.flush()

    too_long_code = "X" * 51
    pages = [
        [
            {
                "lastChangeDate": "2026-02-05T10:00:00",
                "supplierArticle": "EXIST-1",
                "barcode": "WB-BOOT-1",
            },
            {
                "lastChangeDate": "2026-02-05T10:00:00",
                "supplierArticle": "NEW-1",
                "barcode": "WB-BOOT-2",
            },
            {
                "lastChangeDate": "2026-02-05T10:00:00",
                "supplierArticle": too_long_code,
                "barcode": "WB-BOOT-3",
            },
        ],
        [],
    ]

    def fake_wb_get_json_rows(*, path, token, params):
        return pages.pop(0)

    monkeypatch.setattr(wb_ingest, "_wb_get_json_rows", fake_wb_get_json_rows)

    response = client.post(
        "/api/v1/wb/article/bootstrap-live",
        json={
            "account_id": account.id,
            "max_pages": 3,
            "limit": 10,
            "dry_run": True,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["candidate_supplier_articles"] == 3
    assert body["existing_articles"] == 1
    assert body["inserted_articles"] == 0
    assert body["skipped_invalid"] == 1
    assert body["dry_run"] is True

    items = {row["supplier_article"]: row for row in body["items"]}
    assert items["EXIST-1"]["status"] == "existing"
    assert items["NEW-1"]["status"] == "would_insert"
    assert items[too_long_code]["status"] == "invalid_too_long"

    assert db_session.query(Article).filter(Article.code == "NEW-1").count() == 0


def test_wb_live_article_bootstrap_inserts_articles(client, db_session, monkeypatch):
    account = WbIntegrationAccount(
        name="WB Bootstrap Insert",
        supplier_id=None,
        api_token="token-7",
        is_active=True,
    )
    db_session.add(account)
    db_session.flush()

    pages = [
        [
            {
                "lastChangeDate": "2026-02-05T11:00:00",
                "supplierArticle": "NEW-10",
                "barcode": "WB-BOOT-10",
            },
            {
                "lastChangeDate": "2026-02-05T11:00:00",
                "supplierArticle": "NEW-20",
                "barcode": "WB-BOOT-20",
            },
            {
                "lastChangeDate": "2026-02-05T11:00:00",
                "supplierArticle": "NEW-10",
                "barcode": "WB-BOOT-11",
            },
        ],
        [],
    ]

    def fake_wb_get_json_rows(*, path, token, params):
        return pages.pop(0)

    monkeypatch.setattr(wb_ingest, "_wb_get_json_rows", fake_wb_get_json_rows)

    response = client.post(
        "/api/v1/wb/article/bootstrap-live",
        json={
            "account_id": account.id,
            "max_pages": 3,
            "limit": 10,
            "dry_run": False,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["candidate_supplier_articles"] == 2
    assert body["existing_articles"] == 0
    assert body["inserted_articles"] == 2
    assert body["skipped_invalid"] == 0
    assert body["dry_run"] is False

    created = db_session.query(Article).filter(Article.code.in_(["NEW-10", "NEW-20"])).all()
    assert len(created) == 2

    statuses = {row["supplier_article"]: row["status"] for row in body["items"]}
    assert statuses["NEW-10"] == "inserted"
    assert statuses["NEW-20"] == "inserted"


def test_wb_get_json_rows_retries_429_and_then_succeeds(monkeypatch):
    class FakeResponse:
        def __init__(self, status_code, payload, headers=None, text=""):
            self.status_code = status_code
            self._payload = payload
            self.headers = headers or {}
            self.text = text

        def json(self):
            return self._payload

    responses = [
        FakeResponse(429, [], headers={"X-Ratelimit-Retry": "1"}),
        FakeResponse(200, [{"id": 1}, {"id": 2}]),
    ]
    sleep_calls: list[int] = []

    def fake_httpx_request(*args, **kwargs):
        return responses.pop(0)

    def fake_sleep(seconds):
        sleep_calls.append(int(seconds))

    monkeypatch.setattr(wb_ingest.httpx, "request", fake_httpx_request)
    monkeypatch.setattr(wb_ingest.time, "sleep", fake_sleep)

    rows = wb_ingest._wb_get_json_rows(path="/fake", token="t", params={"x": 1})
    assert rows == [{"id": 1}, {"id": 2}]
    assert sleep_calls == [1]


def test_wb_get_json_rows_raises_429_after_retries(monkeypatch):
    class FakeResponse:
        def __init__(self, status_code, payload, headers=None, text=""):
            self.status_code = status_code
            self._payload = payload
            self.headers = headers or {}
            self.text = text

        def json(self):
            return self._payload

    def fake_httpx_request(*args, **kwargs):
        return FakeResponse(429, [], headers={"X-Ratelimit-Retry": "2"})

    monkeypatch.setattr(wb_ingest.httpx, "request", fake_httpx_request)
    monkeypatch.setattr(wb_ingest.time, "sleep", lambda _seconds: None)

    with pytest.raises(HTTPException) as exc:
        wb_ingest._wb_get_json_rows(path="/fake", token="t", params={"x": 1})

    assert exc.value.status_code == 429
    assert exc.value.detail == {
        "code": "wb_api_rate_limit_exceeded",
        "message": "WB API rate limit exceeded",
        "next_steps": ["retry_wb_live_sync_later"],
        "operation": "http_request",
        "operation_metadata": {"method": "GET"},
        "retry_after_seconds": 2,
        "retry_after_raw": "2",
    }


def test_wb_request_raises_structured_request_failed_detail(monkeypatch):
    def fake_httpx_request(*args, **kwargs):
        raise wb_ingest.httpx.RequestError("boom")

    monkeypatch.setattr(wb_ingest.httpx, "request", fake_httpx_request)

    with pytest.raises(HTTPException) as exc:
        wb_ingest._wb_request(method="GET", url="https://example.test", token="t")

    assert exc.value.status_code == 502
    assert exc.value.detail == {
        "code": "wb_api_request_failed",
        "message": "WB API request failed",
        "next_steps": ["retry_wb_live_sync"],
        "operation": "http_request",
        "operation_metadata": {"method": "GET"},
        "error": "boom",
    }


def test_wb_request_raises_structured_unauthorized_detail(monkeypatch):
    class FakeResponse:
        def __init__(self):
            self.status_code = 401
            self.headers = {}
            self.text = "unauthorized"

    monkeypatch.setattr(wb_ingest.httpx, "request", lambda *args, **kwargs: FakeResponse())

    with pytest.raises(HTTPException) as exc:
        wb_ingest._wb_request(method="GET", url="https://example.test", token="t")

    assert exc.value.status_code == 401
    assert exc.value.detail == {
        "code": "wb_api_unauthorized",
        "message": "WB API token is unauthorized for this method",
        "next_steps": ["check_wb_api_token_permissions"],
        "operation": "http_request",
        "operation_metadata": {"method": "GET"},
    }


def test_wb_request_raises_structured_http_error_detail(monkeypatch):
    class FakeResponse:
        def __init__(self):
            self.status_code = 500
            self.headers = {}
            self.text = "upstream boom"

    monkeypatch.setattr(wb_ingest.httpx, "request", lambda *args, **kwargs: FakeResponse())

    with pytest.raises(HTTPException) as exc:
        wb_ingest._wb_request(method="GET", url="https://example.test", token="t")

    assert exc.value.status_code == 502
    assert exc.value.detail == {
        "code": "wb_api_http_error",
        "message": "WB API returned an unexpected HTTP error",
        "next_steps": ["retry_wb_live_sync", "check_wb_api_status_or_request_payload"],
        "operation": "http_request",
        "operation_metadata": {"method": "GET"},
        "upstream_status_code": 500,
        "body_preview": "upstream boom",
    }


def test_wb_parse_json_payload_raises_structured_invalid_json_detail():
    class FakeResponse:
        def json(self):
            raise ValueError("bad json")

    with pytest.raises(HTTPException) as exc:
        wb_ingest._wb_parse_json_payload(FakeResponse())

    assert exc.value.status_code == 502
    assert exc.value.detail == {
        "code": "wb_api_invalid_json",
        "message": "WB API response is not valid JSON",
        "next_steps": ["retry_wb_live_sync", "inspect_wb_api_response_format"],
        "operation": "parse_json_response",
        "operation_metadata": {"expected_type": "json"},
    }


def test_normalize_wb_json_rows_raises_structured_invalid_rows_format_detail():
    with pytest.raises(HTTPException) as exc:
        wb_ingest._normalize_wb_json_rows({"not": "a-list"})

    assert exc.value.status_code == 502
    assert exc.value.detail == {
        "code": "wb_api_invalid_rows_format",
        "message": "WB API response format is invalid: expected array",
        "next_steps": ["inspect_wb_api_response_format"],
        "operation": "normalize_json_rows",
        "operation_metadata": {"expected_type": "list[object]"},
    }


def test_wb_get_json_object_raises_structured_invalid_object_format_detail(monkeypatch):
    class FakeResponse:
        def json(self):
            return ["not", "an", "object"]

    monkeypatch.setattr(
        wb_ingest,
        "_wb_request",
        lambda **kwargs: FakeResponse(),
    )

    with pytest.raises(HTTPException) as exc:
        wb_ingest._wb_get_json_object(
            base_url="https://example.test",
            path="/fake",
            token="t",
        )

    assert exc.value.status_code == 502
    assert exc.value.detail == {
        "code": "wb_api_invalid_object_format",
        "message": "WB API response format is invalid: expected object",
        "next_steps": ["inspect_wb_api_response_format"],
        "operation": "normalize_json_object",
        "operation_metadata": {"expected_type": "object"},
    }


def test_wb_from_wb_readiness_returns_404_for_unknown_article(client, db_session):  # noqa: ARG001
    response = client.post(
        "/api/v1/wb/from-wb/readiness",
        json={"article_id": 999999999, "limit": 10},
    )
    assert response.status_code == 404, response.text
    assert response.json()["detail"] == {
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


def test_wb_from_wb_readiness_reports_blockers_and_ready(client, db_session):
    article_ready = Article(code="READY-1", name="Ready")
    article_no_recipe = Article(code="BLOCK-NO-RECIPE", name="No recipe")
    article_missing_bundle = Article(code="BLOCK-MISSING", name="Missing bundle")
    article_no_sales = Article(code="BLOCK-NO-SALES", name="No sales")
    article_no_stock = Article(code="BLOCK-NO-STOCK", name="No stock")

    bt_main = BundleType(code="BT-MAIN", name="Main", is_assorti=False)
    bt_alt = BundleType(code="BT-ALT", name="Alt", is_assorti=True)
    color_a = Color(inner_code="CLR-READINESS-A", pantone_code=None, description=None)
    color_b = Color(inner_code="CLR-READINESS-B", pantone_code=None, description=None)

    db_session.add_all([
        article_ready,
        article_no_recipe,
        article_missing_bundle,
        article_no_sales,
        article_no_stock,
        bt_main,
        bt_alt,
        color_a,
        color_b,
    ])
    db_session.flush()

    db_session.add_all(
        [
            ArticleWbMapping(article_id=article_ready.id, wb_sku="WB-R-1", bundle_type_id=bt_main.id),
            ArticleWbMapping(article_id=article_no_recipe.id, wb_sku="WB-NR-1", bundle_type_id=bt_main.id),
            ArticleWbMapping(article_id=article_missing_bundle.id, wb_sku="WB-MB-1", bundle_type_id=bt_alt.id),
            ArticleWbMapping(article_id=article_no_sales.id, wb_sku="WB-NS-1", bundle_type_id=bt_main.id),
            ArticleWbMapping(article_id=article_no_stock.id, wb_sku="WB-NST-1", bundle_type_id=bt_main.id),
        ]
    )
    db_session.add_all(
        [
            BundleRecipe(
                article_id=article_ready.id,
                bundle_type_id=bt_main.id,
                color_id=color_a.id,
                position=1,
            ),
            BundleRecipe(
                article_id=article_missing_bundle.id,
                bundle_type_id=bt_main.id,
                color_id=color_b.id,
                position=1,
            ),
            BundleRecipe(
                article_id=article_no_sales.id,
                bundle_type_id=bt_main.id,
                color_id=color_a.id,
                position=1,
            ),
            BundleRecipe(
                article_id=article_no_stock.id,
                bundle_type_id=bt_main.id,
                color_id=color_b.id,
                position=1,
            ),
        ]
    )
    seed_created_at = datetime.now(timezone.utc)
    db_session.add(
        WbSalesDaily(
            wb_sku="WB-R-1",
            date=seed_created_at.date(),
            sales_qty=5,
            revenue=None,
            created_at=seed_created_at,
        )
    )
    db_session.add(
        WbStock(
            wb_sku="WB-R-1",
            warehouse_id=1,
            warehouse_name="WB",
            stock_qty=7,
            updated_at=seed_created_at,
        )
    )
    db_session.add(
        WbStock(
            wb_sku="WB-NS-1",
            warehouse_id=1,
            warehouse_name="WB",
            stock_qty=3,
            updated_at=seed_created_at,
        )
    )
    db_session.add(
        WbSalesDaily(
            wb_sku="WB-NST-1",
            date=seed_created_at.date(),
            sales_qty=4,
            revenue=None,
            created_at=seed_created_at,
        )
    )
    db_session.flush()

    response = client.post("/api/v1/wb/from-wb/readiness", json={"limit": 10})
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["total_articles_considered"] == 5
    assert body["ready_articles"] == 1
    assert body["not_ready_articles"] == 4

    items = {row["article_code"]: row for row in body["items"]}

    assert items["READY-1"]["ready_for_from_wb"] is True
    assert items["READY-1"]["blocker"] is None
    assert items["READY-1"]["mapped_wb_skus_with_sales"] == 1
    assert items["READY-1"]["mapped_wb_skus_with_stock"] == 1
    assert items["READY-1"]["next_steps"] == []

    assert items["BLOCK-NO-RECIPE"]["ready_for_from_wb"] is False
    assert items["BLOCK-NO-RECIPE"]["blocker"] == "no_bundle_recipe"
    assert items["BLOCK-NO-RECIPE"]["mapped_wb_skus_with_sales"] == 0
    assert items["BLOCK-NO-RECIPE"]["mapped_wb_skus_with_stock"] == 0
    assert items["BLOCK-NO-RECIPE"]["next_steps"] == ["create_bundle_recipe_for_mapped_bundle_types"]

    assert items["BLOCK-MISSING"]["ready_for_from_wb"] is False
    assert items["BLOCK-MISSING"]["blocker"] == "missing_bundle_recipe_bundle_types"
    assert items["BLOCK-MISSING"]["missing_recipe_bundle_type_ids"] == [bt_alt.id]
    assert items["BLOCK-MISSING"]["next_steps"] == ["add_bundle_recipe_for_missing_bundle_type_ids"]

    assert items["BLOCK-NO-SALES"]["ready_for_from_wb"] is False
    assert items["BLOCK-NO-SALES"]["blocker"] == "no_wb_sales_data"
    assert items["BLOCK-NO-SALES"]["freshness_status"] == "missing_sales_data"
    assert items["BLOCK-NO-SALES"]["mapped_wb_skus_with_sales"] == 0
    assert items["BLOCK-NO-SALES"]["mapped_wb_skus_with_stock"] == 1
    assert items["BLOCK-NO-SALES"]["sales_age_days"] is None
    assert items["BLOCK-NO-SALES"]["stock_oldest_age_days"] == 0
    assert items["BLOCK-NO-SALES"]["threshold_days"] == {"sales": 3, "stock": 2}
    assert items["BLOCK-NO-SALES"]["threshold_source"] == {"sales": "global_default", "stock": "global_default"}
    assert items["BLOCK-NO-SALES"]["next_steps"] == ["run_wb_sales_daily_sync_live"]

    assert items["BLOCK-NO-STOCK"]["ready_for_from_wb"] is False
    assert items["BLOCK-NO-STOCK"]["blocker"] == "no_wb_stock_data"
    assert items["BLOCK-NO-STOCK"]["freshness_status"] == "missing_stock_data"
    assert items["BLOCK-NO-STOCK"]["mapped_wb_skus_with_sales"] == 1
    assert items["BLOCK-NO-STOCK"]["mapped_wb_skus_with_stock"] == 0
    assert items["BLOCK-NO-STOCK"]["sales_age_days"] == 0
    assert items["BLOCK-NO-STOCK"]["stock_oldest_age_days"] is None
    assert items["BLOCK-NO-STOCK"]["threshold_days"] == {"sales": 3, "stock": 2}
    assert items["BLOCK-NO-STOCK"]["threshold_source"] == {"sales": "global_default", "stock": "global_default"}
    assert items["BLOCK-NO-STOCK"]["next_steps"] == ["run_wb_stock_sync_live"]


def test_wb_from_wb_readiness_reports_missing_sales_with_stale_stock_blocker(client, db_session):
    article_stale = Article(code="NO-SALES-STALE-STOCK-1", name="No sales stale stock")
    bundle_type = BundleType(code="BT-NO-SALES-STALE-STOCK", name="No sales stale stock bundle", is_assorti=False)
    color = Color(inner_code="CLR-NO-SALES-STALE-STOCK", pantone_code=None, description=None)
    today_utc = datetime.now(timezone.utc).date()

    db_session.add_all([article_stale, bundle_type, color])
    db_session.flush()

    db_session.add(
        ArticleWbMapping(
            article_id=article_stale.id,
            wb_sku="WB-NO-SALES-STALE-STOCK-1",
            bundle_type_id=bundle_type.id,
        )
    )
    db_session.add(
        BundleRecipe(
            article_id=article_stale.id,
            bundle_type_id=bundle_type.id,
            color_id=color.id,
            position=1,
        )
    )
    db_session.add(
        WbStock(
            wb_sku="WB-NO-SALES-STALE-STOCK-1",
            warehouse_id=1,
            warehouse_name="WB",
            stock_qty=5,
            updated_at=datetime(2020, 1, 2, tzinfo=timezone.utc),
        )
    )
    db_session.flush()

    response = client.post("/api/v1/wb/from-wb/readiness", json={"article_id": article_stale.id, "limit": 10})
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["total_articles_considered"] == 1
    assert body["ready_articles"] == 0
    assert body["not_ready_articles"] == 1

    item = body["items"][0]
    assert item["article_code"] == "NO-SALES-STALE-STOCK-1"
    assert item["ready_for_from_wb"] is False
    assert item["freshness_status"] == "missing_sales_data"
    assert item["blocker"] == "no_wb_sales_data"
    assert item["sales_age_days"] is None
    assert item["stock_oldest_age_days"] == (today_utc - date(2020, 1, 2)).days
    assert item["threshold_days"] == {"sales": 3, "stock": 2}
    assert item["threshold_source"] == {"sales": "global_default", "stock": "global_default"}
    assert item["next_steps"] == ["run_wb_sales_daily_sync_live", "run_wb_stock_sync_live"]


def test_wb_from_wb_readiness_request_stock_threshold_overrides_admin_defaults_for_missing_sales_with_stale_stock(client, db_session):
    article_stale = Article(code="NO-SALES-STALE-STOCK-MIXED-1", name="No sales stale stock mixed")
    bundle_type = BundleType(code="BT-NO-SALES-STALE-STOCK-MIXED", name="No sales stale stock mixed bundle", is_assorti=False)
    color = Color(inner_code="CLR-NO-SALES-STALE-STOCK-MIXED", pantone_code=None, description=None)
    today_utc = datetime.now(timezone.utc).date()

    db_session.add_all([article_stale, bundle_type, color])
    db_session.flush()

    db_session.add(
        ArticleWbMapping(
            article_id=article_stale.id,
            wb_sku="WB-NO-SALES-STALE-STOCK-MIXED-1",
            bundle_type_id=bundle_type.id,
        )
    )
    db_session.add(
        BundleRecipe(
            article_id=article_stale.id,
            bundle_type_id=bundle_type.id,
            color_id=color.id,
            position=1,
        )
    )
    db_session.add(
        WbStock(
            wb_sku="WB-NO-SALES-STALE-STOCK-MIXED-1",
            warehouse_id=1,
            warehouse_name="WB",
            stock_qty=5,
            updated_at=datetime(2020, 1, 2, tzinfo=timezone.utc),
        )
    )
    db_session.flush()

    settings_response = client.put(
        f"/api/v1/planning/core/production-order/settings/{article_stale.id}",
        json={
            "size_weights": [],
            "elastic_bindings": [],
            "in_flight_supply_defaults": [],
            "freshness_sales_stale_after_days": 3650,
            "freshness_stock_stale_after_days": 3650,
        },
    )
    assert settings_response.status_code == 200, settings_response.text

    response = client.post(
        "/api/v1/wb/from-wb/readiness",
        json={
            "article_id": article_stale.id,
            "limit": 10,
            "freshness_stock_stale_after_days": 1,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["total_articles_considered"] == 1
    assert body["ready_articles"] == 0
    assert body["not_ready_articles"] == 1

    item = body["items"][0]
    assert item["article_code"] == "NO-SALES-STALE-STOCK-MIXED-1"
    assert item["ready_for_from_wb"] is False
    assert item["freshness_status"] == "missing_sales_data"
    assert item["blocker"] == "no_wb_sales_data"
    assert item["sales_age_days"] is None
    assert item["stock_oldest_age_days"] == (today_utc - date(2020, 1, 2)).days
    assert item["threshold_days"] == {"sales": 3650, "stock": 1}
    assert item["threshold_source"] == {"sales": "admin_defaults", "stock": "request"}
    assert item["next_steps"] == ["run_wb_sales_daily_sync_live", "run_wb_stock_sync_live"]


def test_wb_from_wb_readiness_reports_missing_stock_with_stale_sales_blocker(client, db_session):
    article_stale = Article(code="NO-STOCK-STALE-SALES-1", name="No stock stale sales")
    bundle_type = BundleType(code="BT-NO-STOCK-STALE-SALES", name="No stock stale sales bundle", is_assorti=False)
    color = Color(inner_code="CLR-NO-STOCK-STALE-SALES", pantone_code=None, description=None)
    stale_sales_date = date(2020, 1, 1)
    today_utc = datetime.now(timezone.utc).date()

    db_session.add_all([article_stale, bundle_type, color])
    db_session.flush()

    db_session.add(
        ArticleWbMapping(
            article_id=article_stale.id,
            wb_sku="WB-NO-STOCK-STALE-SALES-1",
            bundle_type_id=bundle_type.id,
        )
    )
    db_session.add(
        BundleRecipe(
            article_id=article_stale.id,
            bundle_type_id=bundle_type.id,
            color_id=color.id,
            position=1,
        )
    )
    db_session.add(
        WbSalesDaily(
            wb_sku="WB-NO-STOCK-STALE-SALES-1",
            date=stale_sales_date,
            sales_qty=5,
            revenue=None,
            created_at=datetime.now(timezone.utc),
        )
    )
    db_session.flush()

    response = client.post("/api/v1/wb/from-wb/readiness", json={"article_id": article_stale.id, "limit": 10})
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["total_articles_considered"] == 1
    assert body["ready_articles"] == 0
    assert body["not_ready_articles"] == 1

    item = body["items"][0]
    assert item["article_code"] == "NO-STOCK-STALE-SALES-1"
    assert item["ready_for_from_wb"] is False
    assert item["freshness_status"] == "missing_stock_data"
    assert item["blocker"] == "no_wb_stock_data"
    assert item["sales_age_days"] == (today_utc - stale_sales_date).days
    assert item["stock_oldest_age_days"] is None
    assert item["threshold_days"] == {"sales": 3, "stock": 2}
    assert item["threshold_source"] == {"sales": "global_default", "stock": "global_default"}
    assert item["next_steps"] == ["run_wb_sales_daily_sync_live", "run_wb_stock_sync_live"]


def test_wb_from_wb_readiness_reports_stale_freshness_blocker(client, db_session):
    article_stale = Article(code="STALE-1", name="Stale")
    bundle_type = BundleType(code="BT-STALE", name="Stale bundle", is_assorti=False)
    color = Color(inner_code="CLR-STALE", pantone_code=None, description=None)

    db_session.add_all([article_stale, bundle_type, color])
    db_session.flush()

    db_session.add(
        ArticleWbMapping(article_id=article_stale.id, wb_sku="WB-STALE-1", bundle_type_id=bundle_type.id)
    )
    db_session.add(
        BundleRecipe(
            article_id=article_stale.id,
            bundle_type_id=bundle_type.id,
            color_id=color.id,
            position=1,
        )
    )
    db_session.add(
        WbSalesDaily(
            wb_sku="WB-STALE-1",
            date=date(2026, 1, 10),
            sales_qty=3,
            revenue=None,
            created_at=datetime.now(timezone.utc),
        )
    )
    db_session.add(
        WbStock(
            wb_sku="WB-STALE-1",
            warehouse_id=1,
            warehouse_name="WB",
            stock_qty=5,
            updated_at=datetime.now(timezone.utc),
        )
    )
    db_session.flush()

    response = client.post("/api/v1/wb/from-wb/readiness", json={"article_id": article_stale.id, "limit": 10})
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["total_articles_considered"] == 1
    assert body["ready_articles"] == 0
    assert body["not_ready_articles"] == 1

    item = body["items"][0]
    assert item["article_code"] == "STALE-1"
    assert item["ready_for_from_wb"] is False
    assert item["freshness_status"] == "stale"
    assert item["blocker"] == "stale_wb_sales_data"
    assert item["sales_age_days"] is not None
    assert item["stock_oldest_age_days"] == 0
    assert item["threshold_days"] == {"sales": 3, "stock": 2}
    assert item["threshold_source"] == {"sales": "global_default", "stock": "global_default"}
    assert item["next_steps"] == ["run_wb_sales_daily_sync_live"]


def test_wb_from_wb_readiness_request_thresholds_override_stale_blocker(client, db_session):
    article_stale = Article(code="STALE-OVERRIDE-1", name="Stale override")
    bundle_type = BundleType(code="BT-STALE-OVERRIDE", name="Stale override bundle", is_assorti=False)
    color = Color(inner_code="CLR-STALE-OVERRIDE", pantone_code=None, description=None)

    db_session.add_all([article_stale, bundle_type, color])
    db_session.flush()

    db_session.add(
        ArticleWbMapping(article_id=article_stale.id, wb_sku="WB-STALE-OVERRIDE-1", bundle_type_id=bundle_type.id)
    )
    db_session.add(
        BundleRecipe(
            article_id=article_stale.id,
            bundle_type_id=bundle_type.id,
            color_id=color.id,
            position=1,
        )
    )
    db_session.add(
        WbSalesDaily(
            wb_sku="WB-STALE-OVERRIDE-1",
            date=date(2026, 1, 10),
            sales_qty=3,
            revenue=None,
            created_at=datetime.now(timezone.utc),
        )
    )
    db_session.add(
        WbStock(
            wb_sku="WB-STALE-OVERRIDE-1",
            warehouse_id=1,
            warehouse_name="WB",
            stock_qty=5,
            updated_at=datetime.now(timezone.utc),
        )
    )
    db_session.flush()

    response = client.post(
        "/api/v1/wb/from-wb/readiness",
        json={
            "article_id": article_stale.id,
            "limit": 10,
            "freshness_sales_stale_after_days": 3650,
            "freshness_stock_stale_after_days": 3650,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["total_articles_considered"] == 1
    assert body["ready_articles"] == 1
    assert body["not_ready_articles"] == 0

    item = body["items"][0]
    assert item["article_code"] == "STALE-OVERRIDE-1"
    assert item["ready_for_from_wb"] is True
    assert item["freshness_status"] == "fresh"
    assert item["blocker"] is None
    assert item["threshold_days"] == {"sales": 3650, "stock": 3650}
    assert item["threshold_source"] == {"sales": "request", "stock": "request"}
    assert item["next_steps"] == []


def test_wb_from_wb_readiness_uses_admin_freshness_threshold_defaults(client, db_session):
    article_stale = Article(code="STALE-ADMIN-DEFAULTS-1", name="Stale admin defaults")
    bundle_type = BundleType(code="BT-STALE-ADMIN-DEFAULTS", name="Stale admin defaults bundle", is_assorti=False)
    color = Color(inner_code="CLR-STALE-ADMIN-DEFAULTS", pantone_code=None, description=None)

    db_session.add_all([article_stale, bundle_type, color])
    db_session.flush()

    db_session.add(
        ArticleWbMapping(
            article_id=article_stale.id,
            wb_sku="WB-STALE-ADMIN-DEFAULTS-1",
            bundle_type_id=bundle_type.id,
        )
    )
    db_session.add(
        BundleRecipe(
            article_id=article_stale.id,
            bundle_type_id=bundle_type.id,
            color_id=color.id,
            position=1,
        )
    )
    db_session.add(
        WbSalesDaily(
            wb_sku="WB-STALE-ADMIN-DEFAULTS-1",
            date=date(2020, 1, 1),
            sales_qty=3,
            revenue=None,
            created_at=datetime.now(timezone.utc),
        )
    )
    db_session.add(
        WbStock(
            wb_sku="WB-STALE-ADMIN-DEFAULTS-1",
            warehouse_id=1,
            warehouse_name="WB",
            stock_qty=5,
            updated_at=datetime(2020, 1, 2, tzinfo=timezone.utc),
        )
    )
    db_session.flush()

    settings_response = client.put(
        f"/api/v1/planning/core/production-order/settings/{article_stale.id}",
        json={
            "size_weights": [],
            "elastic_bindings": [],
            "in_flight_supply_defaults": [],
            "freshness_sales_stale_after_days": 3650,
            "freshness_stock_stale_after_days": 3650,
        },
    )
    assert settings_response.status_code == 200, settings_response.text

    response = client.post(
        "/api/v1/wb/from-wb/readiness",
        json={
            "article_id": article_stale.id,
            "limit": 10,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["total_articles_considered"] == 1
    assert body["ready_articles"] == 1
    assert body["not_ready_articles"] == 0

    item = body["items"][0]
    assert item["article_code"] == "STALE-ADMIN-DEFAULTS-1"
    assert item["ready_for_from_wb"] is True
    assert item["freshness_status"] == "fresh"
    assert item["blocker"] is None
    assert item["threshold_days"] == {"sales": 3650, "stock": 3650}
    assert item["threshold_source"] == {"sales": "admin_defaults", "stock": "admin_defaults"}
    assert item["next_steps"] == []


def test_wb_from_wb_readiness_admin_defaults_can_force_stale_blocker(client, db_session):
    article_stale = Article(code="STALE-ADMIN-BLOCKER-1", name="Stale admin blocker")
    bundle_type = BundleType(code="BT-STALE-ADMIN-BLOCKER", name="Stale admin blocker bundle", is_assorti=False)
    color = Color(inner_code="CLR-STALE-ADMIN-BLOCKER", pantone_code=None, description=None)
    today_utc = datetime.now(timezone.utc).date()

    db_session.add_all([article_stale, bundle_type, color])
    db_session.flush()

    db_session.add(
        ArticleWbMapping(
            article_id=article_stale.id,
            wb_sku="WB-STALE-ADMIN-BLOCKER-1",
            bundle_type_id=bundle_type.id,
        )
    )
    db_session.add(
        BundleRecipe(
            article_id=article_stale.id,
            bundle_type_id=bundle_type.id,
            color_id=color.id,
            position=1,
        )
    )
    db_session.add(
        WbSalesDaily(
            wb_sku="WB-STALE-ADMIN-BLOCKER-1",
            date=date(2020, 1, 1),
            sales_qty=3,
            revenue=None,
            created_at=datetime.now(timezone.utc),
        )
    )
    db_session.add(
        WbStock(
            wb_sku="WB-STALE-ADMIN-BLOCKER-1",
            warehouse_id=1,
            warehouse_name="WB",
            stock_qty=5,
            updated_at=datetime(2020, 1, 2, tzinfo=timezone.utc),
        )
    )
    db_session.flush()

    settings_response = client.put(
        f"/api/v1/planning/core/production-order/settings/{article_stale.id}",
        json={
            "size_weights": [],
            "elastic_bindings": [],
            "in_flight_supply_defaults": [],
            "freshness_sales_stale_after_days": 1,
            "freshness_stock_stale_after_days": 1,
        },
    )
    assert settings_response.status_code == 200, settings_response.text

    response = client.post(
        "/api/v1/wb/from-wb/readiness",
        json={
            "article_id": article_stale.id,
            "limit": 10,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["total_articles_considered"] == 1
    assert body["ready_articles"] == 0
    assert body["not_ready_articles"] == 1

    item = body["items"][0]
    assert item["article_code"] == "STALE-ADMIN-BLOCKER-1"
    assert item["ready_for_from_wb"] is False
    assert item["freshness_status"] == "stale"
    assert item["blocker"] == "stale_wb_sales_and_stock_data"
    assert item["sales_age_days"] == (today_utc - date(2020, 1, 1)).days
    assert item["stock_oldest_age_days"] == (today_utc - date(2020, 1, 2)).days
    assert item["threshold_days"] == {"sales": 1, "stock": 1}
    assert item["threshold_source"] == {"sales": "admin_defaults", "stock": "admin_defaults"}
    assert item["next_steps"] == ["run_wb_sales_daily_sync_live", "run_wb_stock_sync_live"]


def test_wb_from_wb_readiness_request_thresholds_override_admin_defaults_to_stale_blocker(client, db_session):
    article_stale = Article(code="STALE-REQUEST-OVERRIDE-ADMIN-1", name="Stale request override admin")
    bundle_type = BundleType(code="BT-STALE-REQUEST-OVERRIDE-ADMIN", name="Stale request override admin bundle", is_assorti=False)
    color = Color(inner_code="CLR-STALE-REQUEST-OVERRIDE-ADMIN", pantone_code=None, description=None)
    today_utc = datetime.now(timezone.utc).date()

    db_session.add_all([article_stale, bundle_type, color])
    db_session.flush()

    db_session.add(
        ArticleWbMapping(
            article_id=article_stale.id,
            wb_sku="WB-STALE-REQUEST-OVERRIDE-ADMIN-1",
            bundle_type_id=bundle_type.id,
        )
    )
    db_session.add(
        BundleRecipe(
            article_id=article_stale.id,
            bundle_type_id=bundle_type.id,
            color_id=color.id,
            position=1,
        )
    )
    db_session.add(
        WbSalesDaily(
            wb_sku="WB-STALE-REQUEST-OVERRIDE-ADMIN-1",
            date=date(2020, 1, 1),
            sales_qty=3,
            revenue=None,
            created_at=datetime.now(timezone.utc),
        )
    )
    db_session.add(
        WbStock(
            wb_sku="WB-STALE-REQUEST-OVERRIDE-ADMIN-1",
            warehouse_id=1,
            warehouse_name="WB",
            stock_qty=5,
            updated_at=datetime(2020, 1, 2, tzinfo=timezone.utc),
        )
    )
    db_session.flush()

    settings_response = client.put(
        f"/api/v1/planning/core/production-order/settings/{article_stale.id}",
        json={
            "size_weights": [],
            "elastic_bindings": [],
            "in_flight_supply_defaults": [],
            "freshness_sales_stale_after_days": 3650,
            "freshness_stock_stale_after_days": 3650,
        },
    )
    assert settings_response.status_code == 200, settings_response.text

    response = client.post(
        "/api/v1/wb/from-wb/readiness",
        json={
            "article_id": article_stale.id,
            "limit": 10,
            "freshness_sales_stale_after_days": 1,
            "freshness_stock_stale_after_days": 1,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["total_articles_considered"] == 1
    assert body["ready_articles"] == 0
    assert body["not_ready_articles"] == 1

    item = body["items"][0]
    assert item["article_code"] == "STALE-REQUEST-OVERRIDE-ADMIN-1"
    assert item["ready_for_from_wb"] is False
    assert item["freshness_status"] == "stale"
    assert item["blocker"] == "stale_wb_sales_and_stock_data"
    assert item["sales_age_days"] == (today_utc - date(2020, 1, 1)).days
    assert item["stock_oldest_age_days"] == (today_utc - date(2020, 1, 2)).days
    assert item["threshold_days"] == {"sales": 1, "stock": 1}
    assert item["threshold_source"] == {"sales": "request", "stock": "request"}
    assert item["next_steps"] == ["run_wb_sales_daily_sync_live", "run_wb_stock_sync_live"]


def test_wb_from_wb_readiness_reports_no_bundle_type_in_mapping_blocker(client, db_session):
    article = Article(code="NO-BUNDLE-TYPE-MAP", name="No bundle type mapping")
    db_session.add(article)
    db_session.flush()

    db_session.add(
        ArticleWbMapping(
            article_id=article.id,
            wb_sku="WB-NO-BUNDLE-TYPE",
            bundle_type_id=None,
        )
    )
    db_session.flush()

    response = client.post("/api/v1/wb/from-wb/readiness", json={"article_id": article.id, "limit": 10})
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["total_articles_considered"] == 1
    assert body["ready_articles"] == 0
    assert body["not_ready_articles"] == 1

    item = body["items"][0]
    assert item["article_code"] == "NO-BUNDLE-TYPE-MAP"
    assert item["ready_for_from_wb"] is False
    assert item["mapped_bundle_type_ids"] == []
    assert item["blocker"] == "no_bundle_type_in_mapping"
    assert item["next_steps"] == ["set_bundle_type_id_on_article_wb_mapping"]


def test_wb_from_wb_readiness_reports_stock_only_stale_freshness_blocker(client, db_session):
    article_stale = Article(code="STALE-STOCK-1", name="Stale stock")
    bundle_type = BundleType(code="BT-STALE-STOCK", name="Stale stock bundle", is_assorti=False)
    color = Color(inner_code="CLR-STALE-STOCK", pantone_code=None, description=None)
    today_utc = datetime.now(timezone.utc).date()

    db_session.add_all([article_stale, bundle_type, color])
    db_session.flush()

    db_session.add(
        ArticleWbMapping(article_id=article_stale.id, wb_sku="WB-STALE-STOCK-1", bundle_type_id=bundle_type.id)
    )
    db_session.add(
        BundleRecipe(
            article_id=article_stale.id,
            bundle_type_id=bundle_type.id,
            color_id=color.id,
            position=1,
        )
    )
    db_session.add(
        WbSalesDaily(
            wb_sku="WB-STALE-STOCK-1",
            date=today_utc,
            sales_qty=3,
            revenue=None,
            created_at=datetime.now(timezone.utc),
        )
    )
    db_session.add(
        WbStock(
            wb_sku="WB-STALE-STOCK-1",
            warehouse_id=1,
            warehouse_name="WB",
            stock_qty=5,
            updated_at=datetime(2020, 1, 2, tzinfo=timezone.utc),
        )
    )
    db_session.flush()

    response = client.post("/api/v1/wb/from-wb/readiness", json={"article_id": article_stale.id, "limit": 10})
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["total_articles_considered"] == 1
    assert body["ready_articles"] == 0
    assert body["not_ready_articles"] == 1

    item = body["items"][0]
    assert item["article_code"] == "STALE-STOCK-1"
    assert item["ready_for_from_wb"] is False
    assert item["freshness_status"] == "stale"
    assert item["blocker"] == "stale_wb_stock_data"
    assert item["sales_age_days"] == 0
    assert item["stock_oldest_age_days"] == (today_utc - date(2020, 1, 2)).days
    assert item["threshold_days"] == {"sales": 3, "stock": 2}
    assert item["threshold_source"] == {"sales": "global_default", "stock": "global_default"}
    assert item["next_steps"] == ["run_wb_stock_sync_live"]


def test_wb_from_wb_readiness_reports_stale_sales_and_stock_freshness_blocker(client, db_session):
    article_stale = Article(code="STALE-BOTH-1", name="Stale both")
    bundle_type = BundleType(code="BT-STALE-BOTH", name="Stale both bundle", is_assorti=False)
    color = Color(inner_code="CLR-STALE-BOTH", pantone_code=None, description=None)

    db_session.add_all([article_stale, bundle_type, color])
    db_session.flush()

    db_session.add(
        ArticleWbMapping(article_id=article_stale.id, wb_sku="WB-STALE-BOTH-1", bundle_type_id=bundle_type.id)
    )
    db_session.add(
        BundleRecipe(
            article_id=article_stale.id,
            bundle_type_id=bundle_type.id,
            color_id=color.id,
            position=1,
        )
    )
    db_session.add(
        WbSalesDaily(
            wb_sku="WB-STALE-BOTH-1",
            date=date(2020, 1, 1),
            sales_qty=3,
            revenue=None,
            created_at=datetime.now(timezone.utc),
        )
    )
    db_session.add(
        WbStock(
            wb_sku="WB-STALE-BOTH-1",
            warehouse_id=1,
            warehouse_name="WB",
            stock_qty=5,
            updated_at=datetime(2020, 1, 2, tzinfo=timezone.utc),
        )
    )
    db_session.flush()

    response = client.post("/api/v1/wb/from-wb/readiness", json={"article_id": article_stale.id, "limit": 10})
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["total_articles_considered"] == 1
    assert body["ready_articles"] == 0
    assert body["not_ready_articles"] == 1

    item = body["items"][0]
    assert item["article_code"] == "STALE-BOTH-1"
    assert item["ready_for_from_wb"] is False
    assert item["freshness_status"] == "stale"
    assert item["blocker"] == "stale_wb_sales_and_stock_data"
    assert item["sales_age_days"] is not None
    assert item["stock_oldest_age_days"] is not None
    assert item["threshold_days"] == {"sales": 3, "stock": 2}
    assert item["threshold_source"] == {"sales": "global_default", "stock": "global_default"}
    assert item["next_steps"] == ["run_wb_sales_daily_sync_live", "run_wb_stock_sync_live"]


def test_wb_from_wb_readiness_request_sales_threshold_overrides_admin_defaults_to_stale_sales_blocker(client, db_session):
    article_stale = Article(code="STALE-MIXED-SOURCE-SALES-FAIL-1", name="Stale mixed source sales fail")
    bundle_type = BundleType(code="BT-STALE-MIXED-SOURCE-SALES-FAIL", name="Stale mixed source sales fail bundle", is_assorti=False)
    color = Color(inner_code="CLR-STALE-MIXED-SOURCE-SALES-FAIL", pantone_code=None, description=None)
    today_utc = datetime.now(timezone.utc).date()

    db_session.add_all([article_stale, bundle_type, color])
    db_session.flush()

    db_session.add(
        ArticleWbMapping(
            article_id=article_stale.id,
            wb_sku="WB-STALE-MIXED-SOURCE-SALES-FAIL-1",
            bundle_type_id=bundle_type.id,
        )
    )
    db_session.add(
        BundleRecipe(
            article_id=article_stale.id,
            bundle_type_id=bundle_type.id,
            color_id=color.id,
            position=1,
        )
    )
    db_session.add(
        WbSalesDaily(
            wb_sku="WB-STALE-MIXED-SOURCE-SALES-FAIL-1",
            date=date(2020, 1, 1),
            sales_qty=3,
            revenue=None,
            created_at=datetime.now(timezone.utc),
        )
    )
    db_session.add(
        WbStock(
            wb_sku="WB-STALE-MIXED-SOURCE-SALES-FAIL-1",
            warehouse_id=1,
            warehouse_name="WB",
            stock_qty=5,
            updated_at=datetime(2020, 1, 2, tzinfo=timezone.utc),
        )
    )
    db_session.flush()

    settings_response = client.put(
        f"/api/v1/planning/core/production-order/settings/{article_stale.id}",
        json={
            "size_weights": [],
            "elastic_bindings": [],
            "in_flight_supply_defaults": [],
            "freshness_sales_stale_after_days": 3650,
            "freshness_stock_stale_after_days": 3650,
        },
    )
    assert settings_response.status_code == 200, settings_response.text

    response = client.post(
        "/api/v1/wb/from-wb/readiness",
        json={
            "article_id": article_stale.id,
            "limit": 10,
            "freshness_sales_stale_after_days": 1,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["total_articles_considered"] == 1
    assert body["ready_articles"] == 0
    assert body["not_ready_articles"] == 1

    item = body["items"][0]
    assert item["article_code"] == "STALE-MIXED-SOURCE-SALES-FAIL-1"
    assert item["ready_for_from_wb"] is False
    assert item["freshness_status"] == "stale"
    assert item["blocker"] == "stale_wb_sales_data"
    assert item["sales_age_days"] == (today_utc - date(2020, 1, 1)).days
    assert item["stock_oldest_age_days"] == (today_utc - date(2020, 1, 2)).days
    assert item["threshold_days"] == {"sales": 1, "stock": 3650}
    assert item["threshold_source"] == {"sales": "request", "stock": "admin_defaults"}
    assert item["next_steps"] == ["run_wb_sales_daily_sync_live"]


def test_wb_from_wb_readiness_request_stock_threshold_overrides_admin_defaults_to_stale_stock_blocker(client, db_session):
    article_stale = Article(code="STALE-MIXED-SOURCE-STOCK-FAIL-1", name="Stale mixed source stock fail")
    bundle_type = BundleType(code="BT-STALE-MIXED-SOURCE-STOCK-FAIL", name="Stale mixed source stock fail bundle", is_assorti=False)
    color = Color(inner_code="CLR-STALE-MIXED-SOURCE-STOCK-FAIL", pantone_code=None, description=None)
    today_utc = datetime.now(timezone.utc).date()

    db_session.add_all([article_stale, bundle_type, color])
    db_session.flush()

    db_session.add(
        ArticleWbMapping(
            article_id=article_stale.id,
            wb_sku="WB-STALE-MIXED-SOURCE-STOCK-FAIL-1",
            bundle_type_id=bundle_type.id,
        )
    )
    db_session.add(
        BundleRecipe(
            article_id=article_stale.id,
            bundle_type_id=bundle_type.id,
            color_id=color.id,
            position=1,
        )
    )
    db_session.add(
        WbSalesDaily(
            wb_sku="WB-STALE-MIXED-SOURCE-STOCK-FAIL-1",
            date=date(2020, 1, 1),
            sales_qty=3,
            revenue=None,
            created_at=datetime.now(timezone.utc),
        )
    )
    db_session.add(
        WbStock(
            wb_sku="WB-STALE-MIXED-SOURCE-STOCK-FAIL-1",
            warehouse_id=1,
            warehouse_name="WB",
            stock_qty=5,
            updated_at=datetime(2020, 1, 2, tzinfo=timezone.utc),
        )
    )
    db_session.flush()

    settings_response = client.put(
        f"/api/v1/planning/core/production-order/settings/{article_stale.id}",
        json={
            "size_weights": [],
            "elastic_bindings": [],
            "in_flight_supply_defaults": [],
            "freshness_sales_stale_after_days": 3650,
            "freshness_stock_stale_after_days": 3650,
        },
    )
    assert settings_response.status_code == 200, settings_response.text

    response = client.post(
        "/api/v1/wb/from-wb/readiness",
        json={
            "article_id": article_stale.id,
            "limit": 10,
            "freshness_stock_stale_after_days": 1,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["total_articles_considered"] == 1
    assert body["ready_articles"] == 0
    assert body["not_ready_articles"] == 1

    item = body["items"][0]
    assert item["article_code"] == "STALE-MIXED-SOURCE-STOCK-FAIL-1"
    assert item["ready_for_from_wb"] is False
    assert item["freshness_status"] == "stale"
    assert item["blocker"] == "stale_wb_stock_data"
    assert item["sales_age_days"] == (today_utc - date(2020, 1, 1)).days
    assert item["stock_oldest_age_days"] == (today_utc - date(2020, 1, 2)).days
    assert item["threshold_days"] == {"sales": 3650, "stock": 1}
    assert item["threshold_source"] == {"sales": "admin_defaults", "stock": "request"}
    assert item["next_steps"] == ["run_wb_stock_sync_live"]


def test_wb_from_wb_readiness_uses_mixed_freshness_threshold_sources(client, db_session):
    article_stale = Article(code="STALE-MIXED-SOURCE-1", name="Stale mixed source")
    bundle_type = BundleType(code="BT-STALE-MIXED-SOURCE", name="Stale mixed source bundle", is_assorti=False)
    color = Color(inner_code="CLR-STALE-MIXED-SOURCE", pantone_code=None, description=None)

    db_session.add_all([article_stale, bundle_type, color])
    db_session.flush()

    db_session.add(
        ArticleWbMapping(
            article_id=article_stale.id,
            wb_sku="WB-STALE-MIXED-SOURCE-1",
            bundle_type_id=bundle_type.id,
        )
    )
    db_session.add(
        BundleRecipe(
            article_id=article_stale.id,
            bundle_type_id=bundle_type.id,
            color_id=color.id,
            position=1,
        )
    )
    db_session.add(
        WbSalesDaily(
            wb_sku="WB-STALE-MIXED-SOURCE-1",
            date=date(2020, 1, 1),
            sales_qty=3,
            revenue=None,
            created_at=datetime.now(timezone.utc),
        )
    )
    db_session.add(
        WbStock(
            wb_sku="WB-STALE-MIXED-SOURCE-1",
            warehouse_id=1,
            warehouse_name="WB",
            stock_qty=5,
            updated_at=datetime(2020, 1, 2, tzinfo=timezone.utc),
        )
    )
    db_session.flush()

    settings_response = client.put(
        f"/api/v1/planning/core/production-order/settings/{article_stale.id}",
        json={
            "size_weights": [],
            "elastic_bindings": [],
            "in_flight_supply_defaults": [],
            "freshness_sales_stale_after_days": 1,
            "freshness_stock_stale_after_days": 3650,
        },
    )
    assert settings_response.status_code == 200, settings_response.text

    response = client.post(
        "/api/v1/wb/from-wb/readiness",
        json={
            "article_id": article_stale.id,
            "limit": 10,
            "freshness_sales_stale_after_days": 3650,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["total_articles_considered"] == 1
    assert body["ready_articles"] == 1
    assert body["not_ready_articles"] == 0

    item = body["items"][0]
    assert item["article_code"] == "STALE-MIXED-SOURCE-1"
    assert item["ready_for_from_wb"] is True
    assert item["freshness_status"] == "fresh"
    assert item["blocker"] is None
    assert item["threshold_days"] == {"sales": 3650, "stock": 3650}
    assert item["threshold_source"] == {"sales": "request", "stock": "admin_defaults"}
    assert item["next_steps"] == []


def test_wb_from_wb_readiness_uses_mirrored_mixed_freshness_threshold_sources(client, db_session):
    article_stale = Article(code="STALE-MIXED-SOURCE-2", name="Stale mixed source mirrored")
    bundle_type = BundleType(code="BT-STALE-MIXED-SOURCE-2", name="Stale mixed source mirrored bundle", is_assorti=False)
    color = Color(inner_code="CLR-STALE-MIXED-SOURCE-2", pantone_code=None, description=None)

    db_session.add_all([article_stale, bundle_type, color])
    db_session.flush()

    db_session.add(
        ArticleWbMapping(
            article_id=article_stale.id,
            wb_sku="WB-STALE-MIXED-SOURCE-2",
            bundle_type_id=bundle_type.id,
        )
    )
    db_session.add(
        BundleRecipe(
            article_id=article_stale.id,
            bundle_type_id=bundle_type.id,
            color_id=color.id,
            position=1,
        )
    )
    db_session.add(
        WbSalesDaily(
            wb_sku="WB-STALE-MIXED-SOURCE-2",
            date=date(2020, 1, 1),
            sales_qty=3,
            revenue=None,
            created_at=datetime.now(timezone.utc),
        )
    )
    db_session.add(
        WbStock(
            wb_sku="WB-STALE-MIXED-SOURCE-2",
            warehouse_id=1,
            warehouse_name="WB",
            stock_qty=5,
            updated_at=datetime(2020, 1, 2, tzinfo=timezone.utc),
        )
    )
    db_session.flush()

    settings_response = client.put(
        f"/api/v1/planning/core/production-order/settings/{article_stale.id}",
        json={
            "size_weights": [],
            "elastic_bindings": [],
            "in_flight_supply_defaults": [],
            "freshness_sales_stale_after_days": 3650,
            "freshness_stock_stale_after_days": 1,
        },
    )
    assert settings_response.status_code == 200, settings_response.text

    response = client.post(
        "/api/v1/wb/from-wb/readiness",
        json={
            "article_id": article_stale.id,
            "limit": 10,
            "freshness_stock_stale_after_days": 3650,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["total_articles_considered"] == 1
    assert body["ready_articles"] == 1
    assert body["not_ready_articles"] == 0

    item = body["items"][0]
    assert item["article_code"] == "STALE-MIXED-SOURCE-2"
    assert item["ready_for_from_wb"] is True
    assert item["freshness_status"] == "fresh"
    assert item["blocker"] is None
    assert item["threshold_days"] == {"sales": 3650, "stock": 3650}
    assert item["threshold_source"] == {"sales": "admin_defaults", "stock": "request"}
    assert item["next_steps"] == []


def test_wb_live_commission_sync_summarizes_subjects(client, db_session, monkeypatch):
    account = WbIntegrationAccount(
        name="WB Commission",
        supplier_id=None,
        api_token="token-8",
        is_active=True,
    )
    db_session.add(account)
    db_session.flush()

    def fake_wb_get_json_object(*, base_url, path, token, params=None):
        return {
            "report": [
                {"subjectID": 10, "subjectName": "A", "kgvpSupplier": 21.5},
                {"subjectID": 11, "subjectName": "B", "kgvpSupplier": 30},
                {"subjectID": 12, "subjectName": "C", "kgvpSupplier": None},
            ]
        }

    monkeypatch.setattr(wb_ingest, "_wb_get_json_object", fake_wb_get_json_object)

    response = client.post(
        "/api/v1/wb/commission/sync-live",
        json={"account_id": account.id, "top_subjects_limit": 2},
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["account_id"] == account.id
    assert body["fetched_rows"] == 3
    assert body["subjects_with_commission"] == 2
    assert body["avg_kgvp_supplier_percent"] == 25.75
    assert body["min_kgvp_supplier_percent"] == 21.5
    assert body["max_kgvp_supplier_percent"] == 30.0
    assert [row["subject_name"] for row in body["subjects"]] == ["B", "A"]


def test_wb_live_supplies_sync_counts_statuses(client, db_session, monkeypatch):
    account = WbIntegrationAccount(
        name="WB Supplies",
        supplier_id=None,
        api_token="token-9",
        is_active=True,
    )
    db_session.add(account)
    db_session.flush()

    def fake_wb_post_json_rows(*, base_url, path, token, payload):
        assert payload["limit"] == 100
        assert payload["isClosed"] is False
        return [
            {
                "supplyID": 1001,
                "statusID": 5,
                "createDate": "2026-02-26T00:00:00+03:00",
                "supplyDate": "2026-02-26T00:00:00+03:00",
                "updatedDate": "2026-02-26T01:00:00+03:00",
            },
            {
                "supplyID": 1002,
                "statusID": 3,
                "createDate": "2026-02-25T00:00:00+03:00",
                "supplyDate": "2026-02-25T00:00:00+03:00",
                "updatedDate": "2026-02-25T02:00:00+03:00",
            },
            {
                "supplyID": 1003,
                "statusID": 5,
                "createDate": "2026-02-24T00:00:00+03:00",
                "supplyDate": "2026-02-24T00:00:00+03:00",
                "updatedDate": "2026-02-24T01:00:00+03:00",
            },
        ]

    monkeypatch.setattr(wb_ingest, "_wb_post_json_rows", fake_wb_post_json_rows)

    response = client.post(
        "/api/v1/wb/supplies/sync-live",
        json={"account_id": account.id, "limit": 100, "is_closed": False},
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["account_id"] == account.id
    assert body["fetched_rows"] == 3
    assert body["status_counts"] == {"5": 2, "3": 1}
    assert len(body["supplies"]) == 3
    assert body["supplies"][0]["supply_id"] == 1001
