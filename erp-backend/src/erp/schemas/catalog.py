from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

Name = Annotated[str, Field(min_length=1, max_length=120)]
PositiveInt = Annotated[StrictInt, Field(ge=1)]
NonNegativeInt = Annotated[StrictInt, Field(ge=0)]


class _Request(BaseModel):
    """Request bodies reject unknown fields, so an ID can never be changed through a PATCH."""

    model_config = ConfigDict(extra="forbid")


class _Update(_Request):
    @model_validator(mode="after")
    def _at_least_one_field(self):
        if not self.model_fields_set:
            raise ValueError("Send at least one field to change")
        for field in self.model_fields_set:
            if getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


# Suppliers (FR-004)


class Supplier(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    supplier_id: str
    name: str
    lead_time_days: int


class SupplierCreate(_Request):
    name: Name
    lead_time_days: PositiveInt


class SupplierUpdate(_Update):
    name: Name | None = None
    lead_time_days: PositiveInt | None = None


# Products (FR-003)


class Product(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    product_id: str
    name: str
    preferred_supplier_id: str
    pack_multiple: int
    max_order_qty: int


class ProductCreate(_Request):
    name: Name
    preferred_supplier_id: str = Field(pattern=r"^S[0-9]{3}$")
    pack_multiple: PositiveInt
    max_order_qty: PositiveInt
    starting_stock: NonNegativeInt = 0


class ProductUpdate(_Update):
    name: Name | None = None
    preferred_supplier_id: str | None = Field(default=None, pattern=r"^S[0-9]{3}$")
    pack_multiple: PositiveInt | None = None
    max_order_qty: PositiveInt | None = None


# Stock at the one location (FR-005)


class StockRow(BaseModel):
    product_id: str
    name: str
    on_hand: int
    updated_at: datetime


class StockSet(_Request):
    on_hand: NonNegativeInt
