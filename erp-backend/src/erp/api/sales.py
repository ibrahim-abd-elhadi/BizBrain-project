import random
from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query, UploadFile
from sqlalchemy import select

from erp.api.deps import require_manager
from erp.clock import today_cairo
from erp.config import Settings, get_settings
from erp.db import SessionDep
from erp.errors import ErpError
from erp.ids import PRODUCT_ID_PATTERN
from erp.models import DailySales
from erp.schemas.sales import SalesList
from erp.schemas.simulate import SimulateRequest, SimulateResult
from erp.schemas.upload import UploadResult
from erp.services.csv_upload import MAX_BYTES, process_upload
from erp.services.day_close import close_past_days
from erp.services.simulate import run_simulation

router = APIRouter(prefix="/sales", tags=["sales"], dependencies=[Depends(require_manager)])


@router.get("", response_model=SalesList)
def list_sales(
    session: SessionDep,
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: date | None = None,
    product_id: Annotated[str | None, Query(pattern=PRODUCT_ID_PATTERN)] = None,
) -> SalesList:
    close_past_days(session)
    today = today_cairo()
    start = from_ if from_ is not None else today - timedelta(days=90)
    end = to if to is not None else today
    if start > end:
        raise ErpError(422, "VALIDATION_ERROR", "'from' must not be after 'to'")

    query = select(DailySales).where(
        DailySales.business_date >= start, DailySales.business_date <= end
    )
    if product_id is not None:
        query = query.where(DailySales.product_id == product_id)
    query = query.order_by(DailySales.business_date.desc(), DailySales.product_id)
    return SalesList(today=today, items=list(session.scalars(query)))


@router.post("/simulate", response_model=SimulateResult)
def simulate_sales(
    session: SessionDep,
    settings: Annotated[Settings, Depends(get_settings)],
    body: SimulateRequest | None = None,
) -> SimulateResult:
    """Adds a realistic batch to today's totals; the optional spike is described in R-16."""
    seed = settings.erp_random_seed
    rng = random.Random(seed) if seed is not None else random.Random()
    return run_simulation(session, settings, body.spike_product_id if body else None, rng)


@router.post("/upload", response_model=UploadResult)
def upload_sales(file: UploadFile, session: SessionDep) -> UploadResult:
    """Replaces today's totals from a CSV. Format: contracts/sales-upload-csv.md."""
    data = file.file.read(MAX_BYTES + 1)  # one byte more than allowed is enough to refuse it
    return process_upload(session, data)
