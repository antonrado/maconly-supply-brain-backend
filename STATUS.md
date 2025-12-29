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
  - branch: `main` (multi-instance lock verification performed against this branch; feature branch used locally for changes)
  - HEAD: `b9e847c` (Make monitoring scheduler single-instance via pg advisory lock)
- Commands:
  - `docker compose -f .\docker-compose.yml up -d --build`
  - `docker compose -f .\docker-compose.yml ps`
  - `docker compose -f .\docker-compose.yml logs --tail=200 backend`
  - `docker compose -f .\docker-compose.yml logs --tail=200 backend2`
  - `docker compose -f .\docker-compose.yml exec db psql -U maconly maconly_db -c "select count(*) as snapshots_count, max(created_at) as last_snapshot from monitoring_snapshots;"`
  - `curl.exe -i http://localhost:8000/api/v1/planning/monitoring/status`
  - `curl.exe -i http://localhost:8001/api/v1/planning/monitoring/status`
- Result summary:
  - Both `backend` and `backend2` services are running against the same PostgreSQL database.
  - Logs show `backend` acquiring the advisory lock and starting the scheduler, while `backend2` logs `MonitoringScheduler disabled (PostgreSQL advisory lock not acquired)`.
  - Snapshot count in `monitoring_snapshots` continues to grow as expected for a single scheduler, not doubling with two backend instances.
  - Both monitoring status endpoints (`/api/v1/planning/monitoring/status`) on ports 8000 and 8001 return HTTP 200 with valid JSON.
- Date: 2025-12-29 (UTC+07)
