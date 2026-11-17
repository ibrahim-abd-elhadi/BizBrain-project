"""Job-run bookkeeping (FR-012): one `job_run` row and one stdout line per run.

This is the worker's own state (catch-up, "last computed" times), not an audit log or a status
endpoint (README Section 7). Summaries hold counts only, never a secret.
"""

from typing import Any

from brain.clock import now_utc, today_cairo
from brain.db import worker_session
from brain.models import JobRun


def start(job: str, trigger: str) -> int:
    with worker_session() as session:
        run = JobRun(
            job=job,
            trigger=trigger,
            business_date=today_cairo(),
            started_at=now_utc(),
            status="running",
            summary={},
        )
        session.add(run)
        session.commit()
        return run.id


def finish(run_id: int, status: str, summary: dict[str, Any]) -> None:
    with worker_session() as session:
        run = session.get(JobRun, run_id)
        assert run is not None
        run.status = status
        run.summary = summary
        run.finished_at = now_utc()
        session.commit()


def skipped(job: str, trigger: str, reason: str) -> None:
    with worker_session() as session:
        now = now_utc()
        session.add(
            JobRun(
                job=job,
                trigger=trigger,
                business_date=today_cairo(),
                started_at=now,
                finished_at=now,
                status="skipped",
                summary={"reason": reason},
            )
        )
        session.commit()


def line(job: str, trigger: str, status: str, summary: dict[str, Any], took: float | None) -> str:
    parts = [job, f"trigger={trigger}", f"status={status}"]
    parts += [f"{key}={value}" for key, value in summary.items()]
    if took is not None:
        parts.append(f"took={took:.1f}s")
    return " ".join(parts)
