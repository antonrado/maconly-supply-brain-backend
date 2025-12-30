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
    PlanningProposalLine,
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

    def build_proposal(self, sales_window_days=None, horizon_days=None) -> PlanningProposal:
        """Build a structured PlanningProposal with minimal logic for API responses."""

        now = datetime.now(timezone.utc)
        
        # TODO: Replace with real demand/supply data and calculations
        # Currently using stub data to demonstrate non-empty response structure
        lines = [
            PlanningProposalLine(
                sku="SKU-001",
                recommended_units=100,
                reason="stub_logic"
            ),
            PlanningProposalLine(
                sku="SKU-002", 
                recommended_units=50,
                reason="stub_logic"
            )
        ]
        
        total_units = sum(line.recommended_units for line in lines)
        
        return PlanningProposal(
            version="v1",
            generated_at=now,
            inputs=PlanningProposalInputs(
                sales_window_days=sales_window_days,
                horizon_days=horizon_days,
            ),
            summary=PlanningProposalSummary(
                total_skus=len(lines),
                total_units=total_units,
            ),
            lines=lines,
        )
