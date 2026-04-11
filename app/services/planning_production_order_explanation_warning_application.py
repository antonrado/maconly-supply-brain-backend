from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class _ExplanationWarningApplicationResult:
    explanation_warnings: list[dict[str, object]]


def _apply_production_order_explanation_warnings(
    *,
    economics_warnings: list[dict[str, object]],
    article_id: int,
    invalid_values_ignored: dict[str, object],
    threshold_order_adjusted: bool,
    accelerate_threshold_effective: float,
    unavoidable_threshold_effective: float,
    threshold_effective_source: str | None,
    arrival_projection_status: str,
    action: str,
    capital_constraint_summary: dict[str, object],
    projected_shortage_before_arrival: int,
    available_capital_effective: float,
    build_explanation_warnings: Callable[..., list[dict[str, object]]],
    build_layer_proxy_invalid_values_ignored_warning: Callable[..., dict[str, object]],
    build_layer5_threshold_clamped_warning: Callable[..., dict[str, object]],
    build_shortage_wait_blocked_by_capital_constraint_warning: Callable[..., dict[str, object]],
) -> _ExplanationWarningApplicationResult:
    explanation_warnings = build_explanation_warnings(
        economics_warnings=economics_warnings,
        article_id=article_id,
        invalid_values_ignored=invalid_values_ignored,
        threshold_order_adjusted=threshold_order_adjusted,
        accelerate_threshold_effective=accelerate_threshold_effective,
        unavoidable_threshold_effective=unavoidable_threshold_effective,
        threshold_effective_source=threshold_effective_source,
        arrival_projection_status=arrival_projection_status,
        action=action,
        capital_constraint_summary=capital_constraint_summary,
        projected_shortage_before_arrival=projected_shortage_before_arrival,
        available_capital_effective=available_capital_effective,
        build_layer_proxy_invalid_values_ignored_warning=(
            build_layer_proxy_invalid_values_ignored_warning
        ),
        build_layer5_threshold_clamped_warning=build_layer5_threshold_clamped_warning,
        build_shortage_wait_blocked_by_capital_constraint_warning=(
            build_shortage_wait_blocked_by_capital_constraint_warning
        ),
    )
    return _ExplanationWarningApplicationResult(
        explanation_warnings=explanation_warnings,
    )
