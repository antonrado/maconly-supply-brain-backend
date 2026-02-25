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
  - `POST /api/v1/planning/core/proposal`
- Planning proposal service currently has minimal DB-backed hook: reads SKU rows and returns deterministic `lines` with `recommended_units=0` and `reason="data_hook_only"`.
- Planning Core production-order proposal endpoint added:
  - `POST /api/v1/planning/core/production-order/proposal`
  - `POST /api/v1/planning/core/production-order/proposal/from-wb`
  - Handles article settings, model-B deficit conversion, minima (fabric/elastic), alternatives, and explanation blocks.
  - `from-wb` adapter path auto-builds `bundle_daily_sales` and `bundle_stock` from WB-ingested tables (`article_wb_mapping`, `wb_sales_daily`, `wb_stock`) and then runs the same proposal engine.
  - `from-wb` explanation now includes requested/effective `as_of_date` source trace, resolved sales window bounds, and adapter snapshots for `daily_sales_by_bundle`, `wb_stock_by_bundle`, and `wb_stock_updated_at_by_bundle` to make WB-derived input reconstruction auditable.
  - `from-wb` explanation now also includes WB data freshness snapshot (`freshness_status`, sales age, oldest stock age, stock age by bundle, and stale thresholds) to surface stale/no-data ingestion risk inline with the proposal.
  - `from-wb` request now supports `freshness_mode`: `warn` (default, attach freshness diagnostics) and `strict` (fail fast with 400 when freshness status is not `fresh`, including stale/no-data WB datasets).
  - `from-wb` request now supports per-request freshness thresholds (`freshness_sales_stale_after_days`, `freshness_stock_stale_after_days`) with source tracing (`global_default` / `admin_defaults` / `request`) in both text explanation and `explanation.meta.from_wb.freshness.threshold_source`.
  - Freshness threshold precedence for `from-wb` is now `request > admin_defaults > global_default`; admin defaults are managed via production-order settings API and persisted on article-level settings.
  - Core production-order reorder policy now applies `safety_stock_days` from planning settings (`reorder_point_days = lead_time_days_total + safety_stock_days`) and exposes this in explanation step + `explanation.meta.reorder_policy`.
  - Core production-order now emits Layer 1 deterministic stock-health metrics per SKU (`velocity_main`, `velocity_assorti`, `coverage_days`, `current_stock`, `in_flight`, `eta_days`, `gross_margin` proxy, `capital_locked` proxy, `stockout_risk`, `overstock_risk`) plus contract checks (`risk_bounds`, `non_negative_*`, unique color-size keys) via `explanation.meta.layer_1_stock_health`.
  - Assorti bundle classification now uses deterministic precedence: `bundle_type.is_assorti` (primary) -> admin mapping (`article_planning_settings.production_order_assorti_bundle_type_ids`) -> global mapping (`global_planning_settings.default_production_order_assorti_bundle_type_ids`) -> main default, with source tracing in explanation step and `explanation.meta.layer_1_stock_health.assorti_classification`.
  - Core production-order now emits Layer 2 deterministic allocation comparison (`profit_if_main_until_eta` vs `profit_if_assorti_until_eta`, GMROI proxy, decision `main|assorti|hold`) via `explanation.meta.layer_2_allocation` and summary steps.
  - Layer 2 semantics are now explicit: decision gate is `profit_until_eta`, deterministic tie-break is `hold`, and GMROI is diagnostic-only (`explanation.meta.layer_2_allocation`).
  - Layer 2 now exposes deterministic decision-quality diagnostics (`decision_reason_counts`, `tie_count`, `near_tie_count`, average profit/GMROI gaps, capital-locked aggregates) in `explanation.meta.layer_2_allocation.decision_quality`, including compact-mode projection.
  - Layer 2 floating-boundary behavior is stabilized by normalizing emitted profit/GMROI diagnostics to 4 decimals before deriving decision flags (`allocation_decision`, `tie_break_applied`, `near_tie`), and regression now locks this rounding-boundary contract consistency.
  - Layer 2 contract summary is now emitted in `explanation.meta.layer_2_allocation.contract` (version/status/checks for summary consistency, allocation-vs-profit-gate consistency, non-negative metrics, positive ETA, tie-break invariants, decision-reason mapping, tie/near-tie flag consistency, profit/GMROI gap consistency, and capital metric sanity) and projected in compact explainability mode.
  - Core production-order Layer 3 purchase shaping now deterministically applies Layer 2 decisions (`main|assorti|hold`) with risk-weighted calibration (stockout boost + overstock dampening + bounded factors), and exposes calibration diagnostics via `explanation.meta.layer_3_purchase_shaping`.
  - Regression now explicitly locks Layer 3 semantics as quantity-shaping only: Layer 3 calibration overrides change shaped quantities/reorder units while Layer 2 allocation summary and per-line decisions remain unchanged.
  - Layer 3 contract summary is now emitted in `explanation.meta.layer_3_purchase_shaping.contract` (version/status/checks for qty delta invariants, decision/risk partition consistency, calibration method/bounds, and factor summary sanity) and projected in compact explainability mode.
  - Core production-order Layer 4 now emits deterministic scenarios (Conservative/Balanced/Aggressive) with per-scenario `total_capital_required`, `expected_turnover_proxy`, `stockout_risk_proxy`, and assorti sustainability proxy/impact via `explanation.meta.layer_4_scenarios`.
  - Core production-order Layer 5 now emits deterministic threshold-policy intervention signals via `explanation.meta.layer_5_intervention`: unavoidable threshold drives `increase_price_to_slow_velocity`, severe threshold drives `accelerate_production`, and severe + in-flight allows deterministic dual-signal output.
  - Layer 5 contract summary is now emitted in `explanation.meta.layer_5_intervention.contract` (version/status/checks for threshold sanity, signal validity/order, and reason-policy consistency) and projected in compact explainability mode.
  - Layer 5 signal-only semantics are regression-locked: threshold changes can alter intervention signals, while recommendation action remains unchanged for equivalent planning state.
  - Core production-order now exposes `explanation.meta.alpha_proxy_economics` with effective alpha proxy values and source tracing (`code_default_constants`) for layer thresholds/calibration/factors (Layer 1 stockout threshold, Layer 3 calibration params/bounds, Layer 4 contract version, Layer 5 intervention thresholds).
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
  - Layer-integrity guardrails are explicit in release criteria: Layer 2 remains profit-comparison based, Layer 3 remains quantity-shaping (does not replace Layer 2 gate), and Layer 5 remains signal-only (does not enforce recommendation action).
  - `from-wb` now clamps future `as_of_date` requests to latest available WB sales date to prevent drifted/empty future windows.
  - `from-wb` validates requested `bundle_type_ids` against `article_wb_mapping` and returns 400 on missing mappings.
  - In-flight supply now uses ETA/stage-sensitive effective contribution (not binary include/exclude), and explanation reports raw/effective in-flight qty.
  - Elastic minima now respect admin elastic binding scope: active bindings select applicable elastic types for current candidate lines; non-matching binding scope does not force elastic minimum uplift.
  - Explanation now includes elastic uplift trace (`delta`, `scope`, `affected_lines`, `line_keys`, `line_alloc`) for easier audit/debug of minimum-batch adjustments.
  - Economic buffer policy is now applied for warning/critical risk zones when `allow_order_with_buffer=true`; explanation includes buffer days and adjusted target horizon.
  - Raw bundle potential now uses competition-aware allocation across bundle types that share colors, with per-bundle breakdown in explanation.
  - Bundle stock input now supports WB ingestion fallback: if request omits `bundle_stock` entries, planner fills missing bundle types from `article_wb_mapping + wb_stock`.
  - Production-order request/admin schemas migrated to Pydantic v2 validator APIs (`@field_validator`/`@model_validator`) to reduce deprecation surface without changing API contract.
- WB ingestion reliability fix:
  - `POST /api/v1/wb/sales-daily/import` now stamps `created_at` on inserts to satisfy DB NOT NULL constraints and keep WB→planning adapter flow stable.
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
- Tests added for production-order endpoint:
  - `tests/test_planning_core_production_order_api.py`
  - Validation regressions now explicitly assert deterministic 422 details for production-order direct/from-WB schema errors (invalid literals, duplicate IDs, invalid threshold ordering, multi-field validation failures).
- Tests added for production-order admin settings:
  - `tests/test_planning_core_production_order_settings_api.py`
- Pydantic v2 migration hardening completed across monitoring/core schema surfaces:
  - Replaced deprecated `@validator`/`@root_validator` with `@field_validator`/`@model_validator` where applicable.
  - Replaced legacy `class Config(orm_mode=True)` with `model_config = ConfigDict(from_attributes=True)` in touched read schemas.
  - Replaced mutable list defaults with `Field(default_factory=list)` in touched schemas.
- Local verify workflow hardening:
  - Added `pytest` and `httpx` to image dependencies so `scripts/dev.ps1 verify` no longer performs ad-hoc pip installs inside running backend containers.
  - Added backend-running wait gate after `up -d --build backend` to avoid dependency-check race when container is still starting.
  - Added `scripts/dev.ps1 po-api-smoke` for deterministic live connectivity checks of production-order endpoints (`health=200`, seeded direct/from-WB happy-path requests=`200`, schema-invalid direct/from-WB requests=`422`).
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
'{"sales_window_days":30,"horizon_days":90}' | Set-Content -Encoding utf8 -NoNewline test_request.json
curl.exe -i -X POST http://localhost:8000/api/v1/planning/core/proposal -H "Content-Type: application/json" --data-binary "@test_request.json"
.\scripts\dev.ps1 context
docker compose -f .\docker-compose.yml exec -T db psql -U maconly -d maconly_db -c "SELECT count(*) FROM monitoring_snapshots;"
```

## Last verification

- Date: `2026-02-24 19:54:59 +07:00`
- Branch: `main`
- Last commit (`git log -1 --oneline`): `638d3e2 Add minimal Planning Core v1 proposal logic (non-empty response)`

### Minimal raw outputs

```text
$ git status -sb
## main...origin/main
 M app/core/planning/service.py
```

```text
$ docker compose -f .\docker-compose.yml up -d --build
unable to get image 'postgres:15': error during connect:
open //./pipe/dockerDesktopLinuxEngine: The system cannot find the file specified.
```

```text
$ docker compose -f .\docker-compose.yml ps
error during connect: open //./pipe/dockerDesktopLinuxEngine: The system cannot find the file specified.
```

```text
$ curl.exe -i http://localhost:8000/api/v1/planning/core/health
curl: (7) Failed to connect to localhost port 8000: Could not connect to server
```

```text
$ test_request.json body
{"sales_window_days":30,"horizon_days":90}
```

```text
$ curl.exe -i -X POST .../planning/core/proposal --data-binary "@test_request.json"
curl: (7) Failed to connect to localhost port 8000: Could not connect to server
```

```text
$ docker compose -f .\docker-compose.yml exec -T db psql ... "SELECT count(*) FROM monitoring_snapshots;"
error during connect: open //./pipe/dockerDesktopLinuxEngine: The system cannot find the file specified.
```

### Interpretation

- Command set is reproducible and PowerShell-safe.
- Current host state blocked full runtime/API verification because Docker engine was unavailable.
- Planning Core request-body validation flow remains defined and reproducible via the file-based curl method above.
