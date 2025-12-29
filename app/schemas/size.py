from pydantic import BaseModel


class SizeBase(BaseModel):
    label: str
    sort_order: int = 0


class SizeCreate(SizeBase):
    pass


class SizeUpdate(BaseModel):
    label: str | None = None
    sort_order: int | None = None


class SizeRead(SizeBase):
    id: int

    class Config:
        orm_mode = True
