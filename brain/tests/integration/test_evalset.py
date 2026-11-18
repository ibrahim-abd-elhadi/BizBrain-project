"""The evaluation set against the scripted stand-in (FR-023, SC-008). Written first (T054).

Every question must pass every check: grounded, language, required tools, side effects (a proposal
only for A08, no ERP POST) and its own checks, all computed from the database of the run.
"""

import pytest
from sqlalchemy import select

from brain.assistant.evalset import QUESTIONS
from brain.assistant.evaluation import run_evaluation
from brain.config import get_settings
from brain.models import Proposal
from brain.proposals.service import create_proposal

from evalset_scripts import ORDER, SCRIPTS, all_steps
from scripted_model import Call, Say, ScriptedModel


def test_the_set_is_ten_questions_five_per_language() -> None:
    assert [q.id for q in QUESTIONS] == ORDER
    assert sum(q.language == "en" for q in QUESTIONS) == 5
    assert sum(q.language == "ar" for q in QUESTIONS) == 5


@pytest.mark.parametrize("qid", ORDER)
def test_each_question_passes_against_the_stand_in(
    first_night, worker_session, fake_clock, qid
) -> None:
    model = ScriptedModel(*SCRIPTS[qid], clock=fake_clock)
    run = run_evaluation(worker_session, model, get_settings(), only=[qid])
    [result] = run.results
    failed = [(name, detail) for name, ok, detail in result.checks if not ok]
    assert failed == [], (result.replies, failed)
    assert result.grounded and result.passed
    assert first_night.post_requests() == []


def test_the_whole_set_passes_and_leaves_nothing_behind(
    first_night, worker_session, fake_clock
) -> None:
    model = ScriptedModel(*all_steps(), clock=fake_clock)
    run = run_evaluation(worker_session, model, get_settings())
    assert [r.id for r in run.results] == ORDER
    assert run.passed == 10 and run.grounded == 10
    worker_session.expire_all()
    assert list(worker_session.scalars(select(Proposal))) == []  # A08's proposal rolled back
    assert first_night.post_requests() == []


def test_a08_passes_on_the_pending_link_when_p003_is_live(
    first_night, worker_session, fake_clock
) -> None:
    live = create_proposal(
        worker_session,
        supplier_id="S004",
        lines=[{"product_id": "P003", "quantity": 12}],
        origin="assistant",
    )
    worker_session.commit()
    model = ScriptedModel(*SCRIPTS["A08"], clock=fake_clock)
    run = run_evaluation(worker_session, model, get_settings(), only=["A08"])
    assert run.live_p003 == str(live.id)
    [result] = run.results
    assert result.passed, result.checks
    worker_session.expire_all()
    assert len(list(worker_session.scalars(select(Proposal)))) == 1


def test_the_checks_catch_a_bad_answer(first_night, worker_session, fake_clock) -> None:
    """An answer that leaves out P017 and invents a number fails, and is reported as such."""
    model = ScriptedModel(
        Call("get_risk_list", {"risk": "high"}),
        Say("High risk: P003 and P011."),
        clock=fake_clock,
    )
    [result] = run_evaluation(worker_session, model, get_settings(), only=["E01"]).results
    assert not result.passed
    assert ("names exactly the high-risk products", False) in [
        (n, ok) for n, ok, _ in result.checks
    ]

    model = ScriptedModel(
        Say("P999 has 987.65 units."), Say("P999 has 987.66 units."), clock=fake_clock
    )
    [result] = run_evaluation(worker_session, model, get_settings(), only=["E09"]).results
    assert not result.grounded and not result.passed
    assert result.attempts == [2] and result.unsupported == [["987.66"]]


def test_a_question_that_proposes_when_it_shouldnt_fails(
    first_night, worker_session, fake_clock
) -> None:
    model = ScriptedModel(
        Call("propose_purchase_order", {"product_ids": ["P003"]}),
        Say("I prepared it from S004."),
        clock=fake_clock,
    )
    [result] = run_evaluation(worker_session, model, get_settings(), only=["E07"]).results
    side_effects = next(ok for name, ok, _ in result.checks if name == "side effects")
    assert side_effects is False and not result.passed
