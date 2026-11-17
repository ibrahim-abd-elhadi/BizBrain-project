"""Post-deployment evaluation and degradation (README 4.2, FR-017, research R-12, P-4).

Each night, last night's forecast for yesterday is compared with yesterday's closed total.
- The live-WAPE window is the newest streak of evaluated days served by the same model kind, up
  to 28 days; a model is judged only after 7 evaluated days. A switch of model kind starts a new
  window (and clears the degraded mark).
- Degraded when live WAPE > 1.5 × the backtest WAPE that started the window.
- "Replaced the next night": the run that marks a LightGBM degraded serves that product with
  seasonal-naive; on later nights the normal backtest decides again. No lockout.
"""

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from brain.config import Settings
from brain.forecasting.series import Series
from brain.models import Forecast, ForecastEvaluation, JobRun, ModelHealth


def evaluate_day(
    session: Session, series: dict[str, Series], day: date, previous_run_id: int | None
) -> list[ForecastEvaluation]:
    """Store forecast-vs-actual for `day` from the previous end-of-day run's forecasts."""
    if previous_run_id is None:
        return []
    out = []
    forecasts = session.scalars(
        select(Forecast).where(Forecast.job_run_id == previous_run_id, Forecast.target_date == day)
    )
    for f in forecasts:
        s = series.get(f.product_id)
        if s is None or day < s.start or day > s.end:
            continue
        actual = int(s.y[s.index_of(day)])
        row = session.get(ForecastEvaluation, (f.product_id, day))
        if row is None:
            row = ForecastEvaluation(product_id=f.product_id, business_date=day)
            session.add(row)
        row.job_run_id = previous_run_id
        row.model = f.model
        row.forecast = f.yhat
        row.actual = actual
        out.append(row)
    session.flush()
    return out


def update_health(
    session: Session,
    product_id: str,
    model: str,
    day: date,
    backtest_wape: float | None,
    settings: Settings,
) -> ModelHealth:
    health = session.get(ModelHealth, product_id)
    if health is None or health.model != model:
        if health is None:
            health = ModelHealth(product_id=product_id)
            session.add(health)
        health.model = model
        health.window_started = day
        health.backtest_wape = Decimal(str(backtest_wape)) if backtest_wape is not None else None
        health.degraded = False
        health.degraded_on = None
    first = max(health.window_started, day - timedelta(days=settings.live_wape_max_days - 1))
    rows = list(
        session.scalars(
            select(ForecastEvaluation).where(
                ForecastEvaluation.product_id == product_id,
                ForecastEvaluation.model == model,
                ForecastEvaluation.business_date >= first,
                ForecastEvaluation.business_date <= day,
            )
        )
    )
    health.evaluated_days = len(rows)
    health.live_wape = None
    if len(rows) >= settings.live_wape_min_days:
        total = sum(r.actual for r in rows)
        if total > 0:
            live = sum(abs(Decimal(r.actual) - r.forecast) for r in rows) / Decimal(total)
            health.live_wape = live
    was = health.degraded
    health.degraded = bool(
        health.live_wape is not None
        and health.backtest_wape is not None
        and health.live_wape > Decimal(str(settings.degradation_factor)) * health.backtest_wape
    )
    if health.degraded and not was:
        health.degraded_on = day
    if not health.degraded:
        health.degraded_on = None
    session.flush()
    return health


def replaced_tonight(healths: list[ModelHealth], day: date) -> set[str]:
    """Products whose LightGBM was marked degraded by tonight's evaluation of `day`."""
    return {
        h.product_id for h in healths if h.model == "lightgbm" and h.degraded and h.degraded_on == day
    }


def previous_end_of_day(session: Session, current_run_id: int) -> int | None:
    return session.scalar(
        select(JobRun.id)
        .where(JobRun.job == "end-of-day", JobRun.status == "succeeded", JobRun.id < current_run_id)
        .order_by(JobRun.id.desc())
        .limit(1)
    )
