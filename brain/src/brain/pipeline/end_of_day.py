"""The 02:00 end-of-day run (README 4.1-4.2; FR-013 to FR-021, FR-027; research R-06 to R-14).

Order: own sales poll → series → evaluate yesterday → backtest both models → choose per product →
final fit and 14-day forecasts with ranges → model artifact → anomaly scan → risk and the order
recommendation for every product (User Story 3). All results are written in one transaction, so
the screens never see half a night.
"""

from datetime import date
from decimal import Decimal
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from brain import anomalies
from brain.clock import now_utc, today_cairo
from brain.config import Settings, get_settings
from brain.db import worker_session
from brain.forecasting import (
    artifacts,
    backtest,
    evaluation,
    features,
    lightgbm_model,
    ranges,
    seasonal_naive,
)
from brain.forecasting.series import Series, load_series
from brain.jobs import locks
from brain.jobs.registry import RunContext
from brain.models import Anomaly, Forecast, ModelChoice
from brain.pipeline import risk_step

FOUR = Decimal("0.0001")


def _dec(value: float | None) -> Decimal | None:
    return None if value is None else Decimal(str(round(float(value), 4))).quantize(FOUR)


def _own_poll(settings: Settings) -> dict[str, Any]:
    """The run starts with a sales poll, waiting up to 60 s for a running poll to finish."""
    from brain.canonical.client import CanonicalClient
    from brain.sales.poll import poll_sales

    with locks.hold(locks.LOCKS["poll"], wait_seconds=60) as got:
        if not got:
            return {"poll": "skipped"}
        try:
            with CanonicalClient.from_settings(settings) as client:
                result = poll_sales(client, settings)
        except Exception as exc:  # noqa: BLE001  (forecast from the copy the Brain already holds)
            return {"poll": f"failed: {exc}"[:200]}
        return {"poll_rows": result["rows"]}


def _sd_28(s: Series, settings: Settings) -> float:
    last = s.y[-settings.safety_sd_window_days :]
    return float(np.std(last, ddof=1)) if len(last) > 1 else 0.0


def forecast_night(
    session: Session,
    run_id: int,
    end: date,
    series: dict[str, Series],
    settings: Settings,
) -> dict[str, Any]:
    horizon = settings.forecast_horizon_days

    # 1. Post-deployment evaluation of yesterday, and degradation (README 4.2; P-4).
    previous = evaluation.previous_end_of_day(session, run_id)
    evaluated = evaluation.evaluate_day(session, series, end, previous)
    healths = []
    for row in evaluated:
        choice = session.get(ModelChoice, (previous, row.product_id))
        wape = None
        if choice is not None:
            wape = choice.lgbm_backtest_wape if row.model == "lightgbm" else choice.sn_backtest_wape
        healths.append(
            evaluation.update_health(
                session,
                row.product_id,
                row.model,
                end,
                float(wape) if wape is not None else None,
                settings,
            )
        )
    replaced = evaluation.replaced_tonight(healths, end)

    # 2. Backtest both models over the last 4 weeks (two 14-day origins).
    eligible = {p for p, s in series.items() if len(s) >= settings.lgbm_min_history_days}
    sn_bt = {p: backtest.seasonal_naive_backtest(s, end, settings) for p, s in series.items()}
    lgbm_actual: dict[str, list[float]] = {p: [] for p in eligible}
    lgbm_pred: dict[str, list[float]] = {p: [] for p in eligible}
    cuts = backtest.origins(end, settings.backtest_days, horizon)
    all_series = list(series.values())
    if eligible:
        for origin in cuts:
            X, y = features.rows_for_training(all_series, origin, horizon)
            if len(X) == 0:
                continue
            booster = lightgbm_model.train(X, y, settings)
            for p in sorted(eligible):
                s = series[p]
                days = backtest.targets(s, origin, end, horizon)
                if not days:
                    continue
                Xo, scale, _ = features.rows_for_origin(s, origin, horizon)
                pred = lightgbm_model.predict(booster, Xo, scale)
                for day in days:
                    lgbm_actual[p].append(float(s.y[s.index_of(day)]))
                    lgbm_pred[p].append(float(pred[(day - origin).days - 1]))

    # 3. Final fit on every closed day, then the 14-day forecasts with ranges.
    final_booster = None
    if eligible:
        X, y = features.rows_for_training(all_series, end, horizon)
        if len(X):
            final_booster = lightgbm_model.train(X, y, settings)
            artifacts.save(session, final_booster, run_id, end, lightgbm_model.params(settings))
            artifacts.prune(session, settings.artifact_keep_nights, today_cairo())

    chosen_lgbm = 0
    forecast_rows = 0
    for p in sorted(series):
        s = series[p]
        sn_actual, sn_pred = sn_bt[p]
        sn_wape = backtest.wape(sn_actual, sn_pred)
        lg_wape = None
        if p in eligible:
            lg_wape = backtest.wape(np.array(lgbm_actual[p]), np.array(lgbm_pred[p]))
        use_lgbm = (
            final_booster is not None
            and p in eligible
            and p not in replaced
            and sn_wape is not None
            and lg_wape is not None
            and lg_wape <= sn_wape - settings.lgbm_margin
        )
        if use_lgbm:
            Xo, scale, _ = features.rows_for_origin(s, end, horizon)
            yhat = lightgbm_model.predict(final_booster, Xo, scale)
            errors = np.array(lgbm_actual[p]) - np.array(lgbm_pred[p])
            model = "lightgbm"
            chosen_lgbm += 1
        else:
            yhat = seasonal_naive.forecast(s.y, horizon, settings.short_history_days)
            errors = sn_actual - sn_pred
            model = "seasonal_naive"
        low, high, q10, q90 = ranges.bounds(yhat, errors, _sd_28(s, settings), settings)
        session.add(
            ModelChoice(
                job_run_id=run_id,
                product_id=p,
                history_days=len(s),
                lgbm_eligible=p in eligible,
                lgbm_replaced=p in replaced,
                sn_backtest_wape=_dec(sn_wape),
                lgbm_backtest_wape=_dec(lg_wape),
                chosen_model=model,
                residual_q10=_dec(q10),
                residual_q90=_dec(q90),
            )
        )
        for h in range(horizon):
            session.add(
                Forecast(
                    job_run_id=run_id,
                    product_id=p,
                    target_date=s.date_at(len(s) + h),
                    model=model,
                    yhat=_dec(yhat[h]),
                    low=_dec(low[h]),
                    high=_dec(high[h]),
                )
            )
            forecast_rows += 1
    session.flush()

    # 4. Spike and drop checks on every closed day not yet scanned.
    found = anomalies.scan_closed_days(session, series, end, run_id, settings)

    # 5. Risk and the recommendation for every product with a forecast (User Story 3). A spike
    #    raises risk only if it is on the newest closed day, the day this run checks (FR-021).
    spikes = set(
        session.scalars(
            select(Anomaly.product_id).where(
                Anomaly.business_date == end, Anomaly.scope == "closed", Anomaly.kind == "spike"
            )
        )
    )
    today = today_cairo()
    risk_summary = risk_step.run_risk(
        session,
        products=sorted(series),
        spikes=spikes,
        series=series,
        forecasts=risk_step.stored_forecasts(session, run_id, today),
        run_id=run_id,
        forecast_run_id=run_id,
        settings=settings,
    )

    return {
        "products": len(series),
        "lgbm_eligible": len(eligible),
        "lgbm_chosen": chosen_lgbm,
        "lgbm_replaced": len(replaced),
        "forecast_rows": forecast_rows,
        "evaluated": len(evaluated),
        "degraded": sum(1 for h in healths if h.degraded),
        "anomalies_found": found,
        "backtest_cuts": [c.isoformat() for c in cuts],
        "final_cut": end.isoformat(),
        **risk_summary,
    }


def run_end_of_day(run: RunContext) -> dict[str, Any]:
    settings = get_settings()
    summary = _own_poll(settings)
    # The hourly window recomputes products whose sales changed after this moment (FR-027).
    summary["sales_read_at"] = now_utc().isoformat()
    today = today_cairo()
    with worker_session() as session:
        end, series = load_series(session, today)
        if end is None:
            return {**summary, "products": 0}
        summary.update(forecast_night(session, run.run_id, end, series, settings))
        session.commit()
    return summary
