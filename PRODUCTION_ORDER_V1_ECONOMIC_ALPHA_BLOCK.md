# Production Order v1 - Economic Alpha Block

## Purpose
Transition Production Order from proxy-only economics to formula-based money calculations while preserving deterministic v1 behavior.

## Scope Guard (strict)
- No ML
- No solver optimization
- No multi-warehouse expansion
- No non-economics feature expansion

## Required economics inputs
- `production_cost_per_unit`
- `logistics_cost_per_unit`
- `wb_commission_percent_main`
- `wb_commission_percent_assorti`
- `average_realized_price_main`
- `average_realized_price_assorti`
- `available_capital` (awareness only)

## Formula baseline
- `unit_capital = production_cost_per_unit + logistics_cost_per_unit`
- `gross_margin_main = average_realized_price_main - (average_realized_price_main * wb_commission_percent_main) - production_cost_per_unit - logistics_cost_per_unit`
- `gross_margin_assorti = average_realized_price_assorti - (average_realized_price_assorti * wb_commission_percent_assorti) - production_cost_per_unit - logistics_cost_per_unit`

## Release requirements
1. Layer 2 gate migration target: compare expected gross profit until ETA (main vs assorti) with deterministic tie-break `hold`.
2. Layer 4 scenarios must expose money outputs per scenario:
   - `expected_revenue`
   - `expected_gross_profit`
   - `expected_margin_percent`
   - `expected_turnover_days`
   - `stockout_probability_proxy`
   - `overstock_risk_proxy`
3. Capital transparency block:
   - `available_capital`
   - `required_capital`
   - `deficit_or_surplus`
4. Explainability traceability:
   - effective economics inputs
   - source for each input (`request`, `admin_defaults`, `global_default`, `code_default_constants`)
5. Regression evidence:
   - allocation sensitivity to economics changes
   - deterministic output stability under fixed inputs

## Current implementation checkpoint
- Request-level economic overrides are available in production-order request overrides.
- Economics source precedence is wired to full chain:
  `request -> admin_defaults -> global_default -> code_default_constants`.
- Economics formula fields and source tracing are exposed in `explanation.meta.alpha_proxy_economics`.
- Admin economics defaults are persisted/read via production-order settings API.
- Global economics defaults are persisted on `global_planning_settings` and migrated via
  `alembic/versions/0014_add_production_order_economics_defaults.py`.
- Layer 4 now emits money fields and risk proxies per scenario.
- Capital-gap transparency is emitted in `explanation.meta.capital_gap`.
- Layer 2 now emits canonical expected-gross-profit aliases in parallel with legacy
  profit naming (decision fields, reason counts, decision-gate labels) to keep
  transition safe for existing clients.
- Layer 2 default presentation now uses canonical expected-gross-profit wording
  (`method`, `decision_gate`) while explicit legacy aliases remain available
  (`legacy_method`, `legacy_decision_gate`) for transition safety.
- from-WB adapter now derives observed realized prices from WB revenue window and applies
  them as runtime economics source `from_wb_observed_window` with deterministic anomaly
  filtering (`max deviation=30%`) and explainability diagnostics.
- Additional regressions now cover economics tracing by source tier (request/admin/global/code-default) and Layer 4 money fields.
- Full verification gate evidence is green in docker-capable environment (`verify-live` + production-order smoke `200/404/422`).

## Next implementation checkpoint
- Integrate remaining API-driven economics calibration inputs (variable commission/cost
  components beyond observed realized price window) into admin/global defaults while keeping
  source traceability and deterministic fallback behavior.
