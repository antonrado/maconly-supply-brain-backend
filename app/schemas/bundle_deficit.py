from pydantic import BaseModel


class DeficitPerSize(BaseModel):
    size_id: int
    size_label: str
    required: dict[int, int]
    current: dict[int, int]
    deficit: dict[int, int]


class BundleDeficitResponse(BaseModel):
    article_id: int
    bundle_type_id: int
    warehouse_id: int
    target_count: int
    per_size: list[DeficitPerSize]
    total_deficit_per_color: dict[int, int]
