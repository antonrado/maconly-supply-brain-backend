# ROADMAP

## Strategic objective (Production Order)
- Build a layered, capital-aware, bundle-aware decision engine.
- Optimize inventory turnover, capital efficiency, stockout risk, bundle composition efficiency, and assorti sustainability.
- Keep v1 deterministic and explainable; no black-box optimization.

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

## Phase 1 - Planning Core v1 contract (active)
- Health endpoint returns 200.
- Proposal endpoint accepts validated request body and returns structured proposal.
- Production-order direct/from-WB proposal APIs are stable and explainable.
- Keep API contract stable while replacing internals incrementally.

## Phase 2 - Production Order v1 Stable Alpha (active)

### 2.1 Layer 1 - Stock health metrics foundation (in progress)
- Per-SKU deterministic metrics: velocity (main/assorti), coverage, stock, in-flight, ETA, margin proxy, capital proxy, stockout/overstock risk.
- Expose machine-readable metrics in explanation meta.

### 2.2 Layer 2 - Allocation comparison engine (in progress)
- Deterministic scenario comparison `profit_if_main_until_eta` vs `profit_if_assorti_until_eta`.
- GMROI proxy and explicit decision (`main` / `assorti` / `hold`) per SKU.
- No hard-coded "critical SKU" classifier as primary allocator.

### 2.3 Layer 3 - Purchase recommendation (in progress)
- Allocation-driven purchase shaping is wired: Layer 2 decisions influence recommendation quantities via deterministic factors.
- Complete deterministic purchase recommendation math on top of Layer 1/2 outputs.
- Preserve deterministic math and full explainability.

### 2.4 Layer 4 - Scenario output (planned)
- Deterministic scenarios: Conservative / Balanced / Aggressive.
- For each scenario: capital required, turnover proxy, stockout risk proxy, assorti sustainability impact.

### 2.5 Layer 5 - Intervention signals (planned)
- If unavoidable stockout is detected: emit intervention flags (accelerate production / increase price to slow velocity).
- Signal-only behavior in v1 (no dynamic pricing model).

## v1 Stable Alpha boundaries (strict)
- Deterministic, explainable, test-covered.
- No ML.
- No global optimization solver.
- No elasticity modeling expansion.
- No multi-warehouse logic.

## Process constraints
- Feature branches only.
- Verify before merge.
- Design before implementation.
- Layer-by-layer delivery, no scope creep.

## Immediate high-leverage follow-ups
1. Complete Layer 1 metric contract and lock regression tests.
2. Wire Layer 2 allocation outcomes into Layer 3 purchase quantities.
3. Freeze freshness/infrastructure work to bug-fix-only while Layer 1-3 stabilizes.
4. Publish explicit `Production Order v1 Stable Alpha` acceptance checklist.

## Phase 3 - Hardening and developer UX
- Docker-first test execution for environments without host `pytest`.
- PowerShell helper scripts for common workflows.
- Explicit OpenAPI stability notes for Planning Core endpoints.
- Clarify/document `backend2` purpose (lock-proof/e2e only).

## Phase 4 - Optional productization
- Auth and access control.
- Multi-tenant boundaries.
- Packaging/operational controls for external use.
