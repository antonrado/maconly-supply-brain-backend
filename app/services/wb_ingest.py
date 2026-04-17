from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import time

from fastapi import HTTPException, status
import httpx
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.models import (
    Article,
    ArticlePlanningSettings,
    ArticleWbMapping,
    BundleRecipe,
    SkuUnit,
    WbIntegrationAccount,
    WbSalesDaily,
    WbStock,
)
from app.services.planning_production_order_freshness import (
    build_from_wb_freshness_blocker,
    build_from_wb_freshness_next_steps,
    build_from_wb_freshness_snapshot,
    resolve_from_wb_freshness_thresholds,
)
from app.schemas.wb import (
    ArticleWbMappingItem,
    WbImportSummary,
    WbFromWbReadinessItem,
    WbFromWbReadinessSummary,
    WbLiveArticleBootstrapItem,
    WbLiveArticleBootstrapSummary,
    WbLiveCommissionSubjectItem,
    WbLiveCommissionSyncSummary,
    WbLiveMappingDiscoverItem,
    WbLiveMappingDiscoverSummary,
    WbLiveMappingSyncSummary,
    WbLiveSupplyStatusItem,
    WbLiveSupplySyncSummary,
    WbLiveSyncSummary,
    WbSalesDailyItem,
    WbStockItem,
)


WB_REPORTS_API_BASE_URL = "https://statistics-api.wildberries.ru"
WB_REPORTS_SALES_PATH = "/api/v1/supplier/sales"
WB_REPORTS_STOCK_PATH = "/api/v1/supplier/stocks"
WB_TARIFFS_API_BASE_URL = "https://common-api.wildberries.ru"
WB_TARIFFS_COMMISSION_PATH = "/api/v1/tariffs/commission"
WB_SUPPLIES_API_BASE_URL = "https://supplies-api.wildberries.ru"
WB_SUPPLIES_LIST_PATH = "/api/v1/supplies"
WB_SYNC_DEFAULT_MAX_PAGES = 5
WB_SYNC_DEFAULT_SALES_LOOKBACK_DAYS = 30
WB_SYNC_DEFAULT_STOCK_DATE_FROM = date(2019, 6, 20)
WB_SYNC_HTTP_TIMEOUT_SECONDS = 30.0
WB_SYNC_RATE_LIMIT_MAX_RETRIES = 2
WB_SYNC_RATE_LIMIT_MAX_SLEEP_SECONDS = 60


def _utcnow() -> datetime:
    """Helper to get timezone-aware UTC now for updated_at default."""
    return datetime.now(timezone.utc)


def _build_wb_account_resolution_detail(
    *,
    code: str,
    message: str,
    next_steps: list[str],
    field: str | None = None,
    field_metadata: dict[str, object] | None = None,
    account_id: int | None = None,
) -> dict[str, object]:
    detail = {
        "code": code,
        "message": message,
        "next_steps": list(next_steps),
    }
    if field is not None:
        detail["field"] = field
    if field_metadata is not None:
        detail["field_metadata"] = dict(field_metadata)
    if account_id is not None:
        detail["account_id"] = int(account_id)
    return detail


def _build_wb_api_failure_detail(
    *,
    code: str,
    message: str,
    next_steps: list[str],
    operation: str | None = None,
    operation_metadata: dict[str, object] | None = None,
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    detail = {
        "code": code,
        "message": message,
        "next_steps": list(next_steps),
    }
    if operation is not None:
        detail["operation"] = operation
    if operation_metadata is not None:
        detail["operation_metadata"] = dict(operation_metadata)
    if extra:
        detail.update(extra)
    return detail


def _build_article_not_found_detail(*, article_id: int) -> dict[str, object]:
    return {
        "code": "article_not_found",
        "message": "Article not found",
        "article_id": int(article_id),
        "field": "article_id",
        "field_metadata": {
            "description": "Requested article identifier",
            "type": "int",
        },
        "next_steps": ["use_existing_article_id"],
    }


def _build_wb_mapping_article_not_found_detail(*, article_id: int, wb_sku: str) -> dict[str, object]:
    return {
        "code": "wb_mapping_article_not_found",
        "message": "Referenced article_id does not exist",
        "field": "article_id",
        "field_metadata": {
            "description": "Article identifier in article-to-WB mapping import payload",
            "type": "int",
        },
        "article_id": int(article_id),
        "wb_sku": str(wb_sku),
        "next_steps": ["use_existing_article_id"],
    }


def _resolve_wb_integration_account(
    db: Session,
    *,
    account_id: int | None,
) -> WbIntegrationAccount:
    query = db.query(WbIntegrationAccount).filter(WbIntegrationAccount.is_active.is_(True))
    if account_id is not None:
        query = query.filter(WbIntegrationAccount.id == account_id)

    account = query.order_by(WbIntegrationAccount.id).first()
    if account is None:
        if account_id is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=_build_wb_account_resolution_detail(
                    code="wb_integration_account_not_found",
                    message="Active WB integration account not found",
                    field="account_id",
                    field_metadata={
                        "description": "WB integration account identifier",
                        "type": "int",
                    },
                    account_id=account_id,
                    next_steps=["use_existing_active_wb_account_id"],
                ),
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_build_wb_account_resolution_detail(
                code="no_active_wb_integration_account",
                message="No active WB integration account configured",
                next_steps=["create_or_activate_wb_integration_account"],
            ),
        )

    token = (account.api_token or "").strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_build_wb_account_resolution_detail(
                code="wb_integration_account_empty_api_token",
                message="WB integration account has empty api_token",
                field="api_token",
                field_metadata={
                    "description": "WB integration account API token",
                    "type": "string",
                },
                account_id=account.id,
                next_steps=["set_wb_integration_account_api_token"],
            ),
        )

    return account


def _as_rfc3339(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    value = value.astimezone(timezone.utc)
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_wb_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None

    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        else:
            return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _coerce_float(value: object) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (float, int, Decimal)):
        return float(value)
    text = str(value).strip()
    if not text:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def _coerce_int(value: object) -> int:
    if value is None:
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float, Decimal)):
        return int(value)
    text = str(value).strip()
    if not text:
        return 0
    try:
        return int(float(text))
    except ValueError:
        return 0


def _coerce_optional_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, (float, int, Decimal)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _coerce_optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float, Decimal)):
        return int(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def _wb_request(
    *,
    method: str,
    url: str,
    token: str,
    params: dict[str, object] | None = None,
    json_body: dict[str, object] | None = None,
) -> httpx.Response:
    response: httpx.Response | None = None
    for attempt in range(WB_SYNC_RATE_LIMIT_MAX_RETRIES + 1):
        try:
            response = httpx.request(
                method,
                url,
                headers={"Authorization": token},
                params=params,
                json=json_body,
                timeout=WB_SYNC_HTTP_TIMEOUT_SECONDS,
            )
        except httpx.RequestError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=_build_wb_api_failure_detail(
                    code="wb_api_request_failed",
                    message="WB API request failed",
                    next_steps=["retry_wb_live_sync"],
                    operation="http_request",
                    operation_metadata={"method": str(method)},
                    extra={"error": str(exc)},
                ),
            ) from exc

        if response.status_code != status.HTTP_429_TOO_MANY_REQUESTS:
            break

        retry_after_header = response.headers.get("X-Ratelimit-Retry") or response.headers.get("Retry-After")
        retry_after = 1
        if retry_after_header:
            try:
                retry_after = max(int(float(retry_after_header)), 1)
            except ValueError:
                retry_after = 1

        if attempt >= WB_SYNC_RATE_LIMIT_MAX_RETRIES:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=_build_wb_api_failure_detail(
                    code="wb_api_rate_limit_exceeded",
                    message="WB API rate limit exceeded",
                    next_steps=["retry_wb_live_sync_later"],
                    operation="http_request",
                    operation_metadata={"method": str(method)},
                    extra={
                        "retry_after_seconds": retry_after,
                        "retry_after_raw": retry_after_header,
                    },
                ),
            )

        time.sleep(min(retry_after, WB_SYNC_RATE_LIMIT_MAX_SLEEP_SECONDS))

    if response is None:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=_build_wb_api_failure_detail(
                code="wb_api_no_response",
                message="WB API request failed: no response",
                next_steps=["retry_wb_live_sync"],
                operation="http_request",
                operation_metadata={"method": str(method)},
            ),
        )

    if response.status_code == status.HTTP_401_UNAUTHORIZED:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_build_wb_api_failure_detail(
                code="wb_api_unauthorized",
                message="WB API token is unauthorized for this method",
                next_steps=["check_wb_api_token_permissions"],
                operation="http_request",
                operation_metadata={"method": str(method)},
            ),
        )

    if response.status_code >= status.HTTP_400_BAD_REQUEST:
        body_preview = response.text[:500]
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=_build_wb_api_failure_detail(
                code="wb_api_http_error",
                message="WB API returned an unexpected HTTP error",
                next_steps=["retry_wb_live_sync", "check_wb_api_status_or_request_payload"],
                operation="http_request",
                operation_metadata={"method": str(method)},
                extra={
                    "upstream_status_code": int(response.status_code),
                    "body_preview": body_preview,
                },
            ),
        )

    return response


def _wb_parse_json_payload(response: httpx.Response) -> object:
    try:
        return response.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=_build_wb_api_failure_detail(
                code="wb_api_invalid_json",
                message="WB API response is not valid JSON",
                next_steps=["retry_wb_live_sync", "inspect_wb_api_response_format"],
                operation="parse_json_response",
                operation_metadata={"expected_type": "json"},
            ),
        ) from exc


def _normalize_wb_json_rows(payload: object) -> list[dict[str, object]]:
    if not isinstance(payload, list):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=_build_wb_api_failure_detail(
                code="wb_api_invalid_rows_format",
                message="WB API response format is invalid: expected array",
                next_steps=["inspect_wb_api_response_format"],
                operation="normalize_json_rows",
                operation_metadata={"expected_type": "list[object]"},
            ),
        )

    normalized: list[dict[str, object]] = []
    for row in payload:
        if isinstance(row, dict):
            normalized.append(row)
    return normalized


def _wb_get_json_rows(
    *,
    path: str,
    token: str,
    params: dict[str, object],
) -> list[dict[str, object]]:
    url = f"{WB_REPORTS_API_BASE_URL}{path}"
    response = _wb_request(
        method="GET",
        url=url,
        token=token,
        params=params,
    )
    payload = _wb_parse_json_payload(response)
    return _normalize_wb_json_rows(payload)


def _wb_get_json_object(
    *,
    base_url: str,
    path: str,
    token: str,
    params: dict[str, object] | None = None,
) -> dict[str, object]:
    response = _wb_request(
        method="GET",
        url=f"{base_url}{path}",
        token=token,
        params=params,
    )
    payload = _wb_parse_json_payload(response)
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=_build_wb_api_failure_detail(
                code="wb_api_invalid_object_format",
                message="WB API response format is invalid: expected object",
                next_steps=["inspect_wb_api_response_format"],
                operation="normalize_json_object",
                operation_metadata={"expected_type": "object"},
            ),
        )
    return payload


def _wb_post_json_rows(
    *,
    base_url: str,
    path: str,
    token: str,
    payload: dict[str, object],
) -> list[dict[str, object]]:
    response = _wb_request(
        method="POST",
        url=f"{base_url}{path}",
        token=token,
        json_body=payload,
    )
    response_payload = _wb_parse_json_payload(response)
    return _normalize_wb_json_rows(response_payload)


def _fetch_wb_rows_paginated(
    *,
    path: str,
    token: str,
    initial_date_from: str,
    max_pages: int,
    include_flag_zero: bool,
) -> tuple[list[dict[str, object]], int, str | None]:
    rows: list[dict[str, object]] = []
    pages_with_data = 0
    cursor = initial_date_from

    for _ in range(max_pages):
        params: dict[str, object] = {"dateFrom": cursor}
        if include_flag_zero:
            params["flag"] = 0

        page_rows = _wb_get_json_rows(path=path, token=token, params=params)
        if not page_rows:
            return rows, pages_with_data, cursor

        pages_with_data += 1
        rows.extend(page_rows)

        next_cursor_raw = page_rows[-1].get("lastChangeDate")
        next_cursor = str(next_cursor_raw).strip() if next_cursor_raw is not None else ""
        if not next_cursor or next_cursor == cursor:
            return rows, pages_with_data, next_cursor or None

        cursor = next_cursor

    return rows, pages_with_data, cursor


def _extract_sales_daily_items_from_wb_rows(
    rows: list[dict[str, object]],
) -> list[WbSalesDailyItem]:
    aggregate: dict[tuple[str, date], dict[str, float | int]] = {}

    for row in rows:
        wb_sku = str(row.get("barcode") or "").strip()
        if not wb_sku:
            continue

        sale_id = str(row.get("saleID") or "").strip().upper()
        if sale_id.startswith("R"):
            # Returns are skipped in this operational feed sync.
            continue

        row_date = _parse_wb_datetime(row.get("date"))
        if row_date is None:
            continue

        revenue = _coerce_float(row.get("finishedPrice"))
        if revenue <= 0:
            revenue = _coerce_float(row.get("priceWithDisc"))
        if revenue <= 0:
            revenue = _coerce_float(row.get("totalPrice"))
        if revenue <= 0:
            revenue = _coerce_float(row.get("forPay"))

        key = (wb_sku, row_date.date())
        bucket = aggregate.setdefault(key, {"qty": 0, "revenue": 0.0})
        bucket["qty"] = int(bucket["qty"]) + 1
        bucket["revenue"] = float(bucket["revenue"]) + max(revenue, 0.0)

    items: list[WbSalesDailyItem] = []
    for (wb_sku, row_day), bucket in sorted(aggregate.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        items.append(
            WbSalesDailyItem(
                wb_sku=wb_sku,
                date=row_day,
                sales_qty=int(bucket["qty"]),
                revenue=round(float(bucket["revenue"]), 2),
            )
        )
    return items


def _extract_article_wb_pairs_from_wb_rows(
    rows: list[dict[str, object]],
) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for row in rows:
        article_code = str(row.get("supplierArticle") or "").strip()
        wb_sku = str(row.get("barcode") or "").strip()
        if not article_code or not wb_sku:
            continue
        pairs.add((article_code, wb_sku))
    return pairs


def _normalize_article_code(value: str) -> str:
    return "".join(ch for ch in value.upper() if ch.isalnum())


def _build_article_match_index(
    db: Session,
    *,
    exact_article_codes: set[str],
) -> tuple[dict[str, tuple[int, str]], dict[str, list[tuple[int, str]]]]:
    exact_by_code: dict[str, tuple[int, str]] = {}
    if exact_article_codes:
        exact_rows = db.query(Article.id, Article.code).filter(Article.code.in_(exact_article_codes)).all()
        for article_id, article_code in exact_rows:
            exact_by_code[str(article_code)] = (int(article_id), str(article_code))

    normalized_by_code: dict[str, list[tuple[int, str]]] = defaultdict(list)
    all_rows = db.query(Article.id, Article.code).all()
    for article_id, article_code in all_rows:
        code_text = str(article_code)
        normalized = _normalize_article_code(code_text)
        if not normalized:
            continue
        normalized_by_code[normalized].append((int(article_id), code_text))

    return exact_by_code, normalized_by_code


def _resolve_article_match(
    *,
    supplier_article: str,
    exact_by_code: dict[str, tuple[int, str]],
    normalized_by_code: dict[str, list[tuple[int, str]]],
) -> tuple[str, int | None, str | None]:
    exact = exact_by_code.get(supplier_article)
    if exact is not None:
        return "exact", exact[0], exact[1]

    normalized = _normalize_article_code(supplier_article)
    if not normalized:
        return "none", None, None

    normalized_matches = normalized_by_code.get(normalized, [])
    if len(normalized_matches) == 1:
        article_id, article_code = normalized_matches[0]
        return "normalized", article_id, article_code

    if len(normalized_matches) > 1:
        return "ambiguous_normalized", None, None

    return "none", None, None


def _collect_supplier_article_aggregates(rows: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    aggregates: dict[str, dict[str, object]] = defaultdict(
        lambda: {"rows": 0, "wb_skus": set()}
    )
    for row in rows:
        supplier_article = str(row.get("supplierArticle") or "").strip()
        if not supplier_article:
            continue

        wb_sku = str(row.get("barcode") or "").strip()
        bucket = aggregates[supplier_article]
        bucket["rows"] = int(bucket["rows"]) + 1
        if wb_sku:
            bucket_wb_skus = bucket.get("wb_skus")
            if isinstance(bucket_wb_skus, set):
                bucket_wb_skus.add(wb_sku)

    return aggregates


def _extract_stock_items_from_wb_rows(rows: list[dict[str, object]]) -> list[WbStockItem]:
    aggregate: dict[str, dict[str, object]] = defaultdict(
        lambda: {"stock_qty": 0, "updated_at": None}
    )

    for row in rows:
        wb_sku = str(row.get("barcode") or "").strip()
        if not wb_sku:
            continue

        qty = max(_coerce_int(row.get("quantity")), 0)
        row_updated_at = _parse_wb_datetime(row.get("lastChangeDate"))

        bucket = aggregate[wb_sku]
        bucket["stock_qty"] = int(bucket["stock_qty"]) + qty

        prev_updated = bucket.get("updated_at")
        if isinstance(prev_updated, datetime):
            if row_updated_at is not None and row_updated_at > prev_updated:
                bucket["updated_at"] = row_updated_at
        elif row_updated_at is not None:
            bucket["updated_at"] = row_updated_at

    items: list[WbStockItem] = []
    for wb_sku in sorted(aggregate.keys()):
        bucket = aggregate[wb_sku]
        updated_at = bucket.get("updated_at")
        if not isinstance(updated_at, datetime):
            updated_at = _utcnow()

        items.append(
            WbStockItem(
                wb_sku=wb_sku,
                warehouse_id=None,
                warehouse_name="WB_TOTAL",
                stock_qty=max(_coerce_int(bucket.get("stock_qty")), 0),
                updated_at=updated_at,
            )
        )

    return items


def sync_sales_daily_from_wb_api(
    db: Session,
    *,
    account_id: int | None,
    date_from: datetime | None,
    max_pages: int,
) -> WbLiveSyncSummary:
    account = _resolve_wb_integration_account(db=db, account_id=account_id)
    start_at = date_from or (_utcnow() - timedelta(days=WB_SYNC_DEFAULT_SALES_LOOKBACK_DAYS))
    date_from_effective = _as_rfc3339(start_at)

    rows, pages_with_data, next_cursor = _fetch_wb_rows_paginated(
        path=WB_REPORTS_SALES_PATH,
        token=account.api_token,
        initial_date_from=date_from_effective,
        max_pages=max_pages,
        include_flag_zero=True,
    )
    items = _extract_sales_daily_items_from_wb_rows(rows)
    import_summary = load_sales_daily(db=db, items=items)

    return WbLiveSyncSummary(
        account_id=account.id,
        fetched_rows=len(rows),
        inserted=import_summary.inserted,
        updated=import_summary.updated,
        pages_requested=max_pages,
        pages_with_data=pages_with_data,
        date_from_effective=date_from_effective,
        next_cursor=next_cursor,
    )


def sync_article_mapping_from_wb_api(
    db: Session,
    *,
    account_id: int | None,
    date_from: datetime | None,
    max_pages: int,
    default_bundle_type_id: int | None,
) -> WbLiveMappingSyncSummary:
    account = _resolve_wb_integration_account(db=db, account_id=account_id)
    start_at = date_from or (_utcnow() - timedelta(days=WB_SYNC_DEFAULT_SALES_LOOKBACK_DAYS))
    date_from_effective = _as_rfc3339(start_at)

    rows, pages_with_data, next_cursor = _fetch_wb_rows_paginated(
        path=WB_REPORTS_SALES_PATH,
        token=account.api_token,
        initial_date_from=date_from_effective,
        max_pages=max_pages,
        include_flag_zero=True,
    )

    pairs = _extract_article_wb_pairs_from_wb_rows(rows)
    candidate_pairs = len(pairs)
    if candidate_pairs == 0:
        return WbLiveMappingSyncSummary(
            account_id=account.id,
            fetched_rows=len(rows),
            pages_requested=max_pages,
            pages_with_data=pages_with_data,
            date_from_effective=date_from_effective,
            next_cursor=next_cursor,
            candidate_pairs=0,
            matched_pairs=0,
            unmatched_pairs=0,
            exact_matched_pairs=0,
            normalized_matched_pairs=0,
            ambiguous_normalized_pairs=0,
            inserted=0,
            updated=0,
        )

    exact_by_code, normalized_by_code = _build_article_match_index(
        db=db,
        exact_article_codes={article_code for article_code, _wb_sku in pairs},
    )

    mapping_items: list[ArticleWbMappingItem] = []
    exact_matched_pairs = 0
    normalized_matched_pairs = 0
    ambiguous_normalized_pairs = 0
    for article_code, wb_sku in sorted(pairs):
        match_source, article_id, _matched_code = _resolve_article_match(
            supplier_article=article_code,
            exact_by_code=exact_by_code,
            normalized_by_code=normalized_by_code,
        )

        if match_source == "exact":
            exact_matched_pairs += 1
        elif match_source == "normalized":
            normalized_matched_pairs += 1
        elif match_source == "ambiguous_normalized":
            ambiguous_normalized_pairs += 1

        if article_id is None:
            continue

        mapping_items.append(
            ArticleWbMappingItem(
                article_id=article_id,
                wb_sku=wb_sku,
                bundle_type_id=default_bundle_type_id,
            )
        )

    matched_pairs = exact_matched_pairs + normalized_matched_pairs
    unmatched_pairs = max(candidate_pairs - matched_pairs - ambiguous_normalized_pairs, 0)
    import_summary = map_bundles_to_sku(db=db, items=mapping_items)

    return WbLiveMappingSyncSummary(
        account_id=account.id,
        fetched_rows=len(rows),
        pages_requested=max_pages,
        pages_with_data=pages_with_data,
        date_from_effective=date_from_effective,
        next_cursor=next_cursor,
        candidate_pairs=candidate_pairs,
        matched_pairs=matched_pairs,
        unmatched_pairs=unmatched_pairs,
        exact_matched_pairs=exact_matched_pairs,
        normalized_matched_pairs=normalized_matched_pairs,
        ambiguous_normalized_pairs=ambiguous_normalized_pairs,
        inserted=import_summary.inserted,
        updated=import_summary.updated,
    )


def discover_article_mapping_from_wb_api(
    db: Session,
    *,
    account_id: int | None,
    date_from: datetime | None,
    max_pages: int,
    limit: int,
) -> WbLiveMappingDiscoverSummary:
    account = _resolve_wb_integration_account(db=db, account_id=account_id)
    start_at = date_from or (_utcnow() - timedelta(days=WB_SYNC_DEFAULT_SALES_LOOKBACK_DAYS))
    date_from_effective = _as_rfc3339(start_at)

    rows, pages_with_data, next_cursor = _fetch_wb_rows_paginated(
        path=WB_REPORTS_SALES_PATH,
        token=account.api_token,
        initial_date_from=date_from_effective,
        max_pages=max_pages,
        include_flag_zero=True,
    )

    aggregates = _collect_supplier_article_aggregates(rows)
    sorted_codes = sorted(
        aggregates.keys(),
        key=lambda code: (-int(aggregates[code]["rows"]), code),
    )
    selected_codes = sorted_codes[:limit]
    candidate_supplier_articles = len(selected_codes)

    existing_by_code: dict[str, Article] = {}
    if selected_codes:
        existing_rows = db.query(Article).filter(Article.code.in_(selected_codes)).all()
        existing_by_code = {str(row.code): row for row in existing_rows}

    existing_articles = 0
    inserted_articles = 0
    skipped_invalid = 0
    items: list[WbLiveArticleBootstrapItem] = []

    for supplier_article in selected_codes:
        bucket = aggregates[supplier_article]
        row_count = int(bucket["rows"])

        if len(supplier_article) > 50:
            skipped_invalid += 1
            items.append(
                WbLiveArticleBootstrapItem(
                    supplier_article=supplier_article,
                    rows=row_count,
                    status="invalid_too_long",
                    article_id=None,
                )
            )
            continue

        existing = existing_by_code.get(supplier_article)
        if existing is not None:
            existing_articles += 1
            items.append(
                WbLiveArticleBootstrapItem(
                    supplier_article=supplier_article,
                    rows=row_count,
                    status="existing",
                    article_id=int(existing.id),
                )
            )
            continue

        new_article = Article(code=supplier_article, name=supplier_article)
        db.add(new_article)
        db.flush()
        existing_by_code[supplier_article] = new_article
        inserted_articles += 1

        items.append(
            WbLiveArticleBootstrapItem(
                supplier_article=supplier_article,
                rows=row_count,
                status="inserted",
                article_id=int(new_article.id),
            )
        )

    db.commit()

    return WbLiveArticleBootstrapSummary(
        account_id=account.id,
        fetched_rows=len(rows),
        pages_requested=max_pages,
        pages_with_data=pages_with_data,
        date_from_effective=date_from_effective,
        next_cursor=next_cursor,
        candidate_supplier_articles=candidate_supplier_articles,
        existing_articles=existing_articles,
        inserted_articles=inserted_articles,
        skipped_invalid=skipped_invalid,
        dry_run=False,
        items=items,
    )


def bootstrap_articles_from_wb_api(
    db: Session,
    *,
    account_id: int | None,
    date_from: datetime | None,
    max_pages: int,
    limit: int,
    dry_run: bool,
) -> WbLiveArticleBootstrapSummary:
    account = _resolve_wb_integration_account(db=db, account_id=account_id)
    start_at = date_from or (_utcnow() - timedelta(days=WB_SYNC_DEFAULT_SALES_LOOKBACK_DAYS))
    date_from_effective = _as_rfc3339(start_at)

    rows, pages_with_data, next_cursor = _fetch_wb_rows_paginated(
        path=WB_REPORTS_SALES_PATH,
        token=account.api_token,
        initial_date_from=date_from_effective,
        max_pages=max_pages,
        include_flag_zero=True,
    )

    aggregates = _collect_supplier_article_aggregates(rows)
    sorted_codes = sorted(
        aggregates.keys(),
        key=lambda code: (-int(aggregates[code]["rows"]), code),
    )
    selected_codes = sorted_codes[:limit]
    candidate_supplier_articles = len(selected_codes)

    existing_by_code: dict[str, Article] = {}
    if selected_codes:
        existing_rows = db.query(Article).filter(Article.code.in_(selected_codes)).all()
        existing_by_code = {str(row.code): row for row in existing_rows}

    existing_articles = 0
    inserted_articles = 0
    skipped_invalid = 0
    items: list[WbLiveArticleBootstrapItem] = []

    for supplier_article in selected_codes:
        bucket = aggregates[supplier_article]
        row_count = int(bucket["rows"])

        if len(supplier_article) > 50:
            skipped_invalid += 1
            items.append(
                WbLiveArticleBootstrapItem(
                    supplier_article=supplier_article,
                    rows=row_count,
                    status="invalid_too_long",
                    article_id=None,
                )
            )
            continue

        existing = existing_by_code.get(supplier_article)
        if existing is not None:
            existing_articles += 1
            items.append(
                WbLiveArticleBootstrapItem(
                    supplier_article=supplier_article,
                    rows=row_count,
                    status="existing",
                    article_id=int(existing.id),
                )
            )
            continue

        if dry_run:
            items.append(
                WbLiveArticleBootstrapItem(
                    supplier_article=supplier_article,
                    rows=row_count,
                    status="would_insert",
                    article_id=None,
                )
            )
            continue

        new_article = Article(code=supplier_article, name=supplier_article)
        db.add(new_article)
        db.flush()
        existing_by_code[supplier_article] = new_article
        inserted_articles += 1

        items.append(
            WbLiveArticleBootstrapItem(
                supplier_article=supplier_article,
                rows=row_count,
                status="inserted",
                article_id=int(new_article.id),
            )
        )

    if not dry_run:
        db.commit()

    return WbLiveArticleBootstrapSummary(
        account_id=account.id,
        fetched_rows=len(rows),
        pages_requested=max_pages,
        pages_with_data=pages_with_data,
        date_from_effective=date_from_effective,
        next_cursor=next_cursor,
        candidate_supplier_articles=candidate_supplier_articles,
        existing_articles=existing_articles,
        inserted_articles=inserted_articles,
        skipped_invalid=skipped_invalid,
        dry_run=dry_run,
        items=items,
    )


def build_from_wb_readiness_next_steps(blocker: str | None) -> list[str]:
    if blocker in {"no_wb_mapping", "missing_wb_mapping_for_requested_bundle_types"}:
        return [
            "run_wb_article_mapping_discover_live",
            "run_wb_article_bootstrap_live_if_article_missing",
            "run_wb_article_mapping_sync_live",
        ]
    if blocker == "no_bundle_type_in_mapping":
        return [
            "set_bundle_type_id_on_article_wb_mapping",
        ]
    if blocker == "no_bundle_recipe":
        return [
            "create_bundle_recipe_for_mapped_bundle_types",
        ]
    if blocker == "missing_bundle_recipe_bundle_types":
        return [
            "add_bundle_recipe_for_missing_bundle_type_ids",
        ]
    if blocker == "no_sku_units_for_recipe_colors":
        return [
            "create_sku_units_for_recipe_colors",
        ]
    if blocker == "no_wb_sales_or_stock_data":
        return [
            "run_wb_sales_daily_sync_live",
            "run_wb_stock_sync_live",
        ]
    if blocker == "no_wb_sales_data":
        return [
            "run_wb_sales_daily_sync_live",
        ]
    if blocker == "no_wb_stock_data":
        return [
            "run_wb_stock_sync_live",
        ]
    if blocker == "stale_wb_sales_and_stock_data":
        return [
            "run_wb_sales_daily_sync_live",
            "run_wb_stock_sync_live",
        ]
    if blocker == "stale_wb_sales_data":
        return [
            "run_wb_sales_daily_sync_live",
        ]
    if blocker == "stale_wb_stock_data":
        return [
            "run_wb_stock_sync_live",
        ]
    return []


def _build_from_wb_readiness_freshness_state(
    db: Session,
    *,
    article_id: int,
    mapped_bundle_type_ids: list[int],
    request_sales_stale_after_days: int | None,
    request_stock_stale_after_days: int | None,
) -> dict[str, object]:
    article_settings = (
        db.query(ArticlePlanningSettings)
        .filter(ArticlePlanningSettings.article_id == article_id)
        .first()
    )

    admin_sales_stale_after_days = (
        int(article_settings.production_order_freshness_sales_stale_after_days)
        if article_settings is not None
        and article_settings.production_order_freshness_sales_stale_after_days is not None
        else None
    )
    admin_stock_stale_after_days = (
        int(article_settings.production_order_freshness_stock_stale_after_days)
        if article_settings is not None
        and article_settings.production_order_freshness_stock_stale_after_days is not None
        else None
    )

    sales_stale_after_days, stock_stale_after_days, threshold_source = resolve_from_wb_freshness_thresholds(
        request_sales_stale_after_days=request_sales_stale_after_days,
        request_stock_stale_after_days=request_stock_stale_after_days,
        admin_sales_stale_after_days=admin_sales_stale_after_days,
        admin_stock_stale_after_days=admin_stock_stale_after_days,
    )

    effective_as_of_date = (
        db.query(func.max(WbSalesDaily.date))
        .join(ArticleWbMapping, ArticleWbMapping.wb_sku == WbSalesDaily.wb_sku)
        .filter(ArticleWbMapping.article_id == article_id)
        .scalar()
    )
    stock_updated_rows = (
        db.query(
            ArticleWbMapping.bundle_type_id,
            func.max(WbStock.updated_at).label("last_updated_at"),
        )
        .join(WbStock, WbStock.wb_sku == ArticleWbMapping.wb_sku)
        .filter(
            ArticleWbMapping.article_id == article_id,
            ArticleWbMapping.bundle_type_id.in_(mapped_bundle_type_ids),
        )
        .group_by(ArticleWbMapping.bundle_type_id)
        .all()
    )

    wb_stock_updated_at_by_bundle = {
        int(bundle_type_id): (last_updated_at.isoformat() if last_updated_at is not None else None)
        for bundle_type_id, last_updated_at in stock_updated_rows
        if bundle_type_id is not None
    }
    for bundle_type_id in mapped_bundle_type_ids:
        wb_stock_updated_at_by_bundle.setdefault(int(bundle_type_id), None)

    freshness_status, sales_age_days, stock_oldest_age_days, _stock_age_days_by_bundle = build_from_wb_freshness_snapshot(
        effective_as_of_date=effective_as_of_date,
        wb_stock_updated_at_by_bundle=wb_stock_updated_at_by_bundle,
        sales_stale_after_days=sales_stale_after_days,
        stock_stale_after_days=stock_stale_after_days,
        now=datetime.now(timezone.utc),
    )
    blocker = build_from_wb_freshness_blocker(
        freshness_status=freshness_status,
        sales_age_days=sales_age_days,
        stock_oldest_age_days=stock_oldest_age_days,
        sales_stale_after_days=sales_stale_after_days,
        stock_stale_after_days=stock_stale_after_days,
    )

    return {
        "freshness_status": freshness_status,
        "sales_age_days": sales_age_days,
        "stock_oldest_age_days": stock_oldest_age_days,
        "threshold_days": {
            "sales": int(sales_stale_after_days),
            "stock": int(stock_stale_after_days),
        },
        "threshold_source": dict(threshold_source),
        "blocker": blocker,
        "next_steps": build_from_wb_freshness_next_steps(
            freshness_status=freshness_status,
            sales_age_days=sales_age_days,
            stock_oldest_age_days=stock_oldest_age_days,
            sales_stale_after_days=sales_stale_after_days,
            stock_stale_after_days=stock_stale_after_days,
        ),
    }


def _has_from_wb_readiness_sku_scope(
    db: Session,
    *,
    article_id: int,
    mapped_bundle_type_ids: list[int],
) -> bool:
    if not mapped_bundle_type_ids:
        return False

    recipe_color_rows = (
        db.query(BundleRecipe.color_id)
        .filter(
            BundleRecipe.article_id == article_id,
            BundleRecipe.bundle_type_id.in_(mapped_bundle_type_ids),
        )
        .distinct()
        .all()
    )
    recipe_color_ids = sorted(
        {
            int(row.color_id)
            for row in recipe_color_rows
            if row.color_id is not None
        }
    )
    if not recipe_color_ids:
        return False

    return (
        db.query(SkuUnit.id)
        .filter(
            SkuUnit.article_id == article_id,
            SkuUnit.color_id.in_(recipe_color_ids),
        )
        .first()
        is not None
    )


def _resolve_from_wb_readiness_structural_state(
    *,
    mapped_bundle_type_ids: list[int],
    recipe_bundle_type_ids: list[int],
    missing_recipe_bundle_type_ids: list[int],
    mapped_wb_skus_with_sales: int,
    mapped_wb_skus_with_stock: int,
) -> tuple[str | None, list[str]]:
    blocker: str | None = None
    if not mapped_bundle_type_ids:
        blocker = "no_bundle_type_in_mapping"
    elif not recipe_bundle_type_ids:
        blocker = "no_bundle_recipe"
    elif missing_recipe_bundle_type_ids:
        blocker = "missing_bundle_recipe_bundle_types"
    elif mapped_wb_skus_with_sales <= 0 and mapped_wb_skus_with_stock <= 0:
        blocker = "no_wb_sales_or_stock_data"
    elif mapped_wb_skus_with_sales <= 0:
        blocker = "no_wb_sales_data"
    elif mapped_wb_skus_with_stock <= 0:
        blocker = "no_wb_stock_data"

    return blocker, build_from_wb_readiness_next_steps(blocker)


def get_from_wb_readiness_summary(
    db: Session,
    *,
    article_id: int | None,
    limit: int,
    request_sales_stale_after_days: int | None,
    request_stock_stale_after_days: int | None,
) -> WbFromWbReadinessSummary:
    if article_id is not None:
        article = db.query(Article).filter(Article.id == article_id).first()
        if article is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=_build_article_not_found_detail(article_id=article_id),
            )

    mapping_query = (
        db.query(
            ArticleWbMapping.article_id,
            Article.code,
            ArticleWbMapping.wb_sku,
            ArticleWbMapping.bundle_type_id,
        )
        .join(Article, Article.id == ArticleWbMapping.article_id)
        .order_by(ArticleWbMapping.article_id, ArticleWbMapping.wb_sku)
    )
    if article_id is not None:
        mapping_query = mapping_query.filter(ArticleWbMapping.article_id == article_id)

    mapping_rows = mapping_query.all()
    if not mapping_rows and article_id is not None:
        article = db.query(Article).filter(Article.id == article_id).first()
        article_code = str(article.code) if article is not None else ""
        return WbFromWbReadinessSummary(
            total_articles_considered=1,
            ready_articles=0,
            not_ready_articles=1,
            items=[
                WbFromWbReadinessItem(
                    article_id=article_id,
                    article_code=article_code,
                    mapped_wb_skus=0,
                    mapped_wb_skus_with_sales=0,
                    mapped_wb_skus_with_stock=0,
                    mapped_bundle_type_ids=[],
                    recipe_bundle_type_ids=[],
                    missing_recipe_bundle_type_ids=[],
                    ready_for_from_wb=False,
                    blocker="no_wb_mapping",
                    next_steps=build_from_wb_readiness_next_steps("no_wb_mapping"),
                )
            ],
        )
    if not mapping_rows:
        return WbFromWbReadinessSummary(
            total_articles_considered=0,
            ready_articles=0,
            not_ready_articles=0,
            items=[],
        )

    aggregate: dict[int, dict[str, object]] = {}
    for row_article_id, row_article_code, wb_sku, bundle_type_id in mapping_rows:
        bucket = aggregate.setdefault(
            int(row_article_id),
            {
                "article_code": str(row_article_code),
                "wb_skus": set(),
                "bundle_type_ids": set(),
            },
        )

        wb_sku_text = str(wb_sku or "").strip()
        if wb_sku_text:
            wb_skus = bucket.get("wb_skus")
            if isinstance(wb_skus, set):
                wb_skus.add(wb_sku_text)

        if bundle_type_id is not None:
            bundle_type_ids = bucket.get("bundle_type_ids")
            if isinstance(bundle_type_ids, set):
                bundle_type_ids.add(int(bundle_type_id))

    selected_article_ids = sorted(aggregate.keys())[:limit]
    recipe_rows = (
        db.query(BundleRecipe.article_id, BundleRecipe.bundle_type_id)
        .filter(BundleRecipe.article_id.in_(selected_article_ids))
        .all()
    )
    recipe_bundle_types_by_article: dict[int, set[int]] = defaultdict(set)
    for recipe_article_id, recipe_bundle_type_id in recipe_rows:
        recipe_bundle_types_by_article[int(recipe_article_id)].add(int(recipe_bundle_type_id))

    sales_rows = (
        db.query(ArticleWbMapping.article_id, ArticleWbMapping.wb_sku)
        .join(WbSalesDaily, WbSalesDaily.wb_sku == ArticleWbMapping.wb_sku)
        .filter(ArticleWbMapping.article_id.in_(selected_article_ids))
        .distinct()
        .all()
    )
    sales_wb_skus_by_article: dict[int, set[str]] = defaultdict(set)
    for sales_article_id, sales_wb_sku in sales_rows:
        sales_wb_sku_text = str(sales_wb_sku or "").strip()
        if sales_wb_sku_text:
            sales_wb_skus_by_article[int(sales_article_id)].add(sales_wb_sku_text)

    stock_rows = (
        db.query(ArticleWbMapping.article_id, ArticleWbMapping.wb_sku)
        .join(WbStock, WbStock.wb_sku == ArticleWbMapping.wb_sku)
        .filter(ArticleWbMapping.article_id.in_(selected_article_ids))
        .distinct()
        .all()
    )
    stock_wb_skus_by_article: dict[int, set[str]] = defaultdict(set)
    for stock_article_id, stock_wb_sku in stock_rows:
        stock_wb_sku_text = str(stock_wb_sku or "").strip()
        if stock_wb_sku_text:
            stock_wb_skus_by_article[int(stock_article_id)].add(stock_wb_sku_text)

    items: list[WbFromWbReadinessItem] = []
    ready_articles = 0
    not_ready_articles = 0

    for current_article_id in selected_article_ids:
        bucket = aggregate[current_article_id]
        mapped_wb_skus = bucket.get("wb_skus")
        mapped_bundle_types_obj = bucket.get("bundle_type_ids")

        mapped_bundle_types = (
            sorted(int(item) for item in mapped_bundle_types_obj)
            if isinstance(mapped_bundle_types_obj, set)
            else []
        )
        recipe_bundle_types = sorted(recipe_bundle_types_by_article.get(current_article_id, set()))
        mapped_wb_skus_with_sales = len(sales_wb_skus_by_article.get(current_article_id, set()))
        mapped_wb_skus_with_stock = len(stock_wb_skus_by_article.get(current_article_id, set()))

        missing_recipe_bundle_type_ids = [
            bundle_type for bundle_type in mapped_bundle_types if bundle_type not in recipe_bundle_types
        ]

        blocker: str | None = None
        ready_for_from_wb = False
        freshness_status: str | None = None
        sales_age_days: int | None = None
        stock_oldest_age_days: int | None = None
        threshold_days: dict[str, int] = {}
        threshold_source: dict[str, str] = {}
        next_steps: list[str] = []
        blocker, next_steps = _resolve_from_wb_readiness_structural_state(
            mapped_bundle_type_ids=mapped_bundle_types,
            recipe_bundle_type_ids=recipe_bundle_types,
            missing_recipe_bundle_type_ids=missing_recipe_bundle_type_ids,
            mapped_wb_skus_with_sales=mapped_wb_skus_with_sales,
            mapped_wb_skus_with_stock=mapped_wb_skus_with_stock,
        )
        if blocker is None or blocker in {
            "no_wb_sales_or_stock_data",
            "no_wb_sales_data",
            "no_wb_stock_data",
        }:
            freshness_state = _build_from_wb_readiness_freshness_state(
                db,
                article_id=current_article_id,
                mapped_bundle_type_ids=mapped_bundle_types,
                request_sales_stale_after_days=request_sales_stale_after_days,
                request_stock_stale_after_days=request_stock_stale_after_days,
            )
            freshness_status_value = freshness_state.get("freshness_status")
            freshness_status = str(freshness_status_value) if freshness_status_value is not None else None
            sales_age_days = freshness_state.get("sales_age_days")
            stock_oldest_age_days = freshness_state.get("stock_oldest_age_days")
            threshold_days = dict(freshness_state.get("threshold_days") or {})
            threshold_source = dict(freshness_state.get("threshold_source") or {})
            freshness_blocker = (
                str(freshness_state["blocker"])
                if freshness_state.get("blocker") is not None
                else None
            )
            if freshness_blocker is not None:
                blocker = freshness_blocker
                next_steps = list(freshness_state.get("next_steps") or [])
            ready_for_from_wb = blocker is None
        if ready_for_from_wb and not _has_from_wb_readiness_sku_scope(
            db=db,
            article_id=current_article_id,
            mapped_bundle_type_ids=mapped_bundle_types,
        ):
            blocker = "no_sku_units_for_recipe_colors"
            next_steps = build_from_wb_readiness_next_steps(blocker)
            ready_for_from_wb = False

        if ready_for_from_wb:
            ready_articles += 1
        else:
            not_ready_articles += 1

        mapped_wb_skus_count = len(mapped_wb_skus) if isinstance(mapped_wb_skus, set) else 0
        items.append(
            WbFromWbReadinessItem(
                article_id=current_article_id,
                article_code=str(bucket.get("article_code") or ""),
                mapped_wb_skus=mapped_wb_skus_count,
                mapped_wb_skus_with_sales=mapped_wb_skus_with_sales,
                mapped_wb_skus_with_stock=mapped_wb_skus_with_stock,
                mapped_bundle_type_ids=mapped_bundle_types,
                recipe_bundle_type_ids=recipe_bundle_types,
                missing_recipe_bundle_type_ids=missing_recipe_bundle_type_ids,
                ready_for_from_wb=ready_for_from_wb,
                blocker=blocker,
                next_steps=next_steps,
                freshness_status=freshness_status,
                sales_age_days=sales_age_days,
                stock_oldest_age_days=stock_oldest_age_days,
                threshold_days=threshold_days,
                threshold_source=threshold_source,
            )
        )

    return WbFromWbReadinessSummary(
        total_articles_considered=len(selected_article_ids),
        ready_articles=ready_articles,
        not_ready_articles=not_ready_articles,
        items=items,
    )


def sync_commission_from_wb_api(
    db: Session,
    *,
    account_id: int | None,
    top_subjects_limit: int,
) -> WbLiveCommissionSyncSummary:
    account = _resolve_wb_integration_account(db=db, account_id=account_id)
    payload = _wb_get_json_object(
        base_url=WB_TARIFFS_API_BASE_URL,
        path=WB_TARIFFS_COMMISSION_PATH,
        token=account.api_token,
    )

    report_payload = payload.get("report")
    report_rows: list[dict[str, object]] = []
    if isinstance(report_payload, list):
        report_rows = _normalize_wb_json_rows(report_payload)

    subjects: list[WbLiveCommissionSubjectItem] = []
    commission_values: list[float] = []
    for row in report_rows:
        subject_name = str(row.get("subjectName") or "").strip()
        if not subject_name:
            continue

        subject_id = _coerce_optional_int(row.get("subjectID"))
        kgvp_supplier_percent = _coerce_optional_float(row.get("kgvpSupplier"))
        if kgvp_supplier_percent is not None:
            commission_values.append(kgvp_supplier_percent)

        subjects.append(
            WbLiveCommissionSubjectItem(
                subject_id=subject_id,
                subject_name=subject_name,
                kgvp_supplier_percent=round(kgvp_supplier_percent, 4)
                if kgvp_supplier_percent is not None
                else None,
            )
        )

    subjects_sorted = sorted(
        subjects,
        key=lambda item: (
            item.kgvp_supplier_percent is None,
            -(item.kgvp_supplier_percent or 0.0),
            item.subject_name,
        ),
    )
    subjects_limited = subjects_sorted[:top_subjects_limit]

    avg_commission = (
        round(sum(commission_values) / float(len(commission_values)), 4)
        if commission_values
        else None
    )
    min_commission = round(min(commission_values), 4) if commission_values else None
    max_commission = round(max(commission_values), 4) if commission_values else None

    return WbLiveCommissionSyncSummary(
        account_id=account.id,
        fetched_rows=len(report_rows),
        subjects_with_commission=len(commission_values),
        avg_kgvp_supplier_percent=avg_commission,
        min_kgvp_supplier_percent=min_commission,
        max_kgvp_supplier_percent=max_commission,
        subjects=subjects_limited,
    )


def sync_supplies_from_wb_api(
    db: Session,
    *,
    account_id: int | None,
    limit: int,
    is_closed: bool | None,
) -> WbLiveSupplySyncSummary:
    account = _resolve_wb_integration_account(db=db, account_id=account_id)
    request_payload: dict[str, object] = {"limit": limit}
    if is_closed is not None:
        request_payload["isClosed"] = is_closed

    rows = _wb_post_json_rows(
        base_url=WB_SUPPLIES_API_BASE_URL,
        path=WB_SUPPLIES_LIST_PATH,
        token=account.api_token,
        payload=request_payload,
    )

    status_counts: dict[str, int] = {}
    supplies: list[WbLiveSupplyStatusItem] = []
    for row in rows:
        supply_id = _coerce_optional_int(row.get("supplyID"))
        if supply_id is None:
            continue

        status_id = _coerce_optional_int(row.get("statusID"))
        status_key = str(status_id) if status_id is not None else "none"
        status_counts[status_key] = status_counts.get(status_key, 0) + 1

        create_date_raw = row.get("createDate")
        supply_date_raw = row.get("supplyDate")
        updated_date_raw = row.get("updatedDate")

        supplies.append(
            WbLiveSupplyStatusItem(
                supply_id=supply_id,
                status_id=status_id,
                create_date=str(create_date_raw) if create_date_raw is not None else None,
                supply_date=str(supply_date_raw) if supply_date_raw is not None else None,
                updated_date=str(updated_date_raw) if updated_date_raw is not None else None,
            )
        )

    return WbLiveSupplySyncSummary(
        account_id=account.id,
        fetched_rows=len(rows),
        status_counts=status_counts,
        supplies=supplies,
    )


def sync_stock_from_wb_api(
    db: Session,
    *,
    account_id: int | None,
    date_from: datetime | None,
    max_pages: int,
) -> WbLiveSyncSummary:
    account = _resolve_wb_integration_account(db=db, account_id=account_id)
    start_at = date_from or datetime.combine(
        WB_SYNC_DEFAULT_STOCK_DATE_FROM,
        datetime.min.time(),
        tzinfo=timezone.utc,
    )
    date_from_effective = _as_rfc3339(start_at)

    rows, pages_with_data, next_cursor = _fetch_wb_rows_paginated(
        path=WB_REPORTS_STOCK_PATH,
        token=account.api_token,
        initial_date_from=date_from_effective,
        max_pages=max_pages,
        include_flag_zero=False,
    )
    items = _extract_stock_items_from_wb_rows(rows)
    import_summary = load_stock(db=db, items=items)

    return WbLiveSyncSummary(
        account_id=account.id,
        fetched_rows=len(rows),
        inserted=import_summary.inserted,
        updated=import_summary.updated,
        pages_requested=max_pages,
        pages_with_data=pages_with_data,
        date_from_effective=date_from_effective,
        next_cursor=next_cursor,
    )


def load_sales_daily(db: Session, items: list[WbSalesDailyItem]) -> WbImportSummary:
    """Upsert WB daily sales into wb_sales_daily.

    - If (wb_sku, date) exists: update sales_qty and revenue.
    - Else: insert new row.
    All changes are committed in a single transaction.
    """
    if not items:
        return WbImportSummary(inserted=0, updated=0)

    keys = {(i.wb_sku, i.date) for i in items}
    if not keys:
        return WbImportSummary(inserted=0, updated=0)

    all_skus = {k[0] for k in keys}
    all_dates = {k[1] for k in keys}

    existing_rows: list[WbSalesDaily] = (
        db.query(WbSalesDaily)
        .filter(WbSalesDaily.wb_sku.in_(all_skus), WbSalesDaily.date.in_(all_dates))
        .all()
    )
    existing_map: dict[tuple[str, datetime.date], WbSalesDaily] = {
        (row.wb_sku, row.date): row for row in existing_rows
    }

    inserted = 0
    updated = 0

    for item in items:
        key = (item.wb_sku, item.date)
        row = existing_map.get(key)
        if row is None:
            row = WbSalesDaily(
                wb_sku=item.wb_sku,
                date=item.date,
                sales_qty=item.sales_qty,
                revenue=item.revenue,
                created_at=_utcnow(),
            )
            db.add(row)
            existing_map[key] = row
            inserted += 1
        else:
            row.sales_qty = item.sales_qty
            row.revenue = item.revenue
            updated += 1

    db.commit()
    return WbImportSummary(inserted=inserted, updated=updated)


def load_stock(db: Session, items: list[WbStockItem]) -> WbImportSummary:
    """Upsert WB stock balances into wb_stock.

    For each (wb_sku, warehouse_id):
    - If exists: overwrite stock_qty, updated_at (v1: simple overwrite policy).
    - Else: insert new row.
    All changes are committed in a single transaction.
    """
    if not items:
        return WbImportSummary(inserted=0, updated=0)

    keys = {(i.wb_sku, i.warehouse_id) for i in items}
    if not keys:
        return WbImportSummary(inserted=0, updated=0)

    all_skus = {k[0] for k in keys}
    all_warehouses = {k[1] for k in keys}

    non_null_warehouses = {wid for wid in all_warehouses if wid is not None}

    query = db.query(WbStock).filter(WbStock.wb_sku.in_(all_skus))
    if non_null_warehouses:
        query = query.filter(
            or_(
                WbStock.warehouse_id.in_(non_null_warehouses),
                WbStock.warehouse_id.is_(None) if None in all_warehouses else False,
            )
        )
    elif None in all_warehouses:
        query = query.filter(WbStock.warehouse_id.is_(None))

    existing_rows: list[WbStock] = query.all()
    existing_map: dict[tuple[str, int | None], WbStock] = {
        (row.wb_sku, row.warehouse_id): row for row in existing_rows
    }

    inserted = 0
    updated = 0

    for item in items:
        key = (item.wb_sku, item.warehouse_id)
        row = existing_map.get(key)
        value_updated_at = item.updated_at or _utcnow()
        if row is None:
            row = WbStock(
                wb_sku=item.wb_sku,
                warehouse_id=item.warehouse_id,
                warehouse_name=item.warehouse_name,
                stock_qty=item.stock_qty,
                updated_at=value_updated_at,
            )
            db.add(row)
            existing_map[key] = row
            inserted += 1
        else:
            row.warehouse_name = item.warehouse_name
            row.stock_qty = item.stock_qty
            row.updated_at = value_updated_at
            updated += 1

    db.commit()
    return WbImportSummary(inserted=inserted, updated=updated)


def map_bundles_to_sku(
    db: Session,
    items: list[ArticleWbMappingItem],
) -> WbImportSummary:
    """Upsert article → WB SKU mappings into article_wb_mapping.

    - Validate that all article_id exist; on first missing article raise 400.
    - For (article_id, wb_sku): update or insert mapping.
    All changes are committed in a single transaction.
    """
    if not items:
        return WbImportSummary(inserted=0, updated=0)

    article_ids = {i.article_id for i in items}
    if not article_ids:
        return WbImportSummary(inserted=0, updated=0)

    existing_articles: list[Article] = (
        db.query(Article).filter(Article.id.in_(article_ids)).all()
    )
    valid_article_ids = {a.id for a in existing_articles}

    for item in items:
        if item.article_id not in valid_article_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=_build_wb_mapping_article_not_found_detail(
                    article_id=item.article_id,
                    wb_sku=item.wb_sku,
                ),
            )

    keys = {(i.article_id, i.wb_sku) for i in items}
    all_mapping_article_ids = {k[0] for k in keys}
    all_wb_skus = {k[1] for k in keys}

    existing_rows: list[ArticleWbMapping] = (
        db.query(ArticleWbMapping)
        .filter(
            ArticleWbMapping.article_id.in_(all_mapping_article_ids),
            ArticleWbMapping.wb_sku.in_(all_wb_skus),
        )
        .all()
    )
    existing_map: dict[tuple[int, str], ArticleWbMapping] = {
        (row.article_id, row.wb_sku): row for row in existing_rows
    }

    inserted = 0
    updated = 0

    for item in items:
        key = (item.article_id, item.wb_sku)
        row = existing_map.get(key)
        if row is None:
            row = ArticleWbMapping(
                article_id=item.article_id,
                wb_sku=item.wb_sku,
                bundle_type_id=item.bundle_type_id,
                color_id=item.color_id,
                size_id=item.size_id,
            )
            db.add(row)
            existing_map[key] = row
            inserted += 1
        else:
            row.bundle_type_id = item.bundle_type_id
            row.color_id = item.color_id
            row.size_id = item.size_id
            updated += 1

    db.commit()
    return WbImportSummary(inserted=inserted, updated=updated)


def sync_all() -> None:
    """Placeholder for running full WB data sync (sales, stock, mappings).

    Not used by HTTP API in TASK #12.
    """
    pass
