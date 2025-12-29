from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.models import MonitoringSnapshotRecord
from app.schemas.monitoring_timeseries import (
    MonitoringMetricPoint,
    MonitoringMetricSeries,
)
from app.services.monitoring_metrics import get_timeseries_metrics


SUPPORTED_METRICS = get_timeseries_metrics()


def build_monitoring_timeseries(
    db: Session,
    metrics: list[str],
    limit: int,
) -> list[MonitoringMetricSeries]:
    seen: set[str] = set()
    requested_metrics: list[str] = []
    for metric in metrics:
        if metric not in seen:
            seen.add(metric)
            requested_metrics.append(metric)

    filtered_metrics = [m for m in requested_metrics if m in SUPPORTED_METRICS]
    if not filtered_metrics:
        return []

    records = (
        db.query(MonitoringSnapshotRecord)
        .order_by(
            MonitoringSnapshotRecord.created_at.desc(),
            MonitoringSnapshotRecord.id.desc(),
        )
        .limit(limit)
        .all()
    )

    if not records:
        return []

    records = list(reversed(records))

    series_list: list[MonitoringMetricSeries] = []

    for metric in filtered_metrics:
        points = [
            MonitoringMetricPoint(
                timestamp=record.created_at,
                value=getattr(record, metric),
            )
            for record in records
        ]
        series_list.append(
            MonitoringMetricSeries(
                metric=metric,
                points=points,
            )
        )

    return series_list
