"""The three jobs (README 4.1), their locks, and running one with bookkeeping (research R-05)."""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from brain.jobs import locks, runs

log = logging.getLogger("brain.jobs")


@dataclass(frozen=True)
class RunContext:
    run_id: int
    trigger: str


@dataclass(frozen=True)
class Job:
    lock: str  # "poll" or "intelligence"
    func: Callable[[RunContext], dict[str, Any]]


def _sales_poll(run: RunContext) -> dict[str, Any]:
    from brain.sales.poll import run_sales_poll

    return run_sales_poll(run)


def _hourly_window(run: RunContext) -> dict[str, Any]:
    from brain.pipeline.hourly_window import run_hourly_window

    return run_hourly_window(run)


def _end_of_day(run: RunContext) -> dict[str, Any]:
    from brain.pipeline.end_of_day import run_end_of_day

    return run_end_of_day(run)


JOBS: dict[str, Job] = {
    "sales-poll": Job("poll", _sales_poll),
    "hourly-window": Job("intelligence", _hourly_window),
    "end-of-day": Job("intelligence", _end_of_day),
}


def _safe(exc: BaseException) -> str:
    """A short failure description; Brain errors never carry the token (FR-001)."""
    text = str(exc) or type(exc).__name__
    return text[:300]


def run_job(name: str, trigger: str) -> int:
    """Runs one job now. Exit codes: 0 done, 1 failed, 3 already running."""
    job = JOBS[name]
    with locks.hold(locks.LOCKS[job.lock]) as got:
        if not got:
            if trigger == "manual":
                print(f"{name} is already running", flush=True)
            else:
                runs.skipped(name, trigger, "already running")
                print(
                    runs.line(name, trigger, "skipped", {"reason": "already-running"}, None),
                    flush=True,
                )
            return 3
        run_id = runs.start(name, trigger)
        started = time.perf_counter()
        try:
            summary = job.func(RunContext(run_id, trigger))
        except Exception as exc:  # noqa: BLE001  (recorded, then the next scheduled run tries again)
            log.error("%s failed: %s", name, _safe(exc))
            summary = {"error": _safe(exc)}
            runs.finish(run_id, "failed", summary)
            print(
                runs.line(name, trigger, "failed", summary, time.perf_counter() - started),
                flush=True,
            )
            return 1
        runs.finish(run_id, "succeeded", summary)
        print(
            runs.line(name, trigger, "succeeded", summary, time.perf_counter() - started),
            flush=True,
        )
        return 0
