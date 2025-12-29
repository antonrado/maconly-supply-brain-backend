# STATUS – Maconly Supply Brain Backend

## Current Stage

Planning Core v1 — NOT STARTED (Monitoring v1 is stable and verified in the current backend stack).

## What works now

- Monitoring v1 endpoints under `/api/v1/planning/monitoring` (`/bootstrap`, `/status`, `/snapshot`, `/history`, `/timeseries`) return HTTP 200 with valid JSON when schema is up to date.
- Alembic migrations up to and including `0008_add_monitoring_alert_rules.py` are applied successfully at container startup.
- PostgreSQL database container (`db`) is running and healthy under Docker Compose.
- Background Monitoring Scheduler (APScheduler) is controlled by `MONITORING_SCHEDULER_ENABLED`, uses a PostgreSQL advisory lock to stay single-instance across backend containers, runs every 15 minutes and persists snapshots into `monitoring_snapshots`.
- Monitoring history and timeseries are populated from `monitoring_snapshots` and reflect the scheduler-produced records.

## What’s broken / missing

- Planning Core v1 domain models and APIs are not implemented yet (stage explicitly marked as NOT STARTED).
- Monitoring snapshot records do not carry an explicit version field for schema/metric evolution; versioning strategy is not defined.

## Next 3 tasks

- Define and implement Planning Core v1 domain models, services and API surface (currently NOT STARTED).
- Decide on and implement a multi-instance scheduler strategy (single leader, external orchestrator or DB-level coordination).
- Design and introduce a versioning approach for monitoring snapshots if metric schema changes.

## Last verification

- Git state:
  - origin: `https://github.com/antonrado/maconly-supply-brain-backend.git`
  - branch: `main`
  - HEAD: `2d120b8`
- Commands:
  - `docker compose -f .\docker-compose.yml ps`
  - `curl.exe -i http://localhost:8000/api/v1/planning/monitoring/bootstrap`
  - `curl.exe -i http://localhost:8000/api/v1/planning/monitoring/status`
  - `curl.exe -i http://localhost:8000/api/v1/planning/monitoring/history`
- Date: 2025-12-29 (UTC+07)
