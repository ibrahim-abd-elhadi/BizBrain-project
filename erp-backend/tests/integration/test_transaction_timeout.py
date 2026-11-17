"""Request-serving connections carry transaction_timeout; the seed and Alembic don't (research R-07,
points 3 and 3a). The limit is what bounds commit - updated_at, so README's 120-second polling
overlap can never be outrun.

Written before the implementation.
"""

import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date

import pytest
from sqlalchemy import create_engine, pool, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from testcontainers.community.postgres import PostgresContainer

from erp.models import DailySales

TIMEOUT_SETTING = text("SELECT setting FROM pg_settings WHERE name = 'transaction_timeout'")


def _reset() -> None:
    from erp.config import get_settings
    from erp.db import reset_caches

    reset_caches()
    get_settings.cache_clear()


@contextmanager
def timeout_seconds(value: int) -> Iterator[None]:
    old = os.environ.get("ERP_DB_TRANSACTION_TIMEOUT_SECONDS")
    os.environ["ERP_DB_TRANSACTION_TIMEOUT_SECONDS"] = str(value)
    _reset()
    try:
        yield
    finally:
        if old is None:
            os.environ.pop("ERP_DB_TRANSACTION_TIMEOUT_SECONDS", None)
        else:
            os.environ["ERP_DB_TRANSACTION_TIMEOUT_SECONDS"] = old
        _reset()


def test_request_sessions_carry_the_60_second_limit(pg: PostgresContainer) -> None:
    from erp.db import get_sessionmaker

    with get_sessionmaker()() as session:
        assert session.scalar(TIMEOUT_SETTING) == "60000"  # milliseconds


def test_a_transaction_past_the_limit_never_commits(db: Session, catalog: None) -> None:
    from erp.db import get_sessionmaker

    with timeout_seconds(1):
        session = get_sessionmaker()()
        try:
            assert session.scalar(TIMEOUT_SETTING) == "1000"
            session.add(
                DailySales(
                    product_id="P001",
                    business_date=date(2026, 1, 1),
                    units_sold=5,
                    units_returned=0,
                    day_status="closed",
                )
            )
            session.flush()
            time.sleep(2)  # idle time inside the transaction counts
            with pytest.raises(OperationalError):
                session.commit()
        finally:
            session.close()

    db.expire_all()
    assert db.scalars(select(DailySales)).all() == []


def test_the_seed_session_has_no_limit(pg: PostgresContainer) -> None:
    from erp.db import get_unlimited_sessionmaker

    with get_unlimited_sessionmaker()() as session:
        assert session.scalar(TIMEOUT_SETTING) == "0"


def test_alembic_connections_have_no_limit(pg: PostgresContainer) -> None:
    from erp.config import get_settings

    # The way migrations/env.py connects: its own engine, no options.
    engine = create_engine(get_settings().erp_database_url, poolclass=pool.NullPool)
    try:
        with engine.connect() as connection:
            assert connection.scalar(TIMEOUT_SETTING) == "0"
    finally:
        engine.dispose()
