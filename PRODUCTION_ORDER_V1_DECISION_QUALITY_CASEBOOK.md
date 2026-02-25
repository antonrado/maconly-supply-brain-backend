# Production Order v1 Stable Alpha - Decision Quality Casebook

## Purpose
This casebook captures deterministic decision behavior for three canonical SKU profiles used as release-gate evidence:
1. Stockout risk case
2. Balanced case
3. Overstock case

All cases follow v1 boundaries: deterministic math only, layered architecture (`L1 -> L5`), no ML, no solver optimization.

## Deterministic assumptions
- Layer 2 decision gate: profit comparison until ETA (`main` vs `assorti`), tie-break `hold`.
- Layer 3 applies quantity shaping/calibration and does not replace Layer 2 gate semantics.
- Layer 5 emits intervention signals only; recommendation action is resolved separately.
- Capital impact proxy uses `LAYER2_UNIT_CAPITAL_PROXY` in Layer 4 scenarios.

## Case A - Stockout risk
### Input metrics
- risk_level: `critical`
- in_flight_effective_qty_total: `0`
- available_bundles_for_cover: `20`
- total_daily_sales: `8.0`
- reorder_point_days: `40`
- line metrics (single SKU):
  - `eta_days=10`
  - `current_stock=20`
  - `in_flight=0`
  - `velocity_main=3.0`
  - `velocity_assorti=1.5`
  - `capital_locked=100.0`
  - `stockout_risk=0.9`
  - `overstock_risk=0.1`

### Layer outputs
- Layer 1:
  - `velocity_main=3.0`
  - `velocity_assorti=1.5`
  - `stockout_risk=0.9`
  - `overstock_risk=0.1`
  - `capital_locked=100.0`
- Layer 2:
  - `allocation_decision=main`
  - `profit_if_main_until_eta=20.0`
  - `profit_if_assorti_until_eta=12.75`
- Layer 3:
  - base input qty: `120`
  - `qty_after_base=120`
  - `qty_after=150`
  - `qty_delta_vs_base=+30`
- Layer 4 scenarios (purchase_units / capital):
  - Conservative: `120 / 120.0`
  - Balanced: `150 / 150.0`
  - Aggressive: `180 / 180.0`
- Layer 5:
  - `signals=["accelerate_production"]`
  - `reason=no_effective_in_flight_and_high_stockout_risk`
- Recommendation action: `order_minimum_only`

## Case B - Balanced
### Input metrics
- risk_level: `warning`
- in_flight_effective_qty_total: `20`
- available_bundles_for_cover: `180`
- total_daily_sales: `5.0`
- reorder_point_days: `40`
- line metrics (single SKU):
  - `eta_days=10`
  - `current_stock=30`
  - `in_flight=10`
  - `velocity_main=1.0`
  - `velocity_assorti=2.0`
  - `capital_locked=80.0`
  - `stockout_risk=0.4`
  - `overstock_risk=0.4`

### Layer outputs
- Layer 1:
  - `velocity_main=1.0`
  - `velocity_assorti=2.0`
  - `stockout_risk=0.4`
  - `overstock_risk=0.4`
  - `capital_locked=80.0`
- Layer 2:
  - `allocation_decision=assorti`
  - `profit_if_main_until_eta=10.0`
  - `profit_if_assorti_until_eta=17.0`
- Layer 3:
  - base input qty: `100`
  - `qty_after_base=75`
  - `qty_after=73`
  - `qty_delta_vs_base=-2`
- Layer 4 scenarios (purchase_units / capital):
  - Conservative: `59 / 59.0`
  - Balanced: `73 / 73.0`
  - Aggressive: `88 / 88.0`
- Layer 5:
  - `signals=[]`
  - `reason=none`
- Recommendation action: `order_minimum_only`

## Case C - Overstock
### Input metrics
- risk_level: `overstock`
- in_flight_effective_qty_total: `40`
- available_bundles_for_cover: `1000`
- total_daily_sales: `4.0`
- reorder_point_days: `40`
- line metrics (single SKU):
  - `eta_days=10`
  - `current_stock=200`
  - `in_flight=50`
  - `velocity_main=1.7`
  - `velocity_assorti=2.0`
  - `capital_locked=120.0`
  - `stockout_risk=0.05`
  - `overstock_risk=0.95`

### Layer outputs
- Layer 1:
  - `velocity_main=1.7`
  - `velocity_assorti=2.0`
  - `stockout_risk=0.05`
  - `overstock_risk=0.95`
  - `capital_locked=120.0`
- Layer 2:
  - `allocation_decision=hold` (profit tie)
  - `profit_if_main_until_eta=17.0`
  - `profit_if_assorti_until_eta=17.0`
- Layer 3:
  - base input qty: `40`
  - `qty_after_base=14`
  - `qty_after=4`
  - `qty_delta_vs_base=-10`
- Layer 4 scenarios (purchase_units / capital):
  - Conservative: `4 / 4.0`
  - Balanced: `4 / 4.0`
  - Aggressive: `5 / 5.0`
- Layer 5:
  - `signals=[]`
  - `reason=none`
- Recommendation action: `wait`

## Release-gate traceability
- This casebook is intended to be locked by regression tests in `tests/test_planning_core_production_order_api.py`.
- Coverage includes deterministic helper snapshots (`test_decision_quality_case_studies_are_deterministic`) and full helper-chain coverage from computed Layer 1 metrics (`test_decision_quality_case_studies_are_deterministic_across_layer1_to_layer5`).
- Regressions verify deterministic outputs, recommendation action integrity, and scenario capital deltas for all three cases.
