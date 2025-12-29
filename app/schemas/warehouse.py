from pydantic import BaseModel


class WarehouseBase(BaseModel):
    code: str
    name: str
    type: str


class WarehouseCreate(WarehouseBase):
    pass


class WarehouseUpdate(BaseModel):
    code: str | None = None
    name: str | None = None
    type: str | None = None


class WarehouseRead(WarehouseBase):
    id: int

    class Config:
        orm_mode = True
