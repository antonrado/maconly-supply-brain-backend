from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

from sqlalchemy.orm import Session

from app.models.models import BundleRecipe, BundleType, PurchaseOrder, PurchaseOrderItem
from app.services.order_proposal import generate_order_proposal
from app.services.purchase_order import (
    _map_target_date_to_planning_horizon_days,
    create_purchase_order_from_proposal,
)
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


def _setup_article_with_non_zero_proposal(db, code: str = "PO-service-A"):
    """Create article + WB data such that generate_order_proposal returns non-empty items.

    Returns (article, target_date).
    """
    article = create_article(db, code=code)
    size = create_size(db, label=f"S-{code}", sort_order=1)
    color = create_color(db, inner_code=f"C1-{code}")
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

    wb_sku = f"SKU-{code}"
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


def _setup_article_with_canonical_from_wb_inputs(db, target_date: date):
    article = create_article(db, code="PO-service-canonical")
    size = create_size(db, label="PO-service-size", sort_order=1)
    color = create_color(db, inner_code="PO-service-canonical-color")
    create_sku(db, article, color, size)

    bundle_type = BundleType(code="PO-service-bundle", name="PO-service-bundle")
    db.add(bundle_type)
    db.flush()
    db.add(
        BundleRecipe(
            article_id=article.id,
            bundle_type_id=bundle_type.id,
            color_id=color.id,
            position=1,
        )
    )

    create_global_planning_settings(
        db,
        default_fabric_min_batch_qty=0,
        default_elastic_min_batch_qty=0,
        default_production_order_available_capital=10000,
    )
    create_article_planning_settings(
        db,
        article,
        target_coverage_days=60,
        lead_time_days=70,
        service_level_percent=90,
        production_order_production_cost_per_unit=100,
        production_order_logistics_cost_per_unit=20,
        production_order_wb_commission_percent_main=15,
        production_order_wb_commission_percent_assorti=15,
        production_order_average_realized_price_main=500,
        production_order_average_realized_price_assorti=500,
        production_order_available_capital=10000,
    )
    create_planning_settings(
        db,
        article,
        is_active=True,
        min_fabric_batch=0,
        min_elastic_batch=0,
        alert_threshold_days=90,
        strictness=1.0,
    )

    wb_sku = "SKU-PO-service-canonical"
    create_wb_mapping(
        db,
        article,
        wb_sku=wb_sku,
        bundle_type_id=bundle_type.id,
        size_id=size.id,
    )
    add_wb_sales(db, wb_sku=wb_sku, day=target_date - timedelta(days=1), sales_qty=60)
    add_wb_stock(db, wb_sku=wb_sku, stock_qty=20)
    db.commit()

    return article, target_date


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


def test_create_purchase_order_from_proposal_scopes_legacy_fallback_to_article_ids(db_session):
    article_a, target_date = _setup_article_with_non_zero_proposal(
        db_session,
        code="PO-service-scope-A",
    )
    article_b, _ = _setup_article_with_non_zero_proposal(
        db_session,
        code="PO-service-scope-B",
    )

    scoped_proposal = generate_order_proposal(
        db_session,
        target_date=target_date,
        explanation=False,
        article_ids=[article_a.id],
    )
    assert scoped_proposal.items
    assert {item.article_id for item in scoped_proposal.items} == {article_a.id}

    po = create_purchase_order_from_proposal(
        db=db_session,
        target_date=target_date,
        article_ids=[article_a.id],
        explanation=False,
        comment="scoped legacy fallback",
    )

    items = (
        db_session.query(PurchaseOrderItem)
        .filter(PurchaseOrderItem.purchase_order_id == po.id)
        .all()
    )
    assert items
    assert {item.article_id for item in items} == {article_a.id}
    assert article_b.id not in {item.article_id for item in items}

    from collections import defaultdict

    proposal_map = defaultdict(int)
    for it in scoped_proposal.items:
        proposal_map[(it.article_id, it.color_id, it.size_id)] += it.quantity

    po_map = defaultdict(int)
    for it in items:
        po_map[(it.article_id, it.color_id, it.size_id)] += it.quantity

    assert proposal_map == po_map


def test_create_purchase_order_from_proposal_uses_canonical_from_wb_adapter(
    db_session,
    monkeypatch,
):
    target_date = date.today() + timedelta(days=45)
    captured_request = {}

    def fake_build_production_order_proposal_from_wb(*, db, request):
        captured_request["request"] = request
        return SimpleNamespace(
            recommendation=SimpleNamespace(
                lines=[
                    SimpleNamespace(
                        article_id=77,
                        color_id=88,
                        size_id=99,
                        recommended_qty=12,
                    ),
                    SimpleNamespace(
                        article_id=77,
                        color_id=88,
                        size_id=100,
                        recommended_qty=0,
                    ),
                ]
            )
        )

    monkeypatch.setattr(
        "app.services.purchase_order.build_production_order_proposal_from_wb",
        fake_build_production_order_proposal_from_wb,
    )

    po = create_purchase_order_from_proposal(
        db=db_session,
        target_date=target_date,
        article_id=77,
        explanation=False,
        comment="canonical adapter",
    )

    request = captured_request["request"]
    assert request.article_id == 77
    assert request.planning_horizon_days == 45
    assert request.explainability_mode == "compact"

    items = (
        db_session.query(PurchaseOrderItem)
        .filter(PurchaseOrderItem.purchase_order_id == po.id)
        .all()
    )
    assert len(items) == 1
    assert items[0].article_id == 77
    assert items[0].color_id == 88
    assert items[0].size_id == 99
    assert items[0].quantity == 12
    assert po.comment == "canonical adapter"
    assert po.target_date == target_date


def test_create_purchase_order_from_proposal_canonical_adapter_clamps_past_target_date(
    db_session,
    monkeypatch,
):
    target_date = date.today() - timedelta(days=10)
    captured_request = {}

    def fake_build_production_order_proposal_from_wb(*, db, request):
        captured_request["request"] = request
        return SimpleNamespace(recommendation=None)

    monkeypatch.setattr(
        "app.services.purchase_order.build_production_order_proposal_from_wb",
        fake_build_production_order_proposal_from_wb,
    )

    po = create_purchase_order_from_proposal(
        db=db_session,
        target_date=target_date,
        article_id=77,
        explanation=True,
        comment="canonical adapter clamped",
    )

    request = captured_request["request"]
    assert request.article_id == 77
    assert request.planning_horizon_days == 1
    assert request.explainability_mode == "full"

    items = (
        db_session.query(PurchaseOrderItem)
        .filter(PurchaseOrderItem.purchase_order_id == po.id)
        .all()
    )
    assert items == []
    assert po.comment == "canonical adapter clamped"
    assert po.target_date == target_date


def test_map_target_date_to_planning_horizon_days_caps_far_future_dates():
    assert _map_target_date_to_planning_horizon_days(
        date.today() + timedelta(days=500)
    ) == 365


def test_create_purchase_order_from_proposal_canonical_branch_real_integration(
    db_session,
):
    article, target_date = _setup_article_with_canonical_from_wb_inputs(
        db_session,
        target_date=date.today() + timedelta(days=45),
    )

    po = create_purchase_order_from_proposal(
        db=db_session,
        target_date=target_date,
        article_id=article.id,
        explanation=True,
        comment="canonical real integration",
    )

    items = (
        db_session.query(PurchaseOrderItem)
        .filter(PurchaseOrderItem.purchase_order_id == po.id)
        .all()
    )
    assert items
    assert all(item.article_id == article.id for item in items)
    assert all(item.quantity > 0 for item in items)
    assert po.status == "draft"
    assert po.comment == "canonical real integration"
    assert po.target_date == target_date


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
