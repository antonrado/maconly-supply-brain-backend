from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class IntegrationStatus(BaseModel):
    wb_accounts_total: int
    wb_accounts_active: int
    ms_accounts_total: int
    ms_accounts_active: int


class RiskSummary(BaseModel):
    critical: int
    warning: int
    ok: int
    overstock: int
    no_data: int


class OrderSummary(BaseModel):
    articles_with_orders: int
    total_final_order_qty: int


class MonitoringSnapshot(BaseModel):
    integrations: IntegrationStatus
    risks: RiskSummary
    orders: OrderSummary
    updated_at: datetime
