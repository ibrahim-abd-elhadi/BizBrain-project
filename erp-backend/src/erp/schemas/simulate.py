from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from erp.ids import PRODUCT_ID_PATTERN


class SimulateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spike_product_id: str | None = Field(default=None, pattern=PRODUCT_ID_PATTERN)


class ProductBatch(BaseModel):
    product_id: str
    units_sold_added: int
    units_returned_added: int
    capped_by_stock: bool


class SpikeResult(BaseModel):
    product_id: str
    target_net_units: int
    achieved_net_units: int
    capped_by_stock: bool  # true -> the manager is told the spike was capped


class SimulateResult(BaseModel):
    business_date: date
    products: list[ProductBatch]
    spike: SpikeResult | None
