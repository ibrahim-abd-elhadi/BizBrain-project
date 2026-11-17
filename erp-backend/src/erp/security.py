"""Password hashing (Argon2id) and the signed bearer token (EdDSA / Ed25519), research R-10, R-11.

The private key stays with erp-backend. brain-api will verify tokens with the public key only.
"""

from datetime import datetime, timedelta
from functools import lru_cache

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key

from erp.clock import now_utc
from erp.config import get_settings

ISSUER = "bizbrain-erp"
AUDIENCE = "bizbrain"
ALGORITHM = "EdDSA"

_hasher = PasswordHasher()


class InvalidToken(Exception):
    """The bearer token is missing, malformed, tampered with or expired."""


def hash_password(plain: str) -> str:
    return _hasher.hash(plain)


def verify_password(password_hash: str, plain: str) -> bool:
    try:
        return _hasher.verify(password_hash, plain)
    except (VerificationError, InvalidHashError):
        return False


@lru_cache
def _load_key(path: str) -> Ed25519PrivateKey:
    with open(path, "rb") as handle:
        key = load_pem_private_key(handle.read(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise TypeError(f"{path} must hold an Ed25519 private key")
    return key


def load_private_key() -> Ed25519PrivateKey:
    """The signing key. Raises at start-up if the file is missing or not Ed25519."""
    return _load_key(str(get_settings().erp_jwt_private_key_file))


def public_key() -> Ed25519PublicKey:
    return load_private_key().public_key()


def create_access_token(username: str) -> tuple[str, datetime]:
    issued_at = now_utc()
    expires_at = issued_at + timedelta(minutes=get_settings().erp_jwt_ttl_minutes)
    claims = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": username,
        "iat": issued_at,
        "exp": expires_at,
    }
    return jwt.encode(claims, load_private_key(), algorithm=ALGORITHM), expires_at


def decode_access_token(token: str) -> str:
    """Verify signature, iss, aud and exp with the public key; return the subject."""
    try:
        claims = jwt.decode(
            token,
            public_key(),
            algorithms=[ALGORITHM],
            audience=AUDIENCE,
            issuer=ISSUER,
            options={"require": ["exp", "iat", "sub", "iss", "aud"]},
        )
    except jwt.PyJWTError as exc:
        raise InvalidToken(str(exc)) from exc
    return str(claims["sub"])
