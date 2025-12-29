from pydantic import BaseModel


class BundleTypeBase(BaseModel):
    code: str
    name: str


class BundleTypeCreate(BundleTypeBase):
    pass


class BundleTypeUpdate(BaseModel):
    code: str | None = None
    name: str | None = None


class BundleTypeRead(BundleTypeBase):
    id: int

    class Config:
        orm_mode = True
