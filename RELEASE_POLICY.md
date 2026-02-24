# RELEASE POLICY

This project uses an API-first release discipline.

## 1) Release types

1. Patch (`x.y.Z`)
   - Bug fixes, no contract breaks.
2. Minor (`x.Y.z`)
   - Backward-compatible endpoint/schema additions.
3. Major (`X.y.z`)
   - Breaking API or data-contract changes.

## 2) Preconditions for release

A release candidate is valid only if:

1. CI is green.
2. Migration status is known and documented.
3. Rollback procedure is documented.
4. Relevant docs are updated.
5. High-risk changes are linked to ADRs.
6. Context guard check is green (`scripts/context_guard.py` via CI).

## 3) API compatibility policy

- Existing endpoint contracts are stable by default.
- Breaking changes require:
  1. explicit approval,
  2. migration path,
  3. versioned endpoint strategy,
  4. communication in release notes.

## 4) Database migration policy

- Every schema change must include Alembic migration.
- Migration PR must include:
  - forward migration behavior,
  - rollback behavior,
  - runtime risk notes (lock time, data backfill, compatibility).

## 5) Rollback strategy

For every release, define:

1. Fast rollback condition (what metrics/errors trigger rollback).
2. Code rollback method (revert tag/commit).
3. Data rollback method (alembic downgrade or forward-fix plan if downgrade is unsafe).
4. Owner on duty.

## 6) Release checklist

- [ ] Version decided and tagged
- [ ] CI passed
- [ ] Migration reviewed
- [ ] Rollback plan approved
- [ ] API/docs updated
- [ ] Post-release verification commands prepared

## 7) Post-release verification (minimum)

```powershell
curl.exe -i http://localhost:8000/api/v1/planning/core/health
curl.exe -i http://localhost:8000/api/v1/planning/monitoring/status
```

Add task-specific verification commands for any new endpoint included in the release.
