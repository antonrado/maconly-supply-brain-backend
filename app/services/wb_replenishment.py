from __future__ import annotations

from collections import defaultdict
from datetime import date

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.models import SkuUnit, StockBalance
from app.schemas.wb_replenishment import WbReplenishmentItem, WbReplenishmentRequest
from app.services.wb_manager import compute_manager_stats


def _compute_oos_risk(stock: int, avg_daily_sales: float, coverage_days: float) -> str:
    if stock == 0 and avg_daily_sales > 0:
        return "red"
    if avg_daily_sales > 0:
        if coverage_days < 3:
            return "red"
        if coverage_days <= 7:
            return "yellow"
        return "green"
    # avg_daily_sales == 0
    return "green"


def compute_replenishment(db: Session, payload: WbReplenishmentRequest) -> list[WbReplenishmentItem]:
    stats_list = compute_manager_stats(
        db=db,
        target_date=payload.target_date,
        article_ids=payload.article_ids,
    )
    if not stats_list:
        return []

    # Map (article, color, size) -> manager stats
    key_to_stats = {}
    article_to_keys: dict[int, list[tuple[int, int | None, int | None]]] = defaultdict(list)
    for s in stats_list:
        key = (s.article_id, s.color_id, s.size_id)
        key_to_stats[key] = s
        article_to_keys[s.article_id].append(key)

    # Map (article, color, size) -> sku_unit_id
    sku_rows = db.query(SkuUnit.id, SkuUnit.article_id, SkuUnit.color_id, SkuUnit.size_id)
    if payload.article_ids:
        sku_rows = sku_rows.filter(SkuUnit.article_id.in_(payload.article_ids))
    sku_map = {
        (a_id, c_id, s_id): sku_id
        for sku_id, a_id, c_id, s_id in sku_rows.all()
    }

    # NSC stock per SKU
    sku_ids = list(sku_map.values())
    nsk_by_sku: dict[int, int] = {}
    if sku_ids:
        rows = (
            db.query(StockBalance.sku_unit_id, func.coalesce(func.sum(StockBalance.quantity), 0))
            .filter(StockBalance.sku_unit_id.in_(sku_ids))
            .group_by(StockBalance.sku_unit_id)
            .all()
        )
        nsk_by_sku = {sku_id: int(qty) for sku_id, qty in rows}

    days_until_arrival = max((payload.wb_arrival_date - payload.target_date).days, 0)

    # First pass: compute base recommendation per SKU (before article cap)
    per_key_data = []
    article_total_deficit: dict[int, int] = defaultdict(int)

    strategy = payload.replenishment_strategy
    if strategy == "aggressive":
        coverage_factor = 1.0
    elif strategy == "conservative":
        coverage_factor = 0.6
    else:
        coverage_factor = 0.8

    for key, s in key_to_stats.items():
        article_id, color_id, size_id = key
        sku_unit_id = sku_map.get(key)
        nsk_stock_available = nsk_by_sku.get(sku_unit_id or -1, 0)

        wb_stock_total = s.wb_stock_total
        avg = s.avg_daily_sales_30d

        # Current coverage
        if avg > 0:
            coverage_current = float(wb_stock_total) / float(avg)
        else:
            coverage_current = 9999.0 if wb_stock_total > 0 else 0.0

        # Projection to arrival
        forecast_to_arrival = avg * float(days_until_arrival)
        projected_stock_at_arrival = max(wb_stock_total - int(forecast_to_arrival), 0)

        if avg > 0:
            projected_coverage_at_arrival = (
                float(projected_stock_at_arrival) / float(avg)
            )
        else:
            projected_coverage_at_arrival = coverage_current

        # Base required replenishment to reach target coverage
        required_stock_at_arrival = (
            avg * float(payload.target_coverage_days) * coverage_factor
        )
        base_required = max(int(required_stock_at_arrival - projected_stock_at_arrival), 0)

        # Zero-sales policy
        ignored_due_to_zero_sales = False
        if avg == 0.0:
            if payload.zero_sales_policy == "ignore":
                recommended = 0
                ignored_due_to_zero_sales = True
            else:  # "keep" or "light" for v1
                recommended = 0
                ignored_due_to_zero_sales = False
        else:
            recommended = base_required

        # Limit by NSC stock
        limited_by_nsk_stock = False
        if nsk_stock_available <= 0:
            recommended = 0
            limited_by_nsk_stock = False
        elif recommended > nsk_stock_available:
            recommended = nsk_stock_available
            limited_by_nsk_stock = True

        limited_by_max_coverage = False

        # Limit by max coverage after transfer (per-SKU, before article cap)
        if avg > 0 and recommended > 0:
            stock_after = projected_stock_at_arrival + recommended
            coverage_after = float(stock_after) / float(avg)
            if coverage_after > payload.max_coverage_days_after:
                allowed_stock = avg * float(payload.max_coverage_days_after)
                allowed_repl = max(int(allowed_stock - projected_stock_at_arrival), 0)
                if allowed_repl < recommended:
                    recommended = allowed_repl
                    limited_by_max_coverage = True

        # Aggregate deficit per article (before NSC/coverage caps)
        article_total_deficit[article_id] += base_required

        per_key_data.append(
            {
                "key": key,
                "stats": s,
                "sku_unit_id": sku_unit_id,
                "nsk_stock_available": nsk_stock_available,
                "wb_stock_total": wb_stock_total,
                "avg": avg,
                "coverage_current": coverage_current,
                "projected_stock_at_arrival": projected_stock_at_arrival,
                "projected_coverage_at_arrival": projected_coverage_at_arrival,
                "base_required": base_required,
                "recommended": max(int(recommended), 0),
                "limited_by_nsk_stock": limited_by_nsk_stock,
                "limited_by_max_coverage": limited_by_max_coverage,
                "ignored_due_to_zero_sales": ignored_due_to_zero_sales,
            }
        )

    # Second pass: apply article-level cap if needed
    if payload.max_replenishment_per_article is not None:
        max_per_article = payload.max_replenishment_per_article
        for article_id, keys in article_to_keys.items():
            # Collect rows for article
            rows = [r for r in per_key_data if r["key"][0] == article_id]
            total_rec = sum(r["recommended"] for r in rows)
            if total_rec > max_per_article and total_rec > 0:
                factor = float(max_per_article) / float(total_rec)
                for r in rows:
                    new_qty = int(r["recommended"] * factor)
                    if new_qty < r["recommended"]:
                        r["recommended"] = new_qty
                        r["limited_by_max_coverage"] = True

    # Third pass: build response items
    article_total_recommended: dict[int, int] = defaultdict(int)
    for r in per_key_data:
        article_total_recommended[r["key"][0]] += r["recommended"]

    items: list[WbReplenishmentItem] = []

    for r in per_key_data:
        s = r["stats"]
        article_id, color_id, size_id = r["key"]
        avg = r["avg"]
        wb_stock_total = r["wb_stock_total"]
        coverage_current = r["coverage_current"]
        projected_stock_at_arrival = r["projected_stock_at_arrival"]
        nsk_stock_available = r["nsk_stock_available"]
        recommended = r["recommended"]

        if avg > 0:
            if recommended > 0:
                coverage_after = float(projected_stock_at_arrival + recommended) / float(avg)
            else:
                coverage_after = float(projected_stock_at_arrival) / float(avg)
        else:
            coverage_after = coverage_current

        nsk_after = max(nsk_stock_available - recommended, 0)

        oos_risk_before = _compute_oos_risk(wb_stock_total, avg, coverage_current)
        oos_risk_after = _compute_oos_risk(
            projected_stock_at_arrival + recommended,
            avg,
            coverage_after,
        )

        below_min_coverage_threshold = coverage_current < float(payload.min_coverage_days)

        explanation = None
        if payload.explanation:
            parts: list[str] = []
            parts.append(
                "Base metrics: "
                f"sales_30d={s.sales_30d}, avg_daily_sales_30d={avg:.3f}, wb_stock_total={wb_stock_total}, "
                f"coverage_current={coverage_current:.1f}, projected_stock_at_arrival={projected_stock_at_arrival}."
            )
            parts.append(
                "Strategy: "
                f"strategy={payload.replenishment_strategy}, target_coverage_days={payload.target_coverage_days}, "
                f"coverage_factor={coverage_factor:.2f}, base_required={r['base_required']}."
            )
            if r["limited_by_nsk_stock"]:
                parts.append(f"Limited by NSC stock (available={nsk_stock_available}).")
            if r["limited_by_max_coverage"]:
                parts.append(
                    f"Limited by coverage cap/max article replenishment (max_coverage_days_after={payload.max_coverage_days_after})."
                )
            if r["ignored_due_to_zero_sales"]:
                parts.append("Ignored due to zero sales policy.")
            parts.append(
                f"Final recommendation: recommended_qty={recommended}, coverage_after_transfer={coverage_after:.1f}, "
                f"nsk_stock_after_transfer={nsk_after}, oos_risk_before={oos_risk_before}, oos_risk_after={oos_risk_after}."
            )
            explanation = " ".join(parts)

        items.append(
            WbReplenishmentItem(
                article_id=s.article_id,
                article_code=s.article_code,
                color_id=s.color_id,
                color_inner_code=s.color_inner_code,
                size_id=s.size_id,
                size_label=s.size_label,
                wb_sku=s.wb_sku,
                wb_stock_total=wb_stock_total,
                avg_daily_sales_30d=avg,
                coverage_days_current=coverage_current,
                days_until_arrival=days_until_arrival,
                target_coverage_days=payload.target_coverage_days,
                projected_stock_at_arrival=projected_stock_at_arrival,
                projected_coverage_at_arrival=r["projected_coverage_at_arrival"],
                recommended_qty=recommended,
                coverage_after_transfer=coverage_after,
                nsk_stock_available=nsk_stock_available,
                nsk_stock_after_transfer=nsk_after,
                oos_risk_before=oos_risk_before,
                oos_risk_after=oos_risk_after,
                limited_by_nsk_stock=r["limited_by_nsk_stock"],
                limited_by_max_coverage=r["limited_by_max_coverage"],
                ignored_due_to_zero_sales=r["ignored_due_to_zero_sales"],
                below_min_coverage_threshold=below_min_coverage_threshold,
                article_total_deficit=article_total_deficit[article_id],
                article_total_recommended=article_total_recommended[article_id],
                explanation=explanation,
            )
        )

    return items
