from __future__ import annotations

from dataclasses import dataclass

from app.services.planning_production_order_settings_resolution_application import (
    _SettingsResolutionApplicationResult,
)


@dataclass(frozen=True)
class _SettingsResolutionUnpackApplicationResult:
    settings: object
    layer_proxy_settings: object
    economic_settings: object


def _apply_production_order_settings_resolution_unpack(
    *,
    settings_resolution_application: _SettingsResolutionApplicationResult,
) -> _SettingsResolutionUnpackApplicationResult:
    return _SettingsResolutionUnpackApplicationResult(
        settings=settings_resolution_application.settings,
        layer_proxy_settings=settings_resolution_application.layer_proxy_settings,
        economic_settings=settings_resolution_application.economic_settings,
    )
