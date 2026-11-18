"""Offline mode is fast and bounded (SC-002, SC-005, SC-007). Written for T062; marker `slow`.

The real adapter runs against unreachable addresses: a refused port, a server that accepts and
never answers, and an unroutable address.
"""

import socket
import time

import pytest
from sqlalchemy import text as sql

from fake_gemini import text
from scripted_model import Call, Say, latest

pytestmark = pytest.mark.slow

CHAT = "/api/v1/brain/assistant/messages"
ASK = {"messages": [{"role": "manager", "text": "Which products are at high risk?"}]}


def _timed(call):
    started = time.perf_counter()
    result = call()
    return result, time.perf_counter() - started


def test_a_refused_port_is_offline_within_five_seconds(
    gemini_env, first_night, api_client, manager, settings_override
) -> None:
    settings_override(BRAIN_GEMINI_BASE_URL=gemini_env.closed_port_url())
    body, seconds = _timed(lambda: api_client.post(CHAT, json=ASK, headers=manager).json())
    assert body["outcome"] == "offline" and seconds < 5, seconds
    body, seconds = _timed(
        lambda: api_client.get("/api/v1/brain/assistant", headers=manager).json()
    )
    assert body["available"] is False and seconds < 5, seconds


def test_a_server_that_never_answers_is_bounded(
    gemini_env, first_night, api_client, manager, settings_override
) -> None:
    settings_override(BRAIN_GEMINI_BASE_URL=gemini_env.silent_url())
    body, seconds = _timed(lambda: api_client.post(CHAT, json=ASK, headers=manager).json())
    assert body["outcome"] == "offline" and body["offline_reason"] == "timeout"
    assert seconds < 14 + 2, seconds  # within the turn deadline, never hanging
    body, seconds = _timed(
        lambda: api_client.get("/api/v1/brain/assistant", headers=manager).json()
    )
    assert body == {"synthetic": True, "available": False, "reason": "timeout"} and seconds < 3.5, (
        seconds
    )


def test_an_unroutable_address_is_cut_by_the_connect_timeout(
    gemini_env, first_night, api_client, manager, settings_override
) -> None:
    probe = socket.socket()
    probe.settimeout(0.5)
    try:
        probe.connect(("10.255.255.1", 80))
        pytest.skip("10.255.255.1 is reachable from this machine")
    except TimeoutError:
        pass  # dropped silently: the case the connect timeout is for
    except OSError as exc:
        pytest.skip(f"the OS rejects 10.255.255.1 at once ({type(exc).__name__})")
    finally:
        probe.close()
    settings_override(BRAIN_GEMINI_BASE_URL="http://10.255.255.1")
    body, seconds = _timed(lambda: api_client.post(CHAT, json=ASK, headers=manager).json())
    assert body["outcome"] == "offline" and body["offline_reason"] == "timeout"
    assert seconds < 5, seconds


def test_the_template_is_under_two_seconds_after_the_model_goes_away(
    gemini_env, first_night, api_client, manager, worker_session
) -> None:
    rid = worker_session.scalar(
        sql(
            "SELECT id FROM risk_result WHERE product_id = 'P003' ORDER BY computed_at DESC LIMIT 1"
        )
    )
    gemini_env.answer(text("P003 is high risk."))
    url = f"/api/v1/brain/explanations/{rid}"
    assert (
        api_client.get(url, params={"language": "en"}, headers=manager).json()["source"]
        == "assistant"
    )
    gemini_env.close()  # the model goes away: the same address now refuses connections
    body, seconds = _timed(
        lambda: api_client.get(url, params={"language": "ar"}, headers=manager).json()
    )
    assert body["source"] == "template" and seconds < 2, seconds


def test_the_brain_adds_little_time_to_a_turn(first_night, api_client, manager, scripted) -> None:
    scripted(
        Call("get_risk_list", {"risk": "high"}),
        Say(
            lambda r, q: (
                "High: " + ", ".join(i["product_id"] for i in latest(r, "get_risk_list")["items"])
            )
        ),
    )
    api_client.get("/api/v1/brain/risk", headers=manager)  # warm the database connections
    body, seconds = _timed(lambda: api_client.post(CHAT, json=ASK, headers=manager).json())
    assert body["outcome"] == "answered" and seconds < 1.0, seconds
