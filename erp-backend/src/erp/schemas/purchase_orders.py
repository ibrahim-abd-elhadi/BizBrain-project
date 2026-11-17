from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, model_validator


class PurchaseOrderLine(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    product_id: str
    quantity: int


class Approval(BaseModel):
    """The approval block a Brain draft carries (feature 002, FR-029a): who approved it and when."""

    proposal_id: str
    approved_by: str
    approved_at: datetime
    arguments_sha256: str


class PurchaseOrder(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    po_id: int
    status: Literal["draft", "confirmed"]
    supplier_id: str
    created_by: Literal["human", "agent"]
    approval: Approval | None
    created_at: datetime
    updated_at: datetime
    confirmed_at: datetime | None
    lines: list[PurchaseOrderLine]

    @model_validator(mode="before")
    @classmethod
    def _approval_from_columns(cls, data: Any) -> Any:
        """The model stores the approval block as four columns; the API shows one object."""
        if isinstance(data, dict) or not hasattr(data, "approval_proposal_id"):
            return data
        approval = None
        if data.approval_proposal_id is not None:
            approval = Approval(
                proposal_id=str(data.approval_proposal_id),
                approved_by=data.approval_approved_by,
                approved_at=data.approval_approved_at,
                arguments_sha256=data.approval_arguments_sha256,
            )
        return {
            "po_id": data.po_id,
            "status": data.status,
            "supplier_id": data.supplier_id,
            "created_by": data.created_by,
            "approval": approval,
            "created_at": data.created_at,
            "updated_at": data.updated_at,
            "confirmed_at": data.confirmed_at,
            "lines": [PurchaseOrderLine.model_validate(line) for line in data.lines],
        }
