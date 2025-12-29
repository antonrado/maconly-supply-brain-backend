from pydantic import BaseModel


class BundleRecipeBase(BaseModel):
    article_id: int
    bundle_type_id: int
    color_id: int
    position: int


class BundleRecipeCreate(BundleRecipeBase):
    pass


class BundleRecipeUpdate(BaseModel):
    article_id: int | None = None
    bundle_type_id: int | None = None
    color_id: int | None = None
    position: int | None = None


class BundleRecipeRead(BundleRecipeBase):
    id: int

    class Config:
        orm_mode = True
