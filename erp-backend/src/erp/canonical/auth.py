"""Service-token access to the Canonical API (FR-007, FR-008, research R-02).

Every Canonical route takes one of these as its first dependency, so 401 and 403 always come
before any 422: nothing is read on a refusal. Nothing here touches the database, and the token
never appears in a message or a log.
"""

from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from erp.canonical.errors import CanonicalError
from erp.security import SCOPE_CREATE_DRAFT, SCOPE_READ, InvalidToken, decode_service_token

_bearer = HTTPBearer(auto_error=False)


def require_scope(scope: str):  # returns a FastAPI dependency
    def dependency(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    ) -> frozenset[str]:
        unauthorized = CanonicalError(
            401,
            "UNAUTHORIZED",
            "A valid service token is required",
            headers={"WWW-Authenticate": "Bearer"},
        )
        if credentials is None:
            raise unauthorized
        try:
            scopes = decode_service_token(credentials.credentials)
        except InvalidToken:
            raise unauthorized from None
        if scope not in scopes:
            raise CanonicalError(403, "FORBIDDEN", f"The service token lacks the scope {scope}")
        return scopes

    return dependency


ReadAccess = Depends(require_scope(SCOPE_READ))
CreateDraftAccess = Depends(require_scope(SCOPE_CREATE_DRAFT))
