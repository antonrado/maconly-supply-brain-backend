from pydantic import BaseModel, ConfigDict


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

    model_config = ConfigDict(from_attributes=True)
