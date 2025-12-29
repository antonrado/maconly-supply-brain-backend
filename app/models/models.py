from __future__ import annotations

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, UniqueConstraint, Float, Numeric, Text, Boolean, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class Article(Base):
    __tablename__ = "article"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)


class Color(Base):
    __tablename__ = "color"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pantone_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    inner_code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)


class Size(Base):
    __tablename__ = "size"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    label: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class SkuUnit(Base):
    __tablename__ = "sku_unit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    article_id: Mapped[int] = mapped_column(ForeignKey("article.id"), nullable=False)
    color_id: Mapped[int] = mapped_column(ForeignKey("color.id"), nullable=False)
    size_id: Mapped[int] = mapped_column(ForeignKey("size.id"), nullable=False)

    __table_args__ = (
        UniqueConstraint("article_id", "color_id", "size_id", name="uq_sku_unit_article_color_size"),
    )

    article: Mapped[Article] = relationship("Article")
    color: Mapped[Color] = relationship("Color")
    size: Mapped[Size] = relationship("Size")


class BundleType(Base):
    __tablename__ = "bundle_type"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)


class BundleRecipe(Base):
    __tablename__ = "bundle_recipe"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    article_id: Mapped[int] = mapped_column(ForeignKey("article.id"), nullable=False)
    bundle_type_id: Mapped[int] = mapped_column(ForeignKey("bundle_type.id"), nullable=False)
    color_id: Mapped[int] = mapped_column(ForeignKey("color.id"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        UniqueConstraint("article_id", "bundle_type_id", "color_id", name="uq_bundle_recipe_article_bundle_color"),
        UniqueConstraint("article_id", "bundle_type_id", "position", name="uq_bundle_recipe_article_bundle_position"),
    )

    article: Mapped[Article] = relationship("Article")
    bundle_type: Mapped[BundleType] = relationship("BundleType")
    color: Mapped[Color] = relationship("Color")


class Warehouse(Base):
    __tablename__ = "warehouse"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False)


class StockBalance(Base):
    __tablename__ = "stock_balance"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sku_unit_id: Mapped[int] = mapped_column(ForeignKey("sku_unit.id"), nullable=False)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouse.id"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("sku_unit_id", "warehouse_id", name="uq_stock_balance_sku_warehouse"),
    )

    sku_unit: Mapped[SkuUnit] = relationship("SkuUnit")
    warehouse: Mapped[Warehouse] = relationship("Warehouse")


class ArticlePlanningSettings(Base):
    __tablename__ = "article_planning_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    article_id: Mapped[int] = mapped_column(
        ForeignKey("article.id"), nullable=False, unique=True
    )
    include_in_planning: Mapped[bool] = mapped_column(nullable=False, default=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    target_coverage_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lead_time_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    service_level_percent: Mapped[int | None] = mapped_column(Integer, nullable=True)


class ColorPlanningSettings(Base):
    __tablename__ = "color_planning_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    article_id: Mapped[int] = mapped_column(ForeignKey("article.id"), nullable=False)
    color_id: Mapped[int] = mapped_column(ForeignKey("color.id"), nullable=False)
    fabric_min_batch_qty: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "article_id",
            "color_id",
            name="uq_color_planning_article_color",
        ),
    )


class ElasticType(Base):
    __tablename__ = "elastic_type"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)


class ElasticPlanningSettings(Base):
    __tablename__ = "elastic_planning_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    article_id: Mapped[int] = mapped_column(ForeignKey("article.id"), nullable=False)
    elastic_type_id: Mapped[int] = mapped_column(
        ForeignKey("elastic_type.id"),
        nullable=False,
    )
    elastic_min_batch_qty: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "article_id",
            "elastic_type_id",
            name="uq_elastic_planning_article_type",
        ),
    )


class GlobalPlanningSettings(Base):
    __tablename__ = "global_planning_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    default_target_coverage_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=60
    )
    default_lead_time_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=70
    )
    default_service_level_percent: Mapped[int] = mapped_column(
        Integer, nullable=False, default=90
    )
    default_fabric_min_batch_qty: Mapped[int] = mapped_column(
        Integer, nullable=False, default=7000
    )
    default_elastic_min_batch_qty: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3000
    )


class PlanningSettings(Base):
    __tablename__ = "planning_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    article_id: Mapped[int] = mapped_column(ForeignKey("article.id"), nullable=False)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)
    min_fabric_batch: Mapped[int] = mapped_column(Integer, nullable=False)
    min_elastic_batch: Mapped[int] = mapped_column(Integer, nullable=False)
    alert_threshold_days: Mapped[int] = mapped_column(Integer, nullable=False)
    safety_stock_days: Mapped[int] = mapped_column(Integer, nullable=False)
    strictness: Mapped[float] = mapped_column(Float, nullable=False)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)

    __table_args__ = (
        UniqueConstraint("article_id", name="uq_planning_settings_article"),
    )


class WbSalesDaily(Base):
    __tablename__ = "wb_sales_daily"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    wb_sku: Mapped[str] = mapped_column(Text, nullable=False)
    date: Mapped[Date] = mapped_column(Date, nullable=False)
    sales_qty: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    revenue: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("wb_sku", "date", name="uq_wb_sales_daily_sku_date"),
    )


class WbStock(Base):
    __tablename__ = "wb_stock"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    wb_sku: Mapped[str] = mapped_column(Text, nullable=False)
    warehouse_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    warehouse_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    stock_qty: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("wb_sku", "warehouse_id", name="uq_wb_stock_sku_warehouse"),
    )


class ArticleWbMapping(Base):
    __tablename__ = "article_wb_mapping"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    article_id: Mapped[int] = mapped_column(ForeignKey("article.id"), nullable=False)
    wb_sku: Mapped[str] = mapped_column(Text, nullable=False)
    bundle_type_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    color_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    size_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "article_id",
            "wb_sku",
            name="uq_article_wb_mapping_article_sku",
        ),
    )


class PurchaseOrder(Base):
    __tablename__ = "purchase_order"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    target_date: Mapped[Date] = mapped_column(Date, nullable=False)
    comment: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    external_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)

    items: Mapped[list["PurchaseOrderItem"]] = relationship("PurchaseOrderItem", back_populates="purchase_order")


class PurchaseOrderItem(Base):
    __tablename__ = "purchase_order_item"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    purchase_order_id: Mapped[int] = mapped_column(ForeignKey("purchase_order.id"), nullable=False)
    article_id: Mapped[int] = mapped_column(ForeignKey("article.id"), nullable=False)
    color_id: Mapped[int] = mapped_column(ForeignKey("color.id"), nullable=False)
    size_id: Mapped[int] = mapped_column(ForeignKey("size.id"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="auto")
    notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    purchase_order: Mapped[PurchaseOrder] = relationship("PurchaseOrder", back_populates="items")

    __table_args__ = (
        UniqueConstraint(
            "purchase_order_id",
            "article_id",
            "color_id",
            "size_id",
            name="uq_po_item_po_article_color_size",
        ),
    )


class WbShipment(Base):
    __tablename__ = "wb_shipment"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    target_date: Mapped[Date] = mapped_column(Date, nullable=False)
    wb_arrival_date: Mapped[Date] = mapped_column(Date, nullable=False)
    comment: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False)
    strategy: Mapped[str] = mapped_column(String(50), nullable=False)
    zero_sales_policy: Mapped[str] = mapped_column(String(50), nullable=False)
    target_coverage_days: Mapped[int] = mapped_column(Integer, nullable=False)
    min_coverage_days: Mapped[int] = mapped_column(Integer, nullable=False)
    max_coverage_days_after: Mapped[int] = mapped_column(Integer, nullable=False)
    max_replenishment_per_article: Mapped[int | None] = mapped_column(Integer, nullable=True)

    items: Mapped[list["WbShipmentItem"]] = relationship("WbShipmentItem", back_populates="shipment")


class WbShipmentItem(Base):
    __tablename__ = "wb_shipment_item"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shipment_id: Mapped[int] = mapped_column(ForeignKey("wb_shipment.id"), nullable=False)
    article_id: Mapped[int] = mapped_column(ForeignKey("article.id"), nullable=False)
    color_id: Mapped[int] = mapped_column(ForeignKey("color.id"), nullable=False)
    size_id: Mapped[int] = mapped_column(ForeignKey("size.id"), nullable=False)
    wb_sku: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommended_qty: Mapped[int] = mapped_column(Integer, nullable=False)
    final_qty: Mapped[int] = mapped_column(Integer, nullable=False)
    nsk_stock_available: Mapped[int] = mapped_column(Integer, nullable=False)
    oos_risk_before: Mapped[str] = mapped_column(String(50), nullable=False)
    oos_risk_after: Mapped[str] = mapped_column(String(50), nullable=False)
    limited_by_nsk_stock: Mapped[bool] = mapped_column(Boolean, nullable=False)
    limited_by_max_coverage: Mapped[bool] = mapped_column(Boolean, nullable=False)
    ignored_due_to_zero_sales: Mapped[bool] = mapped_column(Boolean, nullable=False)
    below_min_coverage_threshold: Mapped[bool] = mapped_column(Boolean, nullable=False)
    article_total_deficit: Mapped[int] = mapped_column(Integer, nullable=False)
    article_total_recommended: Mapped[int] = mapped_column(Integer, nullable=False)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)

    shipment: Mapped[WbShipment] = relationship("WbShipment", back_populates="items")


class WbIntegrationAccount(Base):
    __tablename__ = "wb_integration_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    supplier_id: Mapped[str | None] = mapped_column(String, nullable=True)
    api_token: Mapped[str] = mapped_column(String, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class MonitoringAlertRule(Base):
    __tablename__ = "monitoring_alert_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)

    metric: Mapped[str] = mapped_column(String, nullable=False)
    threshold_type: Mapped[str] = mapped_column(String, nullable=False)
    threshold_value: Mapped[int] = mapped_column(Integer, nullable=False)

    severity: Mapped[str] = mapped_column(String, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class MonitoringSnapshotRecord(Base):
    __tablename__ = "monitoring_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    wb_accounts_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    wb_accounts_active: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ms_accounts_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ms_accounts_active: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    risk_critical: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    risk_warning: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    risk_ok: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    risk_overstock: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    risk_no_data: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    articles_with_orders: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_final_order_qty: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class MoySkladIntegrationAccount(Base):
    __tablename__ = "moysklad_integration_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    account_id: Mapped[str | None] = mapped_column(String, nullable=True)
    api_token: Mapped[str] = mapped_column(String, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
