"""Cross-process job locks: PostgreSQL session advisory locks (research R-05).

A scheduled job and a manual `brain-worker run` are different processes, so the locks live in
the database. They are released when the holding connection closes, so a crashed run never
blocks the next one.
"""

import time
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import text

from brain.db import get_worker_engine

POLL = 7_003_001
INTELLIGENCE = 7_003_002
LOCKS = {"poll": (POLL,), "intelligence": (INTELLIGENCE,), "all": (POLL, INTELLIGENCE)}


@contextmanager
def hold(keys: tuple[int, ...], wait_seconds: float = 0) -> Iterator[bool]:
    """Yields True with every key held, or False (holding none) if any is taken."""
    connection = get_worker_engine().connect()
    held: list[int] = []
    try:
        deadline = time.monotonic() + wait_seconds
        for key in keys:
            while True:
                got = connection.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": key})
                connection.commit()
                if got.scalar():
                    held.append(key)
                    break
                if time.monotonic() >= deadline:
                    break
                time.sleep(0.5)
            if key not in held:
                break
        yield len(held) == len(keys)
    finally:
        for key in held:
            connection.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": key})
        connection.commit()
        connection.close()
