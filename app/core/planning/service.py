from __future__ import annotations

"""Planning Core v1 service interface.

This module intentionally contains *no* business logic. It only defines the
shape of the future Planning Core service so that API layers can depend on a
stable interface while the implementation is developed incrementally.
"""

from app.core.planning.domain import (
    DemandInput,
    OrderProposal,
    PlanningHealth,
    PlanningSettings,
    SupplyInput,
)


class PlanningService:
    """Interface for Planning Core v1 operations.

    All methods deliberately raise NotImplementedError; real implementations
    will be provided in future tasks.
    """

    def compute_order_proposal(
        self,
        settings: PlanningSettings,
        demand: DemandInput,
        supply: SupplyInput,
    ) -> OrderProposal:
        """Compute a replenishment order proposal.

        This is a placeholder and must not be called in production code yet.
        """

        raise NotImplementedError("PlanningService.compute_order_proposal is not implemented")

    def get_planning_health(self) -> PlanningHealth:
        """Return an aggregated view of planning health.

        This is a placeholder and must not be called in production code yet.
        """

        raise NotImplementedError("PlanningService.get_planning_health is not implemented")
