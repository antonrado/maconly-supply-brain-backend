from __future__ import annotations

from sqlalchemy.orm import Session

from app.schemas.monitoring_bootstrap import MonitoringBootstrapResponse
from app.services.monitoring_status import build_monitoring_status
from app.services.monitoring_layout import build_monitoring_layout
from app.services.monitoring_metrics import build_monitoring_metrics_catalog


def build_monitoring_bootstrap(db: Session) -> MonitoringBootstrapResponse:
    """Build a UI bootstrap payload for the monitoring dashboard.

    Aggregates:
    - metrics catalog (MonitoringMetricsResponse),
    - static layout configuration (MonitoringLayoutResponse),
    - current monitoring status (MonitoringStatusResponse) computed from
      the same DB-backed logic as GET /monitoring/status.
    """
    metrics = build_monitoring_metrics_catalog()
    layout = build_monitoring_layout()
    status = build_monitoring_status(db=db)

    return MonitoringBootstrapResponse(
        metrics=metrics,
        layout=layout,
        status=status,
    )
