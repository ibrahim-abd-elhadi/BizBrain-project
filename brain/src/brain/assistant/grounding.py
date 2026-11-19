"""The grounding guard (research R-04; contracts/assistant/assistant-tools.md; D-18, FR-015).

Pure code, no model and no I/O. `Allowed.from_facts` collects every number (by value), ISO date
and product or supplier ID in the data the Brain supplied; `check` finds every such token in a
generated text and reports the ones the data doesn't contain. Arabic-Indic and Eastern
Arabic-Indic digits, the Arabic decimal and thousands separators and the Arabic percent sign are
normalized first. Number words two to twenty (English and Arabic) count as numbers too: counting
is calculating. "One" and its Arabic forms are not checked; they read as articles.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

_DIGITS = {**{0x0660 + i: str(i) for i in range(10)}, **{0x06F0 + i: str(i) for i in range(10)}}
_DIGITS.update({0x066B: ".", 0x066C: "", 0x066A: "%"})

DATE = re.compile(r"(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)")
ID = re.compile(r"(?<![A-Za-z0-9])[PS]\d{3,}(?!\d)")
NUMBER = re.compile(r"\d+(?:\.\d+)?")
THOUSANDS = re.compile(r"(?<=\d),(?=\d{3}(?!\d))")
LATIN_WORD = re.compile(r"[A-Za-z]+")
ARABIC_WORD = re.compile(r"[ء-يـً-ْٰ]+")

EN_WORDS = {
    "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
}  # fmt: skip

# Arabic units after normalization (أ إ آ → ا, diacritics and tatweel removed).
AR_UNITS = {
    "احد": 1, "احدى": 1,
    "اثنان": 2, "اثنين": 2, "اثنتان": 2, "اثنتين": 2, "اثنا": 2, "اثني": 2, "اثنتا": 2,
    "ثلاثة": 3, "ثلاث": 3, "اربعة": 4, "اربع": 4, "خمسة": 5, "خمس": 5, "ستة": 6, "ست": 6,
    "سبعة": 7, "سبع": 7, "ثمانية": 8, "ثماني": 8, "ثمان": 8, "تسعة": 9, "تسع": 9,
}  # fmt: skip
AR_TEN = {"عشرة", "عشر"}
AR_TWENTY = {"عشرون", "عشرين"}
AR_PREFIXES = ("و",)


def normalize(text: str) -> str:
    """Arabic digits and separators to ASCII; thousands separators removed."""
    return THOUSANDS.sub("", text.translate(_DIGITS))


def _arabic_key(word: str) -> str:
    word = re.sub(r"[ً-ْٰـ]", "", word)
    return word.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")


def _value(token: str) -> Decimal | None:
    try:
        return abs(Decimal(token)).normalize()
    except InvalidOperation:
        return None


def _number_words(text: str) -> list[tuple[int, str, int]]:
    """(position, word as written, value) for every checked number word."""
    found: list[tuple[int, str, int]] = []
    for m in LATIN_WORD.finditer(text):
        value = EN_WORDS.get(m.group().lower())
        if value is not None:
            found.append((m.start(), m.group(), value))
    words = list(ARABIC_WORD.finditer(text))
    skip = False
    for i, m in enumerate(words):
        if skip:
            skip = False
            continue
        key = _arabic_key(m.group())
        if key not in AR_UNITS and key not in AR_TEN and key not in AR_TWENTY:
            for prefix in AR_PREFIXES:
                if key.startswith(prefix) and key[len(prefix) :] in (
                    *AR_UNITS,
                    *AR_TEN,
                    *AR_TWENTY,
                ):
                    key = key[len(prefix) :]
                    break
        if key in AR_UNITS:
            nxt = _arabic_key(words[i + 1].group()) if i + 1 < len(words) else ""
            if nxt in AR_TEN:  # "ثلاثة عشر" = 13
                found.append((m.start(), f"{m.group()} {words[i + 1].group()}", 10 + AR_UNITS[key]))
                skip = True
            elif AR_UNITS[key] >= 2:
                found.append((m.start(), m.group(), AR_UNITS[key]))
        elif key in AR_TEN:
            found.append((m.start(), m.group(), 10))
        elif key in AR_TWENTY:
            found.append((m.start(), m.group(), 20))
    return found


def _tokens(text: str) -> list[tuple[int, str, str, Any]]:
    """(position, kind, token, key) for every date, ID, number and number word in `text`."""
    text = normalize(text)
    out: list[tuple[int, str, str, Any]] = []
    masked = list(text)

    def mask(m: re.Match[str]) -> None:
        for i in range(m.start(), m.end()):
            masked[i] = " "

    for m in DATE.finditer(text):
        out.append((m.start(), "date", m.group(), m.group()))
        mask(m)
    rest = "".join(masked)
    for m in ID.finditer(rest):
        out.append((m.start(), "id", m.group(), m.group()))
        mask(m)
    rest = "".join(masked)
    for m in NUMBER.finditer(rest):
        value = _value(m.group())
        if value is not None:
            out.append((m.start(), "number", m.group(), value))
    for position, word, value in _number_words(text):
        out.append((position, "number", word, Decimal(value)))
    out.sort(key=lambda t: t[0])
    return out


@dataclass
class Allowed:
    numbers: set[Decimal] = field(default_factory=set)
    dates: set[str] = field(default_factory=set)
    ids: set[str] = field(default_factory=set)

    @classmethod
    def from_facts(cls, facts: Any, extra_texts: Iterable[str] = ()) -> "Allowed":
        allowed = cls()
        allowed._walk(facts)
        for extra in extra_texts:
            allowed._text(extra)
        return allowed

    def _text(self, value: str) -> None:
        for _, kind, _token, key in _tokens(value):
            {"date": self.dates, "id": self.ids, "number": self.numbers}[kind].add(key)

    def _walk(self, value: Any) -> None:
        if isinstance(value, bool) or value is None:
            return
        if isinstance(value, int | float | Decimal):
            parsed = _value(str(value))
            if parsed is not None:
                self.numbers.add(parsed)
        elif isinstance(value, datetime | date):
            self._text(value.isoformat())
        elif isinstance(value, str):
            self._text(value)
        elif isinstance(value, dict):
            for item in value.values():
                self._walk(item)
        elif isinstance(value, list | tuple | set):
            for item in value:
                self._walk(item)

    def allows(self, kind: str, key: Any) -> bool:
        return key in {"date": self.dates, "id": self.ids, "number": self.numbers}[kind]


@dataclass(frozen=True)
class Grounded:
    ok: bool
    unsupported: list[str]


def check(text: str, allowed: Allowed) -> Grounded:
    unsupported = [token for _, kind, token, key in _tokens(text) if not allowed.allows(kind, key)]
    return Grounded(ok=not unsupported, unsupported=unsupported)


def numbers_in(text: str) -> set[Decimal]:
    """Every number value written in `text` (digits and number words), IDs and dates excluded."""
    return {key for _, kind, _token, key in _tokens(text) if kind == "number"}


def ids_in(text: str) -> set[str]:
    """Every product or supplier ID written in `text`."""
    return {key for _, kind, _token, key in _tokens(text) if kind == "id"}
