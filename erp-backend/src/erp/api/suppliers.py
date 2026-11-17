from fastapi import APIRouter, Depends
from sqlalchemy import select

from erp.api.deps import require_manager
from erp.db import SessionDep
from erp.errors import ErpError
from erp.models import Supplier
from erp.schemas.catalog import Supplier as SupplierOut
from erp.schemas.catalog import SupplierCreate, SupplierUpdate

# No DELETE: nothing in the ERP is ever deleted (FR-022).
router = APIRouter(prefix="/suppliers", tags=["suppliers"], dependencies=[Depends(require_manager)])


def _get(session: SessionDep, supplier_id: str) -> Supplier:
    supplier = session.get(Supplier, supplier_id)
    if supplier is None:
        raise ErpError(404, "NOT_FOUND", f"Supplier {supplier_id} not found")
    return supplier


@router.get("", response_model=list[SupplierOut])
def list_suppliers(session: SessionDep) -> list[Supplier]:
    return list(session.scalars(select(Supplier).order_by(Supplier.supplier_id)))


@router.post("", response_model=SupplierOut, status_code=201)
def create_supplier(body: SupplierCreate, session: SessionDep) -> Supplier:
    supplier = Supplier(name=body.name, lead_time_days=body.lead_time_days)
    session.add(supplier)
    session.flush()  # the database assigns supplier_id
    return supplier


@router.get("/{supplier_id}", response_model=SupplierOut)
def get_supplier(supplier_id: str, session: SessionDep) -> Supplier:
    return _get(session, supplier_id)


@router.patch("/{supplier_id}", response_model=SupplierOut)
def update_supplier(supplier_id: str, body: SupplierUpdate, session: SessionDep) -> Supplier:
    supplier = _get(session, supplier_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(supplier, field, value)
    session.flush()
    return supplier
