"""RFC 8785 (JSON Canonicalization Scheme) for proposal arguments, and their fingerprint
(feature 004, research R-01; README 4.5 step 2).

Only the JSON that proposal arguments can hold is accepted: objects with string keys, arrays,
strings, and integers within +/-(2^53 - 1). Floats, booleans and null are refused, which removes
RFC 8785's number formatting instead of re-implementing it. For this subset the rules are:

- no whitespace;
- object members sorted by the UTF-16 code units of their names (section 3.2.3);
- strings escaped as section 3.2.2.2 says: the short forms for backspace, tab, newline, form
  feed, carriage return, quote and backslash; other control characters as lower-case \\u00xx;
  everything else, including "/", U+007F and non-ASCII, written as is. Python's json.dumps with
  ensure_ascii=False produces exactly this, once lone surrogates are refused;
- integers in plain decimal;
- UTF-8 output.

The test suite checks this encoder against the independent `rfc8785` library (SC-001).
"""

import hashlib
import json
from typing import Any

MAX_SAFE_INTEGER = 2**53 - 1


class NotCanonicalizable(ValueError):
    """A value outside the JSON subset proposal arguments may hold."""


def _string(value: str) -> str:
    if any(0xD800 <= ord(c) <= 0xDFFF for c in value):
        raise NotCanonicalizable("a string holds a lone surrogate")
    return json.dumps(value, ensure_ascii=False)


def _encode(value: Any) -> str:
    if isinstance(value, bool) or value is None:
        raise NotCanonicalizable(f"{value!r} is not allowed in proposal arguments")
    if isinstance(value, int):
        if not -MAX_SAFE_INTEGER <= value <= MAX_SAFE_INTEGER:
            raise NotCanonicalizable(f"{value} is outside the safe integer range")
        return str(value)
    if isinstance(value, str):
        return _string(value)
    if isinstance(value, list):
        return "[" + ",".join(_encode(item) for item in value) + "]"
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise NotCanonicalizable("object keys must be strings")
        keys = sorted(value, key=lambda k: k.encode("utf-16-be"))
        return "{" + ",".join(_string(k) + ":" + _encode(value[k]) for k in keys) + "}"
    raise NotCanonicalizable(f"{type(value).__name__} is not allowed in proposal arguments")


def canonical(value: Any) -> str:
    """The RFC 8785 canonical JSON text of `value`."""
    return _encode(value)


def canonical_bytes(value: Any) -> bytes:
    return _encode(value).encode("utf-8")


def fingerprint(value: Any) -> str:
    """`arguments_sha256`: SHA-256 of the canonical bytes, 64 lower-case hex characters."""
    return hashlib.sha256(canonical_bytes(value)).hexdigest()
