from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, validator

from app.schemas.monitoring import MonitoringSnapshot
from app.schemas.monitoring_history import MonitoringHistoryResponse
from app.schemas.monitoring_alerts import ActiveAlertsResponse, AlertRuleListResponse


class MonitoringStatusSummary(BaseModel):
    overall_status: str
    critical_alerts: int
    warning_alerts: int

    @validator("overall_status")
    def validate_overall_status(cls, value: str) -> str:  # noqa: D417
        if value not in {"ok", "warning", "critical"}:
            raise ValueError("overall_status must be 'ok', 'warning' or 'critical'")
        return value


class MonitoringStatusResponse(BaseModel):
    overall_status: str
    critical_alerts: int
    warning_alerts: int
    updated_at: datetime

    @validator("overall_status")
    def validate_overall_status(cls, value: str) -> str:  # noqa: D417
        if value not in {"ok", "warning", "critical"}:
            raise ValueError("overall_status must be 'ok', 'warning' or 'critical'")
        return value


class MonitoringDashboardResponse(BaseModel):
    snapshot: MonitoringSnapshot
    history: MonitoringHistoryResponse
    alerts: ActiveAlertsResponse
    rules: AlertRuleListResponse
    status: MonitoringStatusSummary
