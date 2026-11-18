"""The proposal tables' own rules (feature 004 data-model.md; FR-005, FR-023, FR-025a; SC-008),
checked by writing straight to the database as brain_api. Written before the migration."""

import json
import threading
import uuid
from datetime import UTC, datetime

import psycopg
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

SHA = "a" * 64
STAMP = datetime(2026, 11, 18, 9, 0, tzinfo=UTC)


def _new(session, products=("P001",), supplier="S001", status="awaiting_approval") -> uuid.UUID:
    pid = uuid.uuid4()
    lines = [{"product_id": p, "quantity": 10} for p in products]
    arguments = {"supplier_id": supplier, "lines": lines}
    session.execute(
        text(
            "INSERT INTO proposal (id, action, origin, supplier_id, arguments, arguments_canonical,"
            " arguments_sha256, status, created_at)"
            " VALUES (:id, 'create_purchase_order', 'assistant', :s, CAST(:a AS jsonb), :c, :h,"
            " :st, :t)"
        ),
        {
            "id": pid,
            "s": supplier,
            "a": json.dumps(arguments),
            "c": json.dumps(arguments),
            "h": SHA,
            "st": status,
            "t": STAMP,
        },
    )
    for n, p in enumerate(products, start=1):
        session.execute(
            text(
                "INSERT INTO proposal_line (proposal_id, product_id, line_no, quantity)"
                " VALUES (:id, :p, :n, 10)"
            ),
            {"id": pid, "p": p, "n": n},
        )
    session.commit()
    return pid


def _approve(session, pid) -> None:
    session.execute(
        text(
            "UPDATE proposal SET status = 'uncertain', approved_by = 'manager', approved_at = :t,"
            " request_body = '{}' WHERE id = :id"
        ),
        {"id": pid, "t": STAMP},
    )
    session.commit()


def _refused(session, sql: str, params: dict) -> None:
    with pytest.raises(DBAPIError):
        session.execute(text(sql), params)
        session.commit()
    session.rollback()


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("arguments", "CAST('{}' AS jsonb)"),
        ("arguments_canonical", "'{}'"),
        ("arguments_sha256", f"'{'b' * 64}'"),
        ("supplier_id", "'S002'"),
        ("origin", "'recommendation'"),
        ("created_at", "now()"),
        ("action", "'create_purchase_order'"),
    ],
)
def test_arguments_and_identity_never_change(api_session, column, value) -> None:
    pid = _new(api_session)
    if column == "action":  # the same value: a no-op update is allowed
        api_session.execute(
            text(f"UPDATE proposal SET {column} = {value} WHERE id = :id"), {"id": pid}
        )
        api_session.commit()
        return
    _refused(api_session, f"UPDATE proposal SET {column} = {value} WHERE id = :id", {"id": pid})


def test_the_approval_is_written_once(api_session) -> None:
    pid = _new(api_session)
    _approve(api_session, pid)
    for column, value in (
        ("approved_by", "'someone'"),
        ("approved_at", "now()"),
        ("request_body", "'changed'"),
    ):
        _refused(api_session, f"UPDATE proposal SET {column} = {value} WHERE id = :id", {"id": pid})


FINAL = {
    "draft_created": "purchase_order_id = 7, closed_at = now()",
    "failed": "failure_code = 'VALIDATION_ERROR', failure_reason = 'no', closed_at = now()",
    "rejected": "closed_at = now()",
}


def _move(session, pid, status: str) -> None:
    extra = FINAL.get(status, "")
    sql = f"UPDATE proposal SET status = :s{', ' + extra if extra else ''} WHERE id = :id"
    session.execute(text(sql), {"s": status, "id": pid})
    session.commit()


@pytest.mark.parametrize(
    ("start", "target"),
    [
        ("draft_created", "uncertain"),
        ("rejected", "awaiting_approval"),
        ("failed", "uncertain"),
        ("draft_created", "failed"),
        ("uncertain", "awaiting_approval"),
        ("uncertain", "rejected"),
    ],
)
def test_forbidden_status_changes(api_session, start, target) -> None:
    pid = _new(api_session)
    if start != "rejected":
        _approve(api_session, pid)
    if start != "uncertain":
        _move(api_session, pid, start)
    extra = FINAL.get(target, "")
    sql = f"UPDATE proposal SET status = :s{', ' + extra if extra else ''} WHERE id = :id"
    _refused(api_session, sql, {"s": target, "id": pid})


def test_allowed_status_changes(api_session) -> None:
    rejected = _new(api_session, ("P001",))
    _move(api_session, rejected, "rejected")
    created = _new(api_session, ("P002",))
    _approve(api_session, created)
    _move(api_session, created, "uncertain")  # another unclear attempt
    _move(api_session, created, "draft_created")
    failed = _new(api_session, ("P003",))
    _approve(api_session, failed)
    _move(api_session, failed, "failed")
    statuses = dict(api_session.execute(text("SELECT id, status FROM proposal")).all())
    assert statuses == {rejected: "rejected", created: "draft_created", failed: "failed"}


@pytest.mark.parametrize(
    "sql",
    [
        # draft_created without an order number
        "UPDATE proposal SET status = 'draft_created', closed_at = now() WHERE id = :id",
        # failed without a code
        "UPDATE proposal SET status = 'failed', closed_at = now() WHERE id = :id",
        # a final status without closed_at
        "UPDATE proposal SET status = 'draft_created', purchase_order_id = 9 WHERE id = :id",
        # half an approval
        "UPDATE proposal SET approved_by = 'manager' WHERE id = :id",
    ],
)
def test_checks(api_session, sql) -> None:
    pid = _new(api_session)
    if "approved_by" not in sql:
        _approve(api_session, pid)
    _refused(api_session, sql, {"id": pid})


def test_column_formats(api_session) -> None:
    _refused(
        api_session,
        "INSERT INTO proposal (id, action, origin, supplier_id, arguments, arguments_canonical,"
        " arguments_sha256, status, created_at) VALUES (:id, 'create_purchase_order', 'assistant',"
        " 'S001', '{}', '{}', 'ABC', 'awaiting_approval', now())",
        {"id": uuid.uuid4()},
    )
    pid = _new(api_session)
    for qty in (0, 1_000_001):
        _refused(
            api_session,
            "INSERT INTO proposal_line (proposal_id, product_id, line_no, quantity)"
            " VALUES (:id, 'P099', 2, :q)",
            {"id": pid, "q": qty},
        )


def test_one_live_proposal_per_product(api_session) -> None:
    first = _new(api_session, ("P001", "P002"))
    with pytest.raises(IntegrityError, match="proposal_live_product"):
        _new(api_session, ("P002",))
    api_session.rollback()
    assert (
        api_session.scalar(text("SELECT count(*) FROM proposal")) == 1
    )  # nothing of the second kept
    for final in ("rejected",):
        _move(api_session, first, final)
    assert api_session.scalar(text("SELECT count(*) FROM proposal_live_product")) == 0
    _new(api_session, ("P002",))  # free again


@pytest.mark.parametrize("final", ["failed", "draft_created"])
def test_the_lock_is_released_by_every_final_status(api_session, final) -> None:
    pid = _new(api_session, ("P005",))
    _approve(api_session, pid)
    _move(api_session, pid, final)
    assert api_session.scalar(text("SELECT count(*) FROM proposal_live_product")) == 0
    _new(api_session, ("P005",))


def test_concurrent_proposals_for_one_product(pg) -> None:
    from brain.db import get_api_sessionmaker

    results: list[str] = []
    barrier = threading.Barrier(2)

    def attempt() -> None:
        with get_api_sessionmaker()() as session:
            barrier.wait()
            try:
                _new(session, ("P007",))
                results.append("ok")
            except IntegrityError:
                results.append("refused")

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == ["ok", "refused"]


def test_attempts_are_finished_once(api_session) -> None:
    pid = _new(api_session)
    _approve(api_session, pid)
    api_session.execute(
        text(
            "INSERT INTO proposal_attempt (proposal_id, attempt_no, started_at) VALUES (:id, 1, now())"
        ),
        {"id": pid},
    )
    api_session.commit()
    finish = (
        "UPDATE proposal_attempt SET finished_at = now(), outcome = :o, http_status = 201"
        " WHERE proposal_id = :id"
    )
    api_session.execute(text(finish), {"id": pid, "o": "uncertain"})
    api_session.commit()
    _refused(api_session, finish, {"id": pid, "o": "draft_created"})
    _refused(
        api_session,
        "INSERT INTO proposal_attempt (proposal_id, attempt_no, started_at, outcome) VALUES (:id, 2, now(), 'failed')",
        {"id": pid},
    )


def test_lines_cannot_be_changed_or_deleted(api_session) -> None:
    pid = _new(api_session)
    for sql in (
        "UPDATE proposal_line SET quantity = 99 WHERE proposal_id = :id",
        "DELETE FROM proposal_line WHERE proposal_id = :id",
        "DELETE FROM proposal WHERE id = :id",
    ):
        with pytest.raises(DBAPIError) as caught:
            api_session.execute(text(sql), {"id": pid})
        assert isinstance(caught.value.orig, psycopg.errors.InsufficientPrivilege)
        api_session.rollback()
