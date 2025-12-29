from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.models import (
    Article,
    ArticlePlanningSettings,
    ColorPlanningSettings,
    ElasticPlanningSettings,
    ElasticType,
    GlobalPlanningSettings,
    PlanningSettings,
)
from app.schemas.demand import DemandResult
from app.schemas.planning import BundleAvailabilityResponse
from app.schemas.order_explanation import OrderExplanationPortfolioResponse
from app.schemas.integrations import IntegrationsConfigSnapshot
from app.schemas.monitoring import MonitoringSnapshot
from app.schemas.monitoring_dashboard import MonitoringDashboardResponse, MonitoringStatusSummary, MonitoringStatusResponse
from app.schemas.monitoring_alert_rules_seed import MonitoringAlertRulesSeedResponse
from app.schemas.monitoring_metrics import MonitoringMetricsResponse
from app.schemas.monitoring_layout import MonitoringLayoutResponse
from app.schemas.monitoring_bootstrap import MonitoringBootstrapResponse
from app.schemas.article_dashboard import ArticleDashboardResponse
from app.schemas.monitoring_risk_focus import MonitoringTopRiskResponse
from app.schemas.monitoring_timeseries import MonitoringTimeseriesResponse
from app.schemas.monitoring_alerts import (
    ActiveAlertsResponse,
    AlertRuleCreate,
    AlertRuleListResponse,
    AlertRuleSchema,
    AlertRuleUpdate,
)
from app.schemas.monitoring_history import MonitoringSnapshotRecordSchema, MonitoringHistoryResponse
from app.schemas.article_bundle_snapshot import ArticleInventorySnapshot
from app.schemas.bundle_risk import BundleRiskPortfolioResponse
from app.schemas.planning_health import PlanningHealthPortfolioResponse
from app.schemas.planning_settings import (
    ArticlePlanningConfigSnapshot,
    ArticlePlanningSettingsExperimentalSnapshot,
    ArticlePlanningSettingsSnapshot,
    ColorPlanningSettingsSnapshot,
    ElasticPlanningSettingsSnapshot,
    GlobalPlanningSettingsExperimentalSnapshot,
    GlobalPlanningSettingsSnapshot,
    PlanningConfigSnapshotResponse,
    PlanningSettingsExperimentalSnapshot,
    PlanningSettingsSnapshot,
)
from app.services.article_bundle_snapshot import build_article_inventory_snapshot
from app.services.bundle_planning import calculate_bundle_availability
from app.services.bundle_risk import build_bundle_risk_portfolio
from app.services.demand_engine import compute_demand
from app.services.order_explanation import build_order_explanation_portfolio
from app.services.integrations_config import build_integrations_config_snapshot
from app.services.monitoring import build_monitoring_snapshot
from app.services.monitoring_history import (
    build_and_persist_monitoring_snapshot,
    get_monitoring_history,
)
from app.services.monitoring_alerts import evaluate_active_alerts
from app.services.monitoring_status import build_monitoring_status, build_monitoring_status_summary
from app.services.monitoring_timeseries import build_monitoring_timeseries
from app.services.monitoring_risk_focus import build_top_risky_articles
from app.services.monitoring_metrics import build_monitoring_metrics_catalog
from app.services.monitoring_layout import build_monitoring_layout
from app.services.monitoring_bootstrap import build_monitoring_bootstrap
from app.services.monitoring_alert_rules import (
    create_alert_rule,
    delete_alert_rule,
    list_alert_rules,
    update_alert_rule,
)
from app.services.monitoring_alert_rules_seed import seed_monitoring_alert_rules
from app.services.planning_health import build_planning_health_portfolio
from app.services.article_dashboard import build_article_dashboard


router = APIRouter()


@router.get(
    "/bundle-availability",
    response_model=BundleAvailabilityResponse,
)
def get_bundle_availability(
    article_id: int,
    bundle_type_id: int,
    warehouse_id: int,
    db: Session = Depends(get_db),
):
    return calculate_bundle_availability(
        db=db,
        article_id=article_id,
        bundle_type_id=bundle_type_id,
        warehouse_id=warehouse_id,
    )


@router.get(
    "/demand",
    response_model=DemandResult,
)
def get_demand(
    article_id: int,
    target_date: date,
    db: Session = Depends(get_db),
):
    return compute_demand(
        db=db,
        article_id=article_id,
        target_date=target_date,
    )


def _build_global_settings_snapshot(db: Session) -> GlobalPlanningSettingsSnapshot | None:
    gps = db.query(GlobalPlanningSettings).order_by(GlobalPlanningSettings.id).first()
    if gps is None:
        return None

    experimental = GlobalPlanningSettingsExperimentalSnapshot(
        default_lead_time_days=gps.default_lead_time_days,
        default_service_level_percent=gps.default_service_level_percent,
        default_fabric_min_batch_qty=gps.default_fabric_min_batch_qty,
        default_elastic_min_batch_qty=gps.default_elastic_min_batch_qty,
    )

    return GlobalPlanningSettingsSnapshot(
        default_target_coverage_days=gps.default_target_coverage_days,
        experimental=experimental,
    )


def _build_article_snapshot(db: Session, article: Article) -> ArticlePlanningConfigSnapshot:
    aps = (
        db.query(ArticlePlanningSettings)
        .filter(ArticlePlanningSettings.article_id == article.id)
        .first()
    )
    if aps is not None:
        aps_experimental = ArticlePlanningSettingsExperimentalSnapshot(
            include_in_planning=aps.include_in_planning,
            priority=aps.priority,
            lead_time_days=aps.lead_time_days,
            service_level_percent=aps.service_level_percent,
        )
        aps_snapshot = ArticlePlanningSettingsSnapshot(
            target_coverage_days=aps.target_coverage_days,
            experimental=aps_experimental,
        )
    else:
        aps_snapshot = None

    ps = (
        db.query(PlanningSettings)
        .filter(PlanningSettings.article_id == article.id)
        .first()
    )
    if ps is not None:
        ps_experimental = PlanningSettingsExperimentalSnapshot(
            alert_threshold_days=ps.alert_threshold_days,
            safety_stock_days=ps.safety_stock_days,
            notes=ps.notes,
        )
        ps_snapshot = PlanningSettingsSnapshot(
            is_active=ps.is_active,
            min_fabric_batch=ps.min_fabric_batch,
            min_elastic_batch=ps.min_elastic_batch,
            strictness=ps.strictness,
            experimental=ps_experimental,
        )
    else:
        ps_snapshot = None

    color_rows = (
        db.query(ColorPlanningSettings)
        .filter(ColorPlanningSettings.article_id == article.id)
        .all()
    )
    color_snapshots = [
        ColorPlanningSettingsSnapshot(
            color_id=row.color_id,
            fabric_min_batch_qty=row.fabric_min_batch_qty,
        )
        for row in color_rows
    ]

    elastic_rows = (
        db.query(ElasticPlanningSettings, ElasticType)
        .join(ElasticType, ElasticType.id == ElasticPlanningSettings.elastic_type_id)
        .filter(ElasticPlanningSettings.article_id == article.id)
        .all()
    )
    elastic_snapshots = [
        ElasticPlanningSettingsSnapshot(
            elastic_type_id=et.id,
            elastic_type_name=et.name,
            elastic_min_batch_qty=eps.elastic_min_batch_qty,
        )
        for eps, et in elastic_rows
    ]

    return ArticlePlanningConfigSnapshot(
        article_id=article.id,
        article_code=article.code,
        article_planning_settings=aps_snapshot,
        planning_settings=ps_snapshot,
        color_settings=color_snapshots,
        elastic_settings=elastic_snapshots,
    )


@router.get(
    "/config-snapshot",
    response_model=PlanningConfigSnapshotResponse,
)
def get_planning_config_snapshot(
    article_id: int | None = Query(
        default=None,
        description=(
            "Optional article id to filter by. "
            "If omitted, snapshot is returned for all articles with PlanningSettings.is_active = true."
        ),
    ),
    db: Session = Depends(get_db),
) -> PlanningConfigSnapshotResponse:
    """Return a read-only snapshot of planning settings used by demand and order proposal.

    The snapshot separates fields that are actually used in calculations from experimental ones.
    """

    global_snapshot = _build_global_settings_snapshot(db)

    articles: list[ArticlePlanningConfigSnapshot] = []

    if article_id is not None:
        article = db.query(Article).filter(Article.id == article_id).first()
        if article is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Article not found",
            )

        snapshot = _build_article_snapshot(db, article)

        if (
            snapshot.article_planning_settings is None
            and snapshot.planning_settings is None
            and not snapshot.color_settings
            and not snapshot.elastic_settings
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No planning settings found for this article",
            )

        articles.append(snapshot)
    else:
        ps_rows = (
            db.query(PlanningSettings, Article)
            .join(Article, Article.id == PlanningSettings.article_id)
            .filter(PlanningSettings.is_active.is_(True))
            .order_by(Article.id)
            .all()
        )
        for _ps, article in ps_rows:
            articles.append(_build_article_snapshot(db, article))

    return PlanningConfigSnapshotResponse(
        global_settings=global_snapshot,
        articles=articles,
    )


@router.get(
    "/article-bundle-snapshot",
    response_model=ArticleInventorySnapshot,
)
def get_article_bundle_snapshot(
    article_id: int,
    db: Session = Depends(get_db),
) -> ArticleInventorySnapshot:
    """Return a read-only snapshot of bundle-related inventory for a single article.

    The snapshot aggregates NSK singles, WB bundle stock and potential bundles from singles
    using existing bundle planning logic.
    """

    return build_article_inventory_snapshot(db=db, article_id=article_id)


@router.get(
    "/bundle-risk-portfolio",
    response_model=BundleRiskPortfolioResponse,
)
def get_bundle_risk_portfolio(
    article_ids: list[int] | None = Query(default=None),
    db: Session = Depends(get_db),
) -> BundleRiskPortfolioResponse:
    items = build_bundle_risk_portfolio(db=db, article_ids=article_ids)
    return BundleRiskPortfolioResponse(items=items)


@router.get(
    "/order-explanation-portfolio",
    response_model=OrderExplanationPortfolioResponse,
)
def get_order_explanation_portfolio(
    article_ids: list[int] | None = Query(default=None),
    db: Session = Depends(get_db),
) -> OrderExplanationPortfolioResponse:
    items = build_order_explanation_portfolio(db=db, article_ids=article_ids)
    return OrderExplanationPortfolioResponse(items=items)


@router.get(
    "/health-portfolio",
    response_model=PlanningHealthPortfolioResponse,
)
def get_planning_health_portfolio(
    article_ids: list[int] | None = Query(default=None),
    db: Session = Depends(get_db),
) -> PlanningHealthPortfolioResponse:
    items = build_planning_health_portfolio(db=db, article_ids=article_ids)
    return PlanningHealthPortfolioResponse(items=items)


@router.get(
    "/article-dashboard/{article_id}",
    response_model=ArticleDashboardResponse,
)
def get_article_dashboard(
    article_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
) -> ArticleDashboardResponse:
    dashboard = build_article_dashboard(db=db, article_id=article_id)
    if dashboard is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Article not found")
    return dashboard


@router.get(
    "/integrations/config-snapshot",
    response_model=IntegrationsConfigSnapshot,
)
def get_integrations_config_snapshot(
    db: Session = Depends(get_db),
) -> IntegrationsConfigSnapshot:
    return build_integrations_config_snapshot(db=db)


@router.get(
    "/monitoring/snapshot",
    response_model=MonitoringSnapshot,
)
def get_monitoring_snapshot(
    db: Session = Depends(get_db),
) -> MonitoringSnapshot:
    return build_monitoring_snapshot(db=db)


@router.post(
    "/monitoring/snapshot/capture",
    response_model=MonitoringSnapshotRecordSchema,
)
def capture_monitoring_snapshot(
    db: Session = Depends(get_db),
) -> MonitoringSnapshotRecordSchema:
    return build_and_persist_monitoring_snapshot(db=db)


@router.get(
    "/monitoring/history",
    response_model=MonitoringHistoryResponse,
)
def get_monitoring_history_api(
    limit: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db),
) -> MonitoringHistoryResponse:
    items = get_monitoring_history(db=db, limit=limit)
    return MonitoringHistoryResponse(items=items)


@router.get(
    "/monitoring/metrics",
    response_model=MonitoringMetricsResponse,
)
def get_monitoring_metrics() -> MonitoringMetricsResponse:
    return build_monitoring_metrics_catalog()


@router.get(
    "/monitoring/layout",
    response_model=MonitoringLayoutResponse,
)
def get_monitoring_layout() -> MonitoringLayoutResponse:
    return build_monitoring_layout()


@router.get(
    "/monitoring/bootstrap",
    response_model=MonitoringBootstrapResponse,
)
def get_monitoring_bootstrap(
    db: Session = Depends(get_db),
) -> MonitoringBootstrapResponse:
    return build_monitoring_bootstrap(db=db)


@router.get(
    "/monitoring/timeseries",
    response_model=MonitoringTimeseriesResponse,
)
def get_monitoring_timeseries(
    metrics: list[str] | None = Query(default=None),
    limit: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db),
) -> MonitoringTimeseriesResponse:
    if not metrics:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="metrics query parameter is required",
        )

    series = build_monitoring_timeseries(db=db, metrics=metrics, limit=limit)
    return MonitoringTimeseriesResponse(items=series)


@router.get(
    "/monitoring/risk-focus",
    response_model=MonitoringTopRiskResponse,
)
def get_monitoring_risk_focus(
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> MonitoringTopRiskResponse:
    items = build_top_risky_articles(db=db, limit=limit)
    return MonitoringTopRiskResponse(items=items)


@router.get(
    "/monitoring/alerts",
    response_model=ActiveAlertsResponse,
)
def get_active_alerts(
    db: Session = Depends(get_db),
) -> ActiveAlertsResponse:
    items = evaluate_active_alerts(db=db)
    return ActiveAlertsResponse(items=items)


@router.get(
    "/monitoring/status",
    response_model=MonitoringStatusResponse,
)
def get_monitoring_status(
    db: Session = Depends(get_db),
) -> MonitoringStatusResponse:
    return build_monitoring_status(db=db)


@router.get(
    "/monitoring/dashboard",
    response_model=MonitoringDashboardResponse,
)
def get_monitoring_dashboard(
    db: Session = Depends(get_db),
) -> MonitoringDashboardResponse:
    snapshot = build_monitoring_snapshot(db=db)
    history_items = get_monitoring_history(db=db, limit=30)
    alert_items = evaluate_active_alerts(db=db)
    rules = list_alert_rules(db=db)
    rule_items = [AlertRuleSchema.from_orm(rule) for rule in rules]

    status_response = build_monitoring_status(db=db)
    status_summary = MonitoringStatusSummary(
        overall_status=status_response.overall_status,
        critical_alerts=status_response.critical_alerts,
        warning_alerts=status_response.warning_alerts,
    )

    return MonitoringDashboardResponse(
        snapshot=snapshot,
        history=MonitoringHistoryResponse(items=history_items),
        alerts=ActiveAlertsResponse(items=alert_items),
        rules=AlertRuleListResponse(items=rule_items),
        status=status_summary,
    )


@router.get(
    "/monitoring/alert-rules",
    response_model=AlertRuleListResponse,
)
def get_alert_rules(
    db: Session = Depends(get_db),
) -> AlertRuleListResponse:
    rules = list_alert_rules(db=db)
    items = [AlertRuleSchema.from_orm(rule) for rule in rules]
    return AlertRuleListResponse(items=items)


@router.post(
    "/monitoring/alert-rules",
    response_model=AlertRuleSchema,
)
def create_alert_rule_api(
    payload: AlertRuleCreate,
    db: Session = Depends(get_db),
) -> AlertRuleSchema:
    rule = create_alert_rule(db=db, data=payload)
    return AlertRuleSchema.from_orm(rule)


@router.patch(
    "/monitoring/alert-rules/{rule_id}",
    response_model=AlertRuleSchema,
)
def update_alert_rule_api(
    rule_id: int,
    payload: AlertRuleUpdate,
    db: Session = Depends(get_db),
) -> AlertRuleSchema:
    rule = update_alert_rule(db=db, rule_id=rule_id, data=payload)
    if rule is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alert rule not found",
        )
    return AlertRuleSchema.from_orm(rule)


@router.delete(
    "/monitoring/alert-rules/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_alert_rule_api(
    rule_id: int,
    db: Session = Depends(get_db),
) -> None:
    deleted = delete_alert_rule(db=db, rule_id=rule_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alert rule not found",
        )
    return None


@router.post(
    "/monitoring/alert-rules/seed",
    response_model=MonitoringAlertRulesSeedResponse,
)
def seed_monitoring_alert_rules_endpoint(
    db: Session = Depends(get_db),
) -> MonitoringAlertRulesSeedResponse:
    created_ids, skipped_ids = seed_monitoring_alert_rules(db=db)
    return MonitoringAlertRulesSeedResponse(
        created_ids=created_ids,
        skipped_ids=skipped_ids,
    )
