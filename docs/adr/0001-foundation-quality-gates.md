# ADR-0001: Foundation quality gates for a no-rework baseline

- Status: Accepted
- Date: 2026-02-24
- Deciders: Project owner + agent
- Related task(s): TASK #9 (platform foundation)

## Context

The project is moving from prototype behavior to production-grade delivery.
Without explicit quality gates, ownership rules, and release discipline, the team risks expensive rework while scaling planning logic.

## Decision

Adopt a mandatory foundation pack:

1. CI workflow with compile check and full test run on pushes/PRs.
2. Pull request template with explicit risk/migration/rollback sections.
3. CONTRIBUTING guide with Definition of Done.
4. CODEOWNERS policy file (owner handle to be finalized).
5. ADR process for significant architecture changes.
6. Release policy document with versioning, migration, and rollback rules.

## Options considered

1. Keep current ad-hoc process
   - Pros: zero setup work now.
   - Cons: high long-term inconsistency and rework risk.
2. Partial process (docs only, no CI gate)
   - Pros: low friction.
   - Cons: no automated enforcement.
3. Full foundation pack (chosen)
   - Pros: consistent delivery, faster reviews, safer releases.
   - Cons: initial setup cost.

## Consequences

- Positive:
  - Better predictability and review quality.
  - Lower risk of accidental contract/migration regressions.
  - Better onboarding for future contributors.
- Trade-offs:
  - PR process is stricter and slightly slower initially.
- Risks:
  - CODEOWNERS placeholder must be replaced with real GitHub owner/team.

## Implementation notes

- Add `.github/workflows/ci.yml`.
- Add `.github/pull_request_template.md`.
- Add `CONTRIBUTING.md`.
- Add `.github/CODEOWNERS` placeholder.
- Add `docs/adr/*` process files.
- Add `RELEASE_POLICY.md`.

Validation:

- CI pipeline executes on PR and `main` pushes.
- PR template appears on new pull requests.
- Team follows Definition of Done in active tasks.

## Supersedes / Superseded by

- Supersedes: none
- Superseded by: none
