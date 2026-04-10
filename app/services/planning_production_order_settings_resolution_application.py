from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from app.models.models import ArticlePlanningSettings, GlobalPlanningSettings, PlanningSettings
from app.schemas.planning_production_order import PlanningOverridesInput
from app.services.planning_production_order_economics import _EffectiveEconomicSettings
from app.services.planning_production_order_layer_proxy import _EffectiveLayerProxySettings
from app.services.planning_production_order_settings import _EffectiveSettings


@dataclass(frozen=True)
class _SettingsResolutionApplicationResult:
    settings: _EffectiveSettings
    layer_proxy_settings: _EffectiveLayerProxySettings
    economic_settings: _EffectiveEconomicSettings


def _apply_production_order_settings_resolution(
    *,
    article_settings: ArticlePlanningSettings | None,
    planning_settings: PlanningSettings | None,
    global_settings: GlobalPlanningSettings | None,
    overrides: PlanningOverridesInput | None,
    runtime_economic_overrides: dict[str, float | None] | None,
    runtime_economic_source: str | None,
    runtime_economic_source_overrides: dict[str, str] | None,
    build_effective_settings: Callable[..., _EffectiveSettings],
    resolve_layer_proxy_settings: Callable[..., _EffectiveLayerProxySettings],
    resolve_economic_settings: Callable[..., _EffectiveEconomicSettings],
) -> _SettingsResolutionApplicationResult:
    settings = build_effective_settings(
        article_settings=article_settings,
        planning_settings=planning_settings,
        global_settings=global_settings,
        overrides=overrides,
    )
    layer_proxy_settings = resolve_layer_proxy_settings(
        article_settings=article_settings,
        global_settings=global_settings,
        overrides=overrides,
    )
    economic_settings = resolve_economic_settings(
        article_settings=article_settings,
        global_settings=global_settings,
        overrides=overrides,
        runtime_overrides=runtime_economic_overrides,
        runtime_source=runtime_economic_source,
        runtime_source_overrides=runtime_economic_source_overrides,
    )
    return _SettingsResolutionApplicationResult(
        settings=settings,
        layer_proxy_settings=layer_proxy_settings,
        economic_settings=economic_settings,
    )
