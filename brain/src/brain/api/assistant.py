"""The Assistant screen's two operations (feature 005; contracts/brain-api-assistant.openapi.yaml).

- GET /assistant: whether the language model answers now (research R-06). Only an "available"
  answer is cached, so "Check again" always re-checks.
- POST /assistant/messages: one chat turn over the open conversation the browser sends; nothing
  of it is stored (FR-021). The model being unreachable is reported in the body (outcome
  "offline"), not as an HTTP error. The session commits once, at the end of the turn, so a
  proposal the turn created is kept even when the model fails afterwards.
"""

from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from brain.api.auth import require_manager
from brain.api.errors import BrainError
from brain.assistant import availability
from brain.assistant import model as llm
from brain.assistant.graph import run_turn
from brain.config import get_settings
from brain.db import SessionDep

router = APIRouter(prefix="/api/v1/brain", dependencies=[Depends(require_manager)])


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["manager", "assistant"]
    text: str
    language: Literal["en", "ar"] | None = None


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    messages: list[ChatMessage]


def _invalid(detail: str) -> BrainError:
    return BrainError(422, "VALIDATION_ERROR", detail)


@router.get("/assistant")
def get_availability(recheck: bool = False) -> dict[str, Any]:
    """`recheck=true` ("Check again") always probes; otherwise a real 429 or 5xx in the last
    30 s answers offline at once (research R-06)."""
    available, reason = availability.probe(llm.model_from_settings(), recheck=recheck)
    return {"synthetic": True, "available": available, "reason": reason}


@router.post("/assistant/messages")
def send_message(body: ChatRequest, session: SessionDep) -> dict[str, Any]:
    settings = get_settings()
    messages = body.messages
    if not 1 <= len(messages) <= settings.chat_max_messages:
        raise _invalid(f"messages: between 1 and {settings.chat_max_messages} are allowed")
    for n, message in enumerate(messages, start=1):
        if not 1 <= len(message.text) <= settings.chat_max_message_chars:
            raise _invalid(f"messages[{n}].text: 1 to {settings.chat_max_message_chars} characters")
    if messages[-1].role != "manager":
        raise _invalid("messages: the last message must be the manager's")
    try:
        result = run_turn(
            session,
            [m.model_dump() for m in messages],
            llm.model_from_settings(),
            settings,
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    return {
        "synthetic": True,
        "outcome": result.outcome,
        "offline_reason": result.offline_reason,
        "reply": {"text": result.reply, "language": result.language}
        if result.reply is not None
        else None,
        "proposal": result.proposal,
        "refusal": result.refusal,
    }
