from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace

from app.models.models import ArticlePlanningSettings, GlobalPlanningSettings
from app.schemas.planning_production_order import PlanningOverridesInput

FROM_WB_OBSERVED_ECONOMIC_SOURCE = "from_wb_observed_window"
LAYER_PROXY_VALUE_SOURCE = "code_default_constants"
ECONOMICS_FORMULA_VERSION = "v1_economic_alpha"
ECONOMICS_DEFAULT_PRODUCTION_COST_PER_UNIT = 0.8
ECONOMICS_DEFAULT_LOGISTICS_COST_PER_UNIT = 0.2
ECONOMICS_DEFAULT_WB_COMMISSION_PERCENT_MAIN = 0.0
ECONOMICS_DEFAULT_WB_COMMISSION_PERCENT_ASSORTI = 0.0
ECONOMICS_DEFAULT_AVERAGE_REALIZED_PRICE_MAIN = 1.8
ECONOMICS_DEFAULT_AVERAGE_REALIZED_PRICE_ASSORTI = 1.65
ECONOMICS_TRUST_LEVEL_TRUSTED = "trusted"
ECONOMICS_TRUST_LEVEL_PARTIAL = "partial"
ECONOMICS_TRUST_LEVEL_UNTRUSTED = "untrusted"
ECONOMICS_TRUST_KEY_FIELDS: tuple[str, ...] = (
    "wb_commission_percent_main",
    "wb_commission_percent_assorti",
    "production_cost_per_unit",
    "logistics_cost_per_unit",
    "average_realized_price_main",
    "average_realized_price_assorti",
)
ECONOMICS_TRUST_UNTRUSTED_CODE_DEFAULT_THRESHOLD = 2
ECONOMICS_TRUST_WARNING_CODE_UNTRUSTED = "economics_untrusted_defaults_dominant"
ECONOMICS_TRUST_WARNING_CODE_PARTIAL = "economics_partial_defaults_present"
CAPITAL_CONSTRAINT_STATUS_MISSING_STRICT = "missing_available_capital_strict"


@dataclass
class _EffectiveEconomicSettings:
    production_cost_per_unit: float
    logistics_cost_per_unit: float
    wb_commission_percent_main: float
    wb_commission_percent_assorti: float
    average_realized_price_main: float
    average_realized_price_assorti: float
    margin_main_per_unit: float
    margin_assorti_per_unit: float
    unit_capital_per_unit: float
    available_capital: float | None
    calibration_state: str
    source: dict[str, str]


@dataclass(frozen=True)
class _EconomicGovernanceResolution:
    economic_settings: _EffectiveEconomicSettings
    economics_trust: dict[str, object]
    economics_warnings: list[dict[str, object]]
    capital_governance: dict[str, object]
    missing_available_capital_detail: dict[str, object] | None


def _normalize_non_negative_float(value: object) -> float | None:
    if value is None:
        return None

    try:
        normalized = float(value)
    except (TypeError, ValueError):
        return None

    if normalized < 0.0:
        return None
    return normalized


def _resolve_economic_float(
    *,
    request_value: float | None,
    runtime_value: float | None,
    admin_value: float | None,
    global_value: float | None,
    code_default: float,
    runtime_source: str,
) -> tuple[float, str]:
    request_normalized = _normalize_non_negative_float(request_value)
    runtime_normalized = _normalize_non_negative_float(runtime_value)
    admin_normalized = _normalize_non_negative_float(admin_value)
    global_normalized = _normalize_non_negative_float(global_value)

    if request_normalized is not None:
        return request_normalized, "request"
    if runtime_normalized is not None:
        return runtime_normalized, runtime_source
    if admin_normalized is not None:
        return admin_normalized, "admin_defaults"
    if global_normalized is not None:
        return global_normalized, "global_default"
    return float(code_default), LAYER_PROXY_VALUE_SOURCE


def _resolve_optional_economic_float(
    *,
    request_value: float | None,
    admin_value: float | None,
    global_value: float | None,
) -> tuple[float | None, str]:
    request_normalized = _normalize_non_negative_float(request_value)
    admin_normalized = _normalize_non_negative_float(admin_value)
    global_normalized = _normalize_non_negative_float(global_value)

    if request_normalized is not None:
        return request_normalized, "request"
    if admin_normalized is not None:
        return admin_normalized, "admin_defaults"
    if global_normalized is not None:
        return global_normalized, "global_default"
    return None, "not_set"


def _resolve_economic_settings(
    *,
    article_settings: ArticlePlanningSettings | None,
    global_settings: GlobalPlanningSettings | None,
    overrides: PlanningOverridesInput | None,
    runtime_overrides: dict[str, float | None] | None = None,
    runtime_source: str | None = None,
    runtime_source_overrides: dict[str, str] | None = None,
) -> _EffectiveEconomicSettings:
    request_production_cost = (
        overrides.production_cost_per_unit
        if overrides is not None
        else None
    )
    request_logistics_cost = (
        overrides.logistics_cost_per_unit
        if overrides is not None
        else None
    )
    request_commission_main = (
        overrides.wb_commission_percent_main
        if overrides is not None
        else None
    )
    request_commission_assorti = (
        overrides.wb_commission_percent_assorti
        if overrides is not None
        else None
    )
    request_price_main = (
        overrides.average_realized_price_main
        if overrides is not None
        else None
    )
    request_price_assorti = (
        overrides.average_realized_price_assorti
        if overrides is not None
        else None
    )
    request_available_capital = (
        overrides.available_capital
        if overrides is not None
        else None
    )
    runtime_values = runtime_overrides or {}
    runtime_source_label = runtime_source or FROM_WB_OBSERVED_ECONOMIC_SOURCE
    runtime_source_by_field = runtime_source_overrides or {}

    def _runtime_source_for(field_name: str) -> str:
        source_raw = runtime_source_by_field.get(field_name)
        if isinstance(source_raw, str):
            normalized = source_raw.strip()
            if normalized:
                return normalized
        return runtime_source_label

    runtime_production_cost = runtime_values.get("production_cost_per_unit")
    runtime_logistics_cost = runtime_values.get("logistics_cost_per_unit")
    runtime_commission_main = runtime_values.get("wb_commission_percent_main")
    runtime_commission_assorti = runtime_values.get("wb_commission_percent_assorti")
    runtime_price_main = runtime_values.get("average_realized_price_main")
    runtime_price_assorti = runtime_values.get("average_realized_price_assorti")

    admin_production_cost = (
        getattr(article_settings, "production_order_production_cost_per_unit", None)
        if article_settings is not None
        else None
    )
    admin_logistics_cost = (
        getattr(article_settings, "production_order_logistics_cost_per_unit", None)
        if article_settings is not None
        else None
    )
    admin_commission_main = (
        getattr(article_settings, "production_order_wb_commission_percent_main", None)
        if article_settings is not None
        else None
    )
    admin_commission_assorti = (
        getattr(article_settings, "production_order_wb_commission_percent_assorti", None)
        if article_settings is not None
        else None
    )
    admin_price_main = (
        getattr(article_settings, "production_order_average_realized_price_main", None)
        if article_settings is not None
        else None
    )
    admin_price_assorti = (
        getattr(article_settings, "production_order_average_realized_price_assorti", None)
        if article_settings is not None
        else None
    )
    admin_available_capital = (
        getattr(article_settings, "production_order_available_capital", None)
        if article_settings is not None
        else None
    )

    global_production_cost = (
        getattr(global_settings, "default_production_order_production_cost_per_unit", None)
        if global_settings is not None
        else None
    )
    global_logistics_cost = (
        getattr(global_settings, "default_production_order_logistics_cost_per_unit", None)
        if global_settings is not None
        else None
    )
    global_commission_main = (
        getattr(global_settings, "default_production_order_wb_commission_percent_main", None)
        if global_settings is not None
        else None
    )
    global_commission_assorti = (
        getattr(global_settings, "default_production_order_wb_commission_percent_assorti", None)
        if global_settings is not None
        else None
    )
    global_price_main = (
        getattr(global_settings, "default_production_order_average_realized_price_main", None)
        if global_settings is not None
        else None
    )
    global_price_assorti = (
        getattr(global_settings, "default_production_order_average_realized_price_assorti", None)
        if global_settings is not None
        else None
    )
    global_available_capital = (
        getattr(global_settings, "default_production_order_available_capital", None)
        if global_settings is not None
        else None
    )

    production_cost_per_unit, production_cost_source = _resolve_economic_float(
        request_value=request_production_cost,
        runtime_value=runtime_production_cost,
        admin_value=admin_production_cost,
        global_value=global_production_cost,
        code_default=ECONOMICS_DEFAULT_PRODUCTION_COST_PER_UNIT,
        runtime_source=_runtime_source_for("production_cost_per_unit"),
    )
    logistics_cost_per_unit, logistics_cost_source = _resolve_economic_float(
        request_value=request_logistics_cost,
        runtime_value=runtime_logistics_cost,
        admin_value=admin_logistics_cost,
        global_value=global_logistics_cost,
        code_default=ECONOMICS_DEFAULT_LOGISTICS_COST_PER_UNIT,
        runtime_source=_runtime_source_for("logistics_cost_per_unit"),
    )
    wb_commission_percent_main, wb_commission_main_source = _resolve_economic_float(
        request_value=request_commission_main,
        runtime_value=runtime_commission_main,
        admin_value=admin_commission_main,
        global_value=global_commission_main,
        code_default=ECONOMICS_DEFAULT_WB_COMMISSION_PERCENT_MAIN,
        runtime_source=_runtime_source_for("wb_commission_percent_main"),
    )
    wb_commission_percent_assorti, wb_commission_assorti_source = _resolve_economic_float(
        request_value=request_commission_assorti,
        runtime_value=runtime_commission_assorti,
        admin_value=admin_commission_assorti,
        global_value=global_commission_assorti,
        code_default=ECONOMICS_DEFAULT_WB_COMMISSION_PERCENT_ASSORTI,
        runtime_source=_runtime_source_for("wb_commission_percent_assorti"),
    )
    average_realized_price_main, price_main_source = _resolve_economic_float(
        request_value=request_price_main,
        runtime_value=runtime_price_main,
        admin_value=admin_price_main,
        global_value=global_price_main,
        code_default=ECONOMICS_DEFAULT_AVERAGE_REALIZED_PRICE_MAIN,
        runtime_source=_runtime_source_for("average_realized_price_main"),
    )
    average_realized_price_assorti, price_assorti_source = _resolve_economic_float(
        request_value=request_price_assorti,
        runtime_value=runtime_price_assorti,
        admin_value=admin_price_assorti,
        global_value=global_price_assorti,
        code_default=ECONOMICS_DEFAULT_AVERAGE_REALIZED_PRICE_ASSORTI,
        runtime_source=_runtime_source_for("average_realized_price_assorti"),
    )
    available_capital, available_capital_source = _resolve_optional_economic_float(
        request_value=request_available_capital,
        admin_value=admin_available_capital,
        global_value=global_available_capital,
    )

    wb_commission_percent_main = max(min(wb_commission_percent_main, 1.0), 0.0)
    wb_commission_percent_assorti = max(min(wb_commission_percent_assorti, 1.0), 0.0)

    commission_main_amount = average_realized_price_main * wb_commission_percent_main
    commission_assorti_amount = average_realized_price_assorti * wb_commission_percent_assorti
    margin_main_per_unit = max(
        average_realized_price_main - commission_main_amount - production_cost_per_unit - logistics_cost_per_unit,
        0.0,
    )
    margin_assorti_per_unit = max(
        average_realized_price_assorti - commission_assorti_amount - production_cost_per_unit - logistics_cost_per_unit,
        0.0,
    )
    unit_capital_per_unit = max(production_cost_per_unit + logistics_cost_per_unit, 0.0)

    source = {
        "production_cost_per_unit": production_cost_source,
        "logistics_cost_per_unit": logistics_cost_source,
        "wb_commission_percent_main": wb_commission_main_source,
        "wb_commission_percent_assorti": wb_commission_assorti_source,
        "average_realized_price_main": price_main_source,
        "average_realized_price_assorti": price_assorti_source,
        "available_capital": available_capital_source,
    }
    calibrated_sources = [
        source["production_cost_per_unit"],
        source["logistics_cost_per_unit"],
        source["wb_commission_percent_main"],
        source["wb_commission_percent_assorti"],
        source["average_realized_price_main"],
        source["average_realized_price_assorti"],
    ]
    calibration_state = (
        "economic_inputs_calibrated"
        if any(item != LAYER_PROXY_VALUE_SOURCE for item in calibrated_sources)
        else "economic_inputs_default_formula"
    )

    return _EffectiveEconomicSettings(
        production_cost_per_unit=round(production_cost_per_unit, 4),
        logistics_cost_per_unit=round(logistics_cost_per_unit, 4),
        wb_commission_percent_main=round(wb_commission_percent_main, 4),
        wb_commission_percent_assorti=round(wb_commission_percent_assorti, 4),
        average_realized_price_main=round(average_realized_price_main, 4),
        average_realized_price_assorti=round(average_realized_price_assorti, 4),
        margin_main_per_unit=round(margin_main_per_unit, 4),
        margin_assorti_per_unit=round(margin_assorti_per_unit, 4),
        unit_capital_per_unit=round(unit_capital_per_unit, 4),
        available_capital=round(available_capital, 4) if available_capital is not None else None,
        calibration_state=calibration_state,
        source=source,
    )


def _build_economics_trust_diagnostics(economic_source: dict[str, str]) -> dict[str, object]:
    key_field_sources = {
        field_name: str(economic_source.get(field_name, "unknown"))
        for field_name in ECONOMICS_TRUST_KEY_FIELDS
    }
    code_default_key_fields = sorted(
        field_name
        for field_name, source in key_field_sources.items()
        if source == LAYER_PROXY_VALUE_SOURCE
    )
    code_default_key_fields_count = len(code_default_key_fields)
    key_fields_total = len(ECONOMICS_TRUST_KEY_FIELDS)
    code_default_dominance_ratio = (
        round(code_default_key_fields_count / key_fields_total, 4)
        if key_fields_total > 0
        else 0.0
    )

    if code_default_key_fields_count >= ECONOMICS_TRUST_UNTRUSTED_CODE_DEFAULT_THRESHOLD:
        trust_level = ECONOMICS_TRUST_LEVEL_UNTRUSTED
    elif code_default_key_fields_count == 0:
        trust_level = ECONOMICS_TRUST_LEVEL_TRUSTED
    else:
        trust_level = ECONOMICS_TRUST_LEVEL_PARTIAL

    warnings: list[dict[str, object]] = []
    if trust_level == ECONOMICS_TRUST_LEVEL_UNTRUSTED:
        warnings.append(
            {
                "code": ECONOMICS_TRUST_WARNING_CODE_UNTRUSTED,
                "severity": "HIGH",
                "message": (
                    "Economics trust level is untrusted because key economics inputs are dominated "
                    "by code defaults."
                ),
                "code_default_key_fields": code_default_key_fields,
            }
        )
    elif trust_level == ECONOMICS_TRUST_LEVEL_PARTIAL:
        warnings.append(
            {
                "code": ECONOMICS_TRUST_WARNING_CODE_PARTIAL,
                "severity": "MEDIUM",
                "message": (
                    "Economics trust level is partial because some key economics inputs still use "
                    "code defaults."
                ),
                "code_default_key_fields": code_default_key_fields,
            }
        )

    return {
        "economics_trust_level": trust_level,
        "key_fields": list(ECONOMICS_TRUST_KEY_FIELDS),
        "key_field_sources": key_field_sources,
        "code_default_key_fields": code_default_key_fields,
        "code_default_key_fields_count": code_default_key_fields_count,
        "code_default_dominance_ratio": code_default_dominance_ratio,
        "warnings": warnings,
    }


def _resolve_economic_trust_and_capital_governance(
    *,
    article_id: int,
    economic_settings: _EffectiveEconomicSettings,
    overrides: PlanningOverridesInput | None,
    capital_governance_mode_strict: str,
    capital_governance_mode_safe_default: str,
    capital_governance_source_safe_default: str,
    build_available_capital_safe_default_warning: Callable[..., dict[str, object]],
    build_missing_available_capital_strict_detail: Callable[..., dict[str, object]],
) -> _EconomicGovernanceResolution:
    economics_trust = _build_economics_trust_diagnostics(economic_settings.source)
    economics_warnings = list(economics_trust.get("warnings", []))

    capital_governance_mode = capital_governance_mode_strict
    if overrides is not None:
        capital_governance_mode = str(overrides.capital_governance_mode).strip().lower()

    capital_governance = {
        "mode": capital_governance_mode,
        "missing_available_capital_policy": capital_governance_mode,
        "safe_default_applied": False,
        "available_capital_effective": economic_settings.available_capital,
        "effective_source": economic_settings.source.get("available_capital"),
    }

    missing_available_capital_detail: dict[str, object] | None = None
    if economic_settings.available_capital is None:
        if capital_governance_mode == capital_governance_mode_safe_default:
            economic_settings = replace(
                economic_settings,
                available_capital=0.0,
                source={
                    **economic_settings.source,
                    "available_capital": capital_governance_source_safe_default,
                },
            )
            economics_warnings.append(
                build_available_capital_safe_default_warning(
                    article_id=article_id,
                    economics_trust_level=economics_trust.get("economics_trust_level"),
                )
            )
            capital_governance = {
                "mode": capital_governance_mode,
                "missing_available_capital_policy": capital_governance_mode,
                "safe_default_applied": True,
                "available_capital_effective": 0.0,
                "effective_source": capital_governance_source_safe_default,
            }
        else:
            missing_available_capital_detail = build_missing_available_capital_strict_detail(
                article_id=article_id,
                economics_trust_level=economics_trust.get("economics_trust_level"),
            )
    else:
        capital_governance = {
            "mode": capital_governance_mode,
            "missing_available_capital_policy": capital_governance_mode,
            "safe_default_applied": False,
            "available_capital_effective": economic_settings.available_capital,
            "effective_source": economic_settings.source.get("available_capital"),
        }

    return _EconomicGovernanceResolution(
        economic_settings=economic_settings,
        economics_trust=economics_trust,
        economics_warnings=economics_warnings,
        capital_governance=capital_governance,
        missing_available_capital_detail=missing_available_capital_detail,
    )
