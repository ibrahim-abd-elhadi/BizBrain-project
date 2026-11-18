"""GET /api/v1/brain/forecasts and /forecasts/{product_id} (FR-029; contracts/brain-api.openapi.yaml).

"Current forecast" means the newest succeeded end-of-day run's. History is the last
BRAIN_FORECASTS_HISTORY_DAYS closed days up to that run's newest closed day, a closed day with no
sales row counting as 0 (the same rule as the forecasts, FR-013)."""

import re
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from brain.api.auth import require_manager
from brain.api.errors import BrainError
from brain.api.risk import anomaly_json
from brain.config import get_settings
from brain.db import SessionDep
from brain.models import Anomaly, Forecast, JobRun, ModelChoice, ModelHealth, ProductRef, SalesDaily

router = APIRouter(prefix="/api/v1/brain", dependencies=[Depends(require_manager)])


def _num(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


def _current_run(session: Session) -> JobRun | None:
    run_id = session.scalar(
        select(func.max(Forecast.job_run_id))
        .join(JobRun, JobRun.id == Forecast.job_run_id)
        .where(JobRun.status == "succeeded")
    )
    return session.get(JobRun, run_id) if run_id is not None else None


def _newest_closed_day(run: JobRun) -> date:
    cut = (run.summary or {}).get("final_cut")
    return date.fromisoformat(cut) if cut else run.business_date - timedelta(days=1)


@router.get("/forecasts")
def list_forecast_products(session: SessionDep) -> list[dict[str, Any]]:
    run = _current_run(session)
    if run is None:
        return []
    names = dict(session.execute(select(ProductRef.product_id, ProductRef.name)).all())
    degraded = dict(session.execute(select(ModelHealth.product_id, ModelHealth.degraded)).all())
    choices = session.scalars(
        select(ModelChoice).where(ModelChoice.job_run_id == run.id).order_by(ModelChoice.product_id)
    )
    return [
        {
            "product_id": c.product_id,
            "product_name": names.get(c.product_id, c.product_id),
            "chosen_model": c.chosen_model,
            "degraded": bool(degraded.get(c.product_id, False)),
        }
        for c in choices
    ]


@router.get("/forecasts/{product_id}")
def get_forecast(product_id: str, session: SessionDep) -> dict[str, Any]:
    settings = get_settings()
    if not re.fullmatch(settings.product_id_pattern, product_id):
        raise BrainError(
            422, "VALIDATION_ERROR", f"product_id: must match {settings.product_id_pattern}"
        )
    run = _current_run(session)
    choice = session.get(ModelChoice, (run.id, product_id)) if run is not None else None
    if run is None or choice is None:
        raise BrainError(404, "NOT_FOUND", f"No forecast for {product_id}")

    end = _newest_closed_day(run)
    first_sale = session.scalar(
        select(func.min(SalesDaily.business_date)).where(SalesDaily.product_id == product_id)
    )
    start = end - timedelta(days=settings.forecasts_history_days - 1)
    if first_sale is not None:
        start = max(start, first_sale)
    closed = dict(
        session.execute(
            select(SalesDaily.business_date, SalesDaily.net_units).where(
                SalesDaily.product_id == product_id,
                SalesDaily.day_status == "closed",
                SalesDaily.business_date.between(start, end),
            )
        ).all()
    )
    history = []
    day = start
    while day <= end:
        history.append({"business_date": day.isoformat(), "y_units": max(closed.get(day, 0), 0)})
        day += timedelta(days=1)

    forecast = [
        {
            "target_date": f.target_date.isoformat(),
            "yhat": float(f.yhat),
            "low": float(f.low),
            "high": float(f.high),
        }
        for f in session.scalars(
            select(Forecast)
            .where(Forecast.job_run_id == run.id, Forecast.product_id == product_id)
            .order_by(Forecast.target_date)
        )
    ]
    last_shown = max(run.business_date, end + timedelta(days=1))
    anomalies = [
        anomaly_json(a)
        for a in session.scalars(
            select(Anomaly)
            .where(
                Anomaly.product_id == product_id,
                Anomaly.business_date.between(start, last_shown),
            )
            .order_by(Anomaly.business_date, Anomaly.scope)
        )
    ]
    health = session.get(ModelHealth, product_id)
    ref = session.get(ProductRef, product_id)
    return {
        "synthetic": True,
        "product_id": product_id,
        "product_name": ref.name if ref else product_id,
        "run_date": run.business_date.isoformat(),
        "model": {
            "chosen_model": choice.chosen_model,
            "sn_backtest_wape": _num(choice.sn_backtest_wape),
            "lgbm_backtest_wape": _num(choice.lgbm_backtest_wape),
            "lgbm_eligible": choice.lgbm_eligible,
            "degraded": bool(health and health.degraded),
            "live_wape": _num(health.live_wape) if health else None,
        },
        "history": history,
        "forecast": forecast,
        "anomalies": anomalies,
    }
