from pydantic import BaseModel


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

    class Config:
        orm_mode = True
