from pydantic import BaseModel, ConfigDict


class ArticleBase(BaseModel):
    code: str
    name: str | None = None


class ArticleCreate(ArticleBase):
    pass


class ArticleUpdate(BaseModel):
    code: str | None = None
    name: str | None = None


class ArticleRead(ArticleBase):
    id: int

    model_config = ConfigDict(from_attributes=True)
