"""The two assistant tables (data-model.md; migration 0003). Written first (T011)."""

import uuid

import psycopg
import pytest
from conftest import LOGINS, connect
from sqlalchemy import text


def _worker(pg):
    return connect(pg, LOGINS["BRAIN_DB_USER"], LOGINS["BRAIN_DB_PASSWORD"], "brain_db")


def _api(pg):
    return connect(pg, LOGINS["BRAIN_API_DB_USER"], LOGINS["BRAIN_API_DB_PASSWORD"], "brain_db")


def _run_id(conn) -> int:
    return conn.execute(
        "INSERT INTO job_run (job, trigger, status, started_at, business_date, summary) "
        "VALUES ('end-of-day', 'manual', 'succeeded', now(), current_date, '{}'::jsonb) "
        "RETURNING id"
    ).fetchone()[0]


def test_both_tables_belong_to_the_worker(pg) -> None:
    with _worker(pg) as conn:
        owners = dict(
            conn.execute(
                "SELECT tablename, tableowner FROM pg_tables "
                "WHERE tablename IN ('briefing', 'explanation')"
            ).fetchall()
        )
    assert owners == {"briefing": LOGINS["BRAIN_DB_USER"], "explanation": LOGINS["BRAIN_DB_USER"]}


@pytest.mark.parametrize(
    ("status", "en", "ar", "ok"),
    [
        ("written", "A briefing.", "موجز.", True),
        ("offline", None, None, True),
        ("not_grounded", None, None, True),
        ("written", None, None, False),
        ("offline", "text", "نص", False),
        ("written", "only English", None, False),
        ("written", "", "", False),
        ("written", "x" * 6001, "y", False),
        ("other", None, None, False),
    ],
)
def test_briefing_rules(pg, status, en, ar, ok) -> None:
    with _worker(pg) as conn:
        run = _run_id(conn)
        statement = (
            "INSERT INTO briefing (job_run_id, night, status, text_en, text_ar, facts, written_at) "
            "VALUES (%s, current_date, %s, %s, %s, '{}'::jsonb, now())"
        )
        if ok:
            conn.execute(statement, (run, status, en, ar))
        else:
            with pytest.raises(psycopg.errors.CheckViolation):
                conn.execute(statement, (run, status, en, ar))
        conn.rollback()


def test_one_briefing_per_run_and_facts_required(pg) -> None:
    with _worker(pg) as conn:
        run = _run_id(conn)
        insert = (
            "INSERT INTO briefing (job_run_id, night, status, facts, written_at) "
            "VALUES (%s, current_date, 'offline', %s, now())"
        )
        conn.execute(insert, (run, "{}"))
        with pytest.raises(psycopg.errors.UniqueViolation):
            conn.execute(insert, (run, "{}"))
        conn.rollback()
        run = _run_id(conn)
        with pytest.raises(psycopg.errors.NotNullViolation):
            conn.execute(insert, (run, None))
        conn.rollback()


def test_explanation_rules(pg) -> None:
    with _worker(pg) as conn:
        insert = (
            "INSERT INTO explanation (risk_result_id, language, text, written_at) "
            "VALUES (%s, %s, %s, now())"
        )
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            conn.execute(insert, (uuid.uuid4(), "en", "x"))
        conn.rollback()


def test_explanation_language_and_length(worker_session, first_night) -> None:
    rid = worker_session.scalar(text("SELECT id FROM risk_result LIMIT 1"))
    insert = text(
        "INSERT INTO explanation (risk_result_id, language, text, written_at) "
        "VALUES (:r, :l, :t, now())"
    )
    from sqlalchemy.exc import IntegrityError

    for language, value in (("fr", "x"), ("en", ""), ("en", "x" * 2001)):
        with pytest.raises(IntegrityError):
            worker_session.execute(insert, {"r": rid, "l": language, "t": value})
        worker_session.rollback()
    worker_session.execute(insert, {"r": rid, "l": "en", "t": "kept"})
    worker_session.execute(insert, {"r": rid, "l": "ar", "t": "محفوظ"})
    worker_session.flush()
    with pytest.raises(IntegrityError):
        worker_session.execute(insert, {"r": rid, "l": "en", "t": "again"})
    worker_session.rollback()


def test_the_api_login_reads_briefings_and_adds_explanations_only(pg, first_night) -> None:
    with _api(pg) as conn:
        conn.execute("SELECT count(*) FROM briefing")
        conn.execute("SELECT count(*) FROM explanation")
        rid = conn.execute("SELECT id FROM risk_result LIMIT 1").fetchone()[0]
        conn.execute(
            "INSERT INTO explanation (risk_result_id, language, text, written_at) "
            "VALUES (%s, 'en', 'kept text', now())",
            (rid,),
        )
        conn.commit()
    for statement in (
        (
            "INSERT INTO briefing (job_run_id, night, status, facts, written_at) "
            "VALUES (1, current_date, 'offline', '{}', now())"
        ),
        "UPDATE briefing SET status = 'offline'",
        "DELETE FROM briefing",
        "UPDATE explanation SET text = 'x'",
        "DELETE FROM explanation",
        "TRUNCATE explanation",
    ):
        with _api(pg) as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(statement)


def test_the_reset_empties_both_tables(first_night, capsys) -> None:
    from brain.db import worker_session as open_worker
    from brain.jobs.cli import main
    from brain.models import Base

    with open_worker() as session:
        rid = session.scalar(text("SELECT id FROM risk_result LIMIT 1"))
        session.execute(
            text(
                "INSERT INTO explanation (risk_result_id, language, text, written_at) "
                "VALUES (:r, 'en', 'kept', now())"
            ),
            {"r": rid},
        )
        session.commit()
    assert len(Base.metadata.sorted_tables) == 18
    assert main(["reset", "--yes"]) == 0
    assert "emptied 18 Brain tables" in capsys.readouterr().out
    with open_worker() as session:
        for table in ("briefing", "explanation"):
            assert session.scalar(text(f"SELECT count(*) FROM {table}")) == 0
