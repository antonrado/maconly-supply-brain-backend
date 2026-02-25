# ARCHITECTURE CANON

## Architectural principles
1. **Stable API contracts**: breaking changes require explicit decision.
2. **Thin routers**: endpoint layer should wire HTTP only.
3. **Domain/services own logic**: planning and monitoring logic belongs in `app/core` and `app/services`.
4. **Deterministic operations**: prefer reproducible commands over screenshots or long logs.
5. **Single scheduler writer**: in multi-instance runtime, only one backend instance may run periodic monitoring capture.

## Repository layout
- `app/main.py` - FastAPI app wiring and lifecycle hooks.
- `app/api/v1` - HTTP routing/endpoints.
- `app/core/planning` - Planning Core domain contract and service interface/implementation.
- `app/services` - Monitoring/planning service logic and scheduler.
- `app/models` - SQLAlchemy models.
- `tests` - API/service tests.

## Monitoring scheduler invariant
- Scheduler is process-local APScheduler, started from FastAPI startup.
- Leadership is guarded via PostgreSQL advisory lock.
- Lock is acquired/released through a dedicated DB connection (`engine.raw_connection()`), so lock lifecycle is connection-scoped.

## Planning Core v1 invariant
- `/api/v1/planning/core/health` and `/api/v1/planning/core/proposal` remain available as contract-first endpoints.
- Request validation and response shape are stable; implementation may evolve behind the same contract.

## Production Order v1 architecture canon
- Production Order is a **layered, capital-aware, bundle-aware decision engine**, not a simple reorder calculator.
- Optimization goals are balanced jointly: turnover, capital efficiency, stockout risk, bundle composition efficiency, assorti sustainability.
- Assorti classification precedence is deterministic and traceable: `bundle_type.is_assorti` (primary) -> article admin mapping fallback -> global mapping fallback -> main default.
- Layer sequence is strict:
  1. Layer 1 - deterministic stock-health metrics by SKU.
  2. Layer 2 - deterministic allocation comparison (`main` vs `assorti`) using time-window profit as decision gate; GMROI proxy is diagnostic-only and tie-break is `hold`.
  3. Layer 3 - purchase recommendation derived from Layer 1+2 outputs.
  4. Layer 4 - deterministic scenarios (Conservative/Balanced/Aggressive).
  5. Layer 5 - intervention flags only (no dynamic pricing model).
- Layer contract summaries are machine-readable and deterministic:
  - Layer 1 contract checks risk bounds + non-negative invariants + unique color-size keys.
  - Layer 4 contract checks scenario order and monotonic behavior.
  - Layer 5 policy exposes threshold-driven intervention reasoning and signal thresholds.

## Production Order v1 Alpha proxy economics contract
- Economic values in v1 alpha are explicit proxies and must not be treated as calibrated financial truth.
- Proxy set includes: margin proxies (main/assorti), unit capital proxy, Layer 1 stockout threshold, Layer 3 shaping factors and calibration bounds/weights, Layer 4 scenario factors + contract version, Layer 5 intervention thresholds.
- Proposal responses must expose effective proxy values and value source through machine-readable meta (currently source=`code_default_constants`).
- Any migration from proxy defaults to request/admin/global settings must preserve determinism and source tracing.

## Production Order v1 Stable Alpha boundaries
- Deterministic and explainable outputs are mandatory.
- Test coverage is mandatory for each layer increment.
- Explicitly out of scope for v1 alpha:
  - ML / black-box optimization.
  - Global optimization solvers.
  - Elasticity model expansion.
  - Multi-warehouse optimization logic.

## Production Order delivery process
- Feature-branch development only.
- Verify before merge.
- Design before implementation.
- Layer-by-layer rollout with no scope creep.

## Explainability payload size control (active)
- Explainability modes `full` and `compact` are supported for direct and from-WB production-order endpoints.
- `compact` mode reduces payload size (summary + compact meta) without changing deterministic decision math.
- `full` remains default for audit/deep diagnostics.
- Regression coverage includes compact/full parity for deterministic business outputs.

## Verification philosophy
- Every substantial task should include command-level verification (PowerShell-safe).
- STATUS.md stores minimal raw outputs and exact commands for reproducibility.

## Engineering governance baseline
- CI gates run compile + automated tests on PR/push (`.github/workflows/ci.yml`).
- CI enforces context sync using `scripts/context_guard.py` (fails PR when runtime/API/planning changes are not reflected in canonical docs).
- PRs use a structured template with risk/migration/rollback sections.
- Definition of Done lives in `CONTRIBUTING.md`.
- Releases follow explicit policy in `RELEASE_POLICY.md`.
- Significant architectural decisions are captured in `docs/adr/`.
