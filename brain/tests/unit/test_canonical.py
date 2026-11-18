"""RFC 8785 canonical JSON for proposal arguments, and the fingerprint (feature 004, research R-01;
SC-001). Written before the implementation."""

import hashlib
import random
import re

import pytest
import rfc8785

from brain.proposals.canonical import NotCanonicalizable, canonical, canonical_bytes, fingerprint

P003 = {"supplier_id": "S004", "lines": [{"product_id": "P003", "quantity": 108}]}
TWO_LINES = {
    "supplier_id": "S001",
    "lines": [{"product_id": "P001", "quantity": 60}, {"product_id": "P002", "quantity": 30}],
}


def test_rfc_8785_sorting_vector() -> None:
    """RFC 8785 section 3.2.3: members sorted by UTF-16 code units (the emoji's surrogates sort
    before U+FB33, unlike code-point order)."""
    value = {
        "€": "Euro Sign",
        "\r": "Carriage Return",
        "דּ": "Hebrew Letter Dalet With Dagesh",
        "1": "One",
        "\U0001f600": "Emoji: Grinning Face",
        "\u0080": "Control",
        "ö": "Latin Small Letter O With Diaeresis",
    }
    order = re.findall(r'"([^"]*)":', canonical(value).replace("\\r", "\r"))
    assert order == ["\r", "1", "\u0080", "ö", "€", "\U0001f600", "דּ"]


def test_rfc_8785_string_vector() -> None:
    """RFC 8785 section 3.2.2.2."""
    value = (
        chr(0x20AC)
        + "$"
        + chr(0x0F)
        + chr(0x0A)
        + "A'B"
        + chr(0x22)
        + chr(0x5C)
        + chr(0x5C)
        + chr(0x22)
        + "/"
    )
    assert canonical(value) == '"€$\\u000f\\nA\'B\\"\\\\\\\\\\"/"'


def test_our_vectors() -> None:
    assert (
        canonical(P003) == '{"lines":[{"product_id":"P003","quantity":108}],"supplier_id":"S004"}'
    )
    assert fingerprint(P003) == "986ec647450a68348bc4bbf8cda2efb7a593fc9cc2e56367f13452f989fff041"
    assert (
        fingerprint(TWO_LINES) == "4d26045c552bc3ce10d209ceb1f2a4d03b410166fd2a1bbe9b25c9aabb753629"
    )
    assert canonical_bytes(P003) == canonical(P003).encode("utf-8")
    assert fingerprint(P003) == hashlib.sha256(canonical_bytes(P003)).hexdigest()


@pytest.mark.parametrize(
    "value",
    [1.5, True, None, {"a": 2**53}, {"a": -(2**53)}, "\ud800", {1: "x"}, {"a": (1, 2)}],
    ids=["float", "bool", "null", "2^53", "-2^53", "lone surrogate", "int key", "tuple"],
)
def test_values_outside_the_subset_are_refused(value) -> None:
    with pytest.raises(NotCanonicalizable):
        canonical(value)


def test_the_largest_safe_integers_are_allowed() -> None:
    assert canonical([2**53 - 1, -(2**53 - 1), 0]) == "[9007199254740991,-9007199254740991,0]"


def _strings(rng: random.Random) -> str:
    alphabet = [
        "a",
        "Z",
        "0",
        " ",
        '"',
        "\\",
        "/",
        "\b",
        "\f",
        "\n",
        "\r",
        "\t",
        "\u0001",
        "\u001f",
        "\u007f",
        "\u0080",
        "é",
        "€",
        " ",
        "דּ",
        "\U0001f600",
        "\U0010ffff",
    ]
    return "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 12)))


def _arguments(rng: random.Random) -> dict:
    count = rng.randint(1, 50)
    products = rng.sample(range(1, 1000), count)
    value: dict = {
        "supplier_id": f"S{rng.randint(1, 999):03d}",
        "lines": [
            {"product_id": f"P{p:03d}", "quantity": rng.randint(1, 1_000_000)} for p in products
        ],
    }
    if rng.random() < 0.5:  # strings and keys beyond what IDs use, to exercise escaping and order
        value[_strings(rng)] = _strings(rng)
        value["nested"] = {_strings(rng): [_strings(rng), rng.randint(-(2**53 - 1), 2**53 - 1)]}
    return value


def test_matches_an_independent_implementation() -> None:
    """SC-001: our encoder and the rfc8785 library agree byte for byte."""
    for value in (P003, TWO_LINES, '€$\u000f\u000aA\'B"\\\\"/'):
        assert canonical_bytes(value) == rfc8785.dumps(value)
    rng = random.Random(8785)
    for _ in range(500):
        value = _arguments(rng)
        assert canonical_bytes(value) == rfc8785.dumps(value)


def test_the_fingerprint_is_64_lower_case_hex() -> None:
    assert re.fullmatch(r"[0-9a-f]{64}", fingerprint(TWO_LINES))
