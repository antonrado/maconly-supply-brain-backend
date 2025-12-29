from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.models.models import PurchaseOrder, PurchaseOrderItem
from app.services.order_proposal import generate_order_proposal
from app.services.purchase_order import create_purchase_order_from_proposal
from tests.test_utils import (
    add_wb_sales,
    add_wb_stock,
    create_article,
    create_article_planning_settings,
    create_color,
    create_global_planning_settings,
    create_planning_settings,
    create_size,
    create_sku,
    create_wb_mapping,
)


def _setup_article_with_non_zero_proposal(db):
    """Create article + WB data such that generate_order_proposal returns non-empty items.

    Returns (article, target_date).
    """
    article = create_article(db, code="PO-service-A")
    size = create_size(db, label="S", sort_order=1)
    color = create_color(db, inner_code="C1")
    create_sku(db, article, color, size)

    create_global_planning_settings(db)
    create_article_planning_settings(db, article, target_coverage_days=10)
    create_planning_settings(
        db,
        article,
        is_active=True,
        min_fabric_batch=0,
        min_elastic_batch=0,
        strictness=1.0,
    )

    wb_sku = "SKU-PO-service-A"
    create_wb_mapping(db, article, wb_sku=wb_sku)
    target_date = date(2025, 1, 31)
    add_wb_sales(db, wb_sku=wb_sku, day=target_date, sales_qty=10)
    add_wb_stock(db, wb_sku=wb_sku, stock_qty=0)

    return article, target_date


def _setup_article_with_empty_proposal(db):
    """Create article and planning settings so that order_proposal has no items.

    We create SKU units but do not create any WB mapping or sales,
    so compute_demand yields zero deficit and proposal is empty.
    """
    article = create_article(db, code="PO-service-empty")
    size = create_size(db, label="S", sort_order=1)
    color = create_color(db, inner_code="C-empty")
    create_sku(db, article, color, size)

    create_global_planning_settings(db)
    create_article_planning_settings(db, article, target_coverage_days=10)
    create_planning_settings(
        db,
        article,
        is_active=True,
        min_fabric_batch=0,
        min_elastic_batch=0,
        strictness=1.0,
    )

    return article, date(2025, 1, 31)


def test_create_purchase_order_from_non_empty_proposal(db_session):
    """Base case: PO created from non-empty order_proposal, items mirror proposal items."""
    article, target_date = _setup_article_with_non_zero_proposal(db_session)

    proposal = generate_order_proposal(
        db_session,
        target_date=target_date,
        explanation=True,
    )
    assert proposal.items, "Expected non-empty proposal for test setup"

    comment = "Test PO from proposal (service)"
    po = create_purchase_order_from_proposal(
        db=db_session,
        target_date=target_date,
        explanation=True,
        comment=comment,
    )

    assert isinstance(po, PurchaseOrder)
    assert po.status == "draft"
    assert po.target_date == target_date
    assert po.comment == comment

    items = (
        db_session.query(PurchaseOrderItem)
        .filter(PurchaseOrderItem.purchase_order_id == po.id)
        .all()
    )
    assert len(items) == len(proposal.items)

    # Build mapping from (article, color, size) to quantity for both proposal and PO
    from collections import defaultdict

    proposal_map = defaultdict(int)
    for it in proposal.items:
        proposal_map[(it.article_id, it.color_id, it.size_id)] += it.quantity

    po_map = defaultdict(int)
    for it in items:
        assert it.source == "auto"
        assert it.notes is None
        po_map[(it.article_id, it.color_id, it.size_id)] += it.quantity

    assert proposal_map == po_map
    assert sum(proposal_map.values()) == sum(po_map.values())


def test_create_purchase_order_from_empty_proposal(db_session):
    """When order_proposal has no items, PO is still created but without items."""
    article, target_date = _setup_article_with_empty_proposal(db_session)

    proposal = generate_order_proposal(
        db_session,
        target_date=target_date,
        explanation=True,
    )
    assert proposal.items == []

    po = create_purchase_order_from_proposal(
        db=db_session,
        target_date=target_date,
        explanation=True,
        comment=None,
    )

    assert isinstance(po, PurchaseOrder)
    items = (
        db_session.query(PurchaseOrderItem)
        .filter(PurchaseOrderItem.purchase_order_id == po.id)
        .all()
    )
    assert items == []


def test_explanation_flag_does_not_affect_po_items(db_session):
    """Explanation flag should not change resulting PO items or quantities."""
    article, target_date = _setup_article_with_non_zero_proposal(db_session)

    po1 = create_purchase_order_from_proposal(
        db=db_session,
        target_date=target_date,
        explanation=True,
        comment="with explanation",
    )
    po2 = create_purchase_order_from_proposal(
        db=db_session,
        target_date=target_date,
        explanation=False,
        comment="without explanation",
    )

    items1 = (
        db_session.query(PurchaseOrderItem)
        .filter(PurchaseOrderItem.purchase_order_id == po1.id)
        .all()
    )
    items2 = (
        db_session.query(PurchaseOrderItem)
        .filter(PurchaseOrderItem.purchase_order_id == po2.id)
        .all()
    )

    assert len(items1) == len(items2)

    from collections import defaultdict

    def build_map(items):
        m = defaultdict(int)
        for it in items:
            m[(it.article_id, it.color_id, it.size_id)] += it.quantity
        return m

    assert build_map(items1) == build_map(items2)
