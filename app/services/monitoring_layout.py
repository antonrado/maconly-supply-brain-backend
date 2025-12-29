from __future__ import annotations

from app.schemas.monitoring_layout import (
    MonitoringLayoutResponse,
    MonitoringLayoutSection,
    MonitoringLayoutTile,
)
from app.services.monitoring_metrics import get_all_metrics, get_timeseries_metrics


def build_monitoring_layout() -> MonitoringLayoutResponse:
    """Build a static, in-memory monitoring dashboard layout configuration.

    The layout describes sections and tiles and references existing monitoring
    endpoints and metric identifiers. It does not access the database or
    perform any business logic.
    """
    all_metrics = get_all_metrics()
    timeseries_metrics = get_timeseries_metrics()

    def _metric(name: str) -> str:
        if name not in all_metrics:
            raise ValueError(f"Unknown monitoring metric in layout: {name}")
        return name

    def _timeseries_metric(name: str) -> str:
        if name not in timeseries_metrics:
            raise ValueError(f"Metric {name} is not a valid timeseries metric")
        return name

    sections: list[MonitoringLayoutSection] = []

    # Status section (traffic light + counters from /monitoring/status)
    sections.append(
        MonitoringLayoutSection(
            id="status",
            title="Overall status",
            description="High-level monitoring status (traffic light and alert counters).",
            tiles=[
                MonitoringLayoutTile(
                    id="status_summary",
                    title="Monitoring status",
                    description="Overall monitoring status and alert counters.",
                    type="counter",
                    primary_metric=None,
                    secondary_metrics=None,
                    source_endpoint="/api/v1/planning/monitoring/status",
                    source_params=None,
                ),
            ],
        )
    )

    # Risk section
    sections.append(
        MonitoringLayoutSection(
            id="risk",
            title="Risk portfolio",
            description="Risk distribution and dynamics across articles/bundles.",
            tiles=[
                MonitoringLayoutTile(
                    id="risk_counters",
                    title="Risk level counters",
                    description="Current distribution of bundle risk levels.",
                    type="counter",
                    primary_metric=_metric("risk_critical"),
                    secondary_metrics=[
                        _metric("risk_warning"),
                        _metric("risk_ok"),
                        _metric("risk_overstock"),
                        _metric("risk_no_data"),
                    ],
                    source_endpoint="/api/v1/planning/monitoring/snapshot",
                    source_params=None,
                ),
                MonitoringLayoutTile(
                    id="risk_timeseries",
                    title="Critical risk timeseries",
                    description="Time series of critical-risk articles.",
                    type="timeseries",
                    primary_metric=_timeseries_metric("risk_critical"),
                    secondary_metrics=None,
                    source_endpoint="/api/v1/planning/monitoring/timeseries",
                    source_params={"metrics": ["risk_critical"], "limit": 30},
                ),
                MonitoringLayoutTile(
                    id="risk_top_articles",
                    title="Top risky articles",
                    description="Most risky articles by bundle risk model.",
                    type="table_link",
                    primary_metric=None,
                    secondary_metrics=None,
                    source_endpoint="/api/v1/planning/monitoring/risk-focus",
                    source_params={"limit": 20},
                ),
            ],
        )
    )

    # Integrations section
    sections.append(
        MonitoringLayoutSection(
            id="integrations",
            title="Integrations health",
            description="WB and MoySklad integration accounts status and trends.",
            tiles=[
                MonitoringLayoutTile(
                    id="integrations_counters",
                    title="Integration accounts counters",
                    description="Current number of active WB and MoySklad accounts.",
                    type="counter",
                    primary_metric=_metric("wb_accounts_active"),
                    secondary_metrics=[_metric("ms_accounts_active")],
                    source_endpoint="/api/v1/planning/monitoring/snapshot",
                    source_params=None,
                ),
                MonitoringLayoutTile(
                    id="integrations_timeseries",
                    title="Integrations activity timeseries",
                    description="Time series for active integration accounts.",
                    type="timeseries",
                    primary_metric=_timeseries_metric("wb_accounts_active"),
                    secondary_metrics=[_timeseries_metric("ms_accounts_active")],
                    source_endpoint="/api/v1/planning/monitoring/timeseries",
                    source_params={
                        "metrics": ["wb_accounts_active", "ms_accounts_active"],
                        "limit": 30,
                    },
                ),
            ],
        )
    )

    # Orders section
    sections.append(
        MonitoringLayoutSection(
            id="orders",
            title="Orders summary",
            description="Orders-related monitoring metrics and trends.",
            tiles=[
                MonitoringLayoutTile(
                    id="orders_counters",
                    title="Orders counters",
                    description="Current orders coverage and total ordered quantity.",
                    type="counter",
                    primary_metric=_metric("articles_with_orders"),
                    secondary_metrics=[_metric("total_final_order_qty")],
                    source_endpoint="/api/v1/planning/monitoring/snapshot",
                    source_params=None,
                ),
                MonitoringLayoutTile(
                    id="orders_timeseries",
                    title="Orders quantity timeseries",
                    description="Time series for total final order quantity.",
                    type="timeseries",
                    primary_metric=_timeseries_metric("total_final_order_qty"),
                    secondary_metrics=None,
                    source_endpoint="/api/v1/planning/monitoring/timeseries",
                    source_params={
                        "metrics": ["total_final_order_qty"],
                        "limit": 30,
                    },
                ),
            ],
        )
    )

    return MonitoringLayoutResponse(sections=sections)
