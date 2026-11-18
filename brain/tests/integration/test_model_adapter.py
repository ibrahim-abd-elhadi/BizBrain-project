"""The Gemini adapter against the fake Gemini server (research R-01, R-05). Written first (T008).

The real google-genai SDK runs; only the server is fake. Every failure must come out as
ModelUnavailable(<reason>) or ModelUnusable, with one attempt only and no key in any message.
"""

import logging
import time

import pytest

from brain.assistant import model as llm
from brain.assistant.model import (
    GeminiModel,
    ModelUnavailable,
    ModelUnusable,
    ToolSpec,
    read_key,
)
from brain.config import get_settings

from fake_gemini import CANARY_KEY, empty, error, function_call, safety, slow, text

TOOLS = [
    ToolSpec(
        "get_risk_list",
        "The newest risk rows.",
        {"type": "object", "properties": {"risk": {"type": "string"}}},
    )
]
ASK = [{"role": "user", "text": "Which products are at high risk?"}]


def _generate(timeout_s: float = 5.0, **kw):
    return GeminiModel(get_settings()).generate(
        system="You are a test.", contents=ASK, tools=TOOLS, timeout_s=timeout_s, **kw
    )


def test_a_text_answer(gemini_env) -> None:
    gemini_env.answer(text("P003 is high."))
    turn = _generate()
    assert turn.text == "P003 is high." and turn.tool_calls == []
    body = gemini_env.generate_requests()[0]["body"]
    assert "You are a test." in str(body["systemInstruction"])
    assert body["generationConfig"]["temperature"] == 0
    names = [f["name"] for t in body["tools"] for f in t["functionDeclarations"]]
    assert names == ["get_risk_list"]
    assert gemini_env.generate_requests()[0]["path"].endswith(
        f"models/{get_settings().gemini_model}:generateContent"
    )


def test_a_function_call_and_its_raw_turn_go_back_unchanged(gemini_env) -> None:
    gemini_env.answer(function_call("get_risk_list", {"risk": "high"}), text("done"))
    turn = _generate()
    assert [(c.name, c.args) for c in turn.tool_calls] == [("get_risk_list", {"risk": "high"})]
    contents = [
        *ASK,
        {"role": "model_raw", "raw": turn.raw},
        {"role": "tool", "name": "get_risk_list", "response": {"items": []}},
    ]
    GeminiModel(get_settings()).generate(system="s", contents=contents, tools=TOOLS, timeout_s=5.0)
    sent = gemini_env.generate_requests()[1]["body"]["contents"]
    assert sent[1]["role"] == "model"
    assert sent[1]["parts"][0]["thoughtSignature"] == "c2lnbmF0dXJl"  # Gemini 3 needs it back
    assert sent[2]["parts"][0]["functionResponse"]["name"] == "get_risk_list"


@pytest.mark.parametrize(
    ("answer", "reason"),
    [
        (error(400, "INVALID_ARGUMENT", "API_KEY_INVALID"), "key_refused"),
        (error(401, "UNAUTHENTICATED"), "key_refused"),
        (error(403, "PERMISSION_DENIED"), "key_refused"),
        (error(404, "NOT_FOUND"), "model_not_found"),
        (error(429, "RESOURCE_EXHAUSTED"), "rate_limited"),
        (error(500, "INTERNAL"), "server_error"),
        (error(503, "UNAVAILABLE"), "server_error"),
        (error(400, "INVALID_ARGUMENT"), "refused"),
        (error(409, "ABORTED"), "refused"),
    ],
)
def test_errors_map_to_reasons(gemini_env, answer, reason) -> None:
    gemini_env.answer(answer)
    with pytest.raises(ModelUnavailable) as caught:
        _generate()
    assert caught.value.reason == reason
    assert "fake error" not in str(caught.value)  # Google's message never comes through


@pytest.mark.parametrize("answer", [error(429, "RESOURCE_EXHAUSTED"), error(500, "INTERNAL")])
def test_no_retry(gemini_env, answer) -> None:
    gemini_env.answer(answer, text("a retry would get this"))
    with pytest.raises(ModelUnavailable):
        _generate()
    assert len(gemini_env.generate_requests()) == 1


@pytest.mark.parametrize("answer", [empty(), safety()])
def test_an_empty_or_blocked_answer_is_unusable(gemini_env, answer) -> None:
    gemini_env.answer(answer)
    with pytest.raises(ModelUnusable):
        _generate()


def test_a_slow_answer_is_a_timeout(gemini_env) -> None:
    gemini_env.answer(slow(3))
    started = time.perf_counter()
    with pytest.raises(ModelUnavailable) as caught:
        _generate(timeout_s=1.0)
    assert caught.value.reason == "timeout"
    assert time.perf_counter() - started < 2.5


def test_a_refused_connection_is_unreachable(gemini_env, monkeypatch, settings_override) -> None:
    settings_override(BRAIN_GEMINI_BASE_URL=gemini_env.closed_port_url())
    with pytest.raises(ModelUnavailable) as caught:
        _generate()
    assert caught.value.reason == "unreachable"


def test_a_server_that_never_answers_times_out(gemini_env, settings_override) -> None:
    settings_override(BRAIN_GEMINI_BASE_URL=gemini_env.silent_url())
    started = time.perf_counter()
    with pytest.raises(ModelUnavailable) as caught:
        _generate(timeout_s=2.0)
    assert caught.value.reason == "timeout"
    assert time.perf_counter() - started < 3.0


def test_the_connect_and_call_timeouts_reach_the_client(gemini_env, monkeypatch) -> None:
    import httpx

    seen = []
    real = httpx.Client.build_request

    def spy(self, *args, **kwargs):
        seen.append(kwargs["timeout"])
        return real(self, *args, **kwargs)

    monkeypatch.setattr(httpx.Client, "build_request", spy)
    gemini_env.answer(text("ok"), text("ok"))
    _generate(timeout_s=6.0)
    _generate(timeout_s=6.0, connect_timeout_s=1.5)
    assert (seen[0].read, seen[0].connect) == (6.0, get_settings().gemini_connect_timeout_seconds)
    assert (seen[1].read, seen[1].connect) == (6.0, 1.5)


@pytest.mark.parametrize("kind", ["missing", "empty", "directory"])
def test_no_key_makes_no_request(gemini_env, settings_override, tmp_path, kind) -> None:
    path = tmp_path / "key"
    if kind == "empty":
        path.write_text("  \n", encoding="utf-8")
    elif kind == "directory":
        path.mkdir()
    settings_override(BRAIN_GEMINI_API_KEY_FILE=str(path))
    with pytest.raises(ModelUnavailable) as caught:
        _generate()
    assert caught.value.reason == "no_key"
    assert gemini_env.requests == []


def test_the_key_goes_only_into_the_api_key_header(gemini_env, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    gemini_env.answer(text("ok"), error(401, "UNAUTHENTICATED"))
    _generate()
    with pytest.raises(ModelUnavailable) as caught:
        _generate()
    request = gemini_env.generate_requests()[0]
    assert request["headers"]["x-goog-api-key"] == CANARY_KEY
    assert CANARY_KEY not in request["path"]
    assert CANARY_KEY not in str(request["body"])
    assert CANARY_KEY not in str(caught.value) and CANARY_KEY not in repr(caught.value)
    for record in caplog.records:
        assert CANARY_KEY not in record.getMessage()


def test_the_key_file_is_read_again_after_its_cache_time(
    gemini_key_file, fake_clock, settings_override
) -> None:
    settings_override(BRAIN_GEMINI_API_KEY_FILE=str(gemini_key_file))
    settings = get_settings()
    assert read_key(settings) == CANARY_KEY
    gemini_key_file.write_text("a-new-key", encoding="utf-8")
    fake_clock.advance(59)
    assert read_key(settings) == CANARY_KEY
    fake_clock.advance(2)
    assert read_key(settings) == "a-new-key"


def test_the_probe_reads_the_model(gemini_env) -> None:
    GeminiModel(get_settings()).probe(timeout_s=3.0)
    assert gemini_env.requests[0]["method"] == "GET"
    gemini_env.answer_probe(error(404, "NOT_FOUND"))
    with pytest.raises(ModelUnavailable) as caught:
        GeminiModel(get_settings()).probe(timeout_s=3.0)
    assert caught.value.reason == "model_not_found"


def test_one_sdk_client_is_kept_per_key(gemini_env, monkeypatch) -> None:
    built = []
    real = llm.http_client
    monkeypatch.setattr(llm, "http_client", lambda timeout: built.append(1) or real(timeout))
    gemini_env.answer(text("one"), text("two"))
    _generate()
    _generate()
    assert len(built) == 1


def test_the_thinking_level_reaches_the_request(gemini_env, settings_override) -> None:
    gemini_env.answer(text("one"), text("two"))
    _generate()
    config = gemini_env.generate_requests()[0]["body"]["generationConfig"]
    thinking = config["thinkingConfig"]  # google-genai 2.34.0 writes the proto field name
    assert (thinking.get("thinkingLevel") or thinking.get("thinking_level")) == "LOW"  # default
    settings_override(BRAIN_GEMINI_THINKING_LEVEL="")
    _generate()
    assert "thinkingConfig" not in gemini_env.generate_requests()[1]["body"]["generationConfig"]
