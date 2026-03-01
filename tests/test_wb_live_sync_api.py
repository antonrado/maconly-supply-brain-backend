from __future__ import annotations

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
    assert response.json()["detail"] == "No active WB integration account configured"


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
    assert "rate limit" in str(exc.value.detail).lower()


def test_wb_from_wb_readiness_reports_blockers_and_ready(client, db_session):
    article_ready = Article(code="READY-1", name="Ready")
    article_no_recipe = Article(code="BLOCK-NO-RECIPE", name="No recipe")
    article_missing_bundle = Article(code="BLOCK-MISSING", name="Missing bundle")

    bt_main = BundleType(code="BT-MAIN", name="Main", is_assorti=False)
    bt_alt = BundleType(code="BT-ALT", name="Alt", is_assorti=True)
    color_a = Color(inner_code="CLR-READINESS-A", pantone_code=None, description=None)
    color_b = Color(inner_code="CLR-READINESS-B", pantone_code=None, description=None)

    db_session.add_all([
        article_ready,
        article_no_recipe,
        article_missing_bundle,
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
        ]
    )
    db_session.flush()

    response = client.post("/api/v1/wb/from-wb/readiness", json={"limit": 10})
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["total_articles_considered"] == 3
    assert body["ready_articles"] == 1
    assert body["not_ready_articles"] == 2

    items = {row["article_code"]: row for row in body["items"]}

    assert items["READY-1"]["ready_for_from_wb"] is True
    assert items["READY-1"]["blocker"] is None

    assert items["BLOCK-NO-RECIPE"]["ready_for_from_wb"] is False
    assert items["BLOCK-NO-RECIPE"]["blocker"] == "no_bundle_recipe"

    assert items["BLOCK-MISSING"]["ready_for_from_wb"] is False
    assert items["BLOCK-MISSING"]["blocker"] == "missing_bundle_recipe_bundle_types"
    assert items["BLOCK-MISSING"]["missing_recipe_bundle_type_ids"] == [bt_alt.id]


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
