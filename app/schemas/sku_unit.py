from pydantic import BaseModel


class SkuUnitBase(BaseModel):
    article_id: int
    color_id: int
    size_id: int


class SkuUnitCreate(SkuUnitBase):
    pass


class SkuUnitUpdate(BaseModel):
    article_id: int | None = None
    color_id: int | None = None
    size_id: int | None = None


class SkuUnitRead(SkuUnitBase):
    id: int

    class Config:
        orm_mode = True
