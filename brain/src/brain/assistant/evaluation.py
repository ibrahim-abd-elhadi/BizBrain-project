"""Running the evaluation set and writing its report (FR-023; contracts/assistant/evaluation-set.md).

`run_evaluation` runs every question through the real chat graph, inside one transaction that is
rolled back at the end, so A08's proposal never stays. Every question is checked for grounding,
language, required tools and side effects (no ERP POST at all; a proposal only for A08), then its
own checks. `brain-worker eval-assistant` writes the result as a dated Markdown report (and JSON):
a report for the presentation, not a test that fails the build. It holds questions, replies and
checks only: no key, no token, no prompt text.
"""

import json
import statistics
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from brain.assistant.evalset import QUESTIONS, Run
from brain.assistant.graph import run_turn
from brain.assistant.language import is_language
from brain.assistant.model import LanguageModel
from brain.canonical.client import CanonicalClient
from brain.config import Settings
from brain.models import Proposal, ProposalLiveProduct

LIVE_P003_WARNING = "P003 already has a live proposal; A08 checks the pending link instead"


@dataclass
class QuestionResult:
    id: str
    language: str
    turns: list[str]
    replies: list[str | None]
    outcomes: list[str]
    tools: list[str]
    attempts: list[int]
    unsupported: list[list[str]]
    offline_reasons: list[str]
    checks: list[tuple[str, bool, str]] = field(default_factory=list)
    seconds: float = 0.0
    date: str = ""  # when this question ran (UTC), so merged parts keep each answer's date

    @property
    def passed(self) -> bool:
        return all(ok for _, ok, _ in self.checks)

    @property
    def grounded(self) -> bool:
        return all(o == "answered" for o in self.outcomes)


@dataclass
class EvalRun:
    model_id: str
    night: str | None
    live_p003: str | None
    results: list[QuestionResult]
    started_at: datetime
    stopped: str | None = None  # "rate_limited" when a 429 stopped the run
    parts: list[str] = field(default_factory=list)  # the partial reports a merge combined

    @property
    def not_run(self) -> list[str]:
        done = {r.id for r in self.results}
        return [q.id for q in QUESTIONS if q.id not in done]

    @property
    def passed(self) -> int:
        return sum(r.passed for r in self.results)

    @property
    def grounded(self) -> int:
        return sum(r.grounded for r in self.results)

    @property
    def total_seconds(self) -> float:
        return sum(r.seconds for r in self.results)


@contextmanager
def _counting_posts() -> Iterator[list[str]]:
    """Every draft-PO POST attempted during the run (there must be none)."""
    calls: list[str] = []
    real = CanonicalClient.create_draft_purchase_order

    def counting(self: CanonicalClient, key: Any, body: bytes) -> Any:
        calls.append(str(key))
        return real(self, key, body)

    CanonicalClient.create_draft_purchase_order = counting  # type: ignore[method-assign]
    try:
        yield calls
    finally:
        CanonicalClient.create_draft_purchase_order = real  # type: ignore[method-assign]


def live_p003(session: Session) -> str | None:
    found = session.scalar(
        select(ProposalLiveProduct.proposal_id).where(ProposalLiveProduct.product_id == "P003")
    )
    return str(found) if found else None


def _approved(session: Session) -> int:
    return session.scalar(
        select(func.count()).select_from(Proposal).where(Proposal.approved_at.is_not(None))
    )


def _proposals(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(Proposal))


def run_evaluation(
    session: Session,
    model: LanguageModel,
    settings: Settings,
    only: list[str] | None = None,
    night: str | None = None,
    now: datetime | None = None,
) -> EvalRun:
    from brain.clock import now_utc

    started_at = now or now_utc()
    live = live_p003(session)
    results: list[QuestionResult] = []
    stopped: str | None = None
    with _counting_posts() as posts:
        try:
            for question in QUESTIONS:
                if only and question.id not in only:
                    continue
                if stopped:
                    break  # a 429: the free quota is spent, the rest waits for another day
                approved_before, proposals_before = _approved(session), _proposals(session)
                history: list[dict[str, Any]] = []
                turns = []
                clock_start = time.perf_counter()
                for text in question.turns:
                    history.append({"role": "manager", "text": text})
                    turn = run_turn(session, list(history), model, settings)
                    turns.append(turn)
                    if turn.reply is not None:
                        history.append(
                            {"role": "assistant", "text": turn.reply, "language": turn.language}
                        )
                seconds = time.perf_counter() - clock_start
                session.flush()
                replies = [t.reply for t in turns]
                tools = [f["name"] for t in turns for f in t.facts]
                result = QuestionResult(
                    id=question.id,
                    language=question.language,
                    turns=list(question.turns),
                    replies=replies,
                    outcomes=[t.outcome for t in turns],
                    tools=tools,
                    attempts=[t.attempts for t in turns],
                    unsupported=[t.unsupported for t in turns],
                    offline_reasons=[t.offline_reason for t in turns if t.offline_reason],
                    seconds=round(seconds, 2),
                    date=now_utc().isoformat(),
                )
                if "rate_limited" in result.offline_reasons:
                    stopped = "rate_limited"
                created = _proposals(session) - proposals_before
                result.checks = [
                    ("grounded", result.grounded, ", ".join(result.outcomes)),
                    (
                        "language",
                        all(
                            t.language == question.language
                            and (t.reply is None or is_language(t.reply, question.language))
                            for t in turns
                        ),
                        question.language,
                    ),
                    (
                        "tools called",
                        all(name in tools for name in question.required_tools),
                        ", ".join(question.required_tools) or "none required",
                    ),
                    (
                        "side effects",
                        len(posts) == 0
                        and created == (1 if question.creates_proposal and not live else 0),
                        f"{created} proposal(s), {len(posts)} ERP POST(s)",
                    ),
                ]
                if all(r is not None for r in replies):
                    run = Run(
                        session=session,
                        replies=[r or "" for r in replies],
                        results=turns,
                        live_p003=live,
                        approved_before=approved_before,
                    )
                    result.checks += question.checks(run)
                results.append(result)
        finally:
            session.rollback()  # A08's proposal never stays
    return EvalRun(
        model_id=getattr(model, "model_id", settings.gemini_model),
        night=night,
        live_p003=live,
        results=results,
        started_at=started_at,
        stopped=stopped,
    )


# ---------------------------------------------------------------- the report


def _block(text: str | None, language: str) -> str:
    if text is None:
        return "_(no reply: Assistant offline)_"
    if language == "ar":
        return f'<div dir="rtl" lang="ar">\n\n{text}\n\n</div>'
    return "\n".join(f"> {line}" for line in text.splitlines() or [""])


def markdown(run: EvalRun) -> str:
    seconds = [r.seconds for r in run.results]
    slowest = max(run.results, key=lambda r: r.seconds) if run.results else None
    reasons = sorted({reason for r in run.results for reason in r.offline_reasons})
    lines = [
        f"# Assistant evaluation: {run.model_id}",
        "",
        f"- **Date (UTC):** {run.started_at:%Y-%m-%d %H:%M}",
        f"- **Model:** `{run.model_id}`",
        f"- **Night of the results:** {run.night or 'unknown'}",
        "- **All data is synthetic.**",
    ]
    if run.live_p003:
        lines.append(f"- **Warning:** {LIVE_P003_WARNING}.")
    if run.parts:
        lines.append(f"- **Merged from {len(run.parts)} parts:** {', '.join(run.parts)}")
    if run.stopped:
        lines.append(f"- **Stopped after a 429 ({run.stopped}):** the rest waits for another day.")
    if run.not_run:
        lines.append(
            f"- **Partial run: {len(run.results)} of {len(QUESTIONS)} questions.** "
            f"Not run: {', '.join(run.not_run)}."
        )
    lines += [
        "",
        "## Summary",
        "",
        "| Passed | Grounded | Total time | Median | Slowest | Offline reasons |",
        "|---|---|---|---|---|---|",
        (
            f"| {run.passed} / {len(run.results)} | {run.grounded} / {len(run.results)} "
            f"| {run.total_seconds:.1f} s | {statistics.median(seconds) if seconds else 0:.1f} s "
            f"| {slowest.id + f' ({slowest.seconds:.1f} s)' if slowest else '-'} "
            f"| {', '.join(reasons) or 'none'} |"
        ),
        "",
    ]
    for r in run.results:
        lines += [f"## {r.id} ({r.language}): {'✅ passed' if r.passed else '❌ failed'}", ""]
        for n, (turn, reply) in enumerate(zip(r.turns, r.replies, strict=False), start=1):
            lines += [
                f"**Question{f' (turn {n})' if len(r.turns) > 1 else ''}:**",
                "",
                _block(turn, r.language),
                "",
            ]
            lines += ["**Reply:**", "", _block(reply, r.language), ""]
        lines += [
            f"- Tools called: {', '.join(r.tools) or 'none'}",
            f"- Grounding checks: {', '.join(str(a) for a in r.attempts)}"
            + (
                f"; unsupported: {', '.join(v for u in r.unsupported for v in u)}"
                if any(r.unsupported)
                else ""
            ),
            f"- Time: {r.seconds:.2f} s",
            "",
            "| Check | Result | Detail |",
            "|---|---|---|",
        ]
        lines += [
            f"| {name} | {'✅' if ok else '❌'} | {detail} |" for name, ok, detail in r.checks
        ]
        lines.append("")
    return "\n".join(lines)


def write_report(run: EvalRun, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{run.started_at:%Y-%m-%dT%H%MZ}-{run.model_id.replace('/', '_')}"
    if run.parts:
        stem += "-merged"
    md, js = out_dir / f"{stem}.md", out_dir / f"{stem}.json"
    md.write_text(markdown(run), encoding="utf-8", newline="\n")
    payload = {
        "synthetic": True,
        "model_id": run.model_id,
        "date": run.started_at.isoformat(),
        "night": run.night,
        "warning": LIVE_P003_WARNING if run.live_p003 else None,
        "passed": run.passed,
        "grounded": run.grounded,
        "questions": len(run.results),
        "total_seconds": round(run.total_seconds, 2),
        "stopped": run.stopped,
        "not_run": run.not_run,
        "parts": run.parts,
        "results": [{**asdict(r), "passed": r.passed, "grounded": r.grounded} for r in run.results],
    }
    js.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    return md, js


def expand_only(only: list[str] | None) -> list[str] | None:
    """`en` and `ar` stand for the five questions of that language; IDs must exist."""
    if not only:
        return None
    wanted: list[str] = []
    for item in only:
        if item in ("en", "ar"):
            wanted += [q.id for q in QUESTIONS if q.language == item]
        else:
            wanted.append(item)
    unknown = [q for q in wanted if q not in {x.id for x in QUESTIONS}]
    if unknown:
        raise ValueError(
            f"unknown question IDs: {', '.join(unknown)} "
            f"(the set: {', '.join(q.id for q in QUESTIONS)}; or en, ar)"
        )
    return wanted


def _result(data: dict[str, Any]) -> QuestionResult:
    fields = {k: data[k] for k in QuestionResult.__dataclass_fields__ if k in data}
    fields["checks"] = [tuple(c) for c in data.get("checks", [])]
    return QuestionResult(**fields)


def merge(paths: list[str], out: str) -> int:
    """Combine dated partial reports (their .json files) into one report. A question answered in
    several parts keeps its newest answer; the questions no part ran are listed."""
    from brain.clock import now_utc

    parts = [(Path(p), json.loads(Path(p).read_text(encoding="utf-8"))) for p in paths]
    models = sorted({data["model_id"] for _, data in parts})
    if len(models) != 1:
        print(f"cannot merge reports of different models: {', '.join(models)}", flush=True)
        return 2
    by_id: dict[str, QuestionResult] = {}
    for _, data in sorted(parts, key=lambda part: part[1]["date"]):
        for item in data["results"]:
            by_id[item["id"]] = _result({**item, "date": item.get("date") or data["date"]})
    nights = sorted({data.get("night") for _, data in parts if data.get("night")})
    run = EvalRun(
        model_id=models[0],
        night=", ".join(nights) or None,
        live_p003=None,
        results=[by_id[q.id] for q in QUESTIONS if q.id in by_id],
        started_at=now_utc(),
        parts=[path.name for path, _ in parts],
    )
    md, _ = write_report(run, Path(out))
    print(
        f"eval-assistant merged {len(parts)} parts model={run.model_id} "
        f"passed={run.passed}/{len(run.results)} grounded={run.grounded}/{len(run.results)} "
        f"not_run={','.join(run.not_run) or 'none'} report={md}",
        flush=True,
    )
    return 0


def main(out: str, only: list[str] | None, merge_paths: list[str] | None = None) -> int:
    """`brain-worker eval-assistant`: exit 0 when the report was written (even with failed
    questions or a stop after a 429), 2 when the preconditions fail, 1 on an unexpected error."""
    if merge_paths:
        return merge(merge_paths, out)
    try:
        only = expand_only(only)
    except ValueError as exc:
        print(str(exc), flush=True)
        return 2
    from brain.api.risk import risk_rows
    from brain.assistant import model as llm
    from brain.assistant.model import ModelUnavailable
    from brain.config import get_settings
    from brain.db import worker_session
    from brain.models import JobRun

    settings = get_settings()
    with worker_session() as session:
        last = session.scalars(
            select(JobRun)
            .where(JobRun.job == "end-of-day", JobRun.status == "succeeded")
            .order_by(JobRun.id.desc())
            .limit(1)
        ).first()
        if last is None or not risk_rows(session):
            print("no end-of-day results; run brain-worker run end-of-day first", flush=True)
            return 2
        night = (last.summary or {}).get("final_cut") or last.business_date.isoformat()
    model = llm.model_from_settings()
    try:
        model.probe(settings.availability_probe_timeout_seconds)
    except ModelUnavailable as exc:
        print(f"assistant offline: {exc.reason}", flush=True)
        return 2
    with worker_session() as session:
        run = run_evaluation(session, model, settings, only=only, night=night)
    md, _ = write_report(run, Path(out))
    print(
        f"eval-assistant model={run.model_id} passed={run.passed}/{len(run.results)} "
        f"grounded={run.grounded}/{len(run.results)} total={run.total_seconds:.1f}s "
        + (f"stopped: {run.stopped} " if run.stopped else "")
        + f"report={md}",
        flush=True,
    )
    return 0
