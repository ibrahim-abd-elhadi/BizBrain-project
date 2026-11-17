"""Anomalies (README 4.3, 4.7; FR-019 to FR-021; research R-13).

z for a day = (net − mean) / sd over the 28 calendar days before it, all closed, a day with no
sales row counting as 0 (the same rule as the ERP's Simulate Sales spike); sample sd, sd = 0
counts as 1. A product needs 28 closed days since its first sales row before any check.

- The hourly window checks only spikes, on today's open total.
- The end-of-day run checks spikes and drops on every closed day not yet scanned.
- Only a spike on the day being checked raises risk; a drop never does.
"""

import statistics
from datetime import date, timedelta

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from brain.clock import now_utc
from brain.config import Settings
from brain.forecasting.series import Series
from brain.models import Anomaly, AnomalyScanProgress


def zscore(window: list[float], value: float) -> tuple[float, float, float]:
    mean = statistics.mean(window)
    sd = statistics.stdev(window) if len(window) > 1 else 0.0
    sd = sd or 1.0
    return (value - mean) / sd, mean, sd


def _record(
    session: Session,
    product_id: str,
    day: date,
    scope: str,
    kind: str,
    net: float,
    mean: float,
    sd: float,
    z: float,
    raised: bool,
    run_id: int,
) -> None:
    values = {
        "product_id": product_id,
        "business_date": day,
        "scope": scope,
        "kind": kind,
        "net_units": int(net),
        "mean_28": mean,
        "sd_28": sd,
        "z": z,
        "raised_risk": raised,
        "job_run_id": run_id,
        "found_at": now_utc(),
    }
    statement = insert(Anomaly).values(values)
    session.execute(
        statement.on_conflict_do_update(
            constraint="uq_anomaly_day_scope",
            set_={k: statement.excluded[k] for k in values if k not in ("product_id", "business_date", "scope")},
        )
    )


def scan_closed_days(
    session: Session, series: dict[str, Series], end: date, run_id: int, settings: Settings
) -> int:
    """Spike and drop checks on every closed day not yet scanned. Returns how many were found."""
    found = 0
    need = settings.anomaly_min_history_days
    threshold = settings.anomaly_z
    for product_id, s in series.items():
        progress = session.get(AnomalyScanProgress, product_id)
        first_index = need  # the first day with `need` closed days before it
        if progress is not None:
            first_index = max(first_index, s.index_of(progress.scanned_through) + 1)
        for i in range(first_index, len(s)):
            window = [float(v) for v in s.net[i - need : i]]
            z, mean, sd = zscore(window, float(s.net[i]))
            kind = "spike" if z >= threshold else "drop" if z <= -threshold else None
            if kind is None:
                continue
            day = s.date_at(i)
            raised = kind == "spike" and day == end
            _record(session, product_id, day, "closed", kind, s.net[i], mean, sd, z, raised, run_id)
            found += 1
        if progress is None:
            session.add(AnomalyScanProgress(product_id=product_id, scanned_through=end))
        else:
            progress.scanned_through = max(progress.scanned_through, end)
    session.flush()
    return found


def check_intraday_spike(
    session: Session,
    series: Series,
    today: date,
    today_net: float,
    run_id: int,
    settings: Settings,
) -> bool:
    """Spike check on today's open total against the 28 closed days before today. Records or
    clears today's intraday anomaly; returns True if today is a spike."""
    need = settings.anomaly_min_history_days
    days_before = (today - series.start).days
    if days_before < need:
        return False
    window = []
    for back in range(need, 0, -1):
        day = today - timedelta(days=back)
        window.append(float(series.net[series.index_of(day)]) if day <= series.end else 0.0)
    z, mean, sd = zscore(window, today_net)
    if z >= settings.anomaly_z:
        _record(session, series.product_id, today, "intraday", "spike", today_net, mean, sd, z, True, run_id)
        return True
    session.query(Anomaly).filter(
        Anomaly.product_id == series.product_id,
        Anomaly.business_date == today,
        Anomaly.scope == "intraday",
    ).delete()
    return False
