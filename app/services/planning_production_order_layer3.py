from __future__ import annotations

from math import floor

from app.services.planning_production_order_layer_proxy import (
    LAYER3_OVERSTOCK_DAMPEN_MAX,
    LAYER3_STOCKOUT_BOOST_MAX,
)

LAYER3_CONTRACT_VERSION = "v1_alpha"
LAYER3_PURCHASE_FACTOR_BY_DECISION: dict[str, float] = {
    "main": 1.0,
    "assorti": 0.75,
    "hold": 0.35,
}
LAYER3_CALIBRATION_METHOD = "risk_weighted_factor_clamp"
LAYER3_STOCKOUT_WEIGHT_BY_DECISION: dict[str, float] = {
    "main": 1.0,
    "assorti": 0.7,
    "hold": 0.15,
}
LAYER3_OVERSTOCK_WEIGHT_BY_DECISION: dict[str, float] = {
    "main": 0.35,
    "assorti": 0.6,
    "hold": 1.0,
}
LAYER3_FACTOR_BOUNDS: dict[str, tuple[float, float]] = {
    "main": (0.65, 1.25),
    "assorti": (0.30, 0.95),
    "hold": (0.10, 0.60),
}


def _apply_layer3_purchase_shaping(
    *,
    line_qty: dict[tuple[int, int], int],
    layer2_allocation_decisions: list[dict[str, int | float | str]],
    layer1_stock_health_metrics: list[dict[str, int | float | None]],
    layer3_stockout_boost_max: float = LAYER3_STOCKOUT_BOOST_MAX,
    layer3_overstock_dampen_max: float = LAYER3_OVERSTOCK_DAMPEN_MAX,
) -> tuple[dict[tuple[int, int], str], dict[str, int | float | dict[str, object] | str]]:
    def _bounded_risk(value: object) -> float:
        try:
            risk = float(value)
        except (TypeError, ValueError):
            return 0.0
        return max(min(risk, 1.0), 0.0)

    def _calibrated_factor(decision_text: str, stockout_risk: float, overstock_risk: float) -> float:
        base_factor = LAYER3_PURCHASE_FACTOR_BY_DECISION[decision_text]
        stockout_weight = LAYER3_STOCKOUT_WEIGHT_BY_DECISION.get(decision_text, 1.0)
        overstock_weight = LAYER3_OVERSTOCK_WEIGHT_BY_DECISION.get(decision_text, 1.0)

        calibrated = (
            base_factor
            + (stockout_risk * layer3_stockout_boost_max * stockout_weight)
            - (overstock_risk * layer3_overstock_dampen_max * overstock_weight)
        )

        min_factor, max_factor = LAYER3_FACTOR_BOUNDS[decision_text]
        return max(min(calibrated, max_factor), min_factor)

    stock_health_by_line: dict[tuple[int, int], tuple[float, float]] = {}
    for metric in layer1_stock_health_metrics:
        color_id_raw = metric.get("color_id")
        size_id_raw = metric.get("size_id")
        try:
            line_key = (int(color_id_raw), int(size_id_raw))
        except (TypeError, ValueError):
            continue

        stock_health_by_line[line_key] = (
            _bounded_risk(metric.get("stockout_risk")),
            _bounded_risk(metric.get("overstock_risk")),
        )

    decision_by_line: dict[tuple[int, int], str] = {}

    for decision in layer2_allocation_decisions:
        color_id_raw = decision.get("color_id")
        size_id_raw = decision.get("size_id")
        try:
            line_key = (int(color_id_raw), int(size_id_raw))
        except (TypeError, ValueError):
            continue

        decision_text = str(decision.get("allocation_decision", "main")).strip().lower()
        if decision_text not in LAYER3_PURCHASE_FACTOR_BY_DECISION:
            decision_text = "main"
        decision_by_line[line_key] = decision_text

    qty_before = sum(max(int(qty), 0) for qty in line_qty.values())
    qty_after_base = 0
    adjusted_lines = 0
    decision_line_counts = {
        "main": 0,
        "assorti": 0,
        "hold": 0,
    }
    calibration_up_lines = 0
    calibration_down_lines = 0
    risk_lines_covered = 0
    risk_lines_missing = 0
    calibrated_factor_sum = 0.0
    calibrated_factor_min: float | None = None
    calibrated_factor_max: float | None = None

    for line_key in sorted(line_qty.keys()):
        current_qty = max(int(line_qty.get(line_key, 0)), 0)
        if current_qty <= 0:
            continue

        decision_text = decision_by_line.get(line_key, "main")
        if decision_text not in LAYER3_PURCHASE_FACTOR_BY_DECISION:
            decision_text = "main"

        decision_line_counts[decision_text] += 1

        base_factor = LAYER3_PURCHASE_FACTOR_BY_DECISION[decision_text]
        base_shaped_qty = floor(float(current_qty) * base_factor)
        if decision_text == "main" and current_qty > 0 and base_shaped_qty <= 0:
            base_shaped_qty = 1
        qty_after_base += max(int(base_shaped_qty), 0)

        stock_health = stock_health_by_line.get(line_key)
        if stock_health is None:
            stockout_risk = 0.0
            overstock_risk = 0.0
            risk_lines_missing += 1
        else:
            stockout_risk, overstock_risk = stock_health
            risk_lines_covered += 1

        factor = _calibrated_factor(
            decision_text=decision_text,
            stockout_risk=stockout_risk,
            overstock_risk=overstock_risk,
        )

        calibrated_factor_sum += factor
        calibrated_factor_min = factor if calibrated_factor_min is None else min(calibrated_factor_min, factor)
        calibrated_factor_max = factor if calibrated_factor_max is None else max(calibrated_factor_max, factor)

        shaped_qty = floor(float(current_qty) * factor)
        if decision_text == "main" and current_qty > 0 and shaped_qty <= 0:
            shaped_qty = 1
        shaped_qty = max(int(shaped_qty), 0)

        if shaped_qty > base_shaped_qty:
            calibration_up_lines += 1
        elif shaped_qty < base_shaped_qty:
            calibration_down_lines += 1

        if shaped_qty != current_qty:
            adjusted_lines += 1

        line_qty[line_key] = shaped_qty

    qty_after = sum(max(int(qty), 0) for qty in line_qty.values())
    calibrated_lines = sum(decision_line_counts.values())
    factor_bounds = {
        decision_text: {
            "min": bounds[0],
            "max": bounds[1],
        }
        for decision_text, bounds in LAYER3_FACTOR_BOUNDS.items()
    }

    return (
        decision_by_line,
        {
            "qty_before": qty_before,
            "qty_after_base": qty_after_base,
            "qty_after": qty_after,
            "qty_delta_vs_base": qty_after - qty_after_base,
            "adjusted_lines": adjusted_lines,
            "main_lines": decision_line_counts["main"],
            "assorti_lines": decision_line_counts["assorti"],
            "hold_lines": decision_line_counts["hold"],
            "calibration_up_lines": calibration_up_lines,
            "calibration_down_lines": calibration_down_lines,
            "calibration": {
                "method": LAYER3_CALIBRATION_METHOD,
                "stockout_boost_max": round(layer3_stockout_boost_max, 4),
                "overstock_dampen_max": round(layer3_overstock_dampen_max, 4),
                "stockout_weight_by_decision": dict(LAYER3_STOCKOUT_WEIGHT_BY_DECISION),
                "overstock_weight_by_decision": dict(LAYER3_OVERSTOCK_WEIGHT_BY_DECISION),
                "factor_bounds": factor_bounds,
                "risk_lines_covered": risk_lines_covered,
                "risk_lines_missing": risk_lines_missing,
                "up_lines": calibration_up_lines,
                "down_lines": calibration_down_lines,
                "factor_summary": {
                    "avg": round(
                        calibrated_factor_sum / float(calibrated_lines),
                        4,
                    )
                    if calibrated_lines > 0
                    else 0.0,
                    "min": round(calibrated_factor_min, 4)
                    if calibrated_factor_min is not None
                    else 0.0,
                    "max": round(calibrated_factor_max, 4)
                    if calibrated_factor_max is not None
                    else 0.0,
                },
            },
        },
    )


def _build_layer3_contract_summary(
    layer3_purchase_shaping: dict[str, object],
) -> dict[str, str | int | dict[str, bool]]:
    def _safe_int(value: object) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    def _safe_float(value: object) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    qty_before = _safe_int(layer3_purchase_shaping.get("qty_before"))
    qty_after_base = _safe_int(layer3_purchase_shaping.get("qty_after_base"))
    qty_after = _safe_int(layer3_purchase_shaping.get("qty_after"))
    qty_delta_vs_base = _safe_int(layer3_purchase_shaping.get("qty_delta_vs_base"))
    adjusted_lines = _safe_int(layer3_purchase_shaping.get("adjusted_lines"))

    main_lines = _safe_int(layer3_purchase_shaping.get("main_lines"))
    assorti_lines = _safe_int(layer3_purchase_shaping.get("assorti_lines"))
    hold_lines = _safe_int(layer3_purchase_shaping.get("hold_lines"))
    decision_lines_total = main_lines + assorti_lines + hold_lines

    calibration_raw = layer3_purchase_shaping.get("calibration")
    calibration = calibration_raw if isinstance(calibration_raw, dict) else {}

    risk_lines_covered = _safe_int(calibration.get("risk_lines_covered"))
    risk_lines_missing = _safe_int(calibration.get("risk_lines_missing"))
    calibration_up_lines = _safe_int(calibration.get("up_lines"))
    calibration_down_lines = _safe_int(calibration.get("down_lines"))
    calibration_method = str(calibration.get("method", ""))

    factor_bounds_raw = calibration.get("factor_bounds")
    factor_bounds_actual = factor_bounds_raw if isinstance(factor_bounds_raw, dict) else {}
    factor_bounds_expected = {
        decision: {
            "min": bounds[0],
            "max": bounds[1],
        }
        for decision, bounds in LAYER3_FACTOR_BOUNDS.items()
    }

    factor_summary_raw = calibration.get("factor_summary")
    factor_summary = factor_summary_raw if isinstance(factor_summary_raw, dict) else {}
    factor_summary_avg = _safe_float(factor_summary.get("avg"))
    factor_summary_min = _safe_float(factor_summary.get("min"))
    factor_summary_max = _safe_float(factor_summary.get("max"))

    global_factor_min = min(bounds[0] for bounds in LAYER3_FACTOR_BOUNDS.values())
    global_factor_max = max(bounds[1] for bounds in LAYER3_FACTOR_BOUNDS.values())

    checks = {
        "non_negative_quantities": (
            qty_before >= 0 and qty_after_base >= 0 and qty_after >= 0
        ),
        "qty_delta_matches_after_minus_base": (
            qty_delta_vs_base == (qty_after - qty_after_base)
        ),
        "non_negative_line_counts": (
            adjusted_lines >= 0 and main_lines >= 0 and assorti_lines >= 0 and hold_lines >= 0
        ),
        "adjusted_lines_within_decision_lines": adjusted_lines <= decision_lines_total,
        "non_negative_risk_line_counts": (
            risk_lines_covered >= 0 and risk_lines_missing >= 0
        ),
        "risk_partition_matches_decision_lines": (
            risk_lines_covered + risk_lines_missing == decision_lines_total
        ),
        "non_negative_calibration_direction_counts": (
            calibration_up_lines >= 0 and calibration_down_lines >= 0
        ),
        "calibration_direction_counts_within_decision_lines": (
            calibration_up_lines + calibration_down_lines <= decision_lines_total
        ),
        "calibration_method_matches": calibration_method == LAYER3_CALIBRATION_METHOD,
        "factor_bounds_match_expected": factor_bounds_actual == factor_bounds_expected,
        "factor_summary_consistent": (
            factor_summary_min <= factor_summary_avg <= factor_summary_max
        ),
        "factor_summary_within_bounds": (
            decision_lines_total == 0
            and factor_summary_avg == 0.0
            and factor_summary_min == 0.0
            and factor_summary_max == 0.0
        )
        or (
            factor_summary_min >= global_factor_min
            and factor_summary_max <= global_factor_max
        ),
    }
    return {
        "version": LAYER3_CONTRACT_VERSION,
        "status": "ok" if all(checks.values()) else "violated",
        "decision_lines": decision_lines_total,
        "checks": checks,
    }
