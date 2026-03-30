# STATUS - maconly-supply-brain-backend

## Current stage

Planning Core v1 contract is active, monitoring APIs are active, scheduler single-instance guard is implemented, and engineering quality gates are now scaffolded.

## Implemented now (code-backed)

- FastAPI app mounts `api_router` under `/api/v1` and starts `MonitoringScheduler` on startup.
- FastAPI lifecycle migrated from deprecated `@app.on_event` hooks to lifespan context manager; scheduler start/stop now runs via `lifespan`.
- Monitoring scheduler uses PostgreSQL advisory lock (`pg_try_advisory_lock` / `pg_advisory_unlock`) via a dedicated connection (`engine.raw_connection`) to keep one writer in multi-instance runtime.
- Monitoring API includes:
  - `GET /api/v1/planning/monitoring/timeseries`
  - `GET /api/v1/planning/monitoring/risk-focus`
- Tests exist for both new monitoring endpoints:
  - `tests/test_monitoring_timeseries_api.py`
  - `tests/test_monitoring_risk_focus_api.py`
- Planning Core v1 endpoints are mounted and return structured responses:
  - `GET /api/v1/planning/core/health`
  - `POST /api/v1/planning/core/proposal` (legacy stub / low-fidelity / deprecated)
- Planning proposal service currently has minimal DB-backed hook: reads SKU rows and returns deterministic `lines` with `recommended_units=0` and `reason="data_hook_only"`; it is not the primary production-order path.
- Planning Core production-order proposal endpoint added:
  - `POST /api/v1/planning/core/production-order/proposal`
  - `POST /api/v1/planning/core/production-order/proposal/from-wb`
  - Handles article settings, model-B deficit conversion, minima (fabric/elastic), alternatives, and explanation blocks.
  - Direct production-order prerequisite failures are now operator-facing and structured: missing bundle recipes and missing SKU scope for recipe colors return machine-readable `400` payloads with `code`, `message`, affected IDs, and deterministic `next_steps` instead of plain strings.
  - Production-order settings admin validation failures are now operator-facing and structured: invalid size ids, elastic bindings outside article scope, assorti bundle type mismatches, and invalid in-flight color/size pairs return machine-readable `400` payloads with `code`, `field`, affected IDs, and deterministic `next_steps`.
  - WB live-sync onboarding now also exposes structured WB account-resolution blockers: missing active account, unknown `account_id`, and empty `api_token` return machine-readable `400` payloads with `code`, optional `account_id`, and deterministic `next_steps`.
  - WB transport/response helper failures are now machine-readable too: request/network failures, `429` rate limits, `401` token errors, invalid JSON, and invalid rows-format responses return structured payloads with deterministic `code`, remediation `next_steps`, and transport metadata when available.
  - WB object-style helper responses now follow the same contract: `_wb_get_json_object` returns structured `wb_api_invalid_object_format` details instead of a raw string when an object endpoint returns a non-object payload.
  - Operator-facing `404` paths are now aligned on a machine-readable `article_not_found` contract across direct proposal, `from-wb` proposal, production-order settings, and WB readiness surfaces (`code`, `message`, `article_id`, `next_steps`) instead of raw strings.
  - `GET /api/v1/planning/config-snapshot` now uses structured `404` details for both missing articles (`article_not_found`) and missing planning config (`no_planning_settings_found`), including `article_id` and deterministic `next_steps`.
  - Read-only article surfaces continue the same contract: `GET /api/v1/planning/article-dashboard/{article_id}` and `GET /api/v1/planning/article-bundle-snapshot` now return structured `article_not_found` details instead of raw strings.
  - `GET /api/v1/planning/bundle-availability` now also exposes structured lookup/prerequisite failures: missing article, bundle type, warehouse, and missing bundle recipe return deterministic machine-readable details instead of raw strings.
  - `from-wb` adapter path auto-builds `bundle_daily_sales` and `bundle_stock` from WB-ingested tables (`article_wb_mapping`, `wb_sales_daily`, `wb_stock`) and then runs the same proposal engine.
  - `from-wb` explanation now includes requested/effective `as_of_date` source trace, resolved sales window bounds, and adapter snapshots for `daily_sales_by_bundle`, `wb_stock_by_bundle`, and `wb_stock_updated_at_by_bundle` to make WB-derived input reconstruction auditable.
  - `from-wb` explanation now also includes WB data freshness snapshot (`freshness_status`, sales age, oldest stock age, stock age by bundle, and stale thresholds) to surface stale/no-data ingestion risk inline with the proposal.
  - `from-wb` now derives observed realized prices from WB sales revenue window (`wb_sales_daily.revenue / sales_qty`) and injects them as runtime economic calibration input source `from_wb_observed_window` when request-level overrides are absent.
  - `from-wb` observed-price calibration applies deterministic anomaly filtering (`max deviation=30%` from rolling accepted baseline) and exposes diagnostics in `explanation.meta.from_wb.economic_observed_prices` (window, prices, sample counts, anomaly-filtered count).
  - `from-wb` request now supports `freshness_mode`: `warn` (default, attach freshness diagnostics) and `strict` (fail fast with 400 when freshness status is not `fresh`, including stale/no-data WB datasets).
  - `from-wb` request now supports per-request freshness thresholds (`freshness_sales_stale_after_days`, `freshness_stock_stale_after_days`) with source tracing (`global_default` / `admin_defaults` / `request`) in both text explanation and `explanation.meta.from_wb.freshness.threshold_source`.
  - Freshness threshold precedence for `from-wb` is now `request > admin_defaults > global_default`; admin defaults are managed via production-order settings API and persisted on article-level settings.
  - Core production-order reorder policy now applies `safety_stock_days` from planning settings (`reorder_point_days = lead_time_days_total + safety_stock_days`) and exposes this in explanation step + `explanation.meta.reorder_policy`.
  - Core production-order now emits Layer 1 deterministic stock-health metrics per SKU (`velocity_main`, `velocity_assorti`, `coverage_days`, `current_stock`, `in_flight`, `eta_days`, `gross_margin` proxy, `capital_locked` proxy, `stockout_risk`, `overstock_risk`) plus contract checks (`risk_bounds`, `non_negative_*`, unique color-size keys) via `explanation.meta.layer_1_stock_health`.
  - Assorti bundle classification now uses deterministic precedence: `bundle_type.is_assorti` (primary) -> admin mapping (`article_planning_settings.production_order_assorti_bundle_type_ids`) -> global mapping (`global_planning_settings.default_production_order_assorti_bundle_type_ids`) -> main default, with source tracing in explanation step and `explanation.meta.layer_1_stock_health.assorti_classification`.
  - Core production-order now emits Layer 2 deterministic allocation comparison with compatibility aliases: legacy profit labels (`profit_if_main_until_eta` / `profit_if_assorti_until_eta`) plus canonical expected-gross-profit labels (`expected_gross_profit_if_main_until_eta` / `expected_gross_profit_if_assorti_until_eta`) in `explanation.meta.layer_2_allocation.decisions`.
  - Layer 2 default presentation now uses canonical composite-objective wording (`method=time_window_composite_objective_with_gmroi_diagnostics`, `decision_gate=composite_objective_until_eta`) while preserving explicit legacy aliases (`legacy_method=time_window_profit_proxy_with_gmroi_diagnostics`, `legacy_decision_gate=profit_until_eta`) with deterministic tie-break `hold` and GMROI diagnostic-only behavior.
  - Layer 2 helper contracts now require explicit economics inputs (`margin_main_per_unit`, `margin_assorti_per_unit`, `unit_capital_per_unit`) instead of proxy defaults, preventing silent fallback to `LAYER2_*_PROXY` values in runtime/refactor paths.
  - Layer 2 now exposes deterministic decision-quality diagnostics (`decision_reason_counts`, canonical `decision_reason_counts_expected_gross_profit`, tie/near-tie counts, average profit/GMROI gaps, capital-locked aggregates, canonical `near_tie_objective_gap_threshold` with legacy `near_tie_profit_gap_threshold` alias) in `explanation.meta.layer_2_allocation.decision_quality`, including compact-mode projection.
  - Layer 2 floating-boundary behavior is stabilized by normalizing emitted profit/GMROI diagnostics to 4 decimals before deriving decision flags (`allocation_decision`, `tie_break_applied`, `near_tie`), and regression now locks this rounding-boundary contract consistency.
  - Layer 2 now emits explicit legacy-alias deprecation-plan diagnostics (`deprecated_after`, policy, legacy gate aliases, canonical replacement map) in `decision_quality`, `explanation.meta.layer_2_allocation`, and `explanation.meta.alpha_proxy_economics.layer_2_legacy_alias_deprecation_plan` while keeping aliases non-breaking during the transition window.
  - Economic Alpha now emits trusted-economics diagnostics in both full/compact explainability (`explanation.meta.economics_trust`, `explanation.meta.warnings`) and in `alpha_proxy_economics` (`economics_trust_level`, trust payload): per-key-field source map, code-default key-field count, and code-default dominance ratio drive deterministic trust levels (`trusted|partial|untrusted`) with explicit warning codes/severity.
  - Production-order capital governance is now strict at API runtime: if `available_capital` cannot be resolved from `request|admin_defaults|global_default`, proposal calculation fails with deterministic `422` and actionable detail (`capital_constraint_status=missing_available_capital_strict`, `severity=HIGH`) for both direct and from-WB flows.
  - Narrow R5 modularization has started in facade-preserving mode: the shared economics helper cluster now lives in `app/services/planning_production_order_economics.py`, while `app/services/planning_production_order.py` preserves the existing external service surface and test imports via re-exported names.
  - The second narrow R5 extraction slice is now complete for compact explainability projection: `app/services/planning_production_order_explainability.py` owns compact-step/meta shaping, while `app/services/planning_production_order.py` continues to preserve compatibility imports and runtime behavior.
  - The third narrow R5 extraction slice is now complete for assorti classification support: `app/services/planning_production_order_assorti.py` owns assorti mapping parse/load helpers and source constants, while `app/services/planning_production_order.py` preserves compatibility imports and deterministic Layer 1 explainability semantics.
  - The fourth narrow R5 extraction slice is now complete for layer-proxy settings resolution: `app/services/planning_production_order_layer_proxy.py` owns proxy default coefficients, precedence/source tracing, and threshold-clamp behavior, while `app/services/planning_production_order.py` preserves compatibility imports and runtime response semantics.
  - Core production-order response now emits explicit physical stock-scope contract fields at the top level (`physical_scope`) and mirrors the same machine-readable block in `explanation.meta.physical_scope`; compact mode preserves the block unchanged.
  - Core production-order response now emits deterministic arrival-horizon projection at the top level (`arrival_projection`) and mirrors it in `explanation.meta.arrival_projection`; projection basis includes ready bundles, competition-aware raw bundle capacity, and effective in-flight capacity at arrival.
  - Arrival-horizon projection now participates in the live recommendation guardrail on the production-order facade: `safe_cover_until_arrival` can deterministically force `recommendation.action=wait`, while `shortage_before_arrival` can escalate action risk without changing the stable risk-level contract into a deep simulator.
  - Constraint-based supply alignment has now completed Phase 1 on the production-order path: explicit per-article resource allocation (`color x size`) is emitted via `constraints_applied.resource_allocation` and `explanation.meta.resource_allocation`, shared resource competition across bundle strategies is represented as a reservation ledger instead of a hidden estimate, and runtime contract checks now assert no double-use / allocation-sum consistency in both full and compact responses.
  - Constraint-based supply alignment now includes Phase 2 cross-article pantone linking on the same production-order facade: sibling articles that share a pantone contribute a WB-sales-based proxy demand pool, fabric minimum batching now evaluates against `required + sibling_proxy_required`, and the applied shared-pool evidence is emitted in both `constraints_applied.fabric_min_batches[*].shared_pool_required|sibling_proxy_required` and `explanation.meta.shared_color_pool` for full/compact responses.
  - Legacy planning endpoints are now explicitly marked low-fidelity/deprecated at runtime rather than relying on tribal knowledge: `/api/v1/planning/core/proposal` and `/api/v1/planning/order-proposal` both emit `Deprecation`, `X-Planning-Fidelity`, and `X-Planning-Successor` headers with no new business logic added.
  - Multi-regime e2e release evidence is now explicit and regression-locked for three economics regimes (`stockout_dominates`, `overstock_dominates`, `commission_price_conflict`): each case proves deterministic objective-vs-profit disagreement and expected Layer 5 intervention signals.
  - Penalty-weight calibration evidence is now documented in the decision-quality casebook with approximate flip boundaries, while regression now asserts emitted/frozen Layer 2 objective parameters (`capital_cost_rate=0.08`, `stockout_penalty_weight=1.0`, `overstock_penalty_weight=1.0`) and objective-source tracing (`code_default_constants`) in explainability payloads.
  - Layer 2 contract summary is now emitted in `explanation.meta.layer_2_allocation.contract` (version/status/checks for summary consistency, allocation-vs-composite-objective-gate consistency with legacy alias compatibility, non-negative metrics, positive ETA, tie-break invariants, decision-reason mapping, tie/near-tie objective-gap consistency with legacy profit-gap aliases, profit/GMROI/objective-score gap consistency, and capital metric sanity) and projected in compact explainability mode.
  - Layer 2 helper + API compact/full regressions now explicitly assert canonical tie/near-tie contract keys (`tie_break_applied_matches_objective_tie`, `near_tie_matches_objective_gap_threshold`) and canonical objective-gap threshold tracing, while preserving legacy alias assertions for backward compatibility.
  - Layer 2 contract hardening now includes objective-component formula integrity check (`objective_score = expected_gross_profit - capital_cost_penalty - stockout_penalty - overstock_penalty`) and objective-score decision-reason consistency check (`decision_reason_objective_score` must match allocation) to prevent silent non-composite fallback and malformed explainability drift.
  - Stable-alpha acceptance checklist now has sections 1-12 fully checked, including scope/API stability, Layer 1-5 contracts, explainability, from-WB freshness, decision-quality casebook evidence, Economic Alpha transition-block criteria, verification gate criteria, and documentation-discipline criteria, based on locked regressions and successful `verify`/`verify-live` runs.
  - Capital-aware line ranking/constraint evidence is now helper + API regression locked: objective-per-capital ranking can deterministically prioritize lower gross-profit lines when penalties dominate, budget-limited allocation follows this ranking rather than silent profit-only ordering, and proposal meta exposes deterministic ranking/cutoff behavior (including partial-cutoff allocation).
  - Shared-capital ranking tie-break is now explicit for equal objective metrics: higher `stockout_risk` first, then lower `overstock_risk`, preserving deterministic availability-priority allocation under constrained capital.
  - Capital-constraint meta now includes contract summary (`version`, `status`, `checks`) with deterministic runtime checks for budget accounting, constrained-status consistency, line-count invariants, ranking sort/uniqueness, risk-priority score consistency (`stockout_risk - overstock_risk`), and cutoff-line consistency; compact explainability preserves this contract block.
  - Core production-order Layer 3 purchase shaping now deterministically applies Layer 2 decisions (`main|assorti|hold`) with risk-weighted calibration (stockout boost + overstock dampening + bounded factors), and exposes calibration diagnostics via `explanation.meta.layer_3_purchase_shaping`.
  - Regression now explicitly locks Layer 3 semantics as quantity-shaping only: Layer 3 calibration overrides change shaped quantities/reorder units while Layer 2 allocation summary and per-line decisions remain unchanged.
  - Layer 3 contract summary is now emitted in `explanation.meta.layer_3_purchase_shaping.contract` (version/status/checks for qty delta invariants, decision/risk partition consistency, calibration method/bounds, and factor summary sanity) and projected in compact explainability mode.
  - Core production-order Layer 4 now emits deterministic scenarios (Conservative/Balanced/Aggressive) with per-scenario money and risk outputs: `total_capital_required`, `expected_revenue`, `expected_gross_profit`, `expected_margin_percent`, `expected_turnover_days`, `expected_turnover_proxy`, `stockout_probability_proxy`, `stockout_risk_proxy`, `overstock_risk_proxy`, and assorti sustainability proxy/impact via `explanation.meta.layer_4_scenarios`.
- Layer 4 now also emits deterministic delta outputs for scenario comparability: per-scenario `capital_delta_vs_balanced`, `expected_revenue_delta_vs_balanced`, `expected_gross_profit_delta_vs_balanced` (legacy alias `gross_profit_delta_vs_balanced` retained), `objective_score_delta_vs_balanced`, plus aggregate `aggressive_vs_conservative` deltas (`capital_delta`, `expected_revenue_delta`, `gross_profit_delta`, `objective_delta`) in both full and compact explainability metadata.
- Layer 4 contract summary now validates scenario delta runtime integrity (`scenario_delta_fields_present`, `scenario_deltas_match_balanced`) to catch missing/malformed delta fields and balanced-baseline drift in explainability outputs.
  - Core production-order now emits capital-gap transparency block in `explanation.meta.capital_gap` (`available_capital`, `required_capital`, `deficit_or_surplus`) without automatic policy enforcement.
  - Core production-order Layer 5 now emits deterministic threshold-policy intervention signals via `explanation.meta.layer_5_intervention`: unavoidable threshold drives `increase_price_to_slow_velocity`, severe threshold drives `accelerate_production`, and severe + in-flight allows deterministic dual-signal output.
  - Layer 5 contract summary is now emitted in `explanation.meta.layer_5_intervention.contract` (version/status/checks for threshold sanity, signal validity/order, and reason-policy consistency) and projected in compact explainability mode.
  - Layer 5 signal-only semantics are regression-locked: threshold changes can alter intervention signals, while recommendation action remains unchanged for equivalent planning state.
  - Core production-order now exposes `explanation.meta.alpha_proxy_economics` with effective alpha proxy values and source tracing for layer thresholds/calibration/factors (Layer 1 stockout threshold, Layer 3 calibration params/bounds, Layer 4 contract version, Layer 5 intervention thresholds), plus Economic Alpha kickoff fields (`economics_formula_version`, `economic_calibration_state`, `economic_inputs`, `economic_source`).
  - Production-order request overrides now include economics calibration knobs (`production_cost_per_unit`, `logistics_cost_per_unit`, `wb_commission_percent_main|assorti`, `average_realized_price_main|assorti`, `available_capital`) and are wired into deterministic margin/capital calculations.
  - Layer 3 calibration coefficients and Layer 5 intervention thresholds now support deterministic precedence (`request > admin_defaults > global_default > code_default_constants`) with source tracing in `alpha_proxy_economics.layer_proxy_source` and safe threshold-order clamping for Layer 5.
  - Admin settings API now supports Layer 3/5 calibration thresholds with validation and persistence; request overrides support same thresholds with precedence and validation.
  - Production-order explanation now exposes machine-readable `explanation.meta` alongside textual `steps`; from-WB adapter writes a dedicated `meta.from_wb` block (as_of trace, sales window bounds, sales/stock snapshots, freshness snapshot) while core planner writes structured source/economic-buffer/elastic/in-flight details.
  - Production-order direct/from-WB now supports explainability payload modes: `full` (default) and `compact`; compact mode preserves deterministic outputs while trimming heavy explanation arrays/maps and adds explicit `explanation.meta.explainability` mode tracing.
  - Unknown `article_id` handling is now aligned across production-order APIs: both direct and from-WB return deterministic `404` with `detail="Article not found"` before downstream mapping/validation checks.
  - Regression coverage now includes compact/full deterministic parity checks for direct and from-WB proposal flows and explicitly asserts compact mode preserves key contract blocks (`layer_1`, `layer_2`, `layer_3`, `layer_4`, `layer_5`, `alpha_proxy_economics`).
  - Compact/full parity regression now additionally covers profile-based direct and from-WB scenarios (stockout/balanced/overstock style demand-stock inputs) and asserts Layer 2 `decision_quality` diagnostics plus Layer 2 contract decision-quality consistency checks are retained in compact metadata, while Layer 2 compact-step readability fields (`decision_gate`, `reason_counts`, average profit gap, capital locked, contract status) remain present.
  - Explicit release-gate checklist published: `PRODUCTION_ORDER_V1_STABLE_ALPHA_CHECKLIST.md`.
  - Decision-quality casebook published: `PRODUCTION_ORDER_V1_DECISION_QUALITY_CASEBOOK.md` with 3 deterministic SKU profiles (stockout/balanced/overstock), each documenting input metrics, `L1->L5` outputs, allocation reasoning, reorder quantity, scenario comparison, and capital impact proxy.
  - Deterministic decision-quality regression harness now includes both precomputed-metric and full helper-chain coverage (`test_decision_quality_case_studies_are_deterministic`, `test_decision_quality_case_studies_are_deterministic_across_layer1_to_layer5`) to lock canonical stockout/balanced/overstock behavior across `L1 -> L5`, including reorder quantity, scenario capital deltas, intervention signals, and recommendation action outcomes.
  - Layer-integrity guardrails are explicit in release criteria: Layer 2 uses canonical composite-objective comparison with legacy profit/expected-gross-profit alias compatibility, Layer 3 remains quantity-shaping (does not replace Layer 2 gate), and Layer 5 remains signal-only (does not enforce recommendation action).
  - `from-wb` now clamps future `as_of_date` requests to latest available WB sales date to prevent drifted/empty future windows.
  - `from-wb` validates requested `bundle_type_ids` against `article_wb_mapping` and returns 400 on missing mappings.
  - In-flight supply now uses ETA/stage-sensitive effective contribution (not binary include/exclude), and explanation reports raw/effective in-flight qty.
  - Elastic minima now respect admin elastic binding scope: active bindings select applicable elastic types for current candidate lines; non-matching binding scope does not force elastic minimum uplift.
  - Explanation now includes elastic uplift trace (`delta`, `scope`, `affected_lines`, `line_keys`, `line_alloc`) for easier audit/debug of minimum-batch adjustments.
  - Economic buffer policy is now applied for warning/critical risk zones when `allow_order_with_buffer=true`; explanation includes buffer days and adjusted target horizon.
  - Raw bundle potential now uses competition-aware allocation across bundle types that share colors, with per-bundle breakdown in explanation.
  - Bundle stock input now supports WB ingestion fallback: if request omits `bundle_stock` entries, planner fills missing bundle types from `article_wb_mapping + wb_stock`.
  - Production-order request/admin schemas migrated to Pydantic v2 validator APIs (`@field_validator`/`@model_validator`) to reduce deprecation surface without changing API contract.
  - Current physical-scope / arrival-projection / legacy-marker block has been regression-validated with `python -m pytest tests/test_planning_core_production_order_api.py -q`, `python -m pytest tests/test_end_to_end_planning.py -q`, and `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 verify`; `verify-live` was intentionally not rerun in this block.
- WB ingestion reliability fix:
  - `POST /api/v1/wb/sales-daily/import` now stamps `created_at` on inserts to satisfy DB NOT NULL constraints and keep WB→planning adapter flow stable.
  - Added live WB pull endpoints using configured active `wb_integration_accounts.api_token`:
    - `POST /api/v1/wb/sales-daily/sync-live` (fetches WB reports sales feed `/api/v1/supplier/sales`, paginates by `lastChangeDate`, upserts into `wb_sales_daily`)
    - `POST /api/v1/wb/stock/sync-live` (fetches WB reports stock feed `/api/v1/supplier/stocks`, paginates by `lastChangeDate`, aggregates per SKU total, upserts into `wb_stock` as `warehouse_name=WB_TOTAL`)
    - `POST /api/v1/wb/commission/sync-live` (fetches WB tariff commissions from `common-api /api/v1/tariffs/commission`, returns top subject diagnostics and aggregate commission percent stats)
    - `POST /api/v1/wb/supplies/sync-live` (fetches WB supplies statuses from `supplies-api POST /api/v1/supplies`, returns status distribution and supply snapshot rows)
    - `POST /api/v1/wb/article-mapping/sync-live` (fetches sales feed and derives candidate `(supplierArticle, barcode)` pairs, matches `supplierArticle -> article.code` via exact + normalized matching, and upserts matched pairs into `article_wb_mapping` with optional `default_bundle_type_id`)
    - `POST /api/v1/wb/article-mapping/discover-live` (returns top supplier-article candidates from WB sales feed with rows/SKU cardinality and match diagnostics `exact|normalized|none|ambiguous_normalized` to prepare local article-code alignment)
    - `POST /api/v1/wb/article/bootstrap-live` (derives top `supplierArticle` codes from WB sales feed and bootstraps missing local `article` rows with `dry_run` preview mode)
    - `POST /api/v1/wb/from-wb/readiness` (audits mapped articles against `bundle_recipe` coverage plus WB sales/stock presence and returns explicit blockers before `/core/production-order/proposal/from-wb` calls)
  - WB HTTP request helper now auto-retries `429 Too Many Requests` with bounded backoff based on `X-Ratelimit-Retry` / `Retry-After` before failing, reducing manual rerun noise during live sync across reports/tariffs/supplies clients.
  - Live sync response now includes operational counters (`fetched_rows`, `inserted`, `updated`, `pages_requested`, `pages_with_data`, effective cursor/date-from) for auditability.
  - Added API + helper regressions for live sync flow in `tests/test_wb_live_sync_api.py` (missing active account guard, sales aggregation/upsert, stock aggregation/upsert, commission/supplies sync summaries, article-mapping live exact/normalized match accounting, discover-live diagnostics response, article bootstrap dry-run/insert modes, from-WB readiness blocker reporting, and 429 retry/backoff helper behavior).
- Planning Core from-WB economics calibration extended:
  - `/api/v1/planning/core/production-order/proposal/from-wb` now attempts live WB tariffs commission calibration (`common-api /api/v1/tariffs/commission`) and injects normalized commission ratios as runtime economics when available.
  - Runtime economic source tracing now supports per-field source overrides (e.g., prices from observed WB sales window + commissions from tariffs API in the same call).
  - Explanation metadata now exposes `from_wb.economic_observed_commission` in full/compact modes (`status`, `reason`, `commission_percent`, stats), and WB adapter step text includes commission calibration diagnostics.
  - Added regression coverage in `tests/test_planning_core_production_order_api.py` for live commission calibration application and default unavailable diagnostics when no active WB account exists.
- Planning Core production-order admin settings endpoints added:
  - `GET /api/v1/planning/core/production-order/settings/{article_id}`
  - `PUT /api/v1/planning/core/production-order/settings/{article_id}`
  - Covers admin-managed inputs for size weights, elastic bindings (SKU/color), in-flight defaults, and assorti fallback mapping (`assorti_bundle_type_ids`).
- Production-order admin settings persistence added:
  - `production_order_size_weight_settings`
  - `production_order_elastic_bindings`
  - `production_order_in_flight_supply_defaults`
  - `production_order_assorti_bundle_type_ids`
  - `production_order_freshness_sales_stale_after_days`
  - `production_order_freshness_stock_stale_after_days`
  - `production_order_layer3_stockout_boost_max`
  - `production_order_layer3_overstock_dampen_max`
  - `production_order_layer5_unavoidable_stockout_risk_threshold`
  - `production_order_layer5_accelerate_production_risk_threshold`
  - `production_order_production_cost_per_unit`
  - `production_order_logistics_cost_per_unit`
  - `production_order_wb_commission_percent_main`
  - `production_order_wb_commission_percent_assorti`
  - `production_order_average_realized_price_main`
  - `production_order_average_realized_price_assorti`
  - `production_order_available_capital`
- Global planning settings persistence added:
  - `default_production_order_size_weight_settings`
  - `default_production_order_elastic_bindings`
  - `default_production_order_in_flight_supply_defaults`
  - `default_production_order_assorti_bundle_type_ids`
  - `default_production_order_freshness_sales_stale_after_days`
  - `default_production_order_freshness_stock_stale_after_days`
  - `default_production_order_layer3_stockout_boost_max`
  - `default_production_order_layer3_overstock_dampen_max`
  - `default_production_order_layer5_unavoidable_stockout_risk_threshold`
  - `default_production_order_layer5_accelerate_production_risk_threshold`
  - `default_production_order_production_cost_per_unit`
  - `default_production_order_logistics_cost_per_unit`
  - `default_production_order_wb_commission_percent_main`
  - `default_production_order_wb_commission_percent_assorti`
  - `default_production_order_average_realized_price_main`
  - `default_production_order_average_realized_price_assorti`
  - `default_production_order_available_capital`
- Alembic migration added for economics defaults columns:
  - `alembic/versions/0014_add_production_order_economics_defaults.py`
- Planning config snapshot now exposes global production-order economics defaults in
  `global_settings.experimental` for deterministic auditability.
- Tests added for production-order endpoint:
  - `tests/test_planning_core_production_order_api.py`
  - Economic precedence regressions now cover request, admin defaults, global defaults,
    and code-default fallback source tracing for Economic Alpha inputs.
  - Added deterministic end-to-end release regression where identical units-until-ETA with only realized-price change flips Layer 2 allocation (`main -> assorti`) and proves runtime sensitivity to real margin inputs.
  - Added deterministic multi-regime e2e regression (`stockout_dominates` / `overstock_dominates` / `commission_price_conflict`) proving objective-vs-profit disagreement, expected Layer 5 signals, and emitted Layer 2 objective-parameter/source payload assertions.
  - Added helper-level guard regression that fails when Layer 2 helper is invoked without explicit economics inputs.
  - Added from-WB economics regressions validating observed revenue-price calibration source propagation and deterministic anomaly filtering behavior for price spikes.
  - Layer 2 regressions now lock canonical expected-gross-profit aliases (`expected_gross_profit_*`, canonical decision-gate/reason-count fields) while preserving legacy fields for compatibility.
- Layer 2 regressions now include explicit violated-case coverage for objective-component formula mismatch, objective-score-gap mismatch, and objective-score decision-reason mismatch while preserving valid-case `contract.status=ok` assertions under canonical composite-objective gating.
- Added helper/API-level economic evidence regressions for objective-per-capital ranking, budget-constrained allocation ordering (including partial cutoff), and proposal-meta capital-constraint ranking/cutoff reporting, plus Layer 4 violated-case regression for scenario delta baseline inconsistency.
- Added capital-constraint contract regressions for valid/violated helper payloads and compact/full API assertions that `capital_constraint.contract.status` remains `ok` on valid flows.
  - Validation regressions now explicitly assert deterministic 422 details for production-order direct/from-WB schema errors (invalid literals, duplicate IDs, invalid threshold ordering, multi-field validation failures).
- Tests added for production-order admin settings:
  - `tests/test_planning_core_production_order_settings_api.py`
  - Roundtrip and proposal regressions now assert economics defaults persistence and
    admin-default source propagation in `alpha_proxy_economics`.
- Pydantic v2 migration hardening completed across monitoring/core schema surfaces:
  - Replaced deprecated `@validator`/`@root_validator` with `@field_validator`/`@model_validator` where applicable.
  - Replaced legacy `class Config(orm_mode=True)` with `model_config = ConfigDict(from_attributes=True)` in touched read schemas.
  - Replaced mutable list defaults with `Field(default_factory=list)` in touched schemas.
- WB API discovery and onboarding docs added:
  - `docs/wb_api_capabilities_and_token_setup.md` now maps available WB API sections/capabilities (Content, Marketplace, Statistics, Finance, Analytics, Promotion, Questions/Reviews, Prices/Discounts, Buyer Chat, Supplies, Returns, Documents) with key endpoint examples and host domains.
  - The same doc includes an explicit secure token onboarding runbook for current backend state (DB-level insert/update into `wb_integration_accounts`), plus verification steps confirming API responses do not expose tokens.
- Local verify workflow hardening:
  - Added `pytest` and `httpx` to image dependencies so `scripts/dev.ps1 verify` no longer performs ad-hoc pip installs inside running backend containers.
  - Added backend-running wait gate after `up -d --build backend` to avoid dependency-check race when container is still starting.
  - Added `scripts/dev.ps1 po-api-smoke-positive` for deterministic seeded live happy-path checks of production-order endpoints (`health=200`, direct/from-WB=`200`).
  - Added `scripts/dev.ps1 po-api-smoke` for deterministic live connectivity checks of production-order endpoints (`health=200`, seeded direct/from-WB happy-path requests=`200`, schema-invalid direct/from-WB requests=`422`).
  - Added `scripts/dev.ps1 verify-live` to run full local gate in one command (`verify` + production-order live API smoke with `200/404/422` contract assertions).
- `scripts/dev.ps1` Docker-backed verify/smoke path is hardened against transient Docker Hub auth/buildkit failures (`failed to fetch anonymous token` / `auth.docker.io/token`): backend build now auto-retries with `DOCKER_BUILDKIT=0` and then restores previous env state.

## Active strategic correction (CTO-aligned)

- Priority is explicitly shifted to `Production Order v1 Economic Alpha`: migrate from proxy-only economics to formula-based, source-traceable money calculations.
- Explainability/contracts remain important but are now constrained to behavior-critical checks while economics calibration is in progress.
- Scope guard is unchanged and strict: no ML, no solver optimization, no multi-warehouse rollout.
- Decision traceability discipline is active: each accepted architectural/product decision is documented automatically in the same work block.
- Mandatory update set after each accepted decision: `ROADMAP.md` (plan), `STATUS.md` (state), and the relevant acceptance artifact (`PRODUCTION_ORDER_V1_STABLE_ALPHA_CHECKLIST.md` / casebook / ADR).
- Governance baseline added:
  - CI pipeline: `.github/workflows/ci.yml`
  - Context synchronization guard in CI: `scripts/context_guard.py`
  - PR template: `.github/pull_request_template.md`
  - Contribution rules and DoD: `CONTRIBUTING.md`
  - Release policy: `RELEASE_POLICY.md`
  - ADR process: `docs/adr/`
  - CODEOWNERS scaffold: `.github/CODEOWNERS`

## Known operational friction

- Running commands from a non-repo directory causes `not a git repository`.
- Docker Desktop engine may be unavailable (`dockerDesktopLinuxEngine` pipe error).
- Docker Hub auth endpoint may intermittently return EOF during buildkit image pull; verify/smoke scripts now auto-retry backend build with `DOCKER_BUILDKIT=0`.
- Host Python may miss `pytest`; prefer Docker-based test runs or install dev deps.
- PowerShell JSON quoting can break curl payloads; file-based `--data-binary "@..."` is the safe default.
- `.github/CODEOWNERS` currently contains a placeholder owner and must be replaced with a real GitHub handle/team before enabling required reviews.

## Verification commands (PowerShell, reproducible)

```powershell
git status -sb
git log -1 --oneline
docker compose -f .\docker-compose.yml up -d --build
docker compose -f .\docker-compose.yml ps
docker compose -f .\docker-compose.yml logs --tail=200 backend
curl.exe -i http://localhost:8000/api/v1/planning/core/health
# Legacy low-fidelity stub:
'{"sales_window_days":30,"horizon_days":90}' | Set-Content -Encoding utf8 -NoNewline test_request.json
curl.exe -i -X POST http://localhost:8000/api/v1/planning/core/proposal -H "Content-Type: application/json" --data-binary "@test_request.json"
# Primary production-order path:
curl.exe -i -X POST http://localhost:8000/api/v1/planning/core/production-order/proposal -H "Content-Type: application/json" --data-binary "@po_request.json"
.\scripts\dev.ps1 context
docker compose -f .\docker-compose.yml exec -T db psql -U maconly -d maconly_db -c "SELECT count(*) FROM monitoring_snapshots;"
```

## Last verification

- Date: `2026-03-28 23:26 +07:00`
- Branch: `feature/po-layer1-layer2-foundation`
- Last commit (`git log -1 --oneline`): `2af7a73`
- Gates:
  - `python -m pytest -q tests/test_planning_core_production_order_api.py` → `111 passed`
  - `python -m pytest -q tests/test_end_to_end_planning.py` → `3 passed`
  - `.\scripts\dev.ps1 verify` → `OK`
  - `.\scripts\dev.ps1 verify-live` → `not rerun in this block` (deferred live/unsafe gate)

### Minimal raw outputs

```text
$ python -m pytest -q tests/test_planning_core_production_order_api.py
........................................................................
.......................................                                    [100%]
111 passed in 159.19s (0:02:39)
```

```text
$ python -m pytest -q tests/test_end_to_end_planning.py
...                                                                       [100%]
3 passed in 7.86s
```

```text
$ .\scripts\dev.ps1 verify
[verify] context guard...
[verify] compile check...
[verify] smoke tests...
[verify] OK
```

```text
$ .\scripts\dev.ps1 verify-live
[verify-live] context guard...
[verify-live] compile check...
[verify-live] smoke tests...
[verify-live] production-order live API smoke...
[po-api-smoke] OK  planning-core-health -> HTTP 200
[po-api-smoke] OK  production-order-direct-happy-path -> HTTP 200
[po-api-smoke] OK  production-order-from-wb-happy-path -> HTTP 200
[po-api-smoke] OK  production-order-direct-unknown-article -> HTTP 404
[po-api-smoke] OK  production-order-from-wb-unknown-article -> HTTP 404
[po-api-smoke] OK  production-order-direct-validation -> HTTP 422
[po-api-smoke] OK  production-order-from-wb-validation -> HTTP 422
[verify-live] OK
```

### Interpretation

- Production-order economic-objective verification gates are green locally (`verify` + `verify-live`).
- Live API smoke confirms deterministic contract behavior for success and error paths (`200/404/422`).
- Docker build retry fallback reduced nondeterministic local failures caused by transient Docker Hub auth/buildkit issues.
