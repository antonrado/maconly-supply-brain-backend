from __future__ import annotations

from app.schemas.planning_production_order import ProductionOrderExplanationBlock

EXPLAINABILITY_MODE_COMPACT = "compact"


def _compact_explanation_steps(steps: list[str]) -> tuple[list[str], int]:
    if not steps:
        return [], 0

    keep_tokens = (
        "WB ingestion adapter",
        "Спрос по наборам",
        "Источник параметров",
        "Economics trust",
        "Assorti classification",
        "Physical scope",
        "Resource allocation",
        "Arrival projection",
        "Shared color pool",
        "Layer 1 stock health",
        "Layer 2 allocation",
        "Layer 3 purchase shaping",
        "Layer 4 scenarios",
        "Capital constraint",
        "Layer 5 intervention",
        "Применены ограничения",
    )

    compact_steps = [
        step
        for step in steps
        if any(token in step for token in keep_tokens)
    ]
    if not compact_steps:
        compact_steps = steps[: min(len(steps), 6)]

    compact_steps = compact_steps[:14]
    omitted_steps = max(len(steps) - len(compact_steps), 0)
    if omitted_steps > 0:
        compact_steps.append(
            f"Explainability compact mode: omitted_steps={omitted_steps}."
        )

    return compact_steps, omitted_steps


def _sum_numeric_mapping_values(value: object) -> float:
    if not isinstance(value, dict):
        return 0.0

    total = 0.0
    for item in value.values():
        if isinstance(item, bool):
            continue
        if isinstance(item, int | float):
            total += float(item)

    return round(total, 4)


def _build_compact_explanation_meta(meta: dict[str, object]) -> dict[str, object]:
    compact_meta: dict[str, object] = {
        "warnings": meta.get("warnings", []),
        "economics_trust": meta.get("economics_trust", {}),
        "sources": meta.get("sources", {}),
        "physical_scope": meta.get("physical_scope", {}),
        "arrival_projection": meta.get("arrival_projection", {}),
        "reorder_policy": meta.get("reorder_policy", {}),
        "economic_buffer": meta.get("economic_buffer", {}),
        "in_flight_effective": meta.get("in_flight_effective", {}),
        "capital_gap": meta.get("capital_gap", {}),
        "capital_constraint": meta.get("capital_constraint", {}),
        "resource_allocation": meta.get("resource_allocation", {}),
        "shared_color_pool": meta.get("shared_color_pool", {}),
        "alpha_proxy_economics": meta.get("alpha_proxy_economics", {}),
    }

    layer1_raw = meta.get("layer_1_stock_health")
    if isinstance(layer1_raw, dict):
        assorti_raw = layer1_raw.get("assorti_classification")
        assorti_compact: dict[str, object] = {}
        if isinstance(assorti_raw, dict):
            assorti_compact = {
                "source": assorti_raw.get("source"),
                "fallback_sources": assorti_raw.get("fallback_sources", []),
                "source_breakdown": assorti_raw.get("source_breakdown", {}),
                "summary": assorti_raw.get("summary", {}),
            }

        compact_meta["layer_1_stock_health"] = {
            "summary": layer1_raw.get("summary", {}),
            "contract": layer1_raw.get("contract", {}),
            "assorti_classification": assorti_compact,
            "proxies": layer1_raw.get("proxies", {}),
        }

    layer2_raw = meta.get("layer_2_allocation")
    if isinstance(layer2_raw, dict):
        compact_meta["layer_2_allocation"] = {
            "method": layer2_raw.get("method"),
            "method_canonical": layer2_raw.get("method_canonical"),
            "legacy_method": layer2_raw.get("legacy_method"),
            "legacy_alias_deprecation_plan": layer2_raw.get("legacy_alias_deprecation_plan", {}),
            "summary": layer2_raw.get("summary", {}),
            "contract": layer2_raw.get("contract", {}),
            "decision_quality": layer2_raw.get("decision_quality", {}),
            "decision_gate": layer2_raw.get("decision_gate"),
            "decision_gate_canonical": layer2_raw.get("decision_gate_canonical"),
            "legacy_decision_gate": layer2_raw.get("legacy_decision_gate"),
            "tie_break": layer2_raw.get("tie_break"),
            "gmroi_usage": layer2_raw.get("gmroi_usage"),
            "objective_formula": layer2_raw.get("objective_formula"),
            "objective_parameters": layer2_raw.get("objective_parameters", {}),
            "objective_source": layer2_raw.get("objective_source", {}),
        }

    layer3_raw = meta.get("layer_3_purchase_shaping")
    if isinstance(layer3_raw, dict):
        compact_meta["layer_3_purchase_shaping"] = {
            "method": layer3_raw.get("method"),
            "factors": layer3_raw.get("factors", {}),
            "contract": layer3_raw.get("contract", {}),
            "qty_before": layer3_raw.get("qty_before", 0),
            "qty_after_base": layer3_raw.get("qty_after_base", 0),
            "qty_after": layer3_raw.get("qty_after", 0),
            "qty_delta_vs_base": layer3_raw.get("qty_delta_vs_base", 0),
            "adjusted_lines": layer3_raw.get("adjusted_lines", 0),
            "main_lines": layer3_raw.get("main_lines", 0),
            "assorti_lines": layer3_raw.get("assorti_lines", 0),
            "hold_lines": layer3_raw.get("hold_lines", 0),
            "calibration": layer3_raw.get("calibration", {}),
        }

    layer4_raw = meta.get("layer_4_scenarios")
    if isinstance(layer4_raw, dict):
        scenarios_compact: list[dict[str, object]] = []
        scenarios_raw = layer4_raw.get("scenarios")
        if isinstance(scenarios_raw, list):
            for scenario in scenarios_raw:
                if not isinstance(scenario, dict):
                    continue
                scenarios_compact.append(
                    {
                        "scenario": scenario.get("scenario"),
                        "purchase_units": scenario.get("purchase_units"),
                        "total_capital_required": scenario.get("total_capital_required"),
                        "expected_revenue": scenario.get("expected_revenue"),
                        "expected_gross_profit": scenario.get("expected_gross_profit"),
                        "objective_score": scenario.get("objective_score"),
                        "expected_margin_percent": scenario.get("expected_margin_percent"),
                        "expected_turnover_days": scenario.get("expected_turnover_days"),
                        "expected_turnover_proxy": scenario.get("expected_turnover_proxy"),
                        "stockout_probability_proxy": scenario.get("stockout_probability_proxy"),
                        "stockout_risk_proxy": scenario.get("stockout_risk_proxy"),
                        "overstock_risk_proxy": scenario.get("overstock_risk_proxy"),
                        "risk_adjusted_profit": scenario.get("risk_adjusted_profit"),
                        "capital_efficiency_metric": scenario.get("capital_efficiency_metric"),
                        "capital_delta_vs_balanced": scenario.get("capital_delta_vs_balanced"),
                        "expected_revenue_delta_vs_balanced": scenario.get(
                            "expected_revenue_delta_vs_balanced"
                        ),
                        "expected_gross_profit_delta_vs_balanced": scenario.get(
                            "expected_gross_profit_delta_vs_balanced"
                        ),
                        "gross_profit_delta_vs_balanced": scenario.get("gross_profit_delta_vs_balanced"),
                        "objective_score_delta_vs_balanced": scenario.get(
                            "objective_score_delta_vs_balanced"
                        ),
                        "assorti_sustainability_impact": scenario.get("assorti_sustainability_impact"),
                    }
                )

        compact_meta["layer_4_scenarios"] = {
            "method": layer4_raw.get("method"),
            "factors": layer4_raw.get("factors", []),
            "contract": layer4_raw.get("contract", {}),
            "aggregate_deltas": layer4_raw.get("aggregate_deltas", {}),
            "scenarios": scenarios_compact,
        }

    layer5_raw = meta.get("layer_5_intervention")
    if isinstance(layer5_raw, dict):
        compact_meta["layer_5_intervention"] = layer5_raw

    elastic_scope_raw = meta.get("elastic_scope")
    if isinstance(elastic_scope_raw, dict):
        compact_meta["elastic_scope"] = elastic_scope_raw

    elastic_uplift_raw = meta.get("elastic_uplift")
    if isinstance(elastic_uplift_raw, dict):
        compact_meta["elastic_uplift"] = {
            "delta": elastic_uplift_raw.get("delta", 0),
            "scope": elastic_uplift_raw.get("scope", "none"),
            "affected_lines": elastic_uplift_raw.get("affected_lines", 0),
        }

    from_wb_raw = meta.get("from_wb")
    if isinstance(from_wb_raw, dict):
        freshness_raw = from_wb_raw.get("freshness")
        economic_observed_raw = from_wb_raw.get("economic_observed_prices")
        economic_commission_raw = from_wb_raw.get("economic_observed_commission")
        freshness_compact: dict[str, object] = {}
        economic_observed_compact: dict[str, object] = {}
        economic_commission_compact: dict[str, object] = {}
        if isinstance(freshness_raw, dict):
            freshness_compact = {
                "status": freshness_raw.get("status"),
                "sales_age_days": freshness_raw.get("sales_age_days"),
                "stock_oldest_age_days": freshness_raw.get("stock_oldest_age_days"),
                "threshold_days": freshness_raw.get("threshold_days"),
                "threshold_source": freshness_raw.get("threshold_source"),
            }
        if isinstance(economic_observed_raw, dict):
            economic_observed_compact = {
                "source": economic_observed_raw.get("source"),
                "window": economic_observed_raw.get("window"),
                "anomaly_max_deviation": economic_observed_raw.get(
                    "anomaly_max_deviation"
                ),
                "prices": economic_observed_raw.get("prices"),
                "sample_counts": economic_observed_raw.get("sample_counts"),
            }
        if isinstance(economic_commission_raw, dict):
            economic_commission_compact = {
                "source": economic_commission_raw.get("source"),
                "status": economic_commission_raw.get("status"),
                "reason": economic_commission_raw.get("reason"),
                "commission_percent": economic_commission_raw.get("commission_percent"),
                "commission_percent_stats": economic_commission_raw.get("commission_percent_stats"),
                "kgvp_supplier_percent_stats": economic_commission_raw.get("kgvp_supplier_percent_stats"),
            }

        daily_sales_by_bundle = from_wb_raw.get("daily_sales_by_bundle")
        wb_stock_by_bundle = from_wb_raw.get("wb_stock_by_bundle")
        wb_stock_updated_at_by_bundle = from_wb_raw.get("wb_stock_updated_at_by_bundle")

        compact_meta["from_wb"] = {
            "observation_window_days": from_wb_raw.get("observation_window_days"),
            "freshness_mode": from_wb_raw.get("freshness_mode"),
            "requested_as_of_date": from_wb_raw.get("requested_as_of_date"),
            "as_of_date": from_wb_raw.get("as_of_date"),
            "as_of_source": from_wb_raw.get("as_of_source"),
            "bundle_type_ids": from_wb_raw.get("bundle_type_ids", []),
            "sales_window": from_wb_raw.get("sales_window"),
            "freshness": freshness_compact,
            "economic_observed_prices": economic_observed_compact,
            "economic_observed_commission": economic_commission_compact,
            "snapshot": {
                "daily_sales_bundle_count": (
                    len(daily_sales_by_bundle)
                    if isinstance(daily_sales_by_bundle, dict)
                    else 0
                ),
                "daily_sales_total": _sum_numeric_mapping_values(daily_sales_by_bundle),
                "wb_stock_bundle_count": (
                    len(wb_stock_by_bundle)
                    if isinstance(wb_stock_by_bundle, dict)
                    else 0
                ),
                "wb_stock_total": int(_sum_numeric_mapping_values(wb_stock_by_bundle)),
                "wb_stock_updated_bundle_count": (
                    len(wb_stock_updated_at_by_bundle)
                    if isinstance(wb_stock_updated_at_by_bundle, dict)
                    else 0
                ),
            },
        }

    return compact_meta


def _apply_explainability_mode(
    explanation: ProductionOrderExplanationBlock,
    mode: str,
) -> ProductionOrderExplanationBlock:
    if mode != EXPLAINABILITY_MODE_COMPACT:
        return explanation

    compact_steps, omitted_steps = _compact_explanation_steps(explanation.steps)
    compact_meta = _build_compact_explanation_meta(explanation.meta)
    compact_meta["explainability"] = {
        "mode": EXPLAINABILITY_MODE_COMPACT,
        "steps_omitted": omitted_steps,
    }

    return ProductionOrderExplanationBlock(
        summary=explanation.summary,
        steps=compact_steps,
        meta=compact_meta,
    )
