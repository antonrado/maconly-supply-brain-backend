from __future__ import annotations

from typing import List, Set

from app.schemas.monitoring_metrics import MonitoringMetricMetadata, MonitoringMetricsResponse


def build_monitoring_metrics_catalog() -> MonitoringMetricsResponse:
    items: list[MonitoringMetricMetadata] = [
        MonitoringMetricMetadata(
            metric="risk_critical",
            category="risk",
            label="Critical risk articles",
            description="Number of articles in critical risk level in the bundle risk portfolio.",
            supports_alerts=True,
            supports_timeseries=True,
            used_in_status=True,
        ),
        MonitoringMetricMetadata(
            metric="risk_warning",
            category="risk",
            label="Warning risk articles",
            description="Number of articles in warning risk level in the bundle risk portfolio.",
            supports_alerts=True,
            supports_timeseries=True,
            used_in_status=True,
        ),
        MonitoringMetricMetadata(
            metric="risk_ok",
            category="risk",
            label="OK risk articles",
            description="Number of articles in OK risk level in the bundle risk portfolio.",
            supports_alerts=True,
            supports_timeseries=True,
            used_in_status=True,
        ),
        MonitoringMetricMetadata(
            metric="risk_overstock",
            category="risk",
            label="Overstock risk articles",
            description="Number of articles classified as overstock risk in the bundle risk portfolio.",
            supports_alerts=True,
            supports_timeseries=True,
            used_in_status=True,
        ),
        MonitoringMetricMetadata(
            metric="risk_no_data",
            category="risk",
            label="No-data risk articles",
            description="Number of articles with insufficient data to evaluate bundle risk.",
            supports_alerts=True,
            supports_timeseries=True,
            used_in_status=True,
        ),
        MonitoringMetricMetadata(
            metric="wb_accounts_active",
            category="integrations",
            label="Active WB accounts",
            description="Number of active Wildberries integration accounts configured in the system.",
            supports_alerts=True,
            supports_timeseries=True,
            used_in_status=True,
        ),
        MonitoringMetricMetadata(
            metric="ms_accounts_active",
            category="integrations",
            label="Active MoySklad accounts",
            description="Number of active MoySklad integration accounts configured in the system.",
            supports_alerts=True,
            supports_timeseries=True,
            used_in_status=True,
        ),
        MonitoringMetricMetadata(
            metric="articles_with_orders",
            category="orders",
            label="Articles with final orders",
            description="Number of articles that have a positive final order quantity in the current order portfolio.",
            supports_alerts=True,
            supports_timeseries=True,
            used_in_status=True,
        ),
        MonitoringMetricMetadata(
            metric="total_final_order_qty",
            category="orders",
            label="Total final order quantity",
            description="Total final order quantity summed across all articles in the current order portfolio.",
            supports_alerts=True,
            supports_timeseries=True,
            used_in_status=True,
        ),
    ]
    return MonitoringMetricsResponse(items=items)


def get_all_metrics() -> Set[str]:
    """Return a set of all metric names from the catalog."""
    catalog = build_monitoring_metrics_catalog()
    return {item.metric for item in catalog.items}


def get_timeseries_metrics() -> Set[str]:
    """Return a set of metrics that support timeseries."""
    catalog = build_monitoring_metrics_catalog()
    return {item.metric for item in catalog.items if item.supports_timeseries}


def get_alert_rule_metrics() -> Set[str]:
    """Return a set of metrics that support alerts."""
    catalog = build_monitoring_metrics_catalog()
    return {item.metric for item in catalog.items if item.supports_alerts}
