"""Opaque, signed keyset cursors (research R-08).

    cursor = base64url(compact sorted JSON payload) + "." + base64url(HMAC-SHA256)

The HMAC key is derived from the ERP's Ed25519 signing key, so there is no new secret. A cursor
that fails the signature, can't be decoded, is of another kind, or was issued for other filters
is refused with InvalidCursor (the routes answer 422 VALIDATION_ERROR naming `cursor`).
"""

import base64
import binascii
import hashlib
import hmac
import json
from datetime import UTC, date, datetime
from functools import lru_cache
from typing import Any

from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

from erp.security import load_private_key

_KIND = "k"


class InvalidCursor(Exception):
    """The cursor is tampered with, malformed, of another kind or reused with other filters."""


@lru_cache
def _hmac_key() -> bytes:
    raw = load_private_key().private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    return hashlib.sha256(b"bizbrain-cursor-v1" + raw).digest()


def reset_key_cache() -> None:
    _hmac_key.cache_clear()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _plain(value: Any) -> Any:
    """Instants as UTC ISO strings (microseconds kept), dates as ISO dates."""
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def _signature(body: bytes) -> bytes:
    return hmac.new(_hmac_key(), body, hashlib.sha256).digest()


def encode(kind: str, payload: dict[str, Any]) -> str:
    content = {key: _plain(value) for key, value in payload.items()}
    content[_KIND] = kind
    body = json.dumps(content, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"{_b64(body)}.{_b64(_signature(body))}"


def _same(expected: Any, actual: Any) -> bool:
    if isinstance(expected, datetime):
        if not isinstance(actual, str):
            return False
        try:
            return datetime.fromisoformat(actual) == expected
        except ValueError:
            return False
    return _plain(expected) == actual


def decode(kind: str, cursor: str, expect: dict[str, Any]) -> dict[str, Any]:
    """The payload, if the cursor is genuine, of this kind, and issued for these filters."""
    try:
        body_part, signature_part = cursor.split(".")
        body = _unb64(body_part)
        signature = _unb64(signature_part)
    except (ValueError, binascii.Error) as exc:
        raise InvalidCursor("malformed cursor") from exc
    if not body or not hmac.compare_digest(signature, _signature(body)):
        raise InvalidCursor("cursor signature does not match")
    try:
        payload = json.loads(body)
    except ValueError as exc:
        raise InvalidCursor("malformed cursor") from exc
    if not isinstance(payload, dict) or payload.get(_KIND) != kind:
        raise InvalidCursor("cursor of another kind")
    for key, value in expect.items():
        if key not in payload or not _same(value, payload[key]):
            raise InvalidCursor("cursor was issued for other filters")
    return payload
