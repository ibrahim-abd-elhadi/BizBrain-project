"""`brain-worker eval-assistant` (contracts/assistant/evaluation-set.md). Written first (T055).

The command runs the set in one rolled-back transaction and writes a dated report; it exits 0 even
when questions fail (a report, not a build gate), 2 when its preconditions fail.
"""

import json
from datetime import UTC, datetime

import time_machine
from sqlalchemy import select

from brain.jobs.cli import main
from brain.models import Proposal
from brain.proposals.service import create_proposal

from evalset_scripts import all_steps
from fake_gemini import CANARY_KEY
from fakes import TOKEN
from scripted_model import Say

FROZEN = datetime(2026, 11, 25, 9, 15, tzinfo=UTC)


def _install(monkeypatch, fake_clock, steps, model_id="gemini-3.6-flash"):
    from scripted_model import ScriptedModel

    stand_in = ScriptedModel(*steps, clock=fake_clock)
    stand_in.model_id = model_id
    monkeypatch.setattr("brain.assistant.model.model_from_settings", lambda: stand_in)
    return stand_in


def test_the_report_is_written_and_the_proposal_rolled_back(
    first_night, worker_session, monkeypatch, fake_clock, tmp_path, capsys
) -> None:
    _install(monkeypatch, fake_clock, all_steps())
    with time_machine.travel(FROZEN, tick=False):
        assert main(["eval-assistant", "--out", str(tmp_path)]) == 0
    md = tmp_path / "2026-11-25T0915Z-gemini-3.6-flash.md"
    js = tmp_path / "2026-11-25T0915Z-gemini-3.6-flash.json"
    assert md.exists() and js.exists()
    report = md.read_text(encoding="utf-8")
    assert "# Assistant evaluation: gemini-3.6-flash" in report
    assert "All data is synthetic" in report and "Night of the results:" in report
    assert "| 10 / 10 | 10 / 10 |" in report  # passed, grounded
    assert report.count("✅ passed") == 10
    assert '<div dir="rtl" lang="ar">' in report
    data = json.loads(js.read_text(encoding="utf-8"))
    assert data["passed"] == 10 and data["grounded"] == 10 and data["synthetic"] is True
    assert "passed=10/10" in capsys.readouterr().out
    worker_session.expire_all()
    assert list(worker_session.scalars(select(Proposal))) == []
    for text in (report, js.read_text(encoding="utf-8")):
        assert CANARY_KEY not in text and TOKEN not in text


def test_a_failing_question_still_exits_zero(
    first_night, monkeypatch, fake_clock, tmp_path
) -> None:
    steps = all_steps({"E09": [Say("P999 has 987.65 units."), Say("P999 has 987.66 units.")]})
    _install(monkeypatch, fake_clock, steps)
    assert main(["eval-assistant", "--out", str(tmp_path)]) == 0
    report = next(tmp_path.glob("*.md")).read_text(encoding="utf-8")
    assert "| 9 / 10 | 9 / 10 |" in report and "## E09 (en): ❌ failed" in report
    assert "unsupported: 987.66" in report


def test_only_some_questions(first_night, monkeypatch, fake_clock, tmp_path) -> None:
    from evalset_scripts import SCRIPTS

    _install(monkeypatch, fake_clock, [*SCRIPTS["E01"], *SCRIPTS["A08"]])
    assert main(["eval-assistant", "--out", str(tmp_path), "--only", "E01,A08"]) == 0
    data = json.loads(next(tmp_path.glob("*.json")).read_text(encoding="utf-8"))
    assert [r["id"] for r in data["results"]] == ["E01", "A08"]


def test_the_model_id_names_the_report(first_night, monkeypatch, fake_clock, tmp_path) -> None:
    from evalset_scripts import SCRIPTS

    _install(monkeypatch, fake_clock, SCRIPTS["E01"], model_id="gemini-3.8-flash")
    assert main(["eval-assistant", "--out", str(tmp_path), "--only", "E01"]) == 0
    [md] = tmp_path.glob("*.md")
    assert md.name.endswith("-gemini-3.8-flash.md")
    assert "`gemini-3.8-flash`" in md.read_text(encoding="utf-8")


def test_a_live_p003_proposal_is_warned_about(
    first_night, worker_session, monkeypatch, fake_clock, tmp_path
) -> None:
    from evalset_scripts import SCRIPTS

    create_proposal(
        worker_session,
        supplier_id="S004",
        lines=[{"product_id": "P003", "quantity": 12}],
        origin="assistant",
    )
    worker_session.commit()
    _install(monkeypatch, fake_clock, SCRIPTS["A08"])
    assert main(["eval-assistant", "--out", str(tmp_path), "--only", "A08"]) == 0
    report = next(tmp_path.glob("*.md")).read_text(encoding="utf-8")
    assert "P003 already has a live proposal; A08 checks the pending link instead" in report
    assert "## A08 (ar): ✅ passed" in report


def test_no_results_exits_two(pg, monkeypatch, fake_clock, tmp_path, capsys) -> None:
    _install(monkeypatch, fake_clock, [])
    assert main(["eval-assistant", "--out", str(tmp_path)]) == 2
    assert "no end-of-day results; run brain-worker run end-of-day first" in capsys.readouterr().out
    assert list(tmp_path.iterdir()) == []


def test_no_key_exits_two(first_night, settings_override, tmp_path, capsys) -> None:
    settings_override(BRAIN_GEMINI_API_KEY_FILE=str(tmp_path / "absent"))
    assert main(["eval-assistant", "--out", str(tmp_path / "out")]) == 2
    assert "assistant offline: no_key" in capsys.readouterr().out


# ---------------------------------------------------------------- split runs and --merge


def test_only_en_and_ar_select_each_half(first_night, monkeypatch, fake_clock, tmp_path) -> None:
    from evalset_scripts import SCRIPTS

    english = ["E01", "E04", "E05", "E07", "E09"]
    _install(monkeypatch, fake_clock, [s for q in english for s in SCRIPTS[q]])
    assert main(["eval-assistant", "--out", str(tmp_path / "en"), "--only", "en"]) == 0
    data = json.loads(next((tmp_path / "en").glob("*.json")).read_text(encoding="utf-8"))
    assert [r["id"] for r in data["results"]] == english
    assert data["not_run"] == ["A02", "A03", "A06", "A08", "A10"]
    report = next((tmp_path / "en").glob("*.md")).read_text(encoding="utf-8")
    assert "Partial run: 5 of 10 questions" in report
    arabic = ["A02", "A03", "A06", "A08", "A10"]
    _install(monkeypatch, fake_clock, [s for q in arabic for s in SCRIPTS[q]])
    assert main(["eval-assistant", "--out", str(tmp_path / "ar"), "--only", "ar"]) == 0
    data = json.loads(next((tmp_path / "ar").glob("*.json")).read_text(encoding="utf-8"))
    assert [r["id"] for r in data["results"]] == arabic


def test_an_unknown_question_id_is_refused(
    first_night, monkeypatch, fake_clock, tmp_path, capsys
) -> None:
    _install(monkeypatch, fake_clock, [])
    assert main(["eval-assistant", "--out", str(tmp_path), "--only", "E01,E02,E03"]) == 2
    out = capsys.readouterr().out
    assert "unknown question IDs: E02, E03" in out and "E01, A02, A03" in out
    assert not tmp_path.exists() or list(tmp_path.iterdir()) == []


def test_a_429_stops_the_run(first_night, monkeypatch, fake_clock, tmp_path, capsys) -> None:
    from evalset_scripts import SCRIPTS
    from scripted_model import Fail

    _install(monkeypatch, fake_clock, [*SCRIPTS["E01"], Fail("rate_limited")])
    assert main(["eval-assistant", "--out", str(tmp_path), "--only", "en"]) == 0
    data = json.loads(next(tmp_path.glob("*.json")).read_text(encoding="utf-8"))
    assert [r["id"] for r in data["results"]] == ["E01", "E04"]
    assert data["stopped"] == "rate_limited"
    assert data["not_run"] == ["A02", "A03", "E05", "A06", "E07", "A08", "E09", "A10"]  # set order
    assert "stopped: rate_limited" in capsys.readouterr().out
    report = next(tmp_path.glob("*.md")).read_text(encoding="utf-8")
    assert "Stopped after a 429 (rate_limited)" in report


def _partial(monkeypatch, fake_clock, folder, ids, when):
    from evalset_scripts import SCRIPTS

    _install(monkeypatch, fake_clock, [s for q in ids for s in SCRIPTS[q]])
    with time_machine.travel(when, tick=False):
        assert main(["eval-assistant", "--out", str(folder), "--only", ",".join(ids)]) == 0
    return next(folder.glob("*.json"))


def test_merge_combines_dated_parts(first_night, monkeypatch, fake_clock, tmp_path, capsys) -> None:
    english = _partial(
        monkeypatch, fake_clock, tmp_path / "day1", ["E01", "E04", "E05", "E07", "E09"], FROZEN
    )
    later = datetime(2026, 11, 26, 8, 0, tzinfo=UTC)
    arabic = _partial(
        monkeypatch, fake_clock, tmp_path / "day2", ["A02", "A03", "A06", "A08", "A10"], later
    )
    out = tmp_path / "merged"
    with time_machine.travel(later, tick=False):
        assert (
            main(["eval-assistant", "--out", str(out), "--merge", str(english), str(arabic)]) == 0
        )
    md = out / "2026-11-26T0800Z-gemini-3.6-flash-merged.md"
    data = json.loads(md.with_suffix(".json").read_text(encoding="utf-8"))
    assert [r["id"] for r in data["results"]] == [
        "E01",
        "A02",
        "A03",
        "E04",
        "E05",
        "A06",
        "E07",
        "A08",
        "E09",
        "A10",
    ]
    assert data["passed"] == 10 and data["grounded"] == 10 and data["not_run"] == []
    assert data["parts"] == [english.name, arabic.name]
    report = md.read_text(encoding="utf-8")
    assert "Merged from 2 parts" in report and english.name in report and arabic.name in report
    assert "| 10 / 10 | 10 / 10 |" in report
    assert "merged 2 parts" in capsys.readouterr().out


def test_merge_keeps_the_newest_answer_and_lists_what_is_missing(
    first_night, monkeypatch, fake_clock, tmp_path
) -> None:
    first = _partial(monkeypatch, fake_clock, tmp_path / "a", ["E01", "E04"], FROZEN)
    second = _partial(
        monkeypatch, fake_clock, tmp_path / "b", ["E04"], datetime(2026, 11, 26, 8, 0, tzinfo=UTC)
    )
    assert (
        main(["eval-assistant", "--out", str(tmp_path / "m"), "--merge", str(first), str(second)])
        == 0
    )
    data = json.loads(next((tmp_path / "m").glob("*.json")).read_text(encoding="utf-8"))
    assert [r["id"] for r in data["results"]] == ["E01", "E04"]
    assert data["results"][1]["date"].startswith("2026-11-26")
    assert data["not_run"] == ["A02", "A03", "E05", "A06", "E07", "A08", "E09", "A10"]


def test_merge_refuses_parts_of_different_models(
    first_night, monkeypatch, fake_clock, tmp_path, capsys
) -> None:
    from evalset_scripts import SCRIPTS

    one = _partial(monkeypatch, fake_clock, tmp_path / "a", ["E01"], FROZEN)
    _install(monkeypatch, fake_clock, SCRIPTS["E04"], model_id="gemini-3.5-flash-lite")
    assert main(["eval-assistant", "--out", str(tmp_path / "b"), "--only", "E04"]) == 0
    two = next((tmp_path / "b").glob("*.json"))
    assert (
        main(["eval-assistant", "--out", str(tmp_path / "m"), "--merge", str(one), str(two)]) == 2
    )
    assert "different models" in capsys.readouterr().out
