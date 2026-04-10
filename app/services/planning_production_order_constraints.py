from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.models import (
    Article,
    ArticlePlanningSettings,
    ArticleWbMapping,
    Color,
    SkuUnit,
    WbSalesDaily,
)
from app.schemas.planning_production_order import (
    FabricConstraintApplied,
    ProductionOrderResourceAllocationApplied,
    ResourceAllocationBundleReservation,
    ResourceAllocationReservation,
)

RESOURCE_ALLOCATION_CONTRACT_VERSION = "v1_alpha"
SHARED_COLOR_POOL_SOURCE = "wb_sales_article_proxy"
SHARED_COLOR_POOL_DEFAULT_OBSERVATION_WINDOW_DAYS = 30


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


def _build_resource_allocation_contract_summary(
    resource_allocation: ProductionOrderResourceAllocationApplied | dict[str, object],
) -> dict[str, object]:
    payload = (
        resource_allocation.model_dump(mode="python")
        if isinstance(resource_allocation, ProductionOrderResourceAllocationApplied)
        else dict(resource_allocation)
    )
    reservations_raw = payload.get("reservations", [])
    reservations = reservations_raw if isinstance(reservations_raw, list) else []

    no_double_use = True
    allocation_sums_consistent = True
    total_reserved_from_reservations = 0
    for reservation in reservations:
        if not isinstance(reservation, dict):
            no_double_use = False
            allocation_sums_consistent = False
            continue

        stock_qty = int(reservation.get("stock_qty", 0) or 0)
        total_reserved_qty = int(reservation.get("total_reserved_qty", 0) or 0)
        allocations_raw = reservation.get("allocations", [])
        allocations = allocations_raw if isinstance(allocations_raw, list) else []
        allocated_sum = sum(
            int(item.get("reserved_qty", 0) or 0)
            for item in allocations
            if isinstance(item, dict)
        )

        total_reserved_from_reservations += total_reserved_qty
        if total_reserved_qty > stock_qty:
            no_double_use = False
        if allocated_sum != total_reserved_qty:
            allocation_sums_consistent = False

    reservation_total_matches_summary = (
        total_reserved_from_reservations == int(payload.get("total_reserved_units", 0) or 0)
    )
    checks = {
        "no_double_use": no_double_use,
        "allocation_sums_consistent": allocation_sums_consistent,
        "reservation_total_matches_summary": reservation_total_matches_summary,
    }
    return {
        "version": RESOURCE_ALLOCATION_CONTRACT_VERSION,
        "status": "ok" if all(checks.values()) else "violated",
        "checks": checks,
    }


def _build_competition_aware_resource_allocation(
    *,
    bundle_type_ids: list[int],
    recipe_colors_by_bundle: dict[int, set[int]],
    all_recipe_color_ids: list[int],
    size_ids: list[int],
    stock_by_color_size: dict[tuple[int, int], int],
    shares_by_bundle: dict[int, float],
) -> ProductionOrderResourceAllocationApplied:
    reservations: list[ResourceAllocationReservation] = []
    reserved_bundle_units: dict[int, int] = {int(bundle_type_id): 0 for bundle_type_id in bundle_type_ids}
    competing_resource_keys = 0
    fully_reserved_resource_keys = 0
    total_stock_units = 0
    total_reserved_units = 0

    color_consumers: dict[int, list[int]] = {
        int(color_id): [
            int(bundle_type_id)
            for bundle_type_id in bundle_type_ids
            if color_id in recipe_colors_by_bundle.get(bundle_type_id, set())
        ]
        for color_id in all_recipe_color_ids
    }

    for size_id in size_ids:
        color_bundle_alloc: dict[tuple[int, int], int] = {}
        for color_id in all_recipe_color_ids:
            stock_qty = max(int(stock_by_color_size.get((color_id, size_id), 0) or 0), 0)
            total_stock_units += stock_qty
            consumers = color_consumers.get(int(color_id), [])
            if not consumers:
                continue

            shared_resource = len(consumers) > 1
            if shared_resource:
                competing_resource_keys += 1

            allocations: list[ResourceAllocationBundleReservation] = []
            total_reserved_qty = 0
            if len(consumers) == 1:
                bundle_type_id = int(consumers[0])
                if stock_qty > 0:
                    allocations.append(
                        ResourceAllocationBundleReservation(
                            bundle_type_id=bundle_type_id,
                            reserved_qty=stock_qty,
                            share_weight=1.0,
                            allocation_basis="single_consumer",
                        )
                    )
                    color_bundle_alloc[(int(color_id), bundle_type_id)] = stock_qty
                    total_reserved_qty = stock_qty
            else:
                consumer_weights = _normalize_weights(
                    consumers,
                    {bundle_type_id: shares_by_bundle.get(bundle_type_id, 0.0) for bundle_type_id in consumers},
                )
                allocated = _allocate_units(stock_qty, consumer_weights)
                for bundle_type_id in consumers:
                    reserved_qty = max(int(allocated.get(bundle_type_id, 0) or 0), 0)
                    if reserved_qty <= 0:
                        continue
                    allocations.append(
                        ResourceAllocationBundleReservation(
                            bundle_type_id=int(bundle_type_id),
                            reserved_qty=reserved_qty,
                            share_weight=float(consumer_weights.get(bundle_type_id, 0.0)),
                            allocation_basis="demand_share",
                        )
                    )
                    color_bundle_alloc[(int(color_id), int(bundle_type_id))] = reserved_qty
                    total_reserved_qty += reserved_qty

            if stock_qty > 0 or allocations:
                if stock_qty > 0 and total_reserved_qty >= stock_qty:
                    fully_reserved_resource_keys += 1
                total_reserved_units += total_reserved_qty
                reservations.append(
                    ResourceAllocationReservation(
                        color_id=int(color_id),
                        size_id=int(size_id),
                        stock_qty=stock_qty,
                        total_reserved_qty=total_reserved_qty,
                        shared_resource=shared_resource,
                        consumer_bundle_type_ids=[int(bundle_type_id) for bundle_type_id in consumers],
                        allocations=allocations,
                    )
                )

        for bundle_type_id in bundle_type_ids:
            recipe_colors = recipe_colors_by_bundle.get(bundle_type_id, set())
            if not recipe_colors:
                continue

            reserved_color_qty = [
                color_bundle_alloc.get((int(color_id), int(bundle_type_id)), 0)
                for color_id in recipe_colors
            ]
            if not reserved_color_qty or any(quantity <= 0 for quantity in reserved_color_qty):
                continue
            reserved_bundle_units[int(bundle_type_id)] += min(reserved_color_qty)

    allocation = ProductionOrderResourceAllocationApplied(
        mode="per_article_bundle_competition",
        total_resource_keys=len(all_recipe_color_ids) * len(size_ids),
        competing_resource_keys=competing_resource_keys,
        fully_reserved_resource_keys=fully_reserved_resource_keys,
        total_stock_units=total_stock_units,
        total_reserved_units=total_reserved_units,
        reserved_bundle_units=reserved_bundle_units,
        reservations=reservations,
        contract={},
    )
    allocation.contract = _build_resource_allocation_contract_summary(allocation)
    return allocation


def _add_units_for_color_with_constraints_weights(
    *,
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


@dataclass(frozen=True)
class _SharedColorPoolFabricConstraintsResult:
    shared_color_pool: dict[str, object]
    fabric_constraints: list[FabricConstraintApplied]


def _resolve_shared_color_pool_as_of_date(
    db: Session,
    requested_as_of_date: date | None,
) -> tuple[date, str]:
    if requested_as_of_date is not None:
        return requested_as_of_date, "request"

    latest_sales_date = db.query(func.max(WbSalesDaily.date)).scalar()
    if isinstance(latest_sales_date, date):
        return latest_sales_date, "latest_wb_sales"

    return datetime.now(timezone.utc).date(), "utc_today"



def _build_shared_color_pool_snapshot(
    *,
    db: Session,
    article_id: int,
    pantone_by_color: dict[int, str],
    target_horizon_days: int,
    observation_window_days: int | None,
    as_of_date: date | None,
) -> dict[str, object]:
    pantone_codes = sorted({value for value in pantone_by_color.values() if value})
    window_days = max(int(observation_window_days or SHARED_COLOR_POOL_DEFAULT_OBSERVATION_WINDOW_DAYS), 1)
    effective_as_of_date, as_of_source = _resolve_shared_color_pool_as_of_date(db, as_of_date)

    snapshot: dict[str, object] = {
        "source": SHARED_COLOR_POOL_SOURCE,
        "status": "no_shared_pantones",
        "applies_to": "fabric_min_batch_only",
        "observation_window_days": window_days,
        "as_of_date": effective_as_of_date.isoformat(),
        "as_of_source": as_of_source,
        "target_horizon_days": int(target_horizon_days),
        "pantones": {},
        "sibling_article_count": 0,
        "sibling_proxy_required_total": 0,
    }
    if not pantone_codes:
        return snapshot

    sibling_rows = (
        db.query(SkuUnit.article_id, Color.pantone_code)
        .join(Color, Color.id == SkuUnit.color_id)
        .filter(
            SkuUnit.article_id != article_id,
            Color.pantone_code.isnot(None),
            Color.pantone_code.in_(pantone_codes),
        )
        .all()
    )
    if not sibling_rows:
        snapshot["status"] = "no_sibling_articles"
        snapshot["pantones"] = {
            pantone_code: {
                "sibling_proxy_required": 0,
                "sibling_article_ids": [],
                "contributors": [],
            }
            for pantone_code in pantone_codes
        }
        return snapshot

    candidate_article_ids = sorted({int(row.article_id) for row in sibling_rows})
    article_settings_rows = (
        db.query(ArticlePlanningSettings)
        .filter(ArticlePlanningSettings.article_id.in_(candidate_article_ids))
        .all()
    )
    include_in_planning_by_article = {
        int(row.article_id): bool(row.include_in_planning) for row in article_settings_rows
    }
    sibling_article_ids = sorted(
        article_id_value
        for article_id_value in candidate_article_ids
        if include_in_planning_by_article.get(article_id_value, True)
    )
    if not sibling_article_ids:
        snapshot["status"] = "siblings_excluded_from_planning"
        snapshot["pantones"] = {
            pantone_code: {
                "sibling_proxy_required": 0,
                "sibling_article_ids": [],
                "contributors": [],
            }
            for pantone_code in pantone_codes
        }
        return snapshot

    article_code_rows = db.query(Article.id, Article.code).filter(Article.id.in_(sibling_article_ids)).all()
    article_code_by_id = {int(article_row_id): str(article_code) for article_row_id, article_code in article_code_rows}

    article_pantone_rows = (
        db.query(SkuUnit.article_id, Color.pantone_code)
        .join(Color, Color.id == SkuUnit.color_id)
        .filter(
            SkuUnit.article_id.in_(sibling_article_ids),
            Color.pantone_code.isnot(None),
        )
        .distinct()
        .all()
    )
    pantones_by_article: dict[int, set[str]] = defaultdict(set)
    for sibling_article_id, pantone_code in article_pantone_rows:
        if pantone_code:
            pantones_by_article[int(sibling_article_id)].add(str(pantone_code))

    sales_window_start = effective_as_of_date - timedelta(days=window_days - 1)
    sibling_sales_rows = (
        db.query(
            ArticleWbMapping.article_id,
            func.coalesce(func.sum(WbSalesDaily.sales_qty), 0).label("sales_qty"),
        )
        .join(WbSalesDaily, WbSalesDaily.wb_sku == ArticleWbMapping.wb_sku)
        .filter(
            ArticleWbMapping.article_id.in_(sibling_article_ids),
            WbSalesDaily.date >= sales_window_start,
            WbSalesDaily.date <= effective_as_of_date,
        )
        .group_by(ArticleWbMapping.article_id)
        .all()
    )
    sales_qty_by_article = {
        int(row.article_id): max(int(row.sales_qty or 0), 0) for row in sibling_sales_rows
    }

    pantone_items: dict[str, dict[str, object]] = {
        pantone_code: {
            "sibling_proxy_required": 0,
            "sibling_article_ids": [],
            "contributors": [],
        }
        for pantone_code in pantone_codes
    }

    total_proxy_required = 0
    pantone_code_set = set(pantone_codes)
    for sibling_article_id in sibling_article_ids:
        article_pantones = sorted(pantones_by_article.get(sibling_article_id, set()) & pantone_code_set)
        if not article_pantones:
            continue

        article_sales_qty = sales_qty_by_article.get(sibling_article_id, 0)
        article_avg_daily_sales = float(article_sales_qty) / float(window_days) if window_days > 0 else 0.0
        if article_avg_daily_sales <= 0:
            continue

        per_pantone_daily_sales = article_avg_daily_sales / float(len(article_pantones))
        proxy_required_units = _ceil_to_int(per_pantone_daily_sales * float(target_horizon_days))
        if proxy_required_units <= 0:
            continue

        for pantone_code in article_pantones:
            item = pantone_items[pantone_code]
            sibling_ids = item["sibling_article_ids"]
            if isinstance(sibling_ids, list) and sibling_article_id not in sibling_ids:
                sibling_ids.append(sibling_article_id)
            contributors = item["contributors"]
            if isinstance(contributors, list):
                contributors.append(
                    {
                        "article_id": sibling_article_id,
                        "article_code": article_code_by_id.get(sibling_article_id, f"ARTICLE-{sibling_article_id}"),
                        "avg_daily_sales_article": round(article_avg_daily_sales, 4),
                        "avg_daily_sales_pantone_proxy": round(per_pantone_daily_sales, 4),
                        "proxy_required_units": proxy_required_units,
                    }
                )
            item["sibling_proxy_required"] = int(item.get("sibling_proxy_required", 0) or 0) + proxy_required_units
            total_proxy_required += proxy_required_units

    snapshot["status"] = "ok" if total_proxy_required > 0 else "no_sibling_sales_signal"
    snapshot["pantones"] = pantone_items
    snapshot["sibling_article_count"] = len(sibling_article_ids)
    snapshot["sibling_proxy_required_total"] = total_proxy_required
    return snapshot


def _apply_shared_color_pool_fabric_min_batches(
    *,
    db: Session,
    article_id: int,
    pantone_by_color: dict[int, str],
    target_horizon_days: int,
    observation_window_days: int | None,
    as_of_date: date | None,
    all_recipe_color_ids: list[int],
    fabric_min_batch_default: int,
    color_min_override: dict[int, int],
    line_qty: dict[tuple[int, int], int],
    color_to_sizes: dict[int, list[int]],
    global_size_weights: dict[int, float],
) -> _SharedColorPoolFabricConstraintsResult:
    shared_color_pool = _build_shared_color_pool_snapshot(
        db=db,
        article_id=article_id,
        pantone_by_color=pantone_by_color,
        target_horizon_days=target_horizon_days,
        observation_window_days=observation_window_days,
        as_of_date=as_of_date,
    )

    color_totals: dict[int, int] = defaultdict(int)
    for (color_id, _size_id), qty in line_qty.items():
        color_totals[color_id] += qty

    colors_by_pantone: dict[str, list[int]] = defaultdict(list)
    for color_id in all_recipe_color_ids:
        colors_by_pantone[pantone_by_color.get(color_id, f"COLOR-{color_id}")].append(color_id)

    fabric_constraints: list[FabricConstraintApplied] = []
    for pantone_code, pantone_color_ids in sorted(colors_by_pantone.items(), key=lambda item: item[0]):
        required_qty = sum(color_totals.get(color_id, 0) for color_id in pantone_color_ids)
        if required_qty <= 0:
            continue

        shared_color_pool_item = shared_color_pool.get("pantones", {}).get(pantone_code, {})
        sibling_proxy_required = int(
            shared_color_pool_item.get("sibling_proxy_required", 0)
            if isinstance(shared_color_pool_item, dict)
            else 0
        )
        shared_pool_required = required_qty + sibling_proxy_required

        min_candidates = [fabric_min_batch_default]
        for color_id in pantone_color_ids:
            override_value = color_min_override.get(color_id)
            if override_value is not None:
                min_candidates.append(override_value)

        applied_min = max(min_candidates)
        if shared_pool_required >= applied_min:
            continue

        delta = applied_min - shared_pool_required
        fabric_constraints.append(
            FabricConstraintApplied(
                pantone_code=pantone_code,
                required=required_qty,
                applied_min=applied_min,
                shared_pool_required=shared_pool_required,
                sibling_proxy_required=sibling_proxy_required,
            )
        )

        if len(pantone_color_ids) == 1:
            _add_units_for_color_with_constraints_weights(
                line_qty=line_qty,
                color_id=pantone_color_ids[0],
                additional_qty=delta,
                color_to_sizes=color_to_sizes,
                global_size_weights=global_size_weights,
            )
        else:
            total_color_weight = sum(max(color_totals.get(color_id, 0), 1) for color_id in pantone_color_ids)
            color_weights = {
                color_id: max(color_totals.get(color_id, 0), 1) / total_color_weight
                for color_id in pantone_color_ids
            }
            color_alloc = _allocate_units(delta, color_weights)
            for color_id, qty in color_alloc.items():
                _add_units_for_color_with_constraints_weights(
                    line_qty=line_qty,
                    color_id=color_id,
                    additional_qty=qty,
                    color_to_sizes=color_to_sizes,
                    global_size_weights=global_size_weights,
                )

        color_totals = defaultdict(int)
        for (color_id, _size_id), qty in line_qty.items():
            color_totals[color_id] += qty

    return _SharedColorPoolFabricConstraintsResult(
        shared_color_pool=shared_color_pool,
        fabric_constraints=fabric_constraints,
    )
