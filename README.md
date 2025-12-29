# MACONLY Supply Brain Backend

This is a minimal backend scaffold for experimenting with the core MACONLY Supply Brain domain models and Alembic migrations.

## Setup

```bash
pip install -r requirements.txt
```

## Database

By default Alembic is configured to use a local SQLite database file:

```ini
sqlalchemy.url = sqlite:///./maconly_supply_brain.db
```

## Migrations

```bash
alembic revision --autogenerate -m "add core models"
alembic upgrade head
```

## Git & workflow

### Local initialization

```bash
git init
git add .
git commit -m "Initial commit"
```

### Connecting to a remote repository (GitHub / GitLab)

```bash
git remote add origin <YOUR_REPO_URL>
git push -u origin main
```

### Daily workflow

Before starting work:

```bash
git pull
```

After completing tasks:

```bash
git add .
git commit -m "TASK #X: short description"
git push
```

### Working from multiple machines (Windows / Mac)

- On the first machine:
  - initialize the repository and push it to the remote.
- On the second machine:

```bash
git clone <YOUR_REPO_URL>
```

Then before each work session run:

```bash
git pull
```

Notes:

- All changes performed by tools (including Windsurf) should be committed with meaningful messages.
- Resolve conflicts consciously; do not just overwrite remote or local changes blindly.

## WB Manager Public API

The backend exposes a small public API surface used by the WB Manager frontend under the common prefix:

- Base prefix: `/api/v1/wb/manager`

The main endpoints are:

- **Online dashboard**
  - `GET /online` — aggregated WB sales and stock metrics per SKU for a given `target_date`.

- **Shipments**
  - `GET /shipment/preset` — suggested parameters for a new shipment based on recent history.
  - `POST /shipment/from-proposal` — create a draft WB shipment from the current replenishment proposal.
  - `GET /shipment/headers` — paginated list of shipment headers with aggregate metrics.
  - `GET /shipment/{shipment_id}` — full shipment header and items for editing.
  - `GET /shipment/{shipment_id}/aggregates` — aggregate counters for a shipment.
  - `GET /shipment/{shipment_id}/items/{item_id}/summary` — detailed summary for a single shipment item.
  - `GET /shipment/status-list` — ordered list of allowed shipment statuses.
  - `PATCH /shipment/{shipment_id}` — update shipment status/comment (with status transition rules).
  - `PATCH /shipment/{shipment_id}/items/{item_id}` — update `final_qty`/`explanation` for an item in draft shipments.

Interactive API documentation is available via FastAPI:

- Swagger UI: `http://localhost:8000/docs`
- OpenAPI JSON: `http://localhost:8000/openapi.json`

## Planning & Bundles API

This backend also exposes read-only planning and bundle-related endpoints used for internal tooling and future UI work:

- Base prefix: `/api/v1/planning`

Main endpoints:

- `GET /demand` — WB-based demand metrics per article.
- `GET /order-proposal` — article/SKU-level purchase proposal based on WB demand and planning settings.
- `GET /bundle-availability` — number of bundles that can be assembled from NSC single-stock for a given article, bundle type and warehouse.
- `GET /article-bundle-snapshot` — article-level bundle & inventory snapshot for NSC/WB:
  - NSC single-SKU stock by color/size.
  - WB bundle stock by bundle type and size.
  - Potential bundles from NSC singles per bundle type (4/5/6 packs and others via recipes).
  - Aggregate bundle coverage per bundle type, including:
    - total available bundles (WB ready + NSC potential from singles),
    - avg_daily_sales (average WB bundle sales over the observation window),
    - days_of_cover (total_available_bundles / avg_daily_sales when avg_daily_sales > 0),
    - observation_window_days (length of the sales history window, currently 30 days).
- `GET /bundle-risk-portfolio` — bundle risk and alerts portfolio for WB manager/buyer:
  - Input: optional `article_ids` query parameter (`?article_ids=1&article_ids=2`).
  - Output: list of `ArticleBundleRiskEntry` items with days_of_cover, risk_level (`ok`/`warning`/`critical`/`overstock`/`no_data`) and human-readable explanations.
- `GET /order-explanation-portfolio` — per-article purchase proposal explanation portfolio grouped by article, returning `OrderExplanationPortfolioResponse` with `ArticleOrderExplanation` and nested `OrderProposalReason` items.
- `GET /health-portfolio` — unified planning health summary per article combining bundle risk and order explanation data; returns `PlanningHealthPortfolioResponse` with `ArticleHealthSummary` items (worst bundle risk level and bundle type, days_of_cover/avg_daily_sales/total_available_bundles, total_final_order_qty, dominant_limiting_constraint, and flags `has_critical`/`has_warning`).
- `GET /integrations/config-snapshot` — returns `IntegrationsConfigSnapshot` with configured WB and MoySklad integration accounts (multi-account support); exposes only IDs, human-readable names, optional `supplier_id`/`account_id` and `is_active` flags, but never API tokens.
- `GET /article-dashboard/{article_id}` — aggregated per-article dashboard that combines bundle risk, order explanation and planning health information for a single article; returns `ArticleDashboardResponse`.
- `GET /monitoring/snapshot` — returns `MonitoringSnapshot` aggregating key business signals for the main monitoring & alerts dashboard: integration status (WB/MS accounts), bundle risk level counts and order summary with `updated_at` timestamp; this endpoint is on-the-fly and does not persist data.
- `GET /monitoring/metrics` — returns [MonitoringMetricsResponse](cci:7://file:///c:/Users/USER/CascadeProjects/maconly-supply-brain-backend/app/schemas/monitoring_metrics.py:0:0-0:0) with a catalog of monitoring metrics (names, categories, descriptions and capability flags for alerts/timeseries/status).
- `GET /monitoring/layout` — returns [MonitoringLayoutResponse](cci:7://file:///c:/Users/USER/CascadeProjects/maconly-supply-brain-backend/app/schemas/monitoring_layout.py:0:0-0:0) with a static configuration of monitoring dashboard sections and tiles (references existing monitoring endpoints and metric identifiers).
- `GET /monitoring/bootstrap` — returns [MonitoringBootstrapResponse](cci:7://file:///c:/Users/USER/CascadeProjects/maconly-supply-brain-backend/app/schemas/monitoring_bootstrap.py:0:0-0:0) with an aggregated bootstrap payload for the monitoring dashboard (metrics catalog, layout configuration and current monitoring status, computed using the same logic as `GET /monitoring/status`).
- `GET /monitoring/history` — returns `MonitoringHistoryResponse` with a list of persisted monitoring snapshots (`MonitoringSnapshotRecordSchema`) for trend analysis; accepts `limit` query parameter (default 30, max 365) to control how many most recent records are returned.
- `POST /monitoring/snapshot/capture` — builds the current `MonitoringSnapshot`, stores it as a new `MonitoringSnapshotRecord` in the database and returns the saved record; intended for cron/automation to populate monitoring history.
 - `GET /monitoring/alerts` — returns `ActiveAlertsResponse` with currently triggered monitoring alerts based on `MonitoringAlertRule` rows and the latest monitoring snapshot (preferring persisted history, falling back to on-the-fly snapshot). Supported metrics include `risk_critical`, `risk_warning`, `risk_ok`, `risk_overstock`, `risk_no_data`, `wb_accounts_active`, `ms_accounts_active`, `articles_with_orders`, and `total_final_order_qty`; `threshold_type` is either `above` (current_value > threshold) or `below` (current_value < threshold), and `severity` is either `warning` or `critical`.
 - `GET /monitoring/alert-rules` — returns `AlertRuleListResponse` with all configured monitoring alert rules.
 - `POST /monitoring/alert-rules` — creates a new monitoring alert rule (`AlertRuleCreate` → `AlertRuleSchema`); validates `metric`, `threshold_type` (`above`/`below`), `severity` (`warning`/`critical`) and non-negative `threshold_value`.
- `PATCH /monitoring/alert-rules/{rule_id}` — partially updates an existing alert rule using `AlertRuleUpdate`; applies the same validation rules as for creation.
- `DELETE /monitoring/alert-rules/{rule_id}` — deletes an alert rule; subsequent updates or deletes for the same `rule_id` return 404. Active rules managed through this CRUD API are used by `GET /monitoring/alerts`.
- `POST /monitoring/alert-rules/seed` — admin endpoint that runs the internal alert rules seeder and returns [`MonitoringAlertRulesSeedResponse`](cci:7://file:///c:/Users/USER/CascadeProjects/maconly-supply-brain-backend/app/schemas/monitoring_alert_rules_seed.py:0:0-0:0) with created and skipped rule IDs.
- `GET /monitoring/dashboard` — returns `MonitoringDashboardResponse`, an aggregated monitoring dashboard that combines the on-the-fly `MonitoringSnapshot`, the last 30 history records (`MonitoringHistoryResponse`), currently active alerts (`ActiveAlertsResponse`) and the configured alert rules (`AlertRuleListResponse`). In addition, the response contains a `status` field (`MonitoringStatusSummary`) with an `overall_status` (one of `"ok"`, `"warning"`, `"critical"`) and the counts of currently active `critical_alerts` and `warning_alerts`, derived from the same alert evaluation logic as `GET /monitoring/alerts`. This endpoint is intended for frontend consumers that want to fetch all monitoring data with a single request.
 - `GET /monitoring/status` — returns `MonitoringStatusResponse` with fields `overall_status` (one of `"ok"`, `"warning"`, `"critical"`), `critical_alerts`, `warning_alerts` and `updated_at` (timestamp of the latest monitoring snapshot). This is a lightweight endpoint for health-checks and simple status indicators; `overall_status` is derived by a deterministic engine that first looks at active alerts (critical > warning) and, if there are none, at snapshot metrics (risks and integrations) before falling back to `"ok"`.
 - `GET /monitoring/timeseries` — returns `MonitoringTimeseriesResponse` with time series for selected monitoring metrics (for example `risk_critical`, `wb_accounts_active`, `total_final_order_qty`) built from `MonitoringSnapshotRecord` history. The `metrics` query parameter is required and defines which metrics to include; the optional `limit` parameter controls how many of the most recent snapshot records are used (default: 30). If there is no monitoring history, the response contains `items: []`.
 - `GET /monitoring/risk-focus` — returns `MonitoringTopRiskResponse` with a list of the most risky articles/bundles according to the existing bundle risk model. Items are sorted by risk severity (for example `critical` before `warning`, then other levels) and then by stable identifiers (article_id / bundle_type) to ensure deterministic ordering. The optional `limit` query parameter (default: 20) controls how many top items are returned.

## API Overview

For a consolidated overview of the Planning & Bundles and Monitoring & Alerts Hub HTTP API, see:

- [`docs/planning_monitoring_api.md`](cci:7://file:///c:/Users/USER/CascadeProjects/maconly-supply-brain-backend/docs/planning_monitoring_api.md:0:0-0:0)

## Seeding Monitoring Alert Rules

- The helper function `seed_monitoring_alert_rules(db: Session)` in `app.services.monitoring_alert_rules_seed` creates the baseline set of 9 monitoring alert rules described in the Monitoring & Alerts Hub section.
- The function is safe to call repeatedly: if a rule with the same `name`, `metric`, `threshold_type`, `threshold_value`, `severity` and `is_active` already exists, it is skipped and its ID is returned in the `skipped_rule_ids` list instead of creating a duplicate.
- The seeder is not invoked automatically by the application; it is intended to be called manually (for example from a one-off script or from an Alembic migration) to bootstrap monitoring alerts in a new environment.
