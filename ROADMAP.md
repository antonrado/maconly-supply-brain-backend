# ROADMAP

## Phase 0 - Monitoring reliability (completed)
- MonitoringScheduler integrated into app lifecycle.
- PostgreSQL advisory lock guard for single scheduler leader in multi-instance setup.
- Monitoring endpoints expanded with timeseries and risk-focus.

## Phase 0.5 - Engineering governance and quality gates (completed)
- CI workflow added for compile + automated tests on PR/push.
- Context synchronization CI guard added to enforce canonical docs updates.
- Contribution rules and Definition of Done documented.
- PR template and CODEOWNERS policy scaffold added.
- ADR process and release policy added.

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
1. Add admin-facing settings contract for size weights, elastic mapping, and in-flight supply inputs.
2. Improve model-B allocation quality (bundle competition heuristic, in-flight ETA sensitivity, economic buffer policy).
3. Prepare integration layer for WB/API ingestion into production-order inputs.
4. Replace placeholder CODEOWNERS handle with real GitHub owner/team and enforce required reviews in repository settings.

## Phase 4 - Optional productization
- Auth and access control.
- Multi-tenant boundaries.
- Packaging/operational controls for external use.
