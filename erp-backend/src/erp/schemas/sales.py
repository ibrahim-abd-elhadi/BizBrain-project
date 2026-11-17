from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict


class DailyTotal(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    product_id: str
    business_date: date
    units_sold: int
    units_returned: int
    net_units: int
    day_status: Literal["open", "closed"]


class SalesList(BaseModel):
    today: date  # the current business date in Africa/Cairo
    items: list[DailyTotal]
