from fastapi import APIRouter

from app.api.v1.endpoints import (
    article,
    color,
    size,
    sku_unit,
    bundle_type,
    bundle_recipe,
    warehouse,
    stock_balance,
    planning,
    deficit,
    planning_settings,
    order_proposal,
    wb,
    wb_manager,
    wb_replenishment,
    wb_shipment,
    purchase_order,
    planning_core,
)

api_router = APIRouter()

api_router.include_router(article.router, prefix="/article", tags=["article"])
api_router.include_router(color.router, prefix="/color", tags=["color"])
api_router.include_router(size.router, prefix="/size", tags=["size"])
api_router.include_router(sku_unit.router, prefix="/sku-unit", tags=["sku-unit"])
api_router.include_router(bundle_type.router, prefix="/bundle-type", tags=["bundle-type"])
api_router.include_router(bundle_recipe.router, prefix="/bundle-recipe", tags=["bundle-recipe"])
api_router.include_router(warehouse.router, prefix="/warehouse", tags=["warehouse"])
api_router.include_router(stock_balance.router, prefix="/stock-balance", tags=["stock-balance"])
api_router.include_router(planning_settings.router, prefix="/planning-settings", tags=["planning-settings"])
api_router.include_router(planning.router, prefix="/planning", tags=["planning"])
api_router.include_router(deficit.router, prefix="/planning", tags=["planning"])
api_router.include_router(order_proposal.router, prefix="/planning", tags=["planning-order-proposal"])
api_router.include_router(planning_core.router, prefix="/planning", tags=["planning-core"])
api_router.include_router(wb.router, prefix="/wb", tags=["wb"])
api_router.include_router(wb_manager.router, prefix="/wb/manager", tags=["wb-manager"])
api_router.include_router(wb_replenishment.router, prefix="/wb/manager", tags=["wb-replenishment"])
api_router.include_router(wb_shipment.router, prefix="/wb/manager", tags=["wb-shipment"])
api_router.include_router(purchase_order.router, prefix="/purchase-order", tags=["purchase-order"])
