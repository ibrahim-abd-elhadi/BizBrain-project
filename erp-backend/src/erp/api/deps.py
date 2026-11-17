from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from erp.db import SessionDep
from erp.errors import ErpError
from erp.models import ManagerAccount
from erp.security import InvalidToken, decode_access_token

_bearer = HTTPBearer(auto_error=False)


def require_manager(
    session: SessionDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> str:
    """Every ERP screen and action needs a signed-in manager (FR-002)."""
    unauthenticated = ErpError(401, "UNAUTHENTICATED", "Sign in required")
    if credentials is None:
        raise unauthenticated
    try:
        username = decode_access_token(credentials.credentials)
    except InvalidToken:
        raise unauthenticated from None
    registered = session.scalar(select(ManagerAccount.username))
    if registered is None or registered != username:
        raise unauthenticated
    return username
