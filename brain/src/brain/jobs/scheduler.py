"""The Africa/Cairo schedule (README 4.1, research R-04, P-5): polls at minute */5, the hourly
window at minute 7, the end-of-day run at 02:00. Missed polls and windows are not caught up; a
missed 02:00 run is run once when the worker starts."""

from datetime import datetime

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select
from sqlalchemy.orm import Session

from brain.clock import CAIRO, now_utc, today_cairo
from brain.config import Settings, get_settings
from brain.db import worker_session
from brain.jobs import registry
from brain.models import JobRun


def triggers(settings: Settings) -> dict[str, CronTrigger]:
    hour, minute = settings.end_of_day_hour_minute
    return {
        "sales-poll": CronTrigger(minute=f"*/{settings.poll_interval_minutes}", timezone=CAIRO),
        "hourly-window": CronTrigger(minute=settings.hourly_minute, timezone=CAIRO),
        "end-of-day": CronTrigger(hour=hour, minute=minute, timezone=CAIRO),
    }


def needs_catch_up(session: Session, now: datetime | None = None) -> bool:
    """True if it is past today's end-of-day time (Cairo) and no end-of-day run has succeeded
    for today yet."""
    now = now or now_utc()
    today = today_cairo(now)
    hour, minute = get_settings().end_of_day_hour_minute
    if now.astimezone(CAIRO) < datetime(today.year, today.month, today.day, hour, minute, tzinfo=CAIRO):
        return False
    done = session.scalar(
        select(JobRun.id).where(
            JobRun.job == "end-of-day",
            JobRun.status == "succeeded",
            JobRun.business_date == today,
        )
    )
    return done is None


def serve() -> int:
    settings = get_settings()
    scheduler = BlockingScheduler(
        timezone=CAIRO,
        job_defaults={"max_instances": 1, "coalesce": True, "misfire_grace_time": 60},
    )
    for name, trigger in triggers(settings).items():
        scheduler.add_job(registry.run_job, trigger, args=[name, "schedule"], id=name, name=name)
    with worker_session() as session:
        catch_up = needs_catch_up(session)
    print(
        f"brain-worker serving (Africa/Cairo): sales-poll */{settings.poll_interval_minutes}, "
        f"hourly-window :{settings.hourly_minute:02d}, end-of-day {settings.end_of_day_time}",
        flush=True,
    )
    if catch_up:
        registry.run_job("end-of-day", "catch-up")
    scheduler.start()
    return 0
