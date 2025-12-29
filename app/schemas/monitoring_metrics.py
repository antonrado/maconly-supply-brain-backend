from __future__ import annotations

from pydantic import BaseModel


class MonitoringMetricMetadata(BaseModel):
    metric: str
    category: str
    label: str
    description: str

    supports_alerts: bool
    supports_timeseries: bool
    used_in_status: bool


class MonitoringMetricsResponse(BaseModel):
    items: list[MonitoringMetricMetadata]
