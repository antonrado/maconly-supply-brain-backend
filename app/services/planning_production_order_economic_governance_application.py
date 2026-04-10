from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from fastapi import HTTPException, status


@dataclass(frozen=True)
class _EconomicGovernanceApplicationResult:
    economic_settings: object
    economics_trust: dict[str, object]
    economics_warnings: list[dict[str, object]]
    capital_governance: dict[str, object]


def _apply_production_order_economic_governance(
    *,
    article_id: int,
    economic_settings: object,
    overrides: object | None,
    capital_governance_mode_strict: str,
    capital_governance_mode_safe_default: str,
    capital_governance_source_safe_default: str,
    build_available_capital_safe_default_warning: Callable[..., dict[str, object]],
    build_missing_available_capital_strict_detail: Callable[..., dict[str, object]],
    resolve_economic_trust_and_capital_governance: Callable[..., object],
) -> _EconomicGovernanceApplicationResult:
    economic_governance_resolution = resolve_economic_trust_and_capital_governance(
        article_id=article_id,
        economic_settings=economic_settings,
        overrides=overrides,
        capital_governance_mode_strict=capital_governance_mode_strict,
        capital_governance_mode_safe_default=capital_governance_mode_safe_default,
        capital_governance_source_safe_default=capital_governance_source_safe_default,
        build_available_capital_safe_default_warning=build_available_capital_safe_default_warning,
        build_missing_available_capital_strict_detail=build_missing_available_capital_strict_detail,
    )
    if economic_governance_resolution.missing_available_capital_detail is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=economic_governance_resolution.missing_available_capital_detail,
        )
    return _EconomicGovernanceApplicationResult(
        economic_settings=economic_governance_resolution.economic_settings,
        economics_trust=economic_governance_resolution.economics_trust,
        economics_warnings=economic_governance_resolution.economics_warnings,
        capital_governance=economic_governance_resolution.capital_governance,
    )
