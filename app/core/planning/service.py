from __future__ import annotations

"""Planning Core v1 service interface.

This module contains minimal business logic to demonstrate data integration
with existing database tables while maintaining a stable API contract.
"""

from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
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
from app.models.models import Article, SkuUnit


class PlanningService:
    """Interface for Planning Core v1 operations.

    Contains minimal data integration logic while maintaining stable API contract.
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
        """Build a PlanningProposal with real SKU data from database."""

        now = datetime.now(timezone.utc)
        
        # Fetch real SKU data from database
        db: Session = SessionLocal()
        try:
            # Get first 10 SKU units with their article codes
            sku_units = db.query(SkuUnit).join(Article).limit(10).all()
            
            lines = []
            for sku_unit in sku_units:
                # Create SKU identifier from article code
                sku_identifier = f"{sku_unit.article.code}-{sku_unit.color_id}-{sku_unit.size_id}"
                
                lines.append(PlanningProposalLine(
                    sku=sku_identifier,
                    recommended_units=0,
                    reason="data_hook_only"
                ))
            
        finally:
            db.close()
        
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
