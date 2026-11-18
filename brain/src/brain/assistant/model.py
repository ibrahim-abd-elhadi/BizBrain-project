"""The language model behind one small protocol, and the Gemini adapter (research R-01, R-05).

This is the only module that imports `google.genai`. Every failure leaves it as one of two
exceptions:

- `ModelUnavailable(reason)`: no key, unreachable, too slow, key refused, unknown model, rate
  limited, server error or another refusal. Callers treat it as offline mode (D-17);
- `ModelUnusable`: an answer with neither text nor a tool call (empty, blocked). Callers treat it
  like a grounding failure.

There is no automatic retry (one attempt, `HttpRetryOptions(attempts=1)`). The key is read from
its file (never an environment variable), goes only into the client, and never into a log line,
an exception or a response (FR-018). Google's error messages are never passed on.
"""

import threading
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import httpx
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from brain import clock
from brain.config import Settings, get_settings

REASONS = (
    "no_key",
    "unreachable",
    "timeout",
    "key_refused",
    "model_not_found",
    "rate_limited",
    "server_error",
    "refused",
)


class ModelUnavailable(Exception):
    """The model can't be used now; `reason` is one of REASONS (never Google's text)."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"assistant offline: {reason}")
        self.reason = reason


class ModelUnusable(Exception):
    """The model answered with nothing usable (no text and no tool call, or a blocked answer)."""


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(frozen=True)
class ToolCall:
    name: str
    args: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ModelTurn:
    """One model answer: a final text, or tool calls. `raw` is the provider's own turn, sent back
    unchanged in the next request (Gemini 3 needs its thought signatures back)."""

    text: str | None
    tool_calls: list[ToolCall]
    raw: Any = None


class LanguageModel(Protocol):
    """`contents` items: {"role": "user"|"model", "text"}, {"role": "model_raw", "raw"} or
    {"role": "tool", "name", "response"}."""

    model_id: str

    def generate(
        self,
        *,
        system: str,
        contents: list[dict[str, Any]],
        tools: list[ToolSpec],
        timeout_s: float,
        connect_timeout_s: float | None = None,
    ) -> ModelTurn: ...

    def probe(self, timeout_s: float) -> None: ...


# ---------------------------------------------------------------- the key file (R-11)

_key_cache: dict[str, tuple[str | None, float]] = {}


def read_key(settings: Settings) -> str | None:
    """The key, re-read at most every `gemini_key_cache_seconds`. None for a missing, empty,
    unreadable or directory path (Docker creates a directory for a missing bind-mount source)."""
    path = str(settings.gemini_api_key_file)
    now = clock.monotonic()
    cached = _key_cache.get(path)
    if cached is not None and now - cached[1] < settings.gemini_key_cache_seconds:
        return cached[0]
    try:
        value = Path(path).read_text(encoding="utf-8").strip() or None
    except (OSError, UnicodeDecodeError):
        value = None
    _key_cache[path] = (value, now)
    return value


def clear_key_cache() -> None:
    _key_cache.clear()
    with _clients_lock:
        for _, http in _clients.values():
            http.close()
        _clients.clear()


# ---------------------------------------------------------------- the adapter


# The timeout of the call in progress, per thread (each call sets its own; see GeminiModel).
_call_timeout: ContextVar[httpx.Timeout | None] = ContextVar(
    "brain_assistant_timeout", default=None
)


class FixedTimeoutClient(httpx.Client):
    """The SDK passes its own timeout with every request, which would replace a client default;
    this client always applies the current call's `httpx.Timeout`, so the separate connect timeout
    holds (research R-05: an unreachable host fails within 3 s)."""

    def build_request(self, *args: Any, **kwargs: Any) -> httpx.Request:
        kwargs["timeout"] = _call_timeout.get() or self.timeout
        return super().build_request(*args, **kwargs)


def http_client(timeout: httpx.Timeout) -> httpx.Client:
    return FixedTimeoutClient(timeout=timeout)


# Building an SDK client loads TLS certificates (about half a second), so one client is kept per
# key and base URL. A changed key file gives a new client; the old ones close with the cache.
_clients: dict[tuple[str, str | None], tuple[Any, httpx.Client]] = {}
_clients_lock = threading.Lock()


def _cached_client(key: str, base_url: str | None) -> Any:
    with _clients_lock:
        found = _clients.get((key, base_url))
        if found is None:
            http = http_client(httpx.Timeout(10.0))
            options = types.HttpOptions(
                retry_options=types.HttpRetryOptions(attempts=1), httpx_client=http
            )
            if base_url:
                options.base_url = base_url
            found = (genai.Client(api_key=key, http_options=options), http)
            _clients[(key, base_url)] = found
        return found[0]


def _reason(exc: Exception) -> str:
    if isinstance(exc, genai_errors.APIError):
        code = int(getattr(exc, "code", 0) or 0)
        if code == 400 and "API_KEY_INVALID" in str(getattr(exc, "details", "")):
            return "key_refused"
        if code in (401, 403):
            return "key_refused"
        if code == 404:
            return "model_not_found"
        if code == 429:
            return "rate_limited"
        if code >= 500:
            return "server_error"
        return "refused"
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    if isinstance(exc, httpx.HTTPError | OSError):
        return "unreachable"
    return "refused"


def _contents(contents: list[dict[str, Any]]) -> list[Any]:
    out: list[Any] = []
    pending: list[types.Part] = []

    def flush() -> None:
        if pending:
            out.append(types.Content(role="user", parts=list(pending)))
            pending.clear()

    for item in contents:
        role = item["role"]
        if role == "tool":
            pending.append(
                types.Part.from_function_response(name=item["name"], response=item["response"])
            )
            continue
        flush()
        if role == "model_raw":
            out.append(item["raw"])
        else:
            out.append(
                types.Content(
                    role="model" if role == "model" else "user",
                    parts=[types.Part(text=item["text"])],
                )
            )
    flush()
    return out


def _turn(response: Any) -> ModelTurn:
    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        raise ModelUnusable()
    content = candidates[0].content
    parts = list(content.parts or []) if content is not None else []
    calls = [
        ToolCall(p.function_call.name or "", dict(p.function_call.args or {}))
        for p in parts
        if p.function_call is not None
    ]
    if calls:
        return ModelTurn(text=None, tool_calls=calls, raw=content)
    text = "".join(p.text for p in parts if p.text and not p.thought).strip()
    if not text:
        raise ModelUnusable()
    return ModelTurn(text=text, tool_calls=[], raw=content)


class GeminiModel:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.model_id = settings.gemini_model

    def _client(
        self, timeout_s: float, connect_timeout_s: float | None
    ) -> tuple[Any, httpx.Timeout]:
        if timeout_s <= 0:
            raise ModelUnavailable("timeout")
        key = read_key(self.settings)
        if not key:
            raise ModelUnavailable("no_key")
        connect = connect_timeout_s or self.settings.gemini_connect_timeout_seconds
        timeout = httpx.Timeout(timeout_s, connect=min(connect, timeout_s))
        return _cached_client(key, self.settings.gemini_base_url), timeout

    def generate(
        self,
        *,
        system: str,
        contents: list[dict[str, Any]],
        tools: list[ToolSpec],
        timeout_s: float,
        connect_timeout_s: float | None = None,
    ) -> ModelTurn:
        request_contents = _contents(contents)
        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=self.settings.gemini_temperature,
            tools=[
                types.Tool(
                    function_declarations=[
                        types.FunctionDeclaration(
                            name=t.name,
                            description=t.description,
                            parameters_json_schema=t.parameters,
                        )
                        for t in tools
                    ]
                )
            ]
            if tools
            else None,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            thinking_config=types.ThinkingConfig(
                thinking_level=self.settings.gemini_thinking_level.upper()
            )
            if self.settings.gemini_thinking_level
            else None,
        )
        client, timeout = self._client(timeout_s, connect_timeout_s)
        token = _call_timeout.set(timeout)
        try:
            response = client.models.generate_content(
                model=self.model_id, contents=request_contents, config=config
            )
        except Exception as exc:  # noqa: BLE001  (every failure becomes a reason, R-05)
            raise ModelUnavailable(_reason(exc)) from None
        finally:
            _call_timeout.reset(token)
        return _turn(response)

    def probe(self, timeout_s: float) -> None:
        """A cheap check that the key and model answer (models.get generates nothing)."""
        connect = min(timeout_s, self.settings.gemini_connect_timeout_seconds)
        client, timeout = self._client(timeout_s, connect)
        token = _call_timeout.set(timeout)
        try:
            client.models.get(model=self.model_id)
        except Exception as exc:  # noqa: BLE001
            raise ModelUnavailable(_reason(exc)) from None
        finally:
            _call_timeout.reset(token)


def model_from_settings() -> LanguageModel:
    """The model the API, the worker and the evaluation command use. Callers look it up as
    `model.model_from_settings()` each time, so tests can replace it."""
    return GeminiModel(get_settings())
