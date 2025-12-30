from __future__ import annotations

"""Planning Core v1 service interface.

This module intentionally contains *no* business logic. It only defines the
shape of the future Planning Core service so that API layers can depend on a
stable interface while the implementation is developed incrementally.
"""

from datetime import datetime, timezone

from app.core.planning.domain import (
    DemandInput,
    OrderProposal,
    PlanningHealth,
    PlanningProposal,
    PlanningProposalInputs,
    PlanningProposalSummary,
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

        return OrderProposal(
            article_id=demand.article_id,
            proposed_order_qty=0,
            comment="stub",
        )

    def get_planning_health(self) -> PlanningHealth:
        """Return an aggregated view of planning health.

        This is a placeholder and must not be called in production code yet.
        """

        return PlanningHealth(status="ok", issues=[])

    def build_proposal_stub(self) -> PlanningProposal:
        """Build a structured PlanningProposal stub for API responses."""

        now = datetime.now(timezone.utc)
        return PlanningProposal(
            version="v1",
            generated_at=now,
            inputs=PlanningProposalInputs(
                sales_window_days=None,
                horizon_days=None,
            ),
            summary=PlanningProposalSummary(
                total_skus=0,
                total_units=0,
            ),
            lines=[],
        )
