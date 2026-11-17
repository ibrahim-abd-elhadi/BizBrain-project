"""The risk step shared by the end-of-day run and the hourly window (FR-027; research R-14)."""

from datetime import date
from typing import Any

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from brain import risk
from brain.canonical.client import CanonicalClient
from brain.config import Settings
from brain.forecasting.series import Series
from brain.models import Forecast, JobRun, RiskResult


def stored_forecasts(session: Session, run_id: int, today: date) -> dict[str, list[float]]:
    """The forecasts of one end-of-day run, from today on, as stored (4 decimals)."""
    out: dict[str, list[float]] = {}
    rows = session.execute(
        select(Forecast.product_id, Forecast.yhat)
        .where(Forecast.job_run_id == run_id, Forecast.target_date >= today)
        .order_by(Forecast.product_id, Forecast.target_date)
    )
    for product_id, yhat in rows:
        out.setdefault(product_id, []).append(float(yhat))
    return out


def last_forecast_run(session: Session) -> int | None:
    """The newest succeeded end-of-day run that wrote forecasts ("last night's forecast")."""
    return session.scalar(
        select(func.max(Forecast.job_run_id))
        .join(JobRun, JobRun.id == Forecast.job_run_id)
        .where(JobRun.status == "succeeded")
    )


def sd_mean_28(s: Series, settings: Settings) -> tuple[float, float, int]:
    window = s.y[-settings.safety_sd_window_days :]
    if len(window) == 0:
        return 0.0, 0.0, 0
    sd = float(np.std(window, ddof=1)) if len(window) > 1 else 0.0
    return sd, float(np.mean(window)), len(window)


def run_risk(
    session: Session,
    *,
    products: list[str],
    spikes: set[str],
    series: dict[str, Series],
    forecasts: dict[str, list[float]],
    run_id: int,
    forecast_run_id: int,
    settings: Settings,
) -> dict[str, Any]:
    computed = kept = no_forecast = 0
    reasons: dict[str, int] = {}
    try:
        client = CanonicalClient.from_settings(settings)
    except Exception as exc:  # noqa: BLE001  (no client: every previous result stays the newest)
        return {"risk_computed": 0, "risk_kept": len(products), "risk_error": str(exc)[:200]}
    with client:
        for product_id in sorted(products):
            forecast = forecasts.get(product_id)
            s = series.get(product_id)
            if not forecast or s is None:
                no_forecast += 1
                continue
            sd, mean, days = sd_mean_28(s, settings)
            outcome = risk.recommend(
                session,
                client,
                product_id=product_id,
                forecast=forecast,
                spike=product_id in spikes,
                sd_28=sd,
                mean_28=mean,
                window_days=days,
                run_id=run_id,
                forecast_run_id=forecast_run_id,
                settings=settings,
            )
            if outcome == "kept":
                kept += 1
            else:
                computed += 1
    session.flush()
    for code in session.scalars(
        select(RiskResult.reason_code).where(
            RiskResult.job_run_id == run_id, RiskResult.reason_code.is_not(None)
        )
    ):
        reasons[code] = reasons.get(code, 0) + 1
    summary: dict[str, Any] = {"risk_computed": computed, "risk_kept": kept, "no_forecast": no_forecast}
    summary.update({f"reason_{k}": v for k, v in sorted(reasons.items())})
    return summary
