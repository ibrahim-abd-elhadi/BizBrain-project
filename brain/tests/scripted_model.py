"""The scripted stand-in for the language model (feature 005, T009; research R-12, R-13).

`ScriptedModel` implements the same `LanguageModel` protocol as the Gemini adapter, so the graph,
the tools, the grounding guard and the propose rules all run for real while the model's turns
are fixed. Steps:

- `Call(name, args)` (or several in one `Calls(...)`): a turn that asks for tool calls;
- `Say(fn)`: a final text; `fn(results)` gets the tool results received so far (a list of
  {"name", "response"} dicts, newest last) and the request, and returns the text;
- `Fail(reason)`: raises ModelUnavailable(reason); `Unusable()`: raises ModelUnusable.

Every step can take `takes=seconds`: the fake monotonic clock moves forward that much instead of
sleeping. A step that takes longer than the timeout it was given raises ModelUnavailable("timeout"),
as the real adapter would.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from brain.assistant.model import ModelTurn, ModelUnavailable, ModelUnusable, ToolCall


@dataclass
class Call:
    name: str
    args: dict[str, Any] = field(default_factory=dict)
    takes: float = 0.0


@dataclass
class Calls:
    calls: list[Call]
    takes: float = 0.0


@dataclass
class Say:
    fn: Callable[..., str] | str
    takes: float = 0.0


@dataclass
class Fail:
    reason: str = "unreachable"
    takes: float = 0.0


@dataclass
class Unusable:
    takes: float = 0.0


def results_of(contents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"name": c["name"], "response": c["response"]} for c in contents if c["role"] == "tool"]


def latest(results: list[dict[str, Any]], name: str) -> dict[str, Any]:
    """The newest result of tool `name`."""
    for r in reversed(results):
        if r["name"] == name:
            return r["response"]
    raise AssertionError(f"the script expected a {name} result")


class ScriptedModel:
    model_id = "scripted-stand-in"

    def __init__(self, *steps: Any, clock: Any = None) -> None:
        self.steps = list(steps)
        self.requests: list[dict[str, Any]] = []
        self.clock = clock
        self.probes = 0

    @property
    def calls(self) -> int:
        return len(self.requests)

    def add(self, *steps: Any) -> None:
        self.steps.extend(steps)

    def probe(self, timeout_s: float) -> None:
        self.probes += 1

    def generate(
        self,
        *,
        system: str,
        contents: list[dict[str, Any]],
        tools: list[Any],
        timeout_s: float,
        connect_timeout_s: float | None = None,
    ) -> ModelTurn:
        request = {
            "system": system,
            "contents": list(contents),
            "tools": [t.name for t in tools],
            "timeout_s": timeout_s,
        }
        self.requests.append(request)
        if not self.steps:
            raise AssertionError(f"the model was called {len(self.requests)} times; not scripted")
        step = self.steps.pop(0)
        if step.takes:
            if self.clock is not None:
                self.clock.advance(min(step.takes, timeout_s))
            if step.takes > timeout_s:
                raise ModelUnavailable("timeout")
        if isinstance(step, Fail):
            raise ModelUnavailable(step.reason)
        if isinstance(step, Unusable):
            raise ModelUnusable()
        if isinstance(step, Call):
            step = Calls([step])
        if isinstance(step, Calls):
            calls = [ToolCall(c.name, dict(c.args)) for c in step.calls]
            return ModelTurn(text=None, tool_calls=calls, raw={"role": "model", "calls": calls})
        if isinstance(step, Say):
            value = step.fn if isinstance(step.fn, str) else step.fn(results_of(contents), request)
            return ModelTurn(text=value, tool_calls=[], raw={"role": "model", "text": value})
        raise AssertionError(f"unknown step {step!r}")
