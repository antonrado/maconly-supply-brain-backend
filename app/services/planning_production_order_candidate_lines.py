from __future__ import annotations

from app.schemas.planning_production_order import ProductionOrderRecommendationLine


def _build_candidate_lines(
    *,
    article_id: int,
    line_qty: dict[tuple[int, int], int],
    layer3_decision_by_line: dict[tuple[int, int], str],
) -> list[ProductionOrderRecommendationLine]:
    candidate_lines: list[ProductionOrderRecommendationLine] = []
    for (color_id, size_id), qty in sorted(
        line_qty.items(),
        key=lambda item: (item[0][0], item[0][1]),
    ):
        if qty <= 0:
            continue
        layer2_decision = layer3_decision_by_line.get((color_id, size_id), "main")
        candidate_lines.append(
            ProductionOrderRecommendationLine(
                article_id=article_id,
                color_id=color_id,
                size_id=size_id,
                recommended_qty=qty,
                source_reason=(
                    "deficit_plus_min_batch_alignment"
                    f"|layer2:{layer2_decision}"
                ),
            )
        )
    return candidate_lines
