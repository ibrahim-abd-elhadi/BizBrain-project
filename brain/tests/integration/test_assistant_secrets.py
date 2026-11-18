"""The Gemini key never leaks (FR-018). Written for T061.

With a canary key and the real adapter against the fake Gemini server: after a chat turn, an
offline turn, a refused-key turn, a Why? (model-phrased and template), an end-of-day with a
briefing and an eval-assistant run, the key appears in no log line, no response, no table and no
report; it went only into the x-goog-api-key header.
"""

import json
import logging
import os

from sqlalchemy import text as sql

from brain.jobs.cli import main
from brain.jobs.registry import run_job

from fake_gemini import CANARY_KEY, error, function_call, text

CHAT = "/api/v1/brain/assistant/messages"


def test_the_key_never_leaks(
    gemini_env, first_night, api_client, manager, worker_session, caplog, capsys, tmp_path
) -> None:
    caplog.set_level(logging.DEBUG)
    fake = gemini_env
    bodies: list[str] = []

    def ask(question: str) -> dict:
        response = api_client.post(
            CHAT, json={"messages": [{"role": "manager", "text": question}]}, headers=manager
        )
        bodies.append(response.text)
        return response.json()

    fake.answer(
        function_call("get_risk_list", {"risk": "high"}), text("P003, P011 and P017 are high risk.")
    )
    assert ask("Which products are at high risk?")["outcome"] == "answered"
    fake.answer(error(503, "UNAVAILABLE"))
    assert ask("Which products are at high risk?")["offline_reason"] == "server_error"
    fake.answer(error(400, "INVALID_ARGUMENT", "API_KEY_INVALID"))
    assert ask("Which products are at high risk?")["offline_reason"] == "key_refused"
    # "Check again": the 503 above made the check say offline for 30 s without probing.
    bodies.append(api_client.get("/api/v1/brain/assistant?recheck=true", headers=manager).text)

    rid = worker_session.scalar(
        sql(
            "SELECT id FROM risk_result WHERE product_id = 'P003' ORDER BY computed_at DESC LIMIT 1"
        )
    )
    fake.answer(text("P003 is high risk."))
    why = api_client.get(
        f"/api/v1/brain/explanations/{rid}", params={"language": "en"}, headers=manager
    )
    bodies.append(why.text)
    assert why.json()["source"] == "assistant"
    fake.answer(error(401, "UNAUTHENTICATED"))
    template = api_client.get(
        f"/api/v1/brain/explanations/{rid}", params={"language": "ar"}, headers=manager
    )
    bodies.append(template.text)
    assert template.json()["source"] == "template"

    fake.answer(
        text("Good morning. The night's results are ready."),
        text("صباح الخير. نتائج الليلة جاهزة."),
    )
    assert run_job("end-of-day", trigger="manual") == 0
    bodies.append(api_client.get("/api/v1/brain/briefing", headers=manager).text)

    fake.answer(text("I don't have information about P999: it isn't in the catalog."))
    out = tmp_path / "reports"
    assert main(["eval-assistant", "--out", str(out), "--only", "E09"]) == 0

    # Logs and printed output.
    for record in caplog.records:
        assert CANARY_KEY not in record.getMessage()
    captured = capsys.readouterr()
    assert CANARY_KEY not in captured.out and CANARY_KEY not in captured.err
    # Responses.
    for body in bodies:
        assert CANARY_KEY not in body
    # Every Brain table.
    from brain.models import Base

    worker_session.expire_all()
    for table in Base.metadata.sorted_tables:
        rows = worker_session.execute(sql(f'SELECT * FROM "{table.name}"')).fetchall()
        assert CANARY_KEY not in json.dumps([list(r) for r in rows], default=str), table.name
    # Reports.
    for report in out.iterdir():
        assert CANARY_KEY not in report.read_text(encoding="utf-8")
    # The environment.
    for name in ("GOOGLE_API_KEY", "GEMINI_API_KEY"):
        assert name not in os.environ
    assert os.environ.get("LANGSMITH_TRACING", "false").lower() != "true"
    assert os.environ.get("LANGCHAIN_TRACING_V2", "false").lower() != "true"
    # Where the key did go: the header only.
    assert fake.requests
    for request in fake.requests:
        assert request["headers"].get("x-goog-api-key") == CANARY_KEY
        others = {k: v for k, v in request["headers"].items() if k != "x-goog-api-key"}
        assert CANARY_KEY not in json.dumps(others)
        assert CANARY_KEY not in request["path"] and CANARY_KEY not in json.dumps(request["body"])
