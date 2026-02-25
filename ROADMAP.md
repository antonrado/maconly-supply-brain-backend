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
- Assorti classification now uses explicit `bundle_type.is_assorti` as primary source with deterministic admin/global fallback mapping (`admin_defaults` -> `global_default`) and traceable meta output (no runtime keyword parsing).
- Expose machine-readable metrics in explanation meta.

### 2.2 Layer 2 - Allocation comparison engine (in progress)
- Deterministic scenario comparison `profit_if_main_until_eta` vs `profit_if_assorti_until_eta` is the primary decision gate.
- GMROI proxy is computed for diagnostics/audit; deterministic tie-break is `hold`.
- Explicit decision (`main` / `assorti` / `hold`) per SKU.
- No hard-coded "critical SKU" classifier as primary allocator.

### 2.3 Layer 3 - Purchase recommendation (in progress)
- Allocation-driven purchase shaping now includes deterministic risk-weighted calibration on top of Layer 2 decisions.
- Stabilize Layer 3 calibration coefficients/bounds and lock regression coverage.
- Preserve deterministic math and full explainability.

### 2.4 Layer 4 - Scenario output (in progress)
- Deterministic scenarios are wired in explanation meta: Conservative / Balanced / Aggressive.
- Per-scenario outputs include: capital required, turnover proxy, stockout risk proxy, assorti sustainability proxy/impact.
- Finalize calibration rules and intervention handoff contract.

### 2.5 Layer 5 - Intervention signals (in progress)
- Deterministic unavoidable-stockout flags are wired from Layer 4 aggressive risk + risk-level context.
- Signal thresholds are explicit and deterministic (`accelerate_production` severe threshold, `increase_price_to_slow_velocity` unavoidable threshold).
- Current signal set: `accelerate_production` / `increase_price_to_slow_velocity` (dual signal allowed under severe in-flight risk).
- Keep signal-only behavior in v1 (no dynamic pricing model).

### 2.6 Explainability payload controls (in progress)
- Response explainability modes are now supported: `full` (default) and `compact` (summary + compact meta) for production-order direct/from-WB endpoints.
- Compact mode preserves deterministic planner outputs and trims explainability payload size (steps + heavy meta arrays).
- Stabilize/lock compact-mode contract with additional regression coverage as Layer 1-5 semantics finalize.

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
2. Stabilize Layer 3 deterministic calibration coefficients/bounds and lock regression coverage.
3. Finalize Layer 4 scenario contract and stabilize regression coverage.
4. Stabilize Layer 5 intervention threshold policy/rules and lock regression coverage.
5. Stabilize explainability `compact|full` payload contract and lock regression coverage.
6. Freeze freshness/infrastructure work to bug-fix-only while Layer 1-5 stabilizes.
7. Publish explicit `Production Order v1 Stable Alpha` acceptance checklist.

## Phase 3 - Hardening and developer UX
- Docker-first test execution for environments without host `pytest`.
- PowerShell helper scripts for common workflows.
- Explicit OpenAPI stability notes for Planning Core endpoints.
- Clarify/document `backend2` purpose (lock-proof/e2e only).

## Phase 4 - Optional productization
- Auth and access control.
- Multi-tenant boundaries.
- Packaging/operational controls for external use.
