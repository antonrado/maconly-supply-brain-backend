from __future__ import annotations

from dataclasses import dataclass

from app.services.planning_production_order_economic_governance_application import (
    _EconomicGovernanceApplicationResult,
)


@dataclass(frozen=True)
class _EconomicGovernanceUnpackApplicationResult:
    economic_settings: object
    economics_trust: dict[str, object]
    economics_warnings: list[dict[str, object]]
    capital_governance: dict[str, object]


def _apply_production_order_economic_governance_unpack(
    *,
    economic_governance_application: _EconomicGovernanceApplicationResult,
) -> _EconomicGovernanceUnpackApplicationResult:
    return _EconomicGovernanceUnpackApplicationResult(
        economic_settings=economic_governance_application.economic_settings,
        economics_trust=economic_governance_application.economics_trust,
        economics_warnings=economic_governance_application.economics_warnings,
        capital_governance=economic_governance_application.capital_governance,
    )
