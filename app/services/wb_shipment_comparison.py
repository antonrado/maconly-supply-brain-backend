from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.schemas.planning_production_order import ProductionOrderProposalFromWbRequest
from app.schemas.wb_replenishment import WbReplenishmentItem
from app.schemas.wb_shipment import (
    WbShipmentProposalArticleComparison,
    WbShipmentProposalComparisonResponse,
    WbShipmentProposalComparisonScopeNormalization,
    WbShipmentProposalComparisonSummary,
    WbShipmentProposalComparisonRequest,
    WbShipmentProposalLineComparison,
)
from app.services.planning_production_order import build_production_order_proposal_from_wb
from app.services.wb_replenishment import compute_replenishment


def _map_target_date_to_planning_horizon_days(target_date: date) -> int:
    planning_horizon_days = (target_date - date.today()).days
    if planning_horizon_days < 1:
        return 1
    if planning_horizon_days > 365:
        return 365
    return planning_horizon_days


def _dedupe_article_ids(article_ids: list[int] | None) -> list[int]:
    if not article_ids:
        return []
    seen: set[int] = set()
    result: list[int] = []
    for article_id in article_ids:
        if article_id in seen:
            continue
        seen.add(article_id)
        result.append(int(article_id))
    return result


def _resolve_normalized_article_ids(
    payload: WbShipmentProposalComparisonRequest,
    replenishment_items: list[WbReplenishmentItem],
) -> tuple[list[int], str]:
    requested_article_ids = _dedupe_article_ids(payload.article_ids)
    if requested_article_ids:
        return requested_article_ids, "requested_article_ids"

    replenishment_article_ids: list[int] = []
    seen: set[int] = set()
    for item in replenishment_items:
        if item.article_id in seen:
            continue
        seen.add(item.article_id)
        replenishment_article_ids.append(int(item.article_id))
    return replenishment_article_ids, "replenishment_output_article_ids"


def _build_line_comparisons(
    *,
    article_id: int,
    replenishment_items: list[WbReplenishmentItem],
    canonical_lines: list[object],
) -> list[WbShipmentProposalLineComparison]:
    replenishment_map: dict[tuple[int, int | None, int | None], int] = {}
    for item in replenishment_items:
        replenishment_map[(item.article_id, item.color_id, item.size_id)] = int(item.recommended_qty)

    canonical_map: dict[tuple[int, int | None, int | None], int] = {}
    for line in canonical_lines:
        canonical_map[(line.article_id, line.color_id, line.size_id)] = int(line.recommended_qty)

    all_keys = sorted(
        set(replenishment_map.keys()) | set(canonical_map.keys()),
        key=lambda key: (key[0], key[1] if key[1] is not None else -1, key[2] if key[2] is not None else -1),
    )

    comparisons: list[WbShipmentProposalLineComparison] = []
    for _, color_id, size_id in all_keys:
        replenishment_qty = int(replenishment_map.get((article_id, color_id, size_id), 0))
        canonical_qty = int(canonical_map.get((article_id, color_id, size_id), 0))

        if replenishment_qty == canonical_qty:
            divergence_category = "aligned"
            explanation = "Replenishment and canonical recommendation quantities match for this line."
        elif replenishment_qty > 0 and canonical_qty == 0:
            divergence_category = "replenishment_only_line"
            explanation = "Current replenishment flow emits quantity for this line while canonical recommendation does not."
        elif replenishment_qty == 0 and canonical_qty > 0:
            divergence_category = "canonical_only_line"
            explanation = "Canonical recommendation emits quantity for this line while current replenishment flow does not."
        else:
            divergence_category = "qty_mismatch"
            explanation = "Both flows emit quantity for this line, but the quantities differ."

        comparisons.append(
            WbShipmentProposalLineComparison(
                article_id=article_id,
                color_id=color_id,
                size_id=size_id,
                replenishment_recommended_qty=replenishment_qty,
                canonical_recommended_qty=canonical_qty,
                divergence_category=divergence_category,
                explanation=explanation,
            )
        )

    return comparisons


def _build_blocked_article_comparison(
    *,
    article_id: int,
    replenishment_items: list[WbReplenishmentItem],
    blocker_detail: object,
) -> WbShipmentProposalArticleComparison:
    blocker_code = None
    blocker_message = None
    if isinstance(blocker_detail, dict):
        blocker_code = blocker_detail.get("code")
        blocker_message = blocker_detail.get("message")

    replenishment_total = sum(int(item.recommended_qty) for item in replenishment_items)
    explanation = (
        f"Canonical from-WB comparison for article_id={article_id} is blocked"
        if blocker_message is None
        else f"Canonical from-WB comparison for article_id={article_id} is blocked: {blocker_message}"
    )

    return WbShipmentProposalArticleComparison(
        article_id=article_id,
        replenishment_total_recommended_qty=replenishment_total,
        replenishment_line_count=len(replenishment_items),
        canonical_status="blocked",
        canonical_action=None,
        canonical_total_units=None,
        canonical_risk_level=None,
        canonical_arrival_projection_status=None,
        canonical_blocker_code=str(blocker_code) if blocker_code is not None else None,
        divergence_category="canonical_blocked",
        explanation=explanation,
        line_comparisons=[
            WbShipmentProposalLineComparison(
                article_id=item.article_id,
                color_id=item.color_id,
                size_id=item.size_id,
                replenishment_recommended_qty=int(item.recommended_qty),
                canonical_recommended_qty=0,
                divergence_category="replenishment_only_line",
                explanation="Canonical comparison is blocked, so only the replenishment quantity is available for this line.",
            )
            for item in replenishment_items
        ],
    )


def _has_constraint_divergence(response: object) -> bool:
    constraints_applied = getattr(response, "constraints_applied", None)
    if constraints_applied is None:
        return False
    if getattr(constraints_applied, "fabric_min_batches", None):
        return True
    if getattr(constraints_applied, "elastic_min_batches", None):
        return True
    if getattr(constraints_applied, "resource_allocation", None) is not None:
        return True
    return False


def _build_ok_article_comparison(
    *,
    article_id: int,
    replenishment_items: list[WbReplenishmentItem],
    canonical_response: object,
) -> WbShipmentProposalArticleComparison:
    recommendation = getattr(canonical_response, "recommendation", None)
    canonical_lines = [] if recommendation is None else list(getattr(recommendation, "lines", []))
    canonical_action = None if recommendation is None else getattr(recommendation, "action", None)
    canonical_total_units = 0 if recommendation is None else int(getattr(recommendation, "total_units", 0))
    canonical_risk_level = getattr(canonical_response, "risk_level", None)
    arrival_projection = getattr(canonical_response, "arrival_projection", None)
    arrival_projection_status = None if arrival_projection is None else getattr(arrival_projection, "status", None)

    replenishment_total = sum(int(item.recommended_qty) for item in replenishment_items)
    line_comparisons = _build_line_comparisons(
        article_id=article_id,
        replenishment_items=replenishment_items,
        canonical_lines=canonical_lines,
    )

    if replenishment_total == canonical_total_units and all(
        comparison.divergence_category == "aligned" for comparison in line_comparisons
    ):
        divergence_category = "aligned"
        explanation = "Current replenishment and canonical recommendation align for this article."
    elif replenishment_total > 0 and canonical_total_units == 0 and canonical_action == "wait":
        divergence_category = "canonical_wait_vs_replenishment_qty"
        explanation = (
            "Current replenishment flow emits transfer quantity, while canonical production-order recommendation resolves to wait."
        )
    elif replenishment_total > 0 and canonical_total_units == 0:
        divergence_category = "replenishment_only_qty"
        explanation = (
            "Current replenishment flow emits quantity for this article, while canonical recommendation emits no order lines."
        )
    elif replenishment_total == 0 and canonical_total_units > 0:
        divergence_category = "canonical_only_qty"
        explanation = (
            "Canonical recommendation emits order quantity for this article, while current replenishment flow emits none."
        )
    elif _has_constraint_divergence(canonical_response):
        divergence_category = "qty_mismatch_constraints"
        explanation = (
            "Quantities differ and canonical recommendation also applies constraint-layer adjustments that do not exist in the replenishment flow."
        )
    elif canonical_action is not None:
        divergence_category = "qty_mismatch_decision_policy"
        explanation = (
            f"Quantities differ after canonical decision policy resolves action='{canonical_action}'"
            f" with risk_level='{canonical_risk_level}' and arrival_projection_status='{arrival_projection_status}'."
        )
    else:
        divergence_category = "qty_mismatch"
        explanation = "Quantities differ between replenishment and canonical recommendation for this article."

    return WbShipmentProposalArticleComparison(
        article_id=article_id,
        replenishment_total_recommended_qty=replenishment_total,
        replenishment_line_count=len(replenishment_items),
        canonical_status="ok",
        canonical_action=canonical_action,
        canonical_total_units=canonical_total_units,
        canonical_risk_level=canonical_risk_level,
        canonical_arrival_projection_status=arrival_projection_status,
        canonical_blocker_code=None,
        divergence_category=divergence_category,
        explanation=explanation,
        line_comparisons=line_comparisons,
    )


def build_wb_shipment_proposal_comparison(
    db: Session,
    payload: WbShipmentProposalComparisonRequest,
) -> WbShipmentProposalComparisonResponse:
    replenishment_items = compute_replenishment(db=db, payload=payload)
    normalized_article_ids, normalization_strategy = _resolve_normalized_article_ids(
        payload=payload,
        replenishment_items=replenishment_items,
    )
    planning_horizon_days = _map_target_date_to_planning_horizon_days(payload.target_date)

    replenishment_by_article: dict[int, list[WbReplenishmentItem]] = defaultdict(list)
    for item in replenishment_items:
        replenishment_by_article[item.article_id].append(item)

    article_comparisons: list[WbShipmentProposalArticleComparison] = []
    for article_id in normalized_article_ids:
        article_replenishment_items = replenishment_by_article.get(article_id, [])
        canonical_request = ProductionOrderProposalFromWbRequest(
            article_id=article_id,
            planning_horizon_days=planning_horizon_days,
            explainability_mode="full",
            as_of_date=payload.target_date,
        )
        try:
            canonical_response = build_production_order_proposal_from_wb(
                db=db,
                request=canonical_request,
            )
        except HTTPException as exc:
            article_comparisons.append(
                _build_blocked_article_comparison(
                    article_id=article_id,
                    replenishment_items=article_replenishment_items,
                    blocker_detail=exc.detail,
                )
            )
            continue

        article_comparisons.append(
            _build_ok_article_comparison(
                article_id=article_id,
                replenishment_items=article_replenishment_items,
                canonical_response=canonical_response,
            )
        )

    divergence_counts = Counter(
        comparison.divergence_category
        for comparison in article_comparisons
        if comparison.divergence_category != "aligned"
    )
    divergence_summary = WbShipmentProposalComparisonSummary(
        has_divergence=any(comparison.divergence_category != "aligned" for comparison in article_comparisons),
        article_count=len(article_comparisons),
        divergent_article_count=sum(
            1 for comparison in article_comparisons if comparison.divergence_category != "aligned"
        ),
        categories=dict(sorted(divergence_counts.items())),
    )

    scope_notes = [
        "Canonical comparison runs ProductionOrderProposalFromWbRequest per article_id.",
        "Canonical planning_horizon_days is derived from target_date.",
        "Shipment coverage parameters are preserved only on the replenishment side and are not projected into canonical overrides.",
    ]
    if normalization_strategy == "replenishment_output_article_ids":
        scope_notes.append(
            "Because article_ids is omitted, canonical comparison scope is limited to article_ids emitted by the current replenishment result."
        )

    return WbShipmentProposalComparisonResponse(
        target_date=payload.target_date,
        wb_arrival_date=payload.wb_arrival_date,
        replenishment_items=replenishment_items,
        scope_normalization=WbShipmentProposalComparisonScopeNormalization(
            requested_article_ids=_dedupe_article_ids(payload.article_ids) or None,
            normalized_article_ids=normalized_article_ids,
            normalization_strategy=normalization_strategy,
            comparison_as_of_date=payload.target_date,
            canonical_planning_horizon_days=planning_horizon_days,
            notes=scope_notes,
        ),
        article_comparisons=article_comparisons,
        divergence_summary=divergence_summary,
    )
