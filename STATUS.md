# STATUS - maconly-supply-brain-backend

## Current stage

Planning Core v1 contract is active, monitoring APIs are active, and scheduler single-instance guard is implemented in code.

## Implemented now (code-backed)

- FastAPI app mounts `api_router` under `/api/v1` and starts `MonitoringScheduler` on startup.
- Monitoring scheduler uses PostgreSQL advisory lock (`pg_try_advisory_lock` / `pg_advisory_unlock`) via a dedicated connection (`engine.raw_connection`) to keep one writer in multi-instance runtime.
- Monitoring API includes:
  - `GET /api/v1/planning/monitoring/timeseries`
  - `GET /api/v1/planning/monitoring/risk-focus`
- Tests exist for both new monitoring endpoints:
  - `tests/test_monitoring_timeseries_api.py`
  - `tests/test_monitoring_risk_focus_api.py`
- Planning Core v1 endpoints are mounted and return structured responses:
  - `GET /api/v1/planning/core/health`
  - `POST /api/v1/planning/core/proposal`
- Planning proposal service currently has minimal DB-backed hook: reads SKU rows and returns deterministic `lines` with `recommended_units=0` and `reason="data_hook_only"`.

## Known operational friction

- Running commands from a non-repo directory causes `not a git repository`.
- Docker Desktop engine may be unavailable (`dockerDesktopLinuxEngine` pipe error).
- Host Python may miss `pytest`; prefer Docker-based test runs or install dev deps.
- PowerShell JSON quoting can break curl payloads; file-based `--data-binary "@..."` is the safe default.

## Verification commands (PowerShell, reproducible)

```powershell
git status -sb
git log -1 --oneline
docker compose -f .\docker-compose.yml up -d --build
docker compose -f .\docker-compose.yml ps
docker compose -f .\docker-compose.yml logs --tail=200 backend
curl.exe -i http://localhost:8000/api/v1/planning/core/health
'{"sales_window_days":30,"horizon_days":90}' | Set-Content -Encoding utf8 -NoNewline test_request.json
curl.exe -i -X POST http://localhost:8000/api/v1/planning/core/proposal -H "Content-Type: application/json" --data-binary "@test_request.json"
docker compose -f .\docker-compose.yml exec -T db psql -U maconly -d maconly_db -c "SELECT count(*) FROM monitoring_snapshots;"
```

## Last verification

- Date: `2026-02-24 19:54:59 +07:00`
- Branch: `main`
- Last commit (`git log -1 --oneline`): `638d3e2 Add minimal Planning Core v1 proposal logic (non-empty response)`

### Minimal raw outputs

```text
$ git status -sb
## main...origin/main
 M app/core/planning/service.py
```

```text
$ docker compose -f .\docker-compose.yml up -d --build
unable to get image 'postgres:15': error during connect:
open //./pipe/dockerDesktopLinuxEngine: The system cannot find the file specified.
```

```text
$ docker compose -f .\docker-compose.yml ps
error during connect: open //./pipe/dockerDesktopLinuxEngine: The system cannot find the file specified.
```

```text
$ curl.exe -i http://localhost:8000/api/v1/planning/core/health
curl: (7) Failed to connect to localhost port 8000: Could not connect to server
```

```text
$ test_request.json body
{"sales_window_days":30,"horizon_days":90}
```

```text
$ curl.exe -i -X POST .../planning/core/proposal --data-binary "@test_request.json"
curl: (7) Failed to connect to localhost port 8000: Could not connect to server
```

```text
$ docker compose -f .\docker-compose.yml exec -T db psql ... "SELECT count(*) FROM monitoring_snapshots;"
error during connect: open //./pipe/dockerDesktopLinuxEngine: The system cannot find the file specified.
```

### Interpretation

- Command set is reproducible and PowerShell-safe.
- Current host state blocked full runtime/API verification because Docker engine was unavailable.
- Planning Core request-body validation flow remains defined and reproducible via the file-based curl method above.
