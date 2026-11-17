"""The hourly intelligence window (README 4.1; FR-020, FR-021, FR-027; research R-14).

For products whose sales changed since the previous succeeded hourly window or end-of-day run read
the sales copy: the intraday spike check on today's open total (never drops), then risk and the
recommendation from last night's forecast with fresh stock and open purchase orders. A product
with no forecast yet is skipped. Other products keep their newest result untouched.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from brain import anomalies
from brain.clock import now_utc, today_cairo
from brain.config import get_settings
from brain.db import worker_session
from brain.forecasting.series import load_series
from brain.jobs.registry import RunContext
from brain.models import JobRun, SalesDaily
from brain.pipeline import risk_step


def _previous_read(session: Session, run_id: int) -> datetime | None:
    """When the previous succeeded intelligence run read the sales copy: its `sales_read_at`
    (the end-of-day run reads after its own poll), else its start."""
    run = session.scalars(
        select(JobRun)
        .where(
            JobRun.job.in_(("hourly-window", "end-of-day")),
            JobRun.status == "succeeded",
            JobRun.id != run_id,
        )
        .order_by(JobRun.started_at.desc(), JobRun.id.desc())
    ).first()
    if run is None:
        return None
    stamp = (run.summary or {}).get("sales_read_at")
    return datetime.fromisoformat(stamp) if stamp else run.started_at


def run_hourly_window(run: RunContext) -> dict[str, Any]:
    settings = get_settings()
    read_at = now_utc()
    today = today_cairo()
    with worker_session() as session:
        since = _previous_read(session, run.run_id)
        query = select(SalesDaily.product_id).distinct()
        if since is not None:
            query = query.where(SalesDaily.changed_at > since)
        changed = sorted(session.scalars(query))
        summary: dict[str, Any] = {"sales_read_at": read_at.isoformat(), "changed": len(changed)}
        if not changed:
            return {**summary, "risk_computed": 0, "risk_kept": 0, "no_forecast": 0, "spikes": 0}

        forecast_run = risk_step.last_forecast_run(session)
        if forecast_run is None:
            return {**summary, "risk_computed": 0, "risk_kept": 0, "no_forecast": len(changed), "spikes": 0}
        forecasts = risk_step.stored_forecasts(session, forecast_run, today)
        _, series = load_series(session, today)

        today_net = dict(
            session.execute(
                select(SalesDaily.product_id, SalesDaily.net_units).where(
                    SalesDaily.business_date == today, SalesDaily.product_id.in_(changed)
                )
            ).all()
        )
        spikes: set[str] = set()
        for product_id in changed:
            s = series.get(product_id)
            if s is None or product_id not in forecasts:
                continue
            if anomalies.check_intraday_spike(
                session, s, today, float(today_net.get(product_id, 0)), run.run_id, settings
            ):
                spikes.add(product_id)

        summary.update(
            risk_step.run_risk(
                session,
                products=changed,
                spikes=spikes,
                series=series,
                forecasts=forecasts,
                run_id=run.run_id,
                forecast_run_id=forecast_run,
                settings=settings,
            )
        )
        summary["spikes"] = len(spikes)
        session.commit()
    return summary
