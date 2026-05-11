# RUNBOOK (WINDOWS / POWERSHELL)

## Repo root
```powershell
cd "C:\Users\USER\CascadeProjects\maconly-supply-brain-backend"
```

## Quick helper script (PowerShell)

Use helper commands from `scripts/dev.ps1`:

```powershell
.\scripts\dev.ps1 up
.\scripts\dev.ps1 ps
.\scripts\dev.ps1 logs
.\scripts\dev.ps1 health
.\scripts\dev.ps1 proposal
.\scripts\dev.ps1 mvp-first-analytics
.\scripts\dev.ps1 mvp-live-readiness
.\scripts\dev.ps1 po-api-smoke-positive
.\scripts\dev.ps1 po-api-smoke
.\scripts\dev.ps1 test
.\scripts\dev.ps1 context
.\scripts\dev.ps1 verify
.\scripts\dev.ps1 verify-live
.\scripts\dev.ps1 verify-mvp
.\scripts\dev.ps1 verify-mvp-reports
```

`proposal` now seeds deterministic smoke data inside the running backend container and calls the canonical `POST /api/v1/planning/core/production-order/proposal` happy path.

`mvp-first-analytics` starts a temporary host API on SQLite, seeds deterministic smoke data, calls the MVP analytics endpoints over HTTP, saves `seed_payloads.json`, `requests.json`, raw JSON responses under `artifacts/mvp_first_analytics/<timestamp>/`, and writes compact `summary.json` / `summary.md` files with input-file completeness, request metadata, the main first-analytics signals, and derived next actions.

`mvp-live-readiness` requires an already running backend at `http://localhost:8000`, calls only the local `POST /api/v1/wb/from-wb/readiness` endpoint, and writes `request.json`, `readiness.json`, `summary.json`, and `summary.md` under `artifacts/mvp_live_readiness/<timestamp>/`; summaries include input-file completeness. It does not call WB external sync endpoints.

Both MVP report summaries include `report_type`, `summary_schema_version`, `artifact_status`, `expected_input_file_count`, `present_input_file_count`, `missing_input_file_count`, `missing_input_files`, and `validation_messages` fields for downstream automation.

Current MVP summary schema version: `1.1`.

Static JSON Schema files for these payloads live at `schemas/reporting/mvp_first_analytics_summary.schema.json` and `schemas/reporting/mvp_live_readiness_summary.schema.json`.

Validate an existing MVP report summary against its schema contract with `python -m scripts.validate_mvp_report_summary_schema <report_dir-or-summary.json>`.

PowerShell shortcut: `.\scripts\dev.ps1 validate-mvp-summary -ReportPath <report_dir-or-summary.json>`.

Both `.\scripts\dev.ps1 mvp-first-analytics` and `.\scripts\dev.ps1 mvp-live-readiness` now run this schema validation automatically after writing `summary.json`.

Use `.\scripts\dev.ps1 verify-mvp-reports` to run a reproducible host-side artifact gate that generates both MVP reports and validates their summaries against the static schema contracts.

Optional targeting parameters for `mvp-live-readiness`:
```powershell
.\scripts\dev.ps1 mvp-live-readiness -ArticleId 123 -ReadinessLimit 20 -FreshnessSalesStaleAfterDays 3 -FreshnessStockStaleAfterDays 3
```

`po-api-smoke-positive` validates only deterministic positive live API checks:
- Auto-syncs backend image and waits for health readiness
- Seeds deterministic smoke fixture data
- `GET /api/v1/planning/core/health` -> `200`
- `POST /api/v1/planning/core/production-order/proposal` (happy-path payload) -> `200`
- `POST /api/v1/planning/core/production-order/proposal/from-wb` (happy-path payload) -> `200`
- `POST /api/v1/wb/manager/shipment/from-proposal/comparison` (happy-path payload) -> `200`

`po-api-smoke` validates live API connectivity for production-order routes with deterministic expected statuses:
- Auto-syncs backend image (`docker compose up -d --build backend`) and waits for running state
- `GET /api/v1/planning/core/health` -> `200`
- Seeds deterministic smoke fixture data via backend container (`scripts/po_api_smoke_seed.py`)
- `POST /api/v1/planning/core/production-order/proposal` (happy-path payload) -> `200`
- `POST /api/v1/planning/core/production-order/proposal/from-wb` (happy-path payload) -> `200`
- `POST /api/v1/wb/manager/shipment/from-proposal/comparison` (happy-path payload) -> `200`
- `POST /api/v1/planning/core/production-order/proposal` (unknown article) -> `404`
- `POST /api/v1/planning/core/production-order/proposal/from-wb` (unknown article) -> `404`
- `POST /api/v1/planning/core/production-order/proposal` (schema-invalid payload) -> `422`
- `POST /api/v1/planning/core/production-order/proposal/from-wb` (schema-invalid payload) -> `422`
- Also validates key response-body fragments (`"status":"ok"`, `"Article not found"`, validation field names)

## Git sanity checks
```powershell
git rev-parse --is-inside-work-tree
git status -sb
git log -1 --oneline
```

If you see `not a git repository`, you are in the wrong directory; switch to the repo root above.

## Docker sanity checks
```powershell
docker version
docker compose version
docker compose -f .\docker-compose.yml ps
```

### If Docker pipe error appears
Error pattern: `open //./pipe/dockerDesktopLinuxEngine: The system cannot find the file specified`.

Quick triage:
1. Start Docker Desktop.
2. Wait until engine is healthy.
3. Re-run:
```powershell
docker compose -f .\docker-compose.yml ps
```

## Start stack and inspect
```powershell
docker compose -f .\docker-compose.yml up -d --build
docker compose -f .\docker-compose.yml ps
docker compose -f .\docker-compose.yml logs --tail=200 backend
docker compose -f .\docker-compose.yml logs --tail=200 backend2
```

## Planning Core checks
### Health
```powershell
curl.exe -i http://localhost:8000/api/v1/planning/core/health
```

### Proposal (PowerShell-safe JSON)
Legacy stub endpoint example (`/api/v1/planning/core/proposal`, deprecated / low-fidelity):
```powershell
'{"sales_window_days":30,"horizon_days":90}' | Set-Content -Encoding utf8 -NoNewline test_request.json
```

Send request:
```powershell
curl.exe -i -X POST http://localhost:8000/api/v1/planning/core/proposal -H "Content-Type: application/json" --data-binary "@test_request.json"
```

Primary production-order path:
```powershell
curl.exe -i -X POST http://localhost:8000/api/v1/planning/core/production-order/proposal -H "Content-Type: application/json" --data-binary "@po_request.json"
```

## Monitoring snapshot count (DB)
```powershell
docker compose -f .\docker-compose.yml exec -T db psql -U maconly -d maconly_db -c "SELECT count(*) FROM monitoring_snapshots;"
```

## Pytest availability issue
If host shell shows `No module named pytest`, prefer one of:
1. Run tests inside Docker backend container.
2. Install dev dependencies in host Python environment.

## CI parity (local)
CI runs with:

- `DATABASE_URL=sqlite:///./ci.db`
- `MONITORING_SCHEDULER_ENABLED=false`

To mirror CI locally (host run):

```powershell
$env:DATABASE_URL = "sqlite:///./ci.db"
$env:MONITORING_SCHEDULER_ENABLED = "false"
python -m pytest -q
```

## Context guard (prevent losing project vector)

Run before opening PR:

```powershell
.\scripts\dev.ps1 context
```

Direct command variant:

```powershell
$base = git merge-base HEAD origin/main
if (-not $base) { $base = "HEAD~1" }
python .\scripts\context_guard.py --base $base --head HEAD
```

Guard policy summary:
- Runtime code changes require `STATUS.md` or `PROJECT_CANON.md` update.
- API/schema changes require `README.md` or `PROJECT_CANON.md` update.
- Planning-engine changes require one of `ROADMAP.md`, `STATUS.md`, `PROJECT_CANON.md` updates.

## One-command local verification

Run before opening PR (recommended):

```powershell
.\scripts\dev.ps1 verify
```

What `verify` does:
1. Runs context guard (`scripts/context_guard.py`).
2. Runs compile check (`python -m compileall app tests scripts alembic`).
3. Runs smoke tests:
   - host pytest (`python -m pytest`) when available, otherwise
   - docker backend pytest (`docker compose exec backend ...`) if backend is running.

If neither host pytest nor running backend container is available, `verify` fails fast with guidance.

## One-command local verification + live API gate

For a full local gate that includes deterministic live API checks for production-order endpoints:

```powershell
.\scripts\dev.ps1 verify-live
```

What `verify-live` does:
1. Runs everything in `verify` (context + compile + targeted production-order smoke tests).
2. Runs `po-api-smoke` (auto-sync backend image, seed deterministic smoke data, then assert 200/404/422 API contracts).

## One-command MVP verification

For the practical MVP gate that prefers live Docker API checks and falls back to a host SQLite API smoke when Docker is unavailable:

```powershell
.\scripts\dev.ps1 verify-mvp
```

What `verify-mvp` does:
1. Runs context guard.
2. Runs compile check.
3. Runs targeted smoke tests, including production-order and shipment-comparison regressions.
4. Runs deterministic API smoke for production-order direct/from-WB and WB shipment comparison.

## Interactive rebase / COMMIT_EDITMSG swap recovery
If Vim opens and reports a swap file for `.git/COMMIT_EDITMSG`:
1. If you do not need recovery, choose `D` (delete swap).
2. Save and close commit message editor.
3. Continue:
```powershell
git rebase --continue
```

Note: some Git versions do not support `git rebase --continue --no-edit`; use editor flow.
