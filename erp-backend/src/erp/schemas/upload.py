from datetime import date

from pydantic import BaseModel


class AcceptedRow(BaseModel):
    row: int  # line number in the file (the header is line 1)
    product_id: str


class RefusedRow(BaseModel):
    row: int
    code: str
    detail: str


class OverriddenRow(BaseModel):
    row: int
    overridden_by_row: int


class UploadResult(BaseModel):
    business_date: date  # today in Africa/Cairo: the only date accepted
    accepted: list[AcceptedRow]
    refused: list[RefusedRow]
    overridden: list[OverriddenRow]
