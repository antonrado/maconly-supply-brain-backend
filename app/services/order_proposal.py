from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.models.models import (
    Article,
    PlanningSettings,
    SkuUnit,
    StockBalance,
    ColorPlanningSettings,
    ElasticPlanningSettings,
    Size,
)
from app.schemas.order_proposal import OrderProposalItem, OrderProposalResponse
from app.services.demand_engine import compute_demand


def generate_order_proposal(
    db: Session,
    target_date: date,
    explanation: bool = True,
) -> OrderProposalResponse:
    settings_list = db.query(PlanningSettings).all()

    items: list[OrderProposalItem] = []
    explanation_parts: list[str] = []

    if not settings_list:
        return OrderProposalResponse(
            target_date=target_date,
            items=[],
            global_explanation="No planning settings configured; no order proposal generated.",
        )

    for ps in settings_list:
        article = db.query(Article).filter(Article.id == ps.article_id).first()
        if article is None:
            if explanation:
                explanation_parts.append(
                    f"Article id={ps.article_id} referenced in PlanningSettings but not found; skipped."
                )
            continue

        if not ps.is_active:
            if explanation:
                explanation_parts.append(
                    f"Article {article.code} is inactive in planning; skipped from proposal."
                )
            continue

        sku_units = db.query(SkuUnit).filter(SkuUnit.article_id == article.id).all()
        if not sku_units:
            if explanation:
                explanation_parts.append(
                    f"Article {article.code}: no SKU units found; cannot build proposal."
                )
            continue

        # Group SKUs by color and collect size information
        color_to_skus: dict[int, list[SkuUnit]] = {}
        color_ids: set[int] = set()
        size_ids: set[int] = set()
        for sku in sku_units:
            color_to_skus.setdefault(sku.color_id, []).append(sku)
            color_ids.add(sku.color_id)
            size_ids.add(sku.size_id)

        sizes = db.query(Size).filter(Size.id.in_(size_ids)).all() if size_ids else []
        size_sort_order: dict[int, int] = {s.id: s.sort_order for s in sizes}

        # Color-level planning settings (fabric minima per color)
        color_settings = (
            db.query(ColorPlanningSettings)
            .filter(
                ColorPlanningSettings.article_id == article.id,
                ColorPlanningSettings.color_id.in_(color_ids) if color_ids else False,
            )
            .all()
        )
        color_min_batches: dict[int, int] = {
            cs.color_id: cs.fabric_min_batch_qty
            for cs in color_settings
            if cs.fabric_min_batch_qty is not None and cs.fabric_min_batch_qty > 0
        }

        # Elastic-level planning settings (simplified: use max elastic_min_batch_qty per article)
        elastic_settings = (
            db.query(ElasticPlanningSettings)
            .filter(ElasticPlanningSettings.article_id == article.id)
            .all()
        )
        elastic_min_batch = 0
        for es in elastic_settings:
            if (
                es.elastic_min_batch_qty is not None
                and es.elastic_min_batch_qty > elastic_min_batch
            ):
                elastic_min_batch = es.elastic_min_batch_qty

        # Step 1: WB-based deficit
        demand = compute_demand(
            db=db,
            article_id=article.id,
            target_date=target_date,
        )
        deficit_base = demand.deficit

        if deficit_base <= 0:
            if explanation:
                explanation_text = (
                    f"Article {article.code}: WB-based demand deficit is {deficit_base}; "
                    "no order suggested."
                )
                if demand.explanation:
                    explanation_text = explanation_text + " Details: " + demand.explanation
                explanation_parts.append(explanation_text)
            continue

        # Step 2: strictness scaling
        strict_factor = ps.strictness if ps.strictness > 0 else 1.0
        planned_total = int(deficit_base * strict_factor)
        if planned_total < deficit_base:
            planned_total = deficit_base

        # Step 3: article-level minima
        planned_total = max(
            planned_total,
            ps.min_fabric_batch,
            ps.min_elastic_batch,
        )
        planned_total_after_article_min = planned_total

        if planned_total_after_article_min <= 0:
            if explanation:
                explanation_parts.append(
                    f"Article {article.code}: planned_total after article minima is non-positive; skipped."
                )
            continue

        # Initial distribution by SKU (for deriving per-color totals)
        n_skus = len(sku_units)
        per_sku_base = planned_total_after_article_min // n_skus
        remainder = planned_total_after_article_min % n_skus

        sorted_skus_for_base = sorted(
            sku_units,
            key=lambda s: (size_sort_order.get(s.size_id, 0), s.id),
        )
        initial_sku_qty: dict[int, int] = {}
        for idx, sku in enumerate(sorted_skus_for_base):
            qty = per_sku_base + (1 if idx < remainder else 0)
            initial_sku_qty[sku.id] = qty

        # Color totals before applying color minima
        color_totals_before_min: dict[int, int] = {}
        for sku in sku_units:
            qty = initial_sku_qty.get(sku.id, 0)
            color_totals_before_min[sku.color_id] = (
                color_totals_before_min.get(sku.color_id, 0) + qty
            )

        color_totals: dict[int, int] = dict(color_totals_before_min)
        color_min_applied_info: list[str] = []

        # Step 4: apply color-level fabric minima
        for color_id, min_batch in color_min_batches.items():
            current = color_totals.get(color_id, 0)
            if current < min_batch:
                color_totals[color_id] = min_batch
                delta = min_batch - current
                color_min_applied_info.append(
                    f"color_id={color_id}: increased from {current} to {min_batch} (+{delta}) "
                    f"due to fabric_min_batch_qty"
                )

        total_after_color = sum(color_totals.values()) if color_totals else planned_total_after_article_min

        # Step 5: apply elastic minima per article (simplified per-article elastic type)
        elastic_applied = False
        total_before_elastic = total_after_color
        if elastic_min_batch and total_after_color < elastic_min_batch:
            delta_total = elastic_min_batch - total_after_color

            color_sum = total_after_color if total_after_color > 0 else 0
            if color_sum > 0 and color_totals:
                add_per_color: dict[int, int] = {}
                assigned = 0
                for color_id, total in color_totals.items():
                    share = total / color_sum if color_sum > 0 else 0.0
                    add = int(delta_total * share)
                    add_per_color[color_id] = add
                    assigned += add
                remainder_delta = delta_total - assigned
                for idx, color_id in enumerate(sorted(color_totals.keys())):
                    if idx >= remainder_delta:
                        break
                    add_per_color[color_id] += 1
                for color_id, add in add_per_color.items():
                    color_totals[color_id] = color_totals.get(color_id, 0) + add
            elif color_totals:
                # If somehow total_after_color is 0 but elastic_min_batch > 0, spread evenly across colors
                colors_list = sorted(color_totals.keys())
                base_add = delta_total // len(colors_list)
                rem_add = delta_total % len(colors_list)
                for idx, color_id in enumerate(colors_list):
                    extra = base_add + (1 if idx < rem_add else 0)
                    color_totals[color_id] = color_totals.get(color_id, 0) + extra

            elastic_applied = True

        planned_total_final = sum(color_totals.values()) if color_totals else planned_total_after_article_min

        # Final distribution per SKU within each color: equal per color, smaller sizes get remainder
        final_sku_qty: dict[int, int] = {}
        for color_id, skus_in_color in color_to_skus.items():
            total_color = color_totals.get(color_id, 0)
            if total_color <= 0 or not skus_in_color:
                for sku in skus_in_color:
                    final_sku_qty[sku.id] = 0
                continue

            base = total_color // len(skus_in_color)
            rem = total_color % len(skus_in_color)
            skus_sorted = sorted(
                skus_in_color,
                key=lambda s: (size_sort_order.get(s.size_id, 0), s.id),
            )
            for idx, sku in enumerate(skus_sorted):
                qty = base + (1 if idx < rem else 0)
                final_sku_qty[sku.id] = qty

        # Current internal stock for explanations
        balances = (
            db.query(StockBalance)
            .filter(StockBalance.sku_unit_id.in_([s.id for s in sku_units]))
            .all()
        )
        qty_by_sku: dict[int, int] = {b.sku_unit_id: b.quantity for b in balances}

        if explanation:
            explanation_text = (
                f"Article {article.code}: WB demand -> avg_daily_sales={demand.avg_daily_sales:.3f}, "
                f"forecast_horizon_days={demand.forecast_horizon_days}, "
                f"forecast_demand={demand.forecast_demand:.3f}, current_stock={demand.current_stock}, "
                f"coverage_days={demand.coverage_days:.3f}, deficit_base={deficit_base}; "
                f"strictness={ps.strictness}, article_min_fabric_batch={ps.min_fabric_batch}, "
                f"article_min_elastic_batch={ps.min_elastic_batch}, "
                f"planned_total_after_article_min={planned_total_after_article_min}, "
                f"planned_total_after_color_min={total_after_color}, "
                f"planned_total_final={planned_total_final}."
            )
            if color_min_applied_info:
                explanation_text += " Color minima applied: " + "; ".join(color_min_applied_info) + "."
            if elastic_min_batch:
                if elastic_applied:
                    explanation_text += (
                        f" Elastic minima applied: elastic_min_batch_qty={elastic_min_batch} "
                        f"increased total from {total_before_elastic} to {planned_total_final}."
                    )
                else:
                    explanation_text += (
                        f" Elastic minima not binding: elastic_min_batch_qty={elastic_min_batch}, "
                        f"current total={total_before_elastic}."
                    )
            if demand.explanation:
                explanation_text = explanation_text + " WB details: " + demand.explanation
            explanation_parts.append(explanation_text)

        for sku in sku_units:
            qty = final_sku_qty.get(sku.id, 0)
            if qty <= 0:
                continue

            item_expl: str | None = None
            if explanation:
                current_sku_qty = qty_by_sku.get(sku.id, 0)
                color_total_final = color_totals.get(sku.color_id, 0)
                item_expl = (
                    f"Article {article.code}, color_id={sku.color_id}, size_id={sku.size_id}: "
                    f"current internal stock {current_sku_qty}, planned additional {qty} "
                    f"within color_total={color_total_final} and article_total={planned_total_final} "
                    f"based on WB demand deficit {deficit_base} and applied minima."
                )

            items.append(
                OrderProposalItem(
                    article_id=sku.article_id,
                    color_id=sku.color_id,
                    size_id=sku.size_id,
                    quantity=qty,
                    explanation=item_expl,
                )
            )

    global_expl: str | None
    if explanation:
        if explanation_parts:
            global_expl = "; ".join(explanation_parts)
        else:
            global_expl = "No issues detected; no orders suggested."
    else:
        global_expl = None

    return OrderProposalResponse(
        target_date=target_date,
        items=items,
        global_explanation=global_expl,
    )
