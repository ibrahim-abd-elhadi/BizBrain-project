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
    return create_engine(get_settings().erp_database_url, pool_pre_ping=True)


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


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
    """Drop the cached engine and sessionmaker (tests call this between settings changes)."""
    if get_engine.cache_info().currsize:
        get_engine().dispose()
    get_sessionmaker.cache_clear()
    get_engine.cache_clear()
