"""`python -m erp.seed [--reset]`: loads the synthetic dataset into erp_db in one transaction.

Seed steps run in order. Each later story registers its step in STEPS.
"""

import argparse
import sys
from collections.abc import Callable

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from erp.config import Settings, get_settings
from erp.db import get_sessionmaker
from erp.models import Base, ManagerAccount
from erp.seed.catalog import seed_catalog
from erp.seed.history import seed_history
from erp.seed.manager import SeedConfigError, seed_manager

SeedStep = Callable[[Session, Settings], None]

# Ordered seed steps: manager, catalog (products, suppliers, starting stock), 90 days of history.
STEPS: list[SeedStep] = [seed_manager, seed_catalog, seed_history]

# Standalone sequences are not restarted by TRUNCATE ... RESTART IDENTITY.
CODE_SEQUENCES = ("product_code_seq", "supplier_code_seq")


class SeedRefused(Exception):
    """Data already exists and --reset was not given."""


def reset_all(session: Session) -> None:
    tables = ", ".join(f'"{table.name}"' for table in Base.metadata.sorted_tables)
    session.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    for sequence in CODE_SEQUENCES:
        exists = session.scalar(
            text("SELECT 1 FROM pg_class WHERE relname = :name AND relkind = 'S'"),
            {"name": sequence},
        )
        if exists:
            session.execute(text(f"ALTER SEQUENCE {sequence} RESTART WITH 1"))


def run_seed(session: Session, settings: Settings, reset: bool = False) -> None:
    """Runs every step in the caller's transaction (the caller commits)."""
    if reset:
        reset_all(session)
    elif session.scalar(select(ManagerAccount.id)) is not None:
        raise SeedRefused("erp_db already holds data; run with --reset to wipe and reseed")
    for step in STEPS:
        step(session, settings)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m erp.seed", description=__doc__)
    parser.add_argument("--reset", action="store_true", help="wipe every table, then reseed")
    args = parser.parse_args(argv)

    settings = get_settings()
    session = get_sessionmaker()()
    try:
        run_seed(session, settings, reset=args.reset)
        session.commit()
    except (SeedRefused, SeedConfigError) as exc:
        session.rollback()
        print(f"seed refused: {exc}", file=sys.stderr)
        return 1
    finally:
        session.close()
    print("seeded erp_db (synthetic data)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
