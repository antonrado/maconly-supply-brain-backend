from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.models import (
    ArticlePlanningSettings,
    GlobalPlanningSettings,
    PlanningSettings,
)


@dataclass(frozen=True)
class _SettingsLoadingApplicationResult:
    article_settings: ArticlePlanningSettings | None
    planning_settings: PlanningSettings | None
    global_settings: GlobalPlanningSettings | None


def _apply_production_order_settings_loading(
    *,
    db: Session,
    article_id: int,
) -> _SettingsLoadingApplicationResult:
    article_settings = (
        db.query(ArticlePlanningSettings)
        .filter(ArticlePlanningSettings.article_id == article_id)
        .first()
    )
    planning_settings = (
        db.query(PlanningSettings)
        .filter(PlanningSettings.article_id == article_id)
        .first()
    )
    global_settings = (
        db.query(GlobalPlanningSettings).order_by(GlobalPlanningSettings.id).first()
    )
    return _SettingsLoadingApplicationResult(
        article_settings=article_settings,
        planning_settings=planning_settings,
        global_settings=global_settings,
    )
