"""Two least-privilege Brain logins, and no cross-database access (FR-002, FR-003, SC-010, D-45).

Written before the implementation.
"""

import re
import shutil
from pathlib import Path

import psycopg
import pytest
from alembic import command
from conftest import (
    INIT_DIR,
    LOGINS,
    alembic_config,
    connect,
    reset_app_caches,
    start_postgres,
    url_for,
)
from testcontainers.community.postgres import PostgresContainer

READ = {
    "risk_result",
    "forecast",
    "model_choice",
    "model_health",
    "anomaly",
    "product_ref",
    "sales_daily",
    "job_run",
}
HIDDEN = {"poll_state", "model_artifact", "forecast_evaluation", "anomaly_scan_progress"}
# Feature 004: brain_api writes only the proposal tables (research R-04).
WRITES = {
    "proposal": {"SELECT", "INSERT", "UPDATE"},
    "proposal_line": {"SELECT", "INSERT"},
    "proposal_live_product": {"SELECT", "INSERT", "DELETE"},
    "proposal_attempt": {"SELECT", "INSERT", "UPDATE"},
}
SELECTABLE = READ | set(WRITES)
SCRIPT = "/docker-entrypoint-initdb.d/02-brain-api-role.sh"


def _api(pg: PostgresContainer, password: str = LOGINS["BRAIN_API_DB_PASSWORD"]):
    return connect(pg, LOGINS["BRAIN_API_DB_USER"], password, "brain_db")


def _granted(pg: PostgresContainer) -> set[str]:
    with connect(pg, LOGINS["BRAIN_DB_USER"], LOGINS["BRAIN_DB_PASSWORD"], "brain_db") as conn:
        rows = conn.execute(
            "SELECT table_name FROM information_schema.role_table_grants "
            "WHERE grantee = %s AND privilege_type = 'SELECT'",
            (LOGINS["BRAIN_API_DB_USER"],),
        ).fetchall()
    return {r[0] for r in rows}


def _privileges(pg: PostgresContainer) -> dict[str, set[str]]:
    with connect(pg, LOGINS["BRAIN_DB_USER"], LOGINS["BRAIN_DB_PASSWORD"], "brain_db") as conn:
        rows = conn.execute(
            "SELECT table_name, privilege_type FROM information_schema.role_table_grants "
            "WHERE grantee = %s",
            (LOGINS["BRAIN_API_DB_USER"],),
        ).fetchall()
    out: dict[str, set[str]] = {}
    for table, privilege in rows:
        out.setdefault(table, set()).add(privilege)
    return out


def test_the_api_login_reads_exactly_the_eight_tables(pg: PostgresContainer) -> None:
    """Feature 003's eight read tables plus feature 004's four proposal tables; never the four
    worker-only tables."""
    for table in sorted(SELECTABLE):
        with _api(pg) as conn:
            conn.execute(f'SELECT count(*) FROM "{table}"')
    for table in sorted(HIDDEN):
        with _api(pg) as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(f'SELECT count(*) FROM "{table}"')
    assert _granted(pg) == SELECTABLE


def test_the_api_login_writes_only_the_proposal_tables(pg: PostgresContainer) -> None:
    expected = {table: {"SELECT"} for table in READ} | WRITES
    assert _privileges(pg) == expected


@pytest.mark.parametrize(
    "statement",
    [
        "DELETE FROM proposal",
        "DELETE FROM proposal_line",
        "DELETE FROM proposal_attempt",
        "UPDATE proposal_line SET quantity = 1",
        "TRUNCATE proposal",
        "TRUNCATE proposal_line",
        "TRUNCATE proposal_live_product",
        "TRUNCATE proposal_attempt",
        "DROP TRIGGER proposal_guard ON proposal",
        "ALTER TABLE proposal DISABLE TRIGGER proposal_guard",
        "INSERT INTO risk_result (id) VALUES (gen_random_uuid())",
    ],
)
def test_the_api_login_cannot_touch_the_proposal_rules(
    pg: PostgresContainer, statement: str
) -> None:
    with _api(pg) as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute(statement)


def test_migrations_create_twelve_then_four_tables(pg: PostgresContainer) -> None:
    """0001 creates only feature 003's twelve tables; 0002 adds the four proposal tables."""

    def tables() -> set[str]:
        with connect(pg, LOGINS["BRAIN_DB_USER"], LOGINS["BRAIN_DB_PASSWORD"], "brain_db") as conn:
            rows = conn.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename <> 'alembic_version'"
            ).fetchall()
        return {r[0] for r in rows}

    command.downgrade(alembic_config(), "0001")
    try:
        assert len(tables()) == 12 and not tables() & set(WRITES)
    finally:
        command.upgrade(alembic_config(), "head")
    assert tables() == SELECTABLE | HIDDEN
    assert _privileges(pg) == {table: {"SELECT"} for table in READ} | WRITES


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO poll_state (id, high_watermark, saved_at) VALUES (1, now(), now())",
        "UPDATE risk_result SET risk = 'low'",
        "DELETE FROM forecast",
        "TRUNCATE sales_daily",
        "CREATE TABLE sneaky (id int)",
    ],
)
def test_the_api_login_cannot_write(pg: PostgresContainer, statement: str) -> None:
    with _api(pg) as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute(statement)


def test_no_login_crosses_databases(pg: PostgresContainer) -> None:
    for user, password in (
        (LOGINS["BRAIN_DB_USER"], LOGINS["BRAIN_DB_PASSWORD"]),
        (LOGINS["BRAIN_API_DB_USER"], LOGINS["BRAIN_API_DB_PASSWORD"]),
    ):
        with pytest.raises(psycopg.OperationalError, match="permission denied"):
            connect(pg, user, password, "erp_db")
    with pytest.raises(psycopg.OperationalError, match="permission denied"):
        connect(pg, LOGINS["ERP_DB_USER"], LOGINS["ERP_DB_PASSWORD"], "brain_db")


def test_the_role_script_is_idempotent_and_syncs_the_password(pg: PostgresContainer) -> None:
    for _ in range(2):
        code, output = pg.exec(["sh", SCRIPT])
        assert code == 0, output
    assert _privileges(pg) == {table: {"SELECT"} for table in READ} | WRITES
    code, output = pg.exec(["sh", "-c", f"BRAIN_API_DB_PASSWORD=rotated_pw sh {SCRIPT}"])
    assert code == 0, output
    _api(pg, "rotated_pw").close()
    code, output = pg.exec(["sh", SCRIPT])  # back to the configured password
    assert code == 0, output
    _api(pg).close()


def test_grants_come_out_the_same_whichever_runs_first(tmp_path: Path, capsys) -> None:
    """Migrations before the role exists: a warning, then the script grants the same tables."""
    only_databases = tmp_path / "init"
    only_databases.mkdir()
    shutil.copy(INIT_DIR / "01-create-databases.sh", only_databases / "01-create-databases.sh")
    import os

    saved = {k: os.environ.get(k) for k in ("BRAIN_DATABASE_URL", "BRAIN_API_DB_USER")}
    with start_postgres(only_databases, extra_volume=(INIT_DIR, "/scripts")) as server:
        connect(server, LOGINS["BRAIN_DB_USER"], LOGINS["BRAIN_DB_PASSWORD"], "brain_db").close()
        os.environ["BRAIN_DATABASE_URL"] = url_for(
            server, LOGINS["BRAIN_DB_USER"], LOGINS["BRAIN_DB_PASSWORD"]
        )
        os.environ["BRAIN_API_DB_USER"] = LOGINS["BRAIN_API_DB_USER"]
        reset_app_caches()
        try:
            # Alembic's fileConfig replaces the root handlers, so read its stderr, not caplog.
            command.upgrade(alembic_config(), "head")
            assert "brain_api role missing" in capsys.readouterr().err
            code, output = server.exec(["sh", "/scripts/02-brain-api-role.sh"])
            assert code == 0, output
            assert _privileges(server) == {table: {"SELECT"} for table in READ} | WRITES
        finally:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            reset_app_caches()


def test_the_script_and_the_code_grant_the_same_list() -> None:
    from brain.grants import API_READ_TABLES

    script = (INIT_DIR / "02-brain-api-role.sh").read_text(encoding="utf-8")
    listed = re.search(r"ARRAY\[([^\]]*)\]", script)
    assert listed is not None
    names = set(re.findall(r"'([a-z_]+)'", listed.group(1)))
    assert names == set(API_READ_TABLES) == READ


def test_the_script_and_the_code_grant_the_same_writes() -> None:
    from brain.grants import API_WRITE_GRANTS

    script = (INIT_DIR / "02-brain-api-role.sh").read_text(encoding="utf-8")
    pairs = re.findall(r"\('(proposal[a-z_]*)', '([A-Z, ]+)'\)", script)
    from_script = {table: {p.strip() for p in privileges.split(",")} for table, privileges in pairs}
    from_code = {table: set(privileges) for table, privileges in API_WRITE_GRANTS.items()}
    assert from_script == from_code == WRITES
