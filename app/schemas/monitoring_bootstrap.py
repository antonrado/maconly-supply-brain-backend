from __future__ import annotations

from pydantic import BaseModel

from app.schemas.monitoring_metrics import MonitoringMetricsResponse
from app.schemas.monitoring_layout import MonitoringLayoutResponse
from app.schemas.monitoring_dashboard import MonitoringStatusResponse


class MonitoringBootstrapResponse(BaseModel):
    metrics: MonitoringMetricsResponse
    layout: MonitoringLayoutResponse
    status: MonitoringStatusResponse
