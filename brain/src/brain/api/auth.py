"""brain-api checks the manager's ERP login token itself (FR-030; research R-17).

The ERP's public key is loaded once at start-up; a missing file or one that isn't an Ed25519
public key stops the app with a message naming the file. A token is accepted only with a valid
EdDSA signature, iss = bizbrain-erp, aud = bizbrain, and exp, iat and sub present. The Brain's
service token (aud = bizbrain-canonical) fails the audience check. The private key never leaves
erp-backend.
"""

from pathlib import Path

import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key
from fastapi import Request

from brain.api.errors import BrainError

ALGORITHM = "EdDSA"
ISSUER = "bizbrain-erp"
AUDIENCE = "bizbrain"


class PublicKeyError(RuntimeError):
    pass


def load_public_key(path: Path) -> Ed25519PublicKey:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise PublicKeyError(f"cannot read the ERP public key {path}: {exc.strerror}") from None
    try:
        key = load_pem_public_key(data)
    except ValueError:
        raise PublicKeyError(f"{path} is not a PEM public key") from None
    if not isinstance(key, Ed25519PublicKey):
        raise PublicKeyError(f"{path} must hold an Ed25519 public key")
    return key


def _refuse() -> BrainError:
    return BrainError(401, "UNAUTHENTICATED", "Sign in required", {"WWW-Authenticate": "Bearer"})


def require_manager(request: Request) -> str:
    """FastAPI dependency: the signed-in manager's username, or 401 UNAUTHENTICATED."""
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise _refuse()
    try:
        claims = jwt.decode(
            token.strip(),
            request.app.state.public_key,
            algorithms=[ALGORITHM],
            audience=AUDIENCE,
            issuer=ISSUER,
            options={"require": ["exp", "iat", "sub", "iss", "aud"]},
        )
    except jwt.PyJWTError:
        raise _refuse() from None
    return str(claims["sub"])
