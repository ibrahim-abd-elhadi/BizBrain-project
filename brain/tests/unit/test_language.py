"""The reply language rule (research R-07, FR-003). Written first (T006)."""

from brain.assistant.language import detect, is_language


def test_english_and_arabic_questions() -> None:
    assert detect("Which products are at high risk?") == "en"
    assert detect("ما المنتجات ذات الخطر العالي؟") == "ar"


def test_a_message_without_letters_keeps_the_last_language() -> None:
    assert detect("P003?", previous="ar") == "ar"
    assert detect("P003?") == "en"
    assert detect("123 / 45", previous="ar") == "ar"


def test_ids_digits_and_punctuation_are_ignored() -> None:
    assert detect("P003 S004 108?! ما رأيك") == "ar"
    assert detect("كم بعنا من المنتج P003 last week") == "ar"  # more Arabic letters than Latin


def test_a_tie_keeps_the_previous_language() -> None:
    assert detect("ab تب", previous="ar") == "ar"
    assert detect("ab تب", previous="en") == "en"


def test_is_language_agrees_with_detect() -> None:
    assert is_language("لدى P003 تغطية 2.83 يوم", "ar")
    assert not is_language("P003 has 2.83 days", "ar")
    assert is_language("P003 has 2.83 days", "en")


NAMES = [
    "Oral rehydration salts sachets",
    "Azithromycin 250 mg tablets",
    "Amoxicillin 500 mg capsules",
    "Delta Health Trading",
]
BRIEFING_AR = (
    "صباح الخير: P017 Oral rehydration salts sachets تغطية 2.05، "
    "P011 Azithromycin 250 mg tablets تغطية 2.72، P003 Amoxicillin 500 mg capsules من "
    "Delta Health Trading."
)


def test_names_from_the_data_do_not_count() -> None:
    """An Arabic text that quotes English product names (they stay as the data writes them)."""
    assert detect(BRIEFING_AR) == "en"  # without the names known: Latin letters win
    assert is_language(BRIEFING_AR, "ar", ignore=NAMES)
    assert detect(BRIEFING_AR, ignore=NAMES) == "ar"
    assert not is_language(
        "Good morning: P003 Amoxicillin 500 mg capsules is high.", "ar", ignore=NAMES
    )


def test_a_question_quoting_a_product_name_follows_its_own_words() -> None:
    question = "كم بعنا من Amoxicillin 500 mg capsules الأسبوع الماضي؟"
    assert detect(question, ignore=NAMES) == "ar"
    assert detect("How many Amoxicillin 500 mg capsules did we sell?", ignore=NAMES) == "en"
