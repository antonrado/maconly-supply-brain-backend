from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class MonitoringSnapshotRecordSchema(BaseModel):
    id: int
    created_at: datetime

    wb_accounts_total: int
    wb_accounts_active: int
    ms_accounts_total: int
    ms_accounts_active: int

    risk_critical: int
    risk_warning: int
    risk_ok: int
    risk_overstock: int
    risk_no_data: int

    articles_with_orders: int
    total_final_order_qty: int

    class Config:
        orm_mode = True
        from_attributes = True


class MonitoringHistoryResponse(BaseModel):
    items: list[MonitoringSnapshotRecordSchema]
