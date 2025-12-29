from datetime import datetime

from pydantic import BaseModel


class StockBalanceBase(BaseModel):
    sku_unit_id: int
    warehouse_id: int
    quantity: int
    updated_at: datetime | None = None


class StockBalanceCreate(StockBalanceBase):
    pass


class StockBalanceUpdate(BaseModel):
    sku_unit_id: int | None = None
    warehouse_id: int | None = None
    quantity: int | None = None
    updated_at: datetime | None = None


class StockBalanceRead(StockBalanceBase):
    id: int

    class Config:
        orm_mode = True
