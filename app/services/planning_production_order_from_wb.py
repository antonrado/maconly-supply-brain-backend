from __future__ import annotations

from collections.abc import Callable
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import httpx
from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.models import (
    ArticleWbMapping,
    BundleRecipe,
    BundleType,
    WbIntegrationAccount,
    WbSalesDaily,
    WbStock,
)
from app.schemas.planning_production_order import (
    BundleDemandInput,
    BundleStockInput,
    ProductionOrderProposalFromWbRequest,
    ProductionOrderProposalRequest,
    ProductionOrderProposalResponse,
)
from app.services.planning_production_order_article import _require_article
from app.services.planning_production_order_economics import (
    FROM_WB_OBSERVED_ECONOMIC_SOURCE,
    _normalize_non_negative_float,
)
from app.services.planning_production_order_freshness import (
    _raise_from_wb_strict_freshness_failure_if_needed,
    _resolve_from_wb_freshness_thresholds,
    build_from_wb_freshness_snapshot,
)
from app.services.planning_production_order_operator_contracts import (
    _build_from_wb_missing_requested_bundle_type_detail,
    _build_from_wb_no_mapping_detail,
)
from app.services.wb_ingest import build_from_wb_readiness_next_steps

FROM_WB_TARIFFS_COMMISSION_SOURCE = "from_wb_tariffs_commission"
FROM_WB_PRICE_ANOMALY_MAX_DEVIATION = 0.30
FROM_WB_TARIFFS_API_BASE_URL = "https://common-api.wildberries.ru"
FROM_WB_TARIFFS_COMMISSION_PATH = "/api/v1/tariffs/commission"
FROM_WB_TARIFFS_HTTP_TIMEOUT_SECONDS = 20.0


def _translate_from_wb_internal_bundle_type_detail(
    detail: object,
    *,
    recipe_bundle_type_ids: list[int],
) -> object:
    if not isinstance(detail, dict):
        return detail

    translated = dict(detail)
    translated_any = False

    if detail.get("field") == "bundle_daily_sales.bundle_type_id":
        translated["field"] = "bundle_type_ids"
        translated["field_metadata"] = {
            "description": "List of bundle type IDs",
            "type": "list[int]",
        }
        translated_any = True

    blocker = str(detail["blocker"]) if detail.get("blocker") is not None else None
    if blocker == "no_bundle_recipe" and recipe_bundle_type_ids:
        blocker = "missing_bundle_recipe_bundle_types"
        translated["code"] = blocker
        translated["message"] = "Bundle recipe is missing for some requested bundle types"
        translated["blocker"] = blocker
        translated_any = True

    if blocker in {
        "no_bundle_recipe",
        "missing_bundle_recipe_bundle_types",
        "no_sku_units_for_recipe_colors",
    }:
        translated["readiness_endpoint"] = "/api/v1/wb/from-wb/readiness"
        translated["next_steps"] = build_from_wb_readiness_next_steps(blocker)
        translated_any = True

    return translated if translated_any else detail


@dataclass(frozen=True)
class _FromWbPreflightContext:
    bundle_type_ids: list[int]
    recipe_bundle_type_ids: list[int]
    daily_sales_by_bundle: dict[int, float]
    effective_as_of_date: date | None
    observed_price_calibration: dict[str, object]
    observed_commission_calibration: dict[str, object]
    wb_stock_by_bundle: dict[int, int]
    wb_stock_updated_at_by_bundle: dict[int, object]
    sales_stale_after_days: int
    stock_stale_after_days: int
    freshness_threshold_source: dict[str, object]
    freshness_status: str
    freshness_sales_age_days: int | None
    freshness_stock_oldest_age_days: int | None
    freshness_stock_age_days_by_bundle: dict[int, int | None]
    proposal_request: ProductionOrderProposalRequest
    runtime_overrides_payload: dict[str, float | None]
    runtime_source_overrides_payload: dict[str, str]


def _build_from_wb_proposal_request(
    *,
    request: ProductionOrderProposalFromWbRequest,
    bundle_type_ids: list[int],
    daily_sales_by_bundle: dict[int, float],
    wb_stock_by_bundle: dict[int, int],
) -> ProductionOrderProposalRequest:
    return ProductionOrderProposalRequest(
        article_id=request.article_id,
        planning_horizon_days=request.planning_horizon_days,
        explainability_mode="full",
        bundle_daily_sales=[
            BundleDemandInput(
                bundle_type_id=bundle_type_id,
                daily_sales=float(daily_sales_by_bundle.get(bundle_type_id, 0.0)),
            )
            for bundle_type_id in bundle_type_ids
        ],
        bundle_stock=[
            BundleStockInput(
                bundle_type_id=bundle_type_id,
                wb_qty=int(wb_stock_by_bundle.get(bundle_type_id, 0)),
                local_qty=0,
            )
            for bundle_type_id in bundle_type_ids
        ],
        in_flight_supply=request.in_flight_supply,
        size_weights=request.size_weights,
        overrides=request.overrides,
    )


def _build_from_wb_preflight_context(
    *,
    db: Session,
    request: ProductionOrderProposalFromWbRequest,
    build_from_wb_freshness_failure_detail: Callable[..., dict[str, object]],
) -> _FromWbPreflightContext:
    bundle_type_ids = _resolve_bundle_type_ids_for_from_wb(
        db=db,
        article_id=request.article_id,
        requested_bundle_type_ids=request.bundle_type_ids,
    )
    if not bundle_type_ids:
        blocker = "no_wb_mapping"
        if not request.bundle_type_ids and _has_wb_mapping_rows_for_article(
            db=db,
            article_id=request.article_id,
        ):
            blocker = "no_bundle_type_in_mapping"
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_build_from_wb_no_mapping_detail(
                article_id=request.article_id,
                requested_bundle_type_ids=request.bundle_type_ids,
                blocker=blocker,
            ),
        )

    recipe_bundle_type_ids = _get_recipe_bundle_type_ids(
        db=db,
        article_id=request.article_id,
    )

    daily_sales_by_bundle, effective_as_of_date = _load_wb_bundle_daily_sales(
        db=db,
        article_id=request.article_id,
        bundle_type_ids=bundle_type_ids,
        observation_window_days=request.observation_window_days,
        as_of_date=request.as_of_date,
    )
    observed_price_calibration = _load_from_wb_observed_price_calibration(
        db=db,
        article_id=request.article_id,
        bundle_type_ids=bundle_type_ids,
        observation_window_days=request.observation_window_days,
        effective_as_of_date=effective_as_of_date,
    )
    observed_commission_calibration = _load_from_wb_observed_commission_calibration(db=db)
    wb_stock_by_bundle = _load_wb_bundle_stock(
        db=db,
        article_id=request.article_id,
        bundle_type_ids=bundle_type_ids,
    )
    wb_stock_updated_at_by_bundle = _load_wb_bundle_stock_updated_at_by_bundle(
        db=db,
        article_id=request.article_id,
        bundle_type_ids=bundle_type_ids,
    )
    (
        sales_stale_after_days,
        stock_stale_after_days,
        freshness_threshold_source,
    ) = _resolve_from_wb_freshness_thresholds(
        db=db,
        article_id=request.article_id,
        request_sales_stale_after_days=request.freshness_sales_stale_after_days,
        request_stock_stale_after_days=request.freshness_stock_stale_after_days,
    )
    (
        freshness_status,
        freshness_sales_age_days,
        freshness_stock_oldest_age_days,
        freshness_stock_age_days_by_bundle,
    ) = build_from_wb_freshness_snapshot(
        effective_as_of_date=effective_as_of_date,
        wb_stock_updated_at_by_bundle=wb_stock_updated_at_by_bundle,
        sales_stale_after_days=sales_stale_after_days,
        stock_stale_after_days=stock_stale_after_days,
        now=datetime.now(timezone.utc),
    )

    _raise_from_wb_strict_freshness_failure_if_needed(
        article_id=request.article_id,
        freshness_mode=request.freshness_mode,
        freshness_status=freshness_status,
        sales_age_days=freshness_sales_age_days,
        stock_oldest_age_days=freshness_stock_oldest_age_days,
        sales_stale_after_days=sales_stale_after_days,
        stock_stale_after_days=stock_stale_after_days,
        threshold_source=freshness_threshold_source,
        build_from_wb_freshness_failure_detail=build_from_wb_freshness_failure_detail,
    )

    proposal_request = _build_from_wb_proposal_request(
        request=request,
        bundle_type_ids=bundle_type_ids,
        daily_sales_by_bundle=daily_sales_by_bundle,
        wb_stock_by_bundle=wb_stock_by_bundle,
    )
    runtime_overrides_payload, runtime_source_overrides_payload = (
        _build_from_wb_runtime_economic_overrides(
            observed_price_calibration=observed_price_calibration,
            observed_commission_calibration=observed_commission_calibration,
        )
    )

    return _FromWbPreflightContext(
        bundle_type_ids=bundle_type_ids,
        recipe_bundle_type_ids=recipe_bundle_type_ids,
        daily_sales_by_bundle=daily_sales_by_bundle,
        effective_as_of_date=effective_as_of_date,
        observed_price_calibration=observed_price_calibration,
        observed_commission_calibration=observed_commission_calibration,
        wb_stock_by_bundle=wb_stock_by_bundle,
        wb_stock_updated_at_by_bundle=wb_stock_updated_at_by_bundle,
        sales_stale_after_days=sales_stale_after_days,
        stock_stale_after_days=stock_stale_after_days,
        freshness_threshold_source=freshness_threshold_source,
        freshness_status=freshness_status,
        freshness_sales_age_days=freshness_sales_age_days,
        freshness_stock_oldest_age_days=freshness_stock_oldest_age_days,
        freshness_stock_age_days_by_bundle=freshness_stock_age_days_by_bundle,
        proposal_request=proposal_request,
        runtime_overrides_payload=runtime_overrides_payload,
        runtime_source_overrides_payload=runtime_source_overrides_payload,
    )


def _build_production_order_proposal_from_wb_response(
    *,
    db: Session,
    request: ProductionOrderProposalFromWbRequest,
    build_article_not_found_detail: Callable[..., dict[str, object]],
    build_from_wb_freshness_failure_detail: Callable[..., dict[str, object]],
    build_production_order_proposal: Callable[..., ProductionOrderProposalResponse],
    finalize_from_wb_explainability: Callable[..., object],
) -> ProductionOrderProposalResponse:
    _require_article(
        db=db,
        article_id=request.article_id,
        build_article_not_found_detail=build_article_not_found_detail,
    )

    preflight_context = _build_from_wb_preflight_context(
        db=db,
        request=request,
        build_from_wb_freshness_failure_detail=build_from_wb_freshness_failure_detail,
    )
    try:
        response = build_production_order_proposal(
            db=db,
            request=preflight_context.proposal_request,
            runtime_economic_overrides=preflight_context.runtime_overrides_payload,
            runtime_economic_source=FROM_WB_OBSERVED_ECONOMIC_SOURCE,
            runtime_economic_source_overrides=preflight_context.runtime_source_overrides_payload,
            shared_color_pool_observation_window_days=request.observation_window_days,
            shared_color_pool_as_of_date=preflight_context.effective_as_of_date,
        )
    except HTTPException as exc:
        translated_detail = _translate_from_wb_internal_bundle_type_detail(
            exc.detail,
            recipe_bundle_type_ids=preflight_context.recipe_bundle_type_ids,
        )
        if translated_detail != exc.detail:
            raise HTTPException(
                status_code=exc.status_code,
                detail=translated_detail,
                headers=exc.headers,
            ) from exc
        raise
    response.explanation = finalize_from_wb_explainability(
        explanation=response.explanation,
        explainability_mode=request.explainability_mode,
        requested_as_of_date=request.as_of_date,
        effective_as_of_date=preflight_context.effective_as_of_date,
        observation_window_days=request.observation_window_days,
        freshness_mode=request.freshness_mode,
        bundle_type_ids=preflight_context.bundle_type_ids,
        daily_sales_by_bundle=preflight_context.daily_sales_by_bundle,
        wb_stock_by_bundle=preflight_context.wb_stock_by_bundle,
        wb_stock_updated_at_by_bundle=preflight_context.wb_stock_updated_at_by_bundle,
        observed_price_calibration=preflight_context.observed_price_calibration,
        observed_commission_calibration=preflight_context.observed_commission_calibration,
        freshness_status=preflight_context.freshness_status,
        freshness_sales_age_days=preflight_context.freshness_sales_age_days,
        freshness_stock_oldest_age_days=preflight_context.freshness_stock_oldest_age_days,
        freshness_stock_age_days_by_bundle=preflight_context.freshness_stock_age_days_by_bundle,
        sales_stale_after_days=preflight_context.sales_stale_after_days,
        stock_stale_after_days=preflight_context.stock_stale_after_days,
        freshness_threshold_source=preflight_context.freshness_threshold_source,
    )
    return response


def _load_wb_bundle_stock(
    db: Session,
    article_id: int,
    bundle_type_ids: list[int],
) -> dict[int, int]:
    if not bundle_type_ids:
        return {}

    mappings = (
        db.query(ArticleWbMapping)
        .filter(
            ArticleWbMapping.article_id == article_id,
            ArticleWbMapping.bundle_type_id.in_(bundle_type_ids),
        )
        .all()
    )
    if not mappings:
        return {}

    wb_skus = {mapping.wb_sku for mapping in mappings if mapping.wb_sku}
    if not wb_skus:
        return {}

    stock_rows = (
        db.query(
            WbStock.wb_sku,
            func.sum(WbStock.stock_qty).label("total_qty"),
        )
        .filter(WbStock.wb_sku.in_(wb_skus))
        .group_by(WbStock.wb_sku)
        .all()
    )
    qty_by_wb_sku = {
        str(row.wb_sku): max(int(row.total_qty or 0), 0)
        for row in stock_rows
    }

    stock_by_bundle_type: dict[int, int] = defaultdict(int)
    for mapping in mappings:
        if mapping.bundle_type_id is None:
            continue
        stock_by_bundle_type[mapping.bundle_type_id] += qty_by_wb_sku.get(mapping.wb_sku, 0)

    return dict(stock_by_bundle_type)


def _load_wb_bundle_stock_updated_at_by_bundle(
    db: Session,
    article_id: int,
    bundle_type_ids: list[int],
) -> dict[int, str | None]:
    if not bundle_type_ids:
        return {}

    mappings = (
        db.query(ArticleWbMapping)
        .filter(
            ArticleWbMapping.article_id == article_id,
            ArticleWbMapping.bundle_type_id.in_(bundle_type_ids),
        )
        .all()
    )
    if not mappings:
        return {bundle_type_id: None for bundle_type_id in bundle_type_ids}

    wb_skus = {mapping.wb_sku for mapping in mappings if mapping.wb_sku}
    if not wb_skus:
        return {bundle_type_id: None for bundle_type_id in bundle_type_ids}

    updated_rows = (
        db.query(
            WbStock.wb_sku,
            func.max(WbStock.updated_at).label("last_updated_at"),
        )
        .filter(WbStock.wb_sku.in_(wb_skus))
        .group_by(WbStock.wb_sku)
        .all()
    )
    updated_at_by_wb_sku = {
        str(row.wb_sku): row.last_updated_at
        for row in updated_rows
    }

    latest_updated_at_by_bundle: dict[int, datetime | None] = {
        bundle_type_id: None for bundle_type_id in bundle_type_ids
    }
    for mapping in mappings:
        if mapping.bundle_type_id is None:
            continue

        bundle_type_id = int(mapping.bundle_type_id)
        updated_at = updated_at_by_wb_sku.get(mapping.wb_sku)
        if updated_at is None:
            continue

        current_updated_at = latest_updated_at_by_bundle.get(bundle_type_id)
        if current_updated_at is None or updated_at > current_updated_at:
            latest_updated_at_by_bundle[bundle_type_id] = updated_at

    return {
        bundle_type_id: (updated_at.isoformat() if updated_at is not None else None)
        for bundle_type_id, updated_at in latest_updated_at_by_bundle.items()
    }


def _get_wb_mapped_bundle_type_ids(
    db: Session,
    article_id: int,
    bundle_type_ids_filter: list[int] | None = None,
) -> set[int]:
    query = (
        db.query(ArticleWbMapping.bundle_type_id)
        .filter(
            ArticleWbMapping.article_id == article_id,
            ArticleWbMapping.bundle_type_id.is_not(None),
        )
    )

    if bundle_type_ids_filter:
        query = query.filter(ArticleWbMapping.bundle_type_id.in_(bundle_type_ids_filter))

    rows = query.distinct().all()
    return {int(row.bundle_type_id) for row in rows}


def _has_wb_mapping_rows_for_article(
    *,
    db: Session,
    article_id: int,
) -> bool:
    return (
        db.query(ArticleWbMapping.article_id)
        .filter(ArticleWbMapping.article_id == article_id)
        .first()
        is not None
    )


def _get_recipe_bundle_type_ids(
    *,
    db: Session,
    article_id: int,
) -> list[int]:
    rows = (
        db.query(BundleRecipe.bundle_type_id)
        .filter(
            BundleRecipe.article_id == article_id,
            BundleRecipe.bundle_type_id.is_not(None),
        )
        .distinct()
        .all()
    )
    return sorted(int(row.bundle_type_id) for row in rows)


def _resolve_bundle_type_ids_for_from_wb(
    db: Session,
    article_id: int,
    requested_bundle_type_ids: list[int],
) -> list[int]:
    if requested_bundle_type_ids:
        requested = sorted(set(requested_bundle_type_ids))
        mapped = _get_wb_mapped_bundle_type_ids(
            db=db,
            article_id=article_id,
            bundle_type_ids_filter=requested,
        )
        missing = [bundle_type_id for bundle_type_id in requested if bundle_type_id not in mapped]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=_build_from_wb_missing_requested_bundle_type_detail(
                    article_id=article_id,
                    missing_bundle_type_ids=missing,
                    requested_bundle_type_ids=requested,
                ),
            )
        return requested

    mapped_all = _get_wb_mapped_bundle_type_ids(db=db, article_id=article_id)
    return sorted(mapped_all)


def _load_wb_bundle_daily_sales(
    db: Session,
    article_id: int,
    bundle_type_ids: list[int],
    observation_window_days: int,
    as_of_date: date | None,
) -> tuple[dict[int, float], date | None]:
    if not bundle_type_ids:
        return {}, as_of_date

    mappings = (
        db.query(ArticleWbMapping)
        .filter(
            ArticleWbMapping.article_id == article_id,
            ArticleWbMapping.bundle_type_id.in_(bundle_type_ids),
        )
        .all()
    )

    wb_skus = {mapping.wb_sku for mapping in mappings if mapping.wb_sku}
    effective_as_of_date = as_of_date
    max_sales_date = None

    if wb_skus:
        max_sales_date = (
            db.query(func.max(WbSalesDaily.date))
            .filter(WbSalesDaily.wb_sku.in_(wb_skus))
            .scalar()
        )

    if effective_as_of_date is None and max_sales_date is not None:
        effective_as_of_date = max_sales_date

    if (
        effective_as_of_date is not None
        and max_sales_date is not None
        and effective_as_of_date > max_sales_date
    ):
        effective_as_of_date = max_sales_date

    if effective_as_of_date is None:
        return {bundle_type_id: 0.0 for bundle_type_id in bundle_type_ids}, None

    start_cutoff = effective_as_of_date - timedelta(days=observation_window_days - 1)

    sales_rows = (
        db.query(
            ArticleWbMapping.bundle_type_id,
            func.coalesce(func.sum(WbSalesDaily.sales_qty), 0).label("total_sales_qty"),
        )
        .join(WbSalesDaily, WbSalesDaily.wb_sku == ArticleWbMapping.wb_sku)
        .filter(
            ArticleWbMapping.article_id == article_id,
            ArticleWbMapping.bundle_type_id.in_(bundle_type_ids),
            WbSalesDaily.date >= start_cutoff,
            WbSalesDaily.date <= effective_as_of_date,
        )
        .group_by(ArticleWbMapping.bundle_type_id)
        .all()
    )

    daily_sales_by_bundle: dict[int, float] = {
        bundle_type_id: 0.0 for bundle_type_id in bundle_type_ids
    }
    for row in sales_rows:
        bundle_type_id = int(row.bundle_type_id)
        total_sales_qty = int(row.total_sales_qty or 0)
        daily_sales_by_bundle[bundle_type_id] = (
            float(total_sales_qty) / float(observation_window_days)
            if observation_window_days > 0
            else 0.0
        )

    return daily_sales_by_bundle, effective_as_of_date


def _summarize_from_wb_price_samples(
    *,
    samples: list[dict[str, float | int]],
    anomaly_max_deviation: float,
) -> dict[str, int | float | bool | None]:
    raw_samples = len(samples)
    if raw_samples <= 0:
        return {
            "price": None,
            "raw_samples": 0,
            "accepted_samples": 0,
            "anomaly_filtered": 0,
            "raw_units": 0,
            "accepted_units": 0,
            "fallback_used": False,
        }

    raw_units = 0
    raw_revenue = 0.0
    accepted_units = 0
    accepted_revenue = 0.0
    accepted_samples = 0
    anomaly_filtered = 0

    for sample in samples:
        qty = max(int(sample.get("qty", 0)), 0)
        revenue = max(float(sample.get("revenue", 0.0)), 0.0)
        if qty <= 0 or revenue <= 0:
            continue

        raw_units += qty
        raw_revenue += revenue
        unit_price = revenue / float(qty)

        if accepted_units > 0:
            baseline_price = accepted_revenue / float(max(accepted_units, 1))
            if baseline_price > 0:
                deviation = abs(unit_price - baseline_price) / baseline_price
                if deviation > anomaly_max_deviation:
                    anomaly_filtered += 1
                    continue

        accepted_units += qty
        accepted_revenue += revenue
        accepted_samples += 1

    fallback_used = False
    observed_price: float | None = None
    if accepted_units > 0:
        observed_price = round(accepted_revenue / float(accepted_units), 4)
    elif raw_units > 0:
        observed_price = round(raw_revenue / float(raw_units), 4)
        fallback_used = True

    return {
        "price": observed_price,
        "raw_samples": raw_samples,
        "accepted_samples": accepted_samples,
        "anomaly_filtered": anomaly_filtered,
        "raw_units": raw_units,
        "accepted_units": accepted_units,
        "fallback_used": fallback_used,
    }


def _load_from_wb_observed_price_calibration(
    *,
    db: Session,
    article_id: int,
    bundle_type_ids: list[int],
    observation_window_days: int,
    effective_as_of_date: date | None,
) -> dict[str, object]:
    empty_summary = _summarize_from_wb_price_samples(
        samples=[],
        anomaly_max_deviation=FROM_WB_PRICE_ANOMALY_MAX_DEVIATION,
    )
    if effective_as_of_date is None or not bundle_type_ids:
        return {
            "source": FROM_WB_OBSERVED_ECONOMIC_SOURCE,
            "window": {
                "start_date": None,
                "end_date": None,
            },
            "anomaly_max_deviation": FROM_WB_PRICE_ANOMALY_MAX_DEVIATION,
            "prices": {
                "main": None,
                "assorti": None,
            },
            "sample_counts": {
                "main": {k: v for k, v in empty_summary.items() if k != "price"},
                "assorti": {k: v for k, v in empty_summary.items() if k != "price"},
            },
        }

    start_cutoff = effective_as_of_date - timedelta(days=observation_window_days - 1)

    bundle_type_rows = (
        db.query(BundleType.id, BundleType.is_assorti)
        .filter(BundleType.id.in_(bundle_type_ids))
        .all()
    )
    assorti_by_bundle_type = {
        int(row.id): bool(row.is_assorti)
        for row in bundle_type_rows
    }

    price_rows = (
        db.query(
            ArticleWbMapping.bundle_type_id,
            WbSalesDaily.date.label("sales_date"),
            func.coalesce(func.sum(WbSalesDaily.sales_qty), 0).label("total_sales_qty"),
            func.coalesce(func.sum(WbSalesDaily.revenue), 0.0).label("total_revenue"),
        )
        .join(WbSalesDaily, WbSalesDaily.wb_sku == ArticleWbMapping.wb_sku)
        .filter(
            ArticleWbMapping.article_id == article_id,
            ArticleWbMapping.bundle_type_id.in_(bundle_type_ids),
            WbSalesDaily.date >= start_cutoff,
            WbSalesDaily.date <= effective_as_of_date,
        )
        .group_by(ArticleWbMapping.bundle_type_id, WbSalesDaily.date)
        .order_by(WbSalesDaily.date.asc(), ArticleWbMapping.bundle_type_id.asc())
        .all()
    )

    samples_by_segment: dict[str, list[dict[str, float | int]]] = {
        "main": [],
        "assorti": [],
    }
    for row in price_rows:
        bundle_type_id = int(row.bundle_type_id)
        segment = "assorti" if assorti_by_bundle_type.get(bundle_type_id, False) else "main"
        qty = max(int(row.total_sales_qty or 0), 0)
        revenue = max(float(row.total_revenue or 0.0), 0.0)
        if qty <= 0 or revenue <= 0:
            continue

        samples_by_segment[segment].append(
            {
                "qty": qty,
                "revenue": revenue,
            }
        )

    main_summary = _summarize_from_wb_price_samples(
        samples=samples_by_segment["main"],
        anomaly_max_deviation=FROM_WB_PRICE_ANOMALY_MAX_DEVIATION,
    )
    assorti_summary = _summarize_from_wb_price_samples(
        samples=samples_by_segment["assorti"],
        anomaly_max_deviation=FROM_WB_PRICE_ANOMALY_MAX_DEVIATION,
    )

    return {
        "source": FROM_WB_OBSERVED_ECONOMIC_SOURCE,
        "window": {
            "start_date": start_cutoff.isoformat(),
            "end_date": effective_as_of_date.isoformat(),
        },
        "anomaly_max_deviation": FROM_WB_PRICE_ANOMALY_MAX_DEVIATION,
        "prices": {
            "main": main_summary["price"],
            "assorti": assorti_summary["price"],
        },
        "sample_counts": {
            "main": {k: v for k, v in main_summary.items() if k != "price"},
            "assorti": {k: v for k, v in assorti_summary.items() if k != "price"},
        },
    }


def _normalize_from_wb_commission_ratio(value: object) -> float | None:
    normalized = _normalize_non_negative_float(value)
    if normalized is None:
        return None
    if normalized > 1.0:
        normalized = normalized / 100.0
    return max(min(normalized, 1.0), 0.0)


def _build_from_wb_runtime_economic_overrides(
    *,
    observed_price_calibration: dict[str, object],
    observed_commission_calibration: dict[str, object],
) -> tuple[dict[str, float | None] | None, dict[str, str] | None]:
    observed_price_values = observed_price_calibration.get("prices")
    observed_price_source_raw = observed_price_calibration.get("source")
    observed_price_source = (
        observed_price_source_raw
        if isinstance(observed_price_source_raw, str) and observed_price_source_raw.strip()
        else FROM_WB_OBSERVED_ECONOMIC_SOURCE
    )

    observed_commission_values = observed_commission_calibration.get("commission_percent")
    observed_commission_source_raw = observed_commission_calibration.get("source")
    observed_commission_source = (
        observed_commission_source_raw
        if isinstance(observed_commission_source_raw, str) and observed_commission_source_raw.strip()
        else FROM_WB_TARIFFS_COMMISSION_SOURCE
    )

    runtime_economic_overrides: dict[str, float | None] = {}
    runtime_economic_source_overrides: dict[str, str] = {}

    if isinstance(observed_price_values, dict):
        price_main = _normalize_non_negative_float(observed_price_values.get("main"))
        if price_main is not None:
            runtime_economic_overrides["average_realized_price_main"] = price_main
            runtime_economic_source_overrides["average_realized_price_main"] = observed_price_source

        price_assorti = _normalize_non_negative_float(observed_price_values.get("assorti"))
        if price_assorti is not None:
            runtime_economic_overrides["average_realized_price_assorti"] = price_assorti
            runtime_economic_source_overrides["average_realized_price_assorti"] = observed_price_source

    if isinstance(observed_commission_values, dict):
        commission_main = _normalize_from_wb_commission_ratio(observed_commission_values.get("main"))
        if commission_main is not None:
            runtime_economic_overrides["wb_commission_percent_main"] = commission_main
            runtime_economic_source_overrides["wb_commission_percent_main"] = observed_commission_source

        commission_assorti = _normalize_from_wb_commission_ratio(
            observed_commission_values.get("assorti")
        )
        if commission_assorti is not None:
            runtime_economic_overrides["wb_commission_percent_assorti"] = commission_assorti
            runtime_economic_source_overrides["wb_commission_percent_assorti"] = observed_commission_source

    return runtime_economic_overrides or None, runtime_economic_source_overrides or None


def _load_from_wb_observed_commission_calibration(
    *,
    db: Session,
) -> dict[str, object]:
    calibration = {
        "source": FROM_WB_TARIFFS_COMMISSION_SOURCE,
        "status": "unavailable",
        "reason": "no_active_account",
        "account_id": None,
        "fetched_rows": 0,
        "subjects_with_commission": 0,
        "commission_percent": {
            "main": None,
            "assorti": None,
        },
        "commission_percent_stats": {
            "avg": None,
            "min": None,
            "max": None,
        },
        "kgvp_supplier_percent_stats": {
            "avg": None,
            "min": None,
            "max": None,
        },
    }

    account = (
        db.query(WbIntegrationAccount)
        .filter(WbIntegrationAccount.is_active.is_(True))
        .order_by(WbIntegrationAccount.id)
        .first()
    )
    if account is None:
        return calibration

    calibration["account_id"] = int(account.id)
    token = (account.api_token or "").strip()
    if not token:
        calibration["reason"] = "empty_api_token"
        return calibration

    try:
        response = httpx.get(
            f"{FROM_WB_TARIFFS_API_BASE_URL}{FROM_WB_TARIFFS_COMMISSION_PATH}",
            headers={"Authorization": token},
            timeout=FROM_WB_TARIFFS_HTTP_TIMEOUT_SECONDS,
        )
    except httpx.RequestError as exc:
        calibration["reason"] = f"request_error:{exc.__class__.__name__}"
        return calibration

    if response.status_code == status.HTTP_401_UNAUTHORIZED:
        calibration["reason"] = "unauthorized"
        return calibration
    if response.status_code >= status.HTTP_400_BAD_REQUEST:
        calibration["reason"] = f"wb_api_http_{response.status_code}"
        return calibration

    try:
        payload = response.json()
    except ValueError:
        calibration["reason"] = "invalid_json"
        return calibration

    if not isinstance(payload, dict):
        calibration["reason"] = "invalid_payload"
        return calibration

    report_payload = payload.get("report")
    if not isinstance(report_payload, list):
        calibration["reason"] = "missing_report"
        return calibration

    report_rows: list[dict[str, object]] = []
    for row in report_payload:
        if isinstance(row, dict):
            report_rows.append(row)
    calibration["fetched_rows"] = len(report_rows)

    commission_values: list[float] = []
    for row in report_rows:
        commission_ratio = _normalize_from_wb_commission_ratio(row.get("kgvpSupplier"))
        if commission_ratio is None:
            continue
        commission_values.append(commission_ratio)

    calibration["subjects_with_commission"] = len(commission_values)
    if not commission_values:
        calibration["status"] = "empty_report"
        calibration["reason"] = "no_numeric_commission_values"
        return calibration

    avg_ratio = round(sum(commission_values) / float(len(commission_values)), 4)
    min_ratio = round(min(commission_values), 4)
    max_ratio = round(max(commission_values), 4)

    calibration["status"] = "ok"
    calibration["reason"] = None
    calibration["commission_percent"] = {
        "main": avg_ratio,
        "assorti": avg_ratio,
    }
    calibration["commission_percent_stats"] = {
        "avg": avg_ratio,
        "min": min_ratio,
        "max": max_ratio,
    }
    calibration["kgvp_supplier_percent_stats"] = {
        "avg": round(avg_ratio * 100.0, 4),
        "min": round(min_ratio * 100.0, 4),
        "max": round(max_ratio * 100.0, 4),
    }
    return calibration
