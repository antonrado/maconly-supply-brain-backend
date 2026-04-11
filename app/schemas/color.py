from pydantic import BaseModel, ConfigDict


class ColorBase(BaseModel):
    pantone_code: str | None = None
    inner_code: str
    description: str | None = None


class ColorCreate(ColorBase):
    pass


class ColorUpdate(BaseModel):
    pantone_code: str | None = None
    inner_code: str | None = None
    description: str | None = None


class ColorRead(ColorBase):
    id: int

    model_config = ConfigDict(from_attributes=True)
