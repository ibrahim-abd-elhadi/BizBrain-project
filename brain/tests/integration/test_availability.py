"""Whether the language model answers (research R-06, R-11). Written first (T010).

Only an "available" answer is cached; an offline one is checked again on the next call, so
"Check again" and the next send see a recovered model at once.
"""

import logging

from brain.assistant import availability
from brain.assistant.model import GeminiModel
from brain.config import get_settings

from fake_gemini import error


def _model() -> GeminiModel:
    return GeminiModel(get_settings())


def test_an_available_answer_is_cached_for_its_time(gemini_env, fake_clock) -> None:
    assert availability.probe(_model()) == (True, None)
    assert availability.probe(_model()) == (True, None)
    assert len(gemini_env.requests) == 1
    fake_clock.advance(31)
    assert availability.probe(_model()) == (True, None)
    assert len(gemini_env.requests) == 2


def test_an_offline_answer_is_not_cached(gemini_env, fake_clock) -> None:
    gemini_env.answer_probe(error(503, "UNAVAILABLE"))
    assert availability.probe(_model()) == (False, "server_error")
    # The fake recovered: "Check again" sees it at once, with no waiting.
    assert availability.probe(_model()) == (True, None)
    assert len(gemini_env.requests) == 2


def test_the_probe_uses_its_own_short_timeout(gemini_env, monkeypatch) -> None:
    seen = []
    monkeypatch.setattr(
        GeminiModel, "probe", lambda self, timeout_s: seen.append(timeout_s), raising=True
    )
    availability.probe(_model())
    assert seen == [get_settings().availability_probe_timeout_seconds]


def test_record_updates_the_state(gemini_env, fake_clock) -> None:
    availability.record(None)
    assert availability.probe(_model()) == (True, None)
    assert gemini_env.requests == []  # cached by the successful call
    availability.record("timeout")
    assert availability.probe(_model()) == (True, None)
    assert len(gemini_env.requests) == 1  # the failure cleared the cache


def test_why_skips_the_model_only_shortly_after_a_failure(fake_clock) -> None:
    assert availability.why_should_skip_model() is False
    availability.record("unreachable")
    assert availability.why_should_skip_model() is True
    fake_clock.advance(29)
    assert availability.why_should_skip_model() is True
    fake_clock.advance(2)
    assert availability.why_should_skip_model() is False
    availability.record("unreachable")
    availability.record(None)
    assert availability.why_should_skip_model() is False


def test_reasons_are_codes_only(gemini_env) -> None:
    gemini_env.answer_probe(error(429, "RESOURCE_EXHAUSTED"))
    available, reason = availability.probe(_model())
    assert (available, reason) == (False, "rate_limited")


def test_no_key_means_no_request(gemini_env, settings_override, tmp_path) -> None:
    settings_override(BRAIN_GEMINI_API_KEY_FILE=str(tmp_path / "absent"))
    assert availability.probe(_model()) == (False, "no_key")
    assert gemini_env.requests == []


def test_one_log_line_per_offline_change(caplog, fake_clock) -> None:
    caplog.set_level(logging.INFO, logger="brain.assistant")
    availability.record("rate_limited")
    availability.record("rate_limited")
    availability.record("timeout")
    availability.record(None)
    availability.record("timeout")
    lines = [r.getMessage() for r in caplog.records if r.name.startswith("brain.assistant")]
    offline = [line for line in lines if line.startswith("assistant offline")]
    assert offline == [
        "assistant offline: rate_limited",
        "assistant offline: timeout",
        "assistant offline: timeout",
    ]


def test_after_a_real_429_or_503_the_check_says_offline_for_30_seconds(
    gemini_env, fake_clock
) -> None:
    for reason in ("rate_limited", "server_error"):
        availability.reset()
        availability.record(reason)  # a real chat, Why? or briefing call failed
        assert availability.probe(_model()) == (False, reason)
        assert gemini_env.requests == []  # no probe: models.get would still say "available"
        fake_clock.advance(29)
        assert availability.probe(_model()) == (False, reason)
        fake_clock.advance(2)
        assert availability.probe(_model()) == (True, None)  # 30 s later: probed again
        gemini_env.requests.clear()


def test_check_again_re_probes_at_once(gemini_env, fake_clock) -> None:
    availability.record("rate_limited")
    assert availability.probe(_model(), recheck=True) == (True, None)
    assert len(gemini_env.requests) == 1
    assert availability.probe(_model()) == (True, None)  # the recheck cleared the memory


def test_other_failures_are_not_remembered(gemini_env, fake_clock) -> None:
    for reason in ("timeout", "unreachable", "key_refused", "model_not_found", "refused"):
        availability.reset()
        availability.record(reason)
        assert availability.probe(_model()) == (True, None), reason
