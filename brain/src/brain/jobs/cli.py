"""`brain-worker`: serve | run <job> | reset [--yes] | healthcheck
(contracts/brain-worker-cli.md). There is no other way to start a job, and no screen button (D-38).
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
        head = ScriptDirectory.from_config(Config(str(get_settings().alembic_ini))).get_current_head()
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
    commands.add_parser("healthcheck", help="exit 0 if the database answers and migrations are at head")
    args = parser.parse_args(argv)

    if args.command == "serve":
        from brain.jobs.scheduler import serve

        return serve()
    if args.command == "run":
        return registry.run_job(args.job, trigger="manual")
    if args.command == "reset":
        return _reset(args.yes)
    return _healthcheck()


if __name__ == "__main__":
    sys.exit(main())
