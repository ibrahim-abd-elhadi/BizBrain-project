"""Signed keyset cursors (research R-08). Written before the implementation."""

import base64
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

from erp.canonical import cursor
from erp.canonical.cursor import InvalidCursor

SINCE = datetime(2026, 11, 17, 22, 0, 3, 512345, tzinfo=UTC)
SALES = {
    "f": date(2026, 8, 19),
    "t": date(2026, 11, 17),
    "u": SINCE,
    "w": datetime(2026, 11, 18, 10, 20, 0, 250001, tzinfo=UTC),
    "a": datetime(2026, 11, 17, 22, 0, 3, 999999, tzinfo=UTC),
    "p": "P1000",
    "d": date(2026, 11, 16),
}
EXPECT = {"f": "2026-08-19", "t": "2026-11-17", "u": SINCE}


@pytest.fixture(autouse=True)
def _key(temp_signing_key: Path) -> None:
    """Every test here signs with a throwaway key."""


def test_round_trip_for_sales_and_purchase_order_cursors() -> None:
    token = cursor.encode("sales", SALES)
    payload = cursor.decode("sales", token, EXPECT)
    assert payload["p"] == "P1000"
    assert payload["d"] == "2026-11-16"
    assert datetime.fromisoformat(payload["a"]) == SALES["a"]

    po = cursor.encode("po", {"product_id": "P003", "last": 41})
    assert cursor.decode("po", po, {"product_id": "P003"})["last"] == 41


def test_a_cursor_of_another_kind_is_refused() -> None:
    with pytest.raises(InvalidCursor):
        cursor.decode("po", cursor.encode("sales", SALES), {})


def test_any_changed_character_is_refused() -> None:
    token = cursor.encode("sales", SALES)
    for index in (0, len(token) // 3, token.index(".") + 1, len(token) - 1):
        swapped = "A" if token[index] != "A" else "B"
        tampered = token[:index] + swapped + token[index + 1 :]
        with pytest.raises(InvalidCursor):
            cursor.decode("sales", tampered, EXPECT)


@pytest.mark.parametrize(
    "garbage",
    ["no-dot-here", "!!!.???", base64.urlsafe_b64encode(b"not json").decode() + ".abc", ".", ""],
)
def test_malformed_cursors_are_refused(garbage: str) -> None:
    with pytest.raises(InvalidCursor):
        cursor.decode("sales", garbage, EXPECT)


@pytest.mark.parametrize(
    "changed",
    [
        {"f": "2026-08-20"},
        {"t": "2026-11-18"},
        {"u": datetime(2026, 11, 17, 22, 0, 4, tzinfo=UTC)},
        {"u": None},
    ],
)
def test_a_cursor_reused_with_other_filters_is_refused(changed: dict) -> None:
    token = cursor.encode("sales", SALES)
    with pytest.raises(InvalidCursor):
        cursor.decode("sales", token, {**EXPECT, **changed})


def test_a_po_cursor_reused_for_another_product_is_refused() -> None:
    token = cursor.encode("po", {"product_id": "P003", "last": 41})
    with pytest.raises(InvalidCursor):
        cursor.decode("po", token, {"product_id": "P004"})
    with pytest.raises(InvalidCursor):
        cursor.decode("po", token, {"product_id": None})


def test_the_same_instant_matches_whether_written_with_z_or_an_offset() -> None:
    token = cursor.encode(
        "sales", {**SALES, "u": datetime.fromisoformat("2026-11-17T22:00:03.512345Z")}
    )
    same = datetime.fromisoformat("2026-11-17T22:00:03.512345+00:00")
    cursor.decode("sales", token, {**EXPECT, "u": same})


def test_a_sales_cursor_fits_the_contract_limit() -> None:
    assert len(cursor.encode("sales", SALES)) <= 512  # defs.schema.json#/$defs/cursor


def test_another_signing_key_refuses_the_cursor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = cursor.encode("sales", SALES)
    other = tmp_path / "other.pem"
    other.write_bytes(
        Ed25519PrivateKey.generate().private_bytes(
            Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()
        )
    )
    from erp.config import get_settings
    from erp.security import _load_key

    monkeypatch.setenv("ERP_JWT_PRIVATE_KEY_FILE", str(other))
    get_settings.cache_clear()
    _load_key.cache_clear()
    cursor.reset_key_cache()
    with pytest.raises(InvalidCursor):
        cursor.decode("sales", token, EXPECT)
