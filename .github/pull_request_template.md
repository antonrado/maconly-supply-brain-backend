## Summary

- What problem does this PR solve?
- Why now?

## Scope

- What is included?
- What is explicitly out of scope?

## Risks

- Potential regressions:
- Operational risks:
- Data risks:

## Rollback plan

- How to rollback quickly if needed?

## Database / migrations

- [ ] No DB change
- [ ] DB schema changed and Alembic migration included
- Migration notes:

## API contract impact

- [ ] No API contract changes
- [ ] Backward-compatible API extension
- [ ] Breaking change (approved separately)
- Endpoint/schema notes:

## Verification evidence

Commands run:

```text
# paste commands
```

Raw output (short):

```text
# paste key outputs
```

## Checklist

- [ ] Code follows architecture rules (thin router, logic in services/core)
- [ ] Tests added/updated and passing
- [ ] Docs updated (`README`, canon docs, or task docs when relevant)
- [ ] Context sync done for behavior changes (`STATUS.md` and/or `PROJECT_CANON.md`)
- [ ] `scripts/context_guard.py` passes locally or CI guard is green
- [ ] No secrets/tokens added
- [ ] Change is scoped and reviewable
