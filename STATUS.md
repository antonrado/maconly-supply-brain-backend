# STATUS – Maconly Supply Brain Backend

## Current Stage

Planning Core v1 — CONTRACT FIXED (stub) (Monitoring v1 is stable and verified in the current backend stack; Planning Core exposes schema-first stub endpoints without business logic).

## What works now

- Monitoring v1 endpoints under `/api/v1/planning/monitoring` (`/bootstrap`, `/status`, `/snapshot`, `/history`, `/timeseries`) return HTTP 200 with valid JSON when schema is up to date.
- Alembic migrations up to and including `0008_add_monitoring_alert_rules.py` are applied successfully at container startup.
- PostgreSQL database container (`db`) is running and healthy under Docker Compose.
- Background Monitoring Scheduler (APScheduler) is controlled by `MONITORING_SCHEDULER_ENABLED`, uses a PostgreSQL advisory lock to stay single-instance across backend containers, runs every 15 minutes and persists snapshots into `monitoring_snapshots`.
- Monitoring history and timeseries are populated from `monitoring_snapshots` and reflect the scheduler-produced records.
- Planning Core v1 exposes stub endpoints without business logic.

## What’s broken / missing

- Planning Core v1 business logic (demand/supply calculations, order proposals) and DB integration are not implemented yet; only domain skeleton and HTTP stub endpoints with structured JSON exist.
- Monitoring snapshot records do not carry an explicit version field for schema/metric evolution; versioning strategy is not defined.

## Next 3 tasks

- Define and implement real Planning Core v1 business logic (demand, supply, order proposal calculations) and connect it to the existing HTTP API surface.
- Decide on and implement a multi-instance scheduler strategy (single leader, external orchestrator or DB-level coordination).
- Design and introduce a versioning approach for monitoring snapshots if metric schema changes.

## Last verification

- Date: 2025-12-31
- Git state:
  - origin: `https://github.com/antonrado/maconly-supply-brain-backend.git`
  - branch: `main`
  - HEAD: `c0bbb93` (Document PowerShell-safe curl for Planning Core proposal)
- Commands:
  - `docker compose -f .\docker-compose.yml up -d --build`
  - `curl.exe -s http://localhost:8000/api/v1/planning/core/health`
  - `curl.exe -s -X POST "http://localhost:8000/api/v1/planning/core/proposal" -H "Content-Type: application/json" --data-binary "@test_request.json"`
  - `git log -1 --oneline`
- Result summary:
  - Planning Core v1 endpoints return HTTP 200 with structured JSON.
  - POST /planning/core/proposal accepts input parameters, validates ranges (7..365), and reflects them in response.
  - Response now includes non-empty lines with SKU recommendations (stub_logic).
  - Expected response fragment:
    ```json
    {
      "status": "ok",
      "proposal": {
        "version": "v1",
        "generated_at": "2025-12-30T18:48:44.086055Z",
        "inputs": {"sales_window_days": 30, "horizon_days": 90},
        "summary": {"total_skus": 2, "total_units": 150},
        "lines": [
          {"sku": "SKU-001", "recommended_units": 100, "reason": "stub_logic"},
          {"sku": "SKU-002", "recommended_units": 50, "reason": "stub_logic"}
        ]
      }
    }
    ```
  - PowerShell-safe curl methods avoid JSON quoting pitfalls.
