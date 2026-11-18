"""The Brain's only way into ERP data: the five Canonical GETs of README Section 3 (research R-02),
and its only business write, the approved draft purchase order (feature 004, research R-10).

The service token is read from its file when a client is created (once per job run), so a newly
issued token is picked up without a restart. Neither the token nor the Authorization header is
ever logged or put into an error message (FR-001). There are no retries inside a run: the
schedule is the retry.
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Self

import httpx

from brain.config import Settings

# Tests point every client at a fake Canonical API (tests/fakes.py) by setting this.
TEST_TRANSPORT: httpx.BaseTransport | None = None


class CanonicalUnavailable(Exception):
    """A Canonical call failed (transport, timeout, 401/403, 5xx), or the token can't be read."""

    def __init__(self, operation: str, detail: str) -> None:
        super().__init__(f"{operation} failed: {detail}")
        self.operation = operation
        self.detail = detail


class CanonicalNotFound(Exception):
    """The ERP answered 404 for a product or supplier."""


@dataclass(frozen=True)
class SalesRow:
    product_id: str
    business_date: date
    units_sold: int
    units_returned: int
    net_units: int
    day_status: str
    updated_at: datetime


@dataclass(frozen=True)
class SalesPage:
    items: list[SalesRow]
    next_cursor: str | None
    high_watermark: datetime


@dataclass(frozen=True)
class Product:
    product_id: str
    name: str
    preferred_supplier_id: str | None
    pack_multiple: int | None
    max_order_qty: int | None


@dataclass(frozen=True)
class Inventory:
    product_id: str
    on_hand: int
    available: int


@dataclass(frozen=True)
class Supplier:
    supplier_id: str
    name: str
    lead_time_days: int | None


@dataclass(frozen=True)
class OpenOrder:
    """One open purchase order, with this product's open quantity (feature 005's chat tool)."""

    purchase_order_id: int
    supplier_id: str
    status: str
    open_qty: int


@dataclass(frozen=True)
class SendResult:
    """What came back from one draft-PO request. `error` is "timeout", "connection" (the request
    may or may not have reached the ERP) or "not_sent" (the token file couldn't be read, so
    nothing was sent). `body` is the parsed JSON, or None when the answer wasn't JSON."""

    status: int | None = None
    body: Any = None
    error: str | None = None


def _instant(text: str) -> datetime:
    return datetime.fromisoformat(text)


class CanonicalClient:
    def __init__(
        self,
        base_url: str,
        token_file: Path,
        timeout: float = 10.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        try:
            token = Path(token_file).read_text(encoding="utf-8").strip()
        except OSError:
            raise CanonicalUnavailable(
                "service token", f"the token file {token_file} could not be read"
            ) from None
        if not token:
            raise CanonicalUnavailable("service token", f"the token file {token_file} is empty")
        self._http = httpx.Client(
            base_url=base_url.rstrip("/") + "/api/v1/canonical",
            timeout=timeout,
            transport=transport,
            headers={"Authorization": f"Bearer {token}"},
        )

    @classmethod
    def from_settings(
        cls, settings: Settings, transport: httpx.BaseTransport | None = None
    ) -> "CanonicalClient":
        return cls(
            settings.erp_base_url,
            settings.erp_service_token_file,
            settings.erp_timeout_seconds,
            transport or TEST_TRANSPORT,
        )

    def close(self) -> None:
        self._http.close()

    def create_draft_purchase_order(self, key: uuid.UUID | str, body: bytes) -> SendResult:
        """POST the given bytes unchanged (FR-016), with Idempotency-Key = the proposal UUID. One
        attempt; HTTP errors are returned, not raised (research R-07). Headers are never logged."""
        try:
            response = self._http.post(
                "/purchase-orders",
                content=body,
                headers={"Content-Type": "application/json", "Idempotency-Key": str(key)},
            )
        except httpx.TimeoutException:
            return SendResult(error="timeout")
        except httpx.HTTPError:
            return SendResult(error="connection")
        try:
            parsed: Any = response.json()
        except ValueError:
            parsed = None
        return SendResult(status=response.status_code, body=parsed)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        operation = f"GET {path.split('?')[0]}"
        try:
            response = self._http.get(path, params=params)
        except httpx.TimeoutException:
            raise CanonicalUnavailable(operation, "timeout") from None
        except httpx.HTTPError as exc:
            raise CanonicalUnavailable(
                operation, f"transport error ({type(exc).__name__})"
            ) from None
        if response.status_code == 404:
            raise CanonicalNotFound(operation)
        if response.status_code != 200:
            raise CanonicalUnavailable(operation, f"HTTP {response.status_code}")
        return response.json()

    def sales_page(
        self,
        from_: date,
        to: date,
        updated_since: datetime | None,
        cursor: str | None,
        limit: int,
    ) -> SalesPage:
        params: dict[str, Any] = {"from": from_.isoformat(), "to": to.isoformat(), "limit": limit}
        if updated_since is not None:
            params["updated_since"] = updated_since.isoformat()
        if cursor is not None:
            params["cursor"] = cursor
        body = self._get("/sales", params)
        return SalesPage(
            items=[
                SalesRow(
                    product_id=r["product_id"],
                    business_date=date.fromisoformat(r["business_date"]),
                    units_sold=r["units_sold"],
                    units_returned=r["units_returned"],
                    net_units=r["net_units"],
                    day_status=r["day_status"],
                    updated_at=_instant(r["updated_at"]),
                )
                for r in body["items"]
            ],
            next_cursor=body["next_cursor"],
            high_watermark=_instant(body["high_watermark"]),
        )

    def product(self, product_id: str) -> Product:
        d = self._get(f"/products/{product_id}")
        return Product(
            d["product_id"],
            d["name"],
            d["preferred_supplier_id"],
            d["pack_multiple"],
            d["max_order_qty"],
        )

    def inventory(self, product_id: str) -> Inventory:
        d = self._get(f"/inventory/{product_id}")
        return Inventory(d["product_id"], d["on_hand"], d["available"])

    def supplier(self, supplier_id: str) -> Supplier:
        d = self._get(f"/suppliers/{supplier_id}")
        return Supplier(d["supplier_id"], d["name"], d["lead_time_days"])

    def open_purchase_order_list(self, product_id: str) -> list[OpenOrder]:
        """Every open order holding `product_id`, all pages: the same GET as
        open_purchase_orders, kept per order (feature 005, get_open_purchase_orders)."""
        orders: list[OpenOrder] = []
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {"status": "open", "product_id": product_id, "limit": 500}
            if cursor is not None:
                params["cursor"] = cursor
            body = self._get("/purchase-orders", params)
            for order in body["items"]:
                qty = sum(
                    line["open_qty"] for line in order["lines"] if line["product_id"] == product_id
                )
                if qty:
                    orders.append(
                        OpenOrder(
                            order["purchase_order_id"], order["supplier_id"], order["status"], qty
                        )
                    )
            cursor = body["next_cursor"]
            if cursor is None:
                return orders

    def open_purchase_orders(self, product_id: str) -> int:
        """Total open quantity of `product_id` across all open (draft) orders, all pages."""
        total = 0
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {"status": "open", "product_id": product_id, "limit": 500}
            if cursor is not None:
                params["cursor"] = cursor
            body = self._get("/purchase-orders", params)
            for order in body["items"]:
                total += sum(
                    line["open_qty"] for line in order["lines"] if line["product_id"] == product_id
                )
            cursor = body["next_cursor"]
            if cursor is None:
                return total
