"""`brain-worker`: serve | run <job> | reset [--yes] | healthcheck | eval-assistant
(contracts/brain-worker-cli.md). There is no other way to start a job, and no screen button (D-38).
`eval-assistant` (feature 005) is not a job: it runs the evaluation set and writes a report.
"""

import argparse
import sys

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import text

from brain.config import get_settings
from brain.db import get_worker_engine, worker_session
from brain.jobs import locks, registry


def _reset(assume_yes: bool) -> int:
    if not assume_yes:
        answer = input("Type RESET to empty every Brain table: ")
        if answer.strip() != "RESET":
            print("reset cancelled")
            return 2
    from brain.models import Base

    with locks.hold(locks.LOCKS["all"]) as got:
        if not got:
            print("a job is running; reset refused")
            return 3
        tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
        with worker_session() as session:
            session.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
            session.commit()
    print(f"reset: emptied {len(Base.metadata.sorted_tables)} Brain tables")
    return 0


def _healthcheck() -> int:
    """Healthy when the worker database answers and the Brain's migrations are at head."""
    try:
        head = ScriptDirectory.from_config(
            Config(str(get_settings().alembic_ini))
        ).get_current_head()
        with get_worker_engine().connect() as connection:
            current = MigrationContext.configure(connection).get_current_revision()
    except Exception as exc:  # noqa: BLE001
        print(f"unhealthy: {type(exc).__name__}")
        return 1
    if current != head:
        print(f"unhealthy: migrations at {current}, head is {head}")
        return 1
    print("healthy")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="brain-worker", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("serve", help="run the Africa/Cairo scheduler")
    run = commands.add_parser("run", help="run one job now")
    run.add_argument("job", choices=sorted(registry.JOBS))
    reset = commands.add_parser("reset", help="empty every Brain table (development)")
    reset.add_argument("--yes", action="store_true", help="don't ask for confirmation")
    commands.add_parser(
        "healthcheck", help="exit 0 if the database answers and migrations are at head"
    )
    evaluate = commands.add_parser(
        "eval-assistant", help="run the assistant's evaluation set and write a dated report"
    )
    evaluate.add_argument("--out", default="./eval-reports", help="the report folder")
    evaluate.add_argument(
        "--only", default="", help="question IDs, comma separated (E01,A08), or en / ar"
    )
    evaluate.add_argument(
        "--merge", nargs="+", metavar="REPORT_JSON", help="combine partial reports into one"
    )
    args = parser.parse_args(argv)

    if args.command == "serve":
        from brain.jobs.scheduler import serve

        return serve()
    if args.command == "run":
        return registry.run_job(args.job, trigger="manual")
    if args.command == "reset":
        return _reset(args.yes)
    if args.command == "eval-assistant":
        return _evaluate(
            args.out, [q.strip() for q in args.only.split(",") if q.strip()], args.merge
        )
    return _healthcheck()


def _evaluate(out: str, only: list[str], merge: list[str] | None = None) -> int:
    from brain.assistant import evaluation

    try:
        return evaluation.main(out, only or None, merge)
    except Exception as exc:  # noqa: BLE001  (a report problem, not a job failure)
        print(f"eval-assistant failed: {type(exc).__name__}", flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
