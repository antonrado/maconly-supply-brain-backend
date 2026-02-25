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
- [ ] Decision gate is `profit_until_eta`.
- [ ] Tie-break is `hold`.
- [ ] GMROI is diagnostic-only.
- [ ] `explanation.meta.layer_2_allocation.summary` and `decisions` are present in full mode.

## 5) Layer 3 contract (purchase shaping)
- [ ] Layer 3 applies deterministic base factors by decision (`main|assorti|hold`).
- [ ] Risk-weighted calibration is applied deterministically (stockout boost + overstock dampening + bounded factors).
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

## 8) Explainability contract
- [ ] `explainability_mode` supports `full|compact` for direct and from-WB requests.
- [ ] `full` preserves detailed steps and detailed meta arrays/maps.
- [ ] `compact` preserves deterministic decisions while trimming payload-heavy explanation blocks.
- [ ] `explanation.meta.explainability` is present in compact mode and reports omitted step count.

## 9) From-WB ingestion/freshness
- [ ] Freshness mode (`warn|strict`) behavior is deterministic and covered.
- [ ] Freshness threshold source precedence (`request > admin_defaults > global_default`) is traceable.
- [ ] `meta.from_wb` contains stable as-of trace and compact/full-consistent diagnostics.

## 10) Verification gate
- [ ] Run verification suite and confirm green:
  - `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 verify`
- [ ] Regression tests include Layer 1-5 contracts + explainability compact/full coverage.
- [ ] Working tree is clean after final commit.
