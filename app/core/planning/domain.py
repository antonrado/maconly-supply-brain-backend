from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import List, Optional


@dataclass
class PlanningSettings:
    """High-level planning configuration for a planning run.

    This is intentionally minimal and will evolve together with Planning Core v1.
    """

    planning_horizon_days: int
    """Number of days ahead the planner should look when proposing orders."""

    service_level_percent: float
    """Target service level (0-100) used as a guideline for safety stock sizing."""


@dataclass
class DemandInput:
    """External demand signal for a single article or SKU.

    At this stage this is a placeholder; real demand models will be introduced later.
    """

    article_id: int
    """Internal identifier of the article being planned."""

    target_date: date
    """Date for which demand is being evaluated (e.g. planning horizon end date)."""

    expected_demand_units: int
    """Estimated units of demand over the relevant horizon."""


@dataclass
class SupplyInput:
    """Current and incoming supply for a single article or SKU.

    This aggregates on-hand inventory and already-placed supply such as PO lines.
    """

    article_id: int
    """Internal identifier of the article being planned."""

    on_hand_units: int
    """Units currently available in stock."""

    incoming_units: int
    """Units that are already ordered and expected to arrive within the horizon."""


@dataclass
class OrderProposal:
    """Skeleton representation of a proposed replenishment order.

    No allocation or vendor logic is encoded here; this is purely a placeholder.
    """

    article_id: int
    """Internal identifier of the article to replenish."""

    proposed_order_qty: int
    """Total quantity that the planner suggests to order."""

    comment: Optional[str] = None
    """Optional human-readable note explaining the proposal (to be filled later)."""


@dataclass
class PlanningHealth:
    """Aggregated health status for planning configuration and inputs.

    Used as a coarse summary for API consumers; details will be refined later.
    """

    status: str
    """High-level status label such as "ok", "warning" or "critical"."""

    issues: List[str]
    """List of human-readable issues detected in planning inputs/configuration."""
