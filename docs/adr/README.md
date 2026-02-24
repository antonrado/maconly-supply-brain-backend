# ADR Index

ADR = Architecture Decision Record.

Use ADRs to capture significant technical decisions that affect:

- API compatibility,
- data model and migrations,
- planning algorithm policy,
- release and operational controls.

## Rules

1. Never rewrite accepted ADR history.
2. If a decision changes, create a new ADR that supersedes the old one.
3. Keep ADRs concise, explicit, and testable.

## Naming

- `0000-template.md` - template.
- `0001-<short-title>.md`, `0002-<short-title>.md`, ...

## Current ADRs

- `0001-foundation-quality-gates.md`
- `0002-context-sync-guard.md`
