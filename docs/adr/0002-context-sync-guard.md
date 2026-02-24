# ADR-0002: Event-driven context synchronization guard in CI

- Status: Accepted
- Date: 2026-02-24
- Deciders: Project owner + agent
- Related task(s): Platform governance hardening

## Context

The project is long-running and planning-sensitive.
Key risks, priorities, and decision context cannot live only in chat history.
Without automatic checks, code changes may drift from canonical docs (`STATUS.md`, `PROJECT_CANON.md`, `ROADMAP.md`, `README.md`) and the team can lose direction over time.

## Decision

Adopt event-driven context synchronization with automated CI enforcement:

1. Introduce `scripts/context_guard.py` to validate that code changes are reflected in canonical docs.
2. Run the guard in CI on PR/push before compile/tests.
3. Keep the guard deterministic and rules-based (no AI dependency).
4. Add local helper command (`scripts/dev.ps1 context`) so contributors can run the same check pre-PR.

## Options considered

1. Manual-only doc discipline
   - Pros: no tooling work.
   - Cons: high probability of missed context updates.
2. Calendar-based sync (e.g., weekly docs updates)
   - Pros: predictable schedule.
   - Cons: stale context between sync windows; weak fit for fast task loops.
3. Event-driven sync with CI guard (chosen)
   - Pros: immediate feedback, merge-time enforcement, minimal ambiguity.
   - Cons: stricter process; occasional false positives need quick doc notes.

## Consequences

- Positive:
  - Stronger protection against losing project vector and constraints.
  - Canon docs stay close to runtime reality.
  - New contributors can trust repo docs as source of truth.
- Trade-offs:
  - Slightly more PR overhead for small runtime changes.
- Risks:
  - Guard rules may initially be too strict or too loose.
  - Mitigation: tune rule scopes in `scripts/context_guard.py` as patterns emerge.

## Implementation notes

- Add `scripts/context_guard.py`.
- Update `.github/workflows/ci.yml` to execute the guard.
- Update `CONTRIBUTING.md`, `RUNBOOK.md`, PR template, and architecture canon with guard policy.

Validation:

- PR fails if runtime/API/planning code changes are not accompanied by canonical doc updates.
- Local check command works via `./scripts/dev.ps1 context`.

## Supersedes / Superseded by

- Supersedes: none
- Superseded by: none
