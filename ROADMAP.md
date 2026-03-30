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
- Machine-readable metrics and contract checks are exposed in explanation meta (risk bounds, non-negative invariants, unique SKU pairs).
- Decision-quality case-study regression now includes full helper-chain `L1 -> L5` deterministic coverage to lock computed Layer 1 metric stability together with downstream allocation/shaping/scenario/intervention behavior.

### 2.2 Layer 2 - Allocation comparison engine (in progress)
- Deterministic composite-objective comparison is the primary decision gate (`objective_score_if_main_until_eta` vs `objective_score_if_assorti_until_eta`, `decision_gate=composite_objective_until_eta`) computed from traceable economics inputs (realized price, commission, production cost, logistics cost).
- GMROI proxy is computed for diagnostics/audit; deterministic tie-break is `hold`.
- Layer 2 now emits explicit decision-quality diagnostics (near-tie/tie counts, decision reason distribution, avg profit/GMROI gaps, capital-locked aggregates) in explainability meta.
- Layer 2 default presentation now uses canonical composite-objective naming (`method=time_window_composite_objective_with_gmroi_diagnostics`, `decision_gate=composite_objective_until_eta`) while keeping explicit legacy aliases (`legacy_method=time_window_profit_proxy_with_gmroi_diagnostics`, `legacy_decision_gate=profit_until_eta`) to support transition without facade drift.
- Layer 2 now emits explicit legacy-alias deprecation-plan diagnostics (`deprecated_after`, legacy gate aliases, canonical field replacement map) in decision-quality and explainability meta/alpha-proxy blocks while keeping aliases non-breaking during the transition window.
- Layer 2 decision flags (`allocation_decision`, `tie_break_applied`, `near_tie`) are stabilized against floating-point boundary noise by using normalized 4-decimal profit/GMROI diagnostics that are also emitted in explainability payloads.
- Layer 2 helper interfaces now require explicit economics inputs (`margin_main_per_unit`, `margin_assorti_per_unit`, `unit_capital_per_unit`) to prevent accidental fallback to proxy constants after refactors.
- Explicit decision (`main` / `assorti` / `hold`) per SKU.
- Layer 2 contract summary is now exposed (version/checks/status; summary-vs-decisions consistency, allocation-vs-composite-objective-gate consistency with legacy alias compatibility, tie-break invariants, decision-reason mapping including objective-score reason field consistency, tie/near-tie objective-gap consistency with legacy profit-gap aliases, profit/GMROI gap consistency, objective-score-gap consistency, capital metric sanity) and projected in compact explainability mode.
- Layer 2 contract now explicitly verifies objective-component decomposition formula consistency (`objective_score = expected_gross_profit - capital_cost_penalty - stockout_penalty - overstock_penalty`) to block silent fallback or malformed objective payloads.
- Capital-limited line selection evidence is now regression-locked at helper/API level: objective-per-capital ranking can prioritize lower gross-profit lines when penalties make them economically dominant, budget allocation follows this ranking (no silent profit-only fallback), and proposal meta exposes deterministic budget-limited ranking/cutoff behavior.
- Shared-capital tie-break now prioritizes availability risk deterministically when objective metrics are equal (`stockout_risk` higher first, then `overstock_risk` lower) to align constrained allocation with out-of-stock protection policy.
- Capital-constraint meta now includes runtime contract summary (`version/checks/status`) validating budget accounting, line-count invariants, ranking sort/uniqueness, risk-priority score consistency, and cutoff-line consistency to guard against silent ranking/accounting drift.
- No hard-coded "critical SKU" classifier as primary allocator.
- Economic Alpha economics precedence is now wired and traceable end-to-end (`request -> admin_defaults -> global_default -> code_default_constants`) with regression coverage for each source tier.

### 2.3 Layer 3 - Purchase recommendation (in progress)
- Allocation-driven purchase shaping now includes deterministic risk-weighted calibration on top of Layer 2 decisions.
- Regression now explicitly locks Layer 3 semantics as quantity-shaping only: changing Layer 3 calibration overrides changes shaped quantity/reorder units, while Layer 2 allocation summary/decisions remain unchanged.
- Layer 3 calibration coefficients now support deterministic precedence (`request -> admin_defaults -> global_default -> code_default_constants`) with source tracing in explainability meta.
- Layer 3 contract summary is now exposed (version/checks/status; qty delta invariants, decision/risk partition consistency, calibration method/bounds, factor summary sanity) and projected in compact explainability mode.
- Stabilize Layer 3 calibration coefficients/bounds and lock regression coverage.
- Preserve deterministic math and full explainability.

### 2.4 Layer 4 - Scenario output (in progress)
- Deterministic scenarios are wired in explanation meta: Conservative / Balanced / Aggressive.
- Per-scenario outputs now include money fields (`expected_revenue`, `expected_gross_profit`, `expected_margin_percent`, `expected_turnover_days`) plus risk proxies (`stockout_probability_proxy`, `stockout_risk_proxy`, `overstock_risk_proxy`) and assorti sustainability proxy/impact.
- Capital-gap transparency is now emitted (`available_capital`, `required_capital`, `deficit_or_surplus`) without auto-policy enforcement.
- Layer 4 contract now includes scenario-delta runtime checks (delta field presence + balanced-baseline consistency across capital/revenue/profit/objective, including gross-profit delta alias consistency) to prevent silent explainability drift.
- Finalize calibration rules and intervention handoff contract.

### 2.7 Economic Alpha calibration (active, highest priority)
- Replace proxy-only economics with formula-based, source-traceable economics inputs.
- Keep deterministic behavior and API contract stability while migrating.
- Scope guard for this block is strict: no ML, no solver optimization, no multi-warehouse rollout, no new non-economics entities.
- from-WB adapter now feeds observed realized prices from WB revenue window into runtime economics source `from_wb_observed_window` (request still has top precedence), with deterministic anomaly filtering (`30%` max deviation) and diagnostics projected in explainability meta.
- Execution order inside this block:
  1. economics input traceability (`request -> admin_defaults -> global_default -> code_default_constants`),
  2. Layer 2 composite-objective gate hardening with legacy alias compatibility,
  3. Layer 4 full money outputs + capital-gap diagnostics,
  4. targeted decomposition of layer helpers into modules without facade behavior drift.
- Release evidence now includes deterministic end-to-end allocation flip under identical units-until-ETA where only realized price inputs are swapped (`main -> assorti`), executed in the integration gate test set used by `verify`/`verify-live`.
- Trusted-economics diagnostics are now a release-block requirement: expose per-key-field economics source, code-default dominance ratio, and trust level (`trusted|partial|untrusted`) with explicit warning block in full/compact explainability.
- Capital governance is now strict for proposal execution: unresolved `available_capital` (no `request|admin_defaults|global_default` source) returns deterministic `422` with actionable detail and explicit `capital_constraint_status=missing_available_capital_strict`.
- Value-proof sequencing is now explicit: lock trusted economics + capital safety + multi-regime e2e evidence first; defer large modular refactor work until these proofs are stable.
- Multi-regime release evidence is now explicit and regression-locked: `stockout_dominates`, `overstock_dominates`, and `commission_price_conflict` e2e cases must prove objective-vs-profit disagreement and expected Layer 5 signal behavior.
- Penalty-weight calibration evidence is now mandatory and documented: freeze Layer 2 defaults (`capital_cost_rate=0.08`, `stockout_penalty_weight=1.0`, `overstock_penalty_weight=1.0`), track approximate flip boundaries in the casebook, and assert emitted `objective_parameters` + `objective_source` in regression payloads.
- Modular decomposition remains intentionally deferred to bug-fix-only scope until R1-R4 economics evidence stays stable through verification gates.
- Narrow R5 work may now proceed only as facade-preserving extraction: first safe slice is the shared economics helper cluster (`planning_production_order_economics.py`) with public behavior unchanged and existing service exports preserved from `planning_production_order.py`.
- Second safe slice for narrow R5 is compact explainability projection (`planning_production_order_explainability.py`): compact/full response behavior stays regression-locked while `planning_production_order.py` preserves compatibility imports and facade behavior.
- Third safe slice for narrow R5 is assorti classification support (`planning_production_order_assorti.py`): assorti mapping parse/load helpers and source constants move out, while `planning_production_order.py` keeps compatibility imports and deterministic Layer 1 explainability behavior unchanged.
- Fourth safe slice for narrow R5 is layer-proxy settings resolution (`planning_production_order_layer_proxy.py`): default coefficients, threshold/source precedence, and threshold-clamp behavior move out, while `planning_production_order.py` keeps compatibility imports and response semantics unchanged.
- Constraint-based supply alignment has started on the existing production-order path: Phase 1 resource allocation core is now implemented per article via explicit shared-resource reservation (`color x size`) across bundle strategies, deterministic no-double-use contract checks, and emitted allocation-consumption diagnostics in `constraints_applied` + full/compact explainability.
- Constraint-based supply alignment now includes Phase 2 cross-article color linking on the existing production-order facade: sibling WB article demand is aggregated into a shared pantone pool proxy that influences fabric minimum batching decisions, and the applied shared-pool evidence is emitted in `constraints_applied.fabric_min_batches` plus full/compact explainability metadata.
- Production-order API contract now explicitly exposes physical stock scope and arrival-horizon projection at the top level (`physical_scope`, `arrival_projection`) and mirrors both blocks in explainability metadata; compact mode preserves these blocks as first-class diagnostics rather than dropping them into untyped tails.
- Arrival-horizon projection is now part of the live decision guardrail on the production-order facade: `safe_cover_until_arrival` may deterministically force `wait`, while `shortage_before_arrival` remains an order-driving/escalation signal without introducing deep simulation.
- Legacy planning paths are now explicitly marked low-fidelity/deprecated at the API surface: `/api/v1/planning/core/proposal` remains a stub with successor guidance, and `/api/v1/planning/order-proposal` remains legacy live logic with deprecation/fidelity headers instead of silent parity assumptions.
- Direct production-order prerequisite failures should stay operator-facing and machine-readable: missing `bundle_recipe` coverage and missing SKU scope for recipe colors now return structured `400` details (`code/message/affected ids/next_steps`) and must not regress back to plain string errors.
- Production-order settings admin validation should stay machine-readable as well: invalid size ids, elastic binding scope mismatches, assorti bundle type ids, and in-flight color/size scope errors now return structured `400` details (`code/field/affected ids/next_steps`) instead of plain strings.
- WB onboarding/live-sync account resolution should stay machine-readable too: missing active account, unknown `account_id`, and empty `api_token` now return structured `400` details (`code/account_id?/next_steps`) instead of plain strings before any external WB call is attempted.
- WB transport/response failures should also stay machine-readable: request/network failures, rate limits, unauthorized tokens, invalid JSON, and invalid rows-format payloads now return structured WB error details with deterministic `code`, `next_steps`, and upstream metadata where available.
- WB object-response helpers should stay machine-readable as well: `_wb_get_json_object` now returns structured `wb_api_invalid_object_format` detail with deterministic `next_steps` instead of a raw string when an object endpoint responds with a non-object payload.
- WB replenishment request validation should stay machine-readable too: invalid date ordering (`wb_arrival_date < target_date`) on `POST /api/v1/wb/manager/proposal` now returns a structured validation detail with both dates, invalid field, and deterministic `next_steps`.
- WB shipment creation validation should stay aligned too: invalid date ordering (`wb_arrival_date < target_date`) on `POST /api/v1/wb/manager/shipment/from-proposal` now returns the same structured validation detail with both dates, invalid field, and deterministic `next_steps`.
- WB shipment resource misses should stay machine-readable too: read/edit shipment surfaces now return structured `wb_shipment_not_found` / `wb_shipment_item_not_found` details with resource IDs and deterministic `next_steps` instead of raw strings.
- WB shipment headers sorting should stay machine-readable too: invalid `sort_by` / `sort_dir` now return structured validation details, and the header-list path no longer crashes due to `status` query shadowing.
- Operator-facing article lookup failures should stay aligned too: direct proposal, `from-wb` proposal, production-order settings, and WB readiness now return the same structured `404` `article_not_found` detail (`code/message/article_id/next_steps`) instead of raw strings.
- Planning config snapshot should stay machine-readable on misses as well: missing article and missing article-level planning configuration now return structured `404` details (`article_not_found` / `no_planning_settings_found`) with `article_id` and deterministic `next_steps` instead of raw strings.
- Read-only article endpoints should follow the same pattern: `article-dashboard` and `article-bundle-snapshot` now return structured `article_not_found` detail (`code/message/article_id/next_steps`) instead of raw strings.
- Read-only bundle availability should follow the same operator contract discipline: missing article, bundle type, warehouse, and missing recipe on `bundle-availability` now return structured details (`article_not_found`, `bundle_type_not_found`, `warehouse_not_found`, `no_bundle_recipe`) instead of raw strings.
- Read-only bundle deficit should match the same contract discipline: invalid `target_count`, missing article, bundle type, warehouse, and missing recipe on `bundle-deficit` now return structured details (`invalid_target_count`, `article_not_found`, `bundle_type_not_found`, `warehouse_not_found`, `no_bundle_recipe`) instead of raw strings.
- Read-only order explanation should preserve the same machine-readable missing-article contract too: filtered `order-explanation-portfolio` requests now handle missing articles via structured `article_not_found` detail internally while keeping the existing skip-missing response semantics.

### 2.5 Layer 5 - Intervention signals (in progress)
- Deterministic unavoidable-stockout flags are wired from Layer 4 aggressive risk + risk-level context.
- Signal thresholds are explicit and deterministic (`accelerate_production` severe threshold, `increase_price_to_slow_velocity` unavoidable threshold).
- Layer 5 thresholds now support deterministic precedence (`request -> admin_defaults -> global_default -> code_default_constants`) with source tracing and safe threshold-order clamping.
- Layer 5 contract summary is now exposed (version/checks/status; threshold sanity, signal validity/order, reason-policy consistency) and projected in compact explainability mode.
- Layer 5 signal-only semantics are explicitly regression-locked: intervention signals may vary with thresholds while recommendation action remains unchanged for equivalent planning state.
- Current signal set: `accelerate_production` / `increase_price_to_slow_velocity` (dual signal allowed under severe in-flight risk).
- Keep signal-only behavior in v1 (no dynamic pricing model).

### 2.6 Explainability payload controls (in progress)
- Response explainability modes are now supported: `full` (default) and `compact` (summary + compact meta) for production-order direct/from-WB endpoints.
- Compact mode preserves deterministic planner outputs and trims explainability payload size (steps + heavy meta arrays).
- Compact-mode regressions now explicitly assert Layer 1-5 contract blocks are preserved for both direct and from-WB flows.
- Compact/full parity harness now covers profile-based direct and from-WB scenarios (stockout / balanced / overstock style demand-stock setups) and validates Layer 2 decision-quality diagnostics plus Layer 2 contract decision-quality consistency checks are retained in compact metadata, while Layer 2 compact step text retains key readability fields (`decision_gate`, `reason_counts`, average profit gap, capital locked, contract status).
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
- Decision logging discipline is mandatory: every accepted architectural/product decision is documented immediately in the same work block.
- Documentation update is automatic after each accepted decision and must include at least `ROADMAP.md`, `STATUS.md`, and the relevant acceptance artifact (`PRODUCTION_ORDER_V1_STABLE_ALPHA_CHECKLIST.md` / casebook / ADR) to avoid omissions.

## Immediate high-leverage follow-ups
1. Finalize Layer 2 legacy-alias deprecation plan (`profit` / `expected_gross_profit` compatibility fields) after the deprecation window, without breaking stable API behavior during transition.
2. Lock regressions that prove allocation sensitivity to economics changes and preserve deterministic outputs.
3. Keep Layer 5 signal-only semantics explicit (no direct recommendation-action enforcement from intervention signals).
4. Keep explainability/contract expansion limited to behavior-critical checks while economics calibration evidence is finalized.
5. Freeze freshness/infrastructure work to bug-fix-only while economics release evidence is being locked.
6. Maintain explicit `Production Order v1 Stable Alpha` acceptance checklist (`PRODUCTION_ORDER_V1_STABLE_ALPHA_CHECKLIST.md`) as release gate.
7. Keep section 12 documentation-discipline checklist evidence current in each accepted work block while release candidate evidence is finalized.

## Phase 3 - Hardening and developer UX
- Docker-first test execution for environments without host `pytest`.
- PowerShell helper scripts for common workflows.
- Explicit OpenAPI stability notes for Planning Core endpoints.
- Clarify/document `backend2` purpose (lock-proof/e2e only).

## Phase 4 - Optional productization
- Auth and access control.
- Multi-tenant boundaries.
- Packaging/operational controls for external use.
