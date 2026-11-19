"""Pydantic models matching contracts/canonical/schemas/ field for field.

Every document carries `schema` and `version` ("1.0") and nothing the contract doesn't define
(FR-004). Every instant is UTC and ends in Z (FR-005).
"""

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    PlainSerializer,
    StringConstraints,
    field_validator,
)

from erp.ids import PRODUCT_ID_PATTERN, SUPPLIER_ID_PATTERN

if TYPE_CHECKING:
    from erp.models import PurchaseOrder as PurchaseOrderRow

VERSION = "1.0"


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("an instant needs a time zone")
    return value.astimezone(UTC)


def _z(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


UtcInstant = Annotated[
    datetime, AfterValidator(_to_utc), PlainSerializer(_z, return_type=str, when_used="always")
]
ProductId = Annotated[str, StringConstraints(pattern=PRODUCT_ID_PATTERN)]
SupplierId = Annotated[str, StringConstraints(pattern=SUPPLIER_ID_PATTERN)]


class CanonicalModel(BaseModel):
    """Refuses unknown fields; `schema` is spelled schema_ in Python (it shadows a BaseModel name)."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True, serialize_by_alias=True)


class ErrorDetail(CanonicalModel):
    field: str | None = None
    issue: str


class ErrorInfo(CanonicalModel):
    code: Literal[
        "VALIDATION_ERROR",
        "NOT_FOUND",
        "CONFLICT",
        "UNAUTHORIZED",
        "FORBIDDEN",
        "DEPENDENCY_UNAVAILABLE",
        "IDEMPOTENCY_CONFLICT",
        "INTERNAL_ERROR",
    ]
    message: str = Field(min_length=1)
    details: list[ErrorDetail]
    trace_id: str = Field(pattern=r"^[0-9a-f]{32}$")


class ErrorBody(CanonicalModel):
    error: ErrorInfo


# Sales (US1): contracts/canonical/schemas/canonical/daily_sales_total.schema.json and sales_page.schema.json


class DailySalesTotal(CanonicalModel):
    schema_: Literal["canonical.DailySalesTotal"] = Field(
        "canonical.DailySalesTotal", alias="schema"
    )
    version: Literal["1.0"] = VERSION
    product_id: ProductId
    business_date: date
    units_sold: int = Field(ge=0)
    units_returned: int = Field(ge=0)
    net_units: int  # negative only if returns exceed sales that day
    day_status: Literal["open", "closed"]
    updated_at: UtcInstant


class SalesPage(CanonicalModel):
    schema_: Literal["canonical.SalesPage"] = Field("canonical.SalesPage", alias="schema")
    version: Literal["1.0"] = VERSION
    items: list[DailySalesTotal]
    next_cursor: str | None
    high_watermark: UtcInstant


# Product, stock and supplier (US2): product, inventory_item and supplier .schema.json


class Product(CanonicalModel):
    schema_: Literal["canonical.Product"] = Field("canonical.Product", alias="schema")
    version: Literal["1.0"] = VERSION
    product_id: ProductId
    name: str = Field(min_length=1, max_length=200)
    preferred_supplier_id: SupplierId | None
    pack_multiple: int | None = Field(ge=1)
    max_order_qty: int | None = Field(ge=1)
    updated_at: UtcInstant


class InventoryItem(CanonicalModel):
    """The stock at the pharmacy's one location: no location or scope field (FR-019)."""

    schema_: Literal["canonical.InventoryItem"] = Field("canonical.InventoryItem", alias="schema")
    version: Literal["1.0"] = VERSION
    product_id: ProductId
    on_hand: int = Field(ge=0)
    available: int = Field(ge=0)  # = on_hand: the ERP holds no reservations
    updated_at: UtcInstant


class Supplier(CanonicalModel):
    schema_: Literal["canonical.Supplier"] = Field("canonical.Supplier", alias="schema")
    version: Literal["1.0"] = VERSION
    supplier_id: SupplierId
    name: str = Field(min_length=1, max_length=200)
    lead_time_days: int | None = Field(ge=0, le=365)
    updated_at: UtcInstant


# Purchase orders (US3, US4): approval_block, purchase_order and purchase_order_page .schema.json

LowerUuid = Annotated[
    str,
    StringConstraints(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"),
]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


def _z_instant(value: str) -> str:
    """The contract's `instant`: an ISO date-time ending in Z (an offset such as +02:00 is refused)."""
    if not value.endswith("Z"):
        raise ValueError("must be a UTC instant ending in Z")
    try:
        datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("must be an ISO 8601 date-time") from exc
    return value


ZInstantText = Annotated[str, AfterValidator(_z_instant)]


class ApprovalBlock(CanonicalModel):
    """Evidence of the manager's approval; the ERP stores it and does not judge it (FR-034)."""

    proposal_id: LowerUuid
    approved_by: str = Field(min_length=1, max_length=128)
    approved_at: ZInstantText
    arguments_sha256: Sha256


class PurchaseOrderLine(CanonicalModel):
    product_id: ProductId
    ordered_qty: int = Field(ge=1)
    received_qty: int = Field(ge=0)
    open_qty: int = Field(ge=0)


class PurchaseOrder(CanonicalModel):
    schema_: Literal["canonical.PurchaseOrder"] = Field("canonical.PurchaseOrder", alias="schema")
    version: Literal["1.0"] = VERSION
    purchase_order_id: int = Field(ge=1)
    supplier_id: SupplierId
    status: Literal["draft", "confirmed"]
    lines: list[PurchaseOrderLine] = Field(min_length=1)
    created_by: Literal["human", "agent"]
    approval: ApprovalBlock | None
    created_at: UtcInstant
    updated_at: UtcInstant


class PurchaseOrderPage(CanonicalModel):
    schema_: Literal["canonical.PurchaseOrderPage"] = Field(
        "canonical.PurchaseOrderPage", alias="schema"
    )
    version: Literal["1.0"] = VERSION
    items: list[PurchaseOrder]
    next_cursor: str | None


def to_canonical_order(order: "PurchaseOrderRow") -> PurchaseOrder:
    """data-model.md: confirming treats quantities as received (feature 001 FR-024), so
    received_qty is 0 for a draft and the full quantity once confirmed."""
    approval = None
    if order.approval_proposal_id is not None:
        approval = ApprovalBlock(
            proposal_id=str(order.approval_proposal_id),
            approved_by=order.approval_approved_by,  # type: ignore[arg-type]
            approved_at=_z(order.approval_approved_at),  # type: ignore[arg-type]
            arguments_sha256=order.approval_arguments_sha256,  # type: ignore[arg-type]
        )
    lines = []
    for line in order.lines:
        received = line.quantity if order.status == "confirmed" else 0
        lines.append(
            PurchaseOrderLine(
                product_id=line.product_id,
                ordered_qty=line.quantity,
                received_qty=received,
                open_qty=line.quantity - received,
            )
        )
    return PurchaseOrder(
        purchase_order_id=order.po_id,
        supplier_id=order.supplier_id,
        status=order.status,  # type: ignore[arg-type]
        lines=lines,
        created_by=order.created_by,  # type: ignore[arg-type]
        approval=approval,
        created_at=order.created_at,
        updated_at=order.updated_at,
    )


# The draft-PO request (US4): create_draft_po_request.schema.json. No `note` (FR-021).


class DraftLine(CanonicalModel):
    product_id: ProductId
    quantity: int = Field(ge=1, strict=True)  # whole units; 1.5 is refused


class CreateDraftPurchaseOrderRequest(CanonicalModel):
    supplier_id: SupplierId
    lines: list[DraftLine] = Field(min_length=1, max_length=50)
    approval: ApprovalBlock

    @field_validator("lines")
    @classmethod
    def _distinct_products(cls, lines: list[DraftLine]) -> list[DraftLine]:
        products = [line.product_id for line in lines]
        if len(set(products)) != len(products):
            raise ValueError("each product may appear at most once")
        return lines
