"""Why? through brain-api (research R-09; FR-013 to FR-014a). Written first (T048).

A model-phrased explanation is kept per recommendation and language and shown again unchanged,
also while the model is unreachable; the template is the plain version, built each time and never
stored.
"""

import json
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator, FormatChecker
from sqlalchemy import select, text

from brain.assistant.explain import FACTS_END, FACTS_START, render_template, row_facts
from brain.clock import today_cairo
from brain.jobs.registry import run_job
from brain.models import RiskResult

from fakes import sales_row
from scripted_model import Fail, Say
from series import spike_target

CONTRACT = (
    Path(__file__).resolve().parents[3] / "contracts/assistant/brain-api-assistant.openapi.yaml"
)


def validate(document) -> None:
    contract = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    schema = {"$ref": "#/components/schemas/Explanation", "components": contract["components"]}
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(document)


def _facts_of(request) -> dict:
    prompt = request["contents"][0]["text"]
    return json.loads(
        prompt[prompt.index(FACTS_START) + len(FACTS_START) : prompt.index(FACTS_END)]
    )


def _plain_en(_results, request) -> str:
    f = _facts_of(request)
    return (
        f"{f['product_id']} has {f['days_of_cover']} days of cover but its supplier needs "
        f"{f['lead_time_days']} days, so the risk is {f['risk']}; order {f['order_qty']}."
    )


def _plain_ar(_results, request) -> str:
    f = _facts_of(request)
    return f"لدى {f['product_id']} تغطية {f['days_of_cover']} يوم ومهلة {f['lead_time_days']} يوم؛ اطلب {f['order_qty']}."


def _newest(session, product_id: str) -> RiskResult:
    session.expire_all()
    return session.scalars(
        select(RiskResult)
        .where(RiskResult.product_id == product_id)
        .order_by(RiskResult.computed_at.desc(), RiskResult.id)
        .limit(1)
    ).one()


def _why(api_client, manager, rid, language="en"):
    return api_client.get(
        f"/api/v1/brain/explanations/{rid}", params={"language": language}, headers=manager
    )


def _kept(worker_session) -> int:
    worker_session.expire_all()
    return worker_session.scalar(text("SELECT count(*) FROM explanation"))


def test_a_model_phrased_explanation_is_kept_and_reused(
    first_night, api_client, manager, scripted, worker_session
) -> None:
    rid = _newest(worker_session, "P003").id
    scripted(Say(_plain_en))
    body = _why(api_client, manager, rid).json()
    assert body["source"] == "assistant" and body["product_id"] == "P003"
    rr = _newest(worker_session, "P003")
    assert body["text"].startswith(f"P003 has {float(rr.days_of_cover)} days of cover")
    validate(body)
    assert _kept(worker_session) == 1
    model = scripted(Fail("unreachable"))  # the model goes away: the kept text still comes back
    again = _why(api_client, manager, rid).json()
    assert again == body and model.calls == 0


def test_offline_with_nothing_kept_gives_the_template_and_stores_nothing(
    first_night, api_client, manager, scripted, worker_session
) -> None:
    rr = _newest(worker_session, "P003")
    model = scripted(Fail("unreachable"))
    body = _why(api_client, manager, rr.id).json()
    assert body["source"] == "template"
    assert body["text"] == render_template(row_facts(worker_session, rr), "en")
    validate(body)
    assert _kept(worker_session) == 0
    # Right after a failure Why? goes straight to the template (offline memory, R-06).
    assert _why(api_client, manager, rr.id).json()["source"] == "template"
    assert model.calls == 1


def test_two_failed_checks_give_the_template(
    first_night, api_client, manager, scripted, worker_session
) -> None:
    rid = _newest(worker_session, "P003").id
    model = scripted(Say("P003 has 987.65 days."), Say("P003 has 987.66 days."))
    body = _why(api_client, manager, rid).json()
    assert body["source"] == "template" and model.calls == 2
    assert "987.6" in model.requests[1]["contents"][-1]["text"]
    assert _kept(worker_session) == 0


def test_each_language_and_each_recommendation_gets_its_own(
    first_night, api_client, manager, scripted, worker_session
) -> None:
    rid = _newest(worker_session, "P005").id
    scripted(Say(_plain_en), Say(_plain_ar))
    en = _why(api_client, manager, rid, "en").json()
    ar = _why(api_client, manager, rid, "ar").json()
    assert (en["language"], ar["language"]) == ("en", "ar")
    assert ar["source"] == "assistant" and "تغطية" in ar["text"]
    assert _kept(worker_session) == 2

    # A newer recommendation (an hourly window after a P005 spike) gets its own explanation.
    fake, today = first_night, today_cairo()
    window = [
        (fake.sales.get(("P005", d.isoformat())) or {"net_units": 0})["net_units"]
        for d in (today.fromordinal(today.toordinal() - back) for back in range(28, 0, -1))
    ]
    fake.put_sales(sales_row("P005", today, spike_target(window), 0, "open", datetime.now(UTC)))
    assert run_job("sales-poll", "manual") == 0
    assert run_job("hourly-window", "manual") == 0
    newer = _newest(worker_session, "P005")
    assert newer.id != rid and newer.raised_by_spike
    scripted(Say(_plain_en))
    assert _why(api_client, manager, newer.id).json()["source"] == "assistant"
    assert _kept(worker_session) == 3
    scripted()  # the old one is still kept, unchanged
    assert _why(api_client, manager, rid).json() == en


def test_the_spike_in_the_facts_is_the_one_that_raised_it(first_night, worker_session) -> None:
    fake, today = first_night, today_cairo()
    window = [
        (fake.sales.get(("P005", d.isoformat())) or {"net_units": 0})["net_units"]
        for d in (today.fromordinal(today.toordinal() - back) for back in range(28, 0, -1))
    ]
    fake.put_sales(sales_row("P005", today, spike_target(window), 0, "open", datetime.now(UTC)))
    assert run_job("sales-poll", "manual") == 0
    assert run_job("hourly-window", "manual") == 0
    rr = _newest(worker_session, "P005")
    f = row_facts(worker_session, rr)
    assert f["raised_by_spike"] and f["spike_date"] == today.isoformat()
    z = worker_session.scalar(
        text(
            "SELECT z FROM anomaly WHERE product_id = 'P005' AND kind = 'spike' AND raised_risk "
            "AND found_at <= :at ORDER BY found_at DESC, business_date DESC LIMIT 1"
        ),
        {"at": rr.computed_at},
    )
    assert f["spike_z"] == round(float(z), 1)
    assert f"A demand spike on {today.isoformat()} (z = " in render_template(f, "en")
    assert "raised the risk one level, from low to medium" in render_template(f, "en")
    # A spike that hadn't been found yet when the row was computed is never used.
    older = _newest(worker_session, "P004")
    assert row_facts(worker_session, older)["spike_date"] is None


def test_two_first_openings_at_once_keep_one_text(
    first_night, worker_session, scripted, settings_override
) -> None:
    from brain.assistant import model as llm
    from brain.assistant.explain import get_explanation
    from brain.config import get_settings
    from brain.db import get_api_sessionmaker

    rid = _newest(worker_session, "P003").id
    scripted(Say(_plain_en), Say(_plain_en))
    stand_in = llm.model_from_settings()
    barrier = threading.Barrier(2)
    results = []

    def open_why():
        with get_api_sessionmaker()() as session:
            barrier.wait()
            results.append(get_explanation(session, rid, "en", stand_in, get_settings()))

    threads = [threading.Thread(target=open_why) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(results) == 2 and results[0] == results[1]
    assert _kept(worker_session) == 1


def test_errors(first_night, api_client, manager, scripted) -> None:
    scripted()
    missing = _why(api_client, manager, uuid.uuid4())
    assert missing.status_code == 404 and missing.json()["code"] == "NOT_FOUND"
    rid = uuid.uuid4()
    bad = api_client.get(
        f"/api/v1/brain/explanations/{rid}", params={"language": "fr"}, headers=manager
    )
    assert bad.status_code == 422 and bad.json()["code"] == "VALIDATION_ERROR"
    assert (
        api_client.get(f"/api/v1/brain/explanations/{rid}", params={"language": "en"}).status_code
        == 401
    )


def test_the_deadline_decides_whether_to_retry(
    first_night, api_client, manager, scripted, worker_session
) -> None:
    rid = _newest(worker_session, "P003").id
    model = scripted(Say("P003 has 987.65 days.", takes=7))
    body = _why(api_client, manager, rid).json()
    assert body["source"] == "template" and model.calls == 1  # under 3 s left of 9: no retry
    model = scripted(Say("P003 has 987.65 days.", takes=1), Say(_plain_en, takes=1))
    body = _why(api_client, manager, rid).json()
    assert body["source"] == "assistant" and model.calls == 2


def test_the_template_is_fast_when_the_model_is_unreachable(
    first_night, api_client, manager, gemini_env, settings_override, worker_session
) -> None:
    rid = _newest(worker_session, "P003").id
    settings_override(BRAIN_GEMINI_BASE_URL=gemini_env.closed_port_url())
    # The SDK client is built once per process (about half a second of TLS set-up); build it
    # first so this measures the unreachable call itself, cut by the 1.5 s connect timeout.
    from brain.assistant import model as llm
    from brain.config import get_settings

    llm._cached_client(llm.read_key(get_settings()), get_settings().gemini_base_url)
    started = time.perf_counter()
    assert _why(api_client, manager, rid).json()["source"] == "template"
    assert time.perf_counter() - started < 2.0


def test_a_hanging_model_is_bounded_and_then_skipped(
    first_night, api_client, manager, gemini_env, settings_override, worker_session
) -> None:
    """A server that accepts and never answers: the first opening ends with the template within
    the 9 s deadline; the next ones skip the model and are fast (offline memory)."""
    rid = _newest(worker_session, "P003").id
    settings_override(
        BRAIN_GEMINI_BASE_URL=gemini_env.silent_url(),
        BRAIN_EXPLANATION_TIMEOUT_SECONDS="2",
        BRAIN_EXPLANATION_DEADLINE_SECONDS="2.5",
    )
    started = time.perf_counter()
    assert _why(api_client, manager, rid).json()["source"] == "template"
    assert time.perf_counter() - started < 4.0
    started = time.perf_counter()
    assert _why(api_client, manager, rid, "ar").json()["source"] == "template"
    assert time.perf_counter() - started < 2.0
