from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class ProductionOrderSizeWeightInput(BaseModel):
    size_id: int = Field(..., ge=1)
    weight: float = Field(..., gt=0)


class ProductionOrderElasticBindingInput(BaseModel):
    elastic_type_id: int = Field(..., ge=1)
    color_id: int | None = Field(default=None, ge=1)
    sku_unit_id: int | None = Field(default=None, ge=1)
    is_active: bool = True

    @model_validator(mode="after")
    def validate_scope(self) -> "ProductionOrderElasticBindingInput":
        if self.color_id is None and self.sku_unit_id is None:
            raise ValueError("Either color_id or sku_unit_id must be provided")
        return self


class ProductionOrderInFlightDefaultInput(BaseModel):
    color_id: int = Field(..., ge=1)
    size_id: int = Field(..., ge=1)
    qty: int = Field(..., ge=0)
    eta_days: int = Field(..., ge=0)
    stage: Literal["production", "china_to_nsk", "packaging", "nsk_to_wb", "other"] = "other"
    is_active: bool = True


class ProductionOrderAdminSettingsUpsertRequest(BaseModel):
    size_weights: list[ProductionOrderSizeWeightInput] = Field(default_factory=list)
    elastic_bindings: list[ProductionOrderElasticBindingInput] = Field(default_factory=list)
    in_flight_supply_defaults: list[ProductionOrderInFlightDefaultInput] = Field(default_factory=list)
    freshness_sales_stale_after_days: int | None = Field(default=None, ge=0, le=3650)
    freshness_stock_stale_after_days: int | None = Field(default=None, ge=0, le=3650)

    @field_validator("size_weights")
    @classmethod
    def validate_unique_size_ids(
        cls,
        value: list[ProductionOrderSizeWeightInput],
    ) -> list[ProductionOrderSizeWeightInput]:
        seen: set[int] = set()
        for item in value:
            if item.size_id in seen:
                raise ValueError("size_weights contains duplicate size_id")
            seen.add(item.size_id)
        return value

    @field_validator("elastic_bindings")
    @classmethod
    def validate_unique_elastic_bindings(
        cls,
        value: list[ProductionOrderElasticBindingInput],
    ) -> list[ProductionOrderElasticBindingInput]:
        seen: set[tuple[int, int | None, int | None]] = set()
        for item in value:
            key = (item.elastic_type_id, item.color_id, item.sku_unit_id)
            if key in seen:
                raise ValueError("elastic_bindings contains duplicate entries")
            seen.add(key)
        return value

    @field_validator("in_flight_supply_defaults")
    @classmethod
    def validate_unique_in_flight_defaults(
        cls,
        value: list[ProductionOrderInFlightDefaultInput],
    ) -> list[ProductionOrderInFlightDefaultInput]:
        seen: set[tuple[int, int, str, int]] = set()
        for item in value:
            key = (item.color_id, item.size_id, item.stage, item.eta_days)
            if key in seen:
                raise ValueError("in_flight_supply_defaults contains duplicate entries")
            seen.add(key)
        return value


class ProductionOrderAdminSettingsResponse(BaseModel):
    article_id: int
    size_weights: list[ProductionOrderSizeWeightInput] = Field(default_factory=list)
    elastic_bindings: list[ProductionOrderElasticBindingInput] = Field(default_factory=list)
    in_flight_supply_defaults: list[ProductionOrderInFlightDefaultInput] = Field(default_factory=list)
    freshness_sales_stale_after_days: int | None = None
    freshness_stock_stale_after_days: int | None = None
