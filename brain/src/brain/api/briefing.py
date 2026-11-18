"""GET /api/v1/brain/briefing: the briefing of the newest succeeded end-of-day run (feature 005,
data-model.md read rule; FR-010, FR-011).

- no succeeded run, or a run that wrote no briefing (it found no data): state "none";
- that night's briefing wasn't written (model unreachable, or not grounded): state "offline", and
  never an older night's text or a template;
- otherwise state "written" with both texts.
"""

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select

from brain.api.auth import require_manager
from brain.db import SessionDep
from brain.models import Briefing, JobRun

router = APIRouter(prefix="/api/v1/brain", dependencies=[Depends(require_manager)])


@router.get("/briefing")
def get_briefing(session: SessionDep) -> dict[str, Any]:
    empty = {"night": None, "run_finished_at": None, "text_en": None, "text_ar": None}
    run = session.scalars(
        select(JobRun)
        .where(JobRun.job == "end-of-day", JobRun.status == "succeeded")
        .order_by(JobRun.finished_at.desc(), JobRun.id.desc())
        .limit(1)
    ).first()
    briefing = (
        session.scalars(select(Briefing).where(Briefing.job_run_id == run.id)).first()
        if run is not None
        else None
    )
    if briefing is None:
        return {"synthetic": True, "state": "none", **empty}
    written = briefing.status == "written"
    return {
        "synthetic": True,
        "state": "written" if written else "offline",
        "night": briefing.night.isoformat(),
        "run_finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "text_en": briefing.text_en if written else None,
        "text_ar": briefing.text_ar if written else None,
    }
