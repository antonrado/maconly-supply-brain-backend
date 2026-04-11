from __future__ import annotations

from dataclasses import dataclass

from app.services.planning_production_order_settings_loading_application import (
    _SettingsLoadingApplicationResult,
)


@dataclass(frozen=True)
class _SettingsLoadingUnpackApplicationResult:
    article_settings: object
    planning_settings: object
    global_settings: object


def _apply_production_order_settings_loading_unpack(
    *,
    settings_loading_application: _SettingsLoadingApplicationResult,
) -> _SettingsLoadingUnpackApplicationResult:
    return _SettingsLoadingUnpackApplicationResult(
        article_settings=settings_loading_application.article_settings,
        planning_settings=settings_loading_application.planning_settings,
        global_settings=settings_loading_application.global_settings,
    )
