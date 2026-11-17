"""Shared test setup for the Brain (feature 003, T007).

A throwaway PostgreSQL 18.7 with the real postgres/init scripts mounted, so the two Brain logins,
their grants and the ERP login are exactly what production gets. The Brain's migrations run as
the worker login. The ERP is never run: tests use tests/fakes.py.
"""

import os
import time
from collections.abc import Callable, Iterator
from datetime import datetime
from pathlib import Path

import psycopg
import pytest
import time_machine
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.orm import Session
from testcontainers.community.postgres import PostgresContainer

from brain.clock import CAIRO

BRAIN_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BRAIN_ROOT.parent
INIT_DIR = REPO_ROOT / "postgres" / "init"
POSTGRES_IMAGE = "postgres:18.7-alpine"

LOGINS = {
    "ERP_DB_USER": "erp_t",
    "ERP_DB_PASSWORD": "erp_pw",
    "BRAIN_DB_USER": "brain_worker_t",
    "BRAIN_DB_PASSWORD": "worker_pw",
    "BRAIN_API_DB_USER": "brain_api_t",
    "BRAIN_API_DB_PASSWORD": "api_pw",
}


def start_postgres(init_dir: Path = INIT_DIR, extra_volume: tuple[Path, str] | None = None):
    container = PostgresContainer(POSTGRES_IMAGE, driver="psycopg").with_volume_mapping(
        str(init_dir), "/docker-entrypoint-initdb.d", "ro"
    )
    if extra_volume is not None:
        container = container.with_volume_mapping(str(extra_volume[0]), extra_volume[1], "ro")
    for key, value in LOGINS.items():
        container = container.with_env(key, value)
    return container


def connect(
    server: PostgresContainer, user: str, password: str, dbname: str
) -> psycopg.Connection:
    """Connects, retrying while the server restarts after running the init scripts."""
    deadline = time.monotonic() + 60
    while True:
        try:
            return psycopg.connect(
                host=server.get_container_host_ip(),
                port=int(server.get_exposed_port(5432)),
                user=user,
                password=password,
                dbname=dbname,
                connect_timeout=5,
            )
        except psycopg.OperationalError as exc:
            if "password authentication failed" in str(exc) or "permission denied" in str(exc):
                raise
            if time.monotonic() > deadline:
                raise
            time.sleep(0.5)


def url_for(server: PostgresContainer, user: str, password: str, dbname: str = "brain_db") -> str:
    host = server.get_container_host_ip()
    port = server.get_exposed_port(5432)
    return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{dbname}"


def alembic_config() -> Config:
    return Config(str(BRAIN_ROOT / "alembic.ini"))


def reset_app_caches() -> None:
    from brain.config import get_settings
    from brain.db import reset_caches

    reset_caches()
    get_settings.cache_clear()


_state = {"started": False}


@pytest.fixture(scope="session")
def pg(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PostgresContainer]:
    with start_postgres() as container:
        # Wait until the init scripts have run and the server has restarted.
        connect(container, LOGINS["BRAIN_DB_USER"], LOGINS["BRAIN_DB_PASSWORD"], "brain_db").close()
        token_file = tmp_path_factory.mktemp("secrets") / "brain_service_token"
        token_file.write_text("test-service-token\n", encoding="utf-8")
        os.environ["BRAIN_DATABASE_URL"] = url_for(
            container, LOGINS["BRAIN_DB_USER"], LOGINS["BRAIN_DB_PASSWORD"]
        )
        os.environ["BRAIN_API_DATABASE_URL"] = url_for(
            container, LOGINS["BRAIN_API_DB_USER"], LOGINS["BRAIN_API_DB_PASSWORD"]
        )
        os.environ["BRAIN_API_DB_USER"] = LOGINS["BRAIN_API_DB_USER"]
        os.environ["BRAIN_ERP_SERVICE_TOKEN_FILE"] = str(token_file)
        os.environ["BRAIN_ERP_BASE_URL"] = "http://erp.test"
        os.environ["BRAIN_ALEMBIC_INI"] = str(BRAIN_ROOT / "alembic.ini")
        reset_app_caches()
        command.upgrade(alembic_config(), "head")
        _state["started"] = True
        try:
            yield container
        finally:
            _state["started"] = False
            reset_app_caches()


@pytest.fixture(autouse=True)
def _clean_brain_db() -> Iterator[None]:
    """After each test that used the database: empty every Brain table, as the worker."""
    yield
    if not _state["started"]:
        return
    from brain.db import worker_session
    from brain.models import Base

    tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    with worker_session() as session:
        session.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
        session.commit()


@pytest.fixture
def worker_session(pg: PostgresContainer) -> Iterator[Session]:
    from brain.db import get_worker_sessionmaker

    with get_worker_sessionmaker()() as session:
        yield session


@pytest.fixture
def api_session(pg: PostgresContainer) -> Iterator[Session]:
    from brain.db import get_api_sessionmaker

    with get_api_sessionmaker()() as session:
        yield session


@pytest.fixture
def at_cairo() -> Callable[[str], time_machine.travel]:
    """at_cairo("2026-11-18T10:00") -> a context manager freezing the clock at that Cairo time."""

    def _at(iso_local: str) -> time_machine.travel:
        moment = datetime.fromisoformat(iso_local).replace(tzinfo=CAIRO)
        return time_machine.travel(moment, tick=False)

    return _at


@pytest.fixture
def settings_override(monkeypatch: pytest.MonkeyPatch) -> Callable[..., None]:
    """settings_override(BRAIN_X="1", ...) sets env vars for this test and clears the caches."""

    def _set(**values: str) -> None:
        for key, value in values.items():
            monkeypatch.setenv(key, value)
        reset_app_caches()

    yield _set
    monkeypatch.undo()
    reset_app_caches()
