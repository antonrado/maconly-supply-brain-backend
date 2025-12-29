from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from app.models.models import (
    Article,
    ArticlePlanningSettings,
    ArticleWbMapping,
    Color,
    ColorPlanningSettings,
    ElasticPlanningSettings,
    ElasticType,
    GlobalPlanningSettings,
    PlanningSettings,
    Size,
    SkuUnit,
    WbSalesDaily,
    WbStock,
)


def create_article(session: Session, code: str) -> Article:
    article = Article(code=code, name=code)
    session.add(article)
    session.flush()
    return article


def create_color(session: Session, inner_code: str) -> Color:
    color = Color(inner_code=inner_code, description=inner_code)
    session.add(color)
    session.flush()
    return color


def create_size(session: Session, label: str, sort_order: int) -> Size:
    size = Size(label=label, sort_order=sort_order)
    session.add(size)
    session.flush()
    return size


def create_sku(session: Session, article: Article, color: Color, size: Size) -> SkuUnit:
    sku = SkuUnit(article_id=article.id, color_id=color.id, size_id=size.id)
    session.add(sku)
    session.flush()
    return sku


def create_planning_settings(
    session: Session,
    article: Article,
    **kwargs,
) -> PlanningSettings:
    ps = PlanningSettings(
        article_id=article.id,
        is_active=kwargs.get("is_active", True),
        min_fabric_batch=kwargs.get("min_fabric_batch", 0),
        min_elastic_batch=kwargs.get("min_elastic_batch", 0),
        alert_threshold_days=kwargs.get("alert_threshold_days", 0),
        safety_stock_days=kwargs.get("safety_stock_days", 0),
        strictness=kwargs.get("strictness", 1.0),
        notes=kwargs.get("notes"),
    )
    session.add(ps)
    session.flush()
    return ps


def create_color_planning_settings(
    session: Session,
    article: Article,
    color: Color,
    fabric_min_batch_qty: int,
) -> ColorPlanningSettings:
    cps = ColorPlanningSettings(
        article_id=article.id,
        color_id=color.id,
        fabric_min_batch_qty=fabric_min_batch_qty,
    )
    session.add(cps)
    session.flush()
    return cps


def create_elastic_planning_settings(
    session: Session,
    article: Article,
    elastic_min_batch_qty: int,
) -> ElasticPlanningSettings:
    # For tests we create a simple ElasticType per article
    et = ElasticType(code=f"elastic-{article.id}", name=f"Elastic {article.id}")
    session.add(et)
    session.flush()

    eps = ElasticPlanningSettings(
        article_id=article.id,
        elastic_type_id=et.id,
        elastic_min_batch_qty=elastic_min_batch_qty,
    )
    session.add(eps)
    session.flush()
    return eps


def create_global_planning_settings(
    session: Session,
    **kwargs,
) -> GlobalPlanningSettings:
    gps = GlobalPlanningSettings(
        default_target_coverage_days=kwargs.get("default_target_coverage_days", 60),
        default_lead_time_days=kwargs.get("default_lead_time_days", 70),
        default_service_level_percent=kwargs.get("default_service_level_percent", 90),
        default_fabric_min_batch_qty=kwargs.get("default_fabric_min_batch_qty", 7000),
        default_elastic_min_batch_qty=kwargs.get("default_elastic_min_batch_qty", 3000),
    )
    session.add(gps)
    session.flush()
    return gps


def create_article_planning_settings(
    session: Session,
    article: Article,
    **kwargs,
) -> ArticlePlanningSettings:
    aps = ArticlePlanningSettings(
        article_id=article.id,
        include_in_planning=kwargs.get("include_in_planning", True),
        priority=kwargs.get("priority", 0),
        target_coverage_days=kwargs.get("target_coverage_days"),
        lead_time_days=kwargs.get("lead_time_days"),
        service_level_percent=kwargs.get("service_level_percent"),
    )
    session.add(aps)
    session.flush()
    return aps


def create_wb_mapping(
    session: Session,
    article: Article,
    wb_sku: str,
    bundle_type_id: int | None = None,
    color_id: int | None = None,
    size_id: int | None = None,
) -> ArticleWbMapping:
    mapping = ArticleWbMapping(
        article_id=article.id,
        wb_sku=wb_sku,
        bundle_type_id=bundle_type_id,
        color_id=color_id,
        size_id=size_id,
    )
    session.add(mapping)
    session.flush()
    return mapping


def add_wb_sales(
    session: Session,
    wb_sku: str,
    day: date,
    sales_qty: int,
    revenue: float | None = None,
) -> WbSalesDaily:
    row = WbSalesDaily(
        wb_sku=wb_sku,
        date=day,
        sales_qty=sales_qty,
        revenue=revenue,
        created_at=datetime.now(timezone.utc),
    )
    session.add(row)
    session.flush()
    return row


def add_wb_stock(
    session: Session,
    wb_sku: str,
    stock_qty: int,
    warehouse_id: int | None = None,
    warehouse_name: str | None = None,
) -> WbStock:
    row = WbStock(
        wb_sku=wb_sku,
        warehouse_id=warehouse_id,
        warehouse_name=warehouse_name,
        stock_qty=stock_qty,
        updated_at=datetime.now(timezone.utc),
    )
    session.add(row)
    session.flush()
    return row
