"""Database access. No engine exists at import time: it is built on first use, so tests can set the
environment before anything connects. Clear the caches (see reset_caches) after changing settings."""

from collections.abc import Iterator
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from erp.config import get_settings


@lru_cache
def get_engine() -> Engine:
    """The engine behind every HTTP request (the ERP screens and the Canonical API alike).

    Each connection carries PostgreSQL's transaction_timeout, so no request transaction can run
    longer than ERP_DB_TRANSACTION_TIMEOUT_SECONDS. That bounds commit_time - updated_at, which
    is what makes the Brain's 120-second polling overlap sufficient (research R-07, point 3).
    """
    settings = get_settings()
    options = f"-c transaction_timeout={settings.erp_db_transaction_timeout_seconds}s"
    return create_engine(
        settings.erp_database_url, pool_pre_ping=True, connect_args={"options": options}
    )


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


@lru_cache
def get_unlimited_engine() -> Engine:
    """For the seed command only: no transaction_timeout, so a large seed is never cut off
    halfway. Safe because a reseed requires resetting the Brain (research R-07, point 3a)."""
    return create_engine(get_settings().erp_database_url, pool_pre_ping=True)


@lru_cache
def get_unlimited_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_unlimited_engine(), expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """FastAPI dependency: commits on success, rolls back on error."""
    session = get_sessionmaker()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# scope="function": the commit runs right after the endpoint returns and BEFORE the response is
# sent. With the default scope it would run after the response, and a browser that refreshes a
# list straight after saving could read stale data.
SessionDep = Annotated[Session, Depends(get_session, scope="function")]


def reset_caches() -> None:
    """Drop the cached engines and sessionmakers (tests call this between settings changes)."""
    for engine in (get_engine, get_unlimited_engine):
        if engine.cache_info().currsize:
            engine().dispose()
    get_sessionmaker.cache_clear()
    get_unlimited_sessionmaker.cache_clear()
    get_engine.cache_clear()
    get_unlimited_engine.cache_clear()
