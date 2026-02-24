from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from math import floor

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.models import (
    Article,
    ArticlePlanningSettings,
    ArticleWbMapping,
    BundleRecipe,
    Color,
    ColorPlanningSettings,
    ElasticPlanningSettings,
    GlobalPlanningSettings,
    PlanningSettings,
    ProductionOrderElasticBinding,
    ProductionOrderInFlightDefault,
    ProductionOrderSizeWeightSetting,
    SkuUnit,
    StockBalance,
    WbSalesDaily,
    WbStock,
)
from app.schemas.planning_production_order import (
    BundleDemandInput,
    BundleStockInput,
    ElasticConstraintApplied,
    FabricConstraintApplied,
    PlanningOverridesInput,
    ProductionOrderAlternative,
    ProductionOrderConstraintsApplied,
    ProductionOrderExplanationBlock,
    ProductionOrderProposalFromWbRequest,
    ProductionOrderProposalRequest,
    ProductionOrderProposalResponse,
    ProductionOrderRecommendation,
    ProductionOrderRecommendationLine,
)


@dataclass
class _EffectiveSettings:
    include_in_planning: bool
    priority: int
    target_coverage_days: int
    service_level_percent: int
    alert_threshold_days: int
    lead_time_days_total: int
    fabric_min_batch_default: int
    elastic_min_batch_default: int
    allow_order_with_buffer: bool


def _ceil_to_int(value: float) -> int:
    as_int = int(value)
    if value > as_int:
        return as_int + 1
    return as_int


def _normalize_weights(size_ids: list[int], raw_weights: dict[int, float]) -> dict[int, float]:
    if not size_ids:
        return {}

    weights: dict[int, float] = {}
    for size_id in size_ids:
        weight = raw_weights.get(size_id)
        if weight is not None and weight > 0:
            weights[size_id] = float(weight)

    if not weights:
        uniform = 1.0 / len(size_ids)
        return {size_id: uniform for size_id in size_ids}

    total = sum(weights.values())
    if total <= 0:
        uniform = 1.0 / len(size_ids)
        return {size_id: uniform for size_id in size_ids}

    normalized = {size_id: weight / total for size_id, weight in weights.items()}

    # Ensure all requested sizes exist in output map.
    for size_id in size_ids:
        normalized.setdefault(size_id, 0.0)

    norm_total = sum(normalized.values())
    if norm_total <= 0:
        uniform = 1.0 / len(size_ids)
        return {size_id: uniform for size_id in size_ids}

    return {size_id: normalized[size_id] / norm_total for size_id in size_ids}


def _allocate_units(total_units: int, weights: dict[int, float]) -> dict[int, int]:
    if total_units <= 0 or not weights:
        return {key: 0 for key in weights}

    keys = sorted(weights.keys())
    raw_values: dict[int, float] = {
        key: float(total_units) * max(weights.get(key, 0.0), 0.0) for key in keys
    }

    allocated: dict[int, int] = {key: int(raw_values[key]) for key in keys}
    assigned = sum(allocated.values())
    remainder = max(total_units - assigned, 0)

    if remainder > 0:
        remainders = sorted(
            keys,
            key=lambda key: (raw_values[key] - allocated[key], -key),
            reverse=True,
        )
        for index in range(remainder):
            allocated[remainders[index % len(remainders)]] += 1

    return allocated


def _choose_action(
    risk_level: str,
    candidate_units: int,
    allow_order_with_buffer: bool,
) -> str:
    if candidate_units <= 0:
        return "wait"

    if risk_level in {"critical", "warning"}:
        if allow_order_with_buffer:
            return "order_with_buffer"
        return "order_minimum_only"

    if risk_level in {"overstock", "ok", "no_data"}:
        return "wait"

    return "order_minimum_only"


def _build_alternatives(action: str) -> list[ProductionOrderAlternative]:
    alternatives = {
        "wait": ProductionOrderAlternative(
            action="wait",
            pros=["Минимальная заморозка средств"],
            cons=["Риск недозаказа при резком росте спроса"],
        ),
        "order_with_buffer": ProductionOrderAlternative(
            action="order_with_buffer",
            pros=["Снижает риск OOS до следующего цикла"],
            cons=["Увеличивает объем замороженного капитала"],
        ),
        "order_minimum_only": ProductionOrderAlternative(
            action="order_minimum_only",
            pros=["Соблюдает фабричные минималки без избыточного буфера"],
            cons=["Может не покрыть всплеск спроса"],
        ),
    }

    # Return at least two alternatives, excluding the recommended action from the first slot.
    ordered_actions = ["wait", "order_with_buffer", "order_minimum_only"]
    result: list[ProductionOrderAlternative] = []
    for alt_action in ordered_actions:
        if alt_action == action:
            continue
        result.append(alternatives[alt_action])

    if len(result) < 2:
        for alt_action in ordered_actions:
            if alt_action != action and all(item.action != alt_action for item in result):
                result.append(alternatives[alt_action])
            if len(result) >= 2:
                break

    return result


def _build_effective_settings(
    article_settings: ArticlePlanningSettings | None,
    planning_settings: PlanningSettings | None,
    global_settings: GlobalPlanningSettings | None,
    overrides: PlanningOverridesInput | None,
) -> _EffectiveSettings:
    target_coverage_days = 60
    service_level_percent = 90
    alert_threshold_days = 90
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

    if overrides is not None:
        if overrides.target_coverage_days is not None:
            target_coverage_days = overrides.target_coverage_days
        if overrides.service_level_percent is not None:
            service_level_percent = overrides.service_level_percent
        if overrides.alert_threshold_days is not None:
            alert_threshold_days = overrides.alert_threshold_days
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
        fabric_min_batch_default=fabric_min_batch_default,
        elastic_min_batch_default=elastic_min_batch_default,
        allow_order_with_buffer=allow_order_with_buffer,
    )


def _add_units_for_color(
    line_qty: dict[tuple[int, int], int],
    color_id: int,
    additional_qty: int,
    color_to_sizes: dict[int, list[int]],
    global_size_weights: dict[int, float],
) -> None:
    if additional_qty <= 0:
        return

    sizes = color_to_sizes.get(color_id, [])
    if not sizes:
        return

    local_weights = _normalize_weights(sizes, global_size_weights)
    allocated = _allocate_units(additional_qty, local_weights)

    for size_id, qty in allocated.items():
        if qty <= 0:
            continue
        key = (color_id, size_id)
        line_qty[key] = line_qty.get(key, 0) + qty


def _resolve_elastic_binding_scope(
    bindings: list[ProductionOrderElasticBinding],
    line_qty: dict[tuple[int, int], int],
    sku_by_color_size: dict[tuple[int, int], SkuUnit],
) -> tuple[set[int], set[tuple[int, int]]]:
    active_line_keys = {
        key
        for key, qty in line_qty.items()
        if qty > 0
    }
    if not active_line_keys:
        return set(), set()

    active_color_ids = {color_id for color_id, _size_id in active_line_keys}
    active_line_keys_by_sku_id = {
        sku.id: key
        for key, sku in sku_by_color_size.items()
        if key in active_line_keys
    }

    applicable: set[int] = set()
    scoped_line_keys: set[tuple[int, int]] = set()
    for binding in bindings:
        if not binding.is_active:
            continue

        if binding.sku_unit_id is not None:
            line_key = active_line_keys_by_sku_id.get(binding.sku_unit_id)
            if line_key is not None:
                applicable.add(binding.elastic_type_id)
                scoped_line_keys.add(line_key)
                continue

        if binding.color_id is not None and binding.color_id in active_color_ids:
            applicable.add(binding.elastic_type_id)
            for line_key in active_line_keys:
                if line_key[0] == binding.color_id:
                    scoped_line_keys.add(line_key)

    return applicable, scoped_line_keys


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
        return {}

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
                detail=f"Missing WB mapping for bundle_type_id(s): {missing}",
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


def build_production_order_proposal_from_wb(
    db: Session,
    request: ProductionOrderProposalFromWbRequest,
) -> ProductionOrderProposalResponse:
    bundle_type_ids = _resolve_bundle_type_ids_for_from_wb(
        db=db,
        article_id=request.article_id,
        requested_bundle_type_ids=request.bundle_type_ids,
    )
    if not bundle_type_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No WB-mapped bundle types found for the article",
        )

    daily_sales_by_bundle, effective_as_of_date = _load_wb_bundle_daily_sales(
        db=db,
        article_id=request.article_id,
        bundle_type_ids=bundle_type_ids,
        observation_window_days=request.observation_window_days,
        as_of_date=request.as_of_date,
    )
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

    proposal_request = ProductionOrderProposalRequest(
        article_id=request.article_id,
        planning_horizon_days=request.planning_horizon_days,
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

    response = build_production_order_proposal(db=db, request=proposal_request)
    requested_as_of_text = request.as_of_date.isoformat() if request.as_of_date is not None else "none"
    as_of_text = effective_as_of_date.isoformat() if effective_as_of_date is not None else "none"
    if effective_as_of_date is None:
        as_of_source = "none"
    elif request.as_of_date is None:
        as_of_source = "latest_sales"
    elif request.as_of_date != effective_as_of_date:
        as_of_source = "clamped_to_latest_sales"
    else:
        as_of_source = "request"

    if effective_as_of_date is not None:
        window_start = (effective_as_of_date - timedelta(days=request.observation_window_days - 1)).isoformat()
        window_text = f"{window_start}..{as_of_text}"
    else:
        window_text = "none"
    daily_sales_snapshot = {
        bundle_type_id: round(float(daily_sales_by_bundle.get(bundle_type_id, 0.0)), 4)
        for bundle_type_id in bundle_type_ids
    }
    wb_stock_snapshot = {
        bundle_type_id: int(wb_stock_by_bundle.get(bundle_type_id, 0))
        for bundle_type_id in bundle_type_ids
    }
    response.explanation.steps.insert(
        0,
        (
            "WB ingestion adapter: "
            f"observation_window_days={request.observation_window_days}, "
            f"requested_as_of_date={requested_as_of_text}, "
            f"as_of_date={as_of_text}, as_of_source={as_of_source}, "
            f"bundle_type_ids={bundle_type_ids}."
            f" sales_window={window_text},"
            f" daily_sales_by_bundle={daily_sales_snapshot}, "
            f"wb_stock_by_bundle={wb_stock_snapshot}, "
            f"wb_stock_updated_at_by_bundle={wb_stock_updated_at_by_bundle}."
        ),
    )
    return response


def _in_flight_stage_factor(stage: str | None) -> float:
    stage_key = (stage or "other").strip().lower()
    stage_factors: dict[str, float] = {
        "production": 0.85,
        "china_to_nsk": 0.90,
        "packaging": 0.97,
        "nsk_to_wb": 1.00,
        "other": 0.80,
    }
    return stage_factors.get(stage_key, stage_factors["other"])


def _estimate_effective_in_flight_qty(
    qty: int,
    eta_days: int,
    lead_time_days_total: int,
    stage: str | None,
) -> int:
    if qty <= 0:
        return 0

    eta = max(int(eta_days), 0)
    lead_time = max(int(lead_time_days_total), 0)

    if lead_time > 0 and eta > lead_time:
        return 0

    if lead_time <= 0:
        eta_factor = 1.0
    else:
        eta_factor = (lead_time - eta + 1) / (lead_time + 1)
        eta_factor = max(min(eta_factor, 1.0), 0.0)

    stage_factor = _in_flight_stage_factor(stage)
    effective = floor(qty * eta_factor * stage_factor)
    return max(int(effective), 0)


def _compute_economic_buffer_days(
    *,
    risk_level: str,
    allow_order_with_buffer: bool,
    total_daily_sales: float,
    lead_time_days_total: int,
    days_of_cover_estimate: float,
) -> int:
    if not allow_order_with_buffer or total_daily_sales <= 0:
        return 0

    if risk_level not in {"critical", "warning"}:
        return 0

    cover_gap_days = max(float(lead_time_days_total) - max(days_of_cover_estimate, 0.0), 0.0)
    if cover_gap_days <= 0:
        return 0

    buffer_days = _ceil_to_int(cover_gap_days * 0.35)
    if risk_level == "critical":
        buffer_days += 2
    else:
        buffer_days += 1

    return max(min(buffer_days, 14), 0)


def _estimate_competition_aware_raw_bundle_stock(
    *,
    bundle_type_ids: list[int],
    recipe_colors_by_bundle: dict[int, set[int]],
    all_recipe_color_ids: list[int],
    size_ids: list[int],
    stock_by_color_size: dict[tuple[int, int], int],
    shares_by_bundle: dict[int, float],
) -> dict[int, int]:
    raw_by_bundle: dict[int, int] = {bundle_type_id: 0 for bundle_type_id in bundle_type_ids}

    color_consumers: dict[int, list[int]] = {}
    for color_id in all_recipe_color_ids:
        color_consumers[color_id] = [
            bundle_type_id
            for bundle_type_id in bundle_type_ids
            if color_id in recipe_colors_by_bundle.get(bundle_type_id, set())
        ]

    for size_id in size_ids:
        color_bundle_alloc: dict[tuple[int, int], int] = {}

        for color_id in all_recipe_color_ids:
            color_qty = max(stock_by_color_size.get((color_id, size_id), 0), 0)
            if color_qty <= 0:
                continue

            consumers = color_consumers.get(color_id, [])
            if not consumers:
                continue

            if len(consumers) == 1:
                color_bundle_alloc[(color_id, consumers[0])] = color_qty
                continue

            consumer_weights = _normalize_weights(
                consumers,
                {bundle_type_id: shares_by_bundle.get(bundle_type_id, 0.0) for bundle_type_id in consumers},
            )
            allocated = _allocate_units(color_qty, consumer_weights)
            for bundle_type_id, allocated_qty in allocated.items():
                if allocated_qty <= 0:
                    continue
                color_bundle_alloc[(color_id, bundle_type_id)] = allocated_qty

        for bundle_type_id in bundle_type_ids:
            recipe_colors = recipe_colors_by_bundle.get(bundle_type_id, set())
            if not recipe_colors:
                continue

            color_quantities = [
                color_bundle_alloc.get((color_id, bundle_type_id), 0) for color_id in recipe_colors
            ]
            if not color_quantities or any(quantity <= 0 for quantity in color_quantities):
                continue

            raw_by_bundle[bundle_type_id] += min(color_quantities)

    return raw_by_bundle


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


def build_production_order_proposal(
    db: Session,
    request: ProductionOrderProposalRequest,
) -> ProductionOrderProposalResponse:
    now = datetime.now(timezone.utc)

    article = db.query(Article).filter(Article.id == request.article_id).first()
    if article is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Article not found")

    article_settings = (
        db.query(ArticlePlanningSettings)
        .filter(ArticlePlanningSettings.article_id == request.article_id)
        .first()
    )
    planning_settings = (
        db.query(PlanningSettings)
        .filter(PlanningSettings.article_id == request.article_id)
        .first()
    )
    global_settings = (
        db.query(GlobalPlanningSettings).order_by(GlobalPlanningSettings.id).first()
    )

    settings = _build_effective_settings(
        article_settings=article_settings,
        planning_settings=planning_settings,
        global_settings=global_settings,
        overrides=request.overrides,
    )

    if not settings.include_in_planning:
        return ProductionOrderProposalResponse(
            status="skipped",
            article_id=request.article_id,
            generated_at=now,
            risk_level="no_data",
            days_of_cover_estimate=0.0,
            lead_time_days_total=settings.lead_time_days_total,
            recommendation=None,
            constraints_applied=ProductionOrderConstraintsApplied(),
            alternatives=[],
            explanation=ProductionOrderExplanationBlock(
                summary="Артикул исключен из планирования настройкой include_in_planning=false.",
                steps=[
                    "Получены настройки статьи и проверен флаг include_in_planning.",
                    "Расчет пропущен по явному правилу исключения.",
                ],
            ),
        )

    bundle_type_ids = sorted({item.bundle_type_id for item in request.bundle_daily_sales})

    recipes = (
        db.query(BundleRecipe)
        .filter(
            BundleRecipe.article_id == request.article_id,
            BundleRecipe.bundle_type_id.in_(bundle_type_ids),
        )
        .all()
    )

    if not recipes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No bundle recipe defined for the provided article and bundle types",
        )

    recipe_colors_by_bundle: dict[int, set[int]] = defaultdict(set)
    for recipe in recipes:
        recipe_colors_by_bundle[recipe.bundle_type_id].add(recipe.color_id)

    missing_bundle_types = [
        bundle_type_id
        for bundle_type_id in bundle_type_ids
        if not recipe_colors_by_bundle.get(bundle_type_id)
    ]
    if missing_bundle_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No bundle recipe defined for bundle_type_id(s): {missing_bundle_types}",
        )

    all_recipe_color_ids = sorted({color_id for colors in recipe_colors_by_bundle.values() for color_id in colors})

    sku_units = (
        db.query(SkuUnit)
        .filter(
            SkuUnit.article_id == request.article_id,
            SkuUnit.color_id.in_(all_recipe_color_ids),
        )
        .all()
    )

    if not sku_units:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No SKU units found for article and recipe colors",
        )

    sku_by_color_size: dict[tuple[int, int], SkuUnit] = {}
    color_to_sizes: dict[int, list[int]] = defaultdict(list)
    size_ids_set: set[int] = set()
    for sku in sku_units:
        sku_by_color_size[(sku.color_id, sku.size_id)] = sku
        color_to_sizes[sku.color_id].append(sku.size_id)
        size_ids_set.add(sku.size_id)

    size_ids = sorted(size_ids_set)
    for color_id in color_to_sizes:
        color_to_sizes[color_id] = sorted(set(color_to_sizes[color_id]))

    requested_size_weights = {
        int(size_id): float(weight) for size_id, weight in request.size_weights.items() if weight > 0
    }
    size_weights_source = "request"
    if not requested_size_weights:
        requested_size_weights = _load_admin_size_weights(
            db=db,
            article_id=request.article_id,
            size_ids=size_ids,
        )
        if requested_size_weights:
            size_weights_source = "admin_defaults"
        else:
            size_weights_source = "uniform_fallback"

    size_weights = _normalize_weights(size_ids, requested_size_weights)

    stock_agg_rows = (
        db.query(
            StockBalance.sku_unit_id,
            func.sum(StockBalance.quantity).label("total_qty"),
        )
        .filter(StockBalance.sku_unit_id.in_([sku.id for sku in sku_units]))
        .group_by(StockBalance.sku_unit_id)
        .all()
    )
    stock_by_sku_id = {
        int(row.sku_unit_id): max(int(row.total_qty or 0), 0) for row in stock_agg_rows
    }

    stock_by_color_size: dict[tuple[int, int], int] = {}
    for sku in sku_units:
        stock_by_color_size[(sku.color_id, sku.size_id)] = stock_by_sku_id.get(sku.id, 0)

    effective_in_flight_supply = list(request.in_flight_supply)
    in_flight_source = "request"

    if not effective_in_flight_supply:
        admin_defaults = _load_admin_in_flight_defaults(
            db=db,
            article_id=request.article_id,
        )
        if admin_defaults:
            in_flight_source = "admin_defaults"
            for row in admin_defaults:
                effective_in_flight_supply.append(row)
        else:
            in_flight_source = "none"

    in_flight_raw_qty_total = 0
    in_flight_effective_qty_total = 0
    in_flight_effective_lines = 0

    # Add in-flight supply with ETA/stage sensitivity.
    for in_flight in effective_in_flight_supply:
        if in_flight.article_id != request.article_id:
            continue

        key = (in_flight.color_id, in_flight.size_id)
        if key not in sku_by_color_size:
            continue

        raw_qty = max(int(in_flight.qty), 0)
        if raw_qty <= 0:
            continue

        in_flight_raw_qty_total += raw_qty
        effective_qty = _estimate_effective_in_flight_qty(
            qty=raw_qty,
            eta_days=int(in_flight.eta_days),
            lead_time_days_total=settings.lead_time_days_total,
            stage=getattr(in_flight, "stage", "other"),
        )
        if effective_qty <= 0:
            continue

        in_flight_effective_qty_total += effective_qty
        in_flight_effective_lines += 1

        stock_by_color_size[key] = stock_by_color_size.get(key, 0) + effective_qty

    demand_by_bundle = {item.bundle_type_id: item.daily_sales for item in request.bundle_daily_sales}
    total_daily_sales = float(sum(demand_by_bundle.values()))

    stock_by_bundle = {
        item.bundle_type_id: item.wb_qty + item.local_qty for item in request.bundle_stock
    }
    bundle_stock_source = "request"

    missing_bundle_type_ids = [
        bundle_type_id
        for bundle_type_id in bundle_type_ids
        if bundle_type_id not in stock_by_bundle
    ]
    if missing_bundle_type_ids:
        wb_bundle_stock = _load_wb_bundle_stock(
            db=db,
            article_id=request.article_id,
            bundle_type_ids=missing_bundle_type_ids,
        )
        for bundle_type_id in missing_bundle_type_ids:
            if bundle_type_id in wb_bundle_stock:
                stock_by_bundle[bundle_type_id] = wb_bundle_stock[bundle_type_id]

        if wb_bundle_stock:
            if request.bundle_stock:
                bundle_stock_source = "mixed_request_plus_wb"
            else:
                bundle_stock_source = "wb_defaults"
        elif not request.bundle_stock:
            bundle_stock_source = "none"

    ready_bundle_stock_total = sum(stock_by_bundle.get(bundle_type_id, 0) for bundle_type_id in bundle_type_ids)

    shares_by_bundle: dict[int, float] = {}
    if total_daily_sales > 0:
        for bundle_type_id in bundle_type_ids:
            shares_by_bundle[bundle_type_id] = demand_by_bundle.get(bundle_type_id, 0.0) / total_daily_sales
    else:
        equal_share = 1.0 / len(bundle_type_ids)
        for bundle_type_id in bundle_type_ids:
            shares_by_bundle[bundle_type_id] = equal_share

    competition_raw_by_bundle = _estimate_competition_aware_raw_bundle_stock(
        bundle_type_ids=bundle_type_ids,
        recipe_colors_by_bundle=recipe_colors_by_bundle,
        all_recipe_color_ids=all_recipe_color_ids,
        size_ids=size_ids,
        stock_by_color_size=stock_by_color_size,
        shares_by_bundle=shares_by_bundle,
    )
    competition_raw_bundle_stock = sum(competition_raw_by_bundle.values())
    competition_raw_breakdown = ", ".join(
        f"{bundle_type_id}:{competition_raw_by_bundle.get(bundle_type_id, 0)}"
        for bundle_type_id in bundle_type_ids
    )

    available_bundles_for_cover = ready_bundle_stock_total + competition_raw_bundle_stock

    if total_daily_sales <= 0:
        days_of_cover_estimate = 9999.0
        risk_level = "no_data"
    else:
        days_of_cover_estimate = available_bundles_for_cover / total_daily_sales
        if days_of_cover_estimate < settings.lead_time_days_total:
            risk_level = "critical"
        elif days_of_cover_estimate < settings.alert_threshold_days:
            risk_level = "warning"
        elif days_of_cover_estimate > settings.target_coverage_days * 2:
            risk_level = "overstock"
        else:
            risk_level = "ok"

    economic_buffer_days = _compute_economic_buffer_days(
        risk_level=risk_level,
        allow_order_with_buffer=settings.allow_order_with_buffer,
        total_daily_sales=total_daily_sales,
        lead_time_days_total=settings.lead_time_days_total,
        days_of_cover_estimate=days_of_cover_estimate,
    )
    target_bundle_horizon_days = (
        settings.target_coverage_days + settings.lead_time_days_total + economic_buffer_days
    )

    required_bundle_units = _ceil_to_int(
        total_daily_sales * target_bundle_horizon_days
    )
    bundle_deficit_total = max(required_bundle_units - available_bundles_for_cover, 0)

    color_probability: dict[int, float] = {color_id: 0.0 for color_id in all_recipe_color_ids}
    for color_id in all_recipe_color_ids:
        for bundle_type_id in bundle_type_ids:
            if color_id in recipe_colors_by_bundle[bundle_type_id]:
                color_probability[color_id] += shares_by_bundle.get(bundle_type_id, 0.0)

    if sum(color_probability.values()) <= 0:
        uniform = 1.0 / len(all_recipe_color_ids)
        color_probability = {color_id: uniform for color_id in all_recipe_color_ids}

    line_required: dict[tuple[int, int], int] = {}
    for color_id in all_recipe_color_ids:
        color_target_units = _ceil_to_int(bundle_deficit_total * color_probability.get(color_id, 0.0))
        sizes_for_color = color_to_sizes.get(color_id, [])
        if not sizes_for_color:
            continue

        local_weights = _normalize_weights(
            sizes_for_color,
            {size_id: size_weights.get(size_id, 0.0) for size_id in sizes_for_color},
        )
        allocated = _allocate_units(color_target_units, local_weights)

        for size_id, qty in allocated.items():
            line_required[(color_id, size_id)] = qty

    line_qty: dict[tuple[int, int], int] = {}
    for key, required_qty in line_required.items():
        current_qty = stock_by_color_size.get(key, 0)
        line_qty[key] = max(required_qty - current_qty, 0)

    color_totals: dict[int, int] = defaultdict(int)
    for (color_id, _size_id), qty in line_qty.items():
        color_totals[color_id] += qty

    colors = db.query(Color).filter(Color.id.in_(all_recipe_color_ids)).all()
    pantone_by_color: dict[int, str] = {}
    for color in colors:
        pantone_by_color[color.id] = color.pantone_code or f"COLOR-{color.id}"

    color_settings_rows = (
        db.query(ColorPlanningSettings)
        .filter(
            ColorPlanningSettings.article_id == request.article_id,
            ColorPlanningSettings.color_id.in_(all_recipe_color_ids),
        )
        .all()
    )
    color_min_override = {
        row.color_id: row.fabric_min_batch_qty
        for row in color_settings_rows
        if row.fabric_min_batch_qty is not None and row.fabric_min_batch_qty > 0
    }

    constraints_applied = ProductionOrderConstraintsApplied()

    colors_by_pantone: dict[str, list[int]] = defaultdict(list)
    for color_id in all_recipe_color_ids:
        colors_by_pantone[pantone_by_color.get(color_id, f"COLOR-{color_id}")].append(color_id)

    for pantone_code, pantone_color_ids in sorted(colors_by_pantone.items(), key=lambda item: item[0]):
        required_qty = sum(color_totals.get(color_id, 0) for color_id in pantone_color_ids)
        if required_qty <= 0:
            continue

        min_candidates = [settings.fabric_min_batch_default]
        for color_id in pantone_color_ids:
            override_value = color_min_override.get(color_id)
            if override_value is not None:
                min_candidates.append(override_value)

        applied_min = max(min_candidates)
        if required_qty >= applied_min:
            continue

        delta = applied_min - required_qty
        constraints_applied.fabric_min_batches.append(
            FabricConstraintApplied(
                pantone_code=pantone_code,
                required=required_qty,
                applied_min=applied_min,
            )
        )

        if len(pantone_color_ids) == 1:
            _add_units_for_color(
                line_qty=line_qty,
                color_id=pantone_color_ids[0],
                additional_qty=delta,
                color_to_sizes=color_to_sizes,
                global_size_weights=size_weights,
            )
        else:
            total_color_weight = sum(max(color_totals.get(color_id, 0), 1) for color_id in pantone_color_ids)
            color_weights = {
                color_id: max(color_totals.get(color_id, 0), 1) / total_color_weight
                for color_id in pantone_color_ids
            }
            color_alloc = _allocate_units(delta, color_weights)
            for color_id, qty in color_alloc.items():
                _add_units_for_color(
                    line_qty=line_qty,
                    color_id=color_id,
                    additional_qty=qty,
                    color_to_sizes=color_to_sizes,
                    global_size_weights=size_weights,
                )

        # Recalculate color totals after updates.
        color_totals = defaultdict(int)
        for (color_id, _size_id), qty in line_qty.items():
            color_totals[color_id] += qty

    elastic_rows = (
        db.query(ElasticPlanningSettings)
        .filter(ElasticPlanningSettings.article_id == request.article_id)
        .all()
    )

    elastic_bindings = (
        db.query(ProductionOrderElasticBinding)
        .filter(
            ProductionOrderElasticBinding.article_id == request.article_id,
            ProductionOrderElasticBinding.is_active.is_(True),
        )
        .all()
    )

    applicable_elastic_type_ids, elastic_scope_line_keys = _resolve_elastic_binding_scope(
        bindings=elastic_bindings,
        line_qty=line_qty,
        sku_by_color_size=sku_by_color_size,
    )

    scoped_elastic_rows = list(elastic_rows)
    elastic_scope_mode = "all_types"
    if elastic_bindings:
        elastic_scope_mode = "binding_scope"
        if applicable_elastic_type_ids:
            scoped_elastic_rows = [
                row for row in elastic_rows if row.elastic_type_id in applicable_elastic_type_ids
            ]
        else:
            scoped_elastic_rows = []

    current_total_units = sum(line_qty.values())

    elastic_target = settings.elastic_min_batch_default
    elastic_type_id: int | None = None

    if elastic_bindings and not applicable_elastic_type_ids:
        elastic_target = 0

    for row in scoped_elastic_rows:
        candidate = row.elastic_min_batch_qty
        if candidate is None or candidate <= 0:
            candidate = settings.elastic_min_batch_default

        if candidate > elastic_target:
            elastic_target = candidate
            elastic_type_id = row.elastic_type_id

    elastic_uplift_delta = 0
    elastic_uplift_scope = "none"
    elastic_uplift_keys: list[tuple[int, int]] = []
    elastic_uplift_line_alloc: dict[tuple[int, int], int] = {}

    if current_total_units > 0 and elastic_target > 0 and current_total_units < elastic_target:
        delta = elastic_target - current_total_units
        elastic_uplift_delta = delta
        constraints_applied.elastic_min_batches.append(
            ElasticConstraintApplied(
                article_id=request.article_id,
                elastic_type_id=elastic_type_id,
                required=current_total_units,
                applied_min=elastic_target,
            )
        )

        if line_qty:
            if elastic_bindings and elastic_scope_line_keys:
                keys = sorted(elastic_scope_line_keys)
                elastic_uplift_scope = "binding_scope"
            else:
                keys = sorted(line_qty.keys())
                elastic_uplift_scope = "all_lines"
            elastic_uplift_keys = list(keys)
            base_add = delta // len(keys)
            rem = delta % len(keys)
            for index, key in enumerate(keys):
                add_qty = base_add + (1 if index < rem else 0)
                line_qty[key] += add_qty
                if add_qty > 0:
                    elastic_uplift_line_alloc[key] = add_qty

    candidate_lines: list[ProductionOrderRecommendationLine] = []
    for (color_id, size_id), qty in sorted(line_qty.items(), key=lambda item: (item[0][0], item[0][1])):
        if qty <= 0:
            continue
        candidate_lines.append(
            ProductionOrderRecommendationLine(
                article_id=request.article_id,
                color_id=color_id,
                size_id=size_id,
                recommended_qty=qty,
                source_reason="deficit_plus_min_batch_alignment",
            )
        )

    candidate_total_units = sum(line.recommended_qty for line in candidate_lines)
    action = _choose_action(
        risk_level=risk_level,
        candidate_units=candidate_total_units,
        allow_order_with_buffer=settings.allow_order_with_buffer,
    )

    if action == "wait":
        recommendation = ProductionOrderRecommendation(
            action="wait",
            priority=settings.priority,
            target_arrival_date=(now + timedelta(days=settings.lead_time_days_total)).date(),
            total_units=0,
            lines=[],
        )
    else:
        recommendation = ProductionOrderRecommendation(
            action=action,
            priority=settings.priority,
            target_arrival_date=(now + timedelta(days=settings.lead_time_days_total)).date(),
            total_units=candidate_total_units,
            lines=candidate_lines,
        )

    alternatives = _build_alternatives(action)

    expected_horizon_sales = total_daily_sales * request.planning_horizon_days
    explanation = ProductionOrderExplanationBlock(
        summary=(
            f"Риск {risk_level}: оценка покрытия {days_of_cover_estimate:.1f} дней при lead time "
            f"{settings.lead_time_days_total} дней."
        ),
        steps=[
            (
                f"Спрос по наборам: total_daily_sales={total_daily_sales:.3f}, "
                f"planning_horizon_days={request.planning_horizon_days}, "
                f"expected_horizon_sales={expected_horizon_sales:.1f}."
            ),
            (
                f"Учтены ready stock наборов (WB+локальный)={ready_bundle_stock_total} и "
                f"оценка сырьевого потенциала={competition_raw_bundle_stock} "
                f"(competition-aware by bundle: {competition_raw_breakdown})."
            ),
            (
                f"Дефицит по модели B: target_bundle_units={required_bundle_units}, "
                f"bundle_deficit_total={bundle_deficit_total}, распределение через size_weights."
            ),
            (
                f"Economic buffer policy: enabled={settings.allow_order_with_buffer}, "
                f"economic_buffer_days={economic_buffer_days}, target_horizon_days={target_bundle_horizon_days}."
            ),
            (
                f"Источник параметров: size_weights={size_weights_source}, "
                f"in_flight={in_flight_source}, bundle_stock={bundle_stock_source}."
            ),
            (
                f"Elastic scope: mode={elastic_scope_mode}, "
                f"applicable_types={sorted(applicable_elastic_type_ids)}, "
                f"scoped_settings={len(scoped_elastic_rows)}, "
                f"scoped_lines={len(elastic_scope_line_keys)}."
            ),
            (
                f"Elastic uplift: delta={elastic_uplift_delta}, "
                f"scope={elastic_uplift_scope}, "
                f"affected_lines={len(elastic_uplift_keys)}, "
                f"line_keys={elastic_uplift_keys}, "
                f"line_alloc={elastic_uplift_line_alloc}."
            ),
            (
                f"In-flight вклад (ETA/stage): raw_qty={in_flight_raw_qty_total}, "
                f"effective_qty={in_flight_effective_qty_total}, lines={in_flight_effective_lines}."
            ),
            (
                f"Применены ограничения: fabric_constraints={len(constraints_applied.fabric_min_batches)}, "
                f"elastic_constraints={len(constraints_applied.elastic_min_batches)}."
            ),
        ],
    )

    return ProductionOrderProposalResponse(
        status="ok",
        article_id=request.article_id,
        generated_at=now,
        risk_level=risk_level,
        days_of_cover_estimate=float(days_of_cover_estimate),
        lead_time_days_total=settings.lead_time_days_total,
        recommendation=recommendation,
        constraints_applied=constraints_applied,
        alternatives=alternatives,
        explanation=explanation,
    )
