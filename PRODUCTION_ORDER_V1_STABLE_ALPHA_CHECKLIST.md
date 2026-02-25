# Production Order v1 Stable Alpha - Acceptance Checklist

## 1) Scope and boundaries
- [ ] Layered deterministic pipeline is active for production-order proposal (`Layer 1 -> 2 -> 3 -> 4 -> 5`).
- [ ] Out-of-scope constraints are respected: no ML, no solver optimization, no multi-warehouse logic, no dynamic pricing model rollout.

## 2) API contract stability
- [ ] `POST /api/v1/planning/core/production-order/proposal` returns stable structured response.
- [ ] `POST /api/v1/planning/core/production-order/proposal/from-wb` returns stable structured response.
- [ ] Request validation rejects malformed payloads with deterministic 4xx errors.

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
- [ ] Allocation decision is profit-comparison based (`profit_if_main_until_eta` vs `profit_if_assorti_until_eta`), not rule-based classification.
- [ ] Decision gate is `profit_until_eta`.
- [ ] Tie-break is `hold`.
- [ ] GMROI is diagnostic-only.
- [ ] `explanation.meta.layer_2_allocation.summary` and `decisions` are present in full mode.
- [ ] Layer 2 contract block exists in `explanation.meta.layer_2_allocation.contract` with status `ok` for valid flows.
- [ ] Contract checks include at least:
  - [ ] decision reason mapping matches allocation decision
  - [ ] tie/near-tie flags match profit-gap math
  - [ ] profit-gap and GMROI-gap fields are internally consistent
  - [ ] capital-locked metric is valid (non-negative numeric)

## 5) Layer 3 contract (purchase shaping)
- [ ] Layer 3 applies deterministic base factors by decision (`main|assorti|hold`).
- [ ] Risk-weighted calibration is applied deterministically (stockout boost + overstock dampening + bounded factors).
- [ ] Layer 3 shapes reorder quantities and does not replace Layer 2 allocation gate semantics.
- [ ] Layer 3 diagnostics are present in `explanation.meta.layer_3_purchase_shaping`:
  - [ ] `qty_before`, `qty_after_base`, `qty_after`, `qty_delta_vs_base`
  - [ ] calibration method, bounds, and factor summary

## 6) Layer 4 contract (scenarios)
- [ ] Scenarios include `Conservative`, `Balanced`, `Aggressive`.
- [ ] Scenario factor list is exposed in `explanation.meta.layer_4_scenarios.factors`.
- [ ] Layer 4 contract summary exists in `explanation.meta.layer_4_scenarios.contract`.
- [ ] Contract checks verify order and monotonic invariants.

## 7) Layer 5 contract (interventions)
- [ ] Layer 5 uses explicit threshold policy with traceable thresholds in `explanation.meta.layer_5_intervention.signal_thresholds`.
- [ ] Policy output is deterministic and includes `signal_policy`, `reason`, and `signals`.
- [ ] Severe risk + in-flight path may return dual signals as designed.
- [ ] Layer 5 remains signal-only and does not directly enforce recommendation action.

## 8) Explainability contract
- [ ] `explainability_mode` supports `full|compact` for direct and from-WB requests.
- [ ] `full` preserves detailed steps and detailed meta arrays/maps.
- [ ] `compact` preserves deterministic decisions while trimming payload-heavy explanation blocks.
- [ ] `explanation.meta.explainability` is present in compact mode and reports omitted step count.
- [ ] `compact` preserves contract blocks for Layers 1-5 and `alpha_proxy_economics`.

## 9) From-WB ingestion/freshness
- [ ] Freshness mode (`warn|strict`) behavior is deterministic and covered.
- [ ] Freshness threshold source precedence (`request > admin_defaults > global_default`) is traceable.
- [ ] `meta.from_wb` contains stable as-of trace and compact/full-consistent diagnostics.

## 10) Decision quality evidence (mandatory for stable alpha)
- [ ] Casebook artifact is maintained in `PRODUCTION_ORDER_V1_DECISION_QUALITY_CASEBOOK.md`.
- [ ] Provide 3 deterministic SKU case studies:
  - [ ] Stockout risk case
  - [ ] Balanced case
  - [ ] Overstock case
- [ ] For each case, include:
  - [ ] Input metrics
  - [ ] Intermediate layer outputs (`L1 -> L5`)
  - [ ] Allocation decision reasoning
  - [ ] Reorder quantity
  - [ ] Scenario comparison (`Conservative|Balanced|Aggressive`)
  - [ ] Capital impact proxy

## 11) Verification gate
- [ ] Run verification suite and confirm green:
  - `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 verify`
- [ ] Regression tests include Layer 1-5 contracts + explainability compact/full coverage.
- [ ] Decision quality case studies are documented and reviewable for external sanity check.
- [ ] Working tree is clean after final commit.
