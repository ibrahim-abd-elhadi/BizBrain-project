"""GET /api/v1/brain/risk: the newest risk result per product, highest risk first (FR-029;
contracts/brain-api.openapi.yaml). Reads only tables the api login may read."""

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import distinct_on

from brain.api.auth import require_manager
from brain.db import SessionDep
from brain.models import Anomaly, JobRun, ProductRef, RiskResult

router = APIRouter(prefix="/api/v1/brain", dependencies=[Depends(require_manager)])

RISK_ORDER = {"high": 0, "medium": 1, "low": 2, None: 3}


def _num(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


def anomaly_json(a: Anomaly) -> dict[str, Any]:
    return {
        "kind": a.kind,
        "scope": a.scope,
        "business_date": a.business_date.isoformat(),
        "z": float(a.z),
        "raised_risk": a.raised_risk,
    }


def last_end_of_day(session) -> Any:
    return session.scalar(
        select(func.max(JobRun.finished_at)).where(
            JobRun.job == "end-of-day", JobRun.status == "succeeded"
        )
    )


@router.get("/risk")
def list_risk(session: SessionDep) -> dict[str, Any]:
    newest = list(
        session.scalars(
            select(RiskResult)
            .ext(distinct_on(RiskResult.product_id))
            .order_by(RiskResult.product_id, RiskResult.computed_at.desc(), RiskResult.id)
        )
    )
    names = dict(session.execute(select(ProductRef.product_id, ProductRef.name)).all())
    run_dates = dict(
        session.execute(
            select(JobRun.id, JobRun.business_date).where(
                JobRun.id.in_({r.forecast_run_id for r in newest})
            )
        ).all()
    )
    anomalies = {
        a.product_id: a
        for a in session.scalars(
            select(Anomaly)
            .ext(distinct_on(Anomaly.product_id))
            .order_by(Anomaly.product_id, Anomaly.business_date.desc(), Anomaly.found_at.desc())
        )
    }
    items = [
        {
            "product_id": r.product_id,
            "product_name": names.get(r.product_id, r.product_id),
            "risk": r.risk,
            "base_risk": r.base_risk,
            "raised_by_spike": r.raised_by_spike,
            "days_of_cover": _num(r.days_of_cover),
            "lead_time_days": r.lead_time_days,
            "available": r.available,
            "open_po_qty": r.open_po_qty,
            "order_qty": r.order_qty,
            "reason_code": r.reason_code,
            "inputs": {
                "forecast_over_lead": _num(r.forecast_over_lead),
                "review_period_days": r.review_period_days,
                "safety_stock": r.safety_stock,
                "sd_28": float(r.sd_28),
                "mean_28": float(r.mean_28),
                "target": r.target,
                "raw": r.raw,
                "pack_multiple": r.pack_multiple,
                "max_order_qty": r.max_order_qty,
                "forecast_run_date": run_dates[r.forecast_run_id].isoformat(),
            },
            "latest_anomaly": anomaly_json(anomalies[r.product_id])
            if r.product_id in anomalies
            else None,
            "computed_at": r.computed_at.isoformat(),
        }
        for r in newest
    ]
    items.sort(
        key=lambda i: (
            RISK_ORDER[i["risk"]],
            i["days_of_cover"] is None,
            i["days_of_cover"] or 0.0,
            i["product_id"],
        )
    )
    finished = last_end_of_day(session)
    return {
        "synthetic": True,
        "results_exist": bool(items),
        "last_end_of_day": finished.isoformat() if finished else None,
        "items": items,
    }
