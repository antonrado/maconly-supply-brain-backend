# Production Order v1 Stable Alpha - Acceptance Checklist

## 1) Scope and boundaries
- [ ] Layered deterministic pipeline is active for production-order proposal (`Layer 1 -> 2 -> 3 -> 4 -> 5`).
- [ ] Out-of-scope constraints are respected: no ML, no solver optimization, no multi-warehouse logic, no dynamic pricing model rollout.

## 2) API contract stability
- [ ] `POST /api/v1/planning/core/production-order/proposal` returns stable structured response.
- [ ] `POST /api/v1/planning/core/production-order/proposal/from-wb` returns stable structured response.
- [ ] Request validation rejects malformed payloads with deterministic 4xx errors.
- [ ] Unknown `article_id` is rejected deterministically with `404 Article not found` for both direct and from-WB endpoints.
- [ ] Live connectivity smoke check passes via `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 po-api-smoke` (health `200`, seeded direct/from-WB happy-path requests `200`, schema validations `422`).

## 3) Layer 1 contract (stock health)
- [ ] Layer 1 emits per-SKU metrics in `explanation.meta.layer_1_stock_health.metrics`.
- [ ] Layer 1 contract block exists in `explanation.meta.layer_1_stock_health.contract` with status `ok` for valid flows.
- [ ] Contract checks include at least:
  - [ ] unique color-size keys
  - [ ] risk bounds validation
  - [ ] non-negative quantity/velocity/coverage invariants
- [ ] Assorti classification precedence is deterministic and traceable:
  - [ ] `bundle_type.is_assorti`
  - [ ] admin fallback mapping
  - [ ] global fallback mapping
  - [ ] missing/default main fallback

## 4) Layer 2 contract (allocation)
- [x] Allocation decision is composite-objective based (`objective_score_if_main_until_eta` vs `objective_score_if_assorti_until_eta`), not rule-based classification.
- [x] Canonical objective-score diagnostics are present in Layer 2 decisions/diagnostics during transition, while expected-gross-profit aliases remain available (`expected_gross_profit_*` fields and canonical/objective reason counts).
- [x] Decision gate default presentation is `composite_objective_until_eta` with explicit legacy alias `profit_until_eta`.
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
  - [x] `available_capital` (awareness-only input)
- [x] `explanation.meta.alpha_proxy_economics` contains economics source tracing (`economic_source`) and effective inputs (`economic_inputs`).
- [x] Source-tier precedence evidence is regression-locked for Economic Alpha inputs:
  - [x] `request`
  - [x] `admin_defaults`
  - [x] `global_default`
  - [x] `code_default_constants`
- [x] Layer 2 allocation is demonstrably sensitive to economics changes in regression tests.
- [x] Capital-limited allocation is demonstrably objective-driven in regression tests (higher `objective_score_per_capital` may be selected before higher raw gross profit; no silent profit-only fallback).
- [x] Budget-limited proposal responses expose deterministic capital-constraint evidence in meta (`status=budget_limited_applied`, ranking, cutoff line incl. partial allocation when applicable).
- [x] For equal objective metrics, shared-capital ranking tie-break is deterministic and availability-priority aligned (`stockout_risk` higher first, then `overstock_risk` lower).
- [x] Capital-constraint meta includes runtime contract block (`version/checks/status`) and valid flows keep `capital_constraint.contract.status=ok` in full/compact responses, including ranking risk-priority consistency (`risk_priority_score = stockout_risk - overstock_risk`).
- [x] Scope guard preserved while implementing economics: no ML, no solver, no multi-warehouse, no non-economics feature expansion.

## 11) Verification gate
- [x] Run verification suite and confirm green:
  - `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 verify`
  - `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 verify-live` (targeted local gate: verify + production-order live API smoke checks)
- [x] Regression tests include Layer 1-5 contracts + explainability compact/full coverage.
- [x] Decision quality case studies are documented and reviewable for external sanity check.
- [x] Working tree is clean after final commit.

## 12) Decision documentation discipline (mandatory)
- [ ] Each accepted architectural/product decision is documented in the same work block (no deferred doc updates).
- [ ] `ROADMAP.md` is updated to reflect plan-level impact of the accepted decision.
- [ ] `STATUS.md` is updated to reflect implementation/runtime state of the accepted decision.
- [ ] Relevant acceptance artifact is updated for the accepted decision (`PRODUCTION_ORDER_V1_STABLE_ALPHA_CHECKLIST.md` / casebook / ADR).
- [ ] Documentation update behavior is explicit: after each accepted decision, documentation updates are applied automatically to prevent omissions.
