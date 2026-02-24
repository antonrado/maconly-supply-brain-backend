# ARCHITECTURE CANON

## Architectural principles
1. **Stable API contracts**: breaking changes require explicit decision.
2. **Thin routers**: endpoint layer should wire HTTP only.
3. **Domain/services own logic**: planning and monitoring logic belongs in `app/core` and `app/services`.
4. **Deterministic operations**: prefer reproducible commands over screenshots or long logs.
5. **Single scheduler writer**: in multi-instance runtime, only one backend instance may run periodic monitoring capture.

## Repository layout
- `app/main.py` - FastAPI app wiring and lifecycle hooks.
- `app/api/v1` - HTTP routing/endpoints.
- `app/core/planning` - Planning Core domain contract and service interface/implementation.
- `app/services` - Monitoring/planning service logic and scheduler.
- `app/models` - SQLAlchemy models.
- `tests` - API/service tests.

## Monitoring scheduler invariant
- Scheduler is process-local APScheduler, started from FastAPI startup.
- Leadership is guarded via PostgreSQL advisory lock.
- Lock is acquired/released through a dedicated DB connection (`engine.raw_connection()`), so lock lifecycle is connection-scoped.

## Planning Core v1 invariant
- `/api/v1/planning/core/health` and `/api/v1/planning/core/proposal` remain available as contract-first endpoints.
- Request validation and response shape are stable; implementation may evolve behind the same contract.

## Verification philosophy
- Every substantial task should include command-level verification (PowerShell-safe).
- STATUS.md stores minimal raw outputs and exact commands for reproducibility.

## Engineering governance baseline
- CI gates run compile + automated tests on PR/push (`.github/workflows/ci.yml`).
- CI enforces context sync using `scripts/context_guard.py` (fails PR when runtime/API/planning changes are not reflected in canonical docs).
- PRs use a structured template with risk/migration/rollback sections.
- Definition of Done lives in `CONTRIBUTING.md`.
- Releases follow explicit policy in `RELEASE_POLICY.md`.
- Significant architectural decisions are captured in `docs/adr/`.
