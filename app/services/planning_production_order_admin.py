from __future__ import annotations

from collections import defaultdict

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.models import (
    Article,
    ArticlePlanningSettings,
    BundleType,
    ElasticType,
    ProductionOrderElasticBinding,
    ProductionOrderInFlightDefault,
    ProductionOrderSizeWeightSetting,
    SkuUnit,
    Size,
)
from app.schemas.planning_production_order_admin import (
    ProductionOrderAdminSettingsResponse,
    ProductionOrderAdminSettingsUpsertRequest,
    ProductionOrderElasticBindingInput,
    ProductionOrderInFlightDefaultInput,
    ProductionOrderSizeWeightInput,
)


def _parse_assorti_bundle_type_ids(raw_value: str | None) -> list[int]:
    if raw_value is None:
        return []

    bundle_type_ids: set[int] = set()
    for token in raw_value.split(","):
        candidate = token.strip()
        if not candidate:
            continue
        try:
            bundle_type_id = int(candidate)
        except ValueError:
            continue
        if bundle_type_id <= 0:
            continue
        bundle_type_ids.add(bundle_type_id)

    return sorted(bundle_type_ids)


def _serialize_assorti_bundle_type_ids(bundle_type_ids: list[int]) -> str | None:
    normalized = sorted(
        {
            int(bundle_type_id)
            for bundle_type_id in bundle_type_ids
            if int(bundle_type_id) > 0
        }
    )
    if not normalized:
        return None
    return ",".join(str(bundle_type_id) for bundle_type_id in normalized)


def _build_article_not_found_detail(*, article_id: int) -> dict[str, object]:
    return {
        "code": "article_not_found",
        "message": "Article not found",
        "article_id": int(article_id),
        "next_steps": ["use_existing_article_id"],
    }


def _require_article(db: Session, article_id: int) -> Article:
    article = db.query(Article).filter(Article.id == article_id).first()
    if article is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_build_article_not_found_detail(article_id=article_id),
        )
    return article


def _get_article_sku_index(db: Session, article_id: int) -> tuple[set[int], set[int], dict[int, SkuUnit], dict[tuple[int, int], int]]:
    sku_rows = db.query(SkuUnit).filter(SkuUnit.article_id == article_id).all()

    color_ids = {sku.color_id for sku in sku_rows}
    size_ids = {sku.size_id for sku in sku_rows}
    sku_by_id = {sku.id: sku for sku in sku_rows}
    sku_by_color_size = {(sku.color_id, sku.size_id): sku.id for sku in sku_rows}

    return color_ids, size_ids, sku_by_id, sku_by_color_size


def _build_admin_settings_validation_detail(
    *,
    code: str,
    message: str,
    article_id: int,
    field: str,
    next_steps: list[str],
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    detail = {
        "code": code,
        "message": message,
        "article_id": int(article_id),
        "field": field,
        "next_steps": list(next_steps),
    }
    if extra:
        detail.update(extra)
    return detail


def _validate_size_weights(
    db: Session,
    article_id: int,
    payload: ProductionOrderAdminSettingsUpsertRequest,
) -> None:
    if not payload.size_weights:
        return

    size_ids = [item.size_id for item in payload.size_weights]
    existing_ids = {
        row.id
        for row in db.query(Size).filter(Size.id.in_(size_ids)).all()
    }

    missing = sorted(set(size_ids) - existing_ids)
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_build_admin_settings_validation_detail(
                code="unknown_size_ids",
                message="Unknown size_id(s)",
                article_id=article_id,
                field="size_weights.size_id",
                next_steps=["use_existing_size_ids"],
                extra={"invalid_size_ids": missing},
            ),
        )


def _validate_elastic_bindings(
    db: Session,
    article_id: int,
    payload: ProductionOrderAdminSettingsUpsertRequest,
    article_color_ids: set[int],
    sku_by_id: dict[int, SkuUnit],
) -> None:
    if not payload.elastic_bindings:
        return

    elastic_type_ids = [item.elastic_type_id for item in payload.elastic_bindings]
    existing_elastic_type_ids = {
        row.id
        for row in db.query(ElasticType).filter(ElasticType.id.in_(elastic_type_ids)).all()
    }

    missing_types = sorted(set(elastic_type_ids) - existing_elastic_type_ids)
    if missing_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_build_admin_settings_validation_detail(
                code="unknown_elastic_type_ids",
                message="Unknown elastic_type_id(s)",
                article_id=article_id,
                field="elastic_bindings.elastic_type_id",
                next_steps=["use_existing_elastic_type_ids"],
                extra={"invalid_elastic_type_ids": missing_types},
            ),
        )

    for item in payload.elastic_bindings:
        if item.color_id is not None and item.color_id not in article_color_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=_build_admin_settings_validation_detail(
                    code="elastic_binding_color_out_of_article_scope",
                    message="color_id does not belong to article SKU scope",
                    article_id=article_id,
                    field="elastic_bindings.color_id",
                    next_steps=["use_article_color_ids_only"],
                    extra={"invalid_color_id": int(item.color_id)},
                ),
            )

        if item.sku_unit_id is not None:
            sku = sku_by_id.get(item.sku_unit_id)
            if sku is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=_build_admin_settings_validation_detail(
                        code="elastic_binding_sku_out_of_article_scope",
                        message="sku_unit_id does not belong to article",
                        article_id=article_id,
                        field="elastic_bindings.sku_unit_id",
                        next_steps=["use_article_sku_unit_ids_only"],
                        extra={"invalid_sku_unit_id": int(item.sku_unit_id)},
                    ),
                )

            if item.color_id is not None and sku.color_id != item.color_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=_build_admin_settings_validation_detail(
                        code="elastic_binding_sku_color_mismatch",
                        message="sku_unit_id color mismatch with color_id",
                        article_id=article_id,
                        field="elastic_bindings.color_id",
                        next_steps=["align_elastic_binding_color_with_sku"],
                        extra={
                            "sku_unit_id": int(item.sku_unit_id),
                            "requested_color_id": int(item.color_id),
                            "sku_color_id": int(sku.color_id),
                        },
                    ),
                )


def _validate_assorti_bundle_type_ids(
    db: Session,
    article_id: int,
    payload: ProductionOrderAdminSettingsUpsertRequest,
) -> None:
    if not payload.assorti_bundle_type_ids:
        return

    existing_ids = {
        row.id
        for row in db.query(BundleType)
        .filter(BundleType.id.in_(payload.assorti_bundle_type_ids))
        .all()
    }
    missing_ids = sorted(set(payload.assorti_bundle_type_ids) - existing_ids)
    if missing_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_build_admin_settings_validation_detail(
                code="unknown_assorti_bundle_type_ids",
                message="Unknown assorti_bundle_type_id(s)",
                article_id=article_id,
                field="assorti_bundle_type_ids",
                next_steps=["use_existing_bundle_type_ids"],
                extra={"invalid_bundle_type_ids": missing_ids},
            ),
        )


def _validate_in_flight_defaults(
    article_id: int,
    payload: ProductionOrderAdminSettingsUpsertRequest,
    sku_by_color_size: dict[tuple[int, int], int],
) -> None:
    for item in payload.in_flight_supply_defaults:
        if (item.color_id, item.size_id) not in sku_by_color_size:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=_build_admin_settings_validation_detail(
                    code="in_flight_default_out_of_article_sku_scope",
                    message="In-flight default does not match any SKU for article",
                    article_id=article_id,
                    field="in_flight_supply_defaults",
                    next_steps=["use_article_color_size_pairs_only"],
                    extra={
                        "color_id": int(item.color_id),
                        "size_id": int(item.size_id),
                    },
                ),
            )


def get_production_order_admin_settings(
    db: Session,
    article_id: int,
) -> ProductionOrderAdminSettingsResponse:
    _require_article(db, article_id)

    size_rows = (
        db.query(ProductionOrderSizeWeightSetting)
        .filter(ProductionOrderSizeWeightSetting.article_id == article_id)
        .order_by(ProductionOrderSizeWeightSetting.size_id)
        .all()
    )
    elastic_rows = (
        db.query(ProductionOrderElasticBinding)
        .filter(ProductionOrderElasticBinding.article_id == article_id)
        .all()
    )
    in_flight_rows = (
        db.query(ProductionOrderInFlightDefault)
        .filter(ProductionOrderInFlightDefault.article_id == article_id)
        .all()
    )
    article_settings = (
        db.query(ArticlePlanningSettings)
        .filter(ArticlePlanningSettings.article_id == article_id)
        .first()
    )

    size_weights = [
        ProductionOrderSizeWeightInput(size_id=row.size_id, weight=float(row.weight))
        for row in size_rows
    ]

    elastic_rows.sort(
        key=lambda row: (
            row.elastic_type_id,
            row.color_id if row.color_id is not None else -1,
            row.sku_unit_id if row.sku_unit_id is not None else -1,
        )
    )
    elastic_bindings = [
        ProductionOrderElasticBindingInput(
            elastic_type_id=row.elastic_type_id,
            color_id=row.color_id,
            sku_unit_id=row.sku_unit_id,
            is_active=row.is_active,
        )
        for row in elastic_rows
    ]

    in_flight_rows.sort(
        key=lambda row: (
            row.color_id,
            row.size_id,
            row.eta_days,
            row.stage,
        )
    )
    in_flight_supply_defaults = [
        ProductionOrderInFlightDefaultInput(
            color_id=row.color_id,
            size_id=row.size_id,
            qty=row.qty,
            eta_days=row.eta_days,
            stage=row.stage,
            is_active=row.is_active,
        )
        for row in in_flight_rows
    ]

    return ProductionOrderAdminSettingsResponse(
        article_id=article_id,
        size_weights=size_weights,
        elastic_bindings=elastic_bindings,
        in_flight_supply_defaults=in_flight_supply_defaults,
        assorti_bundle_type_ids=(
            _parse_assorti_bundle_type_ids(article_settings.production_order_assorti_bundle_type_ids)
            if article_settings is not None
            else []
        ),
        freshness_sales_stale_after_days=(
            int(article_settings.production_order_freshness_sales_stale_after_days)
            if article_settings is not None
            and article_settings.production_order_freshness_sales_stale_after_days is not None
            else None
        ),
        freshness_stock_stale_after_days=(
            int(article_settings.production_order_freshness_stock_stale_after_days)
            if article_settings is not None
            and article_settings.production_order_freshness_stock_stale_after_days is not None
            else None
        ),
        layer3_stockout_boost_max=(
            float(article_settings.production_order_layer3_stockout_boost_max)
            if article_settings is not None
            and article_settings.production_order_layer3_stockout_boost_max is not None
            else None
        ),
        layer3_overstock_dampen_max=(
            float(article_settings.production_order_layer3_overstock_dampen_max)
            if article_settings is not None
            and article_settings.production_order_layer3_overstock_dampen_max is not None
            else None
        ),
        layer5_unavoidable_stockout_risk_threshold=(
            float(article_settings.production_order_layer5_unavoidable_stockout_risk_threshold)
            if article_settings is not None
            and article_settings.production_order_layer5_unavoidable_stockout_risk_threshold is not None
            else None
        ),
        layer5_accelerate_production_risk_threshold=(
            float(article_settings.production_order_layer5_accelerate_production_risk_threshold)
            if article_settings is not None
            and article_settings.production_order_layer5_accelerate_production_risk_threshold is not None
            else None
        ),
        production_cost_per_unit=(
            float(article_settings.production_order_production_cost_per_unit)
            if article_settings is not None
            and article_settings.production_order_production_cost_per_unit is not None
            else None
        ),
        logistics_cost_per_unit=(
            float(article_settings.production_order_logistics_cost_per_unit)
            if article_settings is not None
            and article_settings.production_order_logistics_cost_per_unit is not None
            else None
        ),
        wb_commission_percent_main=(
            float(article_settings.production_order_wb_commission_percent_main)
            if article_settings is not None
            and article_settings.production_order_wb_commission_percent_main is not None
            else None
        ),
        wb_commission_percent_assorti=(
            float(article_settings.production_order_wb_commission_percent_assorti)
            if article_settings is not None
            and article_settings.production_order_wb_commission_percent_assorti is not None
            else None
        ),
        average_realized_price_main=(
            float(article_settings.production_order_average_realized_price_main)
            if article_settings is not None
            and article_settings.production_order_average_realized_price_main is not None
            else None
        ),
        average_realized_price_assorti=(
            float(article_settings.production_order_average_realized_price_assorti)
            if article_settings is not None
            and article_settings.production_order_average_realized_price_assorti is not None
            else None
        ),
        available_capital=(
            float(article_settings.production_order_available_capital)
            if article_settings is not None
            and article_settings.production_order_available_capital is not None
            else None
        ),
    )


def upsert_production_order_admin_settings(
    db: Session,
    article_id: int,
    payload: ProductionOrderAdminSettingsUpsertRequest,
) -> ProductionOrderAdminSettingsResponse:
    _require_article(db, article_id)

    article_color_ids, _, sku_by_id, sku_by_color_size = _get_article_sku_index(
        db=db,
        article_id=article_id,
    )

    _validate_size_weights(db=db, article_id=article_id, payload=payload)
    _validate_elastic_bindings(
        db=db,
        article_id=article_id,
        payload=payload,
        article_color_ids=article_color_ids,
        sku_by_id=sku_by_id,
    )
    _validate_in_flight_defaults(
        article_id=article_id,
        payload=payload,
        sku_by_color_size=sku_by_color_size,
    )
    _validate_assorti_bundle_type_ids(db=db, article_id=article_id, payload=payload)

    db.query(ProductionOrderSizeWeightSetting).filter(
        ProductionOrderSizeWeightSetting.article_id == article_id
    ).delete(synchronize_session=False)

    db.query(ProductionOrderElasticBinding).filter(
        ProductionOrderElasticBinding.article_id == article_id
    ).delete(synchronize_session=False)

    db.query(ProductionOrderInFlightDefault).filter(
        ProductionOrderInFlightDefault.article_id == article_id
    ).delete(synchronize_session=False)

    for item in payload.size_weights:
        db.add(
            ProductionOrderSizeWeightSetting(
                article_id=article_id,
                size_id=item.size_id,
                weight=float(item.weight),
            )
        )

    for item in payload.elastic_bindings:
        db.add(
            ProductionOrderElasticBinding(
                article_id=article_id,
                elastic_type_id=item.elastic_type_id,
                color_id=item.color_id,
                sku_unit_id=item.sku_unit_id,
                is_active=item.is_active,
            )
        )

    in_flight_aggregate: dict[tuple[int, int, str, int, bool], int] = defaultdict(int)
    for item in payload.in_flight_supply_defaults:
        key = (item.color_id, item.size_id, item.stage, item.eta_days, item.is_active)
        in_flight_aggregate[key] += item.qty

    for (color_id, size_id, stage, eta_days, is_active), qty in in_flight_aggregate.items():
        db.add(
            ProductionOrderInFlightDefault(
                article_id=article_id,
                color_id=color_id,
                size_id=size_id,
                qty=qty,
                eta_days=eta_days,
                stage=stage,
                is_active=is_active,
            )
        )

    article_settings = (
        db.query(ArticlePlanningSettings)
        .filter(ArticlePlanningSettings.article_id == article_id)
        .first()
    )
    if article_settings is None:
        article_settings = ArticlePlanningSettings(
            article_id=article_id,
            include_in_planning=True,
            priority=0,
        )
        db.add(article_settings)

    article_settings.production_order_freshness_sales_stale_after_days = (
        payload.freshness_sales_stale_after_days
    )
    article_settings.production_order_freshness_stock_stale_after_days = (
        payload.freshness_stock_stale_after_days
    )
    article_settings.production_order_assorti_bundle_type_ids = _serialize_assorti_bundle_type_ids(
        payload.assorti_bundle_type_ids
    )
    article_settings.production_order_layer3_stockout_boost_max = (
        payload.layer3_stockout_boost_max
    )
    article_settings.production_order_layer3_overstock_dampen_max = (
        payload.layer3_overstock_dampen_max
    )
    article_settings.production_order_layer5_unavoidable_stockout_risk_threshold = (
        payload.layer5_unavoidable_stockout_risk_threshold
    )
    article_settings.production_order_layer5_accelerate_production_risk_threshold = (
        payload.layer5_accelerate_production_risk_threshold
    )
    article_settings.production_order_production_cost_per_unit = (
        payload.production_cost_per_unit
    )
    article_settings.production_order_logistics_cost_per_unit = (
        payload.logistics_cost_per_unit
    )
    article_settings.production_order_wb_commission_percent_main = (
        payload.wb_commission_percent_main
    )
    article_settings.production_order_wb_commission_percent_assorti = (
        payload.wb_commission_percent_assorti
    )
    article_settings.production_order_average_realized_price_main = (
        payload.average_realized_price_main
    )
    article_settings.production_order_average_realized_price_assorti = (
        payload.average_realized_price_assorti
    )
    article_settings.production_order_available_capital = (
        payload.available_capital
    )

    db.commit()

    return get_production_order_admin_settings(db=db, article_id=article_id)
