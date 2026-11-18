"""The morning briefing in the end-of-day run, and GET /briefing (research R-10). Written first
(T040).

The briefing is the run's last step, after the night's results are committed; it never fails the
run. It is published only when both the English and the Arabic text pass the grounding check.
"""

import json
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator, FormatChecker
from sqlalchemy import select, text

from brain.assistant.briefing import FACTS_END, FACTS_START, night_facts
from brain.jobs.registry import run_job
from brain.models import Briefing, Forecast, JobRun, RiskResult

from scripted_model import Fail, Say


def _facts_of(request) -> dict:
    prompt = request["contents"][0]["text"]
    return json.loads(
        prompt[prompt.index(FACTS_START) + len(FACTS_START) : prompt.index(FACTS_END)]
    )


def _english(_results, request) -> str:
    facts = _facts_of(request)
    high = "; ".join(
        f"{r['product_id']} ({r['product_name']}) has {r['days_of_cover']} days of cover, "
        f"order {r['order_qty']} from {r['supplier_id']}"
        for r in facts["high_risk"]
    )
    spikes = ", ".join(
        f"{a['product_id']} {a['kind']} on {a['business_date']}" for a in facts["anomalies"]
    )
    return f"Good morning. High risk: {high}. Anomalies: {spikes}."


def _arabic(_results, request) -> str:
    facts = _facts_of(request)
    high = "، ".join(
        f"{r['product_id']} تغطية {r['days_of_cover']} يوم والطلب المقترح {r['order_qty']}"
        for r in facts["high_risk"]
    )
    return f"صباح الخير. المنتجات ذات الخطر المرتفع: {high}."


def _run_end_of_day(worker_session) -> tuple[int, dict]:
    assert run_job("end-of-day", trigger="manual") == 0
    worker_session.expire_all()
    run = worker_session.scalars(
        select(JobRun).where(JobRun.job == "end-of-day").order_by(JobRun.id.desc()).limit(1)
    ).one()
    return run.id, run.summary


def _briefings(worker_session) -> list[Briefing]:
    worker_session.expire_all()
    return list(worker_session.scalars(select(Briefing).order_by(Briefing.id)))


def test_the_night_facts_are_computed_in_code(first_night, worker_session) -> None:
    run_id = worker_session.scalar(
        select(JobRun.id).where(JobRun.job == "end-of-day").order_by(JobRun.id.desc()).limit(1)
    )
    facts = night_facts(worker_session, run_id)
    assert facts["synthetic"] is True and facts["forecast_days"] == 7
    assert {r["product_id"] for r in facts["high_risk"]} == {"P003", "P011", "P017"}
    assert facts["medium_risk"] == []
    assert facts["counts"] == {"high": 3, "medium": 0, "low": 17}
    for row in facts["high_risk"]:
        assert {
            "days_of_cover",
            "lead_time_days",
            "order_qty",
            "reason_code",
            "supplier_id",
        } <= set(row)
        assert "forecast_next_days" in row
    kinds = {(a["product_id"], a["kind"]) for a in facts["anomalies"]}
    assert {
        ("P004", "spike"),
        ("P008", "spike"),
        ("P013", "spike"),
        ("P001", "drop"),
        ("P016", "drop"),
    } <= kinds
    assert len(facts["top_forecasts"]) == 3
    totals = [f["forecast_next_days"] for f in facts["top_forecasts"]]
    assert totals == sorted(totals, reverse=True)
    # The 7-day total is the sum of the run's first 7 forecast days, rounded by code.
    top = facts["top_forecasts"][0]
    rows = worker_session.scalars(
        select(Forecast.yhat)
        .where(Forecast.job_run_id == run_id, Forecast.product_id == top["product_id"])
        .order_by(Forecast.target_date)
        .limit(7)
    ).all()
    assert top["forecast_next_days"] == round(float(sum(rows)), 1)
    assert facts["night"] == worker_session.get(JobRun, run_id).summary["final_cut"]


def test_a_grounded_briefing_is_written_in_both_languages(
    fake_erp, worker_session, scripted
) -> None:
    model = scripted(Say(_english), Say(_arabic))
    run_id, summary = _run_end_of_day(worker_session)
    assert summary["briefing"] == "written"
    [briefing] = _briefings(worker_session)
    assert briefing.job_run_id == run_id and briefing.status == "written"
    # The night is the run's newest closed day, not the day the job ran.
    assert briefing.night.isoformat() == summary["final_cut"] == briefing.facts["night"]
    assert "P003" in briefing.text_en and "P003" in briefing.text_ar
    assert briefing.facts["high_risk"] and briefing.facts["synthetic"] is True
    assert "English" in model.requests[0]["system"] and "Arabic" in model.requests[1]["system"]
    assert model.requests[0]["timeout_s"] == 45


def test_one_language_failing_twice_publishes_nothing(fake_erp, worker_session, scripted) -> None:
    scripted(
        Say(_english), Say("صباح الخير. لدينا 987.65 وحدة."), Say("صباح الخير. لدينا 987.66 وحدة.")
    )
    _, summary = _run_end_of_day(worker_session)
    assert summary["briefing"] == "not_grounded"
    [briefing] = _briefings(worker_session)
    assert (
        briefing.status == "not_grounded" and briefing.text_en is None and briefing.text_ar is None
    )


def test_a_retry_can_fix_a_text(fake_erp, worker_session, scripted) -> None:
    model = scripted(Say("Good morning: 987.65 units."), Say(_english), Say(_arabic))
    _, summary = _run_end_of_day(worker_session)
    assert summary["briefing"] == "written"
    assert "987.65" in model.requests[1]["contents"][-1]["text"]


def test_an_unreachable_model_means_no_briefing(fake_erp, worker_session, scripted, caplog) -> None:
    import logging

    caplog.set_level(logging.INFO, logger="brain.assistant")
    scripted(Fail("rate_limited"))
    _, summary = _run_end_of_day(worker_session)
    # brain-worker logs the reason too, like brain-api (one line, the code only).
    assert "assistant offline: rate_limited" in [r.getMessage() for r in caplog.records]
    assert summary["briefing"] == "offline:rate_limited"
    [briefing] = _briefings(worker_session)
    assert briefing.status == "offline" and briefing.text_en is None


def test_the_briefing_never_fails_the_run(fake_erp, worker_session, scripted, monkeypatch) -> None:
    scripted()

    def broken(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("brain.assistant.briefing.night_facts", broken)
    run_id, summary = _run_end_of_day(worker_session)
    assert summary["briefing"] == "offline:error"
    assert worker_session.get(JobRun, run_id).status == "succeeded"
    assert worker_session.scalar(select(text("count(*)")).select_from(RiskResult)) == 20
    [briefing] = _briefings(worker_session)
    assert briefing.status == "offline"


def test_a_manual_rerun_adds_a_briefing(fake_erp, worker_session, scripted) -> None:
    scripted(Say(_english), Say(_arabic), Fail("timeout"))
    _run_end_of_day(worker_session)
    _run_end_of_day(worker_session)
    first, second = _briefings(worker_session)
    assert (first.status, second.status) == ("written", "offline")
    assert first.job_run_id != second.job_run_id


def test_a_run_with_no_data_writes_no_briefing(pg, worker_session, scripted, monkeypatch) -> None:
    from fakes import FakeCanonical

    scripted()
    monkeypatch.setattr("brain.canonical.client.TEST_TRANSPORT", FakeCanonical().transport())
    _, summary = _run_end_of_day(worker_session)
    assert summary["briefing"] == "none"
    assert _briefings(worker_session) == []


CONTRACT = (
    Path(__file__).resolve().parents[3]
    / "specs/005-ai-assistant/contracts/brain-api-assistant.openapi.yaml"
)


def validate(name: str, document) -> None:
    contract = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    schema = {"$ref": f"#/components/schemas/{name}", "components": contract["components"]}
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(document)


@pytest.fixture
def briefing_api(api_client, manager):
    return lambda: api_client.get("/api/v1/brain/briefing", headers=manager).json()


def test_the_briefing_states(fake_erp, worker_session, scripted, briefing_api) -> None:
    body = briefing_api()
    assert body == {
        "synthetic": True,
        "state": "none",
        "night": None,
        "run_finished_at": None,
        "text_en": None,
        "text_ar": None,
    }
    validate("Briefing", body)

    scripted(Say(_english), Say(_arabic), Fail("unreachable"))
    _run_end_of_day(worker_session)
    body = briefing_api()
    assert body["state"] == "written" and "P003" in body["text_en"] and "P003" in body["text_ar"]
    assert body["night"] and body["run_finished_at"]
    validate("Briefing", body)

    _run_end_of_day(worker_session)  # the model is unreachable this time
    body = briefing_api()
    assert body["state"] == "offline"  # not yesterday's text (FR-011)
    assert body["text_en"] is None and body["text_ar"] is None and body["night"]
    validate("Briefing", body)


def test_a_text_that_skips_a_high_risk_product_is_not_published(
    fake_erp, worker_session, scripted
) -> None:
    """SC-006: each language must cover every high-risk product. A content-free answer (no
    numbers, right language) would pass the number check alone; it is retried, then refused."""
    meta = "الرد السابق مكتوب بالفعل باللغة العربية. يرجى مراجعته."
    model = scripted(Say(_english), Say(meta), Say(meta))
    _, summary = _run_end_of_day(worker_session)
    assert summary["briefing"] == "not_grounded"
    correction = model.requests[2]["contents"][-1]["text"]
    assert "P003" in correction and "P011" in correction and "P017" in correction


def test_a_retry_can_add_the_missing_products(fake_erp, worker_session, scripted) -> None:
    model = scripted(Say(_english), Say("صباح الخير."), Say(_arabic))
    _, summary = _run_end_of_day(worker_session)
    assert summary["briefing"] == "written" and model.calls == 3


def test_an_arabic_briefing_quoting_english_names_is_published(
    fake_erp, worker_session, scripted
) -> None:
    """Product and supplier names stay in English; they don't make an Arabic text "English"."""

    def arabic_with_names(_results, request) -> str:
        facts = _facts_of(request)
        rows = "، ".join(
            f"{r['product_id']} {r['product_name']} من {r['supplier_name']}: تغطية {r['days_of_cover']} يوم"
            for r in facts["high_risk"]
        )
        tops = "، ".join(
            f"{t['product_name']} {t['forecast_next_days']}" for t in facts["top_forecasts"]
        )
        return f"صباح الخير. {rows}. أعلى التوقعات: {tops}."

    model = scripted(Say(_english), Say(arabic_with_names))
    _, summary = _run_end_of_day(worker_session)
    assert summary["briefing"] == "written" and model.calls == 2
