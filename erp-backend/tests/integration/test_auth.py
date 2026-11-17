import os
from datetime import UTC, datetime, timedelta

import jwt
import time_machine
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from fastapi.testclient import TestClient

LOGIN = "/api/v1/erp/auth/login"
ME = "/api/v1/erp/auth/me"


def sign_in(client: TestClient) -> dict:
    response = client.post(LOGIN, json={"username": "manager", "password": "correct-horse"})
    assert response.status_code == 200, response.text
    return response.json()


def test_good_sign_in_returns_a_token_with_the_expected_claims(
    client: TestClient, manager: str
) -> None:
    body = sign_in(client)
    claims = jwt.decode(body["access_token"], options={"verify_signature": False})
    assert claims["iss"] == "bizbrain-erp"
    assert claims["aud"] == "bizbrain"
    assert claims["sub"] == "manager"
    assert abs((claims["exp"] - claims["iat"]) - 480 * 60) <= 1
    assert body["token_type"] == "bearer"
    expires_at = datetime.fromisoformat(body["expires_at"])
    ahead = expires_at - datetime.now(UTC)
    assert timedelta(minutes=479) < ahead <= timedelta(minutes=480)


def test_bad_sign_in_gives_the_same_error_for_wrong_password_and_unknown_user(
    client: TestClient, manager: str
) -> None:
    wrong_password = client.post(LOGIN, json={"username": "manager", "password": "nope"})
    unknown_user = client.post(LOGIN, json={"username": "nobody", "password": "correct-horse"})
    for response in (wrong_password, unknown_user):
        assert response.status_code == 401
        assert response.json()["code"] == "INVALID_CREDENTIALS"
    assert wrong_password.json() == unknown_user.json()


def test_me_needs_a_valid_token(client: TestClient, manager: str) -> None:
    token = sign_in(client)["access_token"]
    assert client.get(ME, headers={"Authorization": f"Bearer {token}"}).json() == {
        "username": "manager"
    }

    header, payload, signature = token.split(".")
    other = "B" if signature[5] == "A" else "A"
    tampered = f"{header}.{payload}.{signature[:5]}{other}{signature[6:]}"

    for headers in (
        {},  # no token
        {"Authorization": f"Bearer {tampered}"},  # tampered
    ):
        response = client.get(ME, headers=headers)
        assert response.status_code == 401
        assert response.json()["code"] == "UNAUTHENTICATED"

    later = datetime.now(UTC) + timedelta(minutes=481)
    with time_machine.travel(later, tick=False):
        response = client.get(ME, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"


def test_token_verifies_with_only_the_public_key(client: TestClient, manager: str) -> None:
    token = sign_in(client)["access_token"]
    with open(os.environ["ERP_JWT_PRIVATE_KEY_FILE"], "rb") as handle:
        public_key = load_pem_private_key(handle.read(), password=None).public_key()
    claims = jwt.decode(
        token,
        public_key,
        algorithms=["EdDSA"],
        audience="bizbrain",
        issuer="bizbrain-erp",
    )
    assert claims["sub"] == "manager"
