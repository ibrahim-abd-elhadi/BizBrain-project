from fastapi import APIRouter, Depends
from sqlalchemy import select

from erp.api.deps import require_manager
from erp.db import SessionDep
from erp.errors import ErpError
from erp.models import ManagerAccount
from erp.schemas.auth import LoginRequest, Me, TokenResponse
from erp.security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])

# Verified against when the username is unknown, so both failures cost the same.
_DUMMY_HASH = hash_password("not-a-real-password")


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, session: SessionDep) -> TokenResponse:
    account = session.scalar(select(ManagerAccount))
    if account is not None and account.username == body.username:
        ok = verify_password(account.password_hash, body.password)
    else:
        verify_password(_DUMMY_HASH, body.password)
        ok = False
    if not ok:
        raise ErpError(401, "INVALID_CREDENTIALS", "Wrong username or password")
    token, expires_at = create_access_token(body.username)
    return TokenResponse(access_token=token, expires_at=expires_at)


@router.get("/me", response_model=Me)
def me(username: str = Depends(require_manager)) -> Me:
    return Me(username=username)
