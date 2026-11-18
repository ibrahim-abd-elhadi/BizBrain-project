"""brain-api checks the manager's ERP login token itself (FR-030, SC-010; research R-17).
Written before the implementation."""

import functools
from pathlib import Path

import pytest

UNAUTHENTICATED = "UNAUTHENTICATED"


def _create_app(monkeypatch, key_file: Path):
    from conftest import reset_app_caches

    monkeypatch.setenv("BRAIN_ERP_JWT_PUBLIC_KEY_FILE", str(key_file))
    reset_app_caches()
    from brain.api.app import create_app

    return create_app()


def test_a_missing_public_key_stops_the_app(pg, tmp_path, monkeypatch) -> None:
    missing = tmp_path / "nope.pub.pem"
    with pytest.raises(Exception, match="nope.pub.pem"):
        _create_app(monkeypatch, missing)


def test_a_file_that_is_not_an_ed25519_public_key_stops_the_app(pg, tmp_path, monkeypatch) -> None:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    garbage = tmp_path / "garbage.pem"
    garbage.write_text("not a key\n", encoding="utf-8")
    with pytest.raises(Exception, match="garbage.pem"):
        _create_app(monkeypatch, garbage)

    other = tmp_path / "ec.pub.pem"
    other.write_bytes(
        ec.generate_private_key(ec.SECP256R1())
        .public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    )
    with pytest.raises(Exception, match="ec.pub.pem"):
        _create_app(monkeypatch, other)


def test_the_managers_login_token_is_accepted(api_client, manager) -> None:
    response = api_client.get("/api/v1/brain/risk", headers=manager)
    assert response.status_code == 200
    assert response.json()["synthetic"] is True


def _refused(api_client, headers: dict[str, str]) -> None:
    for path in ("/api/v1/brain/risk", "/api/v1/brain/forecasts", "/api/v1/brain/forecasts/P003"):
        response = api_client.get(path, headers=headers)
        assert response.status_code == 401, path
        body = response.json()
        assert body["code"] == UNAUTHENTICATED and set(body) == {"detail", "code"}


def test_everything_else_is_refused(api_client, sign) -> None:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    _refused(api_client, {})
    _refused(api_client, {"Authorization": "Bearer not.a.token"})
    _refused(api_client, {"Authorization": f"Basic {sign()}"})
    _refused(api_client, {"Authorization": f"Bearer {sign(minutes=-5)}"})  # expired
    _refused(api_client, {"Authorization": f"Bearer {sign(key=Ed25519PrivateKey.generate())}"})
    _refused(api_client, {"Authorization": f"Bearer {sign(aud='bizbrain-canonical')}"})  # service
    _refused(api_client, {"Authorization": f"Bearer {sign(iss='someone-else')}"})


def test_brain_api_uses_only_the_api_login(api_client, manager, monkeypatch) -> None:
    from brain.db import get_api_engine

    # With the worker engine made unusable, brain-api still answers: it never uses that login.
    @functools.lru_cache  # shaped like the real cached factories, which teardown clears
    def refuse():
        raise AssertionError("brain-api touched the worker login")

    monkeypatch.setattr("brain.db.get_worker_engine", refuse)
    monkeypatch.setattr("brain.db.get_worker_sessionmaker", refuse)
    for path in ("/api/v1/brain/risk", "/api/v1/brain/forecasts"):
        assert api_client.get(path, headers=manager).status_code == 200
    assert get_api_engine().url.username == "brain_api_t"


def test_no_write_methods_and_no_docs(api_client, manager) -> None:
    response = api_client.post("/api/v1/brain/risk", headers=manager)
    assert response.status_code == 405 and response.json()["code"] == "METHOD_NOT_ALLOWED"
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert api_client.get(path).status_code == 404
