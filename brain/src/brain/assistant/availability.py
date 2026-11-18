"""Whether the language model answers now (research R-06; GET /api/v1/brain/assistant).

Only an "available" answer is cached (`availability_cache_seconds`); after an offline answer the
next probe tries again, so "Check again" and the next chat send see a recovered model at once.
Every model call reports its outcome through `record`. Why? alone skips the model for
`why_offline_memory_seconds` after a failure, so its template stays fast during an outage.
After a real call gets 429 (rate limited, quota spent) or a 5xx, the check reports offline for
`availability_offline_seconds` without probing: the probe's models.get would still answer and the
screen would show "available" while every send fails. "Check again" (recheck) probes at once.

This reports only the model's reachability: nothing about jobs, data or freshness (it is not the
pipeline status endpoint README Section 7 cuts). One log line per offline change, with the reason
code only.
"""

import logging
import threading

from brain import clock
from brain.assistant.model import LanguageModel, ModelUnavailable
from brain.config import get_settings

log = logging.getLogger("brain.assistant")

_lock = threading.Lock()
_state: dict[str, float | str | None] = {
    "available_at": None,
    "failed_at": None,
    "reason": None,
    "hard_at": None,
    "hard_reason": None,
}
# Failures a probe can't see: the API answers models.get but refuses or drops real calls.
HARD = ("rate_limited", "server_error")


def reset() -> None:
    with _lock:
        _state.update(
            available_at=None, failed_at=None, reason=None, hard_at=None, hard_reason=None
        )


def record(reason: str | None, real_call: bool = True) -> None:
    """None after a successful call; a reason code after a failed one. Only a real call's 429 or
    5xx starts the offline memory; a failed probe doesn't (it is re-tried on the next check)."""
    now = clock.monotonic()
    with _lock:
        if reason is None:
            _state.update(
                available_at=now, failed_at=None, reason=None, hard_at=None, hard_reason=None
            )
            return
        changed = _state["reason"] != reason
        _state.update(available_at=None, failed_at=now, reason=reason)
        if real_call and reason in HARD:
            _state.update(hard_at=now, hard_reason=reason)
    if changed:
        log.warning("assistant offline: %s", reason)


def probe(model: LanguageModel, recheck: bool = False) -> tuple[bool, str | None]:
    settings = get_settings()
    with _lock:
        available_at = _state["available_at"]
        hard_at, hard_reason = _state["hard_at"], _state["hard_reason"]
    if (
        not recheck
        and isinstance(hard_at, float | int)
        and clock.monotonic() - hard_at < settings.availability_offline_seconds
    ):
        return False, str(hard_reason)
    if (
        isinstance(available_at, float | int)
        and clock.monotonic() - available_at < settings.availability_cache_seconds
    ):
        return True, None
    try:
        model.probe(settings.availability_probe_timeout_seconds)
    except ModelUnavailable as exc:
        record(exc.reason, real_call=False)
        return False, exc.reason
    record(None)
    return True, None


def why_should_skip_model() -> bool:
    with _lock:
        failed_at = _state["failed_at"]
    return (
        isinstance(failed_at, float | int)
        and clock.monotonic() - failed_at < get_settings().why_offline_memory_seconds
    )
