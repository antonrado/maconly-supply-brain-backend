# ROADMAP

## Phase 0 - Monitoring reliability (completed)
- MonitoringScheduler integrated into app lifecycle.
- PostgreSQL advisory lock guard for single scheduler leader in multi-instance setup.
- Monitoring endpoints expanded with timeseries and risk-focus.

## Phase 1 - Planning Core v1 contract (in progress)
- Health endpoint returns 200.
- Proposal endpoint accepts validated request body and returns structured proposal.
- Inputs (`sales_window_days`, `horizon_days`) are echoed in response.
- Keep API contract stable while replacing placeholder logic incrementally.

## Phase 2 - Planning engine fundamentals
- Demand estimation module.
- Supply constraints (lead time, reorder point, MOQ).
- Deterministic recommendation rules and explainability fields.

## Phase 3 - Hardening and developer UX
- Docker-first test execution for environments without host `pytest`.
- PowerShell helper scripts for common workflows.
- Explicit OpenAPI stability notes for Planning Core endpoints.
- Clarify/document `backend2` purpose (lock-proof/e2e only).

## Immediate high-leverage follow-ups
1. Add a minimal `tests/` suite for Planning Core v1 (`health` + `proposal`) that runs in Docker.
2. Add a PowerShell helper script (Makefile-equivalent) for common commands (`up`, `ps`, `logs`, `health`, `proposal`, `tests`).
3. Add short `/api/v1/planning/core` OpenAPI stability notes in docs to keep schema guarantees explicit.
4. Either add Docker Compose profiles or explicitly document `backend2` as lock-proof/e2e-only service.

## Phase 4 - Optional productization
- Auth and access control.
- Multi-tenant boundaries.
- Packaging/operational controls for external use.
