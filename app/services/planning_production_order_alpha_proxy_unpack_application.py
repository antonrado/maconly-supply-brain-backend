from __future__ import annotations

from dataclasses import dataclass

from app.services.planning_production_order_alpha_proxy_application import (
    _AlphaProxyApplicationResult,
)


@dataclass(frozen=True)
class _AlphaProxyUnpackApplicationResult:
    layer4_scenario_factor_items: list[dict[str, object]]
    alpha_proxy_economics: dict[str, object]


def _apply_production_order_alpha_proxy_unpack(
    *,
    alpha_proxy_application: _AlphaProxyApplicationResult,
) -> _AlphaProxyUnpackApplicationResult:
    return _AlphaProxyUnpackApplicationResult(
        layer4_scenario_factor_items=alpha_proxy_application.layer4_scenario_factor_items,
        alpha_proxy_economics=alpha_proxy_application.alpha_proxy_economics,
    )
