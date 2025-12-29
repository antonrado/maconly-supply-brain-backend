from pydantic import BaseModel


class BundleAvailabilityPerSize(BaseModel):
    size_id: int
    size_label: str
    available: int


class BundleAvailabilityResponse(BaseModel):
    article_id: int
    bundle_type_id: int
    warehouse_id: int
    total_available: int
    per_size: list[BundleAvailabilityPerSize]
