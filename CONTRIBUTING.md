# CONTRIBUTING

This repository is operated as a production-grade backend project.
The goal is predictable delivery with minimal rework.

## 1) Core principles

1. Keep API contracts stable unless a planned breaking change is approved.
2. Keep domain logic in services/core layers, not in FastAPI routers.
3. Keep changes deterministic and reproducible.
4. Prefer small, reviewable pull requests over large mixed changes.
5. Every non-trivial change must include tests and docs updates.

## 2) Branch and commit policy

- Branch from `main` using a task-focused name:
  - `feature/task-009-production-order-core`
  - `fix/monitoring-timeseries-ordering`
- Commit messages should be explicit:
  - `TASK #9: add production order proposal request schema`
  - `FIX: handle empty bundle recipe in planning service`

## 3) Pull request policy

Every PR should include:

1. Problem statement.
2. Scope of changes.
3. Risks and rollback plan.
4. Test evidence (commands + short raw output).
5. API contract impact (if any).
6. Migration impact (if any).

Use `.github/pull_request_template.md`.

## 4) Definition of Done (DoD)

A change is done only if all are true:

1. Acceptance criteria are satisfied.
2. Tests for the changed behavior exist and pass.
3. API/schema changes are reflected in docs.
4. If DB models changed, Alembic migration is present.
5. `STATUS.md` and canonical docs are updated if project-level behavior changed.

## 5) Testing expectations

### Local (preferred: Docker-first)

```powershell
docker compose -f .\docker-compose.yml up -d --build
docker compose -f .\docker-compose.yml exec -T backend python -m pytest -q
```

### Host fallback

```powershell
python -m pytest -q
```

If host env is missing dependencies, use Docker test execution.

## 6) Database and migration rules

- Never edit historical migration files that have been applied in shared environments.
- Every schema change must ship with a new Alembic migration.
- A migration must be reversible where practical.
- PR description must include migration risk and rollback note.

## 7) API contract rules

- Existing public endpoints must remain backward compatible.
- If a breaking change is unavoidable, introduce a new versioned endpoint.
- Include request/response examples in docs for new endpoints.

## 8) Security and secrets

- Never commit API keys, tokens, passwords, or `.env` secrets.
- Never expose integration tokens in API responses.
- Redact sensitive values in logs and screenshots.

## 9) Architecture decisions

For significant decisions (data model, planning algorithm policy, release process), add an ADR in `docs/adr/`.
Use `docs/adr/0000-template.md` as the template.

## 10) Context synchronization discipline (long-project safety)

This project uses event-driven context sync (not calendar-based sync).

Update docs in the same PR when one of these events happens:

1. Runtime behavior changed (`app/`, `alembic/`) -> update `STATUS.md` or `PROJECT_CANON.md`.
2. API/schema contract changed (`app/api/`, `app/schemas/`) -> update `README.md` or `PROJECT_CANON.md`.
3. Planning engine policy/logic changed (`app/core/planning/`, `app/services/planning_*`) -> update one of `ROADMAP.md`, `STATUS.md`, `PROJECT_CANON.md`.
4. Significant architecture/process decision changed -> add a new ADR in `docs/adr/`.

Automation:

- CI runs `scripts/context_guard.py` and fails PRs where code changes are not reflected in canonical docs.
- Keep doc notes short and explicit; one concise bullet is enough if behavior impact is small.
