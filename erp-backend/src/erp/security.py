"""Password hashing (Argon2id) and the signed bearer tokens (EdDSA / Ed25519), research R-10, R-11.

Two tokens share the one signing key and are told apart by their audience (feature 002 R-02):
- the manager's login token, `aud = bizbrain`, for the ERP screens (`/api/v1/erp/*`);
- the Brain's service token, `aud = bizbrain-canonical`, for the Canonical API only.

The private key stays with erp-backend. brain-api will verify tokens with the public key only.
"""

import uuid
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

# The Brain's service token (feature 002, research R-02). Protocol constants, not settings.
CANONICAL_AUDIENCE = "bizbrain-canonical"
SERVICE_SUBJECT = "brain"
SCOPE_READ = "canonical:read"
SCOPE_CREATE_DRAFT = "canonical:po:create_draft"
SERVICE_SCOPES = (SCOPE_READ, SCOPE_CREATE_DRAFT)

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


def create_service_token(
    scopes: tuple[str, ...] | list[str] = SERVICE_SCOPES, days: int | None = None
) -> tuple[str, str, datetime]:
    """Signs a Brain service token. Returns the token, its jti and its expiry (research R-02)."""
    requested = set(scopes)
    if not requested or not requested <= set(SERVICE_SCOPES):
        raise ValueError(f"scopes must be a non-empty subset of {SERVICE_SCOPES}")
    lifetime = days if days is not None else get_settings().erp_service_token_ttl_days
    if lifetime <= 0:
        raise ValueError("days must be greater than 0")
    issued_at = now_utc().replace(microsecond=0)
    expires_at = issued_at + timedelta(days=lifetime)
    jti = str(uuid.uuid4())
    claims = {
        "iss": ISSUER,
        "aud": CANONICAL_AUDIENCE,
        "sub": SERVICE_SUBJECT,
        "scope": " ".join(scope for scope in SERVICE_SCOPES if scope in requested),
        "iat": issued_at,
        "exp": expires_at,
        "jti": jti,
    }
    return jwt.encode(claims, load_private_key(), algorithm=ALGORITHM), jti, expires_at


def decode_service_token(token: str) -> frozenset[str]:
    """Verify a Brain service token (signature, iss, aud, exp, sub); return its scopes."""
    try:
        claims = jwt.decode(
            token,
            public_key(),
            algorithms=[ALGORITHM],
            audience=CANONICAL_AUDIENCE,
            issuer=ISSUER,
            options={"require": ["exp", "iat", "sub", "iss", "aud", "jti", "scope"]},
        )
    except jwt.PyJWTError as exc:
        raise InvalidToken(str(exc)) from exc
    if claims["sub"] != SERVICE_SUBJECT or not isinstance(claims["scope"], str):
        raise InvalidToken("not a Brain service token")
    return frozenset(claims["scope"].split())
