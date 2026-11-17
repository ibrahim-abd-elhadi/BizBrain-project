"""The job framework: Cairo schedule, locks, job runs, reset, catch-up, healthcheck (FR-009 to
FR-012, research R-04, R-05). Written before the implementation."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import func, select, text

from brain.clock import CAIRO


def _next(trigger, after: datetime) -> datetime:
    return trigger.get_next_fire_time(None, after)


def test_the_three_triggers_fire_at_cairo_times(pg) -> None:
    from brain.config import get_settings
    from brain.jobs.scheduler import triggers

    t = triggers(get_settings())
    start = datetime(2026, 11, 17, 23, 58, tzinfo=CAIRO)
    assert _next(t["sales-poll"], start) == datetime(2026, 11, 18, 0, 0, tzinfo=CAIRO)
    assert _next(t["hourly-window"], start) == datetime(2026, 11, 18, 0, 7, tzinfo=CAIRO)
    assert _next(t["end-of-day"], start) == datetime(2026, 11, 18, 2, 0, tzinfo=CAIRO)
    # Across Egypt's daylight-saving changes (last Friday of April and of October 2026).
    for day in (datetime(2026, 4, 23, 23, 0, tzinfo=CAIRO), datetime(2026, 10, 29, 23, 0, tzinfo=CAIRO)):
        fire = _next(t["end-of-day"], day)
        assert fire.astimezone(CAIRO).hour == 2 and fire.astimezone(CAIRO).minute == 0
        polls = [_next(t["sales-poll"], day)]
        for _ in range(40):
            polls.append(_next(t["sales-poll"], polls[-1] + timedelta(seconds=1)))
        assert all(p.astimezone(CAIRO).minute % 5 == 0 for p in polls)


def _job_runs(session):
    from brain.models import JobRun

    return list(session.scalars(select(JobRun).order_by(JobRun.id)))


def test_a_held_lock_refuses_a_manual_run_and_skips_a_scheduled_one(
    pg, worker_session, capsys
) -> None:
    from brain.db import get_worker_engine
    from brain.jobs import registry
    from brain.jobs.cli import main
    from brain.jobs.locks import POLL

    with get_worker_engine().connect() as other:
        other.execute(text("SELECT pg_advisory_lock(:k)"), {"k": POLL})
        assert main(["run", "sales-poll"]) == 3
        assert "sales-poll is already running" in capsys.readouterr().out
        registry.run_job("sales-poll", trigger="schedule")
        other.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": POLL})
        other.commit()
    runs = _job_runs(worker_session)
    assert [(r.job, r.trigger, r.status) for r in runs] == [("sales-poll", "schedule", "skipped")]


def test_hourly_and_end_of_day_exclude_each_other(pg, capsys) -> None:
    from brain.db import get_worker_engine
    from brain.jobs.cli import main
    from brain.jobs.locks import INTELLIGENCE

    with get_worker_engine().connect() as other:
        other.execute(text("SELECT pg_advisory_lock(:k)"), {"k": INTELLIGENCE})
        assert main(["run", "hourly-window"]) == 3
        assert main(["run", "end-of-day"]) == 3
        assert main(["reset", "--yes"]) == 3
        other.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": INTELLIGENCE})
        other.commit()


def test_a_run_records_its_outcome(pg, worker_session, monkeypatch, capsys) -> None:
    from brain.jobs import registry

    monkeypatch.setitem(registry.JOBS, "sales-poll", registry.Job("poll", lambda run: {"rows": 3}))
    assert registry.run_job("sales-poll", trigger="manual") == 0
    out = capsys.readouterr().out
    assert "sales-poll trigger=manual status=succeeded rows=3" in out

    def boom(run):
        raise RuntimeError("bad thing")

    monkeypatch.setitem(registry.JOBS, "sales-poll", registry.Job("poll", boom))
    assert registry.run_job("sales-poll", trigger="manual") == 1
    runs = _job_runs(worker_session)
    assert [r.status for r in runs] == ["succeeded", "failed"]
    assert runs[0].summary == {"rows": 3} and runs[0].finished_at is not None


def test_unknown_jobs_are_refused(pg, capsys) -> None:
    from brain.jobs.cli import main

    with pytest.raises(SystemExit) as caught:
        main(["run", "train-everything"])
    assert caught.value.code == 2


def test_reset_asks_first_and_then_empties_every_table(pg, worker_session, monkeypatch) -> None:
    from brain.jobs.cli import main
    from brain.models import Base, PollState

    worker_session.add(PollState(id=1, high_watermark=datetime(2026, 1, 1, tzinfo=CAIRO),
                                 saved_at=datetime(2026, 1, 1, tzinfo=CAIRO)))
    worker_session.commit()
    monkeypatch.setattr("builtins.input", lambda prompt="": "no")
    assert main(["reset"]) == 2
    assert worker_session.scalar(select(func.count()).select_from(PollState)) == 1
    worker_session.rollback()  # end the read, or TRUNCATE would wait for this session
    monkeypatch.setattr("builtins.input", lambda prompt="": "RESET")
    assert main(["reset"]) == 0
    worker_session.expire_all()
    for table in Base.metadata.sorted_tables:
        assert worker_session.scalar(select(func.count()).select_from(table)) == 0, table.name
    assert main(["healthcheck"]) == 0  # migrations and grants are still there


def test_catch_up_runs_a_missed_end_of_day_once(pg, worker_session, at_cairo) -> None:
    from brain.jobs.scheduler import needs_catch_up
    from brain.models import JobRun

    with at_cairo("2026-11-18T09:00"):
        assert needs_catch_up(worker_session) is True
    with at_cairo("2026-11-18T01:30"):
        assert needs_catch_up(worker_session) is False
    with at_cairo("2026-11-18T09:00"):
        worker_session.add(
            JobRun(job="end-of-day", trigger="schedule", business_date=datetime(2026, 11, 18).date(),
                   started_at=datetime(2026, 11, 18, 2, 0, tzinfo=CAIRO),
                   finished_at=datetime(2026, 11, 18, 2, 1, tzinfo=CAIRO),
                   status="succeeded", summary={})
        )
        worker_session.commit()
        assert needs_catch_up(worker_session) is False


def test_healthcheck(pg, settings_override) -> None:
    from brain.jobs.cli import main

    assert main(["healthcheck"]) == 0
    settings_override(BRAIN_DATABASE_URL="postgresql+psycopg://nobody:x@127.0.0.1:1/brain_db?connect_timeout=2")
    assert main(["healthcheck"]) == 1
