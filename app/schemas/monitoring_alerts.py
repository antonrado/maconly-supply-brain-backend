from __future__ import annotations

from pydantic import BaseModel, Field, validator

from app.services.monitoring_metrics import get_alert_rule_metrics


ALLOWED_METRICS = get_alert_rule_metrics()

ALLOWED_THRESHOLD_TYPES = {"above", "below"}
ALLOWED_SEVERITIES = {"warning", "critical"}


class AlertRuleSchema(BaseModel):
    id: int
    name: str

    metric: str
    threshold_type: str
    threshold_value: int

    severity: str
    is_active: bool

    class Config:
        orm_mode = True


class AlertRuleCreate(BaseModel):
    name: str

    metric: str
    threshold_type: str
    threshold_value: int = Field(ge=0)

    severity: str
    is_active: bool = True

    @validator("metric")
    def validate_metric(cls, value: str) -> str:  # noqa: D417
        if value not in ALLOWED_METRICS:
            allowed = ", ".join(sorted(ALLOWED_METRICS))
            raise ValueError(f"metric must be one of: {allowed}")
        return value

    @validator("threshold_type")
    def validate_threshold_type(cls, value: str) -> str:  # noqa: D417
        if value not in ALLOWED_THRESHOLD_TYPES:
            raise ValueError("threshold_type must be 'above' or 'below'")
        return value

    @validator("severity")
    def validate_severity(cls, value: str) -> str:  # noqa: D417
        if value not in ALLOWED_SEVERITIES:
            raise ValueError("severity must be 'warning' or 'critical'")
        return value


class AlertRuleUpdate(BaseModel):
    name: str | None = None
    metric: str | None = None
    threshold_type: str | None = None
    threshold_value: int | None = Field(default=None, ge=0)
    severity: str | None = None
    is_active: bool | None = None

    @validator("metric")
    def validate_metric(cls, value: str | None) -> str | None:  # noqa: D417
        if value is None:
            return value
        if value not in ALLOWED_METRICS:
            allowed = ", ".join(sorted(ALLOWED_METRICS))
            raise ValueError(f"metric must be one of: {allowed}")
        return value

    @validator("threshold_type")
    def validate_threshold_type(cls, value: str | None) -> str | None:  # noqa: D417
        if value is None:
            return value
        if value not in ALLOWED_THRESHOLD_TYPES:
            raise ValueError("threshold_type must be 'above' or 'below'")
        return value

    @validator("severity")
    def validate_severity(cls, value: str | None) -> str | None:  # noqa: D417
        if value is None:
            return value
        if value not in ALLOWED_SEVERITIES:
            raise ValueError("severity must be 'warning' or 'critical'")
        return value


class ActiveAlertSchema(BaseModel):
    rule_id: int
    name: str
    severity: str

    metric: str
    current_value: int
    threshold_type: str
    threshold_value: int


class ActiveAlertsResponse(BaseModel):
    items: list[ActiveAlertSchema]


class AlertRuleListResponse(BaseModel):
    items: list[AlertRuleSchema]
