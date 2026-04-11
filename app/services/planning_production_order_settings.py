from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.models import (
    ArticlePlanningSettings,
    GlobalPlanningSettings,
    PlanningSettings,
    ProductionOrderInFlightDefault,
    ProductionOrderSizeWeightSetting,
)
from app.schemas.planning_production_order import PlanningOverridesInput


@dataclass
class _EffectiveSettings:
    include_in_planning: bool
    priority: int
    target_coverage_days: int
    service_level_percent: int
    alert_threshold_days: int
    lead_time_days_total: int
    safety_stock_days: int
    fabric_min_batch_default: int
    elastic_min_batch_default: int
    allow_order_with_buffer: bool


def _build_effective_settings(
    article_settings: ArticlePlanningSettings | None,
    planning_settings: PlanningSettings | None,
    global_settings: GlobalPlanningSettings | None,
    overrides: PlanningOverridesInput | None,
) -> _EffectiveSettings:
    target_coverage_days = 60
    service_level_percent = 90
    alert_threshold_days = 90
    safety_stock_days = 0
    fabric_min_batch_default = 7000
    elastic_min_batch_default = 3000

    if global_settings is not None:
        target_coverage_days = global_settings.default_target_coverage_days
        service_level_percent = global_settings.default_service_level_percent
        fabric_min_batch_default = global_settings.default_fabric_min_batch_qty
        elastic_min_batch_default = global_settings.default_elastic_min_batch_qty

    if article_settings is not None:
        if article_settings.target_coverage_days is not None:
            target_coverage_days = article_settings.target_coverage_days
        if article_settings.service_level_percent is not None:
            service_level_percent = article_settings.service_level_percent

    if planning_settings is not None:
        alert_threshold_days = planning_settings.alert_threshold_days
        safety_stock_days = planning_settings.safety_stock_days

    if overrides is not None:
        if overrides.target_coverage_days is not None:
            target_coverage_days = overrides.target_coverage_days
        if overrides.service_level_percent is not None:
            service_level_percent = overrides.service_level_percent
        if overrides.fabric_min_batch_qty_default is not None:
            fabric_min_batch_default = overrides.fabric_min_batch_qty_default
        if overrides.elastic_min_batch_qty_default is not None:
            elastic_min_batch_default = overrides.elastic_min_batch_qty_default

    lead_time_production = 30
    lead_time_china_to_nsk = 30
    lead_time_packaging = 3
    lead_time_nsk_to_wb = 7

    if overrides is not None and overrides.lead_time_days is not None:
        if overrides.lead_time_days.production is not None:
            lead_time_production = overrides.lead_time_days.production
        if overrides.lead_time_days.china_to_nsk is not None:
            lead_time_china_to_nsk = overrides.lead_time_days.china_to_nsk
        if overrides.lead_time_days.packaging is not None:
            lead_time_packaging = overrides.lead_time_days.packaging
        if overrides.lead_time_days.nsk_to_wb is not None:
            lead_time_nsk_to_wb = overrides.lead_time_days.nsk_to_wb

    lead_time_days_total = (
        lead_time_production
        + lead_time_china_to_nsk
        + lead_time_packaging
        + lead_time_nsk_to_wb
    )

    include_in_planning = True
    priority = 0
    if article_settings is not None:
        include_in_planning = article_settings.include_in_planning
        priority = article_settings.priority

    allow_order_with_buffer = True
    if overrides is not None:
        allow_order_with_buffer = overrides.allow_order_with_buffer

    return _EffectiveSettings(
        include_in_planning=include_in_planning,
        priority=priority,
        target_coverage_days=target_coverage_days,
        service_level_percent=service_level_percent,
        alert_threshold_days=alert_threshold_days,
        lead_time_days_total=lead_time_days_total,
        safety_stock_days=safety_stock_days,
        fabric_min_batch_default=fabric_min_batch_default,
        elastic_min_batch_default=elastic_min_batch_default,
        allow_order_with_buffer=allow_order_with_buffer,
    )


def _load_admin_size_weights(
    db: Session,
    article_id: int,
    size_ids: list[int],
) -> dict[int, float]:
    if not size_ids:
        return {}

    rows = (
        db.query(ProductionOrderSizeWeightSetting)
        .filter(
            ProductionOrderSizeWeightSetting.article_id == article_id,
            ProductionOrderSizeWeightSetting.size_id.in_(size_ids),
        )
        .all()
    )

    result: dict[int, float] = {}
    for row in rows:
        if row.weight > 0:
            result[row.size_id] = float(row.weight)

    return result


def _load_admin_in_flight_defaults(
    db: Session,
    article_id: int,
) -> list[ProductionOrderInFlightDefault]:
    return (
        db.query(ProductionOrderInFlightDefault)
        .filter(
            ProductionOrderInFlightDefault.article_id == article_id,
            ProductionOrderInFlightDefault.is_active.is_(True),
            ProductionOrderInFlightDefault.qty > 0,
        )
        .all()
    )
