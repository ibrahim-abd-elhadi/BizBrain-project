"""GET /api/v1/brain/explanations/{recommendation_id}?language=en|ar: Why? for one
recommendation (feature 005, research R-09; FR-013 to FR-014a).

A GET: repeating it returns the same text. The only write is filling the kept-explanation cache
once (brain_api has INSERT, no UPDATE, on `explanation`). The model being unreachable is not an
error: the plain version (the template) comes back with source "template".
"""

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends

from brain.api.auth import require_manager
from brain.api.errors import BrainError
from brain.assistant import model as llm
from brain.assistant.explain import NotFound, get_explanation
from brain.config import get_settings
from brain.db import SessionDep

router = APIRouter(prefix="/api/v1/brain", dependencies=[Depends(require_manager)])


@router.get("/explanations/{recommendation_id}")
def explain(
    recommendation_id: uuid.UUID, language: Literal["en", "ar"], session: SessionDep
) -> dict[str, Any]:
    try:
        product_id, source, text = get_explanation(
            session, recommendation_id, language, llm.model_from_settings(), get_settings()
        )
    except NotFound:
        raise BrainError(404, "NOT_FOUND", "No such recommendation") from None
    return {
        "synthetic": True,
        "recommendation_id": str(recommendation_id),
        "product_id": product_id,
        "language": language,
        "source": source,
        "text": text,
    }
