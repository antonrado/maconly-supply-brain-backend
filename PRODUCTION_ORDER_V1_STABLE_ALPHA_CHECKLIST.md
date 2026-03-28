# Production Order v1 Stable Alpha - Acceptance Checklist

## 1) Scope and boundaries
- [x] Layered deterministic pipeline is active for production-order proposal (`Layer 1 -> 2 -> 3 -> 4 -> 5`).
- [x] Out-of-scope constraints are respected: no ML, no solver optimization, no multi-warehouse logic, no dynamic pricing model rollout.

## 2) API contract stability
- [x] `POST /api/v1/planning/core/production-order/proposal` returns stable structured response.
- [x] `POST /api/v1/planning/core/production-order/proposal/from-wb` returns stable structured response.
- [x] Request validation rejects malformed payloads with deterministic 4xx errors.
- [x] Unknown `article_id` is rejected deterministically with `404 Article not found` for both direct and from-WB endpoints.
- [x] Live connectivity smoke check passes via `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 po-api-smoke` (health `200`, seeded direct/from-WB happy-path requests `200`, schema validations `422`).

## 3) Layer 1 contract (stock health)
- [x] Layer 1 emits per-SKU metrics in `explanation.meta.layer_1_stock_health.metrics`.
- [x] Layer 1 contract block exists in `explanation.meta.layer_1_stock_health.contract` with status `ok` for valid flows.
- [x] Contract checks include at least:
  - [x] unique color-size keys
  - [x] risk bounds validation
  - [x] non-negative quantity/velocity/coverage invariants
- [x] Assorti classification precedence is deterministic and traceable:
  - [x] `bundle_type.is_assorti`
  - [x] admin fallback mapping
  - [x] global fallback mapping
  - [x] missing/default main fallback

## 4) Layer 2 contract (allocation)
- [x] Allocation decision is composite-objective based (`objective_score_if_main_until_eta` vs `objective_score_if_assorti_until_eta`), not rule-based classification.
- [x] Canonical objective-score diagnostics are present in Layer 2 decisions/diagnostics during transition, while expected-gross-profit aliases remain available (`expected_gross_profit_*` fields and canonical/objective reason counts).
- [x] Decision gate default presentation is `composite_objective_until_eta` with explicit legacy alias `profit_until_eta`.
- [x] Layer 2 emits explicit legacy-alias deprecation-plan diagnostics in decision-quality/meta/alpha-proxy payloads (canonical replacement map + `deprecated_after`) without breaking legacy fields.
- [x] Tie-break is `hold`.
- [x] GMROI is diagnostic-only.
- [x] `explanation.meta.layer_2_allocation.summary` and `decisions` are present in full mode.
- [x] Layer 2 contract block exists in `explanation.meta.layer_2_allocation.contract` with status `ok` for valid flows.
- [x] Contract checks include at least:
  - [x] decision reason mapping matches allocation decision
  - [x] objective-score decision reason mapping matches allocation decision (`decision_reason_objective_score`)
  - [x] allocation decision matches composite objective gate outcome (`main|assorti|hold`) with legacy alias compatibility
  - [x] tie/near-tie flags match objective-gap math with legacy profit-gap alias compatibility
  - [x] profit-gap and GMROI-gap fields are internally consistent
  - [x] objective-score-gap field is internally consistent with objective score pair (`objective_score_gap_until_eta = |objective_score_if_main_until_eta - objective_score_if_assorti_until_eta|`)
  - [x] capital-locked metric is valid (non-negative numeric)
  - [x] objective-component formula is consistent (`objective_score = expected_gross_profit - capital_cost_penalty - stockout_penalty - overstock_penalty`)

## 5) Layer 3 contract (purchase shaping)
- [x] Layer 3 applies deterministic base factors by decision (`main|assorti|hold`).
- [x] Risk-weighted calibration is applied deterministically (stockout boost + overstock dampening + bounded factors).
- [x] Layer 3 shapes reorder quantities and does not replace Layer 2 allocation gate semantics.
- [x] Calibration override evidence confirms Layer 3 can change shaped qty/reorder units while Layer 2 allocation summary/decisions stay unchanged.
- [x] Layer 3 diagnostics are present in `explanation.meta.layer_3_purchase_shaping`:
  - [x] `qty_before`, `qty_after_base`, `qty_after`, `qty_delta_vs_base`
  - [x] calibration method, bounds, and factor summary

## 6) Layer 4 contract (scenarios)
- [x] Scenarios include `Conservative`, `Balanced`, `Aggressive`.
- [x] Scenario factor list is exposed in `explanation.meta.layer_4_scenarios.factors`.
- [x] Layer 4 contract summary exists in `explanation.meta.layer_4_scenarios.contract`.
- [x] Contract checks verify order and monotonic invariants.
- [x] Layer 4 contract checks also verify scenario delta integrity against `Balanced` baseline (`capital/revenue/profit/objective` delta consistency + `gross_profit_delta_vs_balanced` alias consistency).
- [x] Per-scenario money outputs are present:
  - [x] `expected_revenue`
  - [x] `expected_gross_profit`
  - [x] `expected_margin_percent`
  - [x] `expected_turnover_days`
  - [x] `stockout_probability_proxy`
  - [x] `overstock_risk_proxy`
- [x] Capital-gap transparency exists in `explanation.meta.capital_gap` (`available_capital`, `required_capital`, `deficit_or_surplus`) and is signal-only (no auto-policy override).

## 7) Layer 5 contract (interventions)
- [x] Layer 5 uses explicit threshold policy with traceable thresholds in `explanation.meta.layer_5_intervention.signal_thresholds`.
- [x] Policy output is deterministic and includes `signal_policy`, `reason`, and `signals`.
- [x] Severe risk + in-flight path may return dual signals as designed.
- [x] Layer 5 remains signal-only and does not directly enforce recommendation action.

## 8) Explainability contract
- [x] `explainability_mode` supports `full|compact` for direct and from-WB requests.
- [x] `full` preserves detailed steps and detailed meta arrays/maps.
- [x] `compact` preserves deterministic decisions while trimming payload-heavy explanation blocks.
- [x] `explanation.meta.explainability` is present in compact mode and reports omitted step count.
- [x] `compact` preserves contract blocks for Layers 1-5 and `alpha_proxy_economics`.

## 9) From-WB ingestion/freshness
- [x] Freshness mode (`warn|strict`) behavior is deterministic and covered.
- [x] Freshness threshold source precedence (`request > admin_defaults > global_default`) is traceable.
- [x] Observed realized-price calibration from WB revenue window is traceable in `meta.from_wb.economic_observed_prices` and deterministic anomaly filtering (`max deviation=30%`) is covered.
- [x] `meta.from_wb` contains stable as-of trace and compact/full-consistent diagnostics.

## 10) Decision quality evidence (mandatory for stable alpha)
- [x] Casebook artifact is maintained in `PRODUCTION_ORDER_V1_DECISION_QUALITY_CASEBOOK.md`.
- [x] Provide 3 deterministic SKU case studies:
  - [x] Stockout risk case
  - [x] Balanced case
  - [x] Overstock case
- [x] For each case, include:
  - [x] Input metrics
  - [x] Intermediate layer outputs (`L1 -> L5`)
  - [x] Allocation decision reasoning
  - [x] Reorder quantity
  - [x] Scenario comparison (`Conservative|Balanced|Aggressive`)
  - [x] Capital impact proxy

## 10.1) Economic Alpha calibration (mandatory transition block)
- [x] Economics are formula-based and traceable (not proxy-only constants):
  - [x] `production_cost_per_unit`
  - [x] `logistics_cost_per_unit`
  - [x] `wb_commission_percent_main|assorti`
  - [x] `average_realized_price_main|assorti`
  - [x] `available_capital` (strict capital governance input: required via `request|admin_defaults|global_default`, missing source rejected)
- [x] `explanation.meta.alpha_proxy_economics` contains economics source tracing (`economic_source`) and effective inputs (`economic_inputs`).
- [x] Trusted-economics diagnostics are emitted in full/compact explainability (`explanation.meta.economics_trust`, `explanation.meta.warnings`) and mirrored in `alpha_proxy_economics` (`economics_trust_level`, trust payload, warning block).
- [x] Source-tier precedence evidence is regression-locked for Economic Alpha inputs:
  - [x] `request`
  - [x] `admin_defaults`
  - [x] `global_default`
  - [x] `code_default_constants`
- [x] Capital governance strict behavior is regression-locked for direct/from-WB flows: unresolved `available_capital` now returns deterministic `422` with actionable detail and explicit status `missing_available_capital_strict`.
- [x] Layer 2 allocation is demonstrably sensitive to economics changes in regression tests.
- [x] Multi-regime end-to-end evidence is regression-locked for three distinct economics regimes (`stockout_dominates`, `overstock_dominates`, `commission_price_conflict`) proving objective-vs-profit disagreement and expected Layer 5 intervention signals.
- [x] Layer 2 penalty-weight calibration evidence is documented with flip boundaries and frozen defaults, and regressions assert emitted `objective_parameters` + `objective_source` in explainability payloads.
- [x] Capital-limited allocation is demonstrably objective-driven in regression tests (higher `objective_score_per_capital` may be selected before higher raw gross profit; no silent profit-only fallback).
- [x] Budget-limited proposal responses expose deterministic capital-constraint evidence in meta (`status=budget_limited_applied`, ranking, cutoff line incl. partial allocation when applicable).
- [x] For equal objective metrics, shared-capital ranking tie-break is deterministic and availability-priority aligned (`stockout_risk` higher first, then `overstock_risk` lower).
- [x] Capital-constraint meta includes runtime contract block (`version/checks/status`) and valid flows keep `capital_constraint.contract.status=ok` in full/compact responses, including ranking risk-priority consistency (`risk_priority_score = stockout_risk - overstock_risk`).
- [x] Phase 1 resource allocation core is regression-locked on the production-order path: per-article shared resources (`color x size`) are explicitly reserved across competing bundle strategies, no-double-use is enforced by runtime contract checks, and allocation consumption is exposed in both `constraints_applied.resource_allocation` and full/compact explainability metadata.
- [x] Phase 2 shared pantone pool is regression-locked on the production-order path: sibling WB article demand can reduce local fabric-min uplift for the same pantone, and shared-pool diagnostics are exposed in both `constraints_applied.fabric_min_batches` and full/compact explainability metadata.
- [x] Production-order API response now explicitly exposes `physical_scope` and `arrival_projection` contracts at the top level and mirrors both blocks in explainability metadata, including compact mode.
- [x] Arrival-horizon projection is regression-locked as a deterministic narrow slice (`ready now + competition-aware raw + effective in-flight @ arrival - demand until arrival`) and is wired into recommendation guardrail behavior (`safe_cover_until_arrival -> wait`, `shortage_before_arrival` remains shortage-driving).
- [x] Legacy planning endpoints are explicitly marked low-fidelity/deprecated without new planning logic: `/api/v1/planning/core/proposal` and `/api/v1/planning/order-proposal` emit successor/fidelity headers instead of silently pretending parity with production-order core.
- [x] Scope guard preserved while implementing economics: no ML, no solver, no multi-warehouse, no non-economics feature expansion.
- [x] Any R5 modularization remains narrow and facade-preserving: extracted helpers may move to dedicated service modules (currently economics + compact explainability + assorti classification + layer-proxy settings), but `planning_production_order.py` keeps the external service surface/compatibility imports unchanged and regressions remain green.

## 11) Verification gate
- [x] Run verification suite and confirm green:
  - `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 verify`
  - `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 verify-live` (targeted local gate: verify + production-order live API smoke checks)
- [x] Regression tests include Layer 1-5 contracts + explainability compact/full coverage.
- [x] Decision quality case studies are documented and reviewable for external sanity check.
- [x] Current physical-scope / arrival-projection / legacy-marker block is revalidated by `tests/test_planning_core_production_order_api.py`, `tests/test_end_to_end_planning.py`, and `scripts/dev.ps1 verify`.
- [x] Working tree is clean after final commit.

## 12) Decision documentation discipline (mandatory)
- [x] Each accepted architectural/product decision is documented in the same work block (no deferred doc updates).
- [x] `ROADMAP.md` is updated to reflect plan-level impact of the accepted decision.
- [x] `STATUS.md` is updated to reflect implementation/runtime state of the accepted decision.
- [x] Relevant acceptance artifact is updated for the accepted decision (`PRODUCTION_ORDER_V1_STABLE_ALPHA_CHECKLIST.md` / casebook / ADR).
- [x] Documentation update behavior is explicit: after each accepted decision, documentation updates are applied automatically to prevent omissions.
