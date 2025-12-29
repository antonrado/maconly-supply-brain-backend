from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class MonitoringMetricPoint(BaseModel):
    timestamp: datetime
    value: int


class MonitoringMetricSeries(BaseModel):
    metric: str
    points: list[MonitoringMetricPoint]


class MonitoringTimeseriesResponse(BaseModel):
    items: list[MonitoringMetricSeries]
