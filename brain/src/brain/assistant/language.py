"""The reply language (research R-07, FR-003): the language each message is written in.

IDs (P003, S004), digits and punctuation are ignored, and so are names quoted from the data
(product and supplier names stay in English inside an Arabic text); more Arabic letters than Latin
ones means Arabic, more Latin means English. A message with no letters, or a tie, keeps the conversation's
last language, English at the start. frontend/src/brain/language.ts applies the same rule.
"""

import re
from collections.abc import Iterable
from typing import Literal

Language = Literal["en", "ar"]

_IDS = re.compile(r"(?<![A-Za-z0-9])[PS]\d{3,}(?!\d)")
_ARABIC = re.compile(r"[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]")
_ARABIC_NOT_LETTERS = re.compile(r"[٠-٩۰-۹،؛؟٪-٭]")
_LATIN = re.compile(r"[A-Za-z]")


def _without(text: str, ignore: Iterable[str]) -> str:
    for name in sorted({n for n in ignore if n and n.strip()}, key=len, reverse=True):
        text = re.sub(re.escape(name.strip()), " ", text, flags=re.IGNORECASE)
    return text


def _counts(text: str, ignore: Iterable[str] = ()) -> tuple[int, int]:
    text = _ARABIC_NOT_LETTERS.sub("", _IDS.sub(" ", _without(text, ignore)))
    return len(_ARABIC.findall(text)), len(_LATIN.findall(text))


def detect(text: str, previous: Language | None = None, ignore: Iterable[str] = ()) -> Language:
    arabic, latin = _counts(text, ignore)
    if arabic > latin:
        return "ar"
    if latin > arabic:
        return "en"
    return previous or "en"


def is_language(text: str, language: Language, ignore: Iterable[str] = ()) -> bool:
    """True when `text` reads as `language` (a text with no letters passes). `ignore`: names
    quoted from the data, which don't count for either language."""
    arabic, latin = _counts(text, ignore)
    if arabic == latin:
        return True
    return ("ar" if arabic > latin else "en") == language
