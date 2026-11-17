"""Each database has its own login; PUBLIC has no CONNECT (README Section 1, research R-09).

Starts a throwaway PostgreSQL with the real postgres/init script mounted, so the script itself is
what is tested.
"""

import time
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from testcontainers.community.postgres import PostgresContainer

INIT_DIR = Path(__file__).resolve().parents[3] / "postgres" / "init"

ERP_USER, ERP_PASSWORD = "erp_t", "erp_pw"
BRAIN_USER, BRAIN_PASSWORD = "brain_t", "brain_pw"


@pytest.fixture(scope="module")
def server() -> Iterator[PostgresContainer]:
    container = (
        PostgresContainer("postgres:18.7-alpine", driver="psycopg")
        .with_volume_mapping(str(INIT_DIR), "/docker-entrypoint-initdb.d", "ro")
        .with_env("ERP_DB_USER", ERP_USER)
        .with_env("ERP_DB_PASSWORD", ERP_PASSWORD)
        .with_env("BRAIN_DB_USER", BRAIN_USER)
        .with_env("BRAIN_DB_PASSWORD", BRAIN_PASSWORD)
        # 02-brain-api-role.sh (feature 003) runs here too and needs its login.
        .with_env("BRAIN_API_DB_USER", "brain_api_t")
        .with_env("BRAIN_API_DB_PASSWORD", "brain_api_pw")
    )
    with container:
        yield container


def connect(server: PostgresContainer, user: str, password: str, dbname: str) -> psycopg.Connection:
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
            refused = "permission denied for database" in str(exc)
            if refused or time.monotonic() > deadline:
                raise
            time.sleep(1)


def test_erp_login_reaches_only_erp_db(server: PostgresContainer) -> None:
    with connect(server, ERP_USER, ERP_PASSWORD, "erp_db") as conn:
        assert conn.execute("select 1").fetchone() == (1,)


def test_erp_login_is_refused_on_brain_db(server: PostgresContainer) -> None:
    with connect(server, ERP_USER, ERP_PASSWORD, "erp_db"):
        pass  # make sure the server is up and the init script has run
    with pytest.raises(psycopg.OperationalError, match="permission denied for database"):
        connect(server, ERP_USER, ERP_PASSWORD, "brain_db")


def test_brain_login_reaches_only_brain_db(server: PostgresContainer) -> None:
    with connect(server, BRAIN_USER, BRAIN_PASSWORD, "brain_db") as conn:
        assert conn.execute("select 1").fetchone() == (1,)
    with pytest.raises(psycopg.OperationalError, match="permission denied for database"):
        connect(server, BRAIN_USER, BRAIN_PASSWORD, "erp_db")


def test_neither_login_is_a_superuser_and_public_cannot_connect(server: PostgresContainer) -> None:
    with connect(server, ERP_USER, ERP_PASSWORD, "erp_db") as conn:
        rows = conn.execute(
            "select rolname, rolsuper, rolcreatedb, rolcreaterole from pg_roles "
            "where rolname in (%s, %s) order by rolname",
            (ERP_USER, BRAIN_USER),
        ).fetchall()
        assert rows == [(BRAIN_USER, False, False, False), (ERP_USER, False, False, False)]
        for database in ("erp_db", "brain_db"):
            public_can_connect = conn.execute(
                "select has_database_privilege('public', %s, 'CONNECT')", (database,)
            ).fetchone()
            assert public_can_connect == (False,), database
