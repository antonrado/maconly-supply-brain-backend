from __future__ import annotations

from datetime import date

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.models import (
    Article,
    Color,
    ColorPlanningSettings,
    ElasticPlanningSettings,
    ElasticType,
    PlanningSettings,
    SkuUnit,
    StockBalance,
)
from app.schemas.order_explanation import (
    ArticleOrderExplanation,
    OrderExplanationPortfolioResponse,
    OrderProposalReason,
)
from app.schemas.order_proposal import OrderProposalResponse
from app.services.demand_engine import compute_demand
from app.services.order_proposal import generate_order_proposal


def _resolve_article(db: Session, article_id: int) -> Article:
    article = db.query(Article).filter(Article.id == article_id).first()
    if article is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Article not found",
        )
    return article


def _load_colors_for_article(db: Session, article_id: int) -> dict[int, Color]:
    skus = db.query(SkuUnit).filter(SkuUnit.article_id == article_id).all()
    color_ids = {s.color_id for s in skus}
    if not color_ids:
        return {}
    colors = db.query(Color).filter(Color.id.in_(color_ids)).all()
    return {c.id: c for c in colors}


def _load_color_min_batches_for_article(db: Session, article_id: int) -> dict[int, int]:
    rows = (
        db.query(ColorPlanningSettings)
        .filter(ColorPlanningSettings.article_id == article_id)
        .all()
    )
    return {
        row.color_id: row.fabric_min_batch_qty
        for row in rows
        if row.fabric_min_batch_qty is not None and row.fabric_min_batch_qty > 0
    }


def _resolve_elastic_min_for_article(db: Session, article_id: int) -> tuple[int | None, ElasticType | None]:
    rows = (
        db.query(ElasticPlanningSettings, ElasticType)
        .join(ElasticType, ElasticType.id == ElasticPlanningSettings.elastic_type_id)
        .filter(ElasticPlanningSettings.article_id == article_id)
        .all()
    )
    if not rows:
        return None, None

    max_qty = 0
    chosen_type: ElasticType | None = None
    for eps, et in rows:
        if eps.elastic_min_batch_qty is not None and eps.elastic_min_batch_qty > max_qty:
            max_qty = eps.elastic_min_batch_qty
            chosen_type = et

    if max_qty <= 0:
        return None, None

    return max_qty, chosen_type


def _compute_total_available_before(db: Session, article_id: int) -> int:
    skus = db.query(SkuUnit).filter(SkuUnit.article_id == article_id).all()
    if not skus:
        return 0
    sku_ids = [s.id for s in skus]
    balances = (
        db.query(StockBalance)
        .filter(StockBalance.sku_unit_id.in_(sku_ids))
        .all()
    )
    return sum(b.quantity for b in balances)


def build_order_explanation_for_article(
    db: Session,
    article_id: int,
) -> ArticleOrderExplanation:
    article = _resolve_article(db, article_id)

    ps = (
        db.query(PlanningSettings)
        .filter(PlanningSettings.article_id == article.id)
        .first()
    )
    if ps is None:
        return ArticleOrderExplanation(article_id=article.id, article_code=article.code, reasons=[])

    target_date = date.today()

    demand = compute_demand(db=db, article_id=article.id, target_date=target_date)
    base_deficit = demand.deficit
    strictness = ps.strictness
    strict_factor = strictness if strictness > 0 else 1.0

    adjusted_deficit = float(base_deficit) * strict_factor

    if base_deficit > 0:
        proposed_qty = int(base_deficit * strict_factor)
        if proposed_qty < base_deficit:
            proposed_qty = base_deficit
    else:
        proposed_qty = 0

    min_fabric_batch = ps.min_fabric_batch if ps.min_fabric_batch > 0 else None
    min_elastic_batch_raw = ps.min_elastic_batch if ps.min_elastic_batch > 0 else None

    elastic_min_batch_from_type, elastic_type = _resolve_elastic_min_for_article(
        db=db,
        article_id=article.id,
    )

    if elastic_min_batch_from_type is not None:
        if min_elastic_batch_raw is None:
            min_elastic_batch_effective = elastic_min_batch_from_type
        else:
            min_elastic_batch_effective = max(
                min_elastic_batch_raw,
                elastic_min_batch_from_type,
            )
    else:
        min_elastic_batch_effective = min_elastic_batch_raw

    color_min_batches = _load_color_min_batches_for_article(db=db, article_id=article.id)

    internal_available = _compute_total_available_before(db=db, article_id=article.id)
    total_available_before = (demand.current_stock or 0) + internal_available

    proposal: OrderProposalResponse = generate_order_proposal(
        db=db,
        target_date=target_date,
        explanation=True,
    )

    article_items = [it for it in proposal.items if it.article_id == article.id]

    color_map = _load_colors_for_article(db=db, article_id=article.id)

    by_color_and_elastic: dict[tuple[int | None, int | None], int] = {}

    for it in article_items:
        elastic_type_id: int | None
        if elastic_type is not None:
            elastic_type_id = elastic_type.id
        else:
            elastic_type_id = None

        key = (it.color_id, elastic_type_id)
        by_color_and_elastic[key] = by_color_and_elastic.get(key, 0) + it.quantity

    reasons: list[OrderProposalReason] = []

    for (color_id, elastic_type_id), final_qty in by_color_and_elastic.items():
        if final_qty <= 0:
            continue

        color_name: str | None = None
        if color_id is not None and color_id in color_map:
            color_name = color_map[color_id].inner_code

        elastic_type_name: str | None = None
        if elastic_type is not None and elastic_type_id == elastic_type.id:
            elastic_type_name = elastic_type.name

        # Цветовая минималка для конкретного цвета
        color_min_batch: int | None = None
        if color_id is not None:
            color_min_batch = color_min_batches.get(color_id)

        # Определяем, какое ограничение было бутылочным горлышком
        limiting_constraint: str | None = None

        # Кандидаты-минималки по значению
        minima_candidates: list[tuple[str, int]] = []
        if min_fabric_batch is not None:
            minima_candidates.append(("fabric_min_batch", min_fabric_batch))
        if min_elastic_batch_effective is not None:
            minima_candidates.append(("elastic_min_batch", min_elastic_batch_effective))
        if color_min_batch is not None:
            minima_candidates.append(("color_min_batch", color_min_batch))

        if minima_candidates:
            # Берём минималку с наибольшим значением, которая не превышает фактический заказ
            applicable = [
                (name, value)
                for (name, value) in minima_candidates
                if final_qty >= value
            ]
            if applicable:
                name, value = max(applicable, key=lambda x: x[1])
                # Считаем минималку ограничивающей, если она выше, чем объём после strictness
                if value >= proposed_qty:
                    limiting_constraint = name

        # Если минималки не определены как ограничение, смотрим на strictness
        if limiting_constraint is None:
            if base_deficit > 0 and strict_factor != 1.0:
                # Если итоговый заказ близок к предложенному после strictness,
                # считаем, что ограничивает strictness
                if final_qty >= proposed_qty:
                    limiting_constraint = "strictness"
            else:
                limiting_constraint = "none"

        explanation_parts: list[str] = []
        explanation_parts.append(
            f"Article {article.code}, color_id={color_id}, elastic_type_id={elastic_type_id}: "
            f"base_deficit={base_deficit}, strictness={strictness}, adjusted_deficit={adjusted_deficit:.2f}."
        )
        explanation_parts.append(
            f"Minima: min_fabric_batch={min_fabric_batch}, min_elastic_batch={min_elastic_batch_effective}, "
            f"color_min_batch={color_min_batch}."
        )
        explanation_parts.append(
            f"Total_available_before={total_available_before}, forecast_horizon_days={demand.forecast_horizon_days}."
        )
        explanation_parts.append(
            f"Final_order_qty={final_qty}, limiting_constraint={limiting_constraint or 'none'}."
        )

        explanation_text = " ".join(explanation_parts)

        reasons.append(
            OrderProposalReason(
                article_id=article.id,
                article_code=article.code,
                color_id=color_id,
                color_name=color_name,
                elastic_type_id=elastic_type_id,
                elastic_type_name=elastic_type_name,
                proposed_qty=proposed_qty,
                base_deficit=base_deficit,
                strictness=strictness,
                adjusted_deficit=adjusted_deficit,
                min_fabric_batch=min_fabric_batch,
                min_elastic_batch=min_elastic_batch_effective,
                color_min_batch=color_min_batch,
                total_available_before=total_available_before,
                forecast_horizon_days=demand.forecast_horizon_days,
                final_order_qty=final_qty,
                limiting_constraint=limiting_constraint or "none",
                explanation=explanation_text,
            )
        )

    return ArticleOrderExplanation(
        article_id=article.id,
        article_code=article.code,
        reasons=reasons,
    )


def build_order_explanation_portfolio(
    db: Session,
    article_ids: list[int] | None = None,
) -> list[ArticleOrderExplanation]:
    target_article_ids: list[int]

    if article_ids is None:
        rows = (
            db.query(PlanningSettings.article_id)
            .filter(PlanningSettings.is_active.is_(True))
            .all()
        )
        target_article_ids = [row[0] for row in rows]
    else:
        seen: set[int] = set()
        target_article_ids = []
        for aid in article_ids:
            if aid not in seen:
                seen.add(aid)
                target_article_ids.append(aid)

    portfolio: list[ArticleOrderExplanation] = []

    for aid in target_article_ids:
        try:
            explanation = build_order_explanation_for_article(db=db, article_id=aid)
        except HTTPException as exc:  # type: ignore[py310-no-except-type-comments]
            if exc.status_code == status.HTTP_404_NOT_FOUND and exc.detail == "Article not found":
                continue
            raise

        portfolio.append(explanation)

    return portfolio
