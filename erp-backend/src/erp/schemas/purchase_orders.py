from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class PurchaseOrderLine(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    product_id: str
    quantity: int


class PurchaseOrder(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    po_id: int
    status: Literal["draft", "confirmed"]
    created_at: datetime
    confirmed_at: datetime | None
    lines: list[PurchaseOrderLine]
