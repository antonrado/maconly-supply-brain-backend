# MVP FIRST ANALYTICS RUNBOOK

## Goal

Get from a locally running backend to the first API-backed supply analytics output.
This MVP definition is intentionally practical: launch the backend, ingest or seed data, call the main API surfaces, and inspect planning/monitoring signals before broader ERP polish.

## MVP readiness target

Current backend readiness for this practical MVP is approximately **85%**:

- Planning/production-order engine is implemented and regression-covered.
- WB live-sync/readiness surfaces exist.
- Monitoring/alerts and risk-focused analytics surfaces exist.
- WB replenishment/shipment surfaces exist, with a comparison endpoint for checking current replenishment output against canonical production-order/from-WB behavior.
- Remaining work is mostly launch-path hardening, live data onboarding, and operator workflow tightening rather than building the core engine from scratch.

## Preconditions

- Docker Desktop is running.
- Repository root is the current working directory.
- Backend dependencies are available either on host Python or inside Docker.
- For live WB analytics, at least one active `wb_integration_accounts` row exists with a valid `api_token`.

## Start and verify backend

```powershell
.\scripts\dev.ps1 up
.\scripts\dev.ps1 health
```

Optional full local gate:

```powershell
.\scripts\dev.ps1 verify
```

Optional live API gate:

```powershell
.\scripts\dev.ps1 verify-live
```

Recommended practical MVP gate:

```powershell
.\scripts\dev.ps1 verify-mvp
```

Optional live-data readiness snapshot for an already running backend:

```powershell
.\scripts\dev.ps1 mvp-live-readiness
```

This command calls only the local `POST /api/v1/wb/from-wb/readiness` endpoint and does not call external WB sync endpoints.
For a specific article or smaller readiness sample:

```powershell
.\scripts\dev.ps1 mvp-live-readiness -ArticleId 123 -ReadinessLimit 20
```

## First analytics path

Example request payloads live under `examples/mvp_first_analytics/`.
Replace `article_id`, `bundle_type_ids`, `article_ids`, and dates with IDs/dates from your local or live dataset before using the examples against real data.

1. Check Planning Core health:

```powershell
curl.exe -i http://localhost:8000/api/v1/planning/core/health
```

2. Pull or refresh WB operational data:

```powershell
curl.exe -i -X POST http://localhost:8000/api/v1/wb/sales-daily/sync-live
curl.exe -i -X POST http://localhost:8000/api/v1/wb/stock/sync-live
curl.exe -i -X POST http://localhost:8000/api/v1/wb/commission/sync-live
curl.exe -i -X POST http://localhost:8000/api/v1/wb/supplies/sync-live
```

3. Discover/bootstrap article mapping if local articles are not aligned yet:

```powershell
curl.exe -i -X POST http://localhost:8000/api/v1/wb/article-mapping/discover-live
curl.exe -i -X POST http://localhost:8000/api/v1/wb/article-mapping/sync-live
```

4. Check from-WB production-order readiness:

```powershell
curl.exe -i -X POST http://localhost:8000/api/v1/wb/from-wb/readiness -H "Content-Type: application/json" --data-binary "@examples/mvp_first_analytics/readiness_request.json"
```

5. Run canonical production-order from WB data:

```powershell
curl.exe -i -X POST http://localhost:8000/api/v1/planning/core/production-order/proposal/from-wb -H "Content-Type: application/json" --data-binary "@examples/mvp_first_analytics/from_wb_proposal_request.json"
```

6. Inspect monitoring/risk analytics:

```powershell
curl.exe -i http://localhost:8000/api/v1/planning/monitoring/dashboard
curl.exe -i http://localhost:8000/api/v1/planning/monitoring/risk-focus
curl.exe -i "http://localhost:8000/api/v1/planning/monitoring/timeseries?metrics=risk_critical&metrics=risk_warning&metrics=total_final_order_qty"
```

7. Compare current WB shipment/replenishment proposal against canonical production-order/from-WB behavior:

```powershell
curl.exe -i -X POST http://localhost:8000/api/v1/wb/manager/shipment/from-proposal/comparison -H "Content-Type: application/json" --data-binary "@examples/mvp_first_analytics/shipment_comparison_request.json"
```

## First analytics outputs to inspect

- Articles or bundles with `critical` / `warning` risk.
- WB data readiness blockers and freshness status.
- Production-order recommendation action and total units.
- Arrival projection status: `safe_cover_until_arrival`, `shortage_before_arrival`, or `no_demand`.
- Layer 1-5 explanation meta and warnings.
- Shipment comparison divergence categories between current replenishment and canonical production-order behavior.

## MVP is not blocked by

- Full UI polish.
- ML forecasting.
- Global optimization solver.
- Finance/cash modules.
- Full multi-warehouse optimization.
- Broad ERP execution workflows.

## MVP is blocked by

- Backend not starting locally.
- Missing WB token for live-data mode.
- No local article/mapping/recipe data for from-WB proposals.
- Readiness returning only blockers with no operator remediation path.
- Full verification or focused smoke tests failing.
