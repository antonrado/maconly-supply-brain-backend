from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models.models import (
    Article,
    ArticlePlanningSettings,
    ArticleWbMapping,
    BundleRecipe,
    BundleType,
    Color,
    GlobalPlanningSettings,
    PlanningSettings,
    Size,
    SkuUnit,
    StockBalance,
    Warehouse,
    WbSalesDaily,
    WbStock,
)

SMOKE_ARTICLE_CODE = "PO-SMOKE-ART-API"
SMOKE_BUNDLE_CODE = "PO-SMOKE-BT-1"
SMOKE_WAREHOUSE_CODE = "PO-SMOKE-NSK"
SMOKE_WB_SKU = "PO-SMOKE-WB-BT1"


def _one_or_none(db, model, *conditions):
    return db.execute(select(model).where(*conditions)).scalar_one_or_none()


def _ensure_article(db) -> Article:
    article = _one_or_none(db, Article, Article.code == SMOKE_ARTICLE_CODE)
    if article is None:
        article = Article(code=SMOKE_ARTICLE_CODE, name="Production Order Smoke Article")
        db.add(article)
        db.flush()
    return article


def _ensure_color(db, inner_code: str, pantone: str, description: str) -> Color:
    color = _one_or_none(db, Color, Color.inner_code == inner_code)
    if color is None:
        color = Color(inner_code=inner_code, pantone_code=pantone, description=description)
        db.add(color)
        db.flush()
    return color


def _ensure_size(db, label: str, sort_order: int) -> Size:
    size = _one_or_none(db, Size, Size.label == label)
    if size is None:
        size = Size(label=label, sort_order=sort_order)
        db.add(size)
        db.flush()
    return size


def _ensure_bundle_type(db) -> BundleType:
    bundle_type = _one_or_none(db, BundleType, BundleType.code == SMOKE_BUNDLE_CODE)
    if bundle_type is None:
        bundle_type = BundleType(code=SMOKE_BUNDLE_CODE, name="Smoke Bundle", is_assorti=False)
        db.add(bundle_type)
        db.flush()
    return bundle_type


def _ensure_warehouse(db) -> Warehouse:
    warehouse = _one_or_none(db, Warehouse, Warehouse.code == SMOKE_WAREHOUSE_CODE)
    if warehouse is None:
        warehouse = Warehouse(code=SMOKE_WAREHOUSE_CODE, name="Smoke Warehouse", type="local")
        db.add(warehouse)
        db.flush()
    return warehouse


def _ensure_sku(db, article_id: int, color_id: int, size_id: int) -> SkuUnit:
    sku = _one_or_none(
        db,
        SkuUnit,
        SkuUnit.article_id == article_id,
        SkuUnit.color_id == color_id,
        SkuUnit.size_id == size_id,
    )
    if sku is None:
        sku = SkuUnit(article_id=article_id, color_id=color_id, size_id=size_id)
        db.add(sku)
        db.flush()
    return sku


def _ensure_stock_balance(db, sku_unit_id: int, warehouse_id: int, now: datetime) -> None:
    stock_balance = _one_or_none(
        db,
        StockBalance,
        StockBalance.sku_unit_id == sku_unit_id,
        StockBalance.warehouse_id == warehouse_id,
    )
    if stock_balance is None:
        stock_balance = StockBalance(
            sku_unit_id=sku_unit_id,
            warehouse_id=warehouse_id,
            quantity=10,
            updated_at=now,
        )
        db.add(stock_balance)
    else:
        stock_balance.quantity = 10
        stock_balance.updated_at = now


def _ensure_bundle_recipe(db, article_id: int, bundle_type_id: int, color_id: int, position: int) -> None:
    recipe = _one_or_none(
        db,
        BundleRecipe,
        BundleRecipe.article_id == article_id,
        BundleRecipe.bundle_type_id == bundle_type_id,
        BundleRecipe.color_id == color_id,
    )
    if recipe is None:
        recipe = BundleRecipe(
            article_id=article_id,
            bundle_type_id=bundle_type_id,
            color_id=color_id,
            position=position,
        )
        db.add(recipe)
    else:
        recipe.position = position


def _ensure_global_settings(db) -> None:
    global_settings = db.execute(
        select(GlobalPlanningSettings).order_by(GlobalPlanningSettings.id)
    ).scalars().first()
    if global_settings is None:
        db.add(
            GlobalPlanningSettings(
                default_target_coverage_days=60,
                default_lead_time_days=70,
                default_service_level_percent=90,
                default_fabric_min_batch_qty=7000,
                default_elastic_min_batch_qty=3000,
                default_production_order_available_capital=10000,
            )
        )
    elif getattr(global_settings, "default_production_order_available_capital", None) is None:
        global_settings.default_production_order_available_capital = 10000


def _ensure_article_settings(db, article_id: int) -> None:
    article_settings = _one_or_none(
        db,
        ArticlePlanningSettings,
        ArticlePlanningSettings.article_id == article_id,
    )
    if article_settings is None:
        article_settings = ArticlePlanningSettings(
            article_id=article_id,
            include_in_planning=True,
            priority=2,
            target_coverage_days=60,
            lead_time_days=70,
            service_level_percent=90,
        )
        db.add(article_settings)
    else:
        article_settings.include_in_planning = True
        article_settings.priority = 2
        article_settings.target_coverage_days = 60
        article_settings.lead_time_days = 70
        article_settings.service_level_percent = 90


def _ensure_planning_settings(db, article_id: int) -> None:
    planning_settings = _one_or_none(
        db,
        PlanningSettings,
        PlanningSettings.article_id == article_id,
    )
    if planning_settings is None:
        db.add(
            PlanningSettings(
                article_id=article_id,
                is_active=True,
                min_fabric_batch=0,
                min_elastic_batch=0,
                alert_threshold_days=90,
                safety_stock_days=0,
                strictness=1.0,
                notes=None,
            )
        )
    else:
        planning_settings.is_active = True
        planning_settings.min_fabric_batch = 0
        planning_settings.min_elastic_batch = 0
        planning_settings.alert_threshold_days = 90
        planning_settings.safety_stock_days = 0
        planning_settings.strictness = 1.0


def _ensure_wb_mapping(db, article_id: int, bundle_type_id: int, size_id: int) -> None:
    mapping = _one_or_none(
        db,
        ArticleWbMapping,
        ArticleWbMapping.article_id == article_id,
        ArticleWbMapping.wb_sku == SMOKE_WB_SKU,
    )
    if mapping is None:
        mapping = ArticleWbMapping(
            article_id=article_id,
            wb_sku=SMOKE_WB_SKU,
            bundle_type_id=bundle_type_id,
            size_id=size_id,
        )
        db.add(mapping)
    else:
        mapping.bundle_type_id = bundle_type_id
        mapping.size_id = size_id


def _ensure_wb_sales_and_stock(db, now: datetime) -> None:
    sales_date = now.date()
    wb_sales = _one_or_none(
        db,
        WbSalesDaily,
        WbSalesDaily.wb_sku == SMOKE_WB_SKU,
        WbSalesDaily.date == sales_date,
    )
    if wb_sales is None:
        wb_sales = WbSalesDaily(
            wb_sku=SMOKE_WB_SKU,
            date=sales_date,
            sales_qty=60,
            revenue=None,
            created_at=now,
        )
        db.add(wb_sales)
    else:
        wb_sales.sales_qty = 60
        wb_sales.created_at = now

    wb_stock = _one_or_none(
        db,
        WbStock,
        WbStock.wb_sku == SMOKE_WB_SKU,
        WbStock.warehouse_id == 1,
    )
    if wb_stock is None:
        wb_stock = WbStock(
            wb_sku=SMOKE_WB_SKU,
            warehouse_id=1,
            warehouse_name="WB-1",
            stock_qty=20,
            updated_at=now,
        )
        db.add(wb_stock)
    else:
        wb_stock.warehouse_name = "WB-1"
        wb_stock.stock_qty = 20
        wb_stock.updated_at = now


def main() -> None:
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)

        article = _ensure_article(db)
        color_1 = _ensure_color(db, "PO-SMOKE-C1", "SMOKE-BLACK-01", "Smoke Black")
        color_2 = _ensure_color(db, "PO-SMOKE-C2", "SMOKE-BLACK-02", "Smoke Gray")
        size_s = _ensure_size(db, "PO-SMOKE-S", 1)
        size_m = _ensure_size(db, "PO-SMOKE-M", 2)
        bundle_type = _ensure_bundle_type(db)
        warehouse = _ensure_warehouse(db)

        sku_ids = [
            _ensure_sku(db, article.id, color_1.id, size_s.id).id,
            _ensure_sku(db, article.id, color_1.id, size_m.id).id,
            _ensure_sku(db, article.id, color_2.id, size_s.id).id,
            _ensure_sku(db, article.id, color_2.id, size_m.id).id,
        ]

        for sku_id in sku_ids:
            _ensure_stock_balance(db, sku_id, warehouse.id, now)

        _ensure_bundle_recipe(db, article.id, bundle_type.id, color_1.id, 1)
        _ensure_bundle_recipe(db, article.id, bundle_type.id, color_2.id, 2)

        _ensure_global_settings(db)
        _ensure_article_settings(db, article.id)
        _ensure_planning_settings(db, article.id)

        _ensure_wb_mapping(db, article.id, bundle_type.id, size_s.id)
        _ensure_wb_sales_and_stock(db, now)

        db.commit()

        payloads = {
            "direct_payload": {
                "article_id": article.id,
                "planning_horizon_days": 90,
                "bundle_daily_sales": [
                    {
                        "bundle_type_id": bundle_type.id,
                        "daily_sales": 20.0,
                    }
                ],
                "bundle_stock": [
                    {
                        "bundle_type_id": bundle_type.id,
                        "wb_qty": 5,
                        "local_qty": 5,
                    }
                ],
                "in_flight_supply": [],
                "size_weights": {
                    size_s.id: 0.55,
                    size_m.id: 0.45,
                },
                "overrides": {
                    "fabric_min_batch_qty_default": 0,
                    "elastic_min_batch_qty_default": 0,
                    "available_capital": 10000,
                    "allow_order_with_buffer": False,
                },
            },
            "from_wb_payload": {
                "article_id": article.id,
                "planning_horizon_days": 90,
                "observation_window_days": 30,
                "bundle_type_ids": [bundle_type.id],
                "in_flight_supply": [],
                "size_weights": {},
                "overrides": {
                    "fabric_min_batch_qty_default": 0,
                    "elastic_min_batch_qty_default": 0,
                    "available_capital": 10000,
                    "allow_order_with_buffer": False,
                },
            },
        }
        print(json.dumps(payloads))
    finally:
        db.close()


if __name__ == "__main__":
    main()
