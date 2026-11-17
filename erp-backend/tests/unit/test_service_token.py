"""The Brain's service token and the command that issues it (research R-02, R-03).

Written before the implementation.
"""

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt
import pytest
import time_machine
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from erp import security
from erp.security import InvalidToken

NOW = datetime(2026, 11, 17, 10, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _key(temp_signing_key: Path) -> None:
    """Every test here signs with a throwaway key."""


def _claims(token: str) -> dict:
    return jwt.decode(token, options={"verify_signature": False})


def test_claims_of_a_default_token() -> None:
    with time_machine.travel(NOW, tick=False):
        token, jti, expires = security.create_service_token()
    claims = _claims(token)
    assert claims["iss"] == "bizbrain-erp"
    assert claims["aud"] == "bizbrain-canonical"
    assert claims["sub"] == "brain"
    assert claims["scope"] == "canonical:read canonical:po:create_draft"
    assert claims["iat"] == int(NOW.timestamp())
    assert claims["exp"] == int((NOW + timedelta(days=90)).timestamp())
    assert expires == NOW + timedelta(days=90)
    assert claims["jti"] == jti
    uuid.UUID(jti)
    assert security.create_service_token()[1] != jti


def test_days_and_scopes_narrow_a_token() -> None:
    with time_machine.travel(NOW, tick=False):
        token, _, expires = security.create_service_token(scopes=("canonical:read",), days=7)
    assert _claims(token)["scope"] == "canonical:read"
    assert expires == NOW + timedelta(days=7)
    for bad in ((), ("canonical:write",), ("canonical:read", "admin")):
        with pytest.raises(ValueError):
            security.create_service_token(scopes=bad)


def test_decode_returns_the_scopes() -> None:
    token, _, _ = security.create_service_token()
    assert security.decode_service_token(token) == frozenset(
        {"canonical:read", "canonical:po:create_draft"}
    )


def _signed(claims: dict, key=None) -> str:
    return jwt.encode(claims, key or security.load_private_key(), algorithm="EdDSA")


def _valid_claims() -> dict:
    now = datetime.now(UTC)
    return {
        "iss": "bizbrain-erp",
        "aud": "bizbrain-canonical",
        "sub": "brain",
        "scope": "canonical:read",
        "iat": now,
        "exp": now + timedelta(days=1),
        "jti": str(uuid.uuid4()),
    }


@pytest.mark.parametrize(
    "change",
    [
        {"aud": "bizbrain"},
        {"aud": "something-else"},
        {"sub": "manager"},
        {"iss": "someone"},
        {"scope": None},
        {"jti": None},
    ],
)
def test_decode_refuses_wrong_claims(change: dict) -> None:
    claims = {**_valid_claims(), **change}
    claims = {k: v for k, v in claims.items() if v is not None}
    with pytest.raises(InvalidToken):
        security.decode_service_token(_signed(claims))


def test_decode_refuses_expired_and_foreign_tokens() -> None:
    with time_machine.travel(NOW, tick=False):
        token, _, _ = security.create_service_token(days=1)
    with time_machine.travel(NOW + timedelta(days=2), tick=False), pytest.raises(InvalidToken):
        security.decode_service_token(token)

    with pytest.raises(InvalidToken):
        security.decode_service_token(_signed(_valid_claims(), Ed25519PrivateKey.generate()))
    with pytest.raises(InvalidToken):
        security.decode_service_token("not-a-token")


def test_the_manager_token_and_the_service_token_do_not_cross() -> None:
    manager_token, _ = security.create_access_token("manager")
    with pytest.raises(InvalidToken):
        security.decode_service_token(manager_token)
    service, _, _ = security.create_service_token()
    with pytest.raises(InvalidToken):
        security.decode_access_token(service)  # FR-009


def test_issue_command_prints_only_the_token_on_stdout(capsys: pytest.CaptureFixture) -> None:
    from erp.service_token import main

    assert main(["issue"]) == 0
    out, err = capsys.readouterr()
    token = out.strip()
    assert out == token + "\n"
    claims = _claims(token)
    assert f"jti={claims['jti']}" in err
    assert "expires=" in err and err.strip().endswith("Z")
    assert token not in err


def test_issue_command_options(capsys: pytest.CaptureFixture) -> None:
    from erp.service_token import main

    assert main(["issue", "--days", "7", "--scope", "canonical:read"]) == 0
    claims = _claims(capsys.readouterr().out.strip())
    assert claims["scope"] == "canonical:read"
    assert claims["exp"] - claims["iat"] == 7 * 86400

    with pytest.raises(SystemExit):
        main(["issue", "--scope", "canonical:everything"])
