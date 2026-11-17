"""Database access for the two Brain logins (research R-16). No engine exists at import time.

- the **worker** engine (BRAIN_DATABASE_URL) owns and writes the Brain's tables;
- the **api** engine (BRAIN_API_DATABASE_URL) can only read eight result tables.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from brain.config import get_settings


class MissingDatabaseUrl(RuntimeError):
    pass


def _engine(url: str | None, name: str) -> Engine:
    if not url:
        raise MissingDatabaseUrl(f"{name} is not set")
    return create_engine(url, pool_pre_ping=True)


@lru_cache
def get_worker_engine() -> Engine:
    return _engine(get_settings().database_url, "BRAIN_DATABASE_URL")


@lru_cache
def get_api_engine() -> Engine:
    return _engine(get_settings().api_database_url, "BRAIN_API_DATABASE_URL")


@lru_cache
def get_worker_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_worker_engine(), expire_on_commit=False)


@lru_cache
def get_api_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_api_engine(), expire_on_commit=False)


@contextmanager
def worker_session() -> Iterator[Session]:
    session = get_worker_sessionmaker()()
    try:
        yield session
    finally:
        session.close()


def get_api_session() -> Iterator[Session]:
    """FastAPI dependency for brain-api: read-only login, nothing to commit."""
    session = get_api_sessionmaker()()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


SessionDep = Annotated[Session, Depends(get_api_session, scope="function")]


def reset_caches() -> None:
    """Drop cached engines and sessionmakers (tests call this between settings changes)."""
    for engine in (get_worker_engine, get_api_engine):
        if engine.cache_info().currsize:
            engine().dispose()
    get_worker_sessionmaker.cache_clear()
    get_api_sessionmaker.cache_clear()
    get_worker_engine.cache_clear()
    get_api_engine.cache_clear()
