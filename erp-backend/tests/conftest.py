"""Shared test setup. Tests run against a throwaway PostgreSQL (testcontainers), never erp_db."""

import os
from collections.abc import Callable, Iterator
from datetime import datetime
from pathlib import Path

import pytest
import time_machine
from alembic import command
from alembic.config import Config
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
)
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from testcontainers.community.postgres import PostgresContainer

from erp.clock import CAIRO

BACKEND_ROOT = Path(__file__).resolve().parents[1]
POSTGRES_IMAGE = "postgres:18.7-alpine"

_state = {"started": False}


def _reset_app_caches() -> None:
    from erp.config import get_settings
    from erp.db import reset_caches
    from erp.security import _load_key

    reset_caches()
    get_settings.cache_clear()
    _load_key.cache_clear()


@pytest.fixture(scope="session")
def pg(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PostgresContainer]:
    """A throwaway PostgreSQL with the schema migrated to head and a fresh signing key."""
    key_file = tmp_path_factory.mktemp("keys") / "erp_jwt_ed25519.pem"
    key_file.write_bytes(
        Ed25519PrivateKey.generate().private_bytes(
            Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()
        )
    )
    with PostgresContainer(POSTGRES_IMAGE, driver="psycopg") as container:
        os.environ["ERP_DATABASE_URL"] = container.get_connection_url()
        os.environ["ERP_JWT_PRIVATE_KEY_FILE"] = str(key_file)
        os.environ["ERP_MANAGER_USERNAME"] = "manager"
        os.environ["ERP_MANAGER_PASSWORD"] = "correct-horse"
        _reset_app_caches()
        command.upgrade(Config(str(BACKEND_ROOT / "alembic.ini")), "head")
        _state["started"] = True
        try:
            yield container
        finally:
            _state["started"] = False
            _reset_app_caches()


@pytest.fixture(autouse=True)
def _clean_database() -> Iterator[None]:
    """After each test that used the database: truncate every table, restart the code sequences."""
    yield
    if not _state["started"]:
        return
    from erp.db import get_sessionmaker
    from erp.seed.__main__ import reset_all

    with get_sessionmaker()() as session:
        reset_all(session)
        session.commit()


@pytest.fixture
def db(pg: PostgresContainer) -> Iterator[Session]:
    from erp.db import get_sessionmaker

    with get_sessionmaker()() as session:
        yield session


@pytest.fixture
def client(pg: PostgresContainer) -> Iterator[TestClient]:
    from erp.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def manager(db: Session) -> str:
    """Inserts the manager account (username `manager`, password `correct-horse`)."""
    from erp.models import ManagerAccount
    from erp.security import hash_password

    db.add(ManagerAccount(username="manager", password_hash=hash_password("correct-horse")))
    db.commit()
    return "manager"


@pytest.fixture
def auth_headers(client: TestClient, manager: str) -> dict[str, str]:
    response = client.post(
        "/api/v1/erp/auth/login", json={"username": manager, "password": "correct-horse"}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def at_cairo() -> Callable[[str], time_machine.travel]:
    """at_cairo("2026-11-17T23:50") -> a context manager that freezes the clock at that Cairo time."""

    def _at(iso_local: str) -> time_machine.travel:
        moment = datetime.fromisoformat(iso_local).replace(tzinfo=CAIRO)
        return time_machine.travel(moment, tick=False)

    return _at


@pytest.fixture
def login(client: TestClient) -> Callable[[], dict[str, str]]:
    """login() signs in as the seeded or inserted manager at the *current* (possibly frozen) time.

    Use it inside an `at_cairo` block: a token issued at real time would be rejected as issued in
    the future (or as expired) once the clock is frozen somewhere else.
    """

    def _login() -> dict[str, str]:
        response = client.post(
            "/api/v1/erp/auth/login", json={"username": "manager", "password": "correct-horse"}
        )
        assert response.status_code == 200, response.text
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    return _login


@pytest.fixture
def catalog(db: Session) -> None:
    """One supplier (S001) and two products (P001, P002), each with 100 in stock."""
    from erp.models import Product, Stock, Supplier

    supplier = Supplier(name="Nile Pharma", lead_time_days=3)
    db.add(supplier)
    db.flush()
    for name in ("Paracetamol 500 mg", "Ibuprofen 400 mg"):
        product = Product(
            name=name,
            preferred_supplier_id=supplier.supplier_id,
            pack_multiple=10,
            max_order_qty=400,
        )
        db.add(product)
        db.flush()
        db.add(Stock(product_id=product.product_id, on_hand=100))
    db.commit()


@pytest.fixture
def seed(db: Session) -> Callable[[], None]:
    """seed() runs the real seed steps (manager, catalog, history) at the current clock.

    The manager it creates is `manager` / `correct-horse` (from the test environment). Call it
    inside an `at_cairo` block.
    """

    def _run() -> None:
        from erp.config import get_settings
        from erp.seed.__main__ import run_seed

        run_seed(db, get_settings(), reset=True)
        db.commit()

    return _run
