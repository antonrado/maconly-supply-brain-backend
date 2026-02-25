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
.\scripts\dev.ps1 po-api-smoke
.\scripts\dev.ps1 test
.\scripts\dev.ps1 context
.\scripts\dev.ps1 verify
.\scripts\dev.ps1 verify-live
```

`po-api-smoke` validates live API connectivity for production-order routes with deterministic expected statuses:
- Auto-syncs backend image (`docker compose up -d --build backend`) and waits for running state
- `GET /api/v1/planning/core/health` -> `200`
- Seeds deterministic smoke fixture data via backend container (`scripts/po_api_smoke_seed.py`)
- `POST /api/v1/planning/core/production-order/proposal` (happy-path payload) -> `200`
- `POST /api/v1/planning/core/production-order/proposal/from-wb` (happy-path payload) -> `200`
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
Create body file:
```powershell
'{"sales_window_days":30,"horizon_days":90}' | Set-Content -Encoding utf8 -NoNewline test_request.json
```

Send request:
```powershell
curl.exe -i -X POST http://localhost:8000/api/v1/planning/core/proposal -H "Content-Type: application/json" --data-binary "@test_request.json"
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
1. Runs everything in `verify` (context + compile + tests).
2. Runs `po-api-smoke` (auto-sync backend image, seed deterministic smoke data, then assert 200/404/422 API contracts).

## Interactive rebase / COMMIT_EDITMSG swap recovery
If Vim opens and reports a swap file for `.git/COMMIT_EDITMSG`:
1. If you do not need recovery, choose `D` (delete swap).
2. Save and close commit message editor.
3. Continue:
```powershell
git rebase --continue
```

Note: some Git versions do not support `git rebase --continue --no-edit`; use editor flow.
