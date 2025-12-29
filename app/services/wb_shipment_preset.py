from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.models import WbShipment, WbShipmentItem
from app.schemas.wb_shipment import WbShipmentPresetResponse, WbShipmentRecentHeader


_NON_CANCELLED_STATUSES: tuple[str, ...] = ("draft", "approved", "shipped")

DEFAULT_STRATEGY = "normal"
DEFAULT_ZERO_SALES_POLICY = "ignore"
DEFAULT_TARGET_COVERAGE_DAYS = 30
DEFAULT_MIN_COVERAGE_DAYS = 7
DEFAULT_MAX_COVERAGE_DAYS_AFTER = 60
DEFAULT_MAX_REPLENISHMENT_PER_ARTICLE: int | None = None
DEFAULT_TRANSIT_DAYS = 7


def _load_recent_shipments_with_aggregates(
    db: Session,
    limit: int = 3,
) -> list[WbShipmentRecentHeader]:
    total_final_qty_expr = func.coalesce(func.sum(WbShipmentItem.final_qty), 0)
    total_items_expr = func.count(WbShipmentItem.id)

    rows = (
        db.query(
            WbShipment.id,
            WbShipment.status,
            WbShipment.target_date,
            WbShipment.wb_arrival_date,
            WbShipment.created_at,
            WbShipment.updated_at,
            total_final_qty_expr.label("total_final_qty"),
            total_items_expr.label("total_items"),
        )
        .outerjoin(WbShipmentItem, WbShipmentItem.shipment_id == WbShipment.id)
        .filter(WbShipment.status.in_(_NON_CANCELLED_STATUSES))
        .group_by(
            WbShipment.id,
            WbShipment.status,
            WbShipment.target_date,
            WbShipment.wb_arrival_date,
            WbShipment.created_at,
            WbShipment.updated_at,
        )
        .order_by(WbShipment.created_at.desc())
        .limit(limit)
        .all()
    )

    result: list[WbShipmentRecentHeader] = []
    for row in rows:
        result.append(
            WbShipmentRecentHeader(
                id=row.id,
                status=row.status,
                target_date=row.target_date,
                wb_arrival_date=row.wb_arrival_date,
                created_at=row.created_at,
                updated_at=row.updated_at,
                total_final_qty=int(row.total_final_qty or 0),
                total_items=int(row.total_items or 0),
            )
        )

    return result


def _compute_transit_days(db: Session) -> int:
    rows = (
        db.query(WbShipment.target_date, WbShipment.wb_arrival_date, WbShipment.created_at)
        .filter(WbShipment.status.in_(_NON_CANCELLED_STATUSES))
        .order_by(WbShipment.created_at.desc())
        .limit(5)
        .all()
    )

    valid_transit_days: list[int] = []
    for target_date, wb_arrival_date, _created_at in rows:
        delta_days = (wb_arrival_date - target_date).days
        if 1 <= delta_days <= 20:
            valid_transit_days.append(delta_days)

    if not valid_transit_days:
        return DEFAULT_TRANSIT_DAYS

    valid_transit_days.sort()
    n = len(valid_transit_days)
    mid = n // 2
    if n % 2 == 1:
        return valid_transit_days[mid]

    # Even number of elements: average the two middle values and round to nearest int
    return int(round((valid_transit_days[mid - 1] + valid_transit_days[mid]) / 2))


def compute_shipment_preset(
    db: Session,
    target_date: date,
) -> WbShipmentPresetResponse:
    base_shipment = (
        db.query(WbShipment)
        .filter(WbShipment.status.in_(_NON_CANCELLED_STATUSES))
        .order_by(WbShipment.created_at.desc())
        .first()
    )

    if base_shipment is not None:
        suggested_strategy = base_shipment.strategy
        suggested_zero_sales_policy = base_shipment.zero_sales_policy
        suggested_target_coverage_days = base_shipment.target_coverage_days
        suggested_min_coverage_days = base_shipment.min_coverage_days
        suggested_max_coverage_days_after = base_shipment.max_coverage_days_after
        suggested_max_replenishment_per_article = base_shipment.max_replenishment_per_article
    else:
        suggested_strategy = DEFAULT_STRATEGY
        suggested_zero_sales_policy = DEFAULT_ZERO_SALES_POLICY
        suggested_target_coverage_days = DEFAULT_TARGET_COVERAGE_DAYS
        suggested_min_coverage_days = DEFAULT_MIN_COVERAGE_DAYS
        suggested_max_coverage_days_after = DEFAULT_MAX_COVERAGE_DAYS_AFTER
        suggested_max_replenishment_per_article = DEFAULT_MAX_REPLENISHMENT_PER_ARTICLE

    recent_shipments = _load_recent_shipments_with_aggregates(db, limit=3)

    if recent_shipments:
        last_shipment_total_final_qty: int | None = int(
            recent_shipments[0].total_final_qty
        )
        avg_total_final_qty_last3: float | None = sum(
            sh.total_final_qty for sh in recent_shipments
        ) / float(len(recent_shipments))
    else:
        last_shipment_total_final_qty = None
        avg_total_final_qty_last3 = None

    transit_days_used = _compute_transit_days(db)
    suggested_wb_arrival_date = target_date + timedelta(days=transit_days_used)

    default_comment_template = (
        f"WB shipment for coverage ~{suggested_target_coverage_days} days "
        f"(ETA {suggested_wb_arrival_date.isoformat()})"
    )

    if base_shipment is not None:
        explanation = (
            f"Defaults derived from last non-cancelled shipment #{base_shipment.id} "
            f"(created_at={base_shipment.created_at.isoformat()}). "
            f"transit_days≈{transit_days_used}, "
            f"strategy={suggested_strategy}, "
            f"zero_sales_policy={suggested_zero_sales_policy}, "
            f"target_coverage_days={suggested_target_coverage_days}, "
            f"min_coverage_days={suggested_min_coverage_days}, "
            f"max_coverage_days_after={suggested_max_coverage_days_after}."
        )
    else:
        explanation = (
            "No non-cancelled WB shipments found. Used global defaults: "
            f"strategy={DEFAULT_STRATEGY}, "
            f"zero_sales_policy={DEFAULT_ZERO_SALES_POLICY}, "
            f"target_coverage_days={DEFAULT_TARGET_COVERAGE_DAYS}, "
            f"min_coverage_days={DEFAULT_MIN_COVERAGE_DAYS}, "
            f"max_coverage_days_after={DEFAULT_MAX_COVERAGE_DAYS_AFTER}, "
            f"transit_days={DEFAULT_TRANSIT_DAYS}."
        )

    return WbShipmentPresetResponse(
        target_date=target_date,
        suggested_wb_arrival_date=suggested_wb_arrival_date,
        suggested_strategy=suggested_strategy,
        suggested_zero_sales_policy=suggested_zero_sales_policy,
        suggested_target_coverage_days=suggested_target_coverage_days,
        suggested_min_coverage_days=suggested_min_coverage_days,
        suggested_max_coverage_days_after=suggested_max_coverage_days_after,
        suggested_max_replenishment_per_article=suggested_max_replenishment_per_article,
        recent_shipments=recent_shipments,
        avg_total_final_qty_last3=avg_total_final_qty_last3,
        last_shipment_total_final_qty=last_shipment_total_final_qty,
        default_comment_template=default_comment_template,
        explanation=explanation,
    )
